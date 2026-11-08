"""The only public package surface; everything here works without HTTP."""
from .exporters import render, render_json, render_table
from .importer import ImportIssue, ImportResult, default_aliases, detect_headers, import_registrations
from .models import (
    Assignment, Compromise, Guest, Plan, Problem, Reason, Rule,
    ScoreItem, SolverConfig, Table, TableUsage, Zone,
)
from .solver import solve

__all__ = [
    "Assignment", "Compromise", "Guest", "Plan", "Problem", "Reason", "Rule",
    "ScoreItem", "SolverConfig", "Table", "TableUsage", "Zone", "solve",
    "render", "render_json", "render_table", "ImportIssue", "ImportResult",
    "default_aliases", "detect_headers", "import_registrations",
]
