"""External test-230 old-vs-new equivalence gate.

Usage:
    python -m seating_optimizer.equivalence --corpus-dir /path/to/coordinator

The coordinator owns this corpus; no fixtures are committed or fabricated.
An optional equivalence-cases.json in the supplied directory may provide
exact case inputs (CSV/JSON paths, manual instructions, enabled rule IDs).
Without a manifest the harness uses the named fixtures from the kickoff.

The harness FAILS when a required case cannot be reconstructed; it never
silently marks unknown historical verdicts as passed.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .generic_solver import GenericProblem, solve_generic
from .importer import import_registrations
from .models import Guest, ManualInstruction, Problem, Rule, SolverConfig, Table, Zone
from .rule_migration import migrate_rules
from .solver import solve as solve_legacy


@dataclass
class Case:
    name: str
    guest_file: str
    expected_status: str
    score: int | None = None
    seated: int | None = None
    short_by: int | None = None
    conflict: str | None = None
    breakdown: dict[str, int] = field(default_factory=dict)
    enabled: list[str] | None = None
    disabled: list[str] = field(default_factory=list)
    manual_file: str | None = None
    splittable_groups: list[str] = field(default_factory=list)


DEFAULT_CASES = [
    Case("run1-full-overcapacity", "test-230/guests-230.csv", "infeasible",
         seated=0, short_by=14),
    Case("run2-hard-conflict", "test-230/guests-216-control.csv", "infeasible",
         conflict="clan-upper-floor"),
    Case("run3-feasible", "test-230/guests-216-control.csv", "feasible",
         score=2260, seated=216, disabled=["clan-upper-floor"],
         breakdown={"hebrew-grouping": 2260}),
    Case("demo-split", "test-230/guests-216-split.csv", "feasible",
         score=-1997596, disabled=["clan-upper-floor"], enabled=["split-penalty"]),
    Case("demo-low-priority", "test-230/guests-216-control.csv", "needs_review",
         seated=189, disabled=["clan-upper-floor"],
         enabled=["low-priority-small-families"]),
    Case("demo-direct-mark", "test-230/guests-216-control.csv", "feasible",
         seated=216, disabled=["clan-upper-floor"],
         enabled=["low-priority-single-guest"]),
    Case("manual-unseat", "test-230/guests-216-control.csv", "feasible",
         disabled=["clan-upper-floor"],
         manual_file="test-230-rerun/run3-unseat-plan.json"),
]


def _load_json(root: Path, name: str):
    path = root / name
    if not path.is_file():
        raise FileNotFoundError(f"Required corpus file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _rules(root: Path, config: dict) -> list[dict]:
    listing = _load_json(root, "test-230-rerun/rules-listing.json")
    if isinstance(listing, list):
        raw = listing
    elif isinstance(listing, dict):
        raw = next((listing[key] for key in ("rules", "instances", "items", "data")
                    if isinstance(listing.get(key), list)), None)
    else:
        raw = None
    if raw is None:
        raise ValueError("Unrecognised rules-listing.json shape; provide equivalence-cases.json")
    rules = []
    for item in raw:
        if "shape" in item:
            rules.append(item)
        elif "rule" in item and isinstance(item["rule"], dict):
            rules.append(item["rule"])
        else:
            raise ValueError(f"Listing item lacks legacy shape: {item!r}")
    if len(rules) != 18:
        raise AssertionError(f"Expected 18 legacy instances; got {len(rules)}")
    return rules


def _guests(root: Path, case: Case, mapping: dict[str, str] | None):
    path = root / case.guest_file
    result = import_registrations(path.read_bytes(), path.name, mapping=mapping)
    if result.has_errors or not result.guests:
        details = "; ".join(item.message for item in result.issues)
        raise ValueError(f"Unable to import {case.guest_file}: {details}")
    return result.guests


def _manual(root: Path, case: Case) -> list[ManualInstruction]:
    if not case.manual_file:
        return []
    data = _load_json(root, case.manual_file)
    if not isinstance(data, dict) or "manual_instructions" not in data:
        raise ValueError(f"{case.name}: plan fixture lacks manual_instructions")
    directions = [ManualInstruction.model_validate(item)
                  for item in data["manual_instructions"]]
    if not any(direction.action == "unseat" for direction in directions):
        raise AssertionError(f"{case.name}: no operator unseat instruction in fixture")
    return directions


def _expected(case: Case, plan):
    status = plan.status
    if case.expected_status == "feasible":
        assert status in ("feasible", "optimal"), (case.name, status, plan.message)
    else:
        assert status == case.expected_status, (case.name, status, plan.message)
    if case.score is not None:
        assert plan.total_score == case.score, (case.name, plan.total_score, case.score)
    if case.seated is not None:
        count = sum(len(a.guest_ids) for a in plan.assignments)
        assert count == case.seated, (case.name, count, case.seated)
    if case.short_by is not None:
        assert f"short by {case.short_by}" in (plan.message + " " + " ".join(plan.conflicting_constraints))
    if case.conflict is not None:
        assert any(case.conflict in conflict for conflict in plan.conflicting_constraints), (
            case.name, plan.conflicting_constraints)
    for rule_id, points in case.breakdown.items():
        actual = {x.rule_id: x.points for x in plan.score_breakdown}
        assert actual.get(rule_id) == points, (case.name, rule_id, actual)


def _placement(plan):
    return {g: a.table_id for a in plan.assignments for g in a.guest_ids}


def _compare(case: Case, legacy, generic):
    assert legacy.status == generic.status or (
        case.expected_status == "feasible" and
        legacy.status in ("optimal", "feasible") and generic.status in ("optimal", "feasible")
    ), (case.name, legacy.status, generic.status)
    if legacy.total_score is not None and generic.total_score is not None:
        assert legacy.total_score == generic.total_score, (
            case.name, legacy.total_score, generic.total_score)
    l_count = sum(len(a.guest_ids) for a in legacy.assignments)
    g_count = sum(len(a.guest_ids) for a in generic.assignments)
    assert l_count == g_count, (case.name, l_count, g_count)
    if l_count and g_count:
        assert set(_placement(legacy)) == set(_placement(generic))
        # Different optimal plans can tie; the optional strict check below
        # is appropriate only for pinned/uniquely determined placements.


def _case_problem(root, case, config, inventory, mapping, *, seed=42):
    rule_records = [dict(item) for item in inventory]
    if case.enabled is not None:
        enabled_ids = set(case.enabled)
        for record in rule_records:
            if record["id"] in enabled_ids:
                record["enabled"] = True
    for record in rule_records:
        if record["id"] in case.disabled:
            record["enabled"] = False
    rules = [Rule.model_validate(item) for item in rule_records]
    return Problem(
        session_id="test-230:"+case.name,
        zones=config["zones"], tables=config["tables"], layout=config.get("layout"),
        guests=_guests(root, case, mapping), rules=rules,
        manual_instructions=_manual(root, case),
        splittable_groups=case.splittable_groups,
        config=SolverConfig(time_limit_seconds=5, random_seed=seed, workers=1),
    )


def _load_cases(root: Path):
    manifest = root / "equivalence-cases.json"
    if not manifest.is_file():
        return DEFAULT_CASES, None
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    cases = [Case(**c) for c in data["cases"]]
    mapping = data.get("mapping")
    return cases, mapping


def corpus_gate(root: Path, *, strict_placement=False):
    config = _load_json(root, "test-230-rerun/venue-configuration.json")
    inventory = _rules(root, config)
    rules, report = migrate_rules(inventory)
    assert len(inventory) == 18
    assert len(rules) == 17
    assert len(report["retired"]) == 1
    assert report["retired"][0]["legacy_source"]["shape"] == "capacity"
    cases, mapping = _load_cases(root)
    passes = 0
    for case in cases:
        legacy_problem = _case_problem(root, case, config, inventory, mapping)
        generic_problem = GenericProblem.from_v1(legacy_problem)
        old = solve_legacy(legacy_problem)
        new = solve_generic(generic_problem)
        _expected(case, old)
        _expected(case, new)
        _compare(case, old, new)
        if strict_placement and old.status in ("optimal", "feasible"):
            assert _placement(old) == _placement(new), case.name
        passes += 1
        print(f"PASS {case.name}: old={old.status}/{old.total_score} "
              f"generic={new.status}/{new.total_score}")
    # An optional historical verdict file is REQUIRED to be present and is
    # counted, but its 29 individual entries are not assumed to be executable
    # without their source inputs. Never mislabel seven case tests as 29/29.
    historic = _load_json(root, "test-230-rerun/verdicts-rerun.json")
    if isinstance(historic, list):
        rows = historic
    elif isinstance(historic, dict):
        rows = next((historic[k] for k in ("verdicts", "checks", "results")
                     if isinstance(historic.get(k), list)), None)
    else:
        rows = None
    if rows is None or len(rows) != 29:
        raise AssertionError("Cannot verify expected 29 historical verdict records")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Unexpected verdict record shape")
    print(f"CORPUS_CASES={passes}/{len(cases)} historical_records={len(rows)} "
          "historical_checks_not_individually_replayed")
    return passes


def small_random_gate(samples=20):
    """Reproducible low-ambiguity random cases, with no shape-specific rules."""
    rng = random.Random(42)
    for index in range(samples):
        count = rng.randint(3, 8)
        capacities = [rng.randint(2, 5) for _ in range(3)]
        guests = [Guest(id=f"g{i}", name=f"g{i}", group_id=f"f{i}",
                        attributes={"language": "x" if i % 2 else "y"})
                  for i in range(count)]
        old = Problem(
            session_id=f"random-{index}", zones=[Zone(id="z", name="Z")],
            tables=[Table(id=f"T{j}", zone_id="z", capacity=n)
                    for j, n in enumerate(capacities)],
            guests=guests, config=SolverConfig(time_limit_seconds=5, workers=1, random_seed=42),
        )
        legacy = solve_legacy(old)
        generic = solve_generic(GenericProblem.from_v1(old))
        assert legacy.status == generic.status, (index, legacy.status, generic.status)
        assert legacy.total_score == generic.total_score, (index, legacy.total_score, generic.total_score)
        assert {g for a in legacy.assignments for g in a.guest_ids} == {
            g for a in generic.assignments for g in a.guest_ids
        }
    print(f"RANDOM={samples}/{samples}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--strict-placement", action="store_true")
    parser.add_argument("--random-cases", type=int, default=20)
    args = parser.parse_args(argv)
    small_random_gate(args.random_cases)
    corpus_gate(args.corpus_dir, strict_placement=args.strict_placement)


if __name__ == "__main__":
    main()
