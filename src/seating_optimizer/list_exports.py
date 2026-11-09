"""Print-ready people and table lists derived only from a solved Plan.

A Plan records table membership, not numbered seats. This exporter never invents
seat numbers, reasons, identities, or a new assignment ordering.
"""
from __future__ import annotations

from html import escape
from typing import Literal

from .models import Assignment, Plan


def _text(value: str) -> str:
    return escape(value, quote=True)


def _reasons(entry: Assignment) -> str:
    return '<div class="written-reasons">' + "".join(
        f'<p class="reason" data-rule-id="{_text(reason.rule_id)}">'
        f'{_text(reason.description)}</p>'
        for reason in entry.reasons
    ) + "</div>"


def _document(title: str, session_id: str, sections: list[str], split: bool) -> str:
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>""" + _text(title) + """</title><style>
@page{size:A4;margin:14mm}
*{box-sizing:border-box}body{font:12px/1.45 Arial,sans-serif;color:#172b3c;margin:22px auto;max-width:1080px;padding:0 15px}
h1{font-size:21px;margin:0 0 4px}h2{font-size:16px;margin:22px 0 10px}
.subtitle{color:#526474;margin:0 0 22px}table{border-collapse:collapse;width:100%}
th,td{padding:8px;border:1px solid #d1dae0;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:#edf2f5}tbody tr{break-inside:avoid}.person{display:inline-block;margin-right:8px}
.reason{margin:0 0 5px;white-space:pre-wrap;overflow-wrap:anywhere}
.empty{color:#6d7982}.print-group{margin-bottom:22px}
@media print{body{margin:0;max-width:none;padding:0}thead{display:table-header-group}
.print-group.split:not(:first-of-type){break-before:page}
a{color:inherit}}
</style></head><body><h1>""" + _text(title) + """</h1><p class="subtitle">Session: """ + _text(session_id) + """</p>""" + "".join(sections) + "</body></html>"


def render_people_list_html(
    plan: Plan, *, group_by: Literal["combined", "floor"] = "combined",
    include_reasons: bool = False,
) -> str:
    """One row per recorded guest; floor grouping uses plan.tables zone IDs."""
    if plan.status not in ("optimal", "feasible"):
        raise ValueError("Printable lists require a feasible plan")
    if group_by not in ("combined", "floor"):
        raise ValueError("people list group_by must be combined or floor")
    table_zones = {table.table_id: table.zone_id for table in plan.tables}
    if len(table_zones) != len(plan.tables):
        raise ValueError("Duplicate table IDs in plan")
    for entry in plan.assignments:
        if entry.table_id not in table_zones:
            raise ValueError(f"Unknown assigned table {entry.table_id}")
        if len(entry.guest_ids) != len(entry.guest_names):
            raise ValueError(f"Guest IDs and names differ for group {entry.group_id}")
    floors = list(dict.fromkeys(table.zone_id for table in plan.tables))
    grouped = [(None, "All floors", plan.assignments)] if group_by == "combined" else [
        (zone, f"Floor / room: {zone}",
         [entry for entry in plan.assignments if table_zones[entry.table_id] == zone])
        for zone in floors
    ]
    sections = []
    for zone, heading, entries in grouped:
        attrs = '' if zone is None else f' data-zone-id="{_text(zone)}"'
        cols = "<th>Guest</th><th>Guest ID</th><th>Group</th><th>Table</th><th>Floor / room</th>"
        if include_reasons:
            cols += "<th>Written reasons</th>"
        rows = []
        for entry in entries:
            for guest_id, guest_name in zip(entry.guest_ids, entry.guest_names):
                rows.append(
                    f'<tr data-guest-id="{_text(guest_id)}" data-group-id="{_text(entry.group_id)}" '
                    f'data-table-id="{_text(entry.table_id)}">'
                    f'<td>{_text(guest_name)}</td><td>{_text(guest_id)}</td>'
                    f'<td>{_text(entry.group_id)}</td><td>{_text(entry.table_id)}</td>'
                    f'<td>{_text(table_zones[entry.table_id])}</td>'
                    + (f"<td>{_reasons(entry)}</td>" if include_reasons else "") + "</tr>"
                )
        sections.append(f'<section class="print-group {"split" if group_by == "floor" else ""}"{attrs}>'
                        f'<h2>{_text(heading)}</h2><table><thead><tr>{cols}</tr></thead>'
                        f'<tbody>{"".join(rows)}</tbody></table></section>')
    return _document("People list", plan.session_id, sections, group_by == "floor")


def render_table_list_html(
    plan: Plan, *, group_by: Literal["combined", "table"] = "combined",
    include_reasons: bool = False,
) -> str:
    """One row per assigned group; show empty tables without fabricating groups."""
    if plan.status not in ("optimal", "feasible"):
        raise ValueError("Printable lists require a feasible plan")
    if group_by not in ("combined", "table"):
        raise ValueError("table list group_by must be combined or table")
    table_by_id = {table.table_id: table for table in plan.tables}
    if len(table_by_id) != len(plan.tables):
        raise ValueError("Duplicate table IDs in plan")
    for entry in plan.assignments:
        if entry.table_id not in table_by_id:
            raise ValueError(f"Unknown assigned table {entry.table_id}")
        if len(entry.guest_ids) != len(entry.guest_names):
            raise ValueError(f"Guest IDs and names differ for group {entry.group_id}")
    sections = []
    scopes = [(None, "All tables", plan.tables)] if group_by == "combined" else [
        (table.table_id, f"Table {table.table_id}", [table]) for table in plan.tables
    ]
    for table_id, heading, tables in scopes:
        attrs = '' if table_id is None else f' data-table-id="{_text(table_id)}"'
        cols = "<th>Table</th><th>Floor / room</th><th>Group</th><th>People</th>"
        if include_reasons:
            cols += "<th>Written reasons</th>"
        rows = []
        for table in tables:
            entries = [entry for entry in plan.assignments if entry.table_id == table.table_id]
            if not entries:
                rows.append(f'<tr class="empty" data-table-id="{_text(table.table_id)}">'
                            f'<td>{_text(table.table_id)}</td><td>{_text(table.zone_id)}</td>'
                            f'<td colspan="{3 if include_reasons else 2}">No assigned groups</td></tr>')
            for entry in entries:
                people = ", ".join(
                    f'<span class="person" data-guest-id="{_text(guest_id)}">{_text(name)}</span>'
                    for guest_id, name in zip(entry.guest_ids, entry.guest_names)
                )
                rows.append(
                    f'<tr data-group-id="{_text(entry.group_id)}" data-table-id="{_text(table.table_id)}">'
                    f'<td>{_text(table.table_id)}</td><td>{_text(table.zone_id)}</td>'
                    f'<td>{_text(entry.group_id)}</td><td>{people}</td>'
                    + (f"<td>{_reasons(entry)}</td>" if include_reasons else "") + "</tr>"
                )
        sections.append(f'<section class="print-group {"split" if group_by == "table" else ""}"{attrs}>'
                        f'<h2>{_text(heading)}</h2><table><thead><tr>{cols}</tr></thead>'
                        f'<tbody>{"".join(rows)}</tbody></table></section>')
    return _document("Table list", plan.session_id, sections, group_by == "table")
