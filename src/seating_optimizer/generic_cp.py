"""Generic CP-SAT mechanism builders for version-2 seating rules.

Only this module constructs scoring/constraint terms for v2 instances.
The legacy shape solver remains in solver.py for comparison.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from types import SimpleNamespace

from ortools.sat.python import cp_model

from .adjacency import neighbouring_tables
from .generic_rules import Criterion, GenericRule, compare_value, guest_value, match_family, match_guest
from .pattern_rules import add_comparison
from .solver import _zone_companionship_penalties


def group_id(guest):
    return guest.group_id if guest.group_id is not None else "guest:" + guest.id


class Build:
    def __init__(self, problem, groups, lookup):
        self.problem = problem
        self.groups = groups
        self.lookup = lookup
        self.model = cp_model.CpModel()
        self.tables = problem.tables
        self.n = len(self.tables)
        self.ids = list(groups)
        self.split = set(problem.splittable_groups)
        self.split.update(i.group_id for i in problem.manual_instructions if i.allow_split)
        max_capacity = max(t.capacity for t in self.tables)
        self.split.update(gid for gid, members in groups.items()
                          if len(members) > max_capacity)
        self.x = {(gid, j): self.model.NewBoolVar(f"v2:x:{gid}:{j}")
                  for gid in groups for j in range(self.n)}
        self.guest_at = {}
        self.loc = {}
        for gid, members in groups.items():
            if gid in self.split:
                for guest in members:
                    for j in range(self.n):
                        self.guest_at[guest.id, j] = self.model.NewBoolVar(f"v2:g:{guest.id}:{j}")
                    self.model.Add(sum(self.guest_at[guest.id, j] for j in range(self.n)) == 1)
                for j in range(self.n):
                    count = sum(self.guest_at[g.id, j] for g in members)
                    self.model.Add(count >= self.x[gid, j])
                    self.model.Add(count <= len(members) * self.x[gid, j])
            else:
                self.model.Add(sum(self.x[gid, j] for j in range(self.n)) == 1)
                self.loc[gid] = self.model.NewIntVar(0, self.n - 1, f"v2:loc:{gid}")
                self.model.Add(self.loc[gid] == sum(j * self.x[gid, j] for j in range(self.n)))
                for guest in members:
                    for j in range(self.n):
                        self.guest_at[guest.id, j] = self.x[gid, j]
        self.seats = {}
        for j, table in enumerate(self.tables):
            self.seats[j] = sum(self.guest_at[g.id, j] for g in problem.guests)
            self.model.Add(self.seats[j] <= table.capacity)
        self.assumptions = {}
        self.terms = []
        self._counts = {}
        self._choose = {}
        self._products = {}
        self._linked_neighbours()

    def guard(self, rule):
        key = rule.display_name
        if key not in self.assumptions:
            bit = self.model.NewBoolVar(f"v2:hard:{rule.id}")
            self.model.AddAssumption(bit)
            self.assumptions[key] = bit
        return self.assumptions[key]

    def matching(self, criterion):
        c = Criterion.model_validate(criterion)
        if c.subject != "guest":
            raise ValueError("This mechanism needs a guest criterion")
        return [g for g in self.problem.guests if match_guest(g, c)]

    def has_property(self, table, property_name):
        if property_name == "small_group_priority":
            return table.small_group_priority
        return property_name.casefold() in {tag.casefold() for tag in table.properties}

    def count(self, ids, j, tag):
        ids = tuple(sorted(ids))
        key = (ids, j)
        if key not in self._counts:
            value = self.model.NewIntVar(0, len(ids), f"v2:count:{len(self._counts)}:{tag}")
            self.model.Add(value == sum(self.guest_at[g, j] for g in ids))
            self._counts[key] = value
        return self._counts[key]

    def choose(self, ids, j, tag):
        ids = tuple(sorted(ids))
        key = (ids, j)
        if len(ids) < 2:
            return 0
        if key not in self._choose:
            limit = len(ids)
            z = self.model.NewIntVar(0, limit * (limit - 1) // 2,
                                     f"v2:choose:{len(self._choose)}:{tag}")
            self.model.AddElement(self.count(ids, j, tag),
                                  [i * (i - 1) // 2 for i in range(limit + 1)], z)
            self._choose[key] = z
        return self._choose[key]

    def product(self, left, right, j, tag):
        lhs = tuple(sorted(left))
        rhs = tuple(sorted(right))
        if not lhs or not rhs:
            return 0
        key = (lhs, rhs, j)
        if key not in self._products:
            value = self.model.NewIntVar(0, len(lhs) * len(rhs),
                                         f"v2:product:{len(self._products)}:{tag}")
            self.model.AddMultiplicationEquality(value, [
                self.count(lhs, j, tag+"-a"), self.count(rhs, j, tag+"-b"),
            ])
            self._products[key] = value
        return self._products[key]

    def _linked_neighbours(self):
        # Oversized parties may be split only into a connected cluster of
        # nearby drawn tables. An explicit operator split is unrestricted.
        explicit = set(self.problem.splittable_groups) | {
            i.group_id for i in self.problem.manual_instructions if i.allow_split
        }
        neighbours = neighbouring_tables(self.problem.layout, self.tables)
        for gid in sorted(self.split - explicit):
            # Directed rank tree: exact connected occupancy on the same floor.
            n = self.n
            roots = {j: self.model.NewBoolVar(f"v2:root:{gid}:{j}") for j in range(n)}
            ranks = {j: self.model.NewIntVar(0, n, f"v2:rank:{gid}:{j}") for j in range(n)}
            incoming = {j: [] for j in range(n)}
            for j in range(n):
                self.model.Add(roots[j] <= self.x[gid, j])
                self.model.Add(ranks[j] == 0).OnlyEnforceIf(roots[j])
            for i, adjacent in neighbours.items():
                for j in adjacent:
                    edge = self.model.NewBoolVar(f"v2:edge:{gid}:{i}:{j}")
                    incoming[j].append(edge)
                    self.model.Add(edge <= self.x[gid, i])
                    self.model.Add(ranks[j] >= ranks[i] + 1).OnlyEnforceIf(edge)
            self.model.Add(sum(roots.values()) == 1)
            for j in range(n):
                self.model.Add(sum(incoming[j]) + roots[j] == self.x[gid, j])

    def manual(self):
        for instruction in self.problem.manual_instructions:
            if instruction.action in ("unseat", "seat_pending"):
                continue
            gid = instruction.group_id
            label = SimpleNamespace(id=instruction.id, display_name="instruction:"+instruction.id)
            lit = self.guard(label)
            if instruction.action == "pin_placement":
                for guest_id, table_id in instruction.guest_tables.items():
                    j = next(j for j, table in enumerate(self.tables) if table.id == table_id)
                    self.model.Add(self.guest_at[guest_id, j] == 1).OnlyEnforceIf(lit)
                continue
            eligible = [j for j, table in enumerate(self.tables)
                        if (table.id == instruction.place_id if instruction.place_type == "table"
                            else table.zone_id == instruction.place_id)]
            if instruction.action == "not_here":
                for j in eligible:
                    self.model.Add(self.x[gid, j] == 0).OnlyEnforceIf(lit)
            elif instruction.place_type == "table":
                self.model.Add(self.x[gid, eligible[0]] == 1).OnlyEnforceIf(lit)
            else:
                for guest in self.groups[gid]:
                    self.model.Add(sum(self.guest_at[guest.id, j] for j in eligible) == 1).OnlyEnforceIf(lit)
        for guest_id, table_id in self.problem.locked_guest_tables.items():
            j = next(j for j, table in enumerate(self.tables) if table.id == table_id)
            self.model.Add(self.guest_at[guest_id, j] == 1)

    def solver(self):
        checker = cp_model.CpSolver()
        checker.parameters.max_time_in_seconds = self.problem.config.time_limit_seconds
        checker.parameters.num_search_workers = self.problem.config.workers
        checker.parameters.random_seed = self.problem.config.random_seed
        return checker


def _no_builder(rule, b):
    """Stage-only mechanisms have no CP-SAT point terms."""
    return


def _split_term(rule, b):
    for gid in b.split:
        b.terms.append(-rule.weight * (sum(b.x[gid, j] for j in range(b.n)) - 1))


def _holes_term(rule, b):
    for j, table in enumerate(b.tables):
        used = b.model.NewBoolVar(f"v2:used:{rule.id}:{j}")
        b.model.Add(b.seats[j] >= 1).OnlyEnforceIf(used)
        b.model.Add(b.seats[j] == 0).OnlyEnforceIf(used.Not())
        b.terms.append(-rule.weight * (table.capacity * used - b.seats[j]))


def _pair_term(rule, b, *, within):
    """Exact pair counts without O(guests²×tables) reified booleans."""
    criterion = Criterion.model_validate(rule.criterion)
    field = criterion.field
    known = [g for g in b.problem.guests if guest_value(g, field) is not None]
    selected = b.matching(rule.criterion)
    others = [g for g in known if g.id not in {p.id for p in selected}]
    categories = defaultdict(list)
    for guest in selected if criterion.value is not None else known:
        categories[str(guest_value(guest, field))].append(guest.id)

    per_family = defaultdict(list)
    for guest in known:
        per_family[group_id(guest)].append(guest)
    for j in range(b.n):
        def pair_count(members):
            ids = [g.id for g in members]
            all_pairs = b.choose(ids, j, rule.id)
            within_pairs = sum(
                b.choose([g.id for g in members if group_id(g) == gid], j, rule.id)
                for gid in per_family
            )
            return within_pairs if within else all_pairs - within_pairs

        if rule.polarity == "reward":
            contribution = sum(
                pair_count([g for g in (selected if criterion.value is not None else known)
                            if str(guest_value(g, field)) == val])
                for val in categories
            )
            b.terms.append(rule.weight * contribution)
        elif criterion.value is not None:
            selected_ids = [g.id for g in selected]
            others_ids = [g.id for g in others]
            all_pairs = b.product(selected_ids, others_ids, j, rule.id)
            inner = sum(b.product(
                [g.id for g in selected if group_id(g) == gid],
                [g.id for g in others if group_id(g) == gid], j, rule.id)
                for gid in per_family)
            b.terms.append(-rule.weight * (inner if within else all_pairs - inner))
        else:
            all_pairs = pair_count(known)
            same_pairs = sum(pair_count(
                [g for g in known if str(guest_value(g, field)) == val])
                for val in categories)
            b.terms.append(-rule.weight * (all_pairs - same_pairs))


def _own_attribute_grouping(rule, b):
    _pair_term(rule, b, within=True)


def _criterion_pairs(rule, b):
    _pair_term(rule, b, within=False)


def _pair_relation(rule, b):
    a, other = (b.lookup[target] for target in rule.targets)
    together = rule.relation == "together"
    if a == other:
        if rule.mode == "hard" and not together:
            b.model.Add(0 == 1).OnlyEnforceIf(b.guard(rule))
        elif rule.mode == "soft" and together:
            b.terms.append(rule.weight)
        return
    overlap = []
    for j in range(b.n):
        both = b.model.NewBoolVar(f"v2:pair:{rule.id}:{j}")
        b.model.AddMultiplicationEquality(both, [b.x[a, j], b.x[other, j]])
        overlap.append(both)
    same = b.model.NewBoolVar(f"v2:pair:any:{rule.id}")
    b.model.AddMaxEquality(same, overlap)
    if rule.mode == "hard":
        # Together means a shared table; apart means no shared table.
        b.model.Add(same == int(together)).OnlyEnforceIf(b.guard(rule))
    else:
        b.terms.append(rule.weight * (same if together else 1 - same))


def _placement_by_criterion(rule, b):
    matches = b.matching(rule.criterion)
    for guest in matches:
        for j, table in enumerate(b.tables):
            if table.zone_id in set(rule.zones):
                if rule.mode == "soft":
                    b.terms.append(rule.weight * b.guest_at[guest.id, j])
            elif rule.mode == "hard":
                b.model.Add(b.guest_at[guest.id, j] == 0).OnlyEnforceIf(b.guard(rule))


def _property_need(rule, b):
    matches = b.matching(rule.criterion)
    for guest in matches:
        for j, table in enumerate(b.tables):
            if b.has_property(table, rule.property):
                continue
            if rule.mode == "hard":
                b.model.Add(b.guest_at[guest.id, j] == 0).OnlyEnforceIf(b.guard(rule))
            else:
                b.terms.append(-rule.weight * b.guest_at[guest.id, j])


def _property_fit(rule, b):
    criterion = Criterion.model_validate(rule.criterion)
    for gid, members in b.groups.items():
        if not match_family(members, criterion):
            continue
        choices = [b.x[gid, j] for j, table in enumerate(b.tables)
                   if b.has_property(table, rule.property)]
        if not choices:
            continue
        flag = b.model.NewBoolVar(f"v2:fit:{rule.id}:{gid}")
        b.model.AddMaxEquality(flag, choices)
        b.terms.append(rule.weight * flag)


def _locked_assignment(rule, b):
    gid = b.lookup[rule.target]
    j = next(j for j, table in enumerate(b.tables) if table.id == rule.table)
    lit = b.guard(rule)
    for member in b.groups[gid]:
        b.model.Add(b.guest_at[member.id, j] == 1).OnlyEnforceIf(lit)


def _table_pattern(rule, b):
    for j, table in enumerate(b.tables):
        bits = []
        for k, clause in enumerate(rule.conditions):
            if clause["fact"] == "groups_at_table":
                fact = sum(b.x[gid, j] for gid in b.ids)
            elif clause["fact"] == "occupied_seats":
                fact = b.seats[j]
            elif clause["fact"] == "empty_seats":
                fact = table.capacity - b.seats[j]
            else:
                count_criterion = Criterion.model_validate(clause["criterion"])
                if count_criterion.subject != "guest":
                    raise ValueError("count() requires a guest criterion")
                matching = b.matching(clause["criterion"])
                fact = sum(b.guest_at[g.id, j] for g in matching)
            bits.append(add_comparison(b.model, fact, clause["op"], clause["value"],
                                       f"v2:pattern:{rule.id}:{j}:{k}"))
        matched = b.model.NewBoolVar(f"v2:pattern:{rule.id}:{j}:matched")
        b.model.Add(sum(bits) == len(bits)).OnlyEnforceIf(matched)
        b.model.Add(sum(bits) < len(bits)).OnlyEnforceIf(matched.Not())
        b.terms.append(rule.weight * matched * (1 if rule.polarity == "reward" else -1))


def _companionship(rule, b):
    old_interface = SimpleNamespace(id=rule.id, parameters={"exclude_groups": rule.exclusions or []})
    for lone in _zone_companionship_penalties(b.model, old_interface, b.ids, b.tables, b.x):
        b.terms.append(-rule.weight * lone)


BUILDERS = {
    ("intra", "split_term"): _split_term,
    ("intra", "own_attribute_grouping"): _own_attribute_grouping,
    ("inter", "pair_relation"): _pair_relation,
    ("inter", "criterion_pairs"): _criterion_pairs,
    ("inter", "table_pattern"): _table_pattern,
    ("inter", "companionship"): _companionship,
    ("venue", "placement_by_criterion"): _placement_by_criterion,
    ("venue", "property_need"): _property_need,
    ("venue", "tiered_placement"): _no_builder,
    ("venue", "holes_term"): _holes_term,
    ("venue", "property_fit"): _property_fit,
    ("venue", "locked_assignment"): _locked_assignment,
    ("stage", "priority_mark"): _no_builder,
}


def add_rule(rule, build):
    key = rule.engine, rule.mechanism
    if key not in BUILDERS:
        raise ValueError(f"No CP-SAT evaluator for {key}")
    BUILDERS[key](rule, build)


def resolve_tiers(build, rules):
    """Exact staged tier feasibility; never pay points for a tier."""
    selection = {}
    for rule in rules:
        if (rule.engine, rule.mechanism) != ("venue", "tiered_placement"):
            continue
        gid = build.lookup[rule.target]
        ranked = []
        covered = set()
        for tier in rule.tiers:
            zones = set(tier.get("zones", []))
            named = set(tier.get("tables", []))
            choice = {j for j, table in enumerate(build.tables)
                      if table.zone_id in zones or table.id in named}
            ranked.append(choice)
            covered |= choice
        fallback = set(range(build.n)) - covered
        if fallback:
            ranked.append(fallback)
        locked = False
        for rank, permitted in enumerate(ranked, 1):
            viable = {j for j in permitted
                      if build.tables[j].capacity >= len(build.groups[gid])}
            if not viable:
                continue
            # Probe candidate under every hard assumption.
            probe = build.model.NewBoolVar(f"v2:tier:{rule.id}:{rank}")
            build.model.Add(sum(build.x[gid, j] for j in viable) == 1).OnlyEnforceIf(probe)
            build.model.Add(sum(build.x[gid, j] for j in range(build.n) if j not in viable) == 0).OnlyEnforceIf(probe)
            build.model.AddAssumption(probe)
            tester = build.solver()
            status = tester.Solve(build.model)
            build.model.ClearAssumptions()
            for guard in build.assumptions.values():
                build.model.AddAssumption(guard)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                build.model.Add(sum(build.x[gid, j] for j in viable) == 1)
                build.model.Add(sum(build.x[gid, j] for j in range(build.n) if j not in viable) == 0)
                selection[rule.id] = rank
                locked = True
                break
            if status == cp_model.UNKNOWN:
                return selection, True
        if locked:
            continue
        if gid not in build.split:
            # The base solver will return infeasible if no whole tier fits.
            continue
        # The split was already explicitly permitted or structurally unavoidable.
        for rank, permitted in enumerate(ranked, 1):
            if sum(build.tables[j].capacity for j in permitted) < len(build.groups[gid]):
                continue
            probe = build.model.NewBoolVar(f"v2:tier:split:{rule.id}:{rank}")
            build.model.Add(sum(build.x[gid, j] for j in range(build.n) if j not in permitted) == 0).OnlyEnforceIf(probe)
            build.model.AddAssumption(probe)
            status = build.solver().Solve(build.model)
            build.model.ClearAssumptions()
            for guard in build.assumptions.values():
                build.model.AddAssumption(guard)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                build.model.Add(sum(build.x[gid, j] for j in range(build.n) if j not in permitted) == 0)
                selection[rule.id] = rank
                break
            if status == cp_model.UNKNOWN:
                return selection, True
    return selection, False
