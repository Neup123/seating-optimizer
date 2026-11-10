"""Print-ready people and table lists derived only from a solved Plan.

A Plan records table membership, not numbered seats. This exporter never invents
seat numbers, reasons, identities, or a new assignment ordering.
"""
from __future__ import annotations

from html import escape
from typing import Literal

from .models import Assignment, Plan
from .display import assignment_name, party_header, party_totals, visible_member_names


def _text(value: str) -> str:
    return escape(value, quote=True)


def _reasons(entry: Assignment) -> str:
    return '<div class="written-reasons">' + "".join(
        f'<p class="reason" data-rule-id="{_text(reason.rule_id)}">'
        f'{_text(reason.description)}</p>'
        for reason in entry.reasons
    ) + "</div>"


def _selected_fields(plan: Plan, fields: list[str] | None) -> list[str]:
    """Restrict column selection to keys present in imported guest data."""
    selected = list(dict.fromkeys(fields or []))
    available = {key for entry in plan.assignments for attrs in entry.guest_attributes for key in attrs}
    unknown = set(selected) - available
    if unknown:
        raise ValueError("Unknown imported field(s): " + ", ".join(sorted(unknown)))
    for entry in plan.assignments:
        if (len(entry.guest_ids) == len(entry.guest_names) and entry.guest_attributes
                and len(entry.guest_attributes) != len(entry.guest_ids)):
            raise ValueError(f"Guest attributes differ for group {entry.group_id}")
    return selected


def _field_value(attrs: dict, field: str) -> str:
    value = attrs.get(field)
    return "—" if value is None or value == "" else str(value)


def _group_label(entry: Assignment, totals: dict[str, int]) -> str:
    return party_header(entry, totals)


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
    include_reasons: bool = False, fields: list[str] | None = None,
    field_labels: list[str] | None = None,
) -> str:
    """One row per recorded guest; floor grouping uses plan.tables zone IDs."""
    if plan.status not in ("optimal", "feasible"):
        raise ValueError("Printable lists require a feasible plan")
    if group_by not in ("combined", "floor"):
        raise ValueError("people list group_by must be combined or floor")
    selected = _selected_fields(plan, fields)
    if field_labels is not None and (len(field_labels) != len(selected)
                                     or any(not label.strip() for label in field_labels)):
        raise ValueError("field_labels must contain one nonempty title per selected field")
    headings = field_labels if field_labels is not None else selected
    totals = party_totals(plan)
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
        cols += "".join(f"<th>{_text(label)}</th>" for label in headings)
        if include_reasons:
            cols += "<th>Written reasons</th>"
        rows = []
        for entry in entries:
            guest_attributes = entry.guest_attributes or [{} for _ in entry.guest_ids]
            if not visible_member_names(entry):
                # Registration-only parties have no individual names. Preserve
                # IDs in the Plan/JSON, not as invented people in print.
                cells = "".join(
                    f"<td>{_text(' / '.join(dict.fromkeys(_field_value(attrs, field) for attrs in guest_attributes)))}</td>"
                    for field in selected
                )
                rows.append(
                    f'<tr data-group-id="{_text(entry.group_id)}" data-table-id="{_text(entry.table_id)}">'
                    f'<td>—</td><td>—</td><td>{_text(_group_label(entry, totals))}</td>'
                    f'<td>{_text(entry.table_id)}</td><td>{_text(table_zones[entry.table_id])}</td>'
                    + cells + (f"<td>{_reasons(entry)}</td>" if include_reasons else "") + "</tr>"
                )
                continue
            for index, (guest_id, guest_name, guest_attrs) in enumerate(zip(
                    entry.guest_ids, entry.guest_names, guest_attributes)):
                rows.append(
                    f'<tr data-guest-id="{_text(guest_id)}" data-group-id="{_text(entry.group_id)}" '
                    f'data-table-id="{_text(entry.table_id)}">'
                    f'<td>{_text(guest_name)}</td><td>{_text(guest_id)}</td>'
                    f'<td>{_text(_group_label(entry, totals)) if index == 0 else "—"}</td>'
                    f'<td>{_text(entry.table_id)}</td>'
                    f'<td>{_text(table_zones[entry.table_id])}</td>'
                    + "".join(f"<td>{_text(_field_value(guest_attrs, field))}</td>" for field in selected)
                    + (f"<td>{_reasons(entry)}</td>" if include_reasons else "") + "</tr>"
                )
        sections.append(f'<section class="print-group {"split" if group_by == "floor" else ""}"{attrs}>'
                        f'<h2>{_text(heading)}</h2><table><thead><tr>{cols}</tr></thead>'
                        f'<tbody>{"".join(rows)}</tbody></table></section>')
    return _document("People list", plan.session_id, sections, group_by == "floor")


def render_table_list_html(
    plan: Plan, *, group_by: Literal["combined", "table"] = "combined",
    include_reasons: bool = False, fields: list[str] | None = None,
) -> str:
    """One row per assigned group; show empty tables without fabricating groups."""
    if plan.status not in ("optimal", "feasible"):
        raise ValueError("Printable lists require a feasible plan")
    if group_by not in ("combined", "table"):
        raise ValueError("table list group_by must be combined or table")
    selected = _selected_fields(plan, fields)
    totals = party_totals(plan)
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
        cols += "".join(f"<th>{_text(field)}</th>" for field in selected)
        if include_reasons:
            cols += "<th>Written reasons</th>"
        rows = []
        for table in tables:
            entries = [entry for entry in plan.assignments if entry.table_id == table.table_id]
            if not entries:
                rows.append(f'<tr class="empty" data-table-id="{_text(table.table_id)}">'
                            f'<td>{_text(table.table_id)}</td><td>{_text(table.zone_id)}</td>'
                            f'<td colspan="{2 + len(selected) + int(include_reasons)}">No assigned groups</td></tr>')
            for entry in entries:
                people = ", ".join(
                    f'<span class="person" data-guest-id="{_text(guest_id)}">{_text(name)}</span>'
                    for guest_id, name in zip(entry.guest_ids, entry.guest_names)
                ) if visible_member_names(entry) else "—"
                guest_attrs = entry.guest_attributes or [{} for _ in entry.guest_ids]
                cells = "".join(
                    f"<td>{_text(' / '.join(dict.fromkeys(_field_value(attrs, field) for attrs in guest_attrs)))}</td>"
                    for field in selected
                )
                rows.append(
                    f'<tr data-group-id="{_text(entry.group_id)}" data-table-id="{_text(table.table_id)}">'
                    f'<td>{_text(table.table_id)}</td><td>{_text(table.zone_id)}</td>'
                    f'<td>{_text(_group_label(entry, totals))}</td><td>{people}</td>'
                    + cells + (f"<td>{_reasons(entry)}</td>" if include_reasons else "") + "</tr>"
                )
        sections.append(f'<section class="print-group {"split" if group_by == "table" else ""}"{attrs}>'
                        f'<h2>{_text(heading)}</h2><table><thead><tr>{cols}</tr></thead>'
                        f'<tbody>{"".join(rows)}</tbody></table></section>')
    return _document("Table list", plan.session_id, sections, group_by == "table")



def render_not_seated_list_html(plan: Plan) -> str:
    """Print only the operator-recorded unseated groups, regardless of solve status.

    Unlike the seated people/table exports, this also works for an infeasible
    capacity alarm and a pending low-priority review. It does not classify,
    select, or change any guest's seating status.
    """
    seen_groups: set[str] = set()
    seen_guests: set[str] = set()
    assigned_guests = {guest_id for entry in plan.assignments for guest_id in entry.guest_ids}
    rows: list[str] = []
    total_people = 0
    for group in plan.not_seated:
        if group.group_id in seen_groups:
            raise ValueError(f"Duplicate not-seated group {group.group_id}")
        seen_groups.add(group.group_id)
        if not group.guest_ids or len(group.guest_ids) != len(group.guest_names):
            raise ValueError(f"Guest IDs and names differ for not-seated group {group.group_id}")
        guest_ids = set(group.guest_ids)
        if len(guest_ids) != len(group.guest_ids) or guest_ids & seen_guests:
            raise ValueError(f"Duplicate not-seated guest in group {group.group_id}")
        if guest_ids & assigned_guests:
            raise ValueError(f"Guest appears both seated and not seated in group {group.group_id}")
        seen_guests |= guest_ids
        size = len(group.guest_ids)
        total_people += size
        # Reuse the same registered-name and synthetic-member discipline as
        # the existing printable table list; do not invent individual names.
        label = assignment_name(group)
        names = visible_member_names(group)
        people = (", ".join(
            f'<span class="person" data-guest-id="{_text(guest_id)}">{_text(name)}</span>'
            for guest_id, name in zip(group.guest_ids, names)
        ) if names else "—")
        rows.append(
            f'<tr data-group-id="{_text(group.group_id)}">'
            f'<td>{_text(label)} — {size}</td><td>{size}</td><td>{people}</td></tr>'
        )
    if rows:
        section = ('<section class="print-group" data-list="not-seated">'
                   f'<h2>{len(rows)} ' + ('family' if len(rows) == 1 else 'families') +
                   f' · {total_people} ' + ('person' if total_people == 1 else 'people') +
                   '</h2><table><thead><tr><th>Registered party</th>'
                   '<th>People</th><th>Named members</th></tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table></section>')
    else:
        # Existing empty-list convention: a titled document with a clear
        # empty message and no fabricated group, person, or table row.
        section = ('<section class="print-group" data-list="not-seated">'
                   '<p class="empty">No one is currently marked not seated.</p></section>')
    return _document("Not seated in the main room", plan.session_id, [section], False)
