# Venue editor — operator workflow and geometry contract

## Common setup

Open **Venue map**, create or select the floor, and click **Add table to floor**. The form starts with a proposed unused ID (editable) and ten chairs; the shape and scoring preferences are under **Shape and preferences**. New tables are assigned a non-overlapping location automatically, including within an optional room polygon. If no free position can fit their full footprint, adjust the layout rather than allowing an overlapping/out-of-room table.

The table list is compact and searchable. Click a row to expand its editor. **Table name** is a human-facing label shown in the map and table list. Renaming it **never changes the stable Table ID** used by hard pins, rules, manual instructions, imports, and exports. The old ID continues to work.

## Move or resize a table

Drag a drawn table to move it. Drag the small corner square to resize. Keyboard: focus the table in the map; arrow keys move it by 5 canvas units, Shift+Arrow adjusts width or height by 5. Circles retain equal width and height. Changes update the saved layout and invalidate a previously solved seating result, which remains available separately as a clearly outdated, read-only preview. Where the floor has an irregular outline, the server validates the move/resize against the entire table footprint before accepting it; on failure the drawing reverts and an error is displayed.

The numeric position and size fields remain available in the selected table editor; edits there are autosaved after backend validation. The browser never silently accepts a drawing that the server rejects.

## Drawing an irregular room

Click **Draw room outline** and click each wall corner on the canvas in order. Use **Undo corner** to remove the last point. Draw at least three corners, then click **Save outline**. A room outline is an optional array of coordinate pairs in the portable `FloorLayout.room_outline` JSON field, shared by the Python model, configuration API, import/export and the browser. Legacy rectangular layouts omit this field.

Outlines must be inside the floor canvas, contain between 3 and 100 corners, enclose a nonzero area, and never intersect themselves. Each table's full bounding rectangle must fit inside the polygon. This deliberately treats ellipse/circle footprints conservatively: if their bounding rectangle would extend through a wall, the placement is rejected even if the curve itself would fit. A failure keeps the uncommitted outline visible so it can be fixed; it does not corrupt the saved floor.

Click **Use rectangular floor** to remove the optional outline only after server validation. Saved configurations and JSON exports retain a validated outline.

## Coverage and limitations

- Covered: table counts, names, shape/size, move and resize controls, polygon persistence and server validation, legacy rectangular JSON, Python/browser polygon acceptance parity.
- Excluded: photographic floor-plan tracing, wall thickness, door/window CAD tools, polygon vertex drag editing, automatic rearrangement of all tables, assignment to individual numbered chairs. These are not part of Issues #121/#123.
- The independent prototype is kept at `prototypes/venue-editor-121-123.html`; visual acceptance of its density, controls, and tablet/mobile layout remains required before releasing this major screen change.
