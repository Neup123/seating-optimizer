"""Metadata for the rule editor. The solver remains the only evaluator."""
from __future__ import annotations

import json
from importlib.resources import files
from typing import Literal

from pydantic import Field

from .models import Model, Shape


class RuleField(Model):
    name: str
    label: str
    kind: Literal["text", "zone", "table", "target", "select", "pattern"]
    required: bool = True
    choices: list[str] = Field(default_factory=list)


class RuleShapeSpec(Model):
    shape: Shape
    title: str
    description: str
    modes: list[Literal["soft", "hard", "mark"]]
    default_mode: Literal["soft", "hard", "mark"]
    default_weight: int | None = None
    fields: list[RuleField] = Field(default_factory=list)


class RuleCatalog(Model):
    shapes: list[RuleShapeSpec]


def rule_catalog() -> RuleCatalog:
    """Load an editable schema of existing rule shapes; no UI-specific logic."""
    content = files("seating_optimizer").joinpath("rule_catalog.json").read_text(encoding="utf-8")
    return RuleCatalog.model_validate(json.loads(content))
