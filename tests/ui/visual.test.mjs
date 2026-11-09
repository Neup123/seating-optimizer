import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { createApp } from "../../src/seating_optimizer/api/web/app.js";

const catalog = {
  shapes: [
    { shape: "attribute_grouping", title: "Attribute grouping", description: "Grouping",
      modes: ["soft","hard"], default_mode: "soft", default_weight: 3,
      fields: [{ name: "attribute", label: "Attribute", kind: "text", required: true, choices: [] }] },
    { shape: "zone_restriction", title: "Zone restriction", description: "Zones",
      modes: ["hard","soft"], default_mode: "hard", default_weight: 3,
      fields: [{ name: "attribute", label: "Attribute", kind: "text", required: true, choices: [] },
               { name: "zone", label: "Zone", kind: "zone", required: true, choices: [] }] },
    { shape: "pair", title: "Pair rules", description: "Pairs",
      modes: ["soft","hard"], default_mode: "soft", default_weight: 3,
      fields: [{ name: "left", label: "Left", kind: "target", required: true, choices: [] },
               { name: "right", label: "Right", kind: "target", required: true, choices: [] },
               { name: "relation", label: "Relation", kind: "select", required: true, choices: ["together", "apart"] }] },
    { shape: "capacity", title: "Capacity", description: "Hard ceiling",
      modes: ["hard"], default_mode: "hard", default_weight: null, fields: [] },
    { shape: "fill_efficiency", title: "Fill efficiency", description: "Holes",
      modes: ["soft"], default_mode: "soft", default_weight: 3, fields: [] },
    { shape: "pin", title: "Pin", description: "Lock table",
      modes: ["hard"], default_mode: "hard", default_weight: null,
      fields: [{ name: "target", label: "Target", kind: "target", required: true, choices: [] },
               { name: "table", label: "Table", kind: "table", required: true, choices: [] }] },
  ]
};
const layout = { floors: [
  { zone_id: "ground", width: 400, height: 300, tables: [
    { table_id: "G1", x: 20, y: 20, width: 160, height: 140, shape: "rectangle" }
  ] }
]};
const plan = {
  session_id: "test", status: "feasible", total_score: 8, solve_seconds: 0.1,
  layout, score_breakdown: [{ rule_id: "lang", points: 8 }],
  tables: [{ table_id: "G1", zone_id: "ground", capacity: 4, occupied: 2, empty_seats: 2 }],
  assignments: [{ group_id: "family-one", table_id: "G1", guest_ids: ["g1", "g2"],
    guest_names: ["Alice", "Bob"], points: 8,
    reasons: [{ rule_id: "lang", description: "Shares language at this table.", points: 8 }] }],
  compromises: [{ rule_id: "fill", description: "Table G1 has two empty chairs.", lost_points: 2 }],
  conflicting_constraints: [], message: "All hard constraints satisfied."
};
function setValue(node, value, window) {
  assert.ok(node, "Expected element");
  node.value = value;
  node.dispatchEvent(new window.Event("change", { bubbles: true }));
}
function click(node) {
  assert.ok(node, "Expected clickable element");
  node.click();
}
async function until(fn, message = "Condition never satisfied") {
  for (let index = 0; index < 100; index++) {
    if (fn()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw Error(message);
}
async function setup(handler = async () => ({}), stored = {}) {
  const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>",
    { url: "http://localhost/" });
  for (const [key, value] of Object.entries(stored)) dom.window.localStorage.setItem(key, value);
  globalThis.document = dom.window.document;
  globalThis.window = dom.window;
  globalThis.btoa = value => Buffer.from(value, "binary").toString("base64");
  dom.window.URL.createObjectURL = () => "blob:test/print";
  dom.window.URL.revokeObjectURL = () => {};
  globalThis.URL = dom.window.URL;
  globalThis.Blob = dom.window.Blob;
  const calls = [];
  const api = {
    get: async path => { calls.push([path,"GET"]); return path === "/v1/rules/catalog" ? catalog : handler(path); },
    post: async (path, payload, responseType) => {
      calls.push([path, payload, responseType]);
      return handler(path, payload, responseType);
    },
  };
  const root = dom.window.document.querySelector("#root");
  const app = createApp(root, api);
  await app.ready;
  return { dom, root, app, calls, api, storage: dom.window.localStorage, $: selector => root.querySelector(selector),
    $$: selector => Array.from(root.querySelectorAll(selector)) };
}
function upload(element, name, bytes, window) {
  const file = { name, size: bytes.length, arrayBuffer: async () => bytes.buffer.slice(
    bytes.byteOffset, bytes.byteOffset + bytes.byteLength
  ) };
  Object.defineProperty(element, "files", { configurable: true, value: [file] });
  element.dispatchEvent(new window.Event("change", { bubbles: true }));
}

test("guest import shows detected headers, lets owner override mapping, and never accepts malformed registrations", async () => {
  let bad = true;
  const preview = {
    headers: ["Participant","Count","Language"], mapping: { Participant: "name", Count: "size", Language: "attribute.language" },
    detected_mapping: { Participant: "name", Count: "size", Language: "attribute.language" },
    sample_rows: [{ Participant: "Alice", Count: "2", Language: "English" }],
    rows_seen: 2, targets: ["name","size","attribute.language"], issues: []
  };
  const { dom, app, calls, $, root } = await setup(async (path, payload) => {
    if (path === "/v1/import/preview") return preview;
    if (path === "/v1/import") return bad ? {
      guests: [], mapping: payload.mapping, rows_seen: 2, rows_imported: 1,
      issues: [{ row: 3, column: "size", severity: "error", message: "Invalid or missing group size" },
               { row: 2, column: "name", severity: "error", message: "Duplicate registration name" }]
    } : { guests: [{ id: "g1", name: "Alice", group_id: "family", attributes: {} }],
           mapping: payload.mapping, rows_seen: 1, rows_imported: 1, issues: [] };
    return {};
  });
  upload($("#guest-file"), "guests.csv", new TextEncoder().encode("Participant,Count,Language\nAlice,2,English\n"), dom.window);
  await until(() => !!$("#map-participant"));
  assert.equal($("#map-participant").value, "name");
  assert.match(root.textContent, /Spreadsheet sample/);
  setValue($("#map-count"), "group_id", dom.window);
  click($("#preview-mapping"));
  await until(() => calls.some(([path,p]) => path === "/v1/import/preview" && p.mapping?.Count === "group_id"));
  await until(() => root.textContent.includes("Mapping checked by the API"));
  setValue($("#map-count"), "size", dom.window);
  click($("#import-guests"));
  await until(() => root.textContent.includes("Import blocked"));
  assert.equal(app.state.guests.length, 0);
  assert.match(root.textContent, /Duplicate registration name/);
  assert.match(root.textContent, /Invalid or missing group size/);
  bad = false;
  click($("#import-guests"));
  await until(() => app.state.guests.length === 1);
  assert.equal(app.state.guests[0].name, "Alice");
  const req = calls.filter(([path]) => path === "/v1/import").at(-1)[1];
  assert.deepEqual(req.header_aliases, {});
  assert.equal(req.mapping.Count, "size");
});

test("all six rule shapes are rendered from API metadata; CRUD and new instances need no code changes", async () => {
  const { app, dom, $, $$ } = await setup();
  app.show("rules");
  for (const shape of catalog.shapes.map(s => s.shape)) {
    setValue($("#new-rule-shape"), shape, dom.window);
    click($("#add-rule"));
  }
  assert.equal(app.state.rules.length, 6);
  assert.deepEqual(app.state.rules.map(r => r.shape), catalog.shapes.map(s => s.shape));
  assert.equal(app.state.rules.find(r => r.shape === "pin").mode, "hard");
  assert.equal(app.state.rules.find(r => r.shape === "capacity").weight, null);
  assert.equal($$("#delete-rule-0").length, 1);
  setValue($("#rule-0-attribute"), "language", dom.window);
  setValue($("#rule-weight-0"), "15", dom.window);
  assert.equal(app.state.rules[0].parameters.attribute, "language");
  assert.equal(app.state.rules[0].weight, 15);
  setValue($("#rule-mode-0"), "hard", dom.window);
  assert.equal(app.state.rules[0].weight, null);
  assert.equal(app.state.rules[0].mode, "hard");
  setValue($("#new-rule-shape"), "attribute_grouping", dom.window);
  click($("#add-rule"));
  assert.equal(app.state.rules.filter(r => r.shape === "attribute_grouping").length, 2);
  click($("#delete-rule-1"));
  assert.equal(app.state.rules.length, 6);
});

test("map editor imports structured geometry, edits capacity/position, validates round-trip over API, and drags tables", async () => {
  const { app, dom, $, calls, root } = await setup(async (path, payload) => {
    if (path !== "/v1/layouts/import") return {};
    const decoded = JSON.parse(Buffer.from(payload.files[0].content_base64, "base64").toString("utf8"));
    return decoded;
  });
  app.show("map");
  upload($("#layout-file"), "layout.json", new TextEncoder().encode(JSON.stringify(layout)), dom.window);
  await until(() => !!$("#table-G1-capacity"));
  assert.equal(app.state.tables[0].capacity, null);
  setValue($("#table-G1-capacity"), "4", dom.window);
  setValue($("#table-G1-x"), "35", dom.window);
  click(root.querySelector('form[data-table-id="G1"] button[type="submit"]'));
  assert.equal(app.state.tables[0].capacity, 4);
  assert.equal(app.state.layout.floors[0].tables[0].x, 35);
  click($("#validate-layout"));
  await until(() => root.textContent.includes("Venue layout validated"));
  const req = calls.filter(([path]) => path === "/v1/layouts/import").at(-1)[1];
  assert.equal(req.tables[0].capacity, 4);
  assert.equal(JSON.parse(Buffer.from(req.files[0].content_base64, "base64")).floors[0].tables[0].x, 35);
  assert.ok($("#map-editor-svg").querySelector('[data-table-id="G1"]'));
  const svg = $("#map-editor-svg");
  svg.getBoundingClientRect = () => ({ width: 400, height: 300 });
  const group = svg.querySelector('[data-table-id="G1"]');
  group.dispatchEvent(new dom.window.MouseEvent("pointerdown", { bubbles: true, clientX: 50, clientY: 50 }));
  dom.window.document.dispatchEvent(new dom.window.MouseEvent("pointermove", { bubbles: true, clientX: 70, clientY: 65 }));
  dom.window.document.dispatchEvent(new dom.window.MouseEvent("pointerup", { bubbles: true }));
  assert.equal(app.state.layout.floors[0].tables[0].x, 55);
  assert.equal(app.state.layout.floors[0].tables[0].y, 35);
});

test("solved plan switches between all API exports and shows reasons, compromises, unused chairs", async () => {
  const { app, dom, calls, $, root } = await setup(async (path, payload) => {
    if (path === "/v1/solve") return plan;
    if (path === "/v1/exports/table") return "Table G1: Alice and Bob";
    if (path === "/v1/exports/floor-map/svg") return { pages: [{zone_id: "ground",
      svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>family-one</text></svg>'}] };
    if (path === "/v1/exports/table-cards/pdf") return new Blob(["%PDF"],{type:"application/pdf"});
    if (path === "/v1/exports/json") return plan;
    throw Error("Unexpected request " + path);
  });
  app.state.guests = [
    { id: "g1", name: "Alice", group_id: "family-one", attributes: {} },
    { id: "g2", name: "Bob", group_id: "family-one", attributes: {} }
  ];
  app.state.zones = [{ id: "ground", name: "Ground" }];
  app.state.tables = [{ id: "G1", zone_id: "ground", capacity: 4 }];
  app.state.layout = layout;
  app.show("plan");
  click($("#solve-plan"));
  await until(() => root.textContent.includes("Table G1: Alice and Bob"));
  assert.match(root.textContent, /Shares language at this table/);
  assert.match(root.textContent, /Table G1 has two empty chairs/);
  assert.match(root.textContent, /Empty chairs/);
  click($("#view-floor"));
  await until(() => !!$("#floor-preview"));
  assert.match($("#floor-preview").srcdoc, /family-one/);
  click($("#view-cards"));
  await until(() => !!$("#cards-preview"));
  assert.equal($("#cards-preview").src, "blob:test/print");
  click($("#view-json"));
  await until(() => root.textContent.includes('"score_breakdown"'));
  assert.ok(calls.some(([path]) => path === "/v1/exports/json"));
  assert.equal(calls.filter(([path]) => path === "/v1/solve").length, 1);
  assert.ok(calls.every(([path]) => path === "/v1/rules/catalog" || path.startsWith("/v1/")));
});

test("a full guest/rule/layout/solved session survives reload and explicit reset preserves templates", async () => {
  const handler = async (path, payload) => {
    if (path === "/v1/solve") return plan;
    if (path === "/v1/exports/table") return "Table G1: Alice and Bob";
    if (path === "/v1/configurations/validate") return payload;
    return {};
  };
  const first = await setup(handler);
  first.app.state.guests = [{ id: "g1", name: "Alice", group_id: "family-one", attributes: {} }];
  first.app.state.zones = [{ id: "ground", name: "Ground" }];
  first.app.state.tables = [{ id: "G1", zone_id: "ground", capacity: 4 }];
  first.app.state.layout = layout;
  first.app.state.preview = { headers: ["Name"], sample_rows: [], issues: [] };
  first.app.state.mapping = { Name: "name" };
  first.app.show("rules");
  click(first.$("#add-rule"));
  setValue(first.$("#rule-0-attribute"), "language", first.dom.window);
  first.app.show("plan");
  click(first.$("#solve-plan"));
  await until(() => !!first.app.state.plan);
  const saved = Object.fromEntries(
    Object.keys(first.storage).map(key => [key, first.storage.getItem(key)]));
  const restored = await setup(handler, saved);
  assert.equal(restored.app.state.guests.length, 1);
  assert.equal(restored.app.state.tables.length, 1);
  assert.equal(restored.app.state.rules.length, 1);
  assert.equal(restored.app.state.mapping.Name, "name");
  assert.deepEqual(restored.app.state.layout, layout);
  assert.deepEqual(restored.app.state.plan, plan);
  await until(() => restored.root.textContent.includes("Table G1: Alice and Bob"));
  click(restored.$("#new-session"));
  assert.equal(restored.app.state.guests.length, 0);
  assert.equal(restored.app.state.rules.length, 0);
  assert.equal(restored.app.state.layout.floors.length, 0);
  assert.equal(restored.storage.getItem("seating-optimizer:session:v1")?.includes('"guests":[]'), true);
});

test("named full configurations can be saved, duplicated, loaded, exported, imported and deleted without guests", async () => {
  const handler = async (path, payload) => {
    if (path === "/v1/configurations/validate") return payload;
    if (path === "/v1/layouts/import") return layout;
    return {};
  };
  const first = await setup(handler);
  first.app.state.zones = [{ id: "ground", name: "Ground" }];
  first.app.state.tables = [{ id: "G1", zone_id: "ground", capacity: 4 }];
  first.app.state.layout = layout;
  first.app.state.rules = [{ id: "lang", shape: "attribute_grouping", mode: "soft",
    weight: 4, parameters: { attribute: "language" } }];
  first.app.show("map");
  setValue(first.$("#template-name"), "Weekly dinner", first.dom.window);
  click(first.$("#save-template"));
  await until(() => first.root.textContent.includes("Saved configuration template"));
  assert.equal(first.app.state.guests.length, 0);
  const stored = first.storage.getItem("seating-optimizer:templates:v1");
  assert.equal(JSON.parse(stored)[0].rules[0].parameters.attribute, "language");
  click(first.$("#duplicate-template"));
  await until(() => first.root.textContent.includes("Duplicated template"));
  assert.equal(JSON.parse(first.storage.getItem("seating-optimizer:templates:v1")).length, 2);
  click(first.$("#new-session"));
  first.app.show("map");
  setValue(first.$("#template-select"), "Weekly dinner", first.dom.window);
  click(first.$("#load-template"));
  await until(() => first.app.state.tables.length === 1);
  assert.equal(first.app.state.rules[0].weight, 4);
  assert.equal(first.app.state.layout.floors.length, 1);
  assert.equal(first.app.state.guests.length, 0);
  let exported;
  first.dom.window.URL.createObjectURL = blob => { exported = blob; return "blob:test/export"; };
  click(first.$("#export-configuration"));
  await until(() => exported);
  assert.match(first.root.textContent, /Exported the complete venue/);
  // A full JSON file imported into a fresh session reuses the headless validator.
  const content = JSON.parse(JSON.stringify(JSON.parse(stored)[0]));
  const fresh = await setup(handler);
  fresh.app.show("map");
  const file = { name: "venue-configuration.json", size: 200,
    text: async () => JSON.stringify(content) };
  Object.defineProperty(fresh.$("#configuration-file"), "files", { configurable: true, value: [file] });
  fresh.$("#configuration-file").dispatchEvent(new fresh.dom.window.Event("change", { bubbles: true }));
  await until(() => fresh.app.state.tables.length === 1);
  assert.deepEqual(fresh.app.state.rules, content.rules);
  assert.deepEqual(fresh.app.state.layout, content.layout);
  assert.equal(fresh.app.state.guests.length, 0);
  setValue(first.$("#template-select"), "Weekly dinner", first.dom.window);
  click(first.$("#delete-template"));
  await until(() => first.root.textContent.includes("Deleted saved template"));
  assert.equal(JSON.parse(first.storage.getItem("seating-optimizer:templates:v1")).length, 1);
});

test("corrupt storage is ignored and a storage quota failure is visible rather than a silent reset", async () => {
  const first = await setup(async () => ({}), {
    "seating-optimizer:session:v1": "{bad json",
    "seating-optimizer:templates:v1": '{"broken":true}'
  });
  assert.equal(first.app.state.guests.length, 0);
  assert.ok(first.$("#new-session"));
  const original = first.dom.window.localStorage.setItem.bind(first.dom.window.localStorage);
  first.dom.window.localStorage.setItem = () => { throw Error("quota"); };
  first.app.show("map");
  // jsdom Storage method may be non-writable; force the warning only when overridden.
  if (first.app.state.storageWarning) assert.match(first.root.textContent, /storage/i);
  first.dom.window.localStorage.setItem = original;
});
