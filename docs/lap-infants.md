## Lap infants and physical chair capacity

An infant sitting on an adult's lap must be **explicitly identified** rather than inferred from an age label. In a CSV/XLSX import, provide a column such as `Lap infants` and map it to **Infants on lap (no chair)**. A registration with `Size=3` and `Lap infants=1` still produces three named attendees, but uses two chairs. An omitted or blank infant count means zero lap infants; counts must be nonnegative whole numbers no larger than the registration size.

For direct API callers, set `requires_chair: false` on a `Guest` who does not need a physical seat. The default is `true`, including when `age_layer` is `Baby`; the age label alone never changes physical capacity. Every attendee remains a member of the family, has a table assignment and appears in exports. A lap infant in an explicitly split family stays at the same table as the first chair-using family member.

Table capacities, occupied-chair figures, empty-chair counts and fill-efficiency scoring use actual chair occupancy, not the raw attendee count. The family size, display names and registration identity continue to include the infants. This is a capacity exemption, not an automatic permission to split a family or exceed physical chairs.

**Test/acceptance:** `python -m pytest -q tests/test_lap_infants.py`; then run the full Python and browser suites. For a family of three (two adults, one lap infant) at a two-chair table, expect a feasible assignment listing all three family members and table occupancy 2/2. For the same family without the explicit lap exemption, expect infeasible.
