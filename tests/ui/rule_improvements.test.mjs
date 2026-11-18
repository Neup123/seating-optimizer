import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { renderGenericRules } from "../../src/seating_optimizer/api/web/v2-rules.js";
import { renderPlanWorkspace } from "../../src/seating_optimizer/api/web/plan-workspace.js";

function domSetup() {
  const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>",
    {url:"http://localhost/"});
  globalThis.window=dom.window;
  globalThis.document=dom.window.document;
  return {dom,root:dom.window.document.getElementById("root")};
}
function sampleRule(id,name,criterion = {subject:"guest",field:"language",op:"==",value:"English"}) {
  return {id,name,description:"",enabled:true,engine:"intra",
    mechanism:"own_attribute_grouping",mode:"soft",weight:5,polarity:"reward",
    criterion};
}
function setupEditor(rules) {
  const {dom,root}=domSetup();
  const state={rules,ruleQuery:"",expandedRuleId:rules[0]?.id,
    guests:[{id:"g1",name:"Alice",group_id:"family-1",attributes:{language:"English"}},
      {id:"g2",name:"Bob",group_id:"family-2",attributes:{language:"French"}}],
    tables:[],zones:[],catalog:[{engine:"intra",mechanism:"own_attribute_grouping",modes:["soft","hard"]}],
    ruleEngine:"intra",ruleMechanism:"own_attribute_grouping",nextRule:10};
  const render=()=>root.replaceChildren(renderGenericRules(state,{changed:render,announce:()=>{}}));
  render();return {dom,root,state,render};
}
test("rule accordion filters while preserving original instance indexes and enabling choices",()=>{
  const {dom,root,state}=setupEditor(["Alpha","Beta","Gamma","Delta","Epsilon"].map((name,i)=>sampleRule("r"+i,name)));
  assert.equal(root.querySelectorAll(".rule-accordion").length,5);
  const input=root.querySelector("#rule-search");assert.ok(input);
  input.value="epsilon";
  input.dispatchEvent(new dom.window.Event("input",{bubbles:true}));
  assert.equal(root.querySelectorAll(".rule-accordion").length,1);
  assert.match(root.querySelector(".rule-accordion").textContent,/Epsilon/);
  assert.equal(state.rules.length,5);
  assert.equal(root.querySelector(".rule-accordion").dataset.ruleId,"r4");
});
test("known value dropdown has an advanced custom value and custom attribute field",()=>{
  const {dom,root,state}=setupEditor([sampleRule("r1","Diet group")]);
  const advanced=root.querySelector("details.advanced-value");
  assert.ok(advanced);
  const customLabel=[...root.querySelectorAll("label")].find(label=>label.textContent.includes("Custom value"));
  assert.ok(customLabel,"Custom value input is discoverable");
  const input=customLabel.querySelector("input");input.value="Italian";
  input.dispatchEvent(new dom.window.Event("change",{bubbles:true}));
  assert.equal(state.rules[0].criterion.value,"Italian");
  const field=[...root.querySelectorAll("label")].find(label=>label.textContent.includes("Attribute key"));
  assert.ok(field);
  const inputField=field.querySelector("input");inputField.value="diet";
  inputField.dispatchEvent(new dom.window.Event("change",{bubbles:true}));
  assert.equal(state.rules[0].criterion.field,"diet");
});
test("assignment rules show operator label and meaning with internal ids hidden in details",()=>{
  const {root}=domSetup();
  const state={
    plan:{status:"feasible",assignments:[{group_id:"family-1",table_id:"A",guest_ids:["g1"],
      guest_names:["Alice"],reasons:[{rule_id:"private-17",description:"Rule passed",points:3}]}],
      tables:[{table_id:"A",zone_id:"hall",capacity:4,occupied:1,empty_seats:3}],
      score_breakdown:[]},
    rules:[{...sampleRule("private-17","Place accessible families"),description:"Keep this family close to the entrance."}],
    selectedPlanItem:null,expandedPartyKey:"family-1@A",view:"table",workspaceQuery:"",
    workspaceFloor:"",workspaceSort:"table",reassignMode:null,reassignResponse:null,
    manualInstructions:[]
  };
  const view=renderPlanWorkspace(state,{partyName:()=> "Family One",partyMembers:()=>["Alice"],
    refresh:()=>{},proposeReassignment:()=>{},applyReassignment:()=>{},
    removeInstruction:()=>{},unseatParty:()=>{}});
  root.append(view);
  assert.match(root.textContent,/Place accessible families/);
  assert.match(root.textContent,/Keep this family close to the entrance/);
  assert.ok(root.querySelector("details.rule-diagnostics"));
  assert.match(root.querySelector("details.rule-diagnostics").textContent,/private-17/);
});
