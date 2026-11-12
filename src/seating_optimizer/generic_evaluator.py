"""Pure v2 plan scoring, one evaluator per mechanism, never per legacy shape.

These evaluators check a FIXED placement. They are deliberately separate from
CP-SAT variable construction: they can verify objective arithmetic against
solver output and operate without any optimizer or user-interface dependency.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any, Callable, Mapping, Sequence

from .generic_rules import (
    Criterion, GenericRule, compare_value, guest_value, match_family,
    match_guest, match_table_pattern,
)


class FixedContext:
    def __init__(self, guests: Sequence[Any], tables: Sequence[Any],
                 guest_tables: Mapping[str, str]):
        self.guests = guests
        self.tables = tables
        self.table_by_id = {t.id: t for t in tables}
        if set(guest_tables) - {g.id for g in guests}:
            raise ValueError("Placement refers to unknown guests")
        if set(guest_tables.values()) - set(self.table_by_id):
            raise ValueError("Placement refers to unknown tables")
        self.placement = guest_tables
        self.groups: dict[str, list[Any]] = defaultdict(list)
        for guest in guests:
            self.groups[self.group_id(guest)].append(guest)
        self.group_tables = {
            gid: {self.placement[g.id] for g in members if g.id in self.placement}
            for gid, members in self.groups.items()
        }
        self.at_table = {
            t.id: [g for g in guests if self.placement.get(g.id) == t.id]
            for t in tables
        }

    @staticmethod
    def group_id(guest: Any) -> str:
        return guest.group_id or "guest:" + guest.id

    def matching(self, criterion: Criterion) -> set[str]:
        if criterion.subject == "family":
            return {g.id for members in self.groups.values()
                    if match_family(members, criterion) for g in members}
        return {g.id for g in self.guests if match_guest(g, criterion)}

    def target_group(self, target: str) -> str:
        if target in self.groups:
            return target
        matching = {self.group_id(g) for g in self.guests
                    if g.id == target or g.name == target}
        if len(matching) != 1:
            raise ValueError(f"Unknown or ambiguous target {target!r}")
        return next(iter(matching))

    def has_property(self, table: Any, name: str) -> bool:
        if name == "small_group_priority":
            return table.small_group_priority
        return name.casefold() in {v.casefold() for v in table.properties}


def _pair_relation(r: GenericRule, c: FixedContext) -> int:
    a, b = (c.target_group(t) for t in r.targets)
    shared = bool(c.group_tables[a] & c.group_tables[b])
    good = shared if r.relation == "together" else not shared and a != b
    return r.weight * int(good)


def _pairs(r: GenericRule, c: FixedContext, *, within: bool) -> int:
    selector = Criterion.model_validate(r.criterion)
    scope = selector.scope or ("within" if within else "all")
    points = 0
    for at_table in c.at_table.values():
        relevant = [g for g in at_table if match_guest(g, selector)]
        for a, b in combinations(relevant, 2):
            same_family = c.group_id(a) == c.group_id(b)
            if scope == "within" and not same_family:
                continue
            if scope == "across" and same_family:
                continue
            same_value = guest_value(a, selector.field) == guest_value(b, selector.field)
            if r.polarity == "reward" and same_value:
                points += r.weight
            elif r.polarity == "penalty" and not same_value:
                points -= r.weight
        if r.polarity == "penalty" and selector.value is not None:
            # An explicitly selected value penalizes mixing against other
            # known values, without charging two nonselected guests.
            others = [
                g for g in at_table if guest_value(g, selector.field) is not None
                and not match_guest(g, selector)
            ]
            for a in relevant:
                for b in others:
                    if scope == "within" and c.group_id(a) != c.group_id(b):
                        continue
                    if scope == "across" and c.group_id(a) == c.group_id(b):
                        continue
                    points -= r.weight
    return points


def _criterion_pairs(r: GenericRule, c: FixedContext) -> int:
    return _pairs(r, c, within=False)


def _own_attribute_grouping(r: GenericRule, c: FixedContext) -> int:
    return _pairs(r, c, within=True)


def _split_term(r: GenericRule, c: FixedContext) -> int:
    return -r.weight * sum(max(0, len(places) - 1)
                           for places in c.group_tables.values())


def _table_pattern(r: GenericRule, c: FixedContext) -> int:
    sign = 1 if r.polarity == "reward" else -1
    return sign * r.weight * sum(
        match_table_pattern(r.conditions, table_id=t.id, tables=c.tables,
                            guests=c.guests, guest_tables=c.placement)
        for t in c.tables
    )


def _companionship(r: GenericRule, c: FixedContext) -> int:
    zone_groups: dict[str, set[str]] = defaultdict(set)
    for gid, table_ids in c.group_tables.items():
        for tid in table_ids:
            zone_groups[c.table_by_id[tid].zone_id].add(gid)
    occupied = [groups for groups in zone_groups.values() if groups]
    if len(occupied) < 2:
        return 0
    excluded = set(r.exclusions or [])
    lone = sum(len(groups) == 1 and next(iter(groups)) not in excluded
               for groups in occupied)
    return -r.weight * lone


def _placement_by_criterion(r: GenericRule, c: FixedContext) -> int:
    chosen = Criterion.model_validate(r.criterion)
    allowed = set(r.zones)
    matched = c.matching(chosen)
    return r.weight * sum(
        g.id in matched and c.table_by_id[c.placement[g.id]].zone_id in allowed
        for g in c.guests if g.id in c.placement
    )


def _property_need(r: GenericRule, c: FixedContext) -> int:
    chosen = Criterion.model_validate(r.criterion)
    matched = c.matching(chosen)
    return -r.weight * sum(
        g.id in matched and not c.has_property(c.table_by_id[c.placement[g.id]], r.property)
        for g in c.guests if g.id in c.placement
    )


def _property_fit(r: GenericRule, c: FixedContext) -> int:
    chosen = Criterion.model_validate(r.criterion)
    return r.weight * sum(
        match_family(members, chosen)
        and any(c.has_property(c.table_by_id[tid], r.property)
                for tid in c.group_tables[gid])
        for gid, members in c.groups.items()
    )


def _holes_term(r: GenericRule, c: FixedContext) -> int:
    return -r.weight * sum(
        t.capacity - len(c.at_table[t.id])
        for t in c.tables if c.at_table[t.id]
    )


def _no_points(r: GenericRule, c: FixedContext) -> int:
    # Constraints, pins, staged tiers and priority marks cannot earn points.
    return 0


SCORERS: dict[tuple[str, str], Callable[[GenericRule, FixedContext], int]] = {
    ("intra", "split_term"): _split_term,
    ("intra", "own_attribute_grouping"): _own_attribute_grouping,
    ("inter", "pair_relation"): _pair_relation,
    ("inter", "criterion_pairs"): _criterion_pairs,
    ("inter", "table_pattern"): _table_pattern,
    ("inter", "companionship"): _companionship,
    ("venue", "placement_by_criterion"): _placement_by_criterion,
    ("venue", "property_need"): _property_need,
    ("venue", "tiered_placement"): _no_points,
    ("venue", "holes_term"): _holes_term,
    ("venue", "property_fit"): _property_fit,
    ("venue", "locked_assignment"): _no_points,
    ("stage", "priority_mark"): _no_points,
}


def score_fixed_plan(guests: Sequence[Any], tables: Sequence[Any],
                     guest_tables: Mapping[str, str],
                     rules: Sequence[GenericRule]) -> tuple[int, dict[str, int]]:
    """One breakdown entry per enabled scoring instance; never hidden points."""
    c = FixedContext(guests, tables, guest_tables)
    lines = {}
    for rule in rules:
        if not rule.enabled or rule.mode != "soft":
            continue
        key = (rule.engine, rule.mechanism)
        if key not in SCORERS:
            raise ValueError(f"No scorer registered for {key}")
        lines[rule.id] = SCORERS[key](rule, c)
    return sum(lines.values()), lines


def hard_violations(guests: Sequence[Any], tables: Sequence[Any],
                    guest_tables: Mapping[str, str], rules: Sequence[GenericRule]) -> list[str]:
    """Check hard mechanisms on fixed placements; pure diagnostic, not CP-SAT."""
    c = FixedContext(guests, tables, guest_tables)
    errors = []
    for t in tables:
        if len(c.at_table[t.id]) > t.capacity:
            errors.append(f"capacity:{t.id}")
    for rule in rules:
        if not rule.enabled or rule.mode != "hard":
            continue
        key = (rule.engine, rule.mechanism)
        if key == ("inter", "pair_relation"):
            a, b = (c.target_group(x) for x in rule.targets)
            shared = bool(c.group_tables[a] & c.group_tables[b])
            if shared != (rule.relation == "together"):
                errors.append(rule.display_name)
        elif key == ("venue", "placement_by_criterion"):
            criterion = Criterion.model_validate(rule.criterion)
            matched = c.matching(criterion)
            if any(g.id in matched
                   and c.table_by_id[c.placement[g.id]].zone_id not in set(rule.zones)
                   for g in guests if g.id in c.placement):
                errors.append(rule.display_name)
        elif key == ("venue", "property_need"):
            criterion = Criterion.model_validate(rule.criterion)
            matched = c.matching(criterion)
            if any(g.id in matched
                   and not c.has_property(c.table_by_id[c.placement[g.id]], rule.property)
                   for g in guests if g.id in c.placement):
                errors.append(rule.display_name)
        elif key == ("venue", "locked_assignment"):
            gid = c.target_group(rule.target)
            if c.group_tables[gid] != {rule.table}:
                errors.append(rule.display_name)
        elif key in (("intra", "own_attribute_grouping"), ("inter", "criterion_pairs")):
            criterion = Criterion.model_validate(rule.criterion)
            scope = criterion.scope or (
                "within" if key[0] == "intra" else "all")
            matched = [g for g in guests if match_guest(g, criterion)
                       and g.id in c.placement]
            known = [g for g in guests if guest_value(g, criterion.field) is not None
                     and g.id in c.placement]
            others = [g for g in known if g.id not in {p.id for p in matched}]
            if rule.polarity == "penalty" and criterion.value is not None:
                candidates = ((a, b) for a in matched for b in others)
            else:
                candidates = combinations(matched, 2)
            for a, b in candidates:
                same_family = c.group_id(a) == c.group_id(b)
                if scope == "within" and not same_family:
                    continue
                if scope == "across" and same_family:
                    continue
                same_value = guest_value(a, criterion.field) == guest_value(b, criterion.field)
                together = c.placement[a.id] == c.placement[b.id]
                if (rule.polarity == "reward" and same_value and not together) or (
                    rule.polarity == "penalty" and not same_value and together
                ):
                    errors.append(rule.display_name)
                    break
        else:
            raise ValueError(f"Unsupported hard mechanism {key}")
    return errors
