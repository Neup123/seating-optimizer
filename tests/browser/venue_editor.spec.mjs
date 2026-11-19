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
  const canvas=page.locator("#map-editor-svg");
  const box=await canvas.boundingBox();
  if(!box)throw Error("Map unavailable");
  for(const [u,v] of [[0.002,0.002],[0.998,0.002],[0.998,0.998],[0.002,0.998]])
    await page.mouse.click(box.x+u*box.width,box.y+v*box.height);
  await page.locator("#save-room-outline").click();
  await expect(page.locator("#notice")).toContainText("Room outline validated and saved");
  await expect(page.locator("#clear-room-outline")).toBeVisible();
  await page.reload();
  await page.locator("#nav-map").click();
  await expect(page.locator("#clear-room-outline")).toBeVisible();
  await expect(page.locator(".room-boundary")).toHaveCount(1);
  await expect(page.locator(".table-row-heading")).toContainText("Near windows");
});
