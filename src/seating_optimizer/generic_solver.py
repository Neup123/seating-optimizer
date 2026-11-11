"""Version-2 generic CP-SAT solver, staged family priority, audit metadata.

v1 solver remains available as seating_optimizer.solver.solve. v2 is not an
adapter to the legacy shape solver: it constructs its own CP-SAT model using
generic_cp.BUILDERS, and checks reported points with generic_evaluator.
"""
from __future__ import annotations

from collections import defaultdict
from time import perf_counter
from typing import Literal

from ortools.sat.python import cp_model
from pydantic import Field

from .display import counted, distinct_party_name, party_name_for
from .generic_cp import Build, add_rule, group_id, resolve_tiers
from .generic_evaluator import score_fixed_plan
from .generic_rules import (
    Criterion, GenericRule, criterion_field_state, match_family,
    split_dominance_warnings,
)
from .models import (
    Assignment, Compromise, Model, NotSeatedGroup, Plan, PriorityMark, Problem,
    Reason, ScoreItem, TableUsage, VenueConfiguration,
)
from .rule_migration import migrate_instance


class GenericProblem(Problem):
    """Identical physical/input contract to Problem; rule instances are v2."""
    rules: list[GenericRule] = Field(default_factory=list)

    @classmethod
    def from_v1(cls, problem: Problem) -> "GenericProblem":
        return cls.model_validate({
            **problem.model_dump(mode="json"),
            "rules": [m.model_dump(mode="json", exclude_none=True) for r in problem.rules
                      if (m := migrate_instance(r)) is not None],
        })


class GenericVenueConfiguration(VenueConfiguration):
    version: Literal[2] = 2
    rules: list[GenericRule] = Field(default_factory=list)


class UnseatedReason(Model):
    group_id: str
    group_name: str
    guest_ids: list[str]
    guest_names: list[str]
    reason: Literal["lack_of_space", "operator_decision"]
    status: Literal["pending", "confirmed"]
    description: str


class GenericPlan(Plan):
    validation_warnings: list[str] = Field(default_factory=list)
    criterion_states: list[dict] = Field(default_factory=list)
    unseated_reasons: list[UnseatedReason] = Field(default_factory=list)


def _groups(problem):
    members = defaultdict(list)
    for guest in problem.guests:
        members[group_id(guest)].append(guest)
    return dict(members)


def _names(groups):
    result = {}
    for gid, members in groups.items():
        names = [guest.name for guest in members]
        registered = distinct_party_name(gid, [g.group_name for g in members], names)
        if not registered and len(members) == 1:
            label = names[0].strip()
            if label and not label.casefold().startswith(("registration:", "guest:")):
                registered = label
        result[gid] = party_name_for(gid, registered, names)
    return result


def _lookup(groups):
    result = {}
    for gid, members in groups.items():
        for name in [gid, *(g.id for g in members), *(g.name for g in members)]:
            if name in result and result[name] != gid:
                raise ValueError(f"Ambiguous target {name!r}")
            result[name] = gid
    return result


def _validate_rule(rule, problem, groups, lookup):
    key = (rule.engine, rule.mechanism)
    target_keys = {
        ("inter", "pair_relation"): rule.targets or [],
        ("venue", "tiered_placement"): [rule.target],
        ("venue", "locked_assignment"): [rule.target],
    }
    for target in target_keys.get(key, []):
        if target not in lookup:
            raise ValueError(f"Rule {rule.display_name}: unknown target {target!r}")
    if key == ("venue", "tiered_placement"):
        zones = {z.id for z in problem.zones}
        tables = {t.id for t in problem.tables}
        for tier in rule.tiers:
            if set(tier.get("zones", [])) - zones or set(tier.get("tables", [])) - tables:
                raise ValueError(f"Rule {rule.display_name}: unknown tier zone/table")
    if key == ("venue", "placement_by_criterion"):
        if set(rule.zones) - {z.id for z in problem.zones}:
            raise ValueError(f"Rule {rule.display_name}: unknown zone")
    if key == ("venue", "locked_assignment"):
        if rule.table not in {t.id for t in problem.tables}:
            raise ValueError(f"Rule {rule.display_name}: unknown table")
    if key == ("inter", "companionship"):
        if set(rule.exclusions or []) - set(groups):
            raise ValueError(f"Rule {rule.display_name}: unknown companionship exclusions")
    if key == ("stage", "priority_mark") and rule.selector == "direct":
        if rule.target not in lookup:
            raise ValueError(f"Rule {rule.display_name}: unknown priority target")


def _validate(problem, groups, lookup):
    warnings, field_states = [], []
    for rule in problem.rules:
        if not rule.enabled:
            continue
        _validate_rule(rule, problem, groups, lookup)
        if rule.criterion:
            criterion = Criterion.model_validate(rule.criterion)
            state = criterion_field_state(problem.guests, criterion)
            field_states.append({
                "rule_id": rule.id, "field": state.field,
                "observed": state.observed, "compatible": state.compatible,
                "message": state.message,
            })
            if not state.compatible:
                raise ValueError(f"Rule {rule.display_name}: {state.message}")
            if not state.observed:
                warnings.append(f"Rule {rule.display_name}: {state.message}")
        for clause in rule.conditions or []:
            if clause.get("fact") != "count":
                continue
            criterion = Criterion.model_validate(clause["criterion"])
            state = criterion_field_state(problem.guests, criterion)
            field_states.append({
                "rule_id": rule.id, "field": state.field,
                "observed": state.observed, "compatible": state.compatible,
                "message": state.message,
            })
            if not state.compatible:
                raise ValueError(f"Rule {rule.display_name}: {state.message}")
            if not state.observed:
                warnings.append(f"Rule {rule.display_name}: {state.message}")
    warnings += split_dominance_warnings(
        problem.rules, guest_count=len(problem.guests), table_count=len(problem.tables))
    return warnings, field_states


def _priority_marks(problem, groups, lookup, names):
    graded = {}
    for rule in problem.rules:
        if not rule.enabled or (rule.engine, rule.mechanism) != ("stage", "priority_mark"):
            continue
        if rule.selector == "direct":
            selected = [lookup[rule.target]]
        else:
            criterion = Criterion.model_validate(rule.criterion)
            selected = [gid for gid, members in groups.items()
                        if match_family(members, criterion)]
        for gid in selected:
            old_grade, sources = graded.get(gid, (0, set()))
            graded[gid] = (max(old_grade, rule.grade), sources | {rule.id})
    return sorted(
        [PriorityMark(group_id=gid, group_name=names[gid], grade=grade,
                      guest_count=len(groups[gid]), source_rule_ids=sorted(sources))
         for gid, (grade, sources) in graded.items()],
        key=lambda m: (m.grade, m.group_name, m.group_id),
    )


def _stage_problem(problem, active_ids, lookup):
    """Data-driven mechanism filters, without inspecting legacy shape names."""
    def target_pair(r):
        return all(lookup[t] in active_ids for t in r.targets)

    def target_one(r):
        return lookup[r.target] in active_ids

    def exclude_stage(r):
        return False

    def all_other(r):
        return True

    predicates = {
        ("inter", "pair_relation"): target_pair,
        ("venue", "locked_assignment"): target_one,
        ("venue", "tiered_placement"): target_one,
        ("stage", "priority_mark"): exclude_stage,
    }
    def stage_rule(rule):
        if (rule.engine, rule.mechanism) != ("inter", "companionship"):
            return rule
        return rule.model_copy(update={
            "exclusions": [gid for gid in rule.exclusions or [] if gid in active_ids],
        })

    guests = [g for g in problem.guests if group_id(g) in active_ids]
    guest_ids = {g.id for g in guests}
    directions = []
    for instruction in problem.manual_instructions:
        if instruction.group_id not in active_ids or instruction.action == "unseat":
            continue
        if instruction.action == "pin_placement":
            pins = {g: t for g, t in instruction.guest_tables.items() if g in guest_ids}
            if pins:
                directions.append(instruction.model_copy(update={"guest_tables": pins}))
        else:
            directions.append(instruction)
    return problem.model_copy(update={
        "guests": guests,
        "rules": [stage_rule(r) for r in problem.rules
                  if r.enabled and predicates.get((r.engine, r.mechanism), all_other)(r)],
        "manual_instructions": directions,
        "splittable_groups": [gid for gid in problem.splittable_groups if gid in active_ids],
        "locked_guest_tables": {g: t for g, t in problem.locked_guest_tables.items()
                                if g in guest_ids},
    })


def _empty(problem):
    return GenericPlan(
        session_id=problem.session_id, status="optimal", total_score=0,
        tables=[TableUsage(table_id=t.id, zone_id=t.zone_id, capacity=t.capacity,
                           occupied=0, empty_seats=t.capacity) for t in problem.tables],
        layout=problem.layout, message="No ordinary families in the first stage.",
    )


def _core(problem):
    """One full CP-SAT stage: 13 mechanisms dispatched without shape branches."""
    start = perf_counter()
    groups = _groups(problem)
    names = _names(groups)
    lookup = _lookup(groups)
    builder = Build(problem, groups, lookup)
    builder.manual()
    for rule in problem.rules:
        if rule.enabled:
            add_rule(rule, builder)
    selection, unknown_tier = resolve_tiers(builder, [r for r in problem.rules if r.enabled])
    if unknown_tier:
        return GenericPlan(
            session_id=problem.session_id, status="unknown",
            message="Tier feasibility is unproved; no later tier selected.",
            layout=problem.layout, solve_seconds=perf_counter()-start,
        )
    builder.model.Maximize(sum(builder.terms))
    optimizer = builder.solver()
    result = optimizer.Solve(builder.model)
    if result not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        conflicts = []
        if result == cp_model.INFEASIBLE:
            builder.model.ClearObjective()
            diagnostic = cp_model.CpSolver()
            diagnostic.parameters.max_time_in_seconds = min(
                problem.config.time_limit_seconds, 5.0)
            diagnostic.parameters.num_search_workers = 1
            diagnostic.parameters.random_seed = problem.config.random_seed
            if diagnostic.Solve(builder.model) == cp_model.INFEASIBLE:
                by_index = {var.Index(): name for name, var in builder.assumptions.items()}
                conflicts = [by_index[i] for i in diagnostic.SufficientAssumptionsForInfeasibility()
                             if i in by_index]
        return GenericPlan(
            session_id=problem.session_id,
            status="infeasible" if result == cp_model.INFEASIBLE else "unknown",
            message=("Hard rules conflict with table capacities and party placement."
                     if result == cp_model.INFEASIBLE else
                     "No feasible placement confirmed before solver time limit."),
            conflicting_constraints=conflicts, layout=problem.layout,
            solve_seconds=perf_counter()-start,
        )
    mapping = {
        g.id: builder.tables[
            next(j for j in range(builder.n) if optimizer.Value(builder.guest_at[g.id, j]))
        ].id for g in problem.guests
    }
    score, by_rule = score_fixed_plan(problem.guests, builder.tables, mapping, problem.rules)
    # A together-linked cluster that cannot fit one table may satisfy a
    # named pair using the legacy connected-adjacent-table exception. The
    # optimized Boolean is the authoritative B1 evaluator for that case.
    if builder.fallback_by_rule:
        by_id = {r.id: r for r in problem.rules if r.enabled and r.mode == "soft"}
        for rule_id, flag in builder.fallback_by_rule.items():
            if rule_id in by_id:
                by_rule[rule_id] = by_id[rule_id].weight * optimizer.Value(flag)
        score = sum(by_rule.values())
    if score != round(optimizer.ObjectiveValue()):
        raise RuntimeError(
            f"v2 objective/report mismatch: reported {score}; optimized "
            f"{optimizer.ObjectiveValue()} (by rule: {by_rule})"
        )
    assignments = []
    for gid, members in groups.items():
        for table in builder.tables:
            portion = [g for g in members if mapping[g.id] == table.id]
            if not portion:
                continue
            assignments.append(Assignment(
                group_id=gid, group_name=names[gid], table_id=table.id,
                guest_ids=[g.id for g in portion], guest_names=[g.name for g in portion],
                guest_attributes=[g.attributes for g in portion],
                reasons=[Reason(rule_id=f"capacity:{table.id}",
                                description=f"Within {table.capacity}-chair structural capacity.")],
            ))
    # The v2 score breakdown is exact. A plan-wide score must not be presented
    # as though it were earned by any single guest or family.
    breakdown = [ScoreItem(rule_id=rule_id, points=value)
                 for rule_id, value in by_rule.items()]
    usage = []
    for table in builder.tables:
        occupied = sum(mapping[g.id] == table.id for g in problem.guests)
        usage.append(TableUsage(table_id=table.id, zone_id=table.zone_id,
                                capacity=table.capacity, occupied=occupied,
                                empty_seats=table.capacity-occupied))
    return GenericPlan(
        session_id=problem.session_id,
        status="optimal" if result == cp_model.OPTIMAL else "feasible",
        total_score=score, assignments=assignments, tables=usage,
        score_breakdown=breakdown,
        compromises=[Compromise(rule_id=r, description=f"Penalty from {r}",
                                lost_points=-points)
                     for r, points in by_rule.items() if points < 0],
        layout=problem.layout, solve_seconds=perf_counter()-start,
        message="All hard constraints satisfied.",
    )


def solve_generic(problem: GenericProblem | Problem) -> GenericPlan:
    """Seat regular families as one stage, then each marked family in grade order.

    A failed low-priority candidate stays pending with lack-of-space explanation.
    Only explicit operator unseat instructions enter Plan.not_seated.
    """
    start = perf_counter()
    if isinstance(problem, Problem) and not isinstance(problem, GenericProblem):
        problem = GenericProblem.from_v1(problem)
    groups = _groups(problem)
    lookup = _lookup(groups)
    names = _names(groups)
    warnings, states = _validate(problem, groups, lookup)
    marks = _priority_marks(problem, groups, lookup, names)
    grade_by_id = {m.group_id: m.grade for m in marks}
    operator_unseat = {i.group_id for i in problem.manual_instructions
                       if i.action == "unseat"}
    not_seated = [
        NotSeatedGroup(group_id=gid, group_name=names[gid],
                       guest_ids=[g.id for g in members],
                       guest_names=[g.name for g in members],
                       grade=grade_by_id.get(gid))
        for gid, members in groups.items() if gid in operator_unseat
    ]
    reasons = [
        UnseatedReason(group_id=gid, group_name=names[gid],
                       guest_ids=[g.id for g in members],
                       guest_names=[g.name for g in members],
                       reason="operator_decision", status="confirmed",
                       description="Explicit unseat manual instruction.")
        for gid, members in groups.items() if gid in operator_unseat
    ]
    active = set(groups) - operator_unseat
    seats = sum(t.capacity for t in problem.tables)
    guest_count = sum(len(groups[gid]) for gid in active)

    def metadata(plan, pending=None, pending_reason=False):
        plan.priority_marks = marks
        plan.pending_groups = pending or []
        plan.manual_instructions = problem.manual_instructions
        plan.not_seated = not_seated
        plan.unseated_reasons = reasons + (
            [UnseatedReason(group_id=m.group_id, group_name=m.group_name,
                            guest_ids=[g.id for g in groups[m.group_id]],
                            guest_names=[g.name for g in groups[m.group_id]],
                            reason="lack_of_space", status="pending",
                            description="Not yet fitted; no operator unseat decision exists.")
             for m in pending or []] if pending_reason else []
        )
        plan.validation_warnings = warnings
        plan.criterion_states = states
        plan.solve_seconds = perf_counter() - start
        return plan

    if guest_count > seats:
        short = guest_count - seats
        return metadata(GenericPlan(
            session_id=problem.session_id, status="infeasible",
            message=(f"Too many people — short by {short}. "
                     "The operator must select whom to leave unseated."),
            conflicting_constraints=[
                f"Too many people — short by {short}: {guest_count} guests, {seats} chairs."
            ], layout=problem.layout,
        ))
    if not active:
        return metadata(_empty(problem))
    filtered = _stage_problem(problem, active, lookup)
    approved = {i.group_id for i in problem.manual_instructions
                if i.action == "pin_placement"}
    ordered = [m for m in marks if m.group_id in active and m.group_id not in approved]
    included = active - {m.group_id for m in ordered}
    if included:
        baseline = _core(_stage_problem(filtered, included, lookup))
        if baseline.status not in ("optimal", "feasible"):
            return metadata(baseline)
    else:
        baseline = _empty(problem)
    if not ordered:
        return metadata(baseline)

    locked = {g: a.table_id for a in baseline.assignments for g in a.guest_ids}
    for index, mark in enumerate(ordered):
        candidate = _stage_problem(filtered, included | {mark.group_id}, lookup)
        candidate.locked_guest_tables = {**candidate.locked_guest_tables, **locked}
        result = _core(candidate)
        if result.status not in ("optimal", "feasible"):
            baseline.status = "needs_review"
            baseline.message = (
                f"Low-priority grade {mark.grade} family {mark.group_name} cannot "
                "be fitted without changing an earlier placement. Operator decision required."
                if result.status == "infeasible" else
                f"Low-priority grade {mark.grade} family {mark.group_name} "
                "could not be confirmed within the solver time limit."
            )
            baseline.conflicting_constraints = result.conflicting_constraints
            return metadata(baseline, ordered[index:], pending_reason=True)
        baseline = result
        included.add(mark.group_id)
        locked = {g: a.table_id for a in baseline.assignments for g in a.guest_ids}
    return metadata(baseline)
