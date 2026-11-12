"""Version-2 generic rule schema and criterion expressions.

This module intentionally has no dependency on the legacy Shape literal or UI.
The registry is the source of truth for mechanism discovery. A disabled record
keeps its original data without validating the mechanism's content.
"""
from __future__ import annotations

import builtins
import math
import re
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


ENGINES = {
    "intra": {
        "split_term": ("soft",),
        "own_attribute_grouping": ("soft", "hard"),
    },
    "inter": {
        "pair_relation": ("hard", "soft"),
        "criterion_pairs": ("hard", "soft"),
        "table_pattern": ("soft",),
        "companionship": ("soft",),
    },
    "venue": {
        "placement_by_criterion": ("hard", "soft"),
        "tiered_placement": ("staged",),
        "property_need": ("hard", "soft"),
        "holes_term": ("soft",),
        "property_fit": ("soft",),
        "locked_assignment": ("hard",),
    },
    # Stage is an ordering layer, not a fourth scoring relation.
    "stage": {"priority_mark": ("mark",)},
}
OPERATORS = ("==", "!=", "<", "<=", ">", ">=", "in")
_FAMILY_AGGREGATE = re.compile(r"^(min|max|any)\(([A-Za-z_][A-Za-z0-9_]*)\)$")
_FAMILY_ALIASES = {
    "youngest_age(family)": ("min", "age"),
    "oldest_age(family)": ("max", "age"),
}


def family_field_spec(field: str) -> tuple[str, str | None] | None:
    """Parse an explicitly named family aggregate, without executing input."""
    if field == "party_size":
        return "size", None
    if field in _FAMILY_ALIASES:
        return _FAMILY_ALIASES[field]
    match = _FAMILY_AGGREGATE.fullmatch(field)
    return (match.group(1), match.group(2)) if match else None


def family_value(members: Sequence[Any], field: str) -> int | float | list[float] | None:
    """Aggregate numeric guest attributes; missing values never become zero."""
    spec = family_field_spec(field)
    if spec is None:
        return None
    aggregate, member_field = spec
    if aggregate == "size":
        return len(members)
    values = [guest_value(member, member_field) for member in members]
    numbers = [float(value) for value in values if _number(value)]
    if not numbers:
        return None
    if aggregate == "min":
        return min(numbers)
    if aggregate == "max":
        return max(numbers)
    return numbers  # any(field): existential comparison over family members

SCORING_POLARITY = {
    ("intra", "split_term"): "penalty",
    ("inter", "companionship"): "penalty",
    ("venue", "holes_term"): "penalty",
    ("venue", "property_fit"): "reward",
    ("venue", "placement_by_criterion"): "reward",
    ("venue", "property_need"): "penalty",
}


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: Literal["guest", "family", "pair", "table"] = "guest"
    field: str = Field(min_length=1)
    op: Literal["==", "!=", "<", "<=", ">", ">=", "in"] = "=="
    value: Any = None
    scope: Literal["within", "across"] | None = None

    @model_validator(mode="after")
    def check(self) -> "Criterion":
        if family_field_spec(self.field) is not None and self.field != "party_size":
            self.subject = "family"
        if self.op == "in":
            if not isinstance(self.value, list) or not self.value:
                raise ValueError("'in' requires a nonempty value list")
            kinds = {"bool" if isinstance(v, bool) else "number" if _number(v)
                     else "text" if isinstance(v, str) else "invalid"
                     for v in self.value}
            if len(kinds) != 1 or "invalid" in kinds:
                raise ValueError("'in' requires homogeneous scalar values")
        elif isinstance(self.value, (list, dict)):
            raise ValueError("Comparison value must be a scalar")
        elif self.value is None and self.op != "==":
            raise ValueError("Missing values are permitted only for unfiltered grouping")
        if self.op in ("<", "<=", ">", ">=") and (
            isinstance(self.value, bool) or not _number(self.value)
        ):
            raise ValueError("Ordered comparisons require a numeric value")
        if self.scope is not None and self.subject != "guest":
            raise ValueError("Pair scope applies only to guest criteria")
        if self.subject == "family" and family_field_spec(self.field) is None:
            raise ValueError(f"Unknown family aggregate {self.field!r}")
        if self.subject == "family" and family_field_spec(self.field)[0] == "any" and self.value is None:
            raise ValueError("any(field) requires a comparison value")
        return self


def _number(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _coerce(actual: Any, expected: Any) -> tuple[Any, Any]:
    """Compare imported string columns with typed expressions predictably."""
    if isinstance(expected, bool):
        if isinstance(actual, bool):
            return actual, expected
        if isinstance(actual, str) and actual.strip().casefold() in ("true", "false"):
            return actual.strip().casefold() == "true", expected
        return actual, expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (float(actual), float(expected)) if _number(actual) else (actual, expected)
    return str(actual), str(expected)


def compare_value(actual: Any, op: str, expected: Any) -> bool:
    """Missing data is handled by the caller; no Python eval or silent casts."""
    if op == "in":
        return any(compare_value(actual, "==", item) for item in expected)
    a, b = _coerce(actual, expected)
    if op in ("<", "<=", ">", ">="):
        if not _number(actual) or not _number(expected):
            return False
        # Imported CSV numeric fields are strings; ordered comparison must
        # be numeric, never lexicographic (e.g. 100 < 65 is false).
        a, b = float(actual), float(expected)
    if op == "==":
        return type(a) is type(b) and a == b
    if op == "!=":
        return type(a) is not type(b) or a != b
    return {
        "<": lambda: a < b,
        "<=": lambda: a <= b,
        ">": lambda: a > b,
        ">=": lambda: a >= b,
    }[op]()


def guest_value(guest: Any, field: str) -> Any:
    if field == "name":
        return guest.name
    if field == "party":
        return guest.group_id or "guest:" + guest.id
    return guest.attributes.get(field)


def match_guest(guest: Any, criterion: Criterion | Mapping[str, Any]) -> bool:
    c = criterion if isinstance(criterion, Criterion) else Criterion.model_validate(criterion)
    if c.subject != "guest":
        raise ValueError("Guest matcher requires a guest criterion")
    actual = guest_value(guest, c.field)
    return actual is not None and (c.value is None or compare_value(actual, c.op, c.value))


def match_family(members: Sequence[Any], criterion: Criterion | Mapping[str, Any]) -> bool:
    c = criterion if isinstance(criterion, Criterion) else Criterion.model_validate(criterion)
    if c.subject != "family":
        raise ValueError("Family matcher requires subject=family")
    value = family_value(members, c.field)
    if value is None:
        return False
    if isinstance(value, list):
        return any(compare_value(item, c.op, c.value) for item in value)
    return c.value is None or compare_value(value, c.op, c.value)


@dataclass(frozen=True)
class CriterionFieldState:
    field: str
    observed: bool
    compatible: bool
    message: str = ""


def criterion_field_state(guests: Sequence[Any], criterion: Criterion) -> CriterionFieldState:
    """Convey absent-column/inert state to the future editor, without guessing."""
    if criterion.subject == "family":
        spec = family_field_spec(criterion.field)
        if spec is None:
            return CriterionFieldState(criterion.field, False, False,
                                       f"Unknown family aggregate {criterion.field!r}")
        if spec[0] == "size":
            return CriterionFieldState(criterion.field, True, True)
        values = [guest_value(g, spec[1]) for g in guests]
    else:
        values = [guest_value(g, criterion.field) for g in guests]
    found = [v for v in values if v is not None]
    if not found:
        return CriterionFieldState(criterion.field, False, True,
                                   f"Field {criterion.field!r} is absent; rule matches no guests")
    needs_number = (criterion.subject == "family" or
                    criterion.op in ("<", "<=", ">", ">=") or
                    _number(criterion.value) and not isinstance(criterion.value, bool) or
                    criterion.op == "in" and all(_number(v) for v in criterion.value))
    if needs_number and any(not _number(v) for v in found):
        return CriterionFieldState(criterion.field, True, False,
                                   f"Field {criterion.field!r} contains nonnumeric values")
    return CriterionFieldState(criterion.field, True, True)


def match_table_pattern(conditions: Sequence[Mapping[str, Any]],
                        *, table_id: str, tables: Sequence[Any],
                        guests: Sequence[Any], guest_tables: Mapping[str, str]) -> bool:
    """Pure counterpart of table-count expressions for fixed-plan verification."""
    table = next(t for t in tables if t.id == table_id)
    present = [g for g in guests if guest_tables.get(g.id) == table_id]
    groups = {g.group_id or "guest:" + g.id for g in present}
    facts = {
        "groups_at_table": len(groups),
        "occupied_seats": len(present),
        "empty_seats": table.capacity - len(present),
    }
    for condition in conditions:
        fact = condition["fact"]
        if fact == "count":
            c = Criterion.model_validate(condition["criterion"])
            if c.subject != "guest":
                raise ValueError("count() requires a guest criterion")
            value = sum(match_guest(g, c) for g in present)
        elif fact in facts:
            value = facts[fact]
        else:
            raise ValueError(f"Unknown table fact {fact!r}")
        if not compare_value(value, condition["op"], condition["value"]):
            return False
    return True


class GenericRule(BaseModel):
    """Event-owned rule instance. All target and criterion selectors are data."""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = ""
    description: str = ""
    enabled: bool = Field(default=True, strict=True)
    engine: Literal["intra", "inter", "venue", "stage"]
    mechanism: str
    mode: Literal["hard", "soft", "staged", "mark"]
    polarity: Literal["reward", "penalty"] | None = None
    weight: int | None = None
    criterion: dict[str, Any] | None = None
    target: str | None = None
    targets: list[str] | None = None
    relation: Literal["together", "apart"] | None = None
    property: str | None = None
    table: str | None = None
    zones: list[str] | None = None
    tiers: list[dict[str, list[str]]] | None = None
    conditions: list[dict[str, Any]] | None = None
    exclusions: list[str] | None = None
    grade: int | None = None
    selector: Literal["direct", "criterion"] | None = None
    unit: str | None = None
    # Full v1 payload survives migration for audited, reversible conversion.
    # This field is provenance only and MUST NOT drive the generic engine.
    legacy_source: dict[str, Any] | None = None

    @builtins.property
    def display_name(self) -> str:
        return self.name.strip() or self.id

    @model_validator(mode="after")
    def check(self) -> "GenericRule":
        if not self.enabled:
            return self
        modes = ENGINES.get(self.engine, {}).get(self.mechanism)
        if modes is None:
            raise ValueError(f"Unknown {self.engine} mechanism {self.mechanism!r}")
        if self.mode not in modes:
            raise ValueError(f"{self.mechanism} expects mode in {modes}")
        if self.mode == "soft":
            if type(self.weight) is not int or self.weight <= 0:
                raise ValueError("Soft rules require a positive integer weight")
            if self.polarity is None:
                raise ValueError("Soft rules require explicit polarity")
            required = SCORING_POLARITY.get((self.engine, self.mechanism))
            if required is not None and required != self.polarity:
                raise ValueError(f"{self.mechanism} requires polarity={required}")
        elif self.weight is not None:
            raise ValueError("Hard, staged and mark rules cannot carry weight")
        if self.criterion is not None:
            Criterion.model_validate(self.criterion)
        for c in self.conditions or []:
            if not isinstance(c, dict) or c.get("fact") not in (
                "groups_at_table", "occupied_seats", "empty_seats", "count"
            ):
                raise ValueError("Invalid table pattern fact")
            if c.get("op") not in OPERATORS[:-1] or type(c.get("value")) is not int or c["value"] < 0:
                raise ValueError("Invalid table pattern comparison")
            if c["fact"] == "count":
                if "criterion" not in c:
                    raise ValueError("count() requires a criterion")
                if Criterion.model_validate(c["criterion"]).subject != "guest":
                    raise ValueError("count() requires a guest criterion")
            elif "criterion" in c:
                raise ValueError("Only count() may carry a nested criterion")
        if self.mechanism in ("criterion_pairs", "own_attribute_grouping",
                              "placement_by_criterion", "property_need", "property_fit") and self.criterion is None:
            raise ValueError(f"{self.mechanism} needs a criterion")
        if self.mechanism in ("criterion_pairs", "own_attribute_grouping"):
            if Criterion.model_validate(self.criterion).subject != "guest":
                raise ValueError("Pair grouping requires a guest criterion")
            # None means historical B2 all-pairs / A3 within-family behavior.
            # Explicit within/across have their literal pair-filter meaning.
        if self.mechanism == "pair_relation" and (
            not self.targets or len(self.targets) != 2 or self.relation is None
        ):
            raise ValueError("Pair relation requires two targets and a relation")
        if self.mechanism == "priority_mark" and (
            type(self.grade) is not int or self.grade < 1 or self.selector not in ("direct", "criterion")
        ):
            raise ValueError("Priority mark requires selector and positive grade")
        if self.mechanism == "priority_mark" and (
            (self.selector == "direct" and not self.target) or
            (self.selector == "criterion" and self.criterion is None)
        ):
            raise ValueError("Priority mark needs a direct target or criterion")
        if self.mechanism == "table_pattern" and not self.conditions:
            raise ValueError("Table pattern requires conditions")
        if self.mechanism in ("property_need", "property_fit") and not self.property:
            raise ValueError("Property mechanism requires a table property")
        if self.mechanism == "locked_assignment" and (not self.target or not self.table):
            raise ValueError("Locked assignment requires target and table")
        if self.mechanism == "tiered_placement" and (not self.target or not self.tiers):
            raise ValueError("Tiered placement requires target and tiers")
        if self.mechanism == "placement_by_criterion" and not self.zones:
            raise ValueError("Placement rule requires zones")
        if self.mechanism == "companionship" and (
            len(self.exclusions or []) != len(set(self.exclusions or []))
        ):
            raise ValueError("Companionship exclusions must be unique")
        return self


def mechanism_catalog() -> list[dict[str, Any]]:
    """Feature catalog is derived from evaluators' mechanism identities."""
    return [{"engine": engine, "mechanism": mechanism, "modes": list(modes)}
            for engine, mechanisms in ENGINES.items()
            for mechanism, modes in mechanisms.items()]


def split_dominance_warnings(rules: Sequence[GenericRule], *,
                             guest_count: int, table_count: int) -> list[str]:
    """Conservative ordinary-pool bound. Report; NEVER modify entered weights."""
    active = [r for r in rules if r.enabled and r.mode == "soft"]
    split = next((r for r in active if r.engine == "intra" and r.mechanism == "split_term"), None)
    if split is None:
        return []
    ordinary = 0
    for rule in active:
        if rule is split or rule.mechanism == "holes_term":
            continue
        count = (guest_count * (guest_count - 1) // 2
                 if rule.mechanism in ("criterion_pairs", "own_attribute_grouping")
                 else table_count if rule.mechanism in ("table_pattern", "companionship")
                 else guest_count)
        ordinary += count * rule.weight
    return ([f"Split weight {split.weight} is too close to conservative ordinary pool "
             f"{ordinary} (90% threshold); operator must review split dominance"]
            if ordinary * 10 >= split.weight * 9 else [])
