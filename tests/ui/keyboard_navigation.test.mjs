import test from "node:test";
import assert from "node:assert/strict";
import {JSDOM} from "jsdom";
import {renderGenericRules} from "../../src/seating_optimizer/api/web/v2-rules.js";
import {renderPlanWorkspace} from "../../src/seating_optimizer/api/web/plan-workspace.js";

function documentFixture() {
  const dom=new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>",
    {url:"http://localhost/"});
  globalThis.document=dom.window.document;
  globalThis.window=dom.window;
  return {dom,root:document.getElementById("root")};
}
function key(dom,target,name) {
  target.dispatchEvent(new dom.window.KeyboardEvent("keydown",
    {key:name,bubbles:true,cancelable:true}));
}
test("rule edit headers have arrow navigation, Escape collapse and confirmed Delete",()=>{
  const {dom,root}=documentFixture();
  const make=(id)=>({id,name:"Rule "+id,enabled:true,engine:"intra",
    mechanism:"split_term",mode:"soft",polarity:"penalty",weight:5});
  const state={rules:[make("one"),make("two")],ruleEngine:"intra",
    ruleMechanism:"split_term",catalog:[{engine:"intra",mechanism:"split_term",modes:["soft"]}],
    guests:[],zones:[],tables:[],nextRule:3,expandedRuleId:"one",ruleQuery:""};
  const refresh=()=>root.replaceChildren(renderGenericRules(state,{
    changed:refresh,announce:()=>{} }));
  refresh();
  root.querySelectorAll(".expand-rule")[0].focus();
  key(dom,document.activeElement,"ArrowDown");
  assert.equal(document.activeElement,root.querySelectorAll(".expand-rule")[1]);
  key(dom,root.querySelectorAll(".expand-rule")[0],"Escape");
  assert.equal(state.expandedRuleId,null);
  assert.equal(document.activeElement,root.querySelectorAll(".expand-rule")[0]);
  root.querySelector("#delete-rule-0").click();
  assert.equal(state.rules.length,2,"first click requests confirmation");
  assert.ok(root.querySelector("#confirm-rule-delete-0"));
  root.querySelector("#cancel-rule-delete-0").click();
  assert.equal(state.rules.length,2,"cancel preserves rule");
  root.querySelector("#delete-rule-0").click();
  root.querySelector("#confirm-rule-delete-0").click();
  assert.equal(state.rules.length,1);
  assert.equal(state.rules[0].id,"two");
});
test("assignment row arrows, Space, Enter, Escape and focus restoration",()=>{
  const {dom,root}=documentFixture();
  const plan={status:"feasible",assignments:[
    {group_id:"family-one",group_name:"Family One",table_id:"A",
     guest_ids:["g1"],guest_names:["Alice"],reasons:[]},
    {group_id:"family-two",group_name:"Family Two",table_id:"A",
     guest_ids:["g2"],guest_names:["Bob"],reasons:[]}
  ],tables:[{table_id:"A",zone_id:"hall",capacity:4,occupied:2,empty_seats:2}],score_breakdown:[]};
  const state={plan,rules:[],selectedPlanItem:null,expandedPartyKey:null,
    view:"table",workspaceQuery:"",workspaceFloor:"",workspaceSort:"table",
    manualInstructions:[]};
  const refresh=()=>root.replaceChildren(renderPlanWorkspace(state,{
    partyName:a=>a.group_name,partyMembers:a=>a.guest_names,
    refresh,proposeReassignment:()=>{},applyReassignment:()=>{},
    removeInstruction:()=>{},unseatParty:()=>{}
  }));
  refresh();
  let rows=root.querySelectorAll(".plan-entry");
  rows[0].focus();
  key(dom,rows[0],"ArrowDown");
  assert.equal(document.activeElement,rows[1]);
  key(dom,rows[1]," ");
  assert.deepEqual(state.selectedPlanItem,{kind:"party",id:"family-two"});
  rows=root.querySelectorAll(".plan-entry");
  assert.equal(document.activeElement,rows[1]);
  key(dom,rows[1],"Enter");
  assert.equal(state.expandedPartyKey,"family-two@A");
  rows=root.querySelectorAll(".plan-entry");
  assert.equal(document.activeElement,rows[1]);
  key(dom,rows[1],"Escape");
  assert.equal(state.expandedPartyKey,null);
  rows=root.querySelectorAll(".plan-entry");
  assert.equal(document.activeElement,rows[1]);
});
