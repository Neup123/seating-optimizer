"""Typed, transport-independent data contracts for a single meal session."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Zone(Model):
    id: str
    name: str


class Table(Model):
    id: str
    zone_id: str
    capacity: int = Field(gt=0)


class Guest(Model):
    id: str
    name: str
    group_id: str | None = None
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


Shape = Literal["attribute_grouping", "zone_restriction", "pair", "capacity", "fill_efficiency", "pin"]


class Rule(Model):
    id: str
    shape: Shape
    mode: Literal["soft", "hard"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    weight: int | None = None

    @model_validator(mode="after")
    def check_weight(self) -> "Rule":
        if self.mode == "soft" and (self.weight is None or self.weight < 1):
            raise ValueError("Soft rules must carry a positive integer weight")
        if self.mode == "hard" and self.weight is not None:
            raise ValueError("Hard rules must not carry a weight")
        if self.shape in {"capacity", "pin"} and self.mode != "hard":
            raise ValueError("Capacity and pin rules must be hard")
        if self.shape == "fill_efficiency" and self.mode != "soft":
            raise ValueError("Fill efficiency must be soft")
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
    config: SolverConfig = Field(default_factory=SolverConfig)

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
        return self


class Reason(Model):
    rule_id: str
    description: str
    points: float = 0


class Assignment(Model):
    group_id: str
    table_id: str
    guest_ids: list[str]
    guest_names: list[str]
    reasons: list[Reason] = Field(default_factory=list)
    points: float = 0


class ScoreItem(Model):
    rule_id: str
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


class Plan(Model):
    session_id: str
    status: Literal["optimal", "feasible", "infeasible", "unknown"]
    total_score: int | None = None
    assignments: list[Assignment] = Field(default_factory=list)
    tables: list[TableUsage] = Field(default_factory=list)
    score_breakdown: list[ScoreItem] = Field(default_factory=list)
    compromises: list[Compromise] = Field(default_factory=list)
    conflicting_constraints: list[str] = Field(default_factory=list)
    solve_seconds: float = 0
    message: str = ""
