"""Phase 2 new API endpoints validated against the checked-in OpenAPI YAML."""
from __future__ import annotations

import base64
from io import BytesIO
from xml.etree import ElementTree

import jsonschema
from pypdf import PdfReader

from seating_optimizer.api.app import app
from fastapi.testclient import TestClient

from test_api_contract import spec, validate


client = TestClient(app)


def as_base64(text: bytes) -> str:
    return base64.b64encode(text).decode("ascii")


def test_layout_import_round_trip_and_headless_print_endpoint_contracts():
    svg = b'''<svg data-zone-id="ground" viewBox="0 0 480 300">
      <g data-table-id="T1"><rect x="20" y="20" width="300" height="220"/>
      <text>T1</text></g></svg>'''
    request = {
        "files": [{"filename": "numbered-ground.svg", "content_base64": as_base64(svg)}],
        "zones": [{"id": "ground", "name": "Ground floor"}],
        "tables": [{"id": "T1", "zone_id": "ground", "capacity": 4}],
    }
    validate(request, "LayoutImportRequest")
    imported = client.post("/v1/layouts/import", json=request)
    assert imported.status_code == 200, imported.text
    validate(imported.json(), "VenueLayout")
    assert imported.json()["floors"][0]["tables"][0]["table_id"] == "T1"

    problem = {
        "session_id": "small",
        "zones": request["zones"], "tables": request["tables"],
        "guests": [{"id": "alice", "name": "Alice"},
                   {"id": "bob", "name": "Bob", "group_id": "family-blue", "group_name": "family-blue"}],
        "rules": [{"id": "pin", "shape": "pin", "mode": "hard",
                   "parameters": {"target": "bob", "table": "T1"}}],
        "layout": imported.json(),
    }
    validate(problem, "Problem")
    solved = client.post("/v1/solve", json=problem)
    assert solved.status_code == 200, solved.text
    plan = solved.json()
    validate(plan, "Plan")
    assert plan["status"] in ("feasible", "optimal")
    assert plan["layout"] == imported.json()

    svg_response = client.post("/v1/exports/floor-map/svg", json=plan)
    assert svg_response.status_code == 200, svg_response.text
    validate(svg_response.json(), "SvgFloorBundle")
    assert len(svg_response.json()["pages"]) == 1
    root = ElementTree.fromstring(svg_response.json()["pages"][0]["svg"])
    assert root.attrib["data-zone-id"] == "ground"
    assert "family-blue" in svg_response.json()["pages"][0]["svg"]

    floor_pdf = client.post("/v1/exports/floor-map/pdf", json=plan)
    assert floor_pdf.status_code == 200, floor_pdf.text
    assert floor_pdf.headers["content-type"] == "application/pdf"
    assert len(PdfReader(BytesIO(floor_pdf.content)).pages) == 1
    assert "family-blue" in PdfReader(BytesIO(floor_pdf.content)).pages[0].extract_text()

    cards = client.post("/v1/exports/table-cards/pdf", json=plan)
    assert cards.status_code == 200, cards.text
    assert cards.headers["content-type"] == "application/pdf"
    assert len(PdfReader(BytesIO(cards.content)).pages) == 1
    text = PdfReader(BytesIO(cards.content)).pages[0].extract_text()
    assert all(s in text for s in ("Table T1", "Alice", "Bob"))

    machine = client.post("/v1/exports/json", json=plan)
    assert machine.status_code == 200
    assert machine.json() == plan  # Phase 1 JSON now preserves layout data.


def test_api_imports_combined_json_and_numbered_svg_for_two_floors():
    content = b'''{"floors":[{"zone_id":"ground","width":450,"height":300,
       "tables":[{"table_id":"G1","x":10,"y":10,"width":200,"height":120}]}]}'''
    svg = b'''<svg data-zone-id="upper" viewBox="0 0 450 300">
      <g data-table-id="U1"><ellipse cx="200" cy="100" rx="90" ry="70"/>
      <text>U1</text></g></svg>'''
    data = {
        "files": [{"filename": "ground.json", "content_base64": as_base64(content)},
                  {"filename": "upper.svg", "content_base64": as_base64(svg)}],
        "zones": [{"id": "ground", "name": "Ground"}, {"id": "upper", "name": "Upper"}],
        "tables": [{"id": "G1", "zone_id": "ground", "capacity": 6},
                   {"id": "U1", "zone_id": "upper", "capacity": 6}],
    }
    response = client.post("/v1/layouts/import", json=data)
    assert response.status_code == 200, response.text
    validate(response.json(), "VenueLayout")
    assert [floor["zone_id"] for floor in response.json()["floors"]] == ["ground", "upper"]


def test_api_rejects_bad_geometry_missing_layout_and_bad_base64():
    bad = client.post("/v1/layouts/import", json={"files": [
        {"filename": "bad.svg", "content_base64": "%%"}]})
    assert bad.status_code == 400
    missing = client.post("/v1/exports/floor-map/svg", json={
        "session_id": "invalid", "status": "feasible", "total_score": 0,
        "tables": [{"table_id": "T1", "zone_id": "ground", "capacity": 4,
                    "occupied": 0, "empty_seats": 4}],
    })
    assert missing.status_code == 422
    assert "plan.layout" in missing.json()["detail"]


def test_openapi_phase2_operations_and_media_types_match_implementation():
    document = spec()
    for path, media in [
        ("/v1/layouts/import", "application/json"),
        ("/v1/exports/floor-map/svg", "application/json"),
        ("/v1/exports/floor-map/pdf", "application/pdf"),
        ("/v1/exports/table-cards/pdf", "application/pdf"),
    ]:
        operation = document["paths"][path]["post"]
        assert operation["operationId"]
        assert media in operation["responses"]["200"]["content"]
        assert (path, "POST") in {(r.path, method) for r in app.routes
                                  if getattr(r, "include_in_schema", False)
                                  for method in r.methods}
    for key in ("VenueLayout", "TableDrawing", "FloorLayout", "SvgFloorBundle",
                "LayoutImportRequest"):
        jsonschema.Draft202012Validator.check_schema(
            document["components"]["schemas"][key]
        )
    assert "@scalar/api-reference" in client.get("/docs").text

def test_table_card_api_query_is_optional_and_documents_supported_densities():
    from test_print_exports import example_plan
    plan = example_plan().model_dump(mode="json")
    for density, expected_pages in ((None, 3), (1, 3), (2, 2), (4, 1)):
        query = "" if density is None else f"?cards_per_page={density}"
        response = client.post("/v1/exports/table-cards/pdf" + query, json=plan)
        assert response.status_code == 200, response.text
        reader = PdfReader(BytesIO(response.content))
        assert len(reader.pages) == expected_pages
        all_text = " ".join(page.extract_text() for page in reader.pages)
        assert all(name in all_text for name in ("Table G1", "Table G2",
                                                "Table U1", "Alice Red", "Bob Red",
                                                "Cara Blue", "Dan Blue"))
    for invalid in ("0", "3", "5", "bogus"):
        response = client.post("/v1/exports/table-cards/pdf?cards_per_page=" + invalid, json=plan)
        assert response.status_code == 422
    parameters = spec()["paths"]["/v1/exports/table-cards/pdf"]["post"]["parameters"]
    assert parameters == [{
        "name": "cards_per_page", "in": "query", "required": False,
        "description": "Number of complete table cards to print on a physical page.",
        "schema": {"type": "integer", "enum": [1, 2, 4], "default": 1}
    }]
