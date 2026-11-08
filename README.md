# Seating Plan Optimizer

**Phases 1–3: explainable seating optimization with a visual API client.** The Python core contains the CP-SAT solver, rule models, guest and venue importers, structured per-floor geometry and pluggable exports. FastAPI exposes every capability, while the responsive browser client handles input, editing and presentation only. Individual seat ordering remains out of scope.

The approved [build brief](docs/build-plan.md) is the authoritative project plan across all phases.

**License:** [LICENSE](LICENSE) is the owner's Business Source License 1.1, including the Additional Use Grant. Read it before production use.

## Installation

Python 3.11+ is required.

    python -m venv .venv
    . .venv/bin/activate
    python -m pip install -e ".[api,test]"
    python -m pytest -v -s

Serve the API, visual planner and Scalar API reference together:

    uvicorn seating_optimizer.api.app:app --host 127.0.0.1 --port 8000

Open http://127.0.0.1:8000/ for the **visual planner**.

The docs are served at http://127.0.0.1:8000/docs, using **Scalar** (not Swagger). The checked-in OpenAPI 3.1 YAML is served at /openapi.yaml.

## Python code example

    from seating_optimizer import Guest, Problem, Rule, Table, Zone, solve, render

    problem = Problem(
        session_id="friday-dinner",
        zones=[Zone(id="ground", name="Ground floor"),
               Zone(id="upstairs", name="First floor")],
        tables=[Table(id="T1", zone_id="ground", capacity=4),
                Table(id="T2", zone_id="upstairs", capacity=6)],
        guests=[
            Guest(id="alice", name="Alice", group_id="family-1",
                  attributes={"language": "English", "mobility": "wheelchair"}),
            Guest(id="bob", name="Bob", group_id="family-1",
                  attributes={"language": "English"}),
            Guest(id="cara", name="Cara", attributes={"language": "French"}),
        ],
        rules=[
            Rule(id="access", shape="zone_restriction", mode="hard",
                 parameters={"attribute": "mobility", "value": "wheelchair",
                             "zone": "ground"}),
            Rule(id="languages", shape="attribute_grouping", mode="soft",
                 weight=6, parameters={"attribute": "language"}),
            Rule(id="fill", shape="fill_efficiency", mode="soft", weight=2),
        ],
    )
    plan = solve(problem)
    print(plan.status, plan.total_score)
    print(render(plan, "table"))
    full_plan_json = render(plan, "json")

Every meal sitting has its own Problem and session_id; zones and tables can be reused. Every table has its own chair capacity, enforced as a hard ceiling. Every group of guests with the same group_id shares one placement variable: groups can never split.

Possible statuses are optimal, feasible, infeasible and unknown. Infeasible plans report a sufficient (not necessarily minimal) named conflicting-constraint set. Unknown means the solve timed out without a feasible plan, **not** proven infeasibility. Configurable SolverConfig fields: time_limit_seconds (default 5), workers (default 8) and random_seed.

## Operator-defined rule records

Rules always contain an id, shape, mode (hard or soft), parameters, and a positive integer weight **only for soft** rules. No scoring weights are hardcoded. Attributes are user-defined data keys and scalar values; new kinds require no code changes.

| Shape | Parameters | Interpretation |
| --- | --- | --- |
| attribute_grouping | attribute; optional value | Per same-value guest pair at the same table, earn the rule's weight. Hard mode requires these groups together. |
| zone_restriction | attribute, optional value, zone or allowed_zones | Hard: only allowed zone(s). Soft: each matching guest earns points when their whole group uses an allowed zone. |
| pair | left, right, relation: together or apart | Hard or weighted relationship between guest IDs, group IDs or unique guest names. |
| capacity | none | Always hard, enforced per table even if no explicit rule record exists. |
| fill_efficiency | none | Penalize empty chairs at **occupied** tables (holes), by its weight. Completely unused tables are not penalized. |
| pin | target, table | Hard pin for any member or their group, respected on re-solve. |

Hard zone restrictions propagate from any guest to the **entire** atomic group. Contradictory member restrictions lead to an infeasible result, not splitting or hard-rule violation. A weighted rule contributes points only when its condition holds; the plan includes per-group rule-based reasons with contributed points, score breakdown per soft rule, compromises for forgone preferences, and remaining chairs per table. Shared pair points are distributed fairly in assignment-level reasons.

## CSV and XLSX import

One spreadsheet row represents one registration with required name and size columns. A size of 3 creates three uniquely identified guests under one group_id. The source header to canonical target manual mapping is always available, including free-form targets such as attribute.food:

    from seating_optimizer import import_registrations

    csv_bytes = b"Guest Name,Party Size,Language\nFamily Alpha,3,English\n"
    automatic = import_registrations(csv_bytes, "guests.csv")
    assert not automatic.has_errors
    manual = import_registrations(
        b"Participant,Count,Allergies\nAlice,1,Peanuts\n",
        "guests.csv",
        mapping={"Participant": "name", "Count": "size",
                 "Allergies": "attribute.allergies"},
    )

Default auto-detection aliases are data in src/seating_optimizer/header_aliases.json. Pass an aliases dictionary to replace them. Manual mappings override auto-detection. Unknown source columns with values are preserved as free-form attributes, not discarded. ImportResult contains guests, effective mapping, rows seen/imported and row-numbered errors and warnings. Missing/invalid sizes, duplicate names and malformed rows are reported. Duplicate registrations are not silently merged. **Correct reported errors before solving.**

## REST (headless parity)

- POST /v1/import: JSON body with filename and base64 content_base64, optional mapping (source-header to target) and header_aliases. Returns ImportResult.
- POST /v1/solve: JSON Problem body. Returns Plan with status and reasons, even on infeasible cases.
- POST /v1/exports/table: JSON Plan body. Returns text/plain table-by-table guest list with reasons and compromises.
- POST /v1/exports/json: JSON Plan body. Returns the complete application/json Plan.
- POST /v1/layouts/import: JSON array of base64-encoded structured JSON and/or numbered SVG layout files; optional zones and tables validate references. Returns VenueLayout.
- POST /v1/exports/floor-map/svg: Plan with layout; returns standalone SVG documents, one per floor, in a JSON bundle.
- POST /v1/exports/floor-map/pdf: Plan with layout; returns a vector PDF with one page per floor.
- POST /v1/exports/table-cards/pdf: Plan; returns an A5 landscape PDF, one card per table.
- GET /healthz, GET /openapi.yaml, GET /docs.

A minimal client can save a problem to problem.json and send:

    curl -s http://127.0.0.1:8000/v1/solve \
      -H 'content-type: application/json' -d @problem.json > plan.json
    curl -s http://127.0.0.1:8000/v1/exports/table \
      -H 'content-type: application/json' -d @plan.json

The API has no persistent state and no history dependency. An integration can pass an updated problem to solve again with pins added or edited. The Python render(plan, format, renderers=...) hook accepts a caller-provided renderer mapping. Built-in formats are table, json, floor-map-svg, floor-map-pdf and table-cards-pdf.

## Verification

The suite includes unit tests for each rule, atomic grouping and wheelchair-family propagation, unique table capacities, contradictory hard rules naming conflicts, soft compromises, fill efficiency and re-solve pins. Import tests cover CSV, XLSX, manual mapping, auto-detection and malformed data. API tests validate live routes and JSON responses against the checked-in YAML and verify Scalar documentation. The golden scenario generates **120 guests in 60 families**, three languages, mixed age layers, a wheelchair family, two floors and 12 differently located tables; it checks all hard invariants and prints GOLDEN_120_SOLVE_SECONDS in the test logs.

The solver targets a few seconds for practical events around 300 guests, subject to instance difficulty, hardware and time limit. A feasible plan is not misreported as optimal.


## Phase 2 — venue geometry and printable exports

VenueLayout is optional data on Problem and is returned unchanged on Plan when solved. Each FloorLayout contains a zone_id, width, height and drawings for zero or more tables. A TableDrawing has table_id, x, y, width, height and shape (rectangle, ellipse or circle). Coordinates have a top-left origin in a floor canvas of the specified dimensions. Tables still belong to exactly one zone and retain their own hard chair capacities. Layout never changes the solver objective or constraints.

Validation rejects duplicate floor/table drawings, drawings outside the floor, negative or zero dimensions, noncircular circles and tables on a mismatched floor. Partial layouts can be saved and solved but the floor-map exporters require a drawing for every table, failing explicitly instead of silently omitting assigned groups. Table cards do not require a layout.

### Structured JSON and numbered SVG draft import

See examples/layout.json for a full two-floor structured geometry file and examples/numbered-ground.svg for a single-floor numbered SVG draft.

    from seating_optimizer import import_layout, import_layout_files, solve
    from seating_optimizer import render_floor_svg, render_floor_pdf, render_table_cards_pdf

    layout = import_layout(open("examples/layout.json", "rb").read(),
                           "layout.json", zones=problem.zones, tables=problem.tables)
    plan = solve(problem.model_copy(update={"layout": layout}))
    floor_svg_pages = render_floor_svg(plan).pages
    floor_pdf_bytes = render_floor_pdf(plan)
    cards_pdf_bytes = render_table_cards_pdf(plan)

A structured JSON layout contains a floors list; each floor contains its zone_id, dimensions and tables list. A numbered SVG draft is converted to equivalent JSON data when:
- The SVG root has data-zone-id and viewBox with a zero origin (e.g. 0 0 600 400).
- Every numbered table is a g element with data-table-id matching the actual venue table, containing precisely one rect, ellipse or circle and, optionally, a text label matching that ID.
- No SVG transforms or external entities are used. The importer rejects unsupported transformations and ambiguous labels instead of making guesses.

Multiple draft SVGs and/or JSON layouts may be combined by import_layout_files in Python or by POST /v1/layouts/import with a list of base64 file entries. The same layout records are usable directly by future visual clients.

Raster scans, unannotated PDF sketches and arbitrary unlabeled SVGs require operator-guided annotation/conversion; Phase 2 does not attempt OCR or guess table identities. This limitation is deliberate.

### Exports and headless API parity

- Floor-map SVG: one standalone SVG page per floor, with every group label printed inside its assigned table drawing. Table/group identifiers are available in data-table-id and data-group-id attributes for verification and later editor reuse.
- Floor-map PDF: matching vector geometry, one printable page per floor, including assigned group names.
- Table cards PDF: one A5 landscape card per table, including empty tables; shows table/zone, occupied seats, all families and their guest names.

In Python, render(plan, "floor-map-svg") returns a JSON string of pages and render(plan, "floor-map-pdf") or render(plan, "table-cards-pdf") returns PDF bytes. The same three operations are available in REST with typed OpenAPI YAML rendered by Scalar. All existing Phase 1 imports and render formats remain valid.

Print renderers report an error instead of dropping names when layouts are too small. PDF output prefers installed Unicode TrueType fonts, and uses the built-in font when available; deployments without a Unicode font must provide a suitable system font to print non-Latin guest names. SVG preserves Unicode directly.

### Open questions preserved from the approved build plan

Individual seat ORDER is out of scope. Multiple sittings remain separate solves over the same fixed venue. Joining or splitting physical tables per event remains undecided and is not implemented. Phase 3 adds the visual API client; the core/REST parity remains intact.


## Phase 3 — browser planner (no UI-only optimization)

The no-build, English-language browser interface ships with the FastAPI application at the root URL (/). It requires no frontend framework or Node.js at runtime; JavaScript, CSS and HTML are packaged with the Python API.

**Workflow:**

1. **Guest import:** choose CSV/XLSX. The browser sends the file to POST /v1/import/preview and shows every source column, automatically detected mapping and sample values. Correct header-to-field mapping manually, including free-form attribute fields. POST /v1/import performs the actual import and returns every validation issue. Imports containing errors are blocked in the UI, not silently merged or discarded.
2. **Venue map editor:** create floors and numbered tables with independent chair counts; position rectangles, ellipses or circles by dragging or entering exact coordinates. Import structured JSON or annotated SVG files through POST /v1/layouts/import. Validate the edited layout through that same endpoint and export the JSON geometry to reuse in code or future edits.
3. **Rule editor:** GET /v1/rules/catalog supplies metadata for **all six** rule shapes, their parameter fields and HARD/soft modes. Add, update, or remove rule records, supply positive weights for soft rules, and provide group/guest/table/zone references. The browser does not compute scores or evaluate rules.
4. **Solve and review:** the client sends a Problem with current guests, table capacities, layout, rules and time limit to POST /v1/solve. View the server's status, rule-by-rule reasons, compromise report and table utilization. Switch between the classic table export, SVG floor maps, printable PDF table cards and complete JSON plan. Download vector floor-map PDF or table-card PDF. Every plan view comes from the API, including the /v1/exports/table, /v1/exports/floor-map/svg, /v1/exports/floor-map/pdf, /v1/exports/table-cards/pdf and /v1/exports/json endpoints.

The UI does not manage registration systems, payments, messaging, CRM, or persistent accounts. The active draft lives in the current browser session; preserve the source spreadsheets, rules and layouts outside the UI. Reloading the page resets the in-memory form state. This is a browser client over stateless APIs, not a separate backend.

### API additions

- POST /v1/import/preview: accepts the existing base64 ImportRequest and returns ImportPreview (headers, automatic/current column mappings, sample rows, row issues and row count). Python exposes preview_registrations() for the same headless capability.
- GET /v1/rules/catalog: returns RuleCatalog with data-defined field metadata. Python exposes rule_catalog(). These records describe existing solver rule shapes; only the solver implements the semantics.

Both operations are documented in the checked-in OpenAPI YAML, still rendered with **Scalar** at /docs.

### UI verification

Core/API tests:

    python -m pip install -e ".[api,test]"
    python -m pytest -v -s

Browser DOM tests (Node.js 22 required **only for testing**):

    npm install
    npm run test:ui

Full real-browser golden E2E (also requires Chromium installed by Playwright):

    npx playwright install chromium
    npm run test:browser

The browser test launches the actual FastAPI server, uploads **60 two-person registrations (120 guests)**, imports two-floor/12-table layout data, sets chair capacities, creates hard and soft rules through the visual editor, calls the real CP-SAT solver, and visits all four plan views. It asserts zero hard violations and wheelchair-family propagation. The CI workflow runs Python 3.11/3.12 core tests plus DOM and Chromium browser tests; the golden browser E2E does not mock a solver.
