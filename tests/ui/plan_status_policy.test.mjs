import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { createApp } from "../../src/seating_optimizer/api/web/app.js";

const statuses = {
  optimal: {complete:true,printable:true,reviewable:false,retryable:false},
  feasible: {complete:true,printable:true,reviewable:false,retryable:false},
  needs_review: {complete:false,printable:false,reviewable:true,retryable:true},
  infeasible: {complete:false,printable:false,reviewable:false,retryable:true},
  unknown: {complete:false,printable:false,reviewable:false,retryable:true},
};
const plan = {
  session_id:"test",status:"feasible",total_score:0,solve_seconds:0,
  assignments:[],tables:[],score_breakdown:[],compromises:[],
  conflicting_constraints:[],not_seated:[],pending_groups:[],
  manual_instructions:[],message:"",
};

async function setup(policy) {
  const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>",
    {url:"http://localhost/"});
  globalThis.window = dom.window;
  globalThis.document = dom.window.document;
  globalThis.URL = dom.window.URL;
  globalThis.Blob = dom.window.Blob;
  const calls = [];
  const api = {
    get: async path => {
      calls.push(path);
      return path === "/v2/rules/catalog" ? [] : policy;
    },
    post: async () => ({}),
  };
  const root = dom.window.document.getElementById("root");
  const app = createApp(root, api);
  await app.ready;
  return {dom,root,app,calls};
}

test("plan UI fetches canonical backend capabilities and uses them for print eligibility", async () => {
  const {dom,root,app,calls} = await setup(statuses);
  assert.equal(calls.filter(path => path === "/v2/plan/status-capabilities").length, 1);
  app.state.plan = structuredClone(plan);
  app.show("plan");
  assert.ok(root.querySelector("#download-json"), "complete plan exposes server-permitted export");
  app.newSession();
  assert.equal(app.state.statusCapabilities.feasible.complete, true,
    "new session preserves non-persistent server status contract");
  app.state.plan = structuredClone(plan);
  app.show("plan");
  assert.ok(root.querySelector("#download-json"));
  dom.window.close();
});

test("client obeys server policy, not a duplicated feasible/optimal status allowlist", async () => {
  const policy = structuredClone(statuses);
  policy.feasible = {...policy.feasible,complete:false,printable:false};
  const {dom,root,app} = await setup(policy);
  app.state.plan = structuredClone(plan);
  app.show("plan");
  assert.equal(root.querySelector("#download-json"), null,
    "no export when the server does not mark the status complete");
  assert.match(root.textContent,/Solution.*FEASIBLE/);
  dom.window.close();
});

test("client fails closed on malformed or missing server plan policy", async () => {
  const {dom,root,app} = await setup({});
  assert.equal(app.state.statusCapabilities, null);
  assert.equal(app.state.error, true);
  app.state.plan = structuredClone(plan);
  app.show("plan");
  assert.match(root.textContent,/Plan status policy unavailable/);
  assert.equal(root.querySelector("#download-json"), null);
  dom.window.close();
});
