# Venue editor: saved, draft and server validation

The venue editor stores each table's capacity and drawing together. Ordinary field changes are **auto-applied only after validating the entire proposed layout with the existing `/v1/layouts/import` API**.

1. While editing a field, the editor visibly reads **Editing draft**.
2. On change, the editor submits the complete candidate venue geometry and table metadata for server validation, without mutating the active layout yet.
3. If the server rejects it, the current table and layout remain unchanged, the unsaved value stays in the text field, and the inline status says **Not saved** with the reason. Correct the input and try again; there is no half-applied table edit.
4. On a successful response, the editor atomically commits the capacity, properties, priority flag, shape and coordinates, and shows **Server validated**.
5. Dragging or keyboard-moving a drawing clears the previously validated marker, because the drawing has changed after that validation. Use the **Validate layout** action before final export or solve when map positions have been moved.

The live API remains authoritative. This is not a second independent JavaScript geometry validator; the same API entrypoint is used for import and full-layout validation.

**Coverage:** DOM tests verify server-rejected geometry does not partially commit a valid early field, keeps the draft visible, then succeeds when the server accepts it. The tests do not substitute for real-browser manual drag/reload acceptance or collaborative multiuser editing (not supported).
