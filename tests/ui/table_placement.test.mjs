import test from "node:test";
import assert from "node:assert/strict";
import { nextFreeTablePosition } from "../../src/seating_optimizer/api/web/app.js";

const disjoint = (a, b, gap = 8) =>
  a.x + a.width + gap <= b.x || b.x + b.width + gap <= a.x ||
  a.y + a.height + gap <= b.y || b.y + b.height + gap <= a.y;

test("new tables occupy usable non-overlapping slots in row-first order", () => {
  const floor = { width: 700, height: 450, tables: [] };
  for (let i = 0; i < 12; i++) {
    const position = nextFreeTablePosition(floor, 160, 125);
    assert.ok(position, "grid must fit the intended 12-table two-floor QA pattern");
    const drawing = { ...position, width: 160, height: 125, table_id: "T" + i };
    assert.ok(floor.tables.every(other => disjoint(drawing, other)));
    floor.tables.push(drawing);
  }
  assert.deepEqual(floor.tables[0].x, 8);
  assert.deepEqual(floor.tables[0].y, 8);
  assert.ok(floor.tables[1].x > floor.tables[0].x);
});

test("placement considers manually moved drawings and rejects full floors", () => {
  const floor = { width: 320, height: 240, tables: [
    { table_id: "manual", x: 20, y: 10, width: 160, height: 125 }
  ] };
  assert.equal(nextFreeTablePosition(floor, 160, 125), null);
  assert.equal(nextFreeTablePosition({ width: 150, height: 100, tables: [] }, 160, 125), null);
});

test("zero-offset placement stays possible on exact-fit floors", () => {
  assert.deepEqual(nextFreeTablePosition({ width: 160, height: 125, tables: [] }, 160, 125),
    { x: 0, y: 0 });
});
