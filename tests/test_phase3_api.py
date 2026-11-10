"""Phase 3 headless parity: CSV/XLSX preview and data-driven rule catalog."""
from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from seating_optimizer import (
    default_aliases, import_registrations, preview_registrations, rule_catalog,
)
from seating_optimizer.api.app import app

from test_api_contract import spec, validate


client = TestClient(app)


def payload(data: bytes, filename: str, mapping=None) -> dict:
    value = {"filename": filename, "content_base64": base64.b64encode(data).decode()}
    if mapping is not None:
        value["mapping"] = mapping
        value["header_aliases"] = {}
    return value


def test_header_preview_reuses_detection_and_reports_malformed_rows():
    raw = b"Guest Name,Party Size,Language\nFamily A,2,English\nFamily A,1,French\nMissing,\n"
    preview = preview_registrations(raw, "guests.csv")
    assert preview.headers == ["Guest Name", "Party Size", "Language"]
    assert preview.mapping == {"Guest Name": "name", "Party Size": "size",
                               "Language": "attribute.language"}
    assert preview.sample_rows[0]["Guest Name"] == "Family A"
    assert preview.rows_seen == 3
    assert any("Duplicate" in issue.message for issue in preview.issues)
    assert any("size" in issue.message for issue in preview.issues)
    resp = client.post("/v1/import/preview", json=payload(raw, "guests.csv"))
    assert resp.status_code == 200
    validate(resp.json(), "ImportPreview")
    assert resp.json()["mapping"] == preview.mapping
    assert client.post("/v1/import/preview", json={"filename": "x.csv",
                        "content_base64": "not-base64"}).status_code == 400


def test_preview_manual_correction_and_custom_attribute_are_headless():
    raw = b"Participant,Count,Needs\nAlice,3,Accessible\n"
    response = client.post("/v1/import/preview", json=payload(raw, "guests.csv"))
    assert response.status_code == 200
    assert any("Missing required mapping" in issue["message"]
               for issue in response.json()["issues"])
    corrected = payload(raw, "guests.csv", {"Participant": "name", "Count": "size",
                                           "Needs": "attribute.mobility"})
    head = client.post("/v1/import/preview", json=corrected)
    assert head.status_code == 200
    assert not any(issue["severity"] == "error" for issue in head.json()["issues"])
    data = client.post("/v1/import", json=corrected)
    assert data.status_code == 200
    assert len(data.json()["guests"]) == 3
    assert all(g["attributes"]["mobility"] == "Accessible"
               for g in data.json()["guests"])


def test_xlsx_header_preview_and_diagnostic_isolation():
    book = Workbook()
    sheet = book.active
    sheet.append(["Full Name", "Group Size", "Age Layer"])
    sheet.append(["Family Z", 2, "Adult"])
    data = BytesIO()
    book.save(data)
    result = client.post("/v1/import/preview", json=payload(data.getvalue(), "guests.xlsx"))
    assert result.status_code == 200
    assert result.json()["rows_seen"] == 1
    assert result.json()["mapping"]["Age Layer"] == "attribute.age_layer"
    assert len(result.json()["sample_rows"]) == 1
    assert preview_registrations(b"", "bad.csv").issues


def test_catalog_covers_six_solver_shapes_and_openapi_contract():
    catalog = rule_catalog()
    shapes = {shape.shape: shape for shape in catalog.shapes}
    assert set(shapes) == {"attribute_grouping", "zone_restriction", "table_property_need", "global_pattern",
                           "pair", "capacity", "fill_efficiency", "pin"}
    assert shapes["capacity"].modes == ["hard"]
    assert shapes["pin"].modes == ["hard"]
    assert shapes["fill_efficiency"].modes == ["soft"]
    assert shapes["global_pattern"].modes == ["soft"]
    assert any(field.kind == "pattern" for field in shapes["global_pattern"].fields)
    assert shapes["table_property_need"].modes == ["soft", "hard"]
    assert {field.name for field in shapes["table_property_need"].fields} == {
        "attribute", "value", "property"
    }
    assert all(shape.fields is not None and shape.title for shape in catalog.shapes)
    response = client.get("/v1/rules/catalog")
    assert response.status_code == 200
    validate(response.json(), "RuleCatalog")
    assert response.json() == catalog.model_dump()
    for path, method, model in [
        ("/v1/import/preview", "post", "ImportPreview"),
        ("/v1/rules/catalog", "get", "RuleCatalog"),
    ]:
        operation = spec()["paths"][path][method]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/" + model
        }
    assert "@scalar/api-reference" in client.get("/docs").text


def test_browser_files_are_actually_served_with_correct_media_types():
    root = client.get("/")
    js = client.get("/assets/app.js")
    css = client.get("/assets/style.css")
    assert root.status_code == js.status_code == css.status_code == 200
    assert 'data-seat-app' in root.text and '/assets/app.js' in root.text
    assert "text/javascript" in js.headers["content-type"]
    assert "createApp" in js.text and "/v1/solve" in js.text
    assert "text/css" in css.headers["content-type"]
    assert "grid-template-columns" in css.text
    selection = client.get("/assets/plan-selection.js")
    workspace = client.get("/assets/plan-workspace.js")
    assert selection.status_code == workspace.status_code == 200
    assert "text/javascript" in selection.headers["content-type"]
    assert "text/javascript" in workspace.headers["content-type"]
    assert "togglePlanSelection" in selection.text
    assert 'from "./plan-selection.js"' in workspace.text



def test_corrupt_xlsx_reports_diagnostics_without_500_or_silent_acceptance():
    corrupted = b"this-is-not-a-valid-XLSX-zip-archive"
    for endpoint, model in (("/v1/import/preview", "ImportPreview"),
                            ("/v1/import", "ImportResult")):
        response = client.post(endpoint, json=payload(corrupted, "bad.xlsx"))
        assert response.status_code == 200, response.text
        validate(response.json(), model)
        assert any(issue["severity"] == "error" for issue in response.json()["issues"])
        assert not response.json().get("guests")
        if endpoint.endswith("/preview"):
            assert response.json()["headers"] == []
        else:
            assert response.json()["rows_imported"] == 0



def test_issue_15_aliases_preview_and_import_have_api_parity():
    raw = b"Guest Name,Family,Party Count,Side,Meal\nAlice,Smith,2,North,Vegan\n"
    preview = client.post("/v1/import/preview", json=payload(raw, "export.csv"))
    assert preview.status_code == 200
    mapping = preview.json()["mapping"]
    assert mapping == {"Guest Name": "name", "Family": "group_id", "Party Count": "size"}
    assert preview.json()["detected_mapping"] == mapping
    assert not [issue for issue in preview.json()["issues"] if issue["severity"] == "error"]
    actual = client.post("/v1/import", json=payload(raw, "export.csv"))
    assert actual.status_code == 200
    assert actual.json()["mapping"] == mapping
    assert len(actual.json()["guests"]) == 2
    assert actual.json()["guests"][0]["attributes"]["Meal"] == "Vegan"
    validate(preview.json(), "ImportPreview")
    validate(actual.json(), "ImportResult")

    incomplete = b"Guest Name,Family,Side,Meal\nAlice,Smith,North,Vegan\n"
    preview = client.post("/v1/import/preview", json=payload(incomplete, "export.csv"))
    assert preview.status_code == 200
    assert preview.json()["mapping"] == {"Guest Name": "name", "Family": "group_id"}
    assert any("Missing required mapping: size" in issue["message"] and issue["severity"] == "warning"
               for issue in preview.json()["issues"])
    actual = client.post("/v1/import", json=payload(incomplete, "export.csv"))
    assert actual.status_code == 200
    assert any("Missing required mapping: size" in issue["message"] and issue["severity"] == "error"
               for issue in actual.json()["issues"])
