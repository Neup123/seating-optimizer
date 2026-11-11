"""The only public package surface; everything here works without HTTP."""
from .exporters import render, render_json, render_table
from .list_exports import render_people_list_html, render_table_list_html, render_not_seated_list_html
from .layout_io import import_layout, import_layout_files
from .print_exports import SvgFloorBundle, SvgFloorPage, render_floor_pdf, render_floor_svg, render_table_cards_pdf
from .importer import ImportIssue, ImportResult, ImportPreview, default_aliases, detect_headers, import_registrations, preview_registrations
from .rule_catalog import RuleCatalog, RuleField, RuleShapeSpec, rule_catalog
from .models import (
    Assignment, Compromise, FloorLayout, Guest, ManualInstruction, NotSeatedGroup, Plan, PriorityMark, Problem, Reason, Rule,
    TableDrawing, VenueLayout, VenueConfiguration, validate_layout_references,
    ScoreItem, SolverConfig, Table, TableUsage, Zone,
)
from .solver import solve
from .generic_rules import Criterion, GenericRule, mechanism_catalog, criterion_field_state, split_dominance_warnings
from .generic_evaluator import score_fixed_plan, hard_violations
from .rule_migration import migrate_instance, migrate_rules, migrate_configuration, reconstruct_v1_rules

__all__ = [
    "Criterion", "GenericRule", "mechanism_catalog", "criterion_field_state", "split_dominance_warnings",
    "score_fixed_plan", "hard_violations", "migrate_instance", "migrate_rules", "migrate_configuration", "reconstruct_v1_rules",
    "Assignment", "Compromise", "Guest", "ManualInstruction", "NotSeatedGroup", "Plan", "PriorityMark", "Problem", "Reason", "Rule",
    "FloorLayout", "TableDrawing", "VenueLayout", "VenueConfiguration", "validate_layout_references",
    "import_layout", "import_layout_files", "SvgFloorBundle", "SvgFloorPage",
    "render_floor_pdf", "render_floor_svg", "render_table_cards_pdf",
    "ScoreItem", "SolverConfig", "Table", "TableUsage", "Zone", "solve",
    "render", "render_json", "render_table", "render_people_list_html", "render_table_list_html", "render_not_seated_list_html", "ImportIssue", "ImportResult",
    "default_aliases", "detect_headers", "import_registrations", "ImportPreview", "preview_registrations",
    "RuleCatalog", "RuleField", "RuleShapeSpec", "rule_catalog",
]
