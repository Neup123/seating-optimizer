/* V2 rule editor. The mechanism registry is provided by /v2/rules/catalog.
 * This module only constructs rule data; all validation and scoring belong to the API.
 */
const OPS = ["==", "!=", "<", "<=", ">", ">=", "in"];
const ENGINE_NAMES = {intra:"Within a family", inter:"Between people / families",
  venue:"Venue & placement", stage:"Priority order"};
const FIXED_POLARITY = {
  split_term:"penalty", companionship:"penalty", holes_term:"penalty",
  property_fit:"reward", placement_by_criterion:"reward", property_need:"penalty"
};
const LABELS = {
  split_term:"Keep a family together", own_attribute_grouping:"Group a family by attribute",
  pair_relation:"Place two families together / apart", criterion_pairs:"Connect matching people",
  table_pattern:"Table occupancy pattern", companionship:"Avoid solitary placement",
  placement_by_criterion:"Place matching guests on floors", tiered_placement:"Placement preference tiers",
  property_need:"Require / prefer a table property", holes_term:"Avoid empty seats",
  property_fit:"Reward a matching table property", locked_assignment:"Lock a family to a table",
  priority_mark:"Mark a family's seating priority"
};
const NEEDS_CRITERION = new Set(["own_attribute_grouping","criterion_pairs",
  "placement_by_criterion","property_need","property_fit"]);
const NUMERIC = value => value !== null && value !== "" && value !== undefined &&
  !Array.isArray(value) && !Number.isNaN(Number(value)) && typeof value !== "boolean";
const scalar = value => typeof value === "boolean" ? value :
  NUMERIC(value) ? Number(value) : value;

function node(tag, cls = "", label) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (label !== undefined) n.textContent = String(label);
  return n;
}
function labelled(name, control) {
  const holder = node("label", "compact-field");
  holder.append(node("span", "", name), control);
  return holder;
}
function pick(label, choices, current, change, id) {
  const s = node("select");
  if (id) s.id = id;
  for (const [value, title] of choices) {
    const option = node("option", "", title);
    option.value = String(value); s.append(option);
  }
  if (current !== undefined && current !== null) s.value = String(current);
  s.addEventListener("change", () => change(s.value));
  return labelled(label, s);
}
function edit(label, value, change, type = "text") {
  const field = node("input");
  field.type = type;
  field.value = String(value ?? "");
  field.addEventListener("change", () => change(field.value));
  return labelled(label, field);
}
function button(symbol, title, click, css = "icon-button", id) {
  const b = node("button", css, symbol);
  b.type = "button"; b.title = title; b.setAttribute("aria-label", title);
  if (id) b.id = id;
  b.addEventListener("click", click);
  return b;
}
function line(...items) {
  const el = node("div", "control-row");
  el.append(...items); return el;
}
function unique(values) {
  return [...new Set(values.map(value => JSON.stringify(value)))].map(value=>JSON.parse(value));
}
export function observedFields(guests) {
  const columns = new Map();
  for (const guest of guests || []) {
    const entries = [["name",guest.name], ...Object.entries(guest.attributes || {})];
    for (const [key,value] of entries) {
      if (!columns.has(key)) columns.set(key, []);
      if (value !== undefined && value !== null && value !== "")
        columns.get(key).push(value);
    }
  }
  const result = [...columns].map(([field, values]) => ({
    field, values:unique(values).sort((a,b)=>String(a).localeCompare(String(b))),
    numeric:values.length > 0 && values.every(NUMERIC)
  }));
  result.push({field:"party_size",values:unique(
    Object.values((guests || []).reduce((acc,g)=>{
      const id=g.group_id || "guest:"+g.id;
      acc[id]=(acc[id] || 0)+1; return acc;
    },{}))),numeric:true});
  for (const numeric of result.filter(item=>item.numeric && item.field!=="party_size")) {
    for (const aggregate of ["min","max","any"]) result.push({
      field:aggregate+"("+numeric.field+")",values:numeric.values.map(scalar),numeric:true,family:true
    });
    if (numeric.field==="age") {
      result.push({field:"youngest_age(family)",values:numeric.values.map(scalar),numeric:true,family:true});
      result.push({field:"oldest_age(family)",values:numeric.values.map(scalar),numeric:true,family:true});
    }
  }
  return result;
}
export function tablePropertyVocabulary(tables) {
  return [...new Set((tables || []).flatMap(t=>t.properties || []).filter(Boolean))].sort();
}
function parties(guests) {
  const found = new Map();
  for (const guest of guests || []) {
    const id = guest.group_id || "guest:"+guest.id;
    if (!found.has(id)) {
      const family = guest.group_name || (guest.name || "").replace(/ \(\d+\/\d+\)$/,"") || "Unnamed family";
      found.set(id,family);
    }
  }
  return [...found].map(([id,name])=>[id,name]);
}
function makeCriterion(fields, scope = false) {
  const f = fields.find(field=>!field.family && field.field!=="name") || fields[0];
  return {subject:"guest",field:f?.field || "name",op:"==",
    value:f?.values[0] ?? null,...(scope?{scope:"across"}:{})};
}
export function createGenericRule(spec, state) {
  const fields=observedFields(state.guests);
  const people=parties(state.guests);
  const mechanism=spec.mechanism;
  const mode=spec.modes.includes("soft")?"soft":spec.modes[0];
  const rule={id:"rule-"+state.nextRule++,name:LABELS[mechanism] || mechanism,
    description:"",enabled:state.guests.length > 0 || !NEEDS_CRITERION.has(mechanism),engine:spec.engine,mechanism,mode,
    polarity:mode==="soft"?(FIXED_POLARITY[mechanism] || "reward"):null,
    weight:mode==="soft"?5:null};
  if (NEEDS_CRITERION.has(mechanism)) rule.criterion=makeCriterion(fields,
    mechanism==="criterion_pairs");
  if (mechanism==="own_attribute_grouping") rule.criterion.scope="within";
  if (mechanism==="pair_relation") {
    rule.targets=[people[0]?.[0] || "",people[1]?.[0] || people[0]?.[0] || ""];
    rule.relation="together";
  }
  if (mechanism==="table_pattern") rule.conditions=[
    {fact:"empty_seats",op:"==",value:1}];
  if (mechanism==="companionship") rule.exclusions=[];
  if (mechanism==="placement_by_criterion") rule.zones=state.zones[0]?[state.zones[0].id]:[];
  if (mechanism==="tiered_placement") {
    rule.target=people[0]?.[0] || "";
    rule.tiers=[{zones:state.zones[0]?[state.zones[0].id]:[],tables:[]}];
  }
  if (mechanism==="property_need" || mechanism==="property_fit")
    rule.property=tablePropertyVocabulary(state.tables)[0] || "";
  if (mechanism==="locked_assignment") {
    rule.target=people[0]?.[0] || "";rule.table=state.tables[0]?.id || "";
  }
  if (mechanism==="priority_mark") {
    rule.selector="direct"; rule.target=people[0]?.[0] || "";rule.grade=1;
  }
  return rule;
}
function summary(rule) {
  const c=rule.criterion;
  if (c) return c.field+" "+c.op+" "+(c.value===null?"any value":Array.isArray(c.value)?c.value.join(", "):String(c.value));
  if (rule.target) return "Family "+rule.target;
  if (rule.targets) return rule.targets.join(" / ")+" · "+rule.relation;
  if (rule.property) return "Property: "+rule.property;
  if (rule.conditions) return rule.conditions.length+" table conditions";
  return LABELS[rule.mechanism] || rule.mechanism.replaceAll("_"," ");
}
function valuePicker(criterion, field, changed, key) {
  const values=field?.values || [];
  const available=unique(values.map(scalar));
  if (criterion.op==="in") {
    const chosen=Array.isArray(criterion.value)?criterion.value:[];
    const holder=node("fieldset","value-set");
    holder.append(node("legend","","Values"));
    if (!available.length) holder.append(node("span","muted","Import guest data to choose values"));
    for (const value of available) {
      const label=node("label","check-inline");
      const box=node("input");box.type="checkbox";box.checked=chosen.some(v=>String(v)===String(value));
      box.addEventListener("change",()=>{
        const next=box.checked?[...chosen,value]:chosen.filter(v=>String(v)!==String(value));
        if(next.length) changed("value",next);
        else {box.checked=true;}
      });
      label.append(box,node("span","",String(value)));holder.append(label);
    }
    return holder;
  }
  const options=available.map(v=>[JSON.stringify(v),String(v)]);
  // Operators with a strict numeric domain permit an advanced threshold, with explicit marking.
  const threshold=field?.numeric && ["<","<=",">",">="].includes(criterion.op);
  const current=JSON.stringify(criterion.value);
  if (threshold && !options.some(([v])=>v===current)) options.push([current,String(criterion.value)]);
  const choices=options.length?options:[["null","No imported values"]];
  const selected=pick("Value",choices,current||choices[0][0],value=>changed("value",JSON.parse(value)),key);
  if (!threshold) return selected;
  const holder=line(selected);
  const advanced=node("details","advanced-value");
  advanced.append(node("summary","","Advanced threshold"));
  advanced.append(edit("Numeric threshold",criterion.value,value=>{
    if (NUMERIC(value)) changed("value",Number(value));
  },"number"));
  holder.append(advanced);
  return holder;
}
function criterionEditor(criterion, state, changed, options={}) {
  const all=observedFields(state.guests);
  const fields=options.guestOnly?all.filter(f=>!f.family && f.field!=="party_size"):all;
  if (!fields.some(f=>f.field===criterion.field))
    fields.push({field:criterion.field,values:[criterion.value].filter(x=>x!==null),numeric:NUMERIC(criterion.value)});
  const field=fields.find(f=>f.field===criterion.field);
  const control=node("fieldset","criteria-editor");
  control.append(node("legend","","Criterion"));
  const set=(key,value)=>{const next={...criterion,[key]:value};changed(next);};
  const row=line(pick("Field",fields.map(f=>[f.field,f.field]),criterion.field,value=>{
    const selected=fields.find(f=>f.field===value);
    const updated={subject:selected?.family||value==="party_size"?"family":"guest",
      field:value,op:"==",value:selected?.values[0]??null};
    if (options.scope && updated.subject==="guest") updated.scope=criterion.scope || "across";
    changed(updated);
  },"criterion-field"),pick("Operator",OPS.filter(op=>field?.numeric || !["<","<=",">",">="].includes(op))
      .map(op=>[op,op]),criterion.op,value=>{
        const next={...criterion,op:value};
        if(value==="in") next.value=Array.isArray(next.value)?next.value:[next.value].filter(v=>v!==null);
        else if(Array.isArray(next.value)) next.value=next.value[0] ?? null;
        if (["<","<=",">",">="].includes(value) && !NUMERIC(next.value))
          next.value=field?.values.find(NUMERIC)??0;
        changed(next);
      },"criterion-op"));
  if (options.scope && criterion.subject==="guest")
    row.append(pick("Pair scope",[["within","Within families"],["across","Across families"]],
      criterion.scope || "across",value=>set("scope",value),"criterion-scope"));
  control.append(row, valuePicker(criterion,field,(key,value)=>set(key,value),"criterion-value"));
  return control;
}
function multi(label,choices,values,change) {
  const fieldset=node("fieldset","multi-picker");fieldset.append(node("legend","",label));
  const selected=values||[];
  if (!choices.length) fieldset.append(node("span","muted","No options yet"));
  for (const [value,title] of choices) {
    const tag=node("label","check-inline");
    const check=node("input");check.type="checkbox";check.checked=selected.includes(value);
    check.addEventListener("change",()=>change(check.checked?[...selected,value]:selected.filter(x=>x!==value)));
    tag.append(check,node("span","",title));fieldset.append(tag);
  }
  return fieldset;
}
function mechanismFields(rule,state,changed) {
  const region=node("div","rule-fields");
  const commit=(field,value)=>{rule[field]=value;changed();};
  const namedParties=parties(state.guests);
  const locations=state.zones.map(z=>[z.id,z.name]);
  const tables=state.tables.map(t=>[t.id,t.id+" · "+t.zone_id]);
  const criterion=(options)=>criterionEditor(rule.criterion || makeCriterion(observedFields(state.guests)),
    state,value=>commit("criterion",value),options);
  const fromGroups=()=>pick("Family",namedParties,rule.target,
    value=>commit("target",value),"rule-target");
  switch(rule.mechanism) {
    case "own_attribute_grouping":
    case "criterion_pairs":
      region.append(criterion({guestOnly:true,scope:true}));break;
    case "placement_by_criterion":
      region.append(criterion(),multi("Allowed floors",locations,rule.zones,v=>commit("zones",v)));break;
    case "property_fit":
    case "property_need":
      region.append(criterion(),pick("Table property",tablePropertyVocabulary(state.tables)
        .map(p=>[p,p]),rule.property,v=>commit("property",v),"rule-property"));break;
    case "pair_relation":
      region.append(line(pick("First family",namedParties,rule.targets?.[0],v=>{
        commit("targets",[v,rule.targets?.[1] || v]);
      }),pick("Second family",namedParties,rule.targets?.[1],v=>{
        commit("targets",[rule.targets?.[0] || v,v]);
      }),pick("Relation",[["together","Together"],["apart","Apart"]],rule.relation,v=>commit("relation",v))));break;
    case "tiered_placement": {
      region.append(fromGroups());
      (rule.tiers||[]).forEach((tier,index)=>{
        const tierRow=node("fieldset","tier-row");tierRow.append(node("legend","","Tier "+(index+1)));
        tierRow.append(multi("Floors",locations,tier.zones,v=>{tier.zones=v;changed();}),
          multi("Tables",tables,tier.tables,v=>{tier.tables=v;changed();}));
        tierRow.append(line(
          button("↑","Move tier up",()=>{if(index){[rule.tiers[index-1],rule.tiers[index]]=
            [rule.tiers[index],rule.tiers[index-1]];changed();}}),
          button("↓","Move tier down",()=>{if(index<rule.tiers.length-1){
            [rule.tiers[index],rule.tiers[index+1]]=[rule.tiers[index+1],rule.tiers[index]];changed();}}),
          button("×","Remove tier",()=>{if(rule.tiers.length>1){rule.tiers.splice(index,1);changed();}})
        ));region.append(tierRow);
      });
      region.append(button("+","Add placement tier",()=>{rule.tiers.push({zones:[],tables:[]});changed();},
        "secondary small"));break;
    }
    case "locked_assignment":
      region.append(line(fromGroups(),pick("Table",tables,rule.table,v=>commit("table",v))));break;
    case "priority_mark": {
      const grades=state.rules.filter(r=>r.mechanism==="priority_mark")
        .map(r=>r.grade || 1);
      const highest=Math.max(1,...grades,rule.grade || 1);
      const choices=Array.from({length:highest+1},(_,i)=>[i+1,"Grade "+(i+1)]);
      region.append(line(pick("Selector",[["direct","One family"],["criterion","Matching families"]],
        rule.selector,value=>{
          rule.selector=value;
          if(value==="criterion"&&!rule.criterion)rule.criterion=makeCriterion(observedFields(state.guests));
          changed();
        }),pick("Grade",choices,
        rule.grade||1,value=>commit("grade",Number(value)))));
      region.append(rule.selector==="criterion"?criterion():fromGroups());break;
    }
    case "companionship":
      region.append(multi("Exempt families",namedParties,rule.exclusions,
        value=>commit("exclusions",value)));break;
    case "table_pattern":
      (rule.conditions||[]).forEach((condition,index)=>{
        const available=[["groups_at_table","Groups at table"],["occupied_seats","Occupied chairs"],
          ["empty_seats","Empty chairs"],["count","Count matching guests"]];
        const fields=line(pick("Table fact",available,condition.fact,value=>{
          condition.fact=value;
          if(value==="count")condition.criterion=makeCriterion(observedFields(state.guests));
          else delete condition.criterion;changed();
        }),pick("Comparison",OPS.slice(0,-1).map(op=>[op,op]),condition.op,value=>{
          condition.op=value;changed();
        }),edit("Count",condition.value,value=>{
          if(/^\d+$/.test(value)) {condition.value=Number(value);changed();}
        },"number"),button("×","Remove condition",()=>{
          if(rule.conditions.length>1){rule.conditions.splice(index,1);changed();}
        }));
        region.append(fields);
        if(condition.fact==="count")region.append(criterionEditor(condition.criterion,
          state,value=>{condition.criterion=value;changed();},{guestOnly:true}));
      });
      region.append(button("+","Add table condition",()=>{
        rule.conditions.push({fact:"occupied_seats",op:">=",value:1});changed();
      },"secondary small"));break;
    default:break;
  }
  return region;
}
export function renderGenericRules(state, actions) {
  const {changed,announce}=actions;
  const outer=node("div","rules-v2");
  const catalog=Array.isArray(state.catalog)?state.catalog:[];
  if(!catalog.length) return node("p","problem","The v2 rule catalog is unavailable. Retry loading.");
  const builder=node("section","card compact-card");
  builder.append(node("h2","","Add a consideration"));
  const frame=node("fieldset","new-rule-form compact-frame");
  frame.append(node("legend","","Relation → mechanism"));
  if(!state.ruleEngine)state.ruleEngine="intra";
  const engines=Object.entries(ENGINE_NAMES).filter(([engine])=>catalog.some(c=>c.engine===engine));
  const mechanisms=catalog.filter(c=>c.engine===state.ruleEngine);
  if(!mechanisms.some(m=>m.mechanism===state.ruleMechanism))
    state.ruleMechanism=mechanisms[0]?.mechanism;
  frame.append(line(pick("Relation",engines.map(([id,title])=>[id,title]),
    state.ruleEngine,value=>{state.ruleEngine=value;state.ruleMechanism="";changed(false);},
    "new-rule-engine"),pick("Mechanism",mechanisms.map(m=>[m.mechanism,LABELS[m.mechanism]||m.mechanism]),
    state.ruleMechanism,value=>{state.ruleMechanism=value;changed(false);},"new-rule-mechanism"),
    button("+","Add this consideration",()=>{
      const spec=catalog.find(m=>m.engine===state.ruleEngine && m.mechanism===state.ruleMechanism);
      if(!spec)return;
      const newRule=createGenericRule(spec,state);
      state.rules.push(newRule);state.expandedRuleId=newRule.id;
      changed();announce("Added "+newRule.name+".");
    },"primary icon-button","add-rule")));
  builder.append(frame);outer.append(builder);
  const list=node("section","rules-list");
  list.append(line(node("h2","","Considerations"),node("span","pill",state.rules.length+" instances")));
  if(!state.rules.length)list.append(node("p","empty","No considerations yet."));
  state.rules.forEach((rule,index)=>{
    const spec=catalog.find(c=>c.engine===rule.engine&&c.mechanism===rule.mechanism);
    const open=state.expandedRuleId===rule.id;
    const item=node("article","rule-accordion"+(rule.enabled===false?" muted-rule":""));
    item.dataset.ruleId=rule.id;
    const head=node("div","rule-accordion-head");
    const expander=button(open?"⌄":"›",open?"Close rule editor":"Edit "+rule.name,()=>{
      state.expandedRuleId=open?null:rule.id;changed(false);
    },"icon-button expand-rule");
    expander.setAttribute("aria-expanded",String(open));
    const headline=node("div","rule-headline");
    headline.append(node("strong","",rule.name || "Unnamed consideration"),
      node("span","rule-summary",summary(rule)));
    const badge=node("span","badge",ENGINE_NAMES[rule.engine]||rule.engine);
    const weight=node("span","rule-weight-label",rule.mode==="soft"?rule.weight+" pts":rule.mode);
    const switchLabel=node("label","rule-switch");
    const checkbox=node("input");checkbox.type="checkbox";checkbox.checked=rule.enabled!==false;
    checkbox.setAttribute("aria-label","Enable "+rule.name);checkbox.id="rule-enabled-"+index;
    checkbox.addEventListener("change",()=>{rule.enabled=checkbox.checked;changed();});
    switchLabel.append(checkbox);
    const remove=button("🗑","Remove "+rule.name,()=>{
      state.rules.splice(index,1);if(open)state.expandedRuleId=null;changed();
    },"icon-button danger-icon","delete-rule-"+index);
    head.append(expander,headline,badge,weight,switchLabel,remove);
    item.append(head);
    if(open){
      const body=node("div","rule-accordion-body");
      if (!state.guests.length && NEEDS_CRITERION.has(rule.mechanism))
        body.append(node("span","draft-status","Draft · Import guests to choose this criterion"));
      body.append(line(edit("Name",rule.name,value=>commitName(value)),
        edit("Note",rule.description || "",value=>{rule.description=value;changed();})));
      function commitName(value){rule.name=value.trim()||LABELS[rule.mechanism];changed();}
      body.append(line(pick("Mode",(spec?.modes || [rule.mode]).map(m=>[m,m]),
        rule.mode,value=>{
          rule.mode=value;
          rule.weight=value==="soft"?(rule.weight||5):null;
          rule.polarity=value==="soft"?(FIXED_POLARITY[rule.mechanism]||rule.polarity||"reward"):null;
          changed();
        },"rule-mode-"+index),
        ...(rule.mode==="soft"?[
          pick("Effect",["reward","penalty"].filter(x=>!FIXED_POLARITY[rule.mechanism]||
            FIXED_POLARITY[rule.mechanism]===x).map(x=>[x,x]),
            rule.polarity,value=>{rule.polarity=value;changed();}),
          pick("Weight",[[1,"Light · 1"],[5,"Normal · 5"],[25,"Strong · 25"],
              ...( [1,5,25].includes(rule.weight)?[]:[[rule.weight,"Custom · "+rule.weight]])],
            rule.weight,value=>{rule.weight=Number(value);changed();},"rule-weight-"+index)
        ]:[])));
      if(rule.mode==="soft"){
        const advanced=node("details","advanced-value");
        advanced.append(node("summary","","Advanced weight"),edit("Points",rule.weight,value=>{
          if(/^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value))){
            rule.weight=Number(value);changed();
          }
        },"number"));
        body.append(advanced);
        const others=state.rules.filter(r=>r!==rule&&r.enabled!==false&&r.mode==="soft")
          .reduce((total,r)=>total+(Number(r.weight)||0),0);
        if(rule.weight>others && others>0)
          body.append(node("p","weight-advice",rule.name+" has a larger weight than all other active rule weights combined ("+others+")."));
      }
      body.append(mechanismFields(rule,state,changed));
      item.append(body);
    }
    list.append(item);
  });
  outer.append(list);return outer;
}
