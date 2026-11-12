import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { createApp, createGateway, friendlyApiError } from "../../src/seating_optimizer/api/web/app.js";

const catalog = [
  {engine:"intra",mechanism:"split_term",modes:["soft"]},
  {engine:"intra",mechanism:"own_attribute_grouping",modes:["soft","hard"]},
  {engine:"inter",mechanism:"pair_relation",modes:["hard","soft"]},
  {engine:"inter",mechanism:"criterion_pairs",modes:["hard","soft"]},
  {engine:"inter",mechanism:"table_pattern",modes:["soft"]},
  {engine:"inter",mechanism:"companionship",modes:["soft"]},
  {engine:"venue",mechanism:"placement_by_criterion",modes:["hard","soft"]},
  {engine:"venue",mechanism:"tiered_placement",modes:["staged"]},
  {engine:"venue",mechanism:"property_need",modes:["hard","soft"]},
  {engine:"venue",mechanism:"holes_term",modes:["soft"]},
  {engine:"venue",mechanism:"property_fit",modes:["soft"]},
  {engine:"venue",mechanism:"locked_assignment",modes:["hard"]},
  {engine:"stage",mechanism:"priority_mark",modes:["mark"]}
];
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
    get: async path => { calls.push([path,"GET"]); return path === "/v2/rules/catalog" ? catalog : handler(path); },
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


test("Group name is available as an import mapping target and sent to the API", async () => {
  const preview = {
    headers: ["Guest Name", "Party Size", "Group ID", "Household Title"],
    mapping: { "Guest Name": "name", "Party Size": "size", "Group ID": "group_id" },
    detected_mapping: { "Guest Name": "name", "Party Size": "size", "Group ID": "group_id" },
    sample_rows: [{ "Guest Name": "Alice Green", "Party Size": "1",
      "Group ID": "greens", "Household Title": "The Greens" }],
    rows_seen: 2, targets: ["name", "size", "group_id", "group_name"], issues: []
  };
  const { dom, $, calls, app } = await setup(async (path, payload) => {
    if (path === "/v1/import/preview") return preview;
    if (path === "/v1/import") return {
      guests: [{ id: "a", name: "Alice Green", group_id: "greens", group_name: "The Greens",
        attributes: {} }], mapping: payload.mapping, rows_seen: 2, rows_imported: 2, issues: []
    };
    return {};
  });
  upload($("#guest-file"), "greens.csv",
    new TextEncoder().encode("Guest Name,Party Size,Group ID,Household Title\nAlice Green,1,greens,The Greens\n"),
    dom.window);
  await until(() => !!$("#map-household-title"));
  const picker = $("#map-household-title");
  assert.ok(Array.from(picker.options).some(o =>
    o.value === "group_name" && o.textContent === "Group name"));
  setValue(picker, "group_name", dom.window);
  click($("#import-guests"));
  await until(() => app.state.guests.length === 1);
  const importCall = calls.filter(([path]) => path === "/v1/import").at(-1)[1];
  assert.equal(importCall.mapping["Household Title"], "group_name");
  assert.equal(app.state.guests[0].group_name, "The Greens");
});


// Phase 3 replaces the retired v1 shape tests with v2 engine/mechanism assertions.
// Headless API contract tests still cover the legacy migration endpoints.
function seed(app) {
  app.state.guests = [
    {id:"g1",name:"Alice",group_id:"family-one",group_name:"Family One",attributes:{language:"English",age:74,mobility:"wheelchair"}},
    {id:"g2",name:"Bob",group_id:"family-one",group_name:"Family One",attributes:{language:"English",age:12,mobility:"mobile"}},
    {id:"g3",name:"Carol",group_id:"family-two",group_name:"Family Two",attributes:{language:"Greek",age:38,mobility:"mobile"}}
  ];
  app.state.zones = [{id:"ground",name:"Ground floor"},{id:"upper",name:"Upper floor"}];
  app.state.tables = [
    {id:"G1",zone_id:"ground",capacity:4,properties:["accessible","quiet_corner"]},
    {id:"U1",zone_id:"upper",capacity:4,properties:["near_window"]}
  ];
  app.state.layout = layout;
}
function chooseMechanism(app,$,dom,engine,mechanism) {
  app.show("rules");
  setValue($("#new-rule-engine"),engine,dom.window);
  setValue($("#new-rule-mechanism"),mechanism,dom.window);
  click($("#add-rule"));
}
test("new rule builder exposes real four-engine mechanism registry without a legacy shape selector",async()=>{
  const {app,dom,$,$$}=await setup();
  seed(app);app.show("rules");
  assert.equal($("#new-rule-shape"),null);
  assert.equal($("#rule-id-0"),null);
  const engines=[...$("#new-rule-engine").options].map(o=>o.value);
  assert.deepEqual(engines,["intra","inter","venue","stage"]);
  chooseMechanism(app,$,dom,"intra","split_term");
  assert.equal(app.state.rules.length,1);
  assert.deepEqual([app.state.rules[0].engine,app.state.rules[0].mechanism,app.state.rules[0].weight],
    ["intra","split_term",5]);
  assert.match($(".rule-accordion-head").textContent,/Keep a family together/);
  assert.equal($$(".rule-accordion").length,1);
  assert.equal($$(".rule-accordion-body").length,1);
});
test("all thirteen generic mechanisms are instances rather than retired closed shapes",async()=>{
  const {app,dom,$,$$}=await setup();seed(app);
  for(const spec of catalog)chooseMechanism(app,$,dom,spec.engine,spec.mechanism);
  assert.equal(app.state.rules.length,catalog.length);
  assert.equal($$(".rule-accordion").length,catalog.length);
  assert.equal($$(".rule-accordion-body").length,1);
  assert.equal(app.state.rules.some(rule=>rule.shape==="capacity"),false);
  assert.equal(app.state.rules.some(rule=>Object.hasOwn(rule,"shape")),false);
  assert.ok(app.state.rules.every(rule=>rule.id.startsWith("rule-")));
  const generated=new Set(app.state.rules.map(rule=>rule.id));
  assert.equal(generated.size,catalog.length);
});
test("soft weights use the 1/5/25 ladder and advanced authored number; no weight on hard rules",async()=>{
  const {app,dom,$}=await setup();seed(app);
  chooseMechanism(app,$,dom,"inter","criterion_pairs");
  const weight=$("#rule-weight-0");
  assert.deepEqual([...weight.options].slice(0,3).map(o=>o.value),["1","5","25"]);
  setValue(weight,"25",dom.window);
  assert.equal(app.state.rules[0].weight,25);
  const advanced=$(".advanced-value");advanced.open=true;
  const points=advanced.querySelector('input[type="number"]');
  setValue(points,"42",dom.window);
  assert.equal(app.state.rules[0].weight,42);
  setValue($("#rule-mode-0"),"hard",dom.window);
  assert.equal(app.state.rules[0].weight,null);
  assert.equal(app.state.rules[0].mode,"hard");
});
test("criterion field and value controls come from imported guest attributes and family aggregates",async()=>{
  const {app,dom,$}=await setup();seed(app);
  chooseMechanism(app,$,dom,"venue","placement_by_criterion");
  const fields=[...$("#criterion-field").options].map(o=>o.value);
  for(const field of ["language","mobility","age","party_size","min(age)","max(age)","any(age)","youngest_age(family)"])
    assert.ok(fields.includes(field),"missing "+field);
  setValue($("#criterion-field"),"language",dom.window);
  assert.deepEqual([...$("#criterion-value").options].map(o=>JSON.parse(o.value)),["English","Greek"]);
  setValue($("#criterion-value"),JSON.stringify("Greek"),dom.window);
  assert.deepEqual(app.state.rules[0].criterion,{subject:"guest",field:"language",op:"==",value:"Greek"});
  setValue($("#criterion-field"),"youngest_age(family)",dom.window);
  setValue($("#criterion-op"),"<",dom.window);
  assert.equal(app.state.rules[0].criterion.subject,"family");
  assert.equal(app.state.rules[0].criterion.op,"<");
});
test("rule card name is the only label; delete and toggles are compact icon actions",async()=>{
  const {app,dom,$,root}=await setup();seed(app);
  chooseMechanism(app,$,dom,"venue","holes_term");
  const name=$(".rule-accordion-body input[type='text']");
  setValue(name,"Avoid gaps",dom.window);
  assert.match(root.textContent,/Avoid gaps/);
  assert.equal($(".rule-accordion-head").textContent.includes("rule-1"),false);
  assert.equal($("#delete-rule-0").getAttribute("aria-label"),"Remove Avoid gaps");
  const checkbox=$("#rule-enabled-0");
  checkbox.checked=false;checkbox.dispatchEvent(new dom.window.Event("change",{bubbles:true}));
  assert.equal(app.state.rules[0].enabled,false);
  click($("#delete-rule-0"));
  assert.equal(app.state.rules.length,0);
});
test("priority mark is mode mark and tiered preferences use same accordion workflow",async()=>{
  const {app,dom,$,$$}=await setup();seed(app);
  chooseMechanism(app,$,dom,"stage","priority_mark");
  assert.equal(app.state.rules[0].mode,"mark");
  assert.equal(app.state.rules[0].weight,null);
  assert.equal(app.state.rules[0].grade,1);
  setValue($("#new-rule-engine"),"venue",dom.window);
  setValue($("#new-rule-mechanism"),"tiered_placement",dom.window);
  click($("#add-rule"));
  assert.equal(app.state.rules[1].mode,"staged");
  assert.equal($$(".tier-row").length,1);
  click($('[aria-label="Add placement tier"]'));
  assert.equal(app.state.rules[1].tiers.length,2);
  click($('[aria-label="Move tier up"]'));
  assert.equal(app.state.rules[1].tiers.length,2);
});
test("table pattern count clauses are data, and count() accepts a nested criterion",async()=>{
  const {app,dom,$}=await setup();seed(app);
  chooseMechanism(app,$,dom,"inter","table_pattern");
  assert.equal(app.state.rules[0].conditions[0].fact,"empty_seats");
  click($('[aria-label="Add table condition"]'));
  assert.equal(app.state.rules[0].conditions.length,2);
  const fact=$(".rule-fields .control-row select");
  setValue(fact,"count",dom.window);
  assert.equal(app.state.rules[0].conditions[0].fact,"count");
  assert.equal(app.state.rules[0].conditions[0].criterion.subject,"guest");
  assert.ok($("#criterion-field"));
});
test("table property vocabulary is shared between rules and the venue editor",async()=>{
  const {app,dom,$}=await setup();seed(app);
  chooseMechanism(app,$,dom,"venue","property_need");
  const properties=[...$("#rule-property").options].map(o=>o.value);
  assert.deepEqual(properties,["accessible","near_window","quiet_corner"]);
  setValue($("#rule-property"),"quiet_corner",dom.window);
  assert.equal(app.state.rules[0].property,"quiet_corner");
  app.show("map");
  assert.ok($(".property-picker"));
  assert.ok([...$(".property-picker").querySelectorAll("span")].some(x=>x.textContent==="quiet_corner"));
});
test("automatically generated floor ID is never a user editable field",async()=>{
  const {app,$}=await setup();app.show("map");
  const form=$("#floor-form");
  assert.ok(form);
  assert.equal(form.querySelector('[name="id"]'),null);
  form.querySelector('[name="name"]').value="Balcony";
  click($("#add-floor"));
  assert.equal(app.state.zones.length,1);
  assert.equal(app.state.zones[0].id,"floor-1");
  assert.equal(app.state.zones[0].name,"Balcony");
});
test("map keyboard arrow move is equivalent to drag and persists local geometry",async()=>{
  const {app,dom,$}=await setup();seed(app);app.show("map");
  const before=app.state.layout.floors[0].tables[0].x;
  const target=$('#map-editor-svg [data-table-id="G1"]');
  assert.equal(target.getAttribute("tabindex"),"0");
  target.dispatchEvent(new dom.window.KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true}));
  assert.equal(app.state.layout.floors[0].tables[0].x,before+5);
});
test("v2 solves include data-model rule instances, show skeleton and fetch view from server",async()=>{
  let finish;
  const {app,$,calls,root}=await setup(async path=>{
    if(path==="/v2/solve")return new Promise(resolve=>{finish=resolve});
    return {};
  });
  seed(app);
  app.show("plan");click($("#solve-plan"));
  assert.ok($(".solve-progress"),"Progress skeleton appears while solver runs");
  assert.equal(app.state.solving,true);
  assert.equal(calls.find(([p])=>p==="/v2/solve")?.[0],"/v2/solve");
  finish(plan);
  await until(()=>!!$(".plan-entry"));
  assert.equal(app.state.solving,false);
  assert.match(root.textContent,/Solution · FEASIBLE/);
  assert.equal($("#view-json"),null);
  assert.ok($("#download-json"));
});
test("v2 plan infeasible state names operator rule and offers edit link",async()=>{
  const {app,$}=await setup();seed(app);
  app.state.rules=[{id:"rule-1",name:"Seniors only downstairs",engine:"venue",
    mechanism:"placement_by_criterion",mode:"hard",weight:null,polarity:null,enabled:true,
    criterion:{subject:"guest",field:"age",op:">=",value:65},zones:["ground"]}];
  app.state.plan={...plan,status:"infeasible",message:"No valid layout",conflicting_constraints:["rule:rule-1 violated"]};
  app.show("plan");
  assert.match($(".conflict-row").textContent,/Seniors only downstairs/);
  assert.doesNotMatch($(".conflict-row").textContent,/rule-1/);
  click($(".conflict-row button"));
  assert.equal(app.state.screen,"rules");
  assert.ok($(".rule-accordion-body"));
});
test("selection is a checkbox state, clear has a back action, and summary counts people and tables",async()=>{
  const {app,$,root}=await setup();seed(app);app.state.plan=plan;app.show("plan");
  const box=$('.plan-check input[type="checkbox"]');
  assert.ok(box);
  box.click();
  assert.ok($("#plan-selection"));
  assert.match($("#plan-selection").textContent,/2 people · 1 table affected/);
  assert.equal($("#clear-plan-selection").title,"Clear selection");
  click($("#clear-plan-selection"));
  assert.equal($("#plan-selection"),null);
  assert.ok(root.querySelector('.plan-check input[type="checkbox"]'));
});
test("print format switches use server HTML/PDF and plan JSON has a separate export button",async()=>{
  const {app,$,calls}=await setup(async (path,payload,type)=>{
    if(path.includes("/html"))return '<html><body><table><tr><td>Family One</td></tr></table></body></html>';
    if(path.includes("floor-map/pdf"))return new Blob(["%PDF"],{type:"application/pdf"});
    if(path==="/v2/exports/json")return plan;
    return {};
  });
  seed(app);app.state.plan=plan;app.show("plan");click($("#view-print"));
  await until(()=>!!$("#list-preview"));
  assert.ok(calls.some(([p])=>p.includes("/v2/exports/table-list/html")));
  assert.equal($("#view-json"),null);
  assert.ok($("#download-json"));
});
test("no unseating occurs on shortage until the operator explicitly chooses",async()=>{
  const {app,$}=await setup();seed(app);
  app.state.plan={...plan,status:"infeasible",message:"Too many people — short by 1",
    unseated_reasons:[{group_id:"family-two",group_name:"Family Two",guest_ids:["g3"],
      reason:"lack_of_space",status:"pending",description:"Short by one chair"}]};
  app.show("plan");
  assert.equal(app.state.manualInstructions.length,0);
  assert.ok($("#overflow-choice"));
  assert.ok($("#confirm-unseat"));
  assert.match($("#nav-plan").textContent,/Seating plan/);
});
test("generic headless move preview receives v2 rule data and only apply commits the option",async()=>{
  let observedInstruction;
  const {app,$,calls}=await setup(async (path,payload)=>{
    if(path==="/v2/reassign/options") {
      observedInstruction=payload.instruction;
      const changed={...plan,manual_instructions:[payload.instruction]};
      return {status:"available",options:[{id:"v2-option-1",title:"Move to another table",
        kind:"solver-checked",score_delta:-1,movements:[
          {group_id:"family-one",party_name:"Family One",before:["G1"],after:["U1"],people:2}],
        soft_rule_warnings:[],plan:changed}],blockers:[]};
    }
    return {};
  });
  seed(app);app.state.plan=plan;app.show("plan");
  const party=$('.plan-check input[type="checkbox"]');party.click();
  click($("#intent-move-to"));
  await until(()=>!!$("#find-reassign-options"));
  click($("#find-reassign-options"));
  await until(()=>!!$("#apply-v2-option-1"));
  assert.equal(calls.filter(([p])=>p==="/v2/reassign/options").length,1);
  assert.equal(app.state.manualInstructions.length,0);
  click($("#apply-v2-option-1"));
  assert.equal(app.state.manualInstructions[0].id,observedInstruction.id);
});
test("v2 session saves and reloads with instances, while preserving named template storage",async()=>{
  const {app,dom,$,storage}=await setup();seed(app);
  chooseMechanism(app,$,dom,"venue","holes_term");
  const stored=storage.getItem("seating-optimizer:session:v2");
  assert.ok(stored);
  assert.equal(JSON.parse(stored).version,2);
  assert.equal(JSON.parse(stored).data.rules[0].mechanism,"holes_term");
  const fresh=await setup(async()=>({}),{"seating-optimizer:session:v2":stored});
  assert.equal(fresh.app.state.rules.length,1);
  assert.equal(fresh.app.state.rules[0].name,"Avoid empty seats");
});
test("errors remain actionable and retry is kept on failed generic solve",async()=>{
  const {app,$}=await setup(async path=>{
    if(path==="/v2/solve")throw Error("Server returned 503");
    return {};
  });
  seed(app);app.show("plan");click($("#solve-plan"));
  await until(()=>!!$("#retry-action"));
  assert.match($("#notice").textContent,/503/);
  assert.equal(app.state.guests.length,3);
});


test("F1/U14: 43 guests, seven tables and six migrated rules show the +6 named plan-wide score", async () => {
  const {app,root,$}=await setup();
  const hebrew = {id:"hebrew-upper-preference",name:"",engine:"venue",
    mechanism:"placement_by_criterion",mode:"soft",weight:2,polarity:"reward",
    criterion:{subject:"guest",field:"language",op:"==",value:"Hebrew"},zones:["upper"]};
  app.state.rules=[hebrew,
    ...["split_term","holes_term","property_need","priority_mark","companionship"]
      .map((mechanism,index)=>({id:"migrated-"+index,name:"",engine:"venue",mechanism,
        mode:"soft",weight:1,enabled:true}))];
  const guests=Array.from({length:43},(_,i)=>({id:"p"+i,name:i<3?"India Family ("+(i+1)+"/3)":"Guest "+i,
    group_id:i<3?"india":"visitor-"+i,group_name:i<3?"India Family":"Visitor "+i,
    attributes:{language:i<3?"Hebrew":"English"}}));
  app.state.guests=guests;
  const tables=["B1","A1","A2","A3","A4","A5","A6"].map((id,i)=>({
    table_id:id,zone_id:i===0?"upper":"ground",capacity:10,occupied:i===0?3:7,
    empty_seats:i===0?7:3
  }));
  app.state.plan={...plan,total_score:6,
    score_breakdown:[{rule_id:"hebrew-upper-preference",points:6}],
    tables,assignments:[{group_id:"india",group_name:"India Family",table_id:"B1",
      guest_ids:["p0","p1","p2"],guest_names:["India Family (1/3)","India Family (2/3)","India Family (3/3)"],
      points:0,reasons:[{rule_id:"capacity",description:"Within chair capacity",points:0}]}]};
  app.show("plan");
  assert.equal(app.state.guests.length,43);
  assert.equal(app.state.tables.length,0); // Seven tables are API plan facts, not fabricated venue state.
  assert.equal(app.state.plan.tables.length,7);
  assert.equal(app.state.rules.length,6);
  assert.match($(".score-breakdown").textContent,/Place matching guests on floors: language is Hebrew: \+6 points/);
  assert.doesNotMatch($(".score-breakdown").textContent,/hebrew-upper-preference|Unnamed consideration/);
  assert.match(root.textContent,/No assignment-specific score — see plan breakdown/);
  click($('.plan-entry [title="Details"]'));
  assert.match($(".plan-details").textContent,/Plan-wide scoring \(not attributed to this family\)/);
  assert.match($(".plan-details").textContent,/language is Hebrew: \+6 points/);
  assert.doesNotMatch($(".plan-details").textContent,/No matching rule records/);
});

test("U4/U19/F3/U38: icon inputs and venue actions have tooltips and focused mobile panes", async () => {
  const {app,$,root}=await setup();
  app.show("import");
  assert.ok($("#guest-file").classList.contains("visually-hidden-file"));
  assert.equal($("#guest-file-trigger").title,"Choose guest list spreadsheet (CSV or XLSX)");
  assert.equal($("#guest-file-trigger").getAttribute("aria-label"),$("#guest-file-trigger").title);
  seed(app);
  app.show("map");
  for (const id of ["configuration-file","layout-file"]) {
    assert.ok($("#"+id).classList.contains("visually-hidden-file"));
    assert.ok($("#"+id+"-trigger").title.length>10);
  }
  for (const id of ["save-template","export-configuration","load-template","duplicate-template",
    "delete-template","validate-layout","export-layout","add-floor","add-table"]) {
    const action=$("#"+id);
    assert.ok(action,id+" must exist");
    assert.ok(action.classList.contains("icon-button"),id+" must be an icon action");
    assert.ok(action.title.length>4,id+" requires complete tooltip");
    assert.equal(action.getAttribute("aria-label"),action.title);
  }
  assert.equal($("#add-table").textContent.trim(),"＋");
  assert.equal($("#new-table-small-priority").parentElement.className,"priority-checkbox");
  assert.equal($("#table-G1-small-priority").parentElement.className,"priority-checkbox");
  assert.equal($(".map-layout").dataset.mobilePane,"map");
  click($("#venue-mobile-tables"));
  assert.equal($(".map-layout").dataset.mobilePane,"tables");
  assert.equal($("#venue-mobile-tables").getAttribute("aria-pressed"),"true");
  click($("#venue-mobile-map"));
  assert.equal($(".map-layout").dataset.mobilePane,"map");
  assert.ok(root.querySelector("#map-editor-svg"));
});

test("F2: network failure retains the last successful plan after edited inputs invalidate it", async () => {
  const {app,dom,$,root}=await setup(async path=>{
    if(path==="/v2/solve")throw Error("Server returned 503");
    return {};
  });
  seed(app);
  app.state.plan=structuredClone(plan);
  app.show("plan");
  // Changing an input marks the old plan stale, but it can still be displayed on failure.
  setValue($("#time-limit"),"4",dom.window);
  assert.equal(app.state.plan,null);
  click($("#solve-plan"));
  await until(()=>!!$("#retry-action"));
  assert.equal(app.state.plan.total_score,8);
  assert.match(root.textContent,/Solution · FEASIBLE/);
  assert.match(root.textContent,/Showing the last successful plan/);
  assert.match($("#notice").textContent,/503/);
  assert.ok($(".plan-entry"));
});
