"""Import validation, explicit mapping, aliases, CSV and XLSX."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from seating_optimizer import (
    default_aliases, detect_headers, import_registrations, preview_registrations,
)


def test_csv_automatic_detection_and_group_expansion():
    raw = b"Guest Name,Party Size,Language,Accessibility\nFamily One,3,English,wheelchair\nSingle,1,French,mobile\n"
    result = import_registrations(raw, "registrations.csv")
    assert not result.has_errors, result.issues
    assert result.rows_imported == 2 and len(result.guests) == 4
    assert len({g.group_id for g in result.guests[:3]}) == 1
    assert result.mapping["Guest Name"] == "name"
    assert result.mapping["Party Size"] == "size"
    assert result.guests[0].attributes["mobility"] == "wheelchair"
    assert result.guests[3].attributes["language"] == "French"


def test_manual_mapping_overrides_auto_and_preserves_unmapped_attributes():
    raw = b"Guest Name,Number,Favorite Food\nAlice,2,Salad\n"
    result = import_registrations(raw, "data.csv", mapping={
        "Guest Name": "name", "Number": "size", "Favorite Food": "attribute.food"
    })
    assert not result.has_errors, result.issues
    assert len(result.guests) == 2
    assert result.guests[0].attributes["food"] == "Salad"
    unmapped = import_registrations(b"Person,Count,Notes\nAnn,1,Quiet\n", "data.csv",
                                    mapping={"Person": "name", "Count": "size"})
    assert unmapped.guests[0].attributes["Notes"] == "Quiet"


def test_custom_alias_configuration_changes_detection_without_code_change():
    aliases = default_aliases()
    aliases["name"] = ["Participant"]
    aliases["size"] = ["How many"]
    assert detect_headers(["Participant", "How many"], aliases)[0] == {
        "Participant": "name", "How many": "size"
    }
    result = import_registrations(b"Participant,How many\nAlice,1\n",
                                  "x.csv", aliases=aliases)
    assert not result.has_errors and len(result.guests) == 1


def test_xlsx_import_reads_active_sheet():
    book = Workbook()
    ws = book.active
    ws.append(["Full Name", "Group Size", "Age Layer"])
    ws.append(["Family Bravo", 2, "Adult"])
    output = BytesIO()
    book.save(output)
    result = import_registrations(output.getvalue(), "registrations.xlsx")
    assert not result.has_errors, result.issues
    assert len(result.guests) == 2
    assert all(g.attributes["age_layer"] == "Adult" for g in result.guests)


def test_malformed_rows_and_duplicates_are_reported_and_not_merged():
    raw = b"Name,Size\nAlice,2\nAlice,1\nBob,\nCara,nope\n,1\n"
    result = import_registrations(raw, "registrations.csv")
    assert result.has_errors
    messages = [issue.message for issue in result.issues]
    assert any("Duplicate" in msg for msg in messages)
    assert sum("size" in msg.lower() for msg in messages) >= 2
    assert any("name missing" in msg for msg in messages)
    assert len(result.guests) == 3  # Duplicate name retained, never merged.
    assert result.rows_imported == 2


def test_missing_size_column_unknown_mapping_and_unsupported_format():
    missing = import_registrations(b"Name\nAlice\n", "registrations.csv")
    assert missing.has_errors
    assert any("Missing required mapping: size" in i.message for i in missing.issues)
    invalid = import_registrations(b"Name,Size\nAlice,1\n", "x.csv",
                                   mapping={"not a column": "name"})
    assert invalid.has_errors
    unsupported = import_registrations(b"irrelevant", "guests.txt")
    assert unsupported.has_errors
    assert any("CSV and XLSX" in i.message for i in unsupported.issues)


def test_ragged_nonempty_data_reported():
    result = import_registrations(b"Name,Size\nAlice,1,surprise\n", "x.csv")
    assert result.has_errors
    assert not result.guests



def test_guest_name_family_side_meal_detects_confident_headers_without_faking_size():
    raw = b"Guest Name,Family,Side,Meal\nAlice,Smith,North,Vegan\n"
    preview = preview_registrations(raw, "export.csv")
    assert preview.detected_mapping == {"Guest Name": "name", "Family": "group_id"}
    assert preview.mapping == preview.detected_mapping
    assert "Side" not in preview.mapping and "Meal" not in preview.mapping
    assert any(issue.severity == "warning" and "Missing required mapping: size" in issue.message
               and "Map columns" in issue.message for issue in preview.issues)
    # A genuinely absent size is a data requirement, not something to guess.
    result = import_registrations(raw, "export.csv")
    assert result.has_errors
    assert not result.guests


def test_real_world_aliases_import_groups_without_manual_correction():
    raw = (b"Full Guest Name,Household,Party Count,Side,Meal\n"
           b"Alice,Family A,2,North,Vegan\n"
           b"Bob,Family B,1,South,Kosher\n")
    result = import_registrations(raw, "external.csv")
    assert not result.has_errors, result.issues
    assert result.mapping["Full Guest Name"] == "name"
    assert result.mapping["Household"] == "group_id"
    assert result.mapping["Party Count"] == "size"
    assert len(result.guests) == 3
    assert result.guests[0].group_id == "Family A"
    assert result.guests[2].group_id == "Family B"
    assert result.guests[0].attributes["Side"] == "North"
    assert result.guests[0].attributes["Meal"] == "Vegan"


def test_fuzzy_typo_does_not_mistake_side_for_size_or_guess_ambiguous_name():
    found, problems = detect_headers(["Guset Name", "Family", "Pax", "Side", "Meal"])
    assert found == {"Guset Name": "name", "Family": "group_id", "Pax": "size"}
    assert not problems
    assert "Side" not in found and "Meal" not in found
    doubles, duplicate_issues = detect_headers(["Guest Name", "Full Name", "Party Size"])
    assert "name" not in doubles.values()
    assert doubles["Party Size"] == "size"
    assert any("Multiple matching columns" in issue.message for issue in duplicate_issues)
    assert all(issue.severity == "warning" for issue in duplicate_issues)


def test_manual_size_mapping_can_correct_an_unknown_column_after_preview():
    raw = b"Guest Name,Family,How Many Came,Side\nAlice,Smith,2,North\n"
    before = preview_registrations(raw, "guests.csv")
    assert before.mapping == {"Guest Name": "name", "Family": "group_id"}
    assert any("Missing required mapping: size" in issue.message for issue in before.issues)
    manual = {"How Many Came": "size"}
    reviewed = preview_registrations(raw, "guests.csv", mapping=manual)
    assert not [issue for issue in reviewed.issues if issue.severity == "error"], reviewed.issues
    assert reviewed.mapping == {"Guest Name": "name", "Family": "group_id", "How Many Came": "size"}
    imported = import_registrations(raw, "guests.csv", mapping=manual)
    assert not imported.has_errors and len(imported.guests) == 2
