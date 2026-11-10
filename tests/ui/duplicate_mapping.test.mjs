import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { createApp } from "../../src/seating_optimizer/api/web/app.js";

async function until(predicate) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  throw Error("Expected guest-import UI state did not appear");
}

test("duplicate target mapping warns before import, blocks it, and allows corrected mapping (#48)", async () => {
  const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>",
    { url: "http://localhost/" });
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.btoa = value => Buffer.from(value, "binary").toString("base64");
  const root = dom.window.document.querySelector("#root");
  const $ = selector => root.querySelector(selector);
  const preview = {
    headers: ["Name", "Size", "Language", "Secondary Language"],
    mapping: { Name: "name", Size: "size", Language: "attribute.language" },
    detected_mapping: { Name: "name", Size: "size", Language: "attribute.language" },
    sample_rows: [{ Name: "Alice", Size: "1", Language: "English", "Secondary Language": "French" }],
    rows_seen: 1, targets: ["name", "size", "attribute.language"], issues: [],
  };
  const calls = [];
  const api = {
    get: async () => ({ shapes: [] }),
    post: async (path, payload) => {
      calls.push({ path, payload });
      if (path === "/v1/import/preview") return preview;
      if (path === "/v1/import") return {
        guests: [{ id: "r2-m1", name: "Alice", group_id: "registration:2", attributes: { language: "English" } }],
        mapping: payload.mapping, rows_seen: 1, rows_imported: 1, issues: [],
      };
      throw Error("Unexpected endpoint " + path);
    },
  };
  const app = createApp(root, api);
  await app.ready;
  const source = new TextEncoder().encode(
    "Name,Size,Language,Secondary Language\nAlice,1,English,French\n");
  Object.defineProperty($("#guest-file"), "files", {
    configurable: true, value: [{
      name: "guests.csv", size: source.length,
      arrayBuffer: async () => source.buffer.slice(source.byteOffset, source.byteOffset + source.byteLength),
    }],
  });
  $("#guest-file").dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  await until(() => !!$("#map-secondary-language"));

  const change = (node, value) => {
    assert.ok(node);
    node.value = value;
    node.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  };
  change($("#map-secondary-language"), "attribute.language");
  assert.match(root.textContent, /Multiple columns mapped to attribute\.language/);
  assert.equal($("#import-guests").disabled, true);
  $("#import-guests").click();
  assert.equal(calls.filter(call => call.path === "/v1/import").length, 0);

  change($("#map-secondary-language"), "");
  assert.equal($("#import-guests").disabled, false);
  $("#import-guests").click();
  await until(() => app.state.guests.length === 1);
  assert.equal(app.state.guests[0].name, "Alice");
  assert.equal(calls.filter(call => call.path === "/v1/import").length, 1);
});
