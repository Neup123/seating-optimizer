import {test, expect} from "@playwright/test";

test.use({viewport:{width:1600,height:1000},deviceScaleFactor:2});
const shot = (page,info,label) => page.screenshot({path:info.outputPath(label+".png"),fullPage:true});
async function upload(page,filename,contents) {
  await page.locator("#nav-import").click();
  await page.locator("#guest-file").setInputFiles({
    name:filename,mimeType:"text/csv",buffer:Buffer.from(contents)
  });
  await expect(page.locator("#import-guests")).toBeVisible();
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported ");
}
async function choose(page,engine,mechanism) {
  await page.locator("#nav-rules").click();
  await page.locator("#new-rule-engine").selectOption(engine);
  await page.locator("#new-rule-mechanism").selectOption(mechanism);
  await page.locator("#add-rule").click();
}
async function floor(page,tableId,chairs,tag) {
  await page.locator("#nav-map").click();
  await page.locator("#new-table-id").fill(tableId);
  await page.locator("#new-table-capacity").fill(String(chairs));
  if(tag) {
    await page.locator(".property-picker").first()
      .locator('input[aria-label="New table property"]').fill(tag);
    await page.locator(".property-picker").first()
      .locator('button[aria-label="Add table property"]').click();
  }
  await page.locator("#add-table").click();
  await expect(page.locator('[data-table-id="'+tableId+'"]')).toHaveCount(2);
}

test("golden 120 guest registrations: v2 criteria, API solve, selection, print and JSON export",async({page},info)=>{
  test.setTimeout(150000);
  const errors=[];page.on("pageerror",err=>errors.push(err.message));
  await page.goto("/");
  await shot(page,info,"01-import-empty");
  const csv=["Guest Name,Party Size,Language,Age Layer,Mobility"];
  const langs=["English","French","Spanish"];
  for(let i=0;i<60;i++)csv.push([
    "Family "+String(i).padStart(2,"0"),"2",langs[i%3],
    i%4===0?"Family with children":"Adults",
    i===7?"wheelchair":"mobile"
  ].join(","));
  await page.locator("#guest-file").setInputFiles({
    name:"golden-120.csv",mimeType:"text/csv",buffer:Buffer.from(csv.join("\n")+"\n")
  });
  await expect(page.locator("#map-mobility")).toHaveValue("attribute.mobility");
  await expect(page.locator(".criterion-ready").first()).toBeVisible();
  await shot(page,info,"02-import-mapping");
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported 120 guests");
  await expect(page.locator(".pill").first()).toContainText("120 guests");

  const floors=[
    {zone_id:"ground",prefix:"G"},{zone_id:"first",prefix:"F"}
  ].map(entry=>({
    zone_id:entry.zone_id,width:1650,height:680,
    tables:Array.from({length:6},(_,i)=>({
      table_id:entry.prefix+"-"+i,x:35+(i%3)*540,
      y:30+Math.floor(i/3)*330,width:485,height:265,
      shape:i%2?"ellipse":"rectangle"
    }))
  }));
  await page.locator("#nav-map").click();
  await shot(page,info,"03-venue-empty");
  await page.locator("#layout-file").setInputFiles({
    name:"golden-layout.json",mimeType:"application/json",buffer:Buffer.from(JSON.stringify({floors}))
  });
  await expect(page.locator("#table-G-0-capacity")).toBeVisible();
  for(const [zone,prefix] of [["ground","G"],["first","F"]]) {
    await page.locator("#floor-select").selectOption(zone);
    for(let i=0;i<6;i++){
      const input=page.locator('form[data-table-id="'+prefix+"-"+i+'"] input[id="table-'+prefix+"-"+i+'-capacity"]');
      await input.fill("10");await input.blur();
      await expect(page.locator('form[data-table-id="'+prefix+"-"+i+'"] .save-state'))
        .toContainText("Saved locally");
    }
  }
  await page.locator("#validate-layout").click();
  await expect(page.locator("#notice")).toContainText("Venue layout validated");
  await shot(page,info,"04-venue-tables");

  await choose(page,"venue","placement_by_criterion");
  await expect(page.locator("#new-rule-shape")).toHaveCount(0);
  await page.locator("#criterion-field").selectOption("mobility");
  await page.locator("#criterion-value").selectOption(JSON.stringify("wheelchair"));
  await page.locator("#rule-mode-0").selectOption("hard");
  await expect(page.locator(".rule-accordion")).toHaveCount(1);
  const criterionControls=await Promise.all(["#criterion-field","#criterion-op","#criterion-value"]
    .map(async selector=>page.locator(selector).boundingBox()));
  const bottoms=criterionControls.map(box=>box.y+box.height);
  expect(Math.max(...bottoms)-Math.min(...bottoms),
    "Criterion field, operator and value must share one baseline").toBeLessThanOrEqual(4);
  const ruleHead=page.locator(".rule-accordion-head").first();
  const aligned=await Promise.all([".rule-headline",".badge",".rule-weight-label",
    ".rule-switch input",".danger-icon"].map(async selector=>ruleHead.locator(selector).boundingBox()));
  const centers=aligned.map(box=>box.y+box.height/2);
  expect(Math.max(...centers)-Math.min(...centers),
    "Rule title, engine, weight, toggle and delete must align").toBeLessThanOrEqual(12);
  await shot(page,info,"05-rules-hard-expanded");
  await choose(page,"intra","own_attribute_grouping");
  await page.locator("#criterion-field").selectOption("language");
  await choose(page,"venue","holes_term");
  await expect(page.locator(".rule-accordion")).toHaveCount(3);
  await expect(page.locator(".rule-accordion-body")).toHaveCount(1);
  await shot(page,info,"06-rules-accordion");
  await page.locator("#nav-plan").click();
  await shot(page,info,"07-plan-empty");

  // Snapshot the deliberately designed intermediate state before the server responds.
  let releaseSolve;
  await page.route("**/v2/solve",async route=>{
    await new Promise(resolve=>{releaseSolve=resolve;});
    await route.continue();
  });
  const pending=page.waitForRequest(r=>r.url().endsWith("/v2/solve")&&r.method()==="POST");
  const responsePromise=page.waitForResponse(r=>r.url().endsWith("/v2/solve")&&r.request().method()==="POST");
  await page.locator("#solve-plan").click();
  await pending;
  await expect(page.locator(".solve-progress")).toBeVisible();
  await shot(page,info,"08-plan-loading");
  releaseSolve();
  const res=await responsePromise;
  expect(res.status()).toBe(200);
  const result=await res.json();
  expect(["optimal","feasible"]).toContain(result.status);
  expect(result.assignments.reduce((total,a)=>total+a.guest_ids.length,0)).toBe(120);
  expect(result.tables.every(t=>t.occupied<=t.capacity)).toBe(true);
  expect(result.conflicting_constraints).toEqual([]);
  expect(result.unseated_reasons).toEqual([]);
  expect(result.score_breakdown.length).toBe(2);
  const req=JSON.parse(res.request().postData());
  expect(req.rules.every(rule=>rule.engine&&rule.mechanism&&!rule.shape)).toBe(true);
  expect(req.tables.every(t=>t.capacity===10)).toBe(true);
  await page.unroute("**/v2/solve");
  await expect(page.locator("#view-table")).toHaveAttribute("aria-selected","true");
  await expect(page.locator(".working-table-section").first()).toBeVisible();
  await shot(page,info,"09-plan-tables");
  await page.locator('.plan-check input[type="checkbox"]').first().check();
  await expect(page.locator("#plan-selection")).toContainText("people");
  await shot(page,info,"10-plan-selected");
  await page.locator("#clear-plan-selection").click();
  await page.locator("#view-people").click();
  await expect(page.locator(".plan-entry").first()).toBeVisible();
  await page.locator("#plan-search").fill("Family 00");
  await expect(page.locator(".plan-entry")).toHaveCount(1);
  await shot(page,info,"11-plan-people-filter");
  await page.locator("#plan-search").fill("");
  await page.locator("#view-floor").click();
  await expect(page.locator("#working-floor-svg")).toBeVisible();
  await shot(page,info,"12-plan-map");

  await page.locator("#view-print").click();
  await page.locator("#print-format").selectOption("people");
  await expect(page.locator("#list-preview")).toHaveAttribute("srcdoc",/<table>/);
  await shot(page,info,"13-print-people");
  await page.locator("#print-format").selectOption("groups-table");
  await expect(page.locator("#list-preview")).toHaveAttribute("srcdoc",/<table>/);
  await shot(page,info,"14-print-tables");
  await page.locator("#print-format").selectOption("cards");
  await expect(page.locator("#cards-preview")).toHaveAttribute("src",/^blob:/);
  await shot(page,info,"15-print-cards");
  await page.locator("#print-format").selectOption("floor");
  await expect(page.locator("#floor-preview")).toHaveAttribute("src",/^blob:/);
  await shot(page,info,"16-print-floor");

  const download=page.waitForEvent("download");
  await page.locator("#download-json").click();
  expect((await download).suggestedFilename()).toBe("seating-plan.json");
  await page.reload();
  await expect(page.locator(".pill").first()).toContainText("120 guests");
  await expect(page.locator(".pill").nth(1)).toContainText("12 tables");
  await expect(page.locator(".pill").nth(2)).toContainText("3 rules");
  await page.locator("#nav-rules").click();
  await expect(page.locator(".rule-accordion")).toHaveCount(3);
  expect(errors).toEqual([]);
  console.log("GOLDEN_V2_120 "+result.status+" assignments="+result.assignments.length);
});

test("mapping preview preserves external column targets and rejects unsafe import",async({page},info)=>{
  await page.goto("/");
  await page.locator("#guest-file").setInputFiles({
    name:"external.csv",mimeType:"text/csv",
    buffer:Buffer.from("Guest Name,Family,Party Count,Side,Meal\nAlice,Smith,2,North,Vegan\n")
  });
  await expect(page.locator("#map-guest-name")).toHaveValue("name");
  await expect(page.locator("#map-family")).toHaveValue("group_id");
  await expect(page.locator("#map-party-count")).toHaveValue("size");
  await expect(page.locator("#map-side")).toHaveValue("");
  await expect(page.locator("#map-meal")).toHaveValue("");
  await shot(page,info,"17-import-extra-columns");
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported 2 guests");
  await page.locator("#new-session").click();
  await page.locator("#guest-file").setInputFiles({
    name:"incomplete.csv",mimeType:"text/csv",
    buffer:Buffer.from("Guest Name,Family,Side,Meal\nAlice,Smith,North,Vegan\n")
  });
  await expect(page.locator("body")).toContainText("Missing required mapping: size");
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Import blocked");
  await shot(page,info,"18-import-error");
});

test("operator owns overflow choices; shortage produces alarm without automatic unseating",async({page},info)=>{
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="name"]').fill("Main hall");
  await page.locator("#add-floor").click();
  await expect(page.locator("#floor-select")).toHaveValue("floor-1");
  await floor(page,"T1",1);
  await upload(page,"shortage.csv","Guest Name,Party Size\nOne family,2\n");
  await page.locator("#nav-plan").click();
  const response=page.waitForResponse(r=>r.url().endsWith("/v2/solve"));
  await page.locator("#solve-plan").click();
  const plan=await (await response).json();
  expect(["infeasible","needs_review"]).toContain(plan.status);
  // Shortage is an alarm, NOT an automatic decision about any specific family.
  expect(plan.message).toMatch(/short by 1/i);
  expect(plan.unseated_reasons).toEqual([]);
  expect(plan.not_seated).toEqual([]);
  await expect(page.locator("#overflow-choice")).toBeVisible();
  await shot(page,info,"19-shortage-infeasible");
  await expect(page.locator("#confirm-unseat")).toBeVisible();
  // No button is clicked: the plan and instructions remain unmodified.
});

test("single-floor venue template retains rules and capacities before guest import",async({page},info)=>{
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="name"]').fill("Main hall");
  await page.locator("#add-floor").click();
  await floor(page,"H1",4);
  await choose(page,"venue","holes_term");
  await page.locator("#nav-map").click();
  await page.locator("#template-toggle").click();
  await page.locator("#template-name").fill("Hall dinner");
  await page.locator("#save-template").click();
  await expect(page.locator("#notice")).toContainText("Saved configuration template");
  await page.locator("#new-session").click();
  await page.locator("#nav-map").click();
  if (!(await page.locator(".template-drawer").evaluate(node=>node.open)))
    await page.locator("#template-toggle").click();
  await page.locator("#template-select").selectOption("Hall dinner");
  await page.locator("#load-template").click();
  await expect(page.locator("#notice")).toContainText("Loaded template");
  await expect(page.locator("#table-H1-capacity")).toHaveValue("4");
  await expect(page.locator(".pill").nth(2)).toContainText("1 rules");
  await shot(page,info,"20-restored-template");
  await upload(page,"guests.csv","Guest Name,Party Size\nAlpha,2\n");
  await page.locator("#nav-plan").click();
  await page.locator("#solve-plan").click();
  await expect(page.locator("#notice")).toContainText("Solver returned");
  await expect(page.locator(".working-table-section").first()).toContainText("Table H1");
});

test("retry after a network failure uses generic v2 endpoint and keeps all inputs",async({page},info)=>{
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="name"]').fill("Hall");
  await page.locator("#add-floor").click();
  await floor(page,"T1",4);
  await upload(page,"retry.csv","Guest Name,Party Size\nAlice,2\n");
  await page.locator("#nav-plan").click();
  let offline=true;
  await page.route("**/v2/solve",route=>offline?route.abort("failed"):route.continue());
  await page.locator("#solve-plan").click();
  await expect(page.locator("#notice")).toContainText("Could not reach the server");
  await expect(page.locator("#retry-action")).toBeVisible();
  await shot(page,info,"21-solve-network-error");
  offline=false;
  await page.locator("#retry-action").click();
  await expect(page.locator("#notice")).toContainText("Solver returned");
  await expect(page.locator(".working-table-section").first()).toBeVisible();
  await page.unroute("**/v2/solve");
});

test("rule property preferences share venue vocabulary and solve through v2 only",async({page},info)=>{
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="name"]').fill("Hall");
  await page.locator("#add-floor").click();
  await floor(page,"A",2,"accessible");
  await floor(page,"B",2,"quiet");
  await upload(page,"needs.csv","Guest Name,Party Size,Mobility\nFamily,2,wheelchair\nVisitors,2,mobile\n");
  await choose(page,"venue","property_need");
  await page.locator("#criterion-field").selectOption("mobility");
  await page.locator("#criterion-value").selectOption(JSON.stringify("wheelchair"));
  await expect(page.locator("#rule-property")).toHaveValue("accessible");
  await page.locator("#rule-weight-0").selectOption("25");
  await page.locator("#nav-plan").click();
  const res=page.waitForResponse(r=>r.url().endsWith("/v2/solve"));
  await page.locator("#solve-plan").click();
  const response=await res;expect(response.status()).toBe(200);
  const plan=await response.json();
  expect(["optimal","feasible"]).toContain(plan.status);
  const family=plan.assignments.find(a=>a.group_id==="registration:2");
  expect(family.table_id).toBe("A");
  expect(response.request().postDataJSON().rules[0].mechanism).toBe("property_need");
  await shot(page,info,"22-table-property-score");
});

test("desktop and mobile shells avoid horizontal overflow with focused task views",async({page},info)=>{
  await page.goto("/");
  for(const screen of ["import","rules","map","plan"]) {
    await page.locator("#nav-"+screen).click();
    await shot(page,info,"23-empty-"+screen);
  }
  await page.setViewportSize({width:390,height:844});
  for(const screen of ["import","rules","map","plan"]) {
    const nav=await page.locator(".nav").boundingBox();
    expect(nav.height,"Mobile task navigation must not grow vertically")
      .toBeLessThanOrEqual(60);
    await page.locator("#nav-"+screen).click();
    const width=await page.evaluate(()=>({
      viewport:window.innerWidth,
      page:document.documentElement.scrollWidth,
      widest:[...document.querySelectorAll("body *")]
        .filter(node=>node.getBoundingClientRect().right>window.innerWidth+1)
        .sort((a,b)=>b.getBoundingClientRect().right-a.getBoundingClientRect().right)
        .slice(0,5).map(node=>node.tagName.toLowerCase()+"."+
          node.className.toString().replaceAll(" ",".")+
          " right="+Math.round(node.getBoundingClientRect().right))
    }));
    expect(width.page,screen+" horizontal overflow: "+JSON.stringify(width))
      .toBeLessThanOrEqual(width.viewport+1);
    await shot(page,info,"24-mobile-"+screen);
  }
});


test("U38/F3: mobile venue, rules and plan use focused panes with aligned controls",async({page},info)=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto("/");
  await page.locator("#guest-file").setInputFiles({
    name:"mobile.csv",mimeType:"text/csv",buffer:Buffer.from("Guest Name,Party Size,Language\nFamily,2,Hebrew\n")
  });
  await expect(page.locator("#guest-file-trigger")).toBeVisible();
  await expect(page.locator("#import-guests")).toBeVisible();
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported 2 guests");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="name"]').fill("Mobile hall");
  await page.locator("#add-floor").click();
  await expect(page.locator("#venue-mobile-map")).toHaveAttribute("aria-pressed","true");
  await expect(page.locator(".map-canvas")).toBeVisible();
  await expect(page.locator(".venue-table-settings")).toBeHidden();
  await shot(page,info,"25-mobile-venue-map");
  await page.locator("#venue-mobile-tables").click();
  await expect(page.locator(".map-canvas")).toBeHidden();
  await expect(page.locator(".venue-table-settings")).toBeVisible();
  await page.locator("#new-table-id").fill("M1");
  await page.locator("#new-table-capacity").fill("4");
  const checkbox=page.locator("#new-table-small-priority");
  const priorityText=page.locator(".priority-checkbox").first().locator("span");
  const [checkBox,labelBox]=await Promise.all([checkbox.boundingBox(),priorityText.boundingBox()]);
  expect(Math.abs((checkBox.y+checkBox.height/2)-(labelBox.y+labelBox.height/2)),
    "Priority checkbox and label must share a baseline").toBeLessThanOrEqual(5);
  await page.locator("#add-table").click();
  await expect(page.locator("#table-M1-capacity")).toBeVisible();
  await shot(page,info,"26-mobile-venue-tables");
  await page.locator("#venue-mobile-map").click();
  await expect(page.locator("#map-editor-svg")).toBeVisible();
  await shot(page,info,"27-mobile-venue-map-with-table");
  await page.locator("#nav-rules").click();
  await page.locator("#new-rule-engine").selectOption("intra");
  await page.locator("#new-rule-mechanism").selectOption("split_term");
  await page.locator("#add-rule").click();
  await expect(page.locator(".rule-accordion-body")).toHaveCount(1);
  await shot(page,info,"28-mobile-rules-expanded");
  await page.locator("#nav-plan").click();
  await page.locator("#solve-plan").click();
  await expect(page.locator(".working-table-section").first()).toBeVisible();
  await expect(page.locator("#view-list")).toHaveAttribute("aria-selected","true");
  await shot(page,info,"29-mobile-plan-list");
  await page.locator("#view-floor").click();
  await expect(page.locator("#working-floor-svg")).toBeVisible();
  await shot(page,info,"30-mobile-plan-map");
  for(const screen of ["rules","map","plan"]){
    await page.locator("#nav-"+screen).click();
    const widths=await page.evaluate(()=>({
      viewport:window.innerWidth,page:document.documentElement.scrollWidth
    }));
    expect(widths.page,screen+" must not overflow mobile viewport")
      .toBeLessThanOrEqual(widths.viewport+1);
  }
});

test("F1/U14: restored 43-guest v2 session exposes named +6 plan breakdown",async({page},info)=>{
  const guests=Array.from({length:43},(_,i)=>({
    id:"g"+i,name:i<3?"India Family ("+(i+1)+"/3)":"Guest "+i,
    group_id:i<3?"india":"family-"+i,group_name:i<3?"India Family":"Family "+i,
    attributes:{language:i<3?"Hebrew":"English"}
  }));
  const rules=[
    {id:"hebrew-upper-preference",name:"",engine:"venue",
      mechanism:"placement_by_criterion",mode:"soft",weight:2,polarity:"reward",enabled:true,
      criterion:{subject:"guest",field:"language",op:"==",value:"Hebrew"},zones:["upper"]},
    ...["split_term","holes_term","companionship","priority_mark","property_fit"]
      .map((mechanism,i)=>({id:"rule-other-"+i,name:"",engine:"venue",mechanism,mode:"soft",weight:1,enabled:true}))
  ];
  const tables=["B1","A1","A2","A3","A4","A5","A6"].map((id,i)=>({
    id,zone_id:i?"ground":"upper",capacity:10,properties:[]
  }));
  const assignments=[{group_id:"india",group_name:"India Family",table_id:"B1",
    guest_ids:["g0","g1","g2"],guest_names:["India Family (1/3)","India Family (2/3)","India Family (3/3)"],
    reasons:[{rule_id:"capacity",description:"Three of ten chairs",points:0}],points:0}];
  const plan={session_id:"test-43",status:"feasible",total_score:6,solve_seconds:.1,
    score_breakdown:[{rule_id:"hebrew-upper-preference",points:6}],
    tables:tables.map((t,i)=>({table_id:t.id,zone_id:t.zone_id,capacity:t.capacity,
      occupied:i?0:3,empty_seats:i?10:7})),
    assignments,layout:{floors:[]},compromises:[],conflicting_constraints:[],
    message:"Solved",not_seated:[]};
  const session={version:2,data:{screen:"plan",view:"table",guests,rules,tables,
    zones:[{id:"upper",name:"Upper"},{id:"ground",name:"Ground"}],
    layout:{floors:[]},plan,manualInstructions:[]}};
  await page.addInitScript(value=>localStorage.setItem("seating-optimizer:session:v2",JSON.stringify(value)),session);
  await page.goto("/");
  await expect(page.locator(".score-breakdown")).toContainText("+6 points");
  await expect(page.locator(".score-breakdown")).toContainText("language is Hebrew");
  await expect(page.locator(".score-breakdown")).not.toContainText("Unnamed consideration");
  await page.locator('.plan-entry button[title="Details"]').first().click();
  await expect(page.locator(".plan-details")).toContainText("Plan-wide scoring");
  await shot(page,info,"31-score-breakdown-43-guests");
});
