# Open Issue acceptance map — 2026-11-19

This is the deliverable tracking table for the **29 open issues** visible before the integrated release. It is not an assertion that the production branch has been updated.

- Original PRs #100–#119 plus #124 were combined into draft integration PR #125; its full Python 3.11/3.12 and browser run passed at commit `9572dc6c` (GitHub Actions run 44580829837).
- Draft feature PR #127 extends that integration with the production venue editor for #121/#123; it has its own CI and explicit visual-acceptance gate. Prototype-only #126 is not a shipped fix.
- **No issue in this table is eligible for final closure solely because a draft branch passed CI.** Recheck each against the merge commit on `main`, and close only after demonstrated acceptance.

| Issue | Implementation PRs | Acceptance scope |
|---:|---|---|
| #56 | #107 | Solver hard-admissible split threshold |
| #57 | #110 | Stable imported family/person identities |
| #58 | #111 | Human-readable infeasibility diagnostics |
| #59 | #119 | Lap infants do not consume chairs |
| #60 | #102 | Non-overlapping automatic table placement |
| #62 | #112, #113 | Fewer split portions and solver objective |
| #63 | #113 | Explicit split mixing objective |
| #80 | #101 | Current README documentation |
| #81 | #100 | Living system orientation |
| #82 | #103 | Install and operator guides |
| #83 | #112 | Split priority against arbitrary weights |
| #84 | #112 | Unrestricted solver search regression |
| #85 | #104 | Browser guest-data retention and purge |
| #86 | #105 | Local-only API trust boundary |
| #87 | #116 | Canonical table metadata |
| #88 | #118 | Plan lifecycle invariants / API capabilities |
| #90 | #117 and branch audit | CI trigger cleanup done; old branch deletion NOT authorized |
| #91 | #114 | Validated table autosave |
| #92 | #106 | Compact rule accordion |
| #93 | #106 | Structured rule vocabulary |
| #94 | #106 and #111 | Readable rule details |
| #96 | #115 | Keyboard map/plan/rule navigation |
| #97 | #108 | README browser screenshots |
| #98 | #109 | Locked JavaScript dependencies |
| #99 | #103 | Fork-first decision record |
| #120 | #124 | Two-step destructive reset |
| #121 | #127 (prototype #126) | Compact table editor; owner visual review outstanding |
| #122 | #124 | Read-only stale solved seating |
| #123 | #127 (prototype #126) | Mouse resize, table rename, room outlines; owner visual review outstanding |

## Remaining external gates

1. Final-head Python, DOM and real Playwright checks on #127, including the joined solver and venue flows.
2. Owner visual click-review of #126's interactive venue prototype, followed by actual UI acceptance at mobile and desktop widths.
3. Authorized merge plan for stacked draft #125 and follow-on #127, with independent review. Main and production remain unchanged until then.
4. Branch-protection/use review and explicit authorization before deleting any of the 28 ancestor branches; nine divergent historical branches need per-commit reconciliation first. No silent pruning.
5. Recheck issue counts and link merge acceptance evidence in the issue tracker. In particular #88 frontend lifecycle consumption may require final verification that all status controls use the API semantics.

The evidence for the historical branch audit is in `docs/branch-hygiene-audit-2026-11-19.md`. This gate document intentionally excludes deployment, changes to external data, and deletion operations.
