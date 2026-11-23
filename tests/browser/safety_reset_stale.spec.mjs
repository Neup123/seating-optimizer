import {test, expect} from "@playwright/test";

// Operator-like acceptance with synthetic guest identities, never live data.
test.use({viewport:{width:1600,height:1000},deviceScaleFactor:2});

function savedSeating() {
  const guests=[
    {id:"g1",name:"Alice",group_id:"family-one",group_name:"Family One",attributes:{language:"English"}},
    {id:"g2",name:"Bob",group_id:"family-one",group_name:"Family One",attributes:{language:"English"}}
  ];
  const layout={floors:[{zone_id:"ground",width:400,height:300,tables:[
    {table_id:"G1",x:20,y:20,width:160,height:140,shape:"rectangle"}]}]};
  const plan={session_id:"browser-safety",status:"feasible",total_score:8,solve_seconds:0.1,
    layout,score_breakdown:[],tables:[
      {table_id:"G1",zone_id:"ground",capacity:4,occupied:2,empty_seats:2}],
    assignments:[{group_id:"family-one",group_name:"Family One",table_id:"G1",
      guest_ids:["g1","g2"],guest_names:["Alice","Bob"],points:8,
      reasons:[{rule_id:"capacity",description:"Two of four seats",points:0}]}],
    compromises:[],conflicting_constraints:[],message:"All hard constraints satisfied."};
  return {version:2,data:{sessionId:"browser-safety",screen:"plan",view:"table",
    guests,layout,plan,tables:[{id:"G1",zone_id:"ground",capacity:4,properties:[]}],
    zones:[{id:"ground",name:"Ground floor"}],rules:[],manualInstructions:[]}};
}
async function restore(page){
  const session=savedSeating();
  // Set storage once for this tab. addInitScript would replay the old
  // snapshot on *every* navigation and undo the reset/stale state on reload.
  await page.goto("/");
  await page.evaluate(value=>localStorage.setItem(
    "seating-optimizer:session:v2",JSON.stringify(value)),session);
  await page.reload();
  await page.locator("#nav-plan").click();
  await expect(page.locator("#solve-plan")).toBeVisible();
  await expect(page.locator("#new-session")).toBeVisible();
}

test("new session cannot erase a saved solved session without explicit confirmation (#120)",async({page},info)=>{
  await restore(page);
  await page.locator("#new-session").click();
  await expect(page.locator("#confirm-new-session")).toBeVisible();
  await expect(page.locator("#cancel-new-session")).toBeFocused();
  await expect(page.locator("#stale-plan-preview")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.locator("#confirm-new-session")).toHaveCount(0);
  await expect(page.locator("#new-session")).toBeVisible();
  await page.reload();
  await page.locator("#nav-plan").click();
  await expect(page.locator("#solve-plan")).toBeVisible();
  await expect(page.locator("#confirm-new-session")).toHaveCount(0);
  const before=await page.evaluate(()=>localStorage.getItem("seating-optimizer:session:v2"));
  expect(before).toContain("Alice");
  await page.locator("#new-session").click();
  await page.locator("#cancel-new-session").click();
  expect(await page.evaluate(()=>localStorage.getItem("seating-optimizer:session:v2"))).toContain("Alice");
  await page.locator("#new-session").click();
  await page.screenshot({path:info.outputPath("confirmation-before-reset.png"),fullPage:true});
  await page.locator("#confirm-new-session").click();
  await expect(page.locator("#notice")).toContainText("New empty session started");
  expect(await page.evaluate(()=>localStorage.getItem("seating-optimizer:session:v2"))).not.toContain("Alice");
  await page.reload();
  await expect(page.locator("#confirm-new-session")).toHaveCount(0);
  expect(await page.evaluate(()=>localStorage.getItem("seating-optimizer:session:v2"))).not.toContain("Alice");
});

test("input edits retain clearly marked read-only stale seating across navigation and reload (#122)",async({page},info)=>{
  await restore(page);
  await page.getByText("Advanced solver settings").click();
  const limit=page.locator("#time-limit");
  await expect(limit).toBeVisible();
  await limit.fill("4");
  await limit.blur();
  await expect(page.locator("#stale-plan-preview")).toBeVisible();
  await expect(page.locator("#stale-plan-preview")).toContainText("Table G1");
  await expect(page.locator("#download-json")).toHaveCount(0);
  await expect(page.getByText("Previous seating plan — needs recalculation")).toBeVisible();
  await page.locator("#nav-rules").click();
  await page.locator("#nav-plan").click();
  await expect(page.locator("#stale-plan-preview")).toBeVisible();
  await page.screenshot({path:info.outputPath("stale-read-only-seating.png"),fullPage:true});
  await page.reload();
  await page.locator("#nav-plan").click();
  await expect(page.locator("#stale-plan-preview")).toContainText("Table G1");
  await expect(page.locator("#stale-plan-preview")).toContainText("Re-optimize before using or printing");
  await expect(page.locator("#download-json")).toHaveCount(0);
});
