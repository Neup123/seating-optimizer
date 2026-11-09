"""Pluggable, headless seating renderers across Phases 1 and 2."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from .models import Plan
from .print_exports import render_floor_pdf, render_floor_svg, render_table_cards_pdf

Renderer = Callable[[Plan], str | bytes]


def render_table(plan: Plan) -> str:
    """Classic table-by-table human-readable seating list."""
    if plan.status not in ("optimal", "feasible"):
        details = "\n".join(plan.conflicting_constraints)
        return (f"Session {plan.session_id}: {plan.status.upper()}\n"
                f"{plan.message}\n" + (details + "\n" if details else ""))
    lines = [f"Session: {plan.session_id} | Status: {plan.status} | Score: {plan.total_score}"]
    for table in plan.tables:
        lines.append("")
        lines.append(f"Table {table.table_id} | Zone {table.zone_id} | "
                     f"{table.occupied}/{table.capacity} chairs | {table.empty_seats} empty")
        for entry in plan.assignments:
            if entry.table_id == table.table_id:
                lines.append(f"  {entry.group_id}: {', '.join(entry.guest_names)}")
                for reason in entry.reasons:
                    lines.append(f"    - {reason.description} ({reason.points:+g} points)")
    if plan.compromises:
        lines.append("")
        lines.append("Compromises:")
        for issue in plan.compromises:
            lines.append(f"  - [{issue.rule_id}] {issue.description} (lost {issue.lost_points} points)")
    return "\n".join(lines) + "\n"


def render_json(plan: Plan) -> str:
    """Complete machine-readable plan; no output facts lost."""
    return plan.model_dump_json(indent=2)


def render(plan: Plan, format: str, renderers: Mapping[str, Renderer] | None = None) -> str | bytes:
    """Caller-provided renderer mapping permits integration without changing the core."""
    available: dict[str, Renderer] = {"table": render_table, "json": render_json,
        "floor-map-svg": lambda p: render_floor_svg(p).model_dump_json(indent=2),
        "floor-map-pdf": render_floor_pdf, "table-cards-pdf": render_table_cards_pdf}
    if renderers:
        available.update(renderers)
    try:
        return available[format](plan)
    except KeyError as exc:
        raise ValueError(f"Unknown export format: {format}") from exc
