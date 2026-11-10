"""Pluggable, headless seating renderers across Phases 1 and 2."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from .models import Plan
from .display import counted, party_lines, party_totals
from .list_exports import render_people_list_html, render_table_list_html, render_not_seated_list_html
from .print_exports import render_floor_pdf, render_floor_svg, render_table_cards_pdf

Renderer = Callable[[Plan], str | bytes]


def render_table(plan: Plan) -> str:
    """Classic table-by-table human-readable seating list."""
    if plan.status not in ("optimal", "feasible"):
        details = "\n".join(plan.conflicting_constraints)
        return (f"Session {plan.session_id}: {plan.status.upper()}\n"
                f"{plan.message}\n" + (details + "\n" if details else ""))
    lines = [f"Session: {plan.session_id} | Status: {plan.status} | Score: {plan.total_score}"]
    totals = party_totals(plan)
    for table in plan.tables:
        lines.append("")
        lines.append(f"Table {table.table_id} | Zone {table.zone_id} | "
                     f"{table.occupied}/{table.capacity} chairs | {counted(table.empty_seats, 'empty chair')}")
        for entry in plan.assignments:
            if entry.table_id == table.table_id:
                lines.extend(f"  {line}" for line in party_lines(entry, totals))
                for reason in entry.reasons:
                    lines.append(f"    - {reason.description} ({reason.points:+g} {'point' if abs(reason.points) == 1 else 'points'})")
    if plan.compromises:
        lines.append("")
        lines.append("Compromises:")
        for issue in plan.compromises:
            lines.append(f"  - [{issue.rule_id}] {issue.description} (lost {counted(issue.lost_points, 'point')})")
    return "\n".join(lines) + "\n"


def render_json(plan: Plan) -> str:
    """Complete machine-readable plan; no output facts lost."""
    return plan.model_dump_json(indent=2)


def render(plan: Plan, format: str, renderers: Mapping[str, Renderer] | None = None) -> str | bytes:
    """Caller-provided renderer mapping permits integration without changing the core."""
    available: dict[str, Renderer] = {"table": render_table, "json": render_json,
        "people-list-html": render_people_list_html, "table-list-html": render_table_list_html,
        "not-seated-list-html": render_not_seated_list_html,
        "floor-map-svg": lambda p: render_floor_svg(p).model_dump_json(indent=2),
        "floor-map-pdf": render_floor_pdf, "table-cards-pdf": render_table_cards_pdf}
    if renderers:
        available.update(renderers)
    try:
        return available[format](plan)
    except KeyError as exc:
        raise ValueError(f"Unknown export format: {format}") from exc
