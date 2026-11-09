"""Guest-independent configuration templates are validated by the public API."""
from fastapi.testclient import TestClient
from seating_optimizer.api.app import app
from seating_optimizer.models import VenueConfiguration
from test_api_contract import spec, validate

client = TestClient(app)


def configuration(two_floors=False):
    floors = [{"zone_id": "ground", "width": 400, "height": 300,
               "tables": [{"table_id": "T1", "x": 20, "y": 20,
                           "width": 120, "height": 100}]}]
    zones = [{"id": "ground", "name": "Ground floor"}]
    tables = [{"id": "T1", "zone_id": "ground", "capacity": 4}]
    if two_floors:
        floors.append({"zone_id": "upper", "width": 500, "height": 300,
                       "tables": [{"table_id": "U1", "x": 25, "y": 25,
                                   "width": 160, "height": 110}]})
        zones.append({"id": "upper", "name": "Upper floor"})
        tables.append({"id": "U1", "zone_id": "upper", "capacity": 10})
    return {"version": 1, "name": "Friday dinner", "zones": zones, "tables": tables,
            "layout": {"floors": floors},
            "rules": [{"id": "language", "shape": "attribute_grouping",
                       "mode": "soft", "weight": 4,
                       "parameters": {"attribute": "language"}}]}


def test_guest_free_configuration_api_round_trip_single_and_multiple_floors():
    for many in (False, True):
        payload = configuration(two_floors=many)
        response = client.post("/v1/configurations/validate", json=payload)
        assert response.status_code == 200, response.text
        assert response.json() == VenueConfiguration.model_validate(payload).model_dump()
        validate(response.json(), "VenueConfiguration")
        assert VenueConfiguration.model_validate(response.json()).model_dump() == response.json()
        assert len(response.json()["layout"]["floors"]) == (2 if many else 1)


def test_configuration_rejects_missing_geometry_capacity_and_mismatched_floors():
    for change in ("missing", "duplicate", "mismatch", "bad-capacity"):
        payload = configuration()
        if change == "missing":
            payload["layout"]["floors"][0]["tables"] = []
        elif change == "duplicate":
            payload["tables"].append(payload["tables"][0].copy())
        elif change == "mismatch":
            payload["zones"][0]["id"] = "another-floor"
        else:
            payload["tables"][0]["capacity"] = 0
        assert client.post("/v1/configurations/validate", json=payload).status_code == 422


def test_configuration_endpoint_is_documented_in_static_openapi():
    operation = spec()["paths"]["/v1/configurations/validate"]["post"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/VenueConfiguration"}


def test_small_group_priority_survives_configuration_json_validation():
    payload = configuration()
    payload["tables"][0]["small_group_priority"] = True
    payload["layout"]["floors"][0]["tables"][0]["small_group_priority"] = True
    response = client.post("/v1/configurations/validate", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["tables"][0]["small_group_priority"] is True
    assert response.json()["layout"]["floors"][0]["tables"][0]["small_group_priority"] is True
    loaded = VenueConfiguration.model_validate_json(response.text)
    assert loaded.tables[0].small_group_priority
