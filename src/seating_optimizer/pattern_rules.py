"""Composable whole-plan pattern rules over independently observed table counts.

Each rule is a conjunction of comparison clauses. The solver and report both use
these same validated primitives, avoiding a branch per user-authored pattern.
"""
from __future__ import annotations

from typing import Any

FACTS = ("groups_at_table", "occupied_seats", "empty_seats")
OPERATORS = ("==", "!=", "<", "<=", ">", ">=")
EFFECTS = ("penalty", "reward")


def validate_pattern(parameters: dict[str, Any], *, rule_id: str = "") -> None:
    prefix = f"Rule {rule_id}: " if rule_id else ""
    if parameters.get("scope", "global") != "global":
        raise ValueError(prefix + "global pattern scope must be global")
    if not isinstance(parameters.get("enabled", False), bool):
        raise ValueError(prefix + "enabled must be a boolean")
    if parameters.get("effect", "penalty") not in EFFECTS:
        raise ValueError(prefix + "effect must be penalty or reward")
    conditions = parameters.get("conditions")
    if not isinstance(conditions, list) or not 1 <= len(conditions) <= 8:
        raise ValueError(prefix + "conditions must contain between 1 and 8 comparisons")
    for i, condition in enumerate(conditions):
        if not isinstance(condition, dict) or set(condition) != {"fact", "op", "value"}:
            raise ValueError(prefix + f"condition {i+1} needs fact, op and value only")
        if condition["fact"] not in FACTS or condition["op"] not in OPERATORS:
            raise ValueError(prefix + f"condition {i+1} has an unknown fact or comparison")
        value = condition["value"]
        if type(value) is not int or value < 0 or value > 100000:
            raise ValueError(prefix + f"condition {i+1} value must be a nonnegative integer")


def pattern_matches(parameters: dict[str, Any], facts: dict[str, int]) -> bool:
    """Pure reporting evaluator of the same comparisons used by CP-SAT."""
    for clause in parameters["conditions"]:
        a, b = facts[clause["fact"]], clause["value"]
        comparison = clause["op"]
        if not {
            "==": lambda: a == b,
            "!=": lambda: a != b,
            "<": lambda: a < b,
            "<=": lambda: a <= b,
            ">": lambda: a > b,
            ">=": lambda: a >= b,
        }[comparison]():
            return False
    return True


def add_comparison(model, expr, operator: str, value: int, name: str):
    """Reify comparison both directions so boolean equals the actual predicate."""
    matched = model.NewBoolVar(name)
    expressions = {
        "==": (expr == value, expr != value),
        "!=": (expr != value, expr == value),
        "<": (expr < value, expr >= value),
        "<=": (expr <= value, expr > value),
        ">": (expr > value, expr <= value),
        ">=": (expr >= value, expr < value),
    }
    positive, negative = expressions[operator]
    model.Add(positive).OnlyEnforceIf(matched)
    model.Add(negative).OnlyEnforceIf(matched.Not())
    return matched


def add_pattern_match(model, parameters: dict[str, Any], table_id: str,
                      table_capacity: int, groups_at_table, occupied_seats):
    """Build an AND of arbitrary user-authored per-table comparisons."""
    facts = {
        "groups_at_table": groups_at_table,
        "occupied_seats": occupied_seats,
        "empty_seats": table_capacity - occupied_seats,
    }
    bits = [
        add_comparison(model, facts[clause["fact"]], clause["op"],
                       clause["value"], f"pattern:{table_id}:{index}")
        for index, clause in enumerate(parameters["conditions"])
    ]
    matched = model.NewBoolVar(f"pattern:matched:{table_id}")
    model.Add(sum(bits) == len(bits)).OnlyEnforceIf(matched)
    model.Add(sum(bits) <= len(bits) - 1).OnlyEnforceIf(matched.Not())
    return matched


def pattern_description(parameters: dict[str, Any]) -> str:
    return " AND ".join(
        f"{clause['fact'].replace('_', ' ')} {clause['op']} {clause['value']}"
        for clause in parameters["conditions"]
    )
