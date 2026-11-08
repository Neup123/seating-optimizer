"""Import validation, explicit mapping, aliases, CSV and XLSX."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from seating_optimizer import default_aliases, detect_headers, import_registrations


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
