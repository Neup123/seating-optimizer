"""Phase 4: migrated rule names are human-facing without changing solver semantics."""
from seating_optimizer.rule_migration import migrate_instance


def test_unnamed_migrated_criterion_gets_readable_title():
    rule = migrate_instance({
        "id": "hebrew-upper-preference",
        "shape": "zone_restriction",
        "mode": "soft",
        "weight": 2,
        "parameters": {
            "attribute": "language", "op": "==", "value": "Hebrew",
            "allowed_zones": ["upper"],
        },
    })
    assert rule is not None
    assert rule.id == "hebrew-upper-preference"
    assert rule.name == "Place matching guests on floors: language is Hebrew"
    assert rule.legacy_source["id"] == rule.id


def test_operator_supplied_name_is_not_rewritten():
    rule = migrate_instance({
        "id": "named-rule",
        "name": "My own placement preference",
        "shape": "split_penalty",
        "mode": "soft",
        "weight": 5,
        "parameters": {},
    })
    assert rule is not None
    assert rule.name == "My own placement preference"


def test_other_unnamed_shapes_get_names_without_leaking_rule_ids():
    rule = migrate_instance({
        "id": "opaque-internal-123",
        "shape": "split_penalty",
        "mode": "soft",
        "weight": 5,
        "parameters": {},
    })
    assert rule is not None
    assert rule.name == "Keep a family together"
    assert "opaque-internal-123" not in rule.name
