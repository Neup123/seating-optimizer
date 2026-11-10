"""Solver-checked concrete reassignment options for manual placement intentions.

Every offered layout is re-solved with *all* original hard constraints, including
unconditional physical capacity. A finite preference may lose points; no hard
rule is disabled or converted to a soft one.
"""
from __future__ import annotations

from itertools import combinations
from collections import defaultdict

from pydantic import Field

from .models import ManualInstruction, Model, Plan, Problem
from .solver import solve, _group_id


class ReassignRequest(Model):
    problem: Problem
    plan: Plan
    instruction: ManualInstruction


class Movement(Model):
    group_id: str
    party_name: str
    before: list[str]
    after: list[str]
    people: int


class ReassignOption(Model):
    id: str
    kind: str
    title: str
    movements: list[Movement]
    score_delta: int
    soft_rule_warnings: list[str]
    plan: Plan


class ReassignResponse(Model):
    status: str
    options: list[ReassignOption] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


def _placements(problem: Problem, plan: Plan) -> dict[str, str]:
    by_guest: dict[str, str] = {}
    for assignment in plan.assignments:
        for guest_id in assignment.guest_ids:
            if guest_id in by_guest:
                raise ValueError(f"Duplicate placement for guest {guest_id}")
            by_guest[guest_id] = assignment.table_id
    if set(by_guest) != {guest.id for guest in problem.guests}:
        raise ValueError("The current plan is missing or has extra guests; re-solve first")
    if set(by_guest.values()) - {table.id for table in problem.tables}:
        raise ValueError("The current plan refers to a missing table; re-solve first")
    if plan.status not in {"feasible", "optimal"} or plan.session_id != problem.session_id:
        raise ValueError("A feasible plan for this session is required")
    return by_guest


def _name(plan: Plan, group: str) -> str:
    for assignment in plan.assignments:
        if assignment.group_id == group:
            return assignment.group_name or (
                assignment.guest_names[0] if len(assignment.guest_names) == 1 else group
            )
    return group


def _effects(problem: Problem, before: dict[str, str], after: dict[str, str], plan: Plan) -> list[Movement]:
    members: dict[str, list[str]] = defaultdict(list)
    for guest in problem.guests:
        members[_group_id(guest)].append(guest.id)
    changes = []
    for group, ids in members.items():
        old = [before[i] for i in ids]
        new = [after[i] for i in ids]
        if old != new:
            changes.append(Movement(group_id=group, party_name=_name(plan, group),
                                    before=sorted(set(old)), after=sorted(set(new)),
                                    people=len(ids)))
    return changes


def _warning_rules(old: Plan, new: Plan, problem: Problem) -> list[str]:
    original = {entry.rule_id: entry.points for entry in old.score_breakdown}
    updated = {entry.rule_id: entry.points for entry in new.score_breakdown}
    named = {rule.id: rule for rule in problem.rules}
    warnings = []
    for rule_id in sorted(original.keys() | updated.keys()):
        delta = updated.get(rule_id, 0) - original.get(rule_id, 0)
        if delta < 0:
            rule = named.get(rule_id)
            desc = (f"{rule.shape}, weight {rule.weight}" if rule else "venue preference")
            warnings.append(f"{rule_id} ({desc}): {abs(delta)} fewer points")
    return warnings


def _describe_split(problem: Problem, placements: dict[str, str], gid: str) -> str:
    counts = defaultdict(int)
    for guest in problem.guests:
        if _group_id(guest) == gid:
            counts[placements[guest.id]] += 1
    total = sum(counts.values())
    return ", ".join(f"{table} ({count}/{total})" for table, count in sorted(counts.items()))


def propose_reassignment(request: ReassignRequest) -> ReassignResponse:
    problem, plan, instruction = request.problem, request.plan, request.instruction
    previous = _placements(problem, plan)
    if plan.manual_instructions != problem.manual_instructions:
        raise ValueError("Stored instructions changed since this plan; re-solve first")
    if instruction.id in {item.id for item in problem.manual_instructions}:
        raise ValueError(f"Instruction ID {instruction.id} already exists")
    members: dict[str, list[str]] = defaultdict(list)
    for guest in problem.guests:
        members[_group_id(guest)].append(guest.id)
    if instruction.group_id not in members:
        raise ValueError(f"Unknown party {instruction.group_id}")
    tables = {table.id: table for table in problem.tables}
    if instruction.place_type == "table" and instruction.place_id not in tables:
        raise ValueError(f"Unknown table {instruction.place_id}")
    if instruction.place_type in {"floor", "zone"} and instruction.place_id not in {z.id for z in problem.zones}:
        raise ValueError(f"Unknown floor/zone {instruction.place_id}")
    ids = members[instruction.group_id]
    occupied = defaultdict(int)
    at_table: dict[str, list[str]] = defaultdict(list)
    for group, guest_ids in members.items():
        for guest_id in guest_ids:
            occupied[previous[guest_id]] += 1
        home = {previous[guest_id] for guest_id in guest_ids}
        if len(home) == 1:
            at_table[next(iter(home))].append(group)
    source = previous[ids[0]]
    destinations = [
        table.id for table in problem.tables
        if (instruction.action != "move_to" or
            (table.id == instruction.place_id if instruction.place_type == "table"
             else table.zone_id == instruction.place_id))
        and (instruction.action != "not_here" or
             (table.id != instruction.place_id if instruction.place_type == "table"
              else table.zone_id != instruction.place_id))
    ]
    # Do not silently present a no-op as a move. Preserve the current pattern
    # when a split party is targeted; a general solver pass is still available.
    destinations = [table_id for table_id in destinations if table_id != source]
    if not destinations:
        return ReassignResponse(status="blocked",
                                blockers=[f"No alternative tables satisfy {instruction.action} "
                                          f"at {instruction.place_type} {instruction.place_id}."])
    with_instruction = problem.model_copy(deep=True)
    with_instruction.manual_instructions.append(instruction)
    if instruction.allow_split and instruction.group_id not in with_instruction.splittable_groups:
        with_instruction.splittable_groups.append(instruction.group_id)
    options: list[ReassignOption] = []
    signatures: set[tuple[tuple[str, str], ...]] = set()
    blockers: set[str] = set()
    unknown = False
    attempts = 0
    max_options, max_attempts = 8, 28
    # A verified option is exact: pin *every* guest before CP-SAT evaluates it.
    # Never present a proposed arrangement that CP-SAT has not accepted.
    def check(layout: dict[str, str], kind: str, title: str) -> None:
        nonlocal attempts, unknown
        if len(options) >= max_options or attempts >= max_attempts:
            return
        signature = tuple(sorted(layout.items()))
        if signature in signatures or layout == previous:
            return
        signatures.add(signature)
        if any(layout[guest_id] == previous[guest_id] for guest_id in ids) and (
            instruction.action == "move_to" and instruction.place_type == "table"
        ):
            # An explicit destination must actually be reached.
            if not any(layout[guest_id] == instruction.place_id for guest_id in ids):
                return
        capacity = defaultdict(int)
        for table_id in layout.values():
            capacity[table_id] += 1
        if any(count > tables[table_id].capacity for table_id, count in capacity.items()):
            return
        attempts += 1
        exact = with_instruction.model_copy(deep=True)
        exact.locked_guest_tables = dict(layout)
        exact.config.time_limit_seconds = min(exact.config.time_limit_seconds, 2.0)
        outcome = solve(exact)
        if outcome.status == "unknown":
            unknown = True
        if outcome.status not in {"feasible", "optimal"}:
            blockers.update(outcome.conflicting_constraints[:5])
            return
        offered = _placements(problem, outcome)
        if offered != layout:
            return
        warnings = _warning_rules(plan, outcome, problem)
        options.append(ReassignOption(
            id=f"option-{len(options) + 1}", kind=kind, title=title,
            movements=_effects(problem, previous, layout, plan),
            score_delta=(outcome.total_score or 0) - (plan.total_score or 0),
            soft_rule_warnings=warnings, plan=outcome,
        ))

    def replace(*changes: tuple[str, str]) -> dict[str, str]:
        result = dict(previous)
        for group, target in changes:
            for guest_id in members[group]:
                result[guest_id] = target
        return result

    for target in destinations:
        if len(options) >= max_options or attempts >= max_attempts:
            break
        free = tables[target].capacity - occupied[target]
        original_free = tables[source].capacity - occupied[source]
        size = len(ids)
        if free >= size:
            check(replace((instruction.group_id, target)), "free-space",
                  f"Free seats: {_name(plan, instruction.group_id)} to {target}")
        # One-for-one swap; other occupants of both tables remain unchanged.
        for other in at_table[target]:
            if other == instruction.group_id:
                continue
            other_size = len(members[other])
            if free + other_size >= size and original_free + size >= other_size:
                check(replace((instruction.group_id, target), (other, source)), "one-to-one",
                      f"Swap with {_name(plan, other)} at {target}")
        # Several smaller groups at the target collectively move into source.
        others = [g for g in at_table[target] if g != instruction.group_id]
        for count in range(2, min(4, len(others)) + 1):
            for displaced in combinations(others, count):
                displaced_size = sum(len(members[g]) for g in displaced)
                if free + displaced_size >= size and original_free + size >= displaced_size:
                    check(replace((instruction.group_id, target),
                                  *((group, source) for group in displaced)),
                          "many-for-one", f"Exchange with {count} parties from {target}")
                if len(options) >= max_options or attempts >= max_attempts:
                    break
        # Reverse: a larger group at the destination takes the source with
        # another source party moving to the destination alongside the selection.
        for other in at_table[target]:
            for extra in at_table[source]:
                if extra == instruction.group_id:
                    continue
                remaining = tables[target].capacity - occupied[target] + len(members[other])
                extra_size = len(members[extra])
                if remaining >= size + extra_size and (
                    original_free + size + extra_size >= len(members[other])
                ):
                    check(replace((instruction.group_id, target), (other, source),
                                  (extra, target)), "reverse-many-for-one",
                          f"Exchange {_name(plan, other)} for two parties")
        # Three-party chain: selected -> destination, destination -> intermediate,
        # intermediate -> source. The physical limits are checked again by CP-SAT.
        for other in at_table[target]:
            for third_table, third_groups in at_table.items():
                if third_table in {source, target}:
                    continue
                for third in third_groups:
                    if (free + len(members[other]) >= size and
                        tables[third_table].capacity - occupied[third_table] + len(members[third]) >= len(members[other]) and
                        original_free + size >= len(members[third])):
                        check(replace((instruction.group_id, target),
                                      (other, third_table), (third, source)), "chain",
                              f"Chain via {target} and {third_table}")
        if instruction.allow_split and size > 1:
            # The user explicitly opted into splitting this party. Fill the
            # target first and distribute the remainder over other free blocks.
            # Splits are described using the exact per-table counts.
            for order in (destinations, list(reversed(destinations))):
                candidate = dict(previous)
                room = {t: tables[t].capacity - occupied[t] for t in tables}
                permitted = [target] + [t for t in order if t != target]
                index = 0
                for t in permitted:
                    while room[t] > 0 and index < size:
                        candidate[ids[index]] = t
                        index += 1
                        room[t] -= 1
                if index == size and len({candidate[g] for g in ids}) > 1:
                    check(candidate, "split", "Split placement: " +
                          _describe_split(problem, candidate, instruction.group_id))

    # A full constrained re-solve covers valid routes not enumerated above,
    # and provides diagnostic hard-rule IDs when no literal option survives.
    # It may rearrange additional parties; those movements are made explicit.
    if len(options) < max_options:
        solved = solve(with_instruction)
        if solved.status in {"optimal", "feasible"}:
            after = _placements(problem, solved)
            signature = tuple(sorted(after.items()))
            if signature not in signatures and after != previous:
                options.append(ReassignOption(
                    id=f"option-{len(options) + 1}", kind="re-optimize",
                    title="Solver re-optimization (additional parties may move)",
                    movements=_effects(problem, previous, after, plan),
                    score_delta=(solved.total_score or 0) - (plan.total_score or 0),
                    soft_rule_warnings=_warning_rules(plan, solved, problem), plan=solved,
                ))
        elif solved.status == "unknown":
            unknown = True
        else:
            blockers.update(solved.conflicting_constraints)
            blockers.add(solved.message)
    if options:
        return ReassignResponse(status="available", options=options)
    blockers.add(f"No feasible seating route from {source} to " +
                 (instruction.place_id if instruction.action == "move_to" else
                  f"an allowed table outside {instruction.place_type} {instruction.place_id}") +
                 "; table capacities are infinite-weight constraints.")
    blockers.update(f"Hard rule {rule.id} ({rule.shape}) must remain satisfied."
                    for rule in problem.rules if rule.mode == "hard")
    return ReassignResponse(status="unknown" if unknown else "blocked",
                            blockers=sorted(blockers))
