"""The only public package surface; everything here works without HTTP."""
from .exporters import render, render_json, render_table
from .layout_io import import_layout, import_layout_files
from .print_exports import SvgFloorBundle, SvgFloorPage, render_floor_pdf, render_floor_svg, render_table_cards_pdf
from .importer import ImportIssue, ImportResult, default_aliases, detect_headers, import_registrations
from .models import (
    Assignment, Compromise, FloorLayout, Guest, Plan, Problem, Reason, Rule,
    TableDrawing, VenueLayout, validate_layout_references,
    ScoreItem, SolverConfig, Table, TableUsage, Zone,
)
from .solver import solve

__all__ = [
    "Assignment", "Compromise", "Guest", "Plan", "Problem", "Reason", "Rule",
    "FloorLayout", "TableDrawing", "VenueLayout", "validate_layout_references",
    "import_layout", "import_layout_files", "SvgFloorBundle", "SvgFloorPage",
    "render_floor_pdf", "render_floor_svg", "render_table_cards_pdf",
    "ScoreItem", "SolverConfig", "Table", "TableUsage", "Zone", "solve",
    "render", "render_json", "render_table", "ImportIssue", "ImportResult",
    "default_aliases", "detect_headers", "import_registrations",
]
