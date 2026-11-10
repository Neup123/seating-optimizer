/* Shared v2 plan selection contract; no seating or chair decisions are made here. */
export function planItem(kind, id) {
  if (!["person", "party"].includes(kind) || typeof id !== "string" || !id)
    throw Error("A plan selection needs a person or party ID.");
  return { kind, id };
}

export function togglePlanSelection(current, kind, id) {
  const next = planItem(kind, id);
  return current?.kind === kind && current?.id === id ? null : next;
}

export function assignmentMatchesSelection(assignment, selection) {
  if (!selection) return false;
  return selection.kind === "party"
    ? assignment.group_id === selection.id
    : selection.kind === "person" && (assignment.guest_ids || []).includes(selection.id);
}

export function selectedPlanAssignments(plan, selection) {
  return (plan?.assignments || []).filter(a => assignmentMatchesSelection(a, selection));
}

export function partyTotals(plan) {
  const totals = new Map();
  for (const a of plan?.assignments || [])
    totals.set(a.group_id, (totals.get(a.group_id) || 0) + (a.guest_ids || []).length);
  return totals;
}

export function portionLabel(assignment, totals, partyName) {
  const here = (assignment.guest_ids || []).length;
  const total = totals.get(assignment.group_id) || here;
  return partyName(assignment) + " — " + (total > here ? here + "/" + total : here);
}
