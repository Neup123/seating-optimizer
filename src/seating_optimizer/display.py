"""Human-facing party identity, independent from IDs and synthetic guest labels."""
from __future__ import annotations

import re

from .models import Assignment, NotSeatedGroup, Plan

_SYNTHETIC = re.compile(r"^(.+) \(([1-9][0-9]*)/([1-9][0-9]*)\)$")


def synthetic_party_name(names: list[str]) -> str | None:
    """Recognize the importer's generated (k/N) names, including split subsets."""
    if not names:
        return None
    matches = [_SYNTHETIC.fullmatch(name) for name in names]
    if not all(matches):
        return None
    first = matches[0]
    if all(match.group(1) == first.group(1)
           and match.group(3) == first.group(3)
           and int(match.group(2)) <= int(match.group(3))
           for match in matches):
        return first.group(1)
    return None


def distinct_party_name(group_id: str, candidates: list[str | None], names: list[str]) -> str | None:
    """Accept only one unambiguous party label that is not any member's name.

    Used during import and solve so every downstream output receives the same
    safe group_name. Raw internal IDs are never presentation labels.
    """
    members = {name.strip().casefold() for name in names}
    labels: dict[str, str] = {}
    for candidate in candidates:
        label = (candidate or "").strip()
        if (not label or (len(names) != 1 and label.casefold() in members)
                or label.casefold().startswith(("registration:", "guest:"))):
            continue
        labels.setdefault(label.casefold(), label)
    return next(iter(labels.values())) if len(labels) == 1 else None


def party_name_for(group_id: str, group_name: str | None, names: list[str]) -> str:
    """Use a distinct party label or a neutral count-bearing header."""
    label = distinct_party_name(group_id, [group_name], names)
    if label:
        return label
    # Backward compatibility for synthetic members in pre-metadata Plans.
    inferred = synthetic_party_name(names)
    if (inferred is not None
            and not inferred.casefold().startswith(("registration:", "guest:"))
            and inferred.casefold() not in {name.strip().casefold() for name in names}):
        return inferred
    # A single registered guest is also the party's registered name.
    # The stored group_name may be missing in old plans or manual API inputs.
    if len(names) == 1 and group_id.startswith(("registration:", "guest:")):
        # A split portion of a larger unlabelled group can also have one
        # member; never promote that member to the whole party's heading.
        registered = names[0].strip()
        if registered and not registered.casefold().startswith(("registration:", "guest:")):
            return registered
    members = {name.strip().casefold() for name in names}
    neutral = "Guest" if len(names) == 1 else "Party"
    while neutral.casefold() in members:
        neutral = "Unnamed " + neutral
    return neutral


def assignment_name(entry: Assignment | NotSeatedGroup) -> str:
    return party_name_for(entry.group_id, entry.group_name, entry.guest_names)


def visible_member_names(entry: Assignment | NotSeatedGroup) -> list[str]:
    """An imported registration has no individually named guests."""
    party = assignment_name(entry)
    generated = synthetic_party_name(entry.guest_names)
    if generated == party or all(not name.strip() or name == party for name in entry.guest_names):
        return []
    return list(entry.guest_names)


def party_totals(plan: Plan) -> dict[str, int]:
    """Whole-party sizes from all table portions; original member JSON is untouched."""
    totals: dict[str, int] = {}
    for entry in plan.assignments:
        totals[entry.group_id] = totals.get(entry.group_id, 0) + len(entry.guest_ids)
    return totals


def party_header(entry: Assignment, totals: dict[str, int]) -> str:
    """Split portions show at-this-table/whole-party; whole parties show a count."""
    at_table = len(entry.guest_ids)
    whole = totals.get(entry.group_id, at_table)
    size = f"{at_table}/{whole}" if whole > at_table else str(at_table)
    return f"{assignment_name(entry)} — {size}"


def party_lines(entry: Assignment, totals: dict[str, int]) -> list[str]:
    """A count-bearing header and any genuine member names beneath it."""
    return [party_header(entry, totals), *(f"  {name}" for name in visible_member_names(entry))]


def counted(number: int, singular: str, plural: str | None = None) -> str:
    """Natural-language counts in all generated explanations."""
    return f"{number} {singular if number == 1 else (plural or singular + 's')}"
