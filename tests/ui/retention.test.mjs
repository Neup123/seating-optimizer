import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { createApp } from "../../src/seating_optimizer/api/web/app.js";

const keys = [
  "seating-optimizer:session:v1", "seating-optimizer:session:v2",
  "seating-optimizer:templates:v1", "seating-optimizer:templates:v2"
];
async function start(preloaded = {}) {
  const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>",
    { url: "http://localhost/" });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.URL = dom.window.URL;
  globalThis.Blob = dom.window.Blob;
  for (const [key, value] of Object.entries(preloaded))
    dom.window.localStorage.setItem(key, value);
  const root = dom.window.document.getElementById("root");
  const api = { get: async path => path === "/v2/plan/status-capabilities" ? {
    optimal:{complete:true,printable:true,reviewable:false,retryable:false},
    feasible:{complete:true,printable:true,reviewable:false,retryable:false},
    infeasible:{complete:false,printable:false,reviewable:false,retryable:true},
    unknown:{complete:false,printable:false,reviewable:false,retryable:true},
    needs_review:{complete:false,printable:false,reviewable:true,retryable:true},
  } : [], post: async () => ({}) };
  const app = createApp(root, api);
  await app.ready;
  return { app, dom, root, store: dom.window.localStorage };
}
function savedWithGuest(saved_at) {
  return JSON.stringify({ version: 2, saved_at, data: {
    guests: [{ id: "x", name: "Test Guest", group_id: "registration:1", attributes: {} }],
    rules: [], tables: [], zones: [], layout: { floors: [] },
    importFile: { filename: "guests.csv", content_base64: "c2Vuc2l0aXZl" }
  }});
}

test("expired guest session is not restored after the seven-day retention limit", async () => {
  const earlier = Date.now() - 8 * 24 * 60 * 60 * 1000;
  const { app, store } = await start({ "seating-optimizer:session:v2": savedWithGuest(earlier) });
  assert.equal(app.state.guests.length, 0);
  assert.ok(!store.getItem("seating-optimizer:session:v2")?.includes("Test Guest"));
});

test("saved source bytes are discarded when restoring a previously cached session", async () => {
  const { app, store } = await start({
    "seating-optimizer:session:v2": savedWithGuest(Date.now())
  });
  assert.equal(app.state.guests[0].name, "Test Guest");
  assert.equal(app.state.importFile.filename, "guests.csv");
  assert.equal(app.state.importFile.content_base64, undefined);
  assert.ok(!store.getItem("seating-optimizer:session:v2")?.includes("c2Vuc2l0aXZl"));
});

test("explicit two-step deletion purges all guest-bearing application keys", async () => {
  const { app, store, root } = await start({
    "seating-optimizer:session:v1": savedWithGuest(Date.now()),
    "seating-optimizer:session:v2": savedWithGuest(Date.now()),
    "seating-optimizer:templates:v1": JSON.stringify([{ name: "Guest Name" }]),
    "seating-optimizer:templates:v2": JSON.stringify([{ name: "Family template" }]),
  });
  const button = root.querySelector("#clear-guest-data");
  assert.ok(button);
  button.click();
  assert.match(root.textContent, /Permanently erase/);
  for (const key of keys) assert.ok(store.getItem(key), "not erased before confirmation: " + key);
  root.querySelector("#confirm-clear-guest-data").click();
  for (const key of keys) assert.equal(store.getItem(key), null, "residual key " + key);
  assert.equal(app.state.guests.length, 0);
  assert.match(root.textContent, /cleared from this browser/);
});
