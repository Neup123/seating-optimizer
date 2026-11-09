import { test, expect } from "@playwright/test";

test("golden 120 guests complete the actual UI/API workflow: import → rules → solve → all views", async ({ page }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("#nav-import")).toBeVisible();

  const languages = ["English", "French", "Spanish"];
  const csv = ["Guest Name,Party Size,Language,Age Layer,Mobility"];
  for (let family = 0; family < 60; family++) {
    csv.push(["Family " + String(family).padStart(2, "0"), "2",
      languages[family % 3],
      family % 4 === 0 ? "Family with children" : "Adults",
      family === 7 ? "wheelchair" : "mobile"].join(","));
  }
  await page.locator("#guest-file").setInputFiles({
    name: "golden-120.csv", mimeType: "text/csv", buffer: Buffer.from(csv.join("\n") + "\n")
  });
  await expect(page.locator("#map-guest-name")).toHaveValue("name");
  await expect(page.locator("#map-party-size")).toHaveValue("size");
  await expect(page.locator("#map-mobility")).toHaveValue("attribute.mobility");
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported 120 guests");
  await expect(page.locator(".pill").first()).toContainText("120 guests");

  const floors = [
    { zone_id: "ground", prefix: "G" },
    { zone_id: "first", prefix: "F" }
  ].map(entry => ({
    zone_id: entry.zone_id, width: 1650, height: 680,
    tables: Array.from({ length: 6 }, (_, i) => ({
      table_id: entry.prefix + "-" + i,
      x: 35 + (i % 3) * 540, y: 30 + Math.floor(i / 3) * 330,
      width: 485, height: 265, shape: i % 2 ? "ellipse" : "rectangle"
    }))
  }));
  await page.locator("#nav-map").click();
  await page.locator("#layout-file").setInputFiles({
    name: "golden-layout.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ floors }))
  });
  await expect(page.locator("#table-G-0-capacity")).toBeVisible();

  for (const [floor, prefix] of [["ground", "G"], ["first", "F"]]) {
    await page.locator("#floor-select").selectOption(floor);
    for (let i = 0; i < 6; i++) {
      const form = page.locator('form[data-table-id="' + prefix + "-" + i + '"]');
      await form.locator('[id="table-' + prefix + "-" + i + '-capacity"]').fill("10");
      await form.locator('button[type="submit"]').click();
    }
  }
  await page.locator("#validate-layout").click();
  await expect(page.locator("#notice")).toContainText("Venue layout validated");

  await page.locator("#nav-rules").click();
  await page.locator("#new-rule-shape").selectOption("zone_restriction");
  await page.locator("#add-rule").click();
  await page.locator("#rule-0-attribute").fill("mobility");
  await page.locator("#rule-0-attribute").blur();
  await page.locator("#rule-0-value").fill("wheelchair");
  await page.locator("#rule-0-value").blur();
  await page.locator("#rule-0-zone").selectOption("ground");
  await expect(page.locator("#rule-mode-0")).toHaveValue("hard");

  await page.locator("#new-rule-shape").selectOption("attribute_grouping");
  await page.locator("#add-rule").click();
  await page.locator("#rule-1-attribute").fill("language");
  await page.locator("#rule-1-attribute").blur();
  await page.locator("#rule-weight-1").fill("4");
  await page.locator("#rule-weight-1").blur();

  await page.locator("#new-rule-shape").selectOption("fill_efficiency");
  await page.locator("#add-rule").click();
  await expect(page.locator("#rule-weight-2")).toHaveValue("2");

  await page.locator("#nav-plan").click();
  await page.locator("#session-id").fill("golden-ui-120");
  await page.locator("#session-id").blur();
  const responsePromise = page.waitForResponse(response =>
    response.url().endsWith("/v1/solve") && response.request().method() === "POST"
  );
  await page.locator("#solve-plan").click();
  const solveResponse = await responsePromise;
  expect(solveResponse.status()).toBe(200);
  const plan = await solveResponse.json();
  expect(["optimal", "feasible"]).toContain(plan.status);
  expect(plan.assignments.length).toBe(60);
  expect(plan.assignments.reduce((count, group) => count + group.guest_ids.length, 0)).toBe(120);
  expect(plan.tables.every(t => t.occupied <= t.capacity && t.empty_seats >= 0)).toBe(true);
  expect(plan.conflicting_constraints).toEqual([]);
  const chairFamily = plan.assignments.find(entry => entry.group_id === "registration:9");
  expect(chairFamily.table_id.startsWith("G-")).toBe(true);
  expect(chairFamily.guest_ids.length).toBe(2);
  expect(plan.layout.floors.length).toBe(2);
  expect(plan.score_breakdown.length).toBe(2);

  await expect(page.locator("#notice")).toContainText("Solver returned");
  await expect(page.locator("#view-table")).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("pre").first()).toContainText("Table G-0");
  await expect(page.getByText("Per-assignment explanations")).toBeVisible();
  await expect(page.getByText("Compromises and empty chairs")).toBeVisible();

  await page.locator("#view-floor").click();
  await expect(page.locator("#floor-preview")).toBeVisible();
  const firstSrc = await page.locator("#floor-preview").getAttribute("srcdoc");
  expect(firstSrc).toContain('data-zone-id="ground"');
  expect(firstSrc).toContain('data-group-id="registration:9"');
  await page.locator("#plan-floor-select").selectOption("first");
  const secondSrc = await page.locator("#floor-preview").getAttribute("srcdoc");
  expect(secondSrc).toContain('data-zone-id="first"');

  const pdfResponse = page.waitForResponse(response => response.url().endsWith("/v1/exports/table-cards/pdf"));
  await page.locator("#view-cards").click();
  expect((await pdfResponse).status()).toBe(200);
  await expect(page.locator("#cards-preview")).toHaveAttribute("src", /^blob:/);
  await expect(page.locator("#cards-per-page")).toHaveValue("1");
  const firstCardsUrl = await page.locator("#cards-preview").getAttribute("src");
  const fourResponse = page.waitForResponse(r => r.url().includes("/v1/exports/table-cards/pdf?cards_per_page=4"));
  await page.locator("#cards-per-page").selectOption("4");
  expect((await fourResponse).status()).toBe(200);
  await expect(page.locator("#cards-preview")).not.toHaveAttribute("src", firstCardsUrl);
  const twoResponse = page.waitForResponse(r => r.url().includes("/v1/exports/table-cards/pdf?cards_per_page=2"));
  await page.locator("#cards-per-page").selectOption("2");
  expect((await twoResponse).status()).toBe(200);
  await expect(page.locator("#cards-preview")).toHaveAttribute("src", /^blob:/);
  await page.locator("#cards-per-page").selectOption("1");

  await page.locator("#view-json").click();
  await expect(page.locator("pre").first()).toContainText('"score_breakdown"');
  await expect(page.locator("pre").first()).toContainText('"layout"');
  // Reload must restore the original plan, mapping, guests, capacities and rules.
  await page.reload();
  await expect(page.locator(".pill").first()).toContainText("120 guests");
  await expect(page.locator(".pill").nth(1)).toContainText("12 tables");
  await expect(page.locator(".pill").nth(2)).toContainText("3 rules");
  await expect(page.locator("#session-id")).toHaveValue("golden-ui-120");
  await expect(page.locator("pre").first()).toContainText('"score_breakdown"');
  await page.locator("#nav-import").click();
  await expect(page.locator("#map-guest-name")).toHaveValue("name");
  await page.locator("#nav-map").click();
  await page.locator("#floor-select").selectOption("ground");
  await expect(page.locator("#table-G-0-capacity")).toHaveValue("10");
  await page.locator("#nav-plan").click();
  await expect(page.getByText("Per-assignment explanations")).toBeVisible();
  expect(errors).toEqual([]);
  console.log("GOLDEN_UI_120 status=" + plan.status +
    " solver_seconds=" + plan.solve_seconds.toFixed(3) +
    " groups=" + plan.assignments.length +
    " floors=" + plan.layout.floors.length +
    " tables=" + plan.tables.length + " hard_violations=0");
});

test("single-floor venue and rules template prepared before import works in a new session", async ({ page }) => {
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="id"]').fill("hall");
  await page.locator('#floor-form input[name="name"]').fill("Main hall");
  await page.locator("#add-floor").click();
  await page.locator("#new-table-id").fill("H1");
  await page.locator("#new-table-capacity").fill("4");
  await page.locator("#add-table").click();
  await page.locator("#validate-layout").click();
  await expect(page.locator("#notice")).toContainText("Venue layout validated");
  await page.locator("#nav-rules").click();
  await page.locator("#new-rule-shape").selectOption("fill_efficiency");
  await page.locator("#add-rule").click();
  await page.locator("#nav-map").click();
  await page.locator("#template-name").fill("Hall dinner");
  await page.locator("#save-template").click();
  await expect(page.locator("#notice")).toContainText("Saved configuration template");
  await page.locator("#new-session").click();
  await page.locator("#nav-map").click();
  await page.locator("#template-select").selectOption("Hall dinner");
  await page.locator("#load-template").click();
  await expect(page.locator("#notice")).toContainText("Loaded template");
  await expect(page.locator("#table-H1-capacity")).toHaveValue("4");
  await expect(page.locator(".pill").nth(2)).toContainText("1 rules");
  await page.locator("#nav-import").click();
  await page.locator("#guest-file").setInputFiles({
    name: "one-hall.csv", mimeType: "text/csv",
    buffer: Buffer.from("Guest Name,Party Size\nAlpha,2\n")
  });
  await expect(page.locator("#map-guest-name")).toHaveValue("name");
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported 2 guests");
  await page.locator("#nav-plan").click();
  await page.locator("#solve-plan").click();
  await expect(page.locator("#notice")).toContainText("Solver returned");
  await expect(page.locator("pre").first()).toContainText("Table H1");
});

test("transient solve network failures show Retry and recover without losing the imported plan inputs", async ({ page }) => {
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="id"]').fill("hall");
  await page.locator('#floor-form input[name="name"]').fill("Main hall");
  await page.locator("#add-floor").click();
  await page.locator("#new-table-id").fill("T1");
  await page.locator("#new-table-capacity").fill("4");
  await page.locator("#add-table").click();
  await page.locator("#nav-import").click();
  await page.locator("#guest-file").setInputFiles({
    name: "retry.csv", mimeType: "text/csv",
    buffer: Buffer.from("Guest Name,Party Size\nAlice,2\n")
  });
  await expect(page.locator("#map-guest-name")).toHaveValue("name");
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported 2 guests");
  await page.locator("#nav-plan").click();
  let offline = true;
  await page.route("**/v1/solve", route => offline ? route.abort("failed") : route.continue());
  await page.locator("#solve-plan").click();
  await expect(page.locator("#notice")).toContainText("Could not reach the server");
  await expect(page.locator("#retry-action")).toBeVisible();
  await expect(page.locator("#notice")).not.toContainText("Failed to fetch");
  await expect(page.locator(".pill").first()).toContainText("2 guests");
  offline = false;
  await page.locator("#retry-action").click();
  await expect(page.locator("#notice")).toContainText("Solver returned");
  await expect(page.locator("pre").first()).toContainText("Table T1");
  await expect(page.locator("#retry-action")).toHaveCount(0);
  await page.unroute("**/v1/solve");
});

test("guest-side property preference seats wheelchair family at tagged table and credits guest need", async ({ page }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.locator("#nav-map").click();
  await page.locator('#floor-form input[name="id"]').fill("hall");
  await page.locator('#floor-form input[name="name"]').fill("Main hall");
  await page.locator("#add-floor").click();

  await page.locator("#new-table-id").fill("A");
  await page.locator("#new-table-capacity").fill("2");
  await page.locator("#new-table-properties").fill("accessible, aisle-edge");
  await page.locator("#add-table").click();
  await page.locator("#new-table-id").fill("B");
  await page.locator("#new-table-capacity").fill("2");
  await page.locator("#new-table-properties").fill("quiet");
  await page.locator("#add-table").click();

  await page.locator("#validate-layout").click();
  await expect(page.locator("#notice")).toContainText("Venue layout validated");
  await page.locator("#nav-import").click();
  await page.locator("#guest-file").setInputFiles({
    name: "needs.csv", mimeType: "text/csv",
    buffer: Buffer.from("Guest Name,Party Size,Mobility\nFamily,2,wheelchair\nVisitors,2,mobile\n")
  });
  await expect(page.locator("#map-mobility")).toHaveValue("attribute.mobility");
  await page.locator("#import-guests").click();
  await expect(page.locator("#notice")).toContainText("Imported 4 guests");

  await page.locator("#nav-rules").click();
  await page.locator("#new-rule-shape").selectOption("table_property_need");
  await page.locator("#add-rule").click();
  await page.locator("#rule-0-attribute").fill("mobility");
  await page.locator("#rule-0-attribute").blur();
  await page.locator("#rule-0-value").fill("wheelchair");
  await page.locator("#rule-0-value").blur();
  await page.locator("#rule-0-property").fill("accessible");
  await page.locator("#rule-0-property").blur();
  await page.locator("#rule-weight-0").fill("7");
  await page.locator("#rule-weight-0").blur();

  await page.locator("#nav-plan").click();
  const request = page.waitForRequest(req => req.url().endsWith("/v1/solve"));
  const response = page.waitForResponse(res => res.url().endsWith("/v1/solve"));
  await page.locator("#solve-plan").click();
  const payload = (await request).postDataJSON();
  expect(payload.tables.find(t => t.id === "A").properties).toEqual(["accessible", "aisle-edge"]);
  expect(payload.layout.floors[0].tables.find(t => t.table_id === "A").properties)
    .toEqual(["accessible", "aisle-edge"]);
  expect(payload.rules[0].shape).toBe("table_property_need");
  const solved = (await response).json();
  const plan = await solved;
  expect(plan.status).toMatch(/^(optimal|feasible)$/);
  const family = plan.assignments.find(assignment => assignment.group_id === "registration:2");
  expect(family.table_id).toBe("A");
  expect(family.guest_ids).toHaveLength(2);
  expect(plan.total_score).toBe(14);
  expect(plan.score_breakdown.find(item => item.rule_id === "rule-1").points).toBe(14);
  expect(family.reasons.some(reason => reason.rule_id === "rule-1" &&
    reason.description.includes("Guest need mobility=wheelchair") && reason.points === 14)).toBe(true);
  await expect(page.locator("#notice")).toContainText("Solver returned");
  await expect(page.locator(".reasons")).toContainText("Guest need mobility=wheelchair");
  expect(errors).toEqual([]);
});
