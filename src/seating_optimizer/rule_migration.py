"""Auditable v1-to-v2 migration for all thirteen legacy shapes.

There is no venue-specific name or rule ID in this converter. v1 source
records, including retired structural capacity pseudo-rules, are retained in
the report so an operator can verify the conversion before switching engines.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .generic_rules import GenericRule

LEGACY_SHAPES = frozenset({
    "attribute_grouping", "zone_restriction", "table_property_need", "pair",
    "capacity", "fill_efficiency", "pin", "global_pattern", "split_penalty",
    "small_group_priority", "low_priority", "tiered_placement", "zone_companionship",
})


def _data(rule: Any) -> dict[str, Any]:
    if isinstance(rule, Mapping):
        return deepcopy(dict(rule))
    return rule.model_dump(mode="json", exclude_none=False)


def _criterion(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": "guest", "field": parameters.get("attribute", ""),
        "op": parameters.get("op", "=="), "value": parameters.get("value"),
    }


def _derived_name(data: Mapping[str, Any]) -> str:
    """Human-readable default for unnamed legacy instances; never display an ID."""
    mechanisms = {
        "criterion_pairs": "Connect matching people",
        "placement_by_criterion": "Place matching guests on floors",
        "property_need": "Prefer a table property",
        "pair_relation": "Place families together or apart",
        "holes_term": "Avoid empty seats",
        "locked_assignment": "Lock a family to a table",
        "table_pattern": "Table occupancy pattern",
        "split_term": "Keep a family together",
        "property_fit": "Reward a matching table property",
        "priority_mark": "Mark a family's seating priority",
        "tiered_placement": "Placement preference tiers",
        "companionship": "Avoid solitary placement",
    }
    label = mechanisms.get(str(data["mechanism"]), str(data["mechanism"]).replace("_", " ").title())
    criterion = data.get("criterion")
    if isinstance(criterion, Mapping) and criterion.get("field"):
        operators = {"==": "is", "!=": "is not", "<": "below",
                     "<=": "at most", ">": "above", ">=": "at least", "in": "in"}
        field = str(criterion["field"]).replace("_", " ")
        value = criterion.get("value")
        if value is not None and value != "":
            value_text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            return f"{label}: {field} {operators.get(str(criterion.get('op')), 'matches')} {value_text}"
        return f"{label}: {field}"
    if data.get("property"):
        return f"{label}: {str(data['property']).replace('_', ' ')}"
    return label


def migrate_instance(rule: Any) -> GenericRule | None:
    """Translate by shape only; never look at an instance's ID or name."""
    source = _data(rule)
    shape = source.get("shape")
    if shape not in LEGACY_SHAPES:
        raise ValueError(f"Unknown legacy shape {shape!r}")
    if shape == "capacity":
        return None  # C4 is an unconditional manual table-capacity fact.
    p = source.get("parameters") or {}
    meta = {
        "id": source["id"], "name": source.get("name") or "",
        "description": source.get("description") or "",
        "enabled": source.get("enabled", True),
        "mode": source["mode"], "weight": source.get("weight"),
        "legacy_source": source,
    }
    if shape == "attribute_grouping":
        data = dict(engine="inter", mechanism="criterion_pairs",
                    # Unscoped B2 retains legacy all-pairs scoring, including
                    # 21 same-family pairs in the §13.1 seven-person golden.
                    criterion=_criterion(p),
                    polarity=p.get("effect", "reward"))
    elif shape == "zone_restriction":
        data = dict(engine="venue", mechanism="placement_by_criterion",
                    criterion=_criterion(p),
                    zones=p.get("allowed_zones", [p["zone"]] if "zone" in p else None),
                    polarity="reward" if source["mode"] == "soft" else None)
    elif shape == "table_property_need":
        data = dict(engine="venue", mechanism="property_need",
                    criterion=_criterion(p), property=p.get("property"),
                    polarity="penalty" if source["mode"] == "soft" else None)
    elif shape == "pair":
        data = dict(engine="inter", mechanism="pair_relation",
                    targets=[p.get("left", ""), p.get("right", "")],
                    relation=p.get("relation"),
                    polarity="reward" if source["mode"] == "soft" else None)
    elif shape == "fill_efficiency":
        data = dict(engine="venue", mechanism="holes_term", polarity="penalty",
                    unit="per empty seat at occupied table")
    elif shape == "pin":
        data = dict(engine="venue", mechanism="locked_assignment",
                    target=p.get("target"), table=p.get("table"))
    elif shape == "global_pattern":
        # The nested legacy switch predates the uniform instance.enabled flag.
        meta["enabled"] = bool(meta["enabled"] and p.get("enabled", False))
        data = dict(engine="inter", mechanism="table_pattern",
                    conditions=deepcopy(p.get("conditions")),
                    polarity=p.get("effect", "penalty"))
    elif shape == "split_penalty":
        data = dict(engine="intra", mechanism="split_term",
                    polarity="penalty", unit="per additional table")
    elif shape == "small_group_priority":
        data = dict(engine="venue", mechanism="property_fit",
                    criterion={"subject": "family", "field": "party_size",
                               "op": "<=", "value": 2},
                    property="small_group_priority", polarity="reward")
    elif shape == "low_priority":
        if p.get("selector") == "group":
            data = dict(engine="stage", mechanism="priority_mark",
                        selector="direct", target=p.get("group_id"), grade=p.get("grade"))
        else:
            data = dict(engine="stage", mechanism="priority_mark",
                        selector="criterion", grade=p.get("grade"),
                        criterion={"subject": "family", "field": "party_size",
                                   "op": "<", "value": p.get("threshold")})
    elif shape == "tiered_placement":
        data = dict(engine="venue", mechanism="tiered_placement",
                    target=p.get("target"), tiers=deepcopy(p.get("tiers")))
    elif shape == "zone_companionship":
        data = dict(engine="inter", mechanism="companionship", polarity="penalty",
                    exclusions=deepcopy(p.get("exclude_groups", [])),
                    unit="per lone group")
    else:
        # Exhaustiveness checked above; adding a shape without a handler fails.
        raise AssertionError(shape)
    if not str(meta["name"]).strip():
        meta["name"] = _derived_name(data)
    return GenericRule.model_validate({**meta, **data})


def migrate_rules(items: list[Any]) -> tuple[list[GenericRule], dict[str, Any]]:
    converted = []
    retired = []
    seen = set()
    for index, item in enumerate(items):
        source = _data(item)
        if source["id"] in seen:
            raise ValueError(f"Duplicate rule ID {source['id']!r}")
        seen.add(source["id"])
        changed = migrate_instance(source)
        if changed is None:
            retired.append({
                "index": index, "id": source["id"],
                "reason": "Structural capacity: manual Table.capacity is always enforced; "
                          "the v1 pseudo-rule is retired, with no behavior change.",
                "legacy_source": source,
            })
        else:
            converted.append(changed)
    report = {
        "input_instances": len(items),
        "migrated_instances": len(converted),
        "retired_instances": len(retired),
        "mapped_shapes": sorted({_data(item)["shape"] for item in items}),
        "retired": retired,
        "instance_ids": [item.id for item in converted],
        "compatibility_notes": [
            "Legacy attribute_grouping includes same-family pair points; "
            "migrated v2 criterion_pairs leaves scope unset for all-pairs "
            "parity (§13.1); explicit across excludes same-family pairs.",
            "Legacy soft table-property needs earn rewards when satisfied; "
            "v2 property_need penalizes unsatisfied affected guests.",
        ],
    }
    return converted, report


def migrate_configuration(configuration: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if configuration.get("version", 1) != 1:
        raise ValueError("Only version-1 configurations can be migrated")
    out = deepcopy(dict(configuration))
    converted, report = migrate_rules(out.get("rules", []))
    out["version"] = 2
    out["rules"] = [rule.model_dump(mode="json", exclude_none=True) for rule in converted]
    return out, report


def reconstruct_v1_rules(rules: list[GenericRule], report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Audit-only exact reconstruction from provenance and retirement ledger."""
    entries = [deepcopy(rule.legacy_source) for rule in rules]
    if any(entry is None for entry in entries):
        raise ValueError("Cannot reverse a new v2 rule without v1 provenance")
    for retired in sorted(report.get("retired", []), key=lambda x: x["index"]):
        entries.insert(retired["index"], deepcopy(retired["legacy_source"]))
    if len(entries) != report["input_instances"]:
        raise ValueError("Migration report does not match source rule count")
    return entries
