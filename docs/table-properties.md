# Table properties and guest-driven needs (issue #9)

A table can carry **passive free-form tags** such as `accessible`, `aisle-edge`, `quiet`, or `near-exit`. A tag has **no score, priority or weight of its own**. The optimizer only consults a table's tags if a **guest-need rule** references one of them. Unreferenced tags do not affect scores, placements, or explanations.

## Portable JSON and the UI

The authoritative solver-facing property list is `Problem.tables[].properties` (optional list of strings, default `[]`). The portable venue-layout JSON can also embed the same list in `layout.floors[].tables[].properties`. The visual editor synchronizes both arrays when importing a layout file and whenever the operator edits table tags.

Tags can be entered when creating a table or edited later using the **Table tags (comma-separated)** field, without importing guests. For example:

```json
{
  "zones": [{"id": "hall", "name": "Main hall"}],
  "tables": [
    {"id": "A", "zone_id": "hall", "capacity": 4, "properties": ["accessible", "aisle-edge"]},
    {"id": "B", "zone_id": "hall", "capacity": 6, "properties": ["quiet"]}
  ],
  "layout": {"floors": [{
    "zone_id": "hall", "width": 400, "height": 300,
    "tables": [
      {"table_id": "A", "x": 20, "y": 20, "width": 140, "height": 110,
       "properties": ["accessible", "aisle-edge"]},
      {"table_id": "B", "x": 220, "y": 20, "width": 140, "height": 110,
       "properties": ["quiet"]}
    ]
  }]}
}
```

The `/v1/layouts/import` endpoint round-trips the layout-side tags. Only a complete solve request supplies the table-side tags, and only those are used by the solver. Keep both copies synchronized when writing directly against the API.

Named configuration templates from PR #10 capture both the table definitions and the complete venue layout. Consequently, once the changes are combined, their existing save/load, duplication and full JSON export/import workflows carry tags without any template-only rules or scores. This PR remains independent and targets `main`; #10 is not merged as of authoring.

## Guest-need rule

Add a rule of shape `table_property_need` with parameters:

- `attribute` (required): guest attribute, e.g. `mobility`
- `value` (optional): e.g. `wheelchair`. If omitted, any guest with that attribute qualifies.
- `property` (required): table tag, e.g. `accessible`.

Choose **Prefer** (soft) with a positive integer weight, or **Require** (hard) with no weight:

```json
{
  "id": "wheelchair-access",
  "shape": "table_property_need",
  "mode": "soft",
  "weight": 7,
  "parameters": {
    "attribute": "mobility",
    "value": "wheelchair",
    "property": "accessible"
  }
}
```

**Prefer:** Every matching guest earns **exactly 7 points** when their family/group is at a table with the `accessible` tag. A matching guest at an untagged table earns zero from this rule and contributes a 7-point missed preference to the compromises report. A family is never split, and members who do not have the specified need do not generate extra points.

**Require:** Every group containing at least one matching guest must be assigned to a tagged table. If no tagged table has sufficient capacity, the result is `infeasible` and its `conflicting_constraints` identifies the hard rule (and any relevant capacity assumptions). The optimizer does **not** silently violate the hard need or claim a feasible plan.

Tag comparison is case-insensitive; tag names are stored with their original capitalization after trimming outer whitespace. Empty or duplicate tags are rejected.

## Compatibility

All tag fields are optional. A legacy venue or problem without properties behaves exactly as before. Existing rule types and the floor-map and table-card renderers are unchanged. The API continues to be headless: the UI adds no scoring logic.
