# Split-family table purity scoring

The solver supports two distinct, operator-configured quality rules:

1. **Keep a family together** (`split_penalty` in legacy v1, `intra/split_term` in v2): negative score per extra occupied table; also activates lexicographic proof of the fewest possible occupied portions, described in [split-objective-proof.md](split-objective-proof.md), introduced by parent PR #112.
2. **Avoid mixing split families with other parties** (`split_mixing_penalty` in v1, `intra/split_mixing_term` in v2): negative score per **other party sharing a table with a family that occupies more than one table**. No penalty is applied when both families are ordinary unsplit parties; sharing tables remains normal for small groups.

For a split clan spanning T1 and T2, where unrelated family A also occupies T2, the mixing count is one. If unrelated families A and B both occupy T2, it is two. When two independently split clans share a table, each evaluates the other as one unwanted connection. The rule weight multiplies the count and is included in the exact Plan score and operator-facing compromises.

## Order of optimization

The optional split-minimization first pass (PR #112) takes precedence when `split_penalty` / `split_term` is active. Within that proven minimum table count, ordinary configurable soft rules — including split mixing — determine how cleanly families occupy tables. A very large unrelated preference may outweigh the mixing term, **but cannot outweigh a proven minimum split-count bound**. This is deliberate: mixing is avoidable quality, not a hard ban on sharing.

## Data rather than hard-coded preferences

Both rules are ordinary editable consideration records, not new special-case constants. The new mechanism is listed in the v2 mechanism registry and the legacy catalog, with a soft penalty polarity and an editable weight (catalog suggestion 100). A deployment or venue template can include active rule instances to avoid repeating configuration; the solver does not silently invent scores when an operator provided no rule.

## Verification and limitations

`tests/test_split_mixing_quality.py` checks unrestricted v1/v2 search for a clean three-table case and an unavoidable two-table mixing case with exact score parity. It also asserts zero mixing penalty for ordinary whole families sharing a table.

**Coverage/exclusions:** splittable families and every other party that shares their table, even if the other party is also split. This is not a ban on mixing, not a proof that the operator always remembers to enable a template rule, and not a quality guarantee for all feasible-but-not-optimal runs. Score reporting remains aligned with actual objective terms.
