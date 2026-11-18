"""Single chair-consumption definition shared by both seating solver versions.

People remain guests even if they sit on a guardian's lap. This affects only
physical capacity, not the number of people to print, notify or select.
"""
from __future__ import annotations


def chair_count(guests) -> int:
    return sum(1 for guest in guests if guest.requires_chair)


def chair_weight(guest) -> int:
    return int(guest.requires_chair)
