import { test, expect } from "@playwright/test";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const prototype = pathToFileURL(resolve("prototypes/venue-editor-121-123.html")).href;

// Prototype-only evidence. Production geometry persistence, rule re-keying and
// print/export integration are intentionally excluded until design approval.
test("venue prototype adds with defaults and edits the selected compact table row", async ({page}) => {
  await page.goto(prototype);
  await expect(page.getByText("5 tables · 48 chairs")).toBeVisible();
  await page.getByRole("button", {name: /Add table/}).click();
  await expect(page.getByText("6 tables · 58 chairs")).toBeVisible();
  await page.getByLabel("Table ID").fill("NEW-6");
  await page.getByLabel("Table ID").press("Tab");
  await expect(page.getByText("NEW-6 · Table 6")).toBeVisible();
  await page.getByLabel("Display name").fill("Near entrance");
  await page.getByLabel("Display name").press("Tab");
  await expect(page.getByText("NEW-6 · Near entrance")).toBeVisible();
  await page.getByRole("button", {name:"Edit room outline"}).click();
  await expect(page.getByRole("button", {name:"Save outline"})).toBeVisible();
  const map=page.locator("#canvas");
  const rect=await map.boundingBox();
  if (!rect) throw Error("Prototype map not visible");
  for (const [x,y] of [[0.12,0.2],[0.70,0.2],[0.7,0.8],[0.12,0.8]])
    await page.mouse.click(rect.x+rect.width*x,rect.y+rect.height*y);
  await page.getByRole("button", {name:"Save outline"}).click();
  await expect(page.getByText("Room outline saved in prototype.")).toBeVisible();
  await expect(page.getByRole("button", {name:"Save outline"})).toBeHidden();
});

test("venue prototype stays usable at mobile width", async ({page}) => {
  await page.setViewportSize({width:390,height:780});
  await page.goto(prototype);
  await expect(page.locator("#canvas")).toBeVisible();
  await expect(page.getByRole("button", {name:/Add table/})).toBeVisible();
  await page.getByLabel("Search tables").fill("Couples");
  await expect(page.getByText("T3 · Couples")).toBeVisible();
  await expect(page.locator(".table-row")).toHaveCount(1);
});
