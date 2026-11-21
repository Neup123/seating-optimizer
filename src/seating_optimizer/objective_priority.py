"""Lexicographic CP-SAT optimization for operator-enabled split avoidance.

No duplicate scoring equation: this function optimizes the *same* model and
returns the final solver for the existing exact by-rule scoring evaluator.
"""
from __future__ import annotations

from time import perf_counter

from ortools.sat.python import cp_model


def optimize_with_split_priority(model, scoring_terms, split_occupancy, config,
                                 solver_factory=None):
    """First minimize occupied split tables, then optimize ordinary rule points.

    Returns (solver, CP-SAT status, priority_proven, seconds). A guarantee is
    reported only when the first pass actually proved its optimum. A feasible
    but unproven first pass can bound the second pass, but never marks the
    final result OPTIMAL for the *lexicographic* objective.
    """
    def create_solver(seconds):
        solver = solver_factory() if solver_factory else cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.01, seconds)
        solver.parameters.num_search_workers = config.workers
        solver.parameters.random_seed = config.random_seed
        return solver

    start = perf_counter()
    time_limit = config.time_limit_seconds
    priority_proven = True
    if split_occupancy:
        # The number of split parties is fixed for the request. Minimizing
        # total occupied tables is therefore exactly minimizing extra portions.
        target = sum(split_occupancy)
        model.Minimize(target)
        probe = create_solver(max(0.01, time_limit * 0.4))
        first = probe.Solve(model)
        if first in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            best = round(probe.ObjectiveValue())
            model.Add(target <= best)
        priority_proven = first == cp_model.OPTIMAL
    model.Maximize(sum(scoring_terms))
    remaining = max(0.01, time_limit - (perf_counter() - start))
    solver = create_solver(remaining)
    status = solver.Solve(model)
    return solver, status, priority_proven, perf_counter() - start


def split_mixing_terms(model, split_groups, all_groups, tables_count, x, tag):
    """Per split family/table, count OTHER parties sharing that table.

    A party occupying only one table is not a split and incurs zero mixing
    penalty, even if it was permitted to split. Each pair is assessed from
    the point of view of the splittable party, with no hard-coded weight.
    """
    contributions=[]
    for gid in sorted(split_groups):
        used_count=sum(x[gid,j] for j in range(tables_count))
        actually_split=model.NewBoolVar(f"mix:{tag}:{gid}:split")
        model.Add(used_count>=2).OnlyEnforceIf(actually_split)
        model.Add(used_count<=1).OnlyEnforceIf(actually_split.Not())
        for j in range(tables_count):
            active=model.NewBoolVar(f"mix:{tag}:{gid}:table:{j}")
            model.AddBoolAnd([actually_split,x[gid,j]]).OnlyEnforceIf(active)
            model.AddBoolOr([actually_split.Not(),x[gid,j].Not(),active])
            others=sum(x[other,j] for other in all_groups if other!=gid)
            mixed=model.NewIntVar(0,len(all_groups)-1,f"mix:{tag}:{gid}:{j}:others")
            model.Add(mixed==others).OnlyEnforceIf(active)
            model.Add(mixed==0).OnlyEnforceIf(active.Not())
            contributions.append(mixed)
    return contributions
