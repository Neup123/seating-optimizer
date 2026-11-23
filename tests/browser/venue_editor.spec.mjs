import {test,expect} from "@playwright/test";

test("real venue editor: compact defaults, rename, resize and persisted room outline", async ({page}) => {
  test.setTimeout(120000);
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="name"]').fill("Assembly hall");
  await page.locator("#add-floor").click();
  await expect(page.locator("#new-table-id")).toHaveValue("T1");
  await expect(page.locator("#new-table-capacity")).toHaveValue("10");
  await page.locator("#add-table").click();
  await expect(page.locator(".table-row-details")).toHaveCount(1);
  await expect(page.locator("#table-T1-name")).toBeVisible();
  await page.locator("#table-T1-name").fill("Near windows");
  await page.locator("#table-T1-name").blur();
  await expect(page.locator(".table-row-heading")).toContainText("Near windows");
  await expect(page.locator('[data-table-id="T1"]')).toHaveCount(2);
  const initialWidth=await page.locator("#table-T1-width").inputValue();
  const handle=page.locator("#map-editor-svg .map-resize-handle");
  const rect=await handle.boundingBox();
  if(!rect)throw Error("Resize handle not visible");
  await page.mouse.move(rect.x+rect.width/2,rect.y+rect.height/2);
  await page.mouse.down();
  await page.mouse.move(rect.x+rect.width/2+30,rect.y+rect.height/2+14,{steps:5});
  await page.mouse.up();
  await expect.poll(async()=>Number(await page.locator("#table-T1-width").inputValue()))
    .toBeGreaterThan(Number(initialWidth));

  // Keep this test table clear of the room corners and the canvas's
  // visually clipped 12px rounded border, just like an operator would.
  await page.locator("#table-T1-x").fill("40");
  await page.locator("#table-T1-x").blur();
  await page.locator("#table-T1-y").fill("40");
  await page.locator("#table-T1-y").blur();
  await expect(page.locator("#table-T1-y")).toHaveValue("40");
  await page.locator("#start-room-outline").click();
  const paintedFloor=page.locator("#map-editor-svg > rect").first();
  const cornerPositions=({width:w,height:h})=>[
    [16,3],[w-16,3],[w-3,16],[w-3,h-16],
    [w-16,h-3],[16,h-3],[3,h-16],[3,16],
  ];
  const floorBox=await paintedFloor.boundingBox();
  if(!floorBox)throw Error("Floor drawing unavailable");
  const corners=cornerPositions(floorBox);
  for(let index=0;index<corners.length;index++){
    const [x,y]=corners[index];
    // A locator click auto-scrolls and checks the real painted target;
    // page.mouse.click at off-screen coordinates can silently miss.
    await paintedFloor.click({position:{x,y}});
    await expect(page.locator(".room-corner")).toHaveCount(index+1);
  }
  await page.locator("#save-room-outline").click();
  await expect(page.locator("#notice")).toContainText("Room outline validated and saved");
  await expect(page.locator("#clear-room-outline")).toBeVisible();
  await page.reload();
  await page.locator("#nav-map").click();
  await expect(page.locator("#clear-room-outline")).toBeVisible();
  await expect(page.locator(".room-boundary")).toHaveCount(1);
  await expect(page.locator(".table-row-heading")).toContainText("Near windows");
  await page.locator("#table-T1-id").fill("Main");
  await page.locator("#rename-table-T1").click();
  await expect(page.locator("#table-Main-capacity")).toBeVisible();
  await expect(page.locator(".table-row-heading")).toContainText("Near windows");
  await expect(page.locator('[data-table-id="Main"]')).toHaveCount(2);
});
