"""Contract: solver tables own metadata, floor drawings own geometry."""
import pytest
from pydantic import ValidationError

from seating_optimizer.models import (
    FloorLayout, Table, TableDrawing, VenueConfiguration, VenueLayout, Zone,
)
from seating_optimizer.generic_solver import GenericVenueConfiguration


def configuration(*, table_properties=("accessible",), drawing_properties=("accessible",),
                  table_priority=False, drawing_priority=False, version=1):
    model = VenueConfiguration if version == 1 else GenericVenueConfiguration
    return model.model_validate({
        "version": version, "name": "Hall", "zones": [{"id": "hall", "name": "Hall"}],
        "tables": [{"id": "T1", "zone_id": "hall", "capacity": 4,
                    "properties": list(table_properties), "small_group_priority": table_priority}],
        "layout": {"floors": [{"zone_id": "hall", "width": 400, "height": 300,
                              "tables": [{"table_id": "T1", "x": 10, "y": 10,
                                          "width": 100, "height": 100,
                                          "properties": list(drawing_properties),
                                          "small_group_priority": drawing_priority}]}]},
        "rules": []
    })


@pytest.mark.parametrize("version", [1, 2])
def test_configuration_metadata_roundtrip(version):
    original = configuration(version=version, table_priority=True, drawing_priority=True)
    assert type(original).model_validate_json(original.model_dump_json()) == original
    drawing = original.layout.floors[0].tables[0]
    assert drawing.properties == original.tables[0].properties
    assert drawing.small_group_priority is original.tables[0].small_group_priority


@pytest.mark.parametrize("version", [1, 2])
def test_configuration_rejects_divergent_table_properties(version):
    with pytest.raises(ValidationError, match="property tags differ"):
        configuration(version=version, table_properties=["accessible"], drawing_properties=["quiet"])


@pytest.mark.parametrize("version", [1, 2])
def test_configuration_rejects_divergent_priority(version):
    with pytest.raises(ValidationError, match="small-group priority differs"):
        configuration(version=version, table_priority=True, drawing_priority=False)


@pytest.mark.parametrize("version", [1, 2])
def test_metadata_case_insensitive_tag_matching(version):
    assert configuration(version=version, table_properties=["Accessible"], drawing_properties=["accessible"])
