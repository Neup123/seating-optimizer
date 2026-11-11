# Generic engines phase 1 — migration ledger and verification status

## Scope

This is the implementation and audit ledger, **not** a certificate that
the external 29-verdict test-230 gate has passed. The target base is main
d6551f27b404ccec6f97dc8095b9f9bfd1da8263. The legacy solver stays
available through `solve(..., engine="legacy")`; the independent
v2 CP-SAT solver is selected through `solve(..., engine="generic")` or
`/v2/solve`. The v2 solver dispatches rules by engine/mechanism identity.

The legacy repository at this base does not contain either \`test-230/\` or
\`test-230-rerun/\` (confirmed from the recursive Git tree). Therefore the
source JSON instance list, venue, guests, historical plans and 29 verdicts
cannot yet be reproduced or verified from checked-in files.

## Planned migration from the owner-supplied inventory

| ID | Enabled | Engine / mechanism | Parameters |
| --- | --- | --- | --- |
| apart-cohen-levi | yes | inter / pair_relation | apart, registration:3 and registration:4, hard |
| together-anna-maria | yes | inter / pair_relation | together, registration:39 and registration:40, hard |
| wheelchair-accessible | yes | venue / property_need | mobility=wheelchair → accessible, hard |
| clan-upper-floor | yes | venue / placement_by_criterion | Floor Preference=Upper → upper, hard |
| seniors-ground-floor | yes | venue / placement_by_criterion | age_layer=Senior → ground, hard |
| hebrew-grouping | yes | inter / criterion_pairs | language=Hebrew, across, reward, w=2 |
| split-penalty | no | intra / split_term | penalty per additional table, w=1000000 |
| fill-holes | no | venue / holes_term | penalty per empty seat, w=1 |
| hebrew-mixing-penalty | no | inter / criterion_pairs | language=Hebrew, across, penalty, w=2 |
| zone-companionship | no | inter / companionship | penalty per lone group, exclusions=[], w=2 |
| clan-tiered-upper-first | no | venue / tiered_placement | registration:2; upper then ground |
| levi-not-ground-first | no | venue / tiered_placement | registration:4; upper then ground |
| low-priority-small-families | no | stage / priority_mark | party_size<4, grade=2 |
| low-priority-single-guest | no | stage / priority_mark | registration:41, grade=1 |
| capacity-ceiling-record | no | **RETIRED** | manual Table.capacity remains enforced unconditionally |
| small-group-priority | no | venue / property_fit | party_size<=2 and small_group_priority, reward, w=1 |
| lonely-last-seat-pattern | no | inter / table_pattern | groups_at_table==1 AND empty_seats==1, penalty, w=2 |
| pin-wheelchair-g3 | no | venue / locked_assignment | registration:34 → G3, hard |

**Capacity deletion is deliberate:** capacity-ceiling-record is retired as a
pseudo-rule, because capacity is a structural table fact, not an operator rule.
The migration converter retains the exact original record, position, and reason
in the report's retirement ledger for reversible audit. Of the 18 supplied
instances, 17 become v2 rules and one is a documented retirement. IDs and
instance metadata are preserved by the converter without branching on IDs.

## Critical semantic checks before declaring equivalence

1. **Legacy attribute grouping counted within-family pairs.** The requested
   generic inter-family mechanism uses \`scope=across\`. The existing
   \`tests/test_solver_objective_terms.py\` verifies 21 same-language pairs
   from a single seven-person family. This is an explicit compatibility
   question: a pure across-family migration can change the score. The v2
   migration retains the entire source payload for comparison and does not
   silently reinterpret it.
2. **Legacy soft table-property needs rewarded a satisfied guest.** The phase-1
   specification requires a penalty per affected guest whose need is unmet.
   These objectives can differ by a fixed offset and need a deliberate
   score-equivalence strategy rather than a falsely claimed equality.
3. **No automatic split-weight calibration.** The new validation warns when
   the ordinary objective pool threatens split dominance. The authored
   weight is never modified.
4. **No automatic unseating.** A failure to fit low-priority families remains
   reviewable, and an \`unseat\` manual instruction must come from the operator.

## Completed implementation surfaces

- \`generic_rules.py\`: typed criterion operators, 13 v2 mechanism identities,
  disabled-instance validation exemption, absent-field diagnostics, and a
  warning-only split-dominance guard (no weight mutation).
- \`generic_cp.py\`: CP-SAT builders for each mechanism, hard assumptions,
  structural chair capacities, permitted and oversized split rules,
  connected adjacent-table fallback, and tier feasibility probing.
- \`generic_solver.py\`: separate v2 model and solver, per-family S1 staging
  (D1), operator-only confirmed unseating and reason-bearing pending records
  (D2).
- \`rule_migration.py\`: shape-driven converter, exact original provenance,
  all 13 mappings, 17 retained instances plus the documented capacity
  pseudo-rule retirement.
- \`generic_evaluator.py\`: per-mechanism fixed-plan score proof with
  attributed, per-instance breakdown.
- \`api/app.py\` and \`api/openapi.yaml\`: parallel v2 solve, catalog, migration
  and schema-validation routes; v1 remains readable and usable for shadow
  comparison. No UI files were modified.

## External coordinator gate

The external corpus is intentionally not included in this repository.
The coordinator will run:

\`\`\`bash
python -m seating_optimizer.equivalence --corpus-dir /path/to/workspace
\`\`\`

The harness runs small random old-versus-new comparisons and the named
section-8 scenarios using the supplied files. The optional
\`equivalence-cases.json\` manifest specifies exact inputs and instructions
when necessary. The harness refuses missing inputs; the 29 historical
records are NOT counted as 29 executable checks without their evidence.

The coordinator still owns verification of 29 historical verdicts, score
2260, split score -1997596, hard-conflict naming, and plan-shape parity.
The scope and property-need semantic differences above may affect strict
score equivalence; neither the solver nor the harness silently alters
weights, changes operator decisions, or masks discrepancies.

Do not merge this branch without coordinator acceptance.
