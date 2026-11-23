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

  await page.locator("#start-room-outline").click();
  // Click the painted floor rectangle rather than the SVG viewport: viewBox
  // letterboxing can leave noninteractive margins around the floor itself.
  const paintedFloor=page.locator("#map-editor-svg > rect").first();
  const corners=[[0.002,0.002],[0.998,0.002],[0.998,0.998],[0.002,0.998]];
  for(let index=0;index<corners.length;index++){
    // The Draw room outline toolbar is above the canvas. Clicking the button
    // may scroll the canvas below the viewport, so bring it back before the
    // coordinate-based real mouse click.
    await paintedFloor.scrollIntoViewIfNeeded();
    const box=await paintedFloor.boundingBox();
    if(!box)throw Error("Floor drawing unavailable");
    const [u,v]=corners[index];
    await page.mouse.click(box.x+u*box.width,box.y+v*box.height);
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
