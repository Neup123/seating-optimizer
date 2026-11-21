# Keyboard interaction contract

The browser planner supports native tab navigation and explicit keyboard
shortcuts where a repeated interactive list or map needs directional movement.

| Surface | Keys | Effect |
| --- | --- | --- |
| Rule editor accordion headers | Tab, Up/Down, Enter/Space, Escape | Tab reaches each toggle; arrows move focus between editor headers; Enter/Space opens/closes one rule; Escape closes an expanded rule and restores focus to its header |
| Rule deletion | Delete button, Enter/Space, then Confirm or Cancel | Deletion is two-step; the rule is preserved until confirmed. Escape cancels the pending removal |
| Working assignment rows | Up/Down, Space, Enter, Escape | Arrows move among visible rows; Space toggles party selection; Enter opens/closes details; Escape closes details or active reassignment mode, retaining row focus |
| Person/party selection checkboxes | Tab, Space | Use the native checkbox for selecting a whole party or one person; checkboxes do not inherit row shortcuts |
| Reassignment controls | Tab, Enter, Escape | Native controls and actions; Escape closes an active reassignment editor and returns focus to the selection toolbar |
| Working floor map | Up/Down/Left/Right, Enter/Space, Escape | Arrows move focus between table shapes; Enter/Space focuses a table; Escape clears the focused table and returns focus to floor selector |
| Venue map | Arrows | Move the focused table drawing by five canvas units per keypress, constrained to floor boundaries; exact coordinate fields remain an alternative |

Avoid interpreting these unmodified keys when a nested input, button or checkbox already owns the key. Keyboard shortcuts operate only while the corresponding row or map shape has focus. Do not delete a family assignment by pressing Delete on a row; removing people has larger consequences and must continue through its explicit confirmation flow.

**Verification:** `tests/ui/keyboard_navigation.test.mjs` covers arrow navigation, focused row selection, expansion, escape recovery and rule deletion confirmation in jsdom. Existing Playwright browser tests exercise the live map and UI; a separate manual keyboard-only browser sweep, visible focus ring and mobile/RTL review still improve acceptance. The application uses English UI strings; language additions are not inferred.

## Integration acceptance

Exercise the real browser with keyboard only: move focus through the working plan, operate venue shapes with arrow keys, invoke rule actions, close transient controls with Escape, and confirm focus restoration. Re-run after integrating other in-flight UI PRs; a standalone green test does not prove integrated layout and focus behavior.
