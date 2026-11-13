"""Phase 3: v2 export parity for headless GenericPlan clients."""
from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfReader

from seating_optimizer.api.app import app
from test_api_contract import spec, validate
from test_print_exports import example_plan


client = TestClient(app)


def generic_plan() -> dict:
    # The v1 Plan is still a valid prefix of GenericPlan. The additional
    # generic-solver fields must survive v2 export validation and JSON output.
    payload = example_plan().model_dump(mode="json")
    payload["validation_warnings"] = ["Operator-selected emphasis unchanged"]
    payload["criterion_states"] = [{"field": "language", "matched": 2}]
    payload["unseated_reasons"] = []
    validate(payload, "GenericPlan")
    return payload


def test_all_eight_v2_export_routes_accept_full_generic_plan_without_mutation():
    payload = generic_plan()
    html_cases = {
        "/v2/exports/people-list/html?group_by=combined": "Alice Red",
        "/v2/exports/table-list/html?group_by=table": "Table G1",
        "/v2/exports/not-seated-list/html": "Not seated",
    }
    for path, phrase in html_cases.items():
        response = client.post(path, json=payload)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["content-type"].startswith("text/html")
        assert phrase.casefold() in response.text.casefold(), path

    table = client.post("/v2/exports/table", json=payload)
    assert table.status_code == 200, table.text
    assert "Table G1" in table.text

    svg = client.post("/v2/exports/floor-map/svg", json=payload)
    assert svg.status_code == 200, svg.text
    assert svg.json()["pages"]
    assert 'data-zone-id="ground"' in svg.json()["pages"][0]["svg"]

    for path in ("/v2/exports/floor-map/pdf", "/v2/exports/table-cards/pdf?cards_per_page=2"):
        response = client.post(path, json=payload)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["content-type"].startswith("application/pdf")
        assert PdfReader(BytesIO(response.content)).pages

    machine = client.post("/v2/exports/json", json=payload)
    assert machine.status_code == 200, machine.text
    assert machine.json() == payload
    assert machine.json()["criterion_states"] == [{"field": "language", "matched": 2}]


def test_openapi_exposes_versioned_generic_plan_export_contracts():
    document = spec()
    paths = (
        "/v2/exports/table", "/v2/exports/json",
        "/v2/exports/people-list/html", "/v2/exports/table-list/html",
        "/v2/exports/not-seated-list/html", "/v2/exports/floor-map/svg",
        "/v2/exports/floor-map/pdf", "/v2/exports/table-cards/pdf",
    )
    for path in paths:
        operation = document["paths"][path]["post"]
        assert operation["operationId"].startswith("generic"), path
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        assert schema == {"$ref": "#/components/schemas/GenericPlan"}, path
        assert (path, "POST") in {(route.path, method) for route in app.routes
                                  if getattr(route, "include_in_schema", False)
                                  for method in route.methods}
