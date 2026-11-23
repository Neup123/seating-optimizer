# Split quality — lexicographic objective and proof status

The solver treats family cohesion as a **first-class optimization phase** when an active split-avoidance consideration is present. This avoids relying on an ordinary weight (which can be exceeded by another operator-configured preference) to protect a nearly absolute principle.

## Two-stage optimization

1. Find the lowest possible number of **occupied tables across automatically or explicitly splittable parties**, subject to all hard constraints, using CP-SAT. This is equivalent to the fewest extra family portions because the number of eligible split families is fixed.
2. If phase 1 found a feasible arrangement, constrain the number of occupied split tables to no more than its best known value.
3. Optimize the **original, fully rule-driven score** under that bound. The reported plan score and breakdown still use only the rule-instance contributions; no hidden points are inserted.

The feature is enabled only when the request includes an enabled legacy `split_penalty` rule or a v2 `intra/split_term` instance. Without such a rule, the existing single-pass objective remains unchanged.

## Proof and timeout semantics

The total requested solve-time budget is shared by both phases (nominally 40% for split-count proof, the remainder for score search). If the split phase proves **OPTIMAL**, its count is globally minimal among hard-feasible arrangements, regardless of ordinary weights, and phase 2 optimizes score within that count.

If phase 1 finds only **FEASIBLE**, the best count is a valid upper bound, but a lower count may exist. The final Plan must never claim lexicographic OPTIMAL, even if phase 2 proves its *restricted* score optimum; it returns FEASIBLE and explains that split priority is unproven. If the first phase finds no placement, the second phase reverts to searching the original hard-feasible model; a successful result must similarly never claim a proven split priority.

This also preserves the distinction between UNKNOWN (search timed out without a feasible plan), INFEASIBLE (proven no hard-feasible arrangement) and FEASIBLE (valid but not proven globally best).

## Relation to mixed-table quality

A split may still share tables with other parties if that satisfies hard constraints or improves secondary preferences. The lexicographic phase guarantees *fewest occupied portions*, not “no mixed tables”. Dedicated split mixing quality and the unit/weight of unwanted connections remain independently tracked in #62/#63. Do not describe mixed-table avoidance as already guaranteed.

## Verification

`tests/test_lexicographic_split_search.py` provides unrestricted v1 and generic v2 solver cases with a deliberately tiny split penalty (1) against 100,000-point preferences. The solver is free to choose two or three portions; it must choose two when that minimum is proven. It also tests that without the rule, ordinary scoring can choose three, demonstrating that the priority is genuinely enabled by an operator consideration.

**Coverage/exclusions:** validates lexicographic semantics for rule-enabled split counts and honest proof status. It does not prove the optimum within a 5-second runtime for every 230/300-guest event, guarantee un-mixed whole tables, or replace full-load performance acceptance.
