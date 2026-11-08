# Seating Plan Optimizer

**Phase 1: a fully headless, explainable seating optimizer** for one event meal sitting at a time. A reusable Python package contains the models, dynamic rule evaluation, Google OR-Tools CP-SAT solver, importer and two export renderers. A thin FastAPI layer exposes every capability. No seating UI, floor map, table cards or individual seat ordering are included.

**License:** [LICENSE](LICENSE) is the owner's Business Source License 1.1, including the Additional Use Grant. Read it before production use.

## Installation

Python 3.11+ is required.

    python -m venv .venv
    . .venv/bin/activate
    python -m pip install -e ".[api,test]"
    python -m pytest -v -s

Serve REST and Scalar API reference:

    uvicorn seating_optimizer.api.app:app --host 127.0.0.1 --port 8000

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
- GET /healthz, GET /openapi.yaml, GET /docs.

A minimal client can save a problem to problem.json and send:

    curl -s http://127.0.0.1:8000/v1/solve \
      -H 'content-type: application/json' -d @problem.json > plan.json
    curl -s http://127.0.0.1:8000/v1/exports/table \
      -H 'content-type: application/json' -d @plan.json

The API has no persistent state and no history dependency. An integration can pass an updated problem to solve again with pins added or edited. The Python render(plan, format, renderers=...) hook accepts a caller-provided renderer mapping. Phase 1 ships exactly two default formats: table and json.

## Verification

The suite includes unit tests for each rule, atomic grouping and wheelchair-family propagation, unique table capacities, contradictory hard rules naming conflicts, soft compromises, fill efficiency and re-solve pins. Import tests cover CSV, XLSX, manual mapping, auto-detection and malformed data. API tests validate live routes and JSON responses against the checked-in YAML and verify Scalar documentation. The golden scenario generates **120 guests in 60 families**, three languages, mixed age layers, a wheelchair family, two floors and 12 differently located tables; it checks all hard invariants and prints GOLDEN_120_SOLVE_SECONDS in the test logs.

The solver targets a few seconds for practical events around 300 guests, subject to instance difficulty, hardware and time limit. A feasible plan is not misreported as optimal.
