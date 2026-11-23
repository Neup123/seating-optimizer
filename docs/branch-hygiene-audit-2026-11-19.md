# Branch hygiene audit — 2026-11-19

This inventory was checked against `main` at `fc6eaf1bfcad1064551bf75864dac5423d115c8c` using the GitHub compare API (`main...branch`). It covers *historical topic branches named in Issue #90*, not every newly opened PR branch. No branch was deleted, renamed or force-pushed.

## Fully incorporated (28 branches, ahead_by = 0)

The branch heads are already ancestors of main. These are potential deletion candidates **only after owner approval and branch-protection/use review**. Behind counts vary and do not indicate missing unique work:

- `docs/phase-1-approved-build-brief`
- `docs/scoring-principles`
- `docs/scoring-principles-two-rules`
- `feat/28-30-list-view-display`
- `feat/29-small-group-table-priority`
- `feat/31-adjacent-table-hardcase-fallback`
- `feat/32-composable-global-pattern-rules`
- `feat/53-interactive-views`
- `feat/54-reassign-assistant`
- `feat/62-63-solver-terms`
- `feat/64-low-priority`
- `feat/65-overflow-page`
- `feat/67-rule-instance-fields`
- `feat/70-zone-companionship`
- `feat/71-tiered-placement`
- `feature/phase-1-headless-optimizer`
- `feature/phase-2-venue-layout-print-exports`
- `feature/phase-3-visual-api-client`
- `fix/37-40-41-party-display`
- `fix/38-39-field-picker-pattern-layout`
- `fix/43-pattern-count-validation`
- `fix/47-people-list-import-column-headings`
- `fix/48-duplicate-import-mapping-notice`
- `fix/51-human-readable-attribute-fallback`
- `integrate/10-13-combined`
- `integrate/16-17-on-10-13`
- `feat/generic-engines-phase2`
- `feat/generic-engines-phase3`

## Divergent (9 branches, ahead_by > 0)

These carry commits not reachable from current main and **must not be bulk deleted**. A nonzero ahead count does not prove the *contents* are still needed; use per-commit equivalence and old PRs before deciding:

| Branch | Commits ahead of main |
| --- | ---: |
| `feat/20-printable-assignment-lists` | 3 |
| `feature/9-guest-driven-table-properties` | 6 |
| `fix/5-7-persist-and-templates` | 6 |
| `fix/6-friendly-api-retry` | 4 |
| `fix/8-multiple-table-cards-per-page` | 5 |
| `fix/14-infeasibility-diagnostics` | 1 |
| `fix/15-header-auto-detection` | 1 |
| `fix/21-22-template-and-rule-editor` | 1 |
| `fix/23-form-content-width` | 3 |

## Remaining acceptance

1. Inspect old PRs/branch protections before deleting the 28 fully incorporated refs; do not remove protected or active branches.
2. For each of the nine divergent branches, compare unique commits with `main` and the ongoing issue PRs, record whether superseded or still needed.
3. Delete branches only after explicit owner approval; the current connector offers no branch deletion action.
4. Recheck GitHub Actions maintained-branch configuration after #117 is merged to `main`. The integrated draft branch has the updated trigger config; `main` does not yet.
5. After cleanup, verify branch list and update #90. This inventory is documentation, **not Issue #90 completion**.

