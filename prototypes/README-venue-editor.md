# Venue editor interaction prototype — Issues #121 and #123

This is an interactive design review artifact, **not the production venue editor**. Open `prototypes/venue-editor-121-123.html` locally in a browser. No server, library or guest data is needed. All changes stay in-memory and reset on reload.

## Demonstrate before coding

- **Add table:** one action, automatically supplies a unique ID, ten chairs, shape and a starting position. The table is selected immediately.
- **Compact list:** one line per table, searchable, with its ID, readable name, chair count and shape. Only the selected table expands into editable controls.
- **Rename:** change a visible table name or its stable ID. In production an ID change must update or reject dependent rules/pins and instruction references atomically.
- **Map:** move with pointer drag or arrow keys, resize from the selected table's corner; numeric dimensions remain available under Advanced.
- **Room outline:** choose Edit room outline, click corners on the canvas, then Save outline; Reset restores the sample room.
- **Controls:** visible action words for high-risk, high-frequency and non-obvious actions; secondary icons may retain tooltips.
- **Layouts:** test at wide desktop, narrow desktop, tablet and mobile widths.

## Engineering handoff after owner visual review

The current backend model treats floor drawings as positions and shapes within rectangular bounds. A persistent irregular room outline requires an explicit schema/version and import/export plan, plus geometry checks for tables inside the polygon (including partial table intersections); the current prototype does not perform those checks.

Production table ID renaming must respect links in rules, manual instructions, layout keys, templates, plan references, and printed exports. A one-field rename would create referential corruption.

Before implementing, review the actual interactive prototype and record decisions on table default placement, room geometry, labels and accessibility. Then split into bounded backend schema, UI, and import/export PRs with Playwright tests. Do not interpret this file as full acceptance of either issue.
