"""Typed, transport-independent data contracts for a single meal session."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .pattern_rules import validate_pattern


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Zone(Model):
    id: str
    name: str


def _clean_properties(values: list[str]) -> list[str]:
    """Normalize whitespace but do not assign scoring to passive table tags."""
    tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = value.strip()
        if not name:
            raise ValueError("Table property names must be nonempty")
        key = name.casefold()
        if key in seen:
            raise ValueError(f"Duplicate table property {name!r}")
        seen.add(key)
        tags.append(name)
    return tags


class Table(Model):
    id: str
    zone_id: str
    capacity: int = Field(gt=0)
    properties: list[str] = Field(default_factory=list)
    small_group_priority: bool = False

    @field_validator("properties")
    @classmethod
    def valid_properties(cls, values: list[str]) -> list[str]:
        return _clean_properties(values)


class TableDrawing(Model):
    """Optional position/shape of a table within its zone's floor canvas.

    Coordinates are canvas units from the top-left. Drawings are keyed by
    table_id and can be edited as data without changing optimization rules.
    """
    table_id: str
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    shape: Literal["rectangle", "ellipse", "circle"] = "rectangle"
    properties: list[str] = Field(default_factory=list)
    small_group_priority: bool = False

    @field_validator("properties")
    @classmethod
    def valid_properties(cls, values: list[str]) -> list[str]:
        return _clean_properties(values)

    @model_validator(mode="after")
    def valid_circle(self) -> "TableDrawing":
        if self.shape == "circle" and abs(self.width - self.height) > 0.0001:
            raise ValueError(f"Circle {self.table_id} must have equal width and height")
        return self


class FloorLayout(Model):
    zone_id: str
    width: float = Field(gt=0, le=10000)
    height: float = Field(gt=0, le=10000)
    tables: list[TableDrawing] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_positions(self) -> "FloorLayout":
        ids = [table.table_id for table in self.tables]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate table drawing in zone {self.zone_id}")
        for table in self.tables:
            if table.x + table.width > self.width + 0.0001 or table.y + table.height > self.height + 0.0001:
                raise ValueError(f"Table drawing {table.table_id} exceeds floor bounds in {self.zone_id}")
        return self


class VenueLayout(Model):
    """Portable floor-by-floor geometry shared by code, API, and future editors."""
    floors: list[FloorLayout] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_uniqueness(self) -> "VenueLayout":
        ids = [floor.zone_id for floor in self.floors]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate floor zone_id in layout")
        tables = [table.table_id for floor in self.floors for table in floor.tables]
        if len(tables) != len(set(tables)):
            raise ValueError("Table drawing duplicated across floors")
        return self


def validate_layout_references(layout: VenueLayout, zones: list[Zone], tables: list[Table]) -> None:
    """Reject geometry that refers to missing tables or the wrong floor."""
    zone_ids = {zone.id for zone in zones}
    table_zones = {table.id: table.zone_id for table in tables}
    for floor in layout.floors:
        if floor.zone_id not in zone_ids:
            raise ValueError(f"Layout refers to unknown zone {floor.zone_id}")
        for drawing in floor.tables:
            if drawing.table_id not in table_zones:
                raise ValueError(f"Layout refers to unknown table {drawing.table_id}")
            if table_zones[drawing.table_id] != floor.zone_id:
                raise ValueError(f"Table {drawing.table_id} belongs to {table_zones[drawing.table_id]}, not {floor.zone_id}")


class VenueConfiguration(Model):
    """Versioned, guest-independent, portable venue/rules configuration."""
    version: Literal[1] = 1
    name: str = Field(min_length=1)
    zones: list[Zone] = Field(min_length=1)
    tables: list[Table] = Field(min_length=1)
    layout: VenueLayout
    rules: list["Rule"] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_configuration(self) -> "VenueConfiguration":
        for label, ids in (
            ("zone", [z.id for z in self.zones]),
            ("table", [t.id for t in self.tables]),
            ("rule", [r.id for r in self.rules]),
        ):
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {label}")
        zone_ids = {z.id for z in self.zones}
        if any(table.zone_id not in zone_ids for table in self.tables):
            raise ValueError("Every table must reference an existing zone")
        if {floor.zone_id for floor in self.layout.floors} != zone_ids:
            raise ValueError("Configuration floors must exactly match zones")
        validate_layout_references(self.layout, self.zones, self.tables)
        if {drawing.table_id for floor in self.layout.floors for drawing in floor.tables} != {
            table.id for table in self.tables
        }:
            raise ValueError("Each configured table must have a layout drawing")
        return self


class Guest(Model):
    id: str
    name: str
    group_id: str | None = None
    group_name: str | None = None  # Human-readable registration/party name.
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


Shape = Literal["attribute_grouping", "zone_restriction", "table_property_need", "pair", "capacity", "fill_efficiency", "pin", "global_pattern", "low_priority"]


class Rule(Model):
    id: str
    shape: Shape
    mode: Literal["soft", "hard", "mark"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    weight: int | None = None

    @model_validator(mode="after")
    def check_weight(self) -> "Rule":
        if self.mode == "soft" and (self.weight is None or self.weight < 1):
            raise ValueError("Soft rules must carry a positive integer weight")
        if self.mode in {"hard", "mark"} and self.weight is not None:
            raise ValueError("Hard and marking rules must not carry a weight")
        if self.shape == "low_priority":
            if self.mode != "mark":
                raise ValueError("Low-priority marks use mode=mark and have no objective weight")
            p = self.parameters
            if p.get("selector") not in {"group", "size_below"}:
                raise ValueError("Low-priority selector must be group or size_below")
            if type(p.get("grade")) is not int or p["grade"] < 1:
                raise ValueError("Low-priority grade must be a positive integer")
            if p["selector"] == "group":
                if not isinstance(p.get("group_id"), str) or not p["group_id"].strip():
                    raise ValueError("Low-priority group selector needs group_id")
                if set(p) != {"selector", "grade", "group_id"}:
                    raise ValueError("Group priority marking takes selector, grade and group_id")
            else:
                if type(p.get("threshold")) is not int or p["threshold"] < 1:
                    raise ValueError("Size-below priority threshold must be a positive integer")
                if set(p) != {"selector", "grade", "threshold"}:
                    raise ValueError("Size-below marking takes selector, grade and threshold")
        elif self.mode == "mark":
            raise ValueError("Mark mode is reserved for non-scoring low_priority rules")
        if self.shape in {"capacity", "pin"} and self.mode != "hard":
            raise ValueError("Capacity and pin rules must be hard")
        if self.shape in {"fill_efficiency", "global_pattern"} and self.mode != "soft":
            raise ValueError("Fill efficiency and global patterns must be soft")
        if self.shape == "global_pattern":
            # Validate before Rule can enter Problem, VenueConfiguration, or an API payload.
            validate_pattern(self.parameters, rule_id=self.id)
        return self


class ManualInstruction(Model):
    """Persistent human direction; precedence below infinite-weight rules."""
    id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    action: Literal["not_here", "move_to", "unseat", "seat_pending", "pin_placement"]
    place_type: Literal["table", "floor", "zone"] | None = None
    place_id: str | None = None
    allow_split: bool = False
    guest_tables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action(self) -> "ManualInstruction":
        if self.action in {"move_to", "not_here"}:
            if self.place_type is None or not self.place_id:
                raise ValueError("A placement direction needs place_type and place_id")
            if self.guest_tables:
                raise ValueError("A placement direction does not accept guest_tables")
        elif self.action == "pin_placement":
            if not self.guest_tables or self.place_type is not None or self.place_id is not None:
                raise ValueError("A confirmed placement requires guest_tables, not a place")
        elif self.place_type is not None or self.place_id is not None or self.guest_tables or self.allow_split:
            raise ValueError("An unseated or pending decision must not include placement details")
        return self


class SolverConfig(Model):
    time_limit_seconds: float = Field(default=5.0, gt=0)
    workers: int = Field(default=8, ge=1, le=64)
    random_seed: int = 42


class Problem(Model):
    session_id: str
    zones: list[Zone]
    tables: list[Table]
    guests: list[Guest]
    rules: list[Rule] = Field(default_factory=list)
    manual_instructions: list[ManualInstruction] = Field(default_factory=list)
    # Temporary, exact per-person locks for checking option consequences.
    # These never appear in the returned plan or persisted instructions.
    locked_guest_tables: dict[str, str] = Field(default_factory=dict)
    splittable_groups: list[str] = Field(default_factory=list)
    config: SolverConfig = Field(default_factory=SolverConfig)
    layout: VenueLayout | None = None

    @model_validator(mode="after")
    def validate_references(self) -> "Problem":
        for label, values in (
            ("zone", [z.id for z in self.zones]),
            ("table", [t.id for t in self.tables]),
            ("guest", [g.id for g in self.guests]),
            ("guest name", [g.name for g in self.guests]),
            ("rule", [r.id for r in self.rules]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label}")
        if not self.tables or not self.guests:
            raise ValueError("At least one table and one guest are required")
        zones = {z.id for z in self.zones}
        if any(t.zone_id not in zones for t in self.tables):
            raise ValueError("Every table must reference an existing zone")
        if not all(g.id.strip() and g.name.strip() for g in self.guests):
            raise ValueError("Guests need nonempty IDs and names")
        groups = {g.group_id or "guest:" + g.id for g in self.guests}
        table_ids = {t.id for t in self.tables}
        if len({i.id for i in self.manual_instructions}) != len(self.manual_instructions):
            raise ValueError("Duplicate manual instruction ID")
        for instruction in self.manual_instructions:
            if instruction.group_id not in groups:
                raise ValueError(f"Unknown manual-instruction party {instruction.group_id}")
            if instruction.action == "seat_pending":
                raise ValueError("A pending option search is not a persisted manual instruction")
            if instruction.place_type == "table" and instruction.place_id not in table_ids:
                raise ValueError(f"Unknown instruction table {instruction.place_id}")
            if instruction.place_type in {"floor", "zone"} and instruction.place_id not in zones:
                raise ValueError(f"Unknown instruction floor/zone {instruction.place_id}")
            if set(instruction.guest_tables) - {g.id for g in self.guests}:
                raise ValueError("Confirmed placement names an unknown guest")
            if set(instruction.guest_tables.values()) - table_ids:
                raise ValueError("Confirmed placement names an unknown table")
            if instruction.action == "pin_placement" and not any(
                (g.group_id or "guest:" + g.id) == instruction.group_id and g.id in instruction.guest_tables
                for g in self.guests
            ):
                raise ValueError("Confirmed placement must include its selected party")
        if set(self.splittable_groups) - groups:
            raise ValueError("A splittable party is not registered")
        if set(self.locked_guest_tables) - {g.id for g in self.guests}:
            raise ValueError("A temporary placement names an unknown guest")
        if set(self.locked_guest_tables.values()) - table_ids:
            raise ValueError("A temporary placement names an unknown table")
        if self.layout is not None:
            validate_layout_references(self.layout, self.zones, self.tables)
        return self


class Reason(Model):
    rule_id: str
    description: str
    points: float = 0


class Assignment(Model):
    group_id: str
    group_name: str | None = None
    table_id: str
    guest_ids: list[str]
    guest_names: list[str]
    guest_attributes: list[dict[str, str | int | float | bool]] = Field(default_factory=list)
    reasons: list[Reason] = Field(default_factory=list)
    points: float = 0


class ScoreItem(Model):
    rule_id: str
    points: int


class PatternMatch(Model):
    rule_id: str
    table_id: str
    description: str
    points: int


class Compromise(Model):
    rule_id: str
    description: str
    lost_points: int = 0


class TableUsage(Model):
    table_id: str
    zone_id: str
    capacity: int
    occupied: int
    empty_seats: int


class PriorityMark(Model):
    group_id: str
    group_name: str
    grade: int = Field(ge=1)
    guest_count: int = Field(ge=1)
    source_rule_ids: list[str] = Field(default_factory=list)


class NotSeatedGroup(Model):
    group_id: str
    group_name: str
    guest_ids: list[str]
    guest_names: list[str]
    grade: int | None = None


class Plan(Model):
    session_id: str
    manual_instructions: list[ManualInstruction] = Field(default_factory=list)
    status: Literal["optimal", "feasible", "infeasible", "unknown", "needs_review"]
    priority_marks: list[PriorityMark] = Field(default_factory=list)
    pending_groups: list[PriorityMark] = Field(default_factory=list)
    not_seated: list[NotSeatedGroup] = Field(default_factory=list)
    total_score: int | None = None
    assignments: list[Assignment] = Field(default_factory=list)
    tables: list[TableUsage] = Field(default_factory=list)
    score_breakdown: list[ScoreItem] = Field(default_factory=list)
    pattern_matches: list[PatternMatch] = Field(default_factory=list)
    compromises: list[Compromise] = Field(default_factory=list)
    conflicting_constraints: list[str] = Field(default_factory=list)
    solve_seconds: float = 0
    message: str = ""
    layout: VenueLayout | None = None
