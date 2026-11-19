# Combined acceptance gate — 2026-11-19

This **draft** branch contains the combined, conflict-reconciled implementation from source PRs #100, #101, #102, #103, #104, #105, #106 (via #111), #107, #110, #111, #112 (via #113), #113, #114, #115, #116, #118, #119, and #124.

The conflict resolver in `scripts/resolve_issue_merges.py` has an explicit file/hunk policy. It does **not** blindly prefer either side. A green individual PR is not integration acceptance.

## Gates still required

1. Python 3.11 and 3.12 unit, API, golden, and contract suites on this exact combined commit.
2. DOM and Playwright browser suites on the exact combined commit.
3. End-to-end operator scenarios: table autosave and canonical metadata consistency, stable guest identity on import/reorder, lap infant capacity and export, edit-induced stale plans, destructive reset, keyboard interactions, visual overflow/resize.
4. Recheck all issue-specific acceptance criteria against main only after approved merge. Do not automatically close any linked issue from this draft.
5. Include the workflow-changing PRs #108, #109 and #117 through a principal with GitHub Actions workflow write permission; this integration bot cannot push their workflow commits.
6. Review the interactive prototype PR #126 for the still-open venue screen requests #121/#123; the prototype is not a production solution.
7. Review old/divergent branches under #90 separately, preserving unique commits; do not delete them by inference.

No production deployment is authorized by this integration PR.
