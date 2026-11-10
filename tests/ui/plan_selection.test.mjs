import test from "node:test";
import assert from "node:assert/strict";
import { planItem, togglePlanSelection, assignmentMatchesSelection,
  selectedPlanAssignments, partyTotals, portionLabel } from "../../src/seating_optimizer/api/web/plan-selection.js";

const plan = {
  assignments: [
    { group_id: "fam", table_id: "A", guest_ids: ["p1", "p2", "p3", "p4"] },
    { group_id: "fam", table_id: "B", guest_ids: ["p5", "p6", "p7"] },
    { group_id: "solo", table_id: "B", guest_ids: ["s1"] }
  ]
};
test("one shared selection can identify a person or all split portions of their party", () => {
  assert.deepEqual(planItem("person", "p5"), { kind: "person", id: "p5" });
  assert.throws(() => planItem("chair", "1"), /person or party/);
  assert.throws(() => planItem("person", ""), /person or party/);
  assert.deepEqual(selectedPlanAssignments(plan, { kind: "person", id: "p5" })
    .map(a => a.table_id), ["B"]);
  assert.deepEqual(selectedPlanAssignments(plan, { kind: "party", id: "fam" })
    .map(a => a.table_id), ["A", "B"]);
  assert.equal(assignmentMatchesSelection(plan.assignments[2], { kind: "party", id: "fam" }), false);
  const selected = togglePlanSelection(null, "party", "fam");
  assert.deepEqual(selected, { kind: "party", id: "fam" });
  assert.equal(togglePlanSelection(selected, "party", "fam"), null);
  assert.deepEqual(togglePlanSelection(selected, "person", "p2"),
    { kind: "person", id: "p2" });
  assert.deepEqual(selectedPlanAssignments(plan, { kind: "person", id: "not-here" }), []);
});

test("party heading always reports registered party and per-table fractions without chair numbers", () => {
  const totals = partyTotals(plan);
  assert.equal(totals.get("fam"), 7);
  assert.equal(portionLabel(plan.assignments[0], totals, () => "Green Family"), "Green Family — 4/7");
  assert.equal(portionLabel(plan.assignments[1], totals, () => "Green Family"), "Green Family — 3/7");
  assert.equal(portionLabel(plan.assignments[2], totals, () => "Green Family"), "Green Family — 1");
  assert.deepEqual(partyTotals({ assignments: [] }).size, 0);
});
