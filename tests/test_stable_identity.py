"""Stable registration IDs survive row insertions/reordering; changed names fail closed."""
from __future__ import annotations

from seating_optimizer import Guest, Problem, Rule, Table, Zone, import_registrations
from pydantic import ValidationError
import pytest


def get(source: bytes):
    imported = import_registrations(source, "event.csv")
    assert not imported.has_errors, imported.issues
    return imported.guests


def test_reordering_and_removing_registrations_does_not_retarget_guest_or_party_ids():
    first = get(b"Name,Size,Language\nFamily Alpha,2,English\nFamily Beta,1,Greek\nFamily Gamma,3,Hebrew\n")
    changed = get(b"Name,Size,Language\nNew Registration,1,Greek\nFamily Gamma,3,Hebrew\nFamily Alpha,2,English\n")
    def by_name(guests):
        return {g.name: (g.id, g.group_id) for g in guests}
    before, after = by_name(first), by_name(changed)
    for name in ["Family Alpha (1/2)", "Family Alpha (2/2)", "Family Gamma (1/3)", "Family Gamma (3/3)"]:
        assert before[name] == after[name]
    assert before["Family Beta"][1] not in {g.group_id for g in changed}
    assert all(g.group_id.startswith("registration:stable:") for g in changed)


def test_same_party_with_changed_attribute_preserves_binding():
    a = get(b"Name,Size,Language\nFamily Alpha,2,English\n")
    b = get(b"Name,Size,Language\nFamily Alpha,2,Greek\n")
    assert [(g.id, g.group_id) for g in a] == [(g.id, g.group_id) for g in b]


def test_name_correction_fails_closed_for_stale_pair_and_pin_rules():
    a = get(b"Name,Size\nFamily Alpha,2\nFamily Beta,1\n")
    b = get(b"Name,Size\nFamily Alpha Corrected,2\nFamily Beta,1\n")
    old = next(g.group_id for g in a if g.name.startswith("Family Alpha"))
    assert old not in {g.group_id for g in b}
    p = Problem(session_id="rename", zones=[Zone(id="z",name="Z")],
        tables=[Table(id="T",zone_id="z",capacity=3)],
        guests=b, rules=[Rule(id="old-pin",shape="pin",mode="hard",
                            parameters={"target":old,"table":"T"})])
    # Problem validation can accept a stale rule's syntax, but solve must reject
    # unknown binding rather than apply it to an unrelated registration.
    from seating_optimizer import solve
    with pytest.raises(ValueError, match="unknown target"):
        solve(p)


def test_explicit_stable_source_id_remains_preferred_for_shared_named_family_rows():
    a = get(b"Name,Size,Group ID\nAlice Green,1,green-family\nBob Green,1,green-family\n")
    b = get(b"Name,Size,Group ID\nBob Green,1,green-family\nAlice Green,1,green-family\n")
    assert {g.group_id for g in a} == {"green-family"}
    assert {g.group_id for g in b} == {"green-family"}
    assert {g.id for g in a} == {g.id for g in b}
