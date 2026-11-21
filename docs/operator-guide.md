# Operator guide — seating optimizer

This guide describes the current browser planner. It is not a registration, CRM or messaging tool. Start locally at `http://127.0.0.1:8000/` after following [installation and acceptance](install-and-acceptance.md). Names and labels in the UI are English.

## Before importing

Keep an original copy of the registration CSV/XLSX outside the browser. Each row should identify a registration, party size and any attributes needed for placement. Check individual names and party grouping. **Never use a previously saved pin or pair rule without verifying that its target is still the intended person/party after edits to an imported guest sheet** (issue #57).

## 1. Guest import

1. Open **Guest import**; choose a CSV/XLSX file. Review the preview's detected source column mappings and sample values.
2. Correct mappings for the registered name, party size, optional group name/ID and free-form attributes. Keep stable IDs where the source supports them; do not confuse ID with the visible name.
3. Run the import. If row errors appear, correct the source or mappings and re-import; successful imports include the validated guest list.
4. Inspect totals and party names before adding rules.

## 2. Venue map

1. Open **Venue map**; create named floors with canvas dimensions, or import a saved JSON/SVG geometry.
2. Add numbered tables to each floor. Give each its own capacity; the capacity is the maximum chairs, not an average size.
3. Adjust table positions by dragging or by exact X/Y/width/height fields. In the current editor, changed values can be saved on field change; confirm the save notice.
4. Add table properties only when relevant to a rule. A table property or small-group priority marker does not itself grant a score unless the corresponding consideration is active.
5. Validate the complete layout. If geometry fails, repair the referenced table; do not proceed on an invalid map.
6. Export a standalone layout/configuration JSON as a reusable backup rather than relying only on local browser storage.

## 3. Considerations and scoring

1. Open **Rules**. Choose the **Relation** (engine) and then **Mechanism**. Click the plus button to add an instance.
2. Use the compact list to enable/disable instances, read name and effect, and expand a rule to edit its details. The actual operative rule record is submitted to the API; it is never evaluated by browser JavaScript.
3. Set hard restrictions only for mandatory requirements (e.g., floor accessibility). Set soft preferences with weights. Large soft weights may dominate other ordinary preferences; avoid claiming absolute priority when its implementation does not enforce it.
4. For a rule referring to a specific family, choose/check the actual current party, not an outdated spreadsheet row number. Review every saved rule after the guest list changes.
5. For attributes or table properties, use observed values when available and verify exact spelling of any custom value.
6. Disable a rule to retain its configuration without applying it. Removing an instance deletes its definition from the current plan.

## 4. Optimize and inspect

1. Open **Seating plan** and run the solve. Submit guests, venue, current rule instances and the configured time limit.
2. Read the status carefully: **OPTIMAL** proves the best result for the modeled objective; **FEASIBLE** satisfies hard rules but may improve with longer search; **INFEASIBLE** means no solution under the present hard constraints; **UNKNOWN** did not confirm a solution within the limit; **needs_review** requires an operator decision about pending families.
3. Inspect the table view and floor view; use search, floor filters and selection checkboxes. Selecting a person is different from selecting their whole party.
4. Review the reasons and compromise information before printing. A rule can change the assignment and the resulting score.
5. For a blocked placement, examine capacity and rule constraints rather than trying to force invalid output.

## 5. Reassign, pending guests and overflow

1. Select the party or person in the working view; choose **Move to** or **Not here** to request solver-checked alternatives.
2. Check the proposed alternative's affected parties and warnings, then explicitly apply a chosen option. Reassignment is solved against the actual constraints.
3. An unseated low-priority family can appear in **needs_review**. The review list and operator-selected not-seated export are separate from the main assignment.
4. To move a whole party to the not-seated list, select the *whole party* and confirm the removal. A single-person selection never silently excludes the full family.
5. Changes to guests, map or rules invalidate previously solved assignments; rerun the solver and recheck reports.

## 6. Export, print and preserve

- Print the per-table cards, people lists, grouped lists, not-seated list and floor-map PDF/SVG as appropriate. The plan contains **table assignments**, not numbered chairs within a table.
- Use JSON export for machine-readable results and full configuration JSON for reusable venue/rule setup.
- The current browser stores a local session in `localStorage` and may restore it after reload. The API stores no server-side account history. On a shared browser, clear site data when appropriate and treat PDFs and source spreadsheets as sensitive event records.
- Printed seating plans should be checked against registration totals, party identity, chair capacity, pending/unseated guests and last-minute changes.

## Common problems

| Symptom | Action |
| --- | --- |
| Mapping or import errors | Correct column mapping/source row and import again |
| Old pair or pin target looks wrong | Inspect the actual current group ID/name and recreate the rule; #57 tracks stability |
| Table cannot be placed | Check floor size and existing geometry; #60 tracks automatic first placement |
| Solver infeasible | Check hard restrictions, adjacency, individual table capacities and group size |
| Plan feasible but scattered | Compare solve time and split quality; #62/#63/#83/#84 track objective guarantees |
| Pending review | Inspect the operator's choices; do not print an incomplete seating result as fully assigned |
| Reload failed to restore | Recover original source and exported configuration; browser storage is not a backup |

No direct network exposure is supported without an authenticated gateway and security review (issue #86). This guide documents operator controls; it does not substitute for an event-specific QA run.
