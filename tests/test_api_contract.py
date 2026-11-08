"""Contract tests against checked-in OpenAPI YAML, plus live HTTP parity tests."""
from __future__ import annotations

import base64
from importlib.resources import files

import jsonschema
import yaml
from fastapi.testclient import TestClient

from seating_optimizer.api.app import app

client = TestClient(app)


def spec():
    return yaml.safe_load(
        files("seating_optimizer.api").joinpath("openapi.yaml").read_text(encoding="utf-8")
    )


def validate(body, schema_name):
    document = spec()
    jsonschema.Draft202012Validator.check_schema(document["components"]["schemas"][schema_name])
    wrapper = {"$ref": f"#/components/schemas/{schema_name}",
               "components": document["components"]}
    jsonschema.validate(body, wrapper, cls=jsonschema.Draft202012Validator)


def test_openapi_file_is_served_and_scalar_not_swagger():
    s = spec()
    r = client.get("/openapi.yaml")
    assert r.status_code == 200
    assert yaml.safe_load(r.text) == s
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "@scalar/api-reference" in docs.text
    assert 'data-url="/openapi.yaml"' in docs.text
    assert "swagger-ui" not in docs.text.lower()
    assert s["openapi"].startswith("3.1.")


def test_contract_paths_methods_and_media_types_match_live_api():
    s = spec()
    declared = {(path, method.upper())
                for path, value in s["paths"].items()
                for method in value if method.lower() in ("get", "post", "put", "delete")}
    implemented = {(route.path, method)
                   for route in app.routes if getattr(route, "include_in_schema", False)
                   for method in route.methods}
    assert declared == implemented
    assert s["paths"]["/v1/exports/table"]["post"]["responses"]["200"]["content"].keys() == {"text/plain"}
    assert "application/json" in s["paths"]["/v1/exports/json"]["post"]["responses"]["200"]["content"]


def test_health_import_solve_and_both_exports_contract():
    assert client.get("/healthz").json() == {"status": "ok"}
    source = b"Name,Size,Language\nFamily Alpha,2,English\nGuest B,1,French\n"
    payload = {"filename": "guests.csv",
               "content_base64": base64.b64encode(source).decode("ascii")}
    validate(payload, "ImportRequest")
    imported = client.post("/v1/import", json=payload)
    assert imported.status_code == 200
    validate(imported.json(), "ImportResult")
    assert len(imported.json()["guests"]) == 3
    problem = {
        "session_id": "one-meal",
        "zones": [{"id": "ground", "name": "Ground"}],
        "tables": [{"id": "T1", "zone_id": "ground", "capacity": 3}],
        "guests": imported.json()["guests"],
        "rules": [{"id": "fill", "shape": "fill_efficiency", "mode": "soft",
                   "weight": 4, "parameters": {}}],
    }
    validate(problem, "Problem")
    solved = client.post("/v1/solve", json=problem)
    assert solved.status_code == 200, solved.text
    assert solved.json()["status"] in ("optimal", "feasible")
    validate(solved.json(), "Plan")
    human = client.post("/v1/exports/table", json=solved.json())
    machine = client.post("/v1/exports/json", json=solved.json())
    assert human.status_code == machine.status_code == 200
    assert human.headers["content-type"].startswith("text/plain")
    assert machine.headers["content-type"].startswith("application/json")
    assert "Table T1" in human.text
    assert machine.json() == solved.json()
    validate(machine.json(), "Plan")


def test_import_invalid_base64_and_infeasible_api_report():
    assert client.post("/v1/import", json={"filename": "x.csv", "content_base64": "%%"}).status_code == 400
    problem = {
        "session_id": "conflict",
        "zones": [{"id": "ground", "name": "Ground"}, {"id": "upper", "name": "Upper"}],
        "tables": [{"id": "G", "zone_id": "ground", "capacity": 1},
                   {"id": "U", "zone_id": "upper", "capacity": 1}],
        "guests": [{"id": "a", "name": "Alice"}],
        "rules": [{"id": "one", "shape": "pin", "mode": "hard",
                   "parameters": {"target": "a", "table": "G"}},
                  {"id": "two", "shape": "pin", "mode": "hard",
                   "parameters": {"target": "a", "table": "U"}}],
    }
    response = client.post("/v1/solve", json=problem)
    assert response.status_code == 200
    assert response.json()["status"] == "infeasible"
    assert {"rule:one", "rule:two"} <= set(response.json()["conflicting_constraints"])
    validate(response.json(), "Plan")
