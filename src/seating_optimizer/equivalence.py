"""External test-230 old-vs-new equivalence gate.

Usage:
    python -m seating_optimizer.equivalence --corpus-dir /path/to/coordinator

The coordinator owns this corpus; no fixtures are committed or fabricated.
An optional equivalence-cases.json in the supplied directory may provide
exact case inputs (CSV/JSON paths, manual instructions, enabled rule IDs).
Without a manifest the harness mirrors the coordinator's run_rerun.py:
run3 and every demonstration use guests-216-split.csv; run3 keeps M3 ON.

Reference scores (2260 and -1997596) are historical QA snapshots, not
5-second equality gates. Instead, compare the two engines' objectives,
hard verdicts and plan shape under matching settings. For timed feasible
incumbents, optionally set --score-tolerance N to declare and display
the maximum accepted search-noise delta; default 0 means strict equality.

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
from .generic_evaluator import score_fixed_plan
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
    time_limit_seconds: float = 5.0
    allow_d1_difference: bool = False
    legacy_seated: int | None = None
    generic_seated: int | None = None
    mark_count: int | None = None
    legacy_pending: int | None = None
    generic_pending: int | None = None
    unseated_group_id: str | None = None


DEFAULT_CASES = [
    Case("run1-full-overcapacity", "test-230/guests-230.csv", "infeasible",
         seated=0, short_by=14),
    Case("run2-hard-conflict", "test-230/guests-216-control.csv", "infeasible",
         conflict="clan-upper-floor"),
    # The original run3 uses the 36-person clan SPLIT CSV with M3 enabled.
    # 2260 is a 5-second QA-machine reference, not a deterministic optimum.
    Case("run3-feasible", "test-230/guests-216-split.csv", "feasible",
         seated=216, score=2260, breakdown={"hebrew-grouping": 2260}),
    # The original split demonstration ran at 15s (unless CLI overrides).
    Case("demo-split", "test-230/guests-216-split.csv", "feasible",
         score=-1997596, enabled=["split-penalty"], time_limit_seconds=15),
    Case("demo-low-priority", "test-230/guests-216-split.csv", "needs_review",
         enabled=["low-priority-small-families"], allow_d1_difference=True,
         legacy_seated=189, generic_seated=205, mark_count=16,
         legacy_pending=16, generic_pending=6),
    Case("demo-direct-mark", "test-230/guests-216-split.csv", "feasible",
         seated=216, enabled=["low-priority-single-guest"]),
    Case("manual-unseat", "test-230/guests-216-split.csv", "feasible",
         seated=206, unseated_group_id="registration:5",
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


def _expected(case: Case, plan, *, engine: str):
    status = plan.status
    if case.expected_status == "feasible":
        assert status in ("feasible", "optimal"), (case.name, status, plan.message)
    else:
        assert status == case.expected_status, (case.name, status, plan.message)
    # Case.score and Case.breakdown retain historical QA reference values;
    # timed CP-SAT optimization is not guaranteed to reproduce them exactly.
    expected_seated = (
        case.generic_seated if engine == "generic" and case.generic_seated is not None
        else case.legacy_seated if engine == "legacy" and case.legacy_seated is not None
        else case.seated
    )
    if expected_seated is not None:
        count = sum(len(a.guest_ids) for a in plan.assignments)
        assert count == expected_seated, (case.name, engine, count, expected_seated)
    if case.mark_count is not None:
        assert len(plan.priority_marks) == case.mark_count, (
            case.name, engine, "priority marks", len(plan.priority_marks), case.mark_count
        )
    pending = case.generic_pending if engine == "generic" else case.legacy_pending
    if pending is not None:
        assert len(plan.pending_groups) == pending, (
            case.name, engine, "pending", len(plan.pending_groups), pending
        )
    if case.unseated_group_id:
        assert [x.group_id for x in plan.not_seated] == [case.unseated_group_id], (
            case.name, engine, "operator unseat", plan.not_seated
        )
    else:
        assert not plan.not_seated, (case.name, engine, "unexpected automatic unseat")
    if case.short_by is not None:
        assert f"short by {case.short_by}" in (plan.message + " " + " ".join(plan.conflicting_constraints))
    if case.conflict is not None:
        assert any(case.conflict in conflict for conflict in plan.conflicting_constraints), (
            case.name, plan.conflicting_constraints)
    if case.breakdown:
        actual = {x.rule_id: x.points for x in plan.score_breakdown}
        assert set(actual) == set(case.breakdown), (
            case.name, engine, "unexpected breakdown instances", actual
        )
    if plan.status in ("optimal", "feasible", "needs_review"):
        assert plan.total_score == sum(x.points for x in plan.score_breakdown), (
            case.name, engine, "unattributed objective points", plan.total_score
        )


def _placement(plan):
    return {g: a.table_id for a in plan.assignments for g in a.guest_ids}


def _assert_same_objective_on_fixed_plan(case, engine, plan, generic_problem):
    """Avoid confusing different timed incumbents with different objectives.

    The reference solver's own reported objective must equal the generic
    scoring formula applied to that SAME fixed seating arrangement. This
    catches missing family-internal pairs independently of CP-SAT search.
    """
    if plan.status not in ("optimal", "feasible", "needs_review"):
        return
    guest_tables = _placement(plan)
    calculated, breakdown = score_fixed_plan(
        generic_problem.guests, generic_problem.tables,
        guest_tables, generic_problem.rules
    )
    assert plan.total_score == calculated, (
        case.name, engine, "fixed-plan objective mismatch",
        plan.total_score, calculated, breakdown
    )
    reported = {r.rule_id: r.points for r in plan.score_breakdown}
    assert reported == breakdown, (
        case.name, engine, "fixed-plan instance breakdown mismatch",
        reported, breakdown
    )


def _compare(case: Case, legacy, generic, *, score_tolerance=0):
    assert legacy.status == generic.status or (
        case.expected_status == "feasible" and
        legacy.status in ("optimal", "feasible") and generic.status in ("optimal", "feasible")
    ), (case.name, legacy.status, generic.status)
    l_count = sum(len(a.guest_ids) for a in legacy.assignments)
    g_count = sum(len(a.guest_ids) for a in generic.assignments)
    if case.allow_d1_difference:
        # Binding D1: the newer engine admits candidates per-family, so
        # legacy's all-or-nothing grade result must NOT be forced onto v2.
        assert legacy.status == generic.status == "needs_review"
        assert not legacy.not_seated and not generic.not_seated
        assert g_count >= l_count, (case.name, l_count, g_count)
        assert not set(_placement(legacy)) - set(_placement(generic)), (
            case.name, "generic dropped a previously seated guest"
        )
        return None
    if legacy.total_score is not None and generic.total_score is not None:
        delta = generic.total_score - legacy.total_score
        assert abs(delta) <= score_tolerance, (
            case.name, "objective delta exceeds search-noise tolerance",
            legacy.total_score, generic.total_score, delta, score_tolerance
        )
    else:
        delta = None
    assert l_count == g_count, (case.name, l_count, g_count)
    if l_count and g_count:
        assert set(_placement(legacy)) == set(_placement(generic))
        # Different optimal plans may tie; exact portions are not a gate.
    return delta


def _case_problem(root, case, config, inventory, mapping, *, seed=42,
                  time_limit=None, workers=8):
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
        config=SolverConfig(time_limit_seconds=(
            time_limit if time_limit is not None else case.time_limit_seconds
        ), random_seed=seed, workers=workers),
    )


def _load_cases(root: Path):
    manifest = root / "equivalence-cases.json"
    if not manifest.is_file():
        return DEFAULT_CASES, None
    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    cases = [Case(**c) for c in data["cases"]]
    mapping = data.get("mapping")
    return cases, mapping


def corpus_gate(root: Path, *, strict_placement=False, time_limit=None,
                workers=8, score_tolerance=0, seed=42):
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
        legacy_problem = _case_problem(
            root, case, config, inventory, mapping, seed=seed,
            time_limit=time_limit, workers=workers
        )
        generic_problem = GenericProblem.from_v1(legacy_problem)
        old = solve_legacy(legacy_problem)
        new = solve_generic(generic_problem)
        _expected(case, old, engine="legacy")
        _expected(case, new, engine="generic")
        _assert_same_objective_on_fixed_plan(case, "legacy", old, generic_problem)
        _assert_same_objective_on_fixed_plan(case, "generic", new, generic_problem)
        delta = _compare(case, old, new, score_tolerance=score_tolerance)
        if strict_placement and old.status in ("optimal", "feasible"):
            assert _placement(old) == _placement(new), case.name
        passes += 1
        print(f"PASS {case.name}: limit={legacy_problem.config.time_limit_seconds}s "
              f"workers={workers} old={old.status}/{old.total_score} "
              f"generic={new.status}/{new.total_score} delta={delta} "
              f"reference={case.score}", flush=True)
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
    parser.add_argument("--time-limit", type=float, default=None,
                        help="Override per-case limit (default 5s; split demo 15s)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--score-tolerance", type=int, default=0,
                        help="Explicit maximum absolute timed-incumbent delta; 0=strict")
    args = parser.parse_args(argv)
    if args.score_tolerance < 0 or args.workers < 1:
        parser.error("score-tolerance must be >= 0 and workers >= 1")
    small_random_gate(args.random_cases)
    corpus_gate(args.corpus_dir, strict_placement=args.strict_placement,
                time_limit=args.time_limit, workers=args.workers,
                score_tolerance=args.score_tolerance, seed=args.seed)


if __name__ == "__main__":
    main()
