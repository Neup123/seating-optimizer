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
from .solver import solve, _group_id, _prepare, _active_problem, _solve_core


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
    if instruction.action == "seat_pending":
        return _propose_pending(request)
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
            # Other free blocks may lie outside a table-specific destination.
            # Prefer to move the entire party away from its old table, if possible.
            other_blocks = [t for t in tables if t != target and t != source and (
                instruction.action != "not_here" or (
                    t != instruction.place_id if instruction.place_type == "table"
                    else tables[t].zone_id != instruction.place_id))]
            if source != target and (instruction.action != "not_here" or (
                source != instruction.place_id if instruction.place_type == "table"
                else tables[source].zone_id != instruction.place_id)):
                other_blocks.append(source)
            for order in (other_blocks, list(reversed(other_blocks))):
                candidate = dict(previous)
                room = {t: tables[t].capacity - occupied[t] for t in tables}
                permitted = [target] + list(order)
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



def _propose_pending(request: ReassignRequest) -> ReassignResponse:
    """Present explicit, solver-checked choices for an unplaced graded family.

    The candidate is NOT unseated. Until the human chooses an option, it remains
    pending in the plan. Confirmed placements are saved as manual instructions
    with exact guest/table mappings, making moved guests and split portions
    durable across re-solves. A selected overflow move uses its own instruction.
    """
    problem, plan, intent = request.problem, request.plan, request.instruction
    if plan.status != "needs_review" or plan.session_id != problem.session_id:
        raise ValueError("A low-priority plan awaiting operator review is required")
    if intent.group_id not in {mark.group_id for mark in plan.pending_groups}:
        raise ValueError("The selected family is not pending operator review")
    if plan.manual_instructions != problem.manual_instructions:
        raise ValueError("Stored instructions changed since this plan; re-solve first")
    if intent.id in {i.id for i in problem.manual_instructions}:
        raise ValueError(f"Instruction ID {intent.id} already exists")
    if plan.not_seated and {p.group_id for p in plan.not_seated} != {
            i.group_id for i in problem.manual_instructions if i.action == "unseat"}:
        raise ValueError("The not-seated selection has changed; re-solve first")

    groups, lookup = _prepare(problem)
    selected = intent.group_id
    ids = [g.id for g in groups[selected]]
    previous = {}
    for assignment in plan.assignments:
        for guest_id in assignment.guest_ids:
            if guest_id in previous:
                raise ValueError("Duplicate guest in pending-plan placements")
            previous[guest_id] = assignment.table_id
    if any(guest_id in previous for guest_id in ids):
        raise ValueError("The pending family is already placed")
    # The baseline must be complete for all accepted stages; only pending
    # and human-unseated families can be missing.
    excluded = ({m.group_id for m in plan.pending_groups} |
                {m.group_id for m in plan.not_seated})
    expected = {g.id for gid, members in groups.items() if gid not in excluded
                for g in members}
    if set(previous) != expected:
        raise ValueError("The review plan has stale or incomplete placements")

    tables = {table.id: table for table in problem.tables}
    occupied = defaultdict(int)
    at_table = defaultdict(list)
    for guest_id, table_id in previous.items():
        if table_id not in tables:
            raise ValueError("Review plan references a missing table")
        occupied[table_id] += 1
    for gid, members in groups.items():
        seats = {previous[g.id] for g in members if g.id in previous}
        if len(seats) == 1 and all(g.id in previous for g in members):
            at_table[next(iter(seats))].append(gid)
    free = {t: tables[t].capacity - occupied[t] for t in tables}
    if any(value < 0 for value in free.values()):
        raise ValueError("Review plan exceeds a table capacity")
    options: list[ReassignOption] = []
    signatures: set[tuple] = set()
    blockers: set[str] = set()
    unknown = False
    attempts = 0
    max_attempts = 32
    max_options = 8

    def check(layout: dict[str, str], kind: str, title: str, *, split: bool = False):
        nonlocal attempts, unknown
        if len(options) >= max_options - 1 or attempts >= max_attempts:
            return
        if set(layout) != set(previous) | set(ids):
            return
        signature = tuple(sorted(layout.items()))
        if signature in signatures:
            return
        signatures.add(signature)
        capacity = defaultdict(int)
        for table_id in layout.values():
            if table_id not in tables:
                return
            capacity[table_id] += 1
        if any(value > tables[t].capacity for t, value in capacity.items()):
            return
        attempts += 1
        direction = ManualInstruction(
            id=intent.id, group_id=selected, action="pin_placement",
            guest_tables=dict(layout), allow_split=split)
        # Solve through the actual staged public path, with the approved
        # arrangement treated as mandatory data rather than a heuristic.
        candidate = problem.model_copy(deep=True)
        candidate.manual_instructions.append(direction)
        candidate.config.time_limit_seconds = min(candidate.config.time_limit_seconds, 4.0)
        outcome = solve(candidate)
        if outcome.status == "unknown":
            unknown = True
        if outcome.status not in {"optimal", "feasible", "needs_review"}:
            blockers.update(outcome.conflicting_constraints[:5])
            return
        actual = {g: a.table_id for a in outcome.assignments for g in a.guest_ids}
        if not all(actual.get(g) == t for g, t in layout.items()):
            return
        movements = []
        for gid, members in groups.items():
            new_tables = sorted({layout[g.id] for g in members if g.id in layout})
            old_tables = sorted({previous[g.id] for g in members if g.id in previous})
            if new_tables != old_tables:
                movements.append(Movement(
                    group_id=gid, party_name=next(
                        (mark.group_name for mark in plan.priority_marks if mark.group_id == gid),
                        _name(plan, gid)),
                    before=old_tables, after=new_tables, people=len(members)))
        options.append(ReassignOption(
            id=f"option-{len(options)+1}", kind=kind, title=title,
            movements=movements, score_delta=(outcome.total_score or 0) - (plan.total_score or 0),
            soft_rule_warnings=_warning_rules(plan, outcome, problem), plan=outcome))

    # Free seats: the main staged solve normally would have used these,
    # but full verification is still required (hard restrictions may block).
    for target in tables:
        if free[target] >= len(ids):
            check({**previous, **{g: target for g in ids}},
                  "free-space", f"Seat at table {target} without moving others")

    # Move an occupant elsewhere so that the deferred party can occupy its
    # former seats. All displaced parties remain whole.
    for target in tables:
        for other in at_table[target]:
            other_ids = [g.id for g in groups[other]]
            for destination in tables:
                if destination == target or free[destination] < len(other_ids):
                    continue
                layout = {**previous, **{g: target for g in ids},
                          **{g: destination for g in other_ids}}
                check(layout, "one-to-one",
                      f"Move {_name(plan, other)} to {destination}; seat at {target}")

    # Many-for-one: displace two or three smaller parties from one target
    # into distinct available blocks, without splitting them.
    for target in tables:
        others = at_table[target]
        for count in range(2, min(3, len(others)) + 1):
            for displaced in combinations(others, count):
                relocating = [(other, [g.id for g in groups[other]]) for other in displaced]
                blocks = {t: free[t] for t in tables if t != target}
                assignments = []
                def pack(i: int):
                    if i == len(relocating):
                        layout = {**previous, **{g: target for g in ids}}
                        for (_, members), destination in zip(relocating, assignments):
                            layout.update({g: destination for g in members})
                        check(layout, "many-for-one",
                              f"Move {count} parties; seat at {target}")
                        return
                    _, members = relocating[i]
                    for destination in blocks:
                        if blocks[destination] < len(members):
                            continue
                        blocks[destination] -= len(members)
                        assignments.append(destination)
                        pack(i + 1)
                        assignments.pop()
                        blocks[destination] += len(members)
                        if len(options) >= max_options - 1:
                            return
                pack(0)

    # Chain: A pending -> target, one incumbent -> middle, middle -> free
    # destination. It is never permitted to weaken an infinite-weight rule.
    for target in tables:
        for other in at_table[target]:
            other_ids = [g.id for g in groups[other]]
            for middle in tables:
                if middle == target:
                    continue
                for third in at_table[middle]:
                    if third == other:
                        continue
                    third_ids = [g.id for g in groups[third]]
                    for destination in tables:
                        if destination in {target, middle}:
                            continue
                        if free[destination] < len(third_ids) or (
                                free[middle] + len(third_ids) < len(other_ids)):
                            continue
                        layout = {
                            **previous, **{g: target for g in ids},
                            **{g: middle for g in other_ids},
                            **{g: destination for g in third_ids},
                        }
                        check(layout, "chain",
                              f"Chain through {target}, {middle} and {destination}")

    # Split placement is an offered *choice*, not an automatic solve action.
    # Different orders favour different remaining free blocks.
    if len(ids) > 1 and sum(free.values()) >= len(ids):
        for ordering in (list(tables), list(reversed(tables))):
            layout = dict(previous)
            remaining = list(ids)
            for t in ordering:
                portion = remaining[:free[t]]
                remaining = remaining[len(portion):]
                layout.update({g: t for g in portion})
                if not remaining:
                    break
            if not remaining and len({layout[g] for g in ids}) >= 2:
                counts = defaultdict(int)
                for g in ids:
                    counts[layout[g]] += 1
                title = "Split: " + ", ".join(f"{t} ({count})" for t, count in counts.items())
                check(layout, "split", title, split=True)

    # A final broader solve can find a multi-party arrangement that the
    # concrete enumerator did not cover. It is still pinned and checked by
    # the same candidate verifier before appearing as an option.
    if len(options) < max_options - 1 and attempts < max_attempts:
        active = {gid for gid in groups
                  if gid not in {m.group_id for m in plan.not_seated} and
                  (gid == selected or all(g.id in previous for g in groups[gid]))}
        partial = _active_problem(problem, active, lookup)
        full = _solve_core(partial)
        if full.status in {"optimal", "feasible"}:
            layout = {g: a.table_id for a in full.assignments for g in a.guest_ids}
            check(layout, "re-optimize",
                  "Re-optimize current parties with all hard rules")
        elif full.status == "unknown":
            unknown = True
        else:
            blockers.update(full.conflicting_constraints[:5])

    # No unseated list entry is manufactured automatically. This is only
    # an explicit option, and applying it persists the human instruction.
    unseat = ManualInstruction(id=intent.id, group_id=selected, action="unseat")
    with_unseat = problem.model_copy(deep=True)
    with_unseat.manual_instructions.append(unseat)
    unseated_plan = solve(with_unseat)
    options.append(ReassignOption(
        id=f"option-{len(options)+1}", kind="leave_unseated",
        title=f"Leave {_name(plan, selected)} unseated (operator decision)",
        movements=[Movement(
            group_id=selected, party_name=next(
                (m.group_name for m in plan.pending_groups if m.group_id == selected), selected),
            before=[], after=[], people=len(ids))],
        score_delta=(unseated_plan.total_score or 0) - (plan.total_score or 0),
        soft_rule_warnings=[], plan=unseated_plan))
    return ReassignResponse(
        status="available", options=options,
        blockers=sorted(blockers) if len(options) == 1 else [])
