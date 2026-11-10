"""Duplicate-target CSV mapping must be diagnosed throughout the import API (#48)."""
import base64

from fastapi.testclient import TestClient

from seating_optimizer import import_registrations, preview_registrations
from seating_optimizer.api.app import app


SOURCE = b"Name,Size,Language,Secondary Language\nAlice,1,English,French\n"
DUPLICATE_MAPPING = {
    "Name": "name",
    "Size": "size",
    "Language": "attribute.language",
    "Secondary Language": "attribute.language",
}


def test_duplicate_import_mapping_reports_core_preview_and_api_errors():
    imported = import_registrations(SOURCE, "guests.csv", mapping=DUPLICATE_MAPPING)
    assert imported.has_errors
    assert len(imported.guests) == 0
    assert imported.rows_imported == 0
    assert sum("Multiple columns mapped to attribute.language" in issue.message
               and issue.severity == "error" for issue in imported.issues) == 2

    preview = preview_registrations(SOURCE, "guests.csv", mapping=DUPLICATE_MAPPING)
    assert sum("Multiple columns mapped to attribute.language" in issue.message
               and issue.severity == "error" for issue in preview.issues) == 2

    response = TestClient(app).post("/v1/import", json={
        "filename": "guests.csv",
        "content_base64": base64.b64encode(SOURCE).decode("ascii"),
        "mapping": DUPLICATE_MAPPING,
        "header_aliases": {},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["guests"] == []
    assert body["rows_imported"] == 0
    assert sum("Multiple columns mapped to attribute.language" in issue["message"]
               and issue["severity"] == "error" for issue in body["issues"]) == 2


def test_distinct_import_targets_keep_normal_guest_import():
    mapping = {**DUPLICATE_MAPPING, "Secondary Language": "attribute.secondary_language"}
    imported = import_registrations(SOURCE, "guests.csv", mapping=mapping)
    assert not imported.has_errors, imported.issues
    assert imported.rows_imported == 1
    assert len(imported.guests) == 1
    assert imported.guests[0].name == "Alice"
    assert imported.guests[0].attributes == {
        "language": "English", "secondary_language": "French",
    }
