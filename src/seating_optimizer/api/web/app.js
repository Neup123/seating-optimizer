/* Phase 3: an API-driven visual client, with no seating or rule evaluation. */
const SVG_NS = "http://www.w3.org/2000/svg";
const SCREENS = [["import", "Guest import"], ["rules", "Rules"], ["map", "Venue map"], ["plan", "Seating plan"]];
const VIEWS = [["table", "Table view"], ["people", "People list"], ["people-floor", "People by floor"],
  ["groups", "Table list"], ["groups-table", "Per-table lists"],
  ["floor", "Floor maps"], ["cards", "Table cards"], ["json", "JSON plan"]];
const LIST_VIEWS = new Set(["people", "people-floor", "groups", "groups-table"]);
const SESSION_KEY = "seating-optimizer:session:v1";
const TEMPLATES_KEY = "seating-optimizer:templates:v1";
const SESSION_FIELDS = ["screen", "view", "importFile", "preview", "mapping", "importResult",
  "guests", "selectedShape", "rules", "nextRule", "zones", "tables", "layout",
  "focusedFloor", "sessionId", "seconds", "plan", "cardsPerPage", "includeReasons", "listFields", "notice", "error", "templateName", "templateSelected"];

function storedJSON(key, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch (_) { return fallback; }
}
function deepCopy(value) { return JSON.parse(JSON.stringify(value)); }


function element(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function append(parent, ...children) {
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) parent.append(child);
  }
  return parent;
}
function action(label, callback, className = "secondary", id) {
  const b = element("button", className, label);
  b.type = "button";
  if (id) b.id = id;
  b.addEventListener("click", callback);
  return b;
}
function textField(label, value, onChange, options = {}) {
  const holder = element("label", "field");
  holder.append(element("span", "", label));
  const field = document.createElement("input");
  field.type = options.type || "text";
  field.value = value === null || value === undefined ? "" : String(value);
  if (options.id) field.id = options.id;
  if (options.placeholder) field.placeholder = options.placeholder;
  if (options.min !== undefined) field.min = String(options.min);
  if (options.step !== undefined) field.step = String(options.step);
  if (options.required) field.required = true;
  field.addEventListener("change", () => onChange(field.value));
  holder.append(field);
  return holder;
}
function selectField(label, choices, current, onChange, options = {}) {
  const holder = element("label", "field");
  holder.append(element("span", "", label));
  const field = document.createElement("select");
  if (options.id) field.id = options.id;
  for (const candidate of choices) {
    const value = Array.isArray(candidate) ? candidate[0] : candidate;
    const title = Array.isArray(candidate) ? candidate[1] : candidate;
    const o = document.createElement("option");
    o.value = value;
    o.textContent = title;
    field.append(o);
  }
  field.value = String(current === null || current === undefined ? "" : current);
  field.addEventListener("change", () => onChange(field.value));
  holder.append(field);
  return holder;
}
function card(title, description) {
  const holder = element("section", "card");
  if (title) holder.append(element("h2", "", title));
  if (description) holder.append(element("p", "muted", description));
  return holder;
}
function row(...nodes) { return append(element("div", "row"), nodes); }
function grid(...nodes) { return append(element("div", "grid"), nodes); }
function issuesList(issues) {
  const holder = element("div", "stack");
  for (const issue of issues || []) {
    const d = element("div", "problem" + (issue.severity === "warning" ? " warning" : ""),
      (issue.row == null ? "File" : "Row " + issue.row) +
      (issue.column ? " · " + issue.column : "") + ": " + issue.message);
    holder.append(d);
  }
  return holder;
}
function safeNumber(input) {
  const number = Number(input);
  return Number.isFinite(number) ? number : NaN;
}
function patternCountError(value) {
  // Avoid Number("") === 0, fractional/negative values and implicit string coercion.
  const canonical = typeof value === "number" ? String(value) : value;
  if (typeof canonical === "string" && /^(0|[1-9][0-9]*)$/.test(canonical)) {
    const count = Number(canonical);
    if (Number.isSafeInteger(count) && count <= 100000) return "";
  }
  return "Enter a whole number from 0 to 100000 (no blanks or fractions).";
}
function parseTableProperties(input) {
  const tags = String(input || "").split(",").map(tag => tag.trim()).filter(Boolean);
  if (new Set(tags.map(tag => tag.toLocaleLowerCase())).size !== tags.length)
    throw Error("Table property names must be unique (case-insensitive).");
  return tags;
}
function encodeBytes(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  }
  return btoa(binary);
}
async function encodeFile(file) {
  if (!file || file.size > 10_000_000) throw Error("File must be smaller than 10 MB.");
  return encodeBytes(new Uint8Array(await file.arrayBuffer()));
}
function encodeText(text) { return encodeBytes(new TextEncoder().encode(text)); }

export function friendlyApiError(error) {
  const message = typeof error?.message === "string" ? error.message : String(error || "");
  if (error instanceof TypeError || /failed to fetch|fetch failed|networkerror|network request failed|load failed|err_name_not_resolved/i.test(message))
    return "Could not reach the server — check your connection and try again.";
  return message || "The server could not complete this request. Please try again.";
}

export function createGateway(fetcher = fetch) {
  async function request(path, options, resultType = "json") {
    let response;
    try { response = await fetcher(path, options); }
    catch (error) { throw Error(friendlyApiError(error), { cause: error }); }
    if (!response.ok) {
      let detail = await response.text();
      try { const parsed = JSON.parse(detail); detail = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail); }
      catch (_) { /* preserve human-readable HTTP error */ }
      throw Error(friendlyApiError(Error(detail || "Server returned HTTP " + response.status + ". Please try again.")));
    }
    return resultType === "blob" ? response.blob() :
      resultType === "text" ? response.text() : response.json();
  }
  return {
    get: (path) => request(path),
    post: (path, value, type = "json") => request(path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value)
    }, type)
  };
}

export function createApp(root, api = createGateway()) {
  function emptySession() {
    return {
      screen: "import", view: "table", viewContent: null, viewError: "",
      importFile: null, preview: null, mapping: {}, importResult: null, guests: [],
      catalog: null, selectedShape: "attribute_grouping", rules: [], nextRule: 1,
      zones: [], tables: [], layout: { floors: [] }, focusedFloor: "",
      sessionId: "meal-1", seconds: 5, plan: null, cardsPerPage: 1, includeReasons: false, listFields: [],
      notice: "Choose a CSV or XLSX guest list to begin.", error: false, retryAction: null,
      templateName: "", templateSelected: "", storageWarning: ""
    };
  }
  const state = emptySession();
  // Uncommitted invalid text stays visible through re-renders, but never enters rules.
  const invalidPatternDrafts = new WeakMap();
  const savedTemplates = storedJSON(TEMPLATES_KEY, []);
  const templates = Array.isArray(savedTemplates) ? savedTemplates : [];
  const previous = storedJSON(SESSION_KEY, null);
  if (previous?.version === 1 && previous.data && Array.isArray(previous.data.guests) &&
      Array.isArray(previous.data.rules) && Array.isArray(previous.data.tables) &&
      Array.isArray(previous.data.zones) && Array.isArray(previous.data.layout?.floors)) {
    for (const key of SESSION_FIELDS) {
      if (Object.hasOwn(previous.data, key)) state[key] = previous.data[key];
    }
    state.notice = "Restored your previous planning session.";
    state.error = false;
  }
  let viewObjectUrl = null;
  let listContentEndpoint = null;
  let working = false;
  let noticesIssued = 0;

  function hasInvalidStoredPatternCounts(rules) {
    return (rules || []).some(rule => rule.shape === "global_pattern" &&
      (!Array.isArray(rule.parameters?.conditions) ||
        rule.parameters.conditions.some(condition =>
          !condition || typeof condition.value !== "number" || patternCountError(condition.value))));
  }
  function assertValidPatternCounts() {
    const invalidDraft = state.rules.some(rule => rule.shape === "global_pattern" &&
      (rule.parameters?.conditions || []).some(condition => invalidPatternDrafts.has(condition)));
    if (invalidDraft || hasInvalidStoredPatternCounts(state.rules))
      throw Error("Fix the highlighted global-pattern count fields before saving or solving.");
  }

  function saveSession() {
    if (hasInvalidStoredPatternCounts(state.rules)) {
      state.storageWarning = "An invalid global-pattern count cannot be saved. Correct it on Rules.";
      return;
    }
    const data = {};
    for (const key of SESSION_FIELDS) data[key] = state[key];
    try {
      window.localStorage.setItem(SESSION_KEY, JSON.stringify({ version: 1, data }));
      state.storageWarning = "";
    } catch (_) {
      // Import source data can exceed the per-origin quota; retain all imported
      // guests, mapping, rules, layout and solution instead of losing the session.
      if (data.importFile?.content_base64) {
        data.importFile = { filename: data.importFile.filename };
        try {
          window.localStorage.setItem(SESSION_KEY, JSON.stringify({ version: 1, data }));
          state.storageWarning = "Source spreadsheet could not be cached. Re-select it to redo the import.";
          return;
        } catch (_) { /* even the smaller snapshot did not fit */ }
      }
      state.storageWarning = "Browser storage is unavailable or full; this session may not survive a reload.";
    }
  }
  function saveTemplates() {
    if (templates.some(template => hasInvalidStoredPatternCounts(template.rules)))
      throw Error("A template contains an invalid global-pattern count; correct it before saving.");
    try { window.localStorage.setItem(TEMPLATES_KEY, JSON.stringify(templates)); }
    catch (_) { throw Error("Cannot save templates: browser storage is unavailable or full. Export the configuration instead."); }
  }
  function configuration(name) {
    assertValidPatternCounts();
    if (!name) throw Error("Enter a configuration name.");
    if (!state.layout.floors.length || !state.tables.length)
      throw Error("Add a floor and at least one table before saving a configuration.");
    if (configuredTables().length !== state.tables.length)
      throw Error("All configured tables need a positive chair capacity.");
    return deepCopy({
      version: 1, name, zones: state.zones, tables: state.tables,
      layout: state.layout, rules: state.rules
    });
  }
  function applyConfiguration(config) {
    const copy = deepCopy(config);
    if (hasInvalidStoredPatternCounts(copy.rules))
      throw Error("Imported configuration contains an invalid global-pattern count.");
    state.zones = copy.zones;
    state.tables = copy.tables;
    state.layout = copy.layout;
    for (const floor of state.layout.floors) for (const drawing of floor.tables) {
      const table = state.tables.find(t => t.id === drawing.table_id);
      if (table && (Object.hasOwn(table, "small_group_priority") ||
          Object.hasOwn(drawing, "small_group_priority")))
        drawing.small_group_priority = Boolean(table.small_group_priority);
    }
    state.rules = copy.rules;
    state.nextRule = Math.max(1, ...state.rules.map(r => {
      const match = /^rule-(\d+)$/.exec(r.id);
      return match ? Number(match[1]) + 1 : 1;
    }));
    state.focusedFloor = state.layout.floors[0]?.zone_id || "";
    state.templateName = copy.name;
    invalidate();
  }
  function newSession() {
    const catalog = state.catalog;
    clearObjectUrl();
    Object.assign(state, emptySession(), { catalog });
    if (catalog?.shapes?.length) state.selectedShape = catalog.shapes[0].shape;
    announce("New empty session started. Saved configuration templates are still available.");
  }
  // Change handlers on inputs sometimes update state without re-rendering.
  root.addEventListener("change", saveSession);


  function announce(message, error = false) {
    noticesIssued += 1;
    state.notice = message;
    state.error = error;
    render();
  }
  async function attempt(task) {
    if (working) return;
    working = true;
    state.retryAction = null;
    const earlierNotices = noticesIssued;
    try {
      await task();
      // Downloads have no separate success notice, unlike a rejected import:
      // preserve explicit validation notices while clearing stale network errors.
      if (state.error && !state.retryAction && earlierNotices === noticesIssued)
        announce("Request completed successfully.", false);
    }
    catch (error) {
      state.retryAction = task;
      announce(friendlyApiError(error), true);
    }
    finally { working = false; }
  }
  function invalidate() { state.plan = null; state.viewContent = null; }
  function currentFloor() { return state.layout.floors.find(f => f.zone_id === state.focusedFloor); }
  function configuredTables() { return state.tables.filter(t => Number.isInteger(Number(t.capacity)) && Number(t.capacity) > 0); }
  function projectProblem() {
    assertValidPatternCounts();
    if (!state.guests.length) throw Error("Import valid guests before solving.");
    if (!state.tables.length || !state.zones.length) throw Error("Configure tables and floors before solving.");
    if (configuredTables().length !== state.tables.length) throw Error("Every table requires its own positive chair capacity.");
    return {
      session_id: state.sessionId,
      zones: state.zones.map(z => ({ id: z.id, name: z.name })),
      tables: state.tables.map(t => ({ id: t.id, zone_id: t.zone_id,
        capacity: Number(t.capacity), properties: [...(t.properties || [])],
        small_group_priority: Boolean(t.small_group_priority) })),
      guests: state.guests,
      rules: state.rules,
      config: { time_limit_seconds: Number(state.seconds), workers: 8, random_seed: 42 },
      layout: state.layout.floors.length ? state.layout : null
    };
  }
  function importColumnHeaders() {
    return new Map(Object.entries(state.mapping || {})
      .filter(([, target]) => typeof target === "string" && target.startsWith("attribute."))
      .map(([header, target]) => [target.slice("attribute.".length), header]));
  }
  function attributeLabel(key, importHeaders) {
    return importHeaders.get(key) || key.replace(/_+/g, " ").replace(/^./, char => char.toUpperCase());
  }
  function listEndpoint(view) {
    const people = view === "people" || view === "people-floor";
    const grouped = view === "people-floor" || view === "groups-table";
    const by = people ? (grouped ? "floor" : "combined") : (grouped ? "table" : "combined");
    const available = new Set((state.plan?.assignments || []).flatMap(
      entry => (entry.guest_attributes || []).flatMap(attrs => Object.keys(attrs))));
    const query = new URLSearchParams({group_by: by, include_reasons: String(Boolean(state.includeReasons))});
    const importHeaders = people ? importColumnHeaders() : null;
    for (const field of (state.listFields || [])) if (available.has(field)) {
      query.append("fields", field);
      if (people) query.append("field_labels", attributeLabel(field, importHeaders));
    }
    return "/v1/exports/" + (people ? "people-list" : "table-list") + "/html?" + query.toString();
  }
  function tableCardsEndpoint() {
    return "/v1/exports/table-cards/pdf" +
      (state.cardsPerPage === 1 ? "" : "?cards_per_page=" + state.cardsPerPage);
  }
  function clearObjectUrl() {
    if (viewObjectUrl && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(viewObjectUrl);
    viewObjectUrl = null;
  }
  function downloadBlob(data, name, type) {
    const blob = data instanceof Blob ? data : new Blob([data], { type });
    if (typeof URL.createObjectURL !== "function") throw Error("File downloads are unavailable in this browser.");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name;
    document.body.append(a);
    a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
  function drawHeader() {
    const sidebar = element("aside", "sidebar");
    const brand = element("div", "brand", "Seating Plan Optimizer");
    brand.append(element("span", "", "Event meal planning"));
    sidebar.append(brand);
    const nav = element("nav", "nav");
    nav.setAttribute("aria-label", "Workflow screens");
    SCREENS.forEach(([screen, name], index) => {
      const b = action("", () => { state.screen = screen; render(); }, "");
      b.append(element("span", "step", "0" + (index + 1)), element("span", "", name));
      b.id = "nav-" + screen;
      if (state.screen === screen) b.setAttribute("aria-current", "page");
      nav.append(b);
    });
    sidebar.append(nav, element("p", "side-note",
      "All assignments and printable exports are produced by the REST API. No seating rules execute in the browser."));
    return sidebar;
  }
  function render() {
    if (state.screen === "plan" && LIST_VIEWS.has(state.view) &&
        typeof state.viewContent === "string" &&
        listContentEndpoint !== listEndpoint(state.view)) {
      void loadView(state.view);
      return;
    }
    saveSession();
    root.replaceChildren();
    const shell = element("div", "shell");
    shell.append(drawHeader());
    const main = element("main", "workspace");
    const header = element("div", "topline");
    const text = element("div");
    const title = SCREENS.find(([screen]) => screen === state.screen)?.[1] || "Seating Plan";
    text.append(element("h1", "", title), element("p", "", "Build, optimize and review a seating session"));
    const stats = element("div", "stats");
    stats.append(element("span", "pill", state.guests.length + " guests"),
      element("span", "pill", state.tables.length + " tables"),
      element("span", "pill", state.rules.length + " rules"));
    header.append(text, stats);
    main.append(header);
    main.append(row(action("New empty session", newSession, "danger small", "new-session")));
    if (state.storageWarning) main.append(element("p", "problem", state.storageWarning));
    const notice = element("div", "notice" + (state.error ? " error" : ""), state.notice);
    notice.setAttribute("role", "status");
    notice.id = "notice";
    main.append(notice);
    if (state.error && state.retryAction) {
      main.append(row(action("Retry failed action", () => attempt(state.retryAction),
        "primary", "retry-action")));
    }
    if (state.screen === "import") main.append(renderImport());
    else if (state.screen === "rules") main.append(renderRules());
    else if (state.screen === "map") main.append(renderMap());
    else main.append(renderPlan());
    shell.append(main);
    root.append(shell);
  }

  function renderImport() {
    const area = element("div", "form-measure import-flow");
    const form = card("Upload guest registrations", "CSV or XLSX. The server detects headers; you can override every column before importing.");
    const fileLabel = element("label", "");
    fileLabel.append(element("span", "", "Guest list spreadsheet"));
    const file = document.createElement("input");
    file.type = "file"; file.id = "guest-file"; file.accept = ".csv,.xlsx";
    file.addEventListener("change", async () => attempt(async () => {
      const selected = file.files && file.files[0];
      if (!selected) return;
      const base64 = await encodeFile(selected);
      const uploaded = { filename: selected.name, content_base64: base64 };
      const preview = await api.post("/v1/import/preview", uploaded);
      state.importFile = uploaded;
      state.preview = preview;
      state.mapping = { ...preview.mapping };
      state.importResult = null;
      state.guests = [];
      invalidate();
      announce("Header preview loaded. Review the mapping and import the guests.");
    }));
    fileLabel.append(file);
    form.append(fileLabel);
    if (state.importFile) form.append(element("p", "muted", "Selected: " + state.importFile.filename));
    area.append(form);
    if (!state.preview) return area;

    const mappingCard = card("Map columns", "Automatic matches are preselected. Choose a target or enter any custom attribute key. Unmapped columns are preserved under their original header.");
    const choices = [["", "Unmapped (preserve as attribute)"],
      ["name", "Guest / registration name"], ["size", "Party size"],
      ["group_id", "Group ID"], ["attribute.language", "Attribute: language"],
      ["attribute.age_layer", "Attribute: age layer"],
      ["attribute.mobility", "Attribute: mobility"], ["custom", "Custom attribute..."]];
    const sheet = element("div", "table-scroll");
    const table = document.createElement("table");
    const head = element("thead");
    const tr = element("tr");
    ["Source column", "Target field", "Preview value"].forEach(t => tr.append(element("th", "", t)));
    head.append(tr); table.append(head);
    const body = element("tbody");
    state.preview.headers.forEach(header => {
      const rowEl = element("tr");
      rowEl.append(element("td", "", header));
      const cell = element("td");
      const value = state.mapping[header] || "";
      const selected = choices.some(choice => choice[0] === value) ? value :
                       value.startsWith("attribute.") ? "custom" : "";
      const sel = selectField("Mapping for " + header, choices, selected, next => {
        if (next === "custom") state.mapping[header] = "attribute.custom";
        else if (!next) delete state.mapping[header];
        else state.mapping[header] = next;
        render();
      }, { id: "map-" + header.replace(/[^a-z0-9]+/gi, "-").toLowerCase() });
      cell.append(sel);
      if (selected === "custom") {
        const custom = textField("Attribute key", value.startsWith("attribute.") ?
          value.slice(10) : "", next => { state.mapping[header] = "attribute." + next; }, {
          id: "custom-" + header.replace(/[^a-z0-9]+/gi, "-").toLowerCase()
        });
        cell.append(custom);
      }
      rowEl.append(cell, element("td", "sample", state.preview.sample_rows[0]?.[header] || "—"));
      body.append(rowEl);
    });
    table.append(body); sheet.append(table); mappingCard.append(sheet);
    const buttons = row(action("Review corrected mapping", () => attempt(async () => {
      if (!state.importFile?.content_base64) throw Error("Re-select the spreadsheet to review its mapping.");
      state.preview = await api.post("/v1/import/preview", { ...state.importFile, mapping: state.mapping, header_aliases: {} });
      announce("Mapping checked by the API. Review any row-level issues below.");
    }), "secondary", "preview-mapping"), action("Import guests", () => attempt(async () => {
      if (!state.importFile?.content_base64) throw Error("Re-select the spreadsheet to import guests again.");
      const result = await api.post("/v1/import", { ...state.importFile, mapping: state.mapping, header_aliases: {} });
      state.importResult = result;
      if (result.issues.some(i => i.severity === "error")) {
        state.guests = [];
        invalidate();
        announce("Import blocked: fix the reported errors. No rows were silently accepted.", true);
      } else {
        state.guests = result.guests;
        invalidate();
        announce("Imported " + result.guests.length + " guests from " + result.rows_imported + " registrations.");
      }
    }), "primary", "import-guests"));
    mappingCard.append(buttons);
    area.append(mappingCard);
    if (state.preview.issues?.length || state.importResult?.issues?.length) {
      const problems = card("Validation diagnostics", "Every import error and warning stays visible for correction.");
      problems.append(issuesList(state.importResult ? state.importResult.issues : state.preview.issues));
      area.append(problems);
    }
    if (state.preview.sample_rows?.length) {
      const sample = card("Spreadsheet sample", "First rows as parsed by the API.");
      const wrap = element("div", "table-scroll");
      const table2 = document.createElement("table");
      const h2 = element("tr");
      state.preview.headers.forEach(h => h2.append(element("th", "", h)));
      table2.append(append(element("thead"), h2));
      const body2 = element("tbody");
      state.preview.sample_rows.forEach(entry => {
        const r = element("tr");
        state.preview.headers.forEach(h => r.append(element("td", "", entry[h])));
        body2.append(r);
      });
      table2.append(body2); wrap.append(table2); sample.append(wrap); area.append(sample);
    }
    if (state.importResult && !state.importResult.issues.some(i => i.severity === "error")) {
      area.append(append(card("Import complete"), element("p", "counter", state.guests.length + " guests are ready for optimization.")));
    }
    return area;
  }

  function defaultRuleParameters(spec) {
    const params = {};
    spec.fields.forEach(f => {
      if (f.kind === "select" && f.choices.length) params[f.name] = f.choices[0];
    });
    if (spec.shape === "global_pattern") {
      // Editable lonely-last-seat example: a rule configuration, not a new solver branch.
      params.scope = "global";
      params.enabled = false;
      params.conditions = [
        { fact: "groups_at_table", op: "==", value: 1 },
        { fact: "empty_seats", op: "==", value: 1 }
      ];
    }
    return params;
  }

  function renderPatternEditor(rule, index) {
    const panel = element("div", "pattern-editor");
    panel.append(element("p", "muted",
      "Scope: whole plan · All comparisons are AND clauses, evaluated per table. " +
      "Every matching table earns or loses the selected weight."));
    const facts = [
      ["groups_at_table", "Number of groups at table"],
      ["occupied_seats", "Occupied seats at table"],
      ["empty_seats", "Empty seats at table"]
    ];
    const operators = [
      ["==", "equals"], ["!=", "does not equal"], ["<", "less than"],
      ["<=", "at most"], [">", "greater than"], [">=", "at least"]
    ];
    const conditions = Array.isArray(rule.parameters.conditions) ? rule.parameters.conditions : [];
    conditions.forEach((condition, j) => {
      const clause = element("div", "pattern-clause");
      clause.append(selectField("Table fact", facts, condition.fact, value => {
        condition.fact = value; invalidate();
      }, { id: "rule-" + index + "-pattern-" + j + "-fact" }));
      clause.append(selectField("Comparison", operators, condition.op, value => {
        condition.op = value; invalidate();
      }, { id: "rule-" + index + "-pattern-" + j + "-op" }));
      const id = "rule-" + index + "-pattern-" + j + "-value";
      const countLabel = element("label", "field");
      countLabel.append(element("span", "", "Count"));
      const input = document.createElement("input");
      // Text preserves invalid characters so the user can see and correct them.
      input.type = "text";
      input.inputMode = "numeric";
      input.id = id;
      const draft = invalidPatternDrafts.get(condition);
      input.value = draft === undefined ? String(condition.value ?? "") : draft;
      const error = element("span", "field-error");
      error.id = id + "-error";
      error.setAttribute("role", "alert");
      input.setAttribute("aria-describedby", error.id);
      function setError(message) {
        error.textContent = message;
        error.hidden = !message;
        if (message) input.setAttribute("aria-invalid", "true");
        else input.removeAttribute("aria-invalid");
      }
      setError(draft === undefined && typeof condition.value !== "number"
        ? "Saved count must be a whole number. Re-enter it."
        : patternCountError(input.value));
      function acceptCount() {
        const message = patternCountError(input.value);
        if (message) invalidPatternDrafts.set(condition, input.value);
        else {
          condition.value = Number(input.value);
          invalidPatternDrafts.delete(condition);
        }
        setError(message);
        invalidate();
        saveSession(); // Valid edits are immediate; invalid text never enters persisted rules.
      }
      input.addEventListener("input", acceptCount);
      input.addEventListener("change", acceptCount);
      countLabel.append(input, error);
      clause.append(countLabel);
      clause.append(action("Remove comparison", () => {
        if (conditions.length === 1) return announce("A pattern requires at least one comparison.", true);
        conditions.splice(j, 1);
        invalidate(); render();
      }, "danger small", "rule-" + index + "-remove-pattern-" + j));
      panel.append(clause);
    });
    panel.append(action("Add comparison", () => {
      if (conditions.length >= 8) return announce("Patterns support up to eight comparisons.", true);
      if (!Array.isArray(rule.parameters.conditions)) rule.parameters.conditions = [];
      rule.parameters.conditions.push({ fact: "occupied_seats", op: ">=", value: 1 });
      invalidate(); render();
    }, "secondary small", "rule-" + index + "-add-pattern"));
    return panel;
  }

  function renderRules() {
    const area = element("div", "form-measure rules-flow");
    const form = card("Build consideration rules", "All shapes and their fields come from the API catalog. Rule records, modes and positive weights are sent unchanged to CP-SAT.");
    if (!state.catalog) {
      form.append(element("p", "problem", "Rule catalog is unavailable. Use Retry above."));
      return append(area, form);
    }
    const shapes = state.catalog.shapes;
    const newRuleForm = element("fieldset", "new-rule-form");
    newRuleForm.append(element("legend", "", "Add a new consideration — select its type first"));
    const chosenShape = shapes.find(s => s.shape === state.selectedShape) || shapes[0];
    newRuleForm.append(selectField("Step 1 — Type of the rule you want to create",
      shapes.map(s => [s.shape, s.title]), chosenShape.shape,
      next => { state.selectedShape = next; render(); }, { id: "new-rule-shape" }));
    newRuleForm.append(element("p", "muted", chosenShape.description ||
      "Choose a type to see the new rule's fields."));
    newRuleForm.append(action("Step 2 — Add " + chosenShape.title + " rule", () => {
      const spec = shapes.find(s => s.shape === state.selectedShape);
      const parameters = defaultRuleParameters(spec);
      state.rules.push({
        id: "rule-" + state.nextRule++, shape: spec.shape, mode: spec.default_mode,
        weight: spec.default_mode === "soft" ? spec.default_weight : null, parameters
      });
      invalidate();
      announce("Added a " + spec.title + " rule. Set its parameters below.");
    }, "primary", "add-rule"));
    newRuleForm.append(element("p", "muted",
      "Step 1 sets the NEW rule's type only. Existing rules below have their own type control."));
    form.append(newRuleForm);
    area.append(form);
    if (!state.rules.length) {
      area.append(append(card("No considerations yet"), element("p", "muted",
        "Add grouping, zone restrictions, pair preferences, capacity, fill efficiency, or locked assignments.")));
    }
    state.rules.forEach((rule, i) => {
      const spec = shapes.find(s => s.shape === rule.shape);
      const section = card(spec?.title || rule.shape, spec?.description);
      section.setAttribute("data-rule-id", rule.id);
      const header = element("div", "row between");
      header.append(element("span", "badge", rule.shape));
      header.append(action("Remove rule", () => {
        state.rules.splice(i, 1); invalidate(); announce("Rule removed.");
      }, "danger small", "delete-rule-" + i));
      section.append(header);
      section.append(selectField("Type of this existing rule (changing resets its fields)",
        shapes.map(s => [s.shape, s.title]), rule.shape, value => {
          if (value === rule.shape) return;
          const nextSpec = shapes.find(s => s.shape === value);
          const parameters = defaultRuleParameters(nextSpec);
          rule.shape = nextSpec.shape;
          rule.mode = nextSpec.default_mode;
          rule.weight = nextSpec.default_mode === "soft" ? nextSpec.default_weight : null;
          rule.parameters = parameters;
          invalidate();
          render();
        }, { id: "rule-shape-" + i }));
      section.append(grid(
        textField("Rule ID", rule.id, value => { rule.id = value; invalidate(); }, { id: "rule-id-" + i, required: true }),
        selectField(rule.shape === "table_property_need" ? "Guest need: require or prefer" : "Hard or weighted",
          spec.modes.map(m => [m,
            rule.shape === "table_property_need"
              ? (m === "hard" ? "Require (hard)" : "Prefer (soft, weighted per affected guest)")
              : (m === "hard" ? "HARD (cannot violate)" : "Soft (weighted points)")]),
          rule.mode, value => {
            rule.mode = value;
            rule.weight = value === "soft" ? (spec.default_weight || 1) : null;
            invalidate(); render();
          }, { id: "rule-mode-" + i }),
        rule.mode === "soft"
          ? textField("Points weight", rule.weight, value => { rule.weight = Number(value); invalidate(); },
              { type: "number", min: 1, step: 1, id: "rule-weight-" + i })
          : element("p", "muted", "HARD — no weight")
      ));
      const fields = element("div", "grid three");
      if (rule.shape === "global_pattern") {
        const label = element("label", "field pattern-enabled-choice");
        const enabled = document.createElement("input");
        enabled.type = "checkbox";
        enabled.id = "rule-pattern-enabled-" + i;
        enabled.checked = rule.parameters.enabled === true;
        enabled.addEventListener("change", () => {
          rule.parameters.enabled = enabled.checked;
          invalidate();
        });
        label.append(enabled, element("span", "", "Enable global pattern (default off)"));
        fields.append(label);
      }
      spec.fields.forEach(field => {
        const original = rule.parameters[field.name] || "";
        const update = value => {
          if (value === "") delete rule.parameters[field.name];
          else rule.parameters[field.name] = value;
          invalidate();
        };
        if (field.kind === "pattern") fields.append(renderPatternEditor(rule, i));
        else if (field.kind === "select") fields.append(selectField(field.label,
          field.choices, original, update, { id: "rule-" + i + "-" + field.name }));
        else if (field.kind === "zone") fields.append(selectField(field.label,
          [["", "Select zone"], ...state.zones.map(z => [z.id, z.name])], original, update,
          { id: "rule-" + i + "-" + field.name }));
        else if (field.kind === "table") fields.append(selectField(field.label,
          [["", "Select table"], ...state.tables.map(t => [t.id, t.id + " (" + t.zone_id + ")"])],
          original, update, { id: "rule-" + i + "-" + field.name }));
        else if (field.kind === "target") {
          const list = [[ "", "Select guest or group" ]];
          const seen = new Set();
          state.guests.forEach(g => {
            const val = g.group_id || g.id;
            if (!seen.has(val)) { seen.add(val); list.push([val, val]); }
          });
          fields.append(selectField(field.label, list, original, update,
            { id: "rule-" + i + "-" + field.name }));
        } else fields.append(textField(field.label, original, update,
          { id: "rule-" + i + "-" + field.name, required: field.required }));
      });
      section.append(fields);
      area.append(section);
    });
    return area;
  }

  async function validateLayout() {
    if (!state.layout.floors.length) throw Error("Add or import at least one floor.");
    if (configuredTables().length !== state.tables.length) throw Error("Set every table's chair capacity before validating.");
    const request = {
      files: [{ filename: "edited-layout.json", content_base64: encodeText(JSON.stringify(state.layout)) }],
      zones: state.zones, tables: state.tables.map(t => ({ ...t, capacity: Number(t.capacity) }))
    };
    const validated = await api.post("/v1/layouts/import", request);
    state.layout = validated;
    invalidate();
    announce("Venue layout validated by the API. Positions and shapes are ready for printing.");
  }
  async function loadLayoutFiles(files) {
    const encoded = [];
    for (const file of files) encoded.push({ filename: file.name, content_base64: await encodeFile(file) });
    const imported = await api.post("/v1/layouts/import", { files: encoded });
    state.layout = imported;
    for (const floor of imported.floors) {
      if (!state.zones.some(z => z.id === floor.zone_id))
        state.zones.push({ id: floor.zone_id, name: floor.zone_id });
      for (const drawing of floor.tables) {
        const old = state.tables.find(t => t.id === drawing.table_id);
        if (old && old.zone_id !== floor.zone_id)
          throw Error("Table " + drawing.table_id + " is assigned to a different floor.");
        // Layout JSON carries portable tags; Table.properties is the solver input.
        // Synchronize both copies without assigning tag weights.
        if (old) {
          old.properties = [...(drawing.properties || [])];
          old.small_group_priority = Boolean(drawing.small_group_priority);
        } else state.tables.push({
          id: drawing.table_id, zone_id: floor.zone_id, capacity: null,
          properties: [...(drawing.properties || [])],
          small_group_priority: Boolean(drawing.small_group_priority)
        });
      }
    }
    state.focusedFloor = imported.floors[0].zone_id;
    invalidate();
    announce("Layout imported. Set chair capacities and validate the venue before solving.");
  }

  function renderMap() {
    const area = element("div");
    const templatesCard = card("Reusable venue + rules configurations",
      "Prepare a layout, capacities and rules before importing guests. Named templates are saved in this browser; JSON files are portable. Saving an existing name updates that template.");
    templatesCard.classList.add("form-measure");
    templatesCard.append(textField("Configuration name", state.templateName, value => {
      state.templateName = value;
    }, { id: "template-name", placeholder: "e.g. Weekly dinner" }));
    templatesCard.append(row(
      action("Save / update template", () => attempt(async () => {
        const name = document.getElementById("template-name").value.trim();
        const validated = await api.post("/v1/configurations/validate", configuration(name));
        const index = templates.findIndex(t => t.name === name);
        const oldValue = index < 0 ? null : templates[index];
        if (index < 0) templates.push(validated);
        else templates[index] = validated;
        try { saveTemplates(); } catch (error) {
          if (index < 0) templates.pop();
          else templates[index] = oldValue;
          throw error;
        }
        state.templateSelected = name;
        announce((index < 0 ? "Saved" : "Updated") + " configuration template: " + name);
      }), "primary", "save-template"),
      action("Export full configuration JSON", () => attempt(async () => {
        const name = document.getElementById("template-name").value.trim() || "Venue configuration";
        const validated = await api.post("/v1/configurations/validate", configuration(name));
        downloadBlob(JSON.stringify(validated, null, 2), "venue-configuration.json", "application/json");
        announce("Exported the complete venue, capacities and rules.");
      }), "secondary", "export-configuration")
    ));
    templatesCard.append(selectField("Saved templates",
      [["", "Choose saved template"], ...templates.map(t => [t.name, t.name])],
      state.templateSelected, value => { state.templateSelected = value; }, { id: "template-select" }));
    templatesCard.append(row(
      action("Load template", () => attempt(async () => {
        const found = templates.find(t => t.name === state.templateSelected);
        if (!found) throw Error("Choose a saved configuration template.");
        const validated = await api.post("/v1/configurations/validate", found);
        applyConfiguration(validated);
        announce("Loaded template " + found.name + ". Import guests whenever ready.");
      }), "secondary", "load-template"),
      action("Duplicate template", () => attempt(async () => {
        const found = templates.find(t => t.name === state.templateSelected);
        if (!found) throw Error("Choose a template to duplicate.");
        let name = found.name + " (copy)";
        for (let number = 2; templates.some(t => t.name === name); number++)
          name = found.name + " (copy " + number + ")";
        const copy = deepCopy(found);
        copy.name = name;
        templates.push(copy);
        try { saveTemplates(); } catch (error) { templates.pop(); throw error; }
        state.templateSelected = name;
        announce("Duplicated template as " + name);
      }), "secondary", "duplicate-template"),
      action("Delete template", () => attempt(async () => {
        const index = templates.findIndex(t => t.name === state.templateSelected);
        if (index === -1) throw Error("Choose a template to delete.");
        const [removed] = templates.splice(index, 1);
        try { saveTemplates(); } catch (error) { templates.splice(index, 0, removed); throw error; }
        state.templateSelected = "";
        announce("Deleted saved template " + removed.name + ".");
      }), "danger small", "delete-template")
    ));
    const importLabel = element("label", "field");
    importLabel.append(element("span", "", "Import full configuration JSON"));
    const configFile = document.createElement("input");
    configFile.id = "configuration-file";
    configFile.type = "file";
    configFile.accept = ".json,application/json";
    configFile.addEventListener("change", () => attempt(async () => {
      const file = configFile.files?.[0];
      if (!file) return;
      if (file.size > 2_000_000) throw Error("Configuration JSON must be smaller than 2 MB.");
      const incoming = JSON.parse(await file.text());
      const validated = await api.post("/v1/configurations/validate", incoming);
      applyConfiguration(validated);
      announce("Imported complete configuration " + validated.name + ".");
    }));
    templatesCard.append(append(importLabel, configFile));
    area.append(templatesCard);
    const intro = card("Floor layout editor", "Create numbered tables, drag them within a floor, or import structured JSON / annotated SVG drafts. Add passive table tags (accessible, aisle-edge, quiet) to match guest needs — tags carry no score by themselves.");
    intro.classList.add("form-measure");
    const file = document.createElement("input");
    file.type = "file"; file.id = "layout-file"; file.accept = ".json,.svg"; file.multiple = true;
    file.addEventListener("change", () => attempt(async () => {
      if (file.files?.length) await loadLayoutFiles(Array.from(file.files));
    }));
    intro.append(append(element("label", "", ""), element("span", "", "Import venue layout files"), file));
    intro.append(row(
      action("Validate layout", () => attempt(validateLayout), "primary", "validate-layout"),
      action("Export layout JSON", () => attempt(async () => {
        const validated = await api.post("/v1/layouts/import", {
          files: [{ filename: "layout.json", content_base64: encodeText(JSON.stringify(state.layout)) }]
        });
        downloadBlob(JSON.stringify(validated, null, 2), "venue-layout.json", "application/json");
      }), "secondary", "export-layout")
    ));
    area.append(intro);
    const floorForm = card("Add floor", "Zones identify the floor for solver restrictions and printable pages.");
    floorForm.classList.add("form-measure");
    const addFloor = element("form", "grid three");
    addFloor.id = "floor-form";
    const inputs = {};
    [["id", "Floor ID", "ground"], ["name", "Floor name", "Ground floor"],
     ["width", "Canvas width", "700"], ["height", "Canvas height", "450"]].forEach(([key,label,placeholder]) => {
      const input = document.createElement("input");
      input.name = key; input.placeholder = placeholder; input.required = true;
      input.type = key === "width" || key === "height" ? "number" : "text";
      if (input.type === "number") { input.min = "1"; input.value = placeholder; }
      inputs[key] = input;
      addFloor.append(append(element("label"), element("span", "", label), input));
    });
    const submit = element("button", "primary", "Create floor");
    submit.type = "submit"; submit.id = "add-floor";
    addFloor.append(submit);
    addFloor.addEventListener("submit", event => {
      event.preventDefault();
      const id = inputs.id.value.trim();
      if (!id || state.zones.some(z => z.id === id)) return announce("Floor ID must be unique and nonempty.", true);
      const width = safeNumber(inputs.width.value), height = safeNumber(inputs.height.value);
      if (!(width > 0 && height > 0)) return announce("Floor dimensions must be positive.", true);
      state.zones.push({ id, name: inputs.name.value.trim() || id });
      state.layout.floors.push({ zone_id: id, width, height, tables: [] });
      state.focusedFloor = id;
      invalidate(); announce("Floor " + id + " added.");
    });
    floorForm.append(addFloor); area.append(floorForm);

    if (!state.layout.floors.length) {
      area.append(element("div", "empty", "No floors yet. Create one or import structured layout files."));
      return area;
    }
    if (!currentFloor()) state.focusedFloor = state.layout.floors[0].zone_id;
    const layout = currentFloor();
    const panel = card("Edit tables on " + (state.zones.find(z => z.id === layout.zone_id)?.name || layout.zone_id),
      "Drag a numbered shape to reposition it, or edit exact geometry and table chair count below.");
    panel.append(selectField("Floor", state.layout.floors.map(f => [f.zone_id,
      state.zones.find(z => z.id === f.zone_id)?.name || f.zone_id]),
      state.focusedFloor, value => { state.focusedFloor = value; render(); }, { id: "floor-select" }));

    const split = element("div", "map-layout");
    const canvas = element("div", "map-canvas");
    canvas.append(makeEditorSvg(layout));
    split.append(canvas);
    const controls = element("div");
    const tableForm = element("form", "stack");
    tableForm.id = "table-form";
    tableForm.append(element("h3", "", "Add numbered table"));
    const idInput = textField("Table ID", "", () => {}, { id: "new-table-id", required: true });
    const capacityInput = textField("Chair count", "10", () => {}, { id: "new-table-capacity", type: "number", min: 1, step: 1 });
    const shapeInput = selectField("Shape", ["rectangle", "ellipse", "circle"], "rectangle", () => {}, { id: "new-table-shape" });
    const propertyInput = textField("Table tags (comma-separated)", "", () => {},
      { id: "new-table-properties", placeholder: "accessible, aisle-edge" });
    const priorityLabel = element("label", "field");
    const priorityInput = document.createElement("input");
    priorityInput.type = "checkbox"; priorityInput.id = "new-table-small-priority";
    priorityLabel.append(priorityInput, element("span", "", "Priority for couples and singles (soft)"));
    tableForm.append(grid(idInput, capacityInput, shapeInput), propertyInput, priorityLabel);
    const create = element("button", "secondary", "Add table to floor"); create.type = "submit"; create.id = "add-table";
    tableForm.append(create);
    tableForm.addEventListener("submit", event => {
      event.preventDefault();
      const id = tableForm.querySelector("#new-table-id").value.trim();
      const capacity = Number(tableForm.querySelector("#new-table-capacity").value);
      const shape = tableForm.querySelector("#new-table-shape").value;
      let properties;
      try { properties = parseTableProperties(tableForm.querySelector("#new-table-properties").value); }
      catch (error) { return announce(error.message, true); }
      if (!id || state.tables.some(t => t.id === id)) return announce("Each table requires a unique ID.", true);
      if (!Number.isInteger(capacity) || capacity < 1) return announce("Chair capacity must be a positive integer.", true);
      const width = Math.min(160, layout.width / 2);
      const height = shape === "circle" ? width : Math.min(125, layout.height / 2);
      const x = 8 + (layout.tables.length % 3) * 14;
      const y = 8 + (layout.tables.length % 3) * 14;
      if (x + width > layout.width || y + height > layout.height) return announce("Canvas too small for a new table.", true);
      const small_group_priority = priorityInput.checked;
      state.tables.push({ id, zone_id: layout.zone_id, capacity, properties, small_group_priority });
      layout.tables.push({ table_id: id, x, y, width, height, shape,
        properties: [...properties], small_group_priority });
      invalidate(); announce("Added table " + id + " with " + capacity + " chairs.");
    });
    controls.append(tableForm);
    const list = element("div", "stack");
    list.append(element("h3", "", "Tables on this floor"));
    for (const drawing of layout.tables) {
      const table = state.tables.find(t => t.id === drawing.table_id);
      const editor = element("form", "table-editor");
      editor.dataset.tableId = drawing.table_id;
      editor.append(element("h3", "", drawing.table_id));
      const fields = element("div", "grid three");
      const definitions = [
        ["capacity", "Chairs", table?.capacity, 1],
        ["x", "X", drawing.x, 0], ["y", "Y", drawing.y, 0],
        ["width", "Width", drawing.width, 1], ["height", "Height", drawing.height, 1]
      ];
      for (const [key, label, value, min] of definitions) {
        const f = textField(label, value, () => {}, {
          type: "number", step: key === "capacity" ? 1 : "any",
          min, id: "table-" + drawing.table_id + "-" + key
        });
        fields.append(f);
      }
      fields.append(selectField("Shape", ["rectangle", "ellipse", "circle"], drawing.shape,
        () => {}, { id: "table-" + drawing.table_id + "-shape" }));
      editor.append(fields, textField("Table tags (comma-separated)",
        (table?.properties || drawing.properties || []).join(", "), () => {},
        { id: "table-" + drawing.table_id + "-properties" }));
      const priorityLabel = element("label", "field");
      const priorityInput = document.createElement("input");
      priorityInput.type = "checkbox";
      priorityInput.id = "table-" + drawing.table_id + "-small-priority";
      priorityInput.checked = Boolean(table?.small_group_priority);
      priorityLabel.append(priorityInput, element("span", "",
        "Priority for couples and singles (soft)"));
      editor.append(priorityLabel);
      const save = element("button", "secondary small", "Apply dimensions");
      save.type = "submit";
      const remove = action("Remove table", () => {
        layout.tables = layout.tables.filter(d => d.table_id !== drawing.table_id);
        state.tables = state.tables.filter(t => t.id !== drawing.table_id);
        invalidate(); announce("Removed table " + drawing.table_id + ".");
      }, "danger small");
      editor.append(row(save, remove));
      editor.addEventListener("submit", event => {
        event.preventDefault();
        const next = {};
        for (const [key] of definitions) {
          const val = editor.querySelector('[id="table-' + drawing.table_id + "-" + key + '"]').value;
          next[key] = Number(val);
        }
        if (["x","y","width","height"].some(k => !Number.isFinite(next[k])))
          return announce("Table drawing coordinates must be finite numbers.", true);
        if (!Number.isInteger(next.capacity) || next.capacity < 1)
          return announce("Chair capacity must be a positive integer.", true);
        let properties;
        try {
          properties = parseTableProperties(editor.querySelector(
            '[id="table-' + drawing.table_id + '-properties"]').value);
        } catch (error) { return announce(error.message, true); }
        table.capacity = next.capacity;
        table.properties = properties;
        table.small_group_priority = priorityInput.checked;
        drawing.properties = [...properties];
        drawing.small_group_priority = priorityInput.checked;
        ["x", "y", "width", "height"].forEach(k => drawing[k] = next[k]);
        drawing.shape = editor.querySelector('[id="table-' + drawing.table_id + '-shape"]').value;
        invalidate(); announce("Updated table " + drawing.table_id + ". Use Validate layout to check geometry.");
      });
      list.append(editor);
    }
    controls.append(list);
    split.append(controls); panel.append(split); area.append(panel);
    return area;
  }

  function makeEditorSvg(floor) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + floor.width + " " + floor.height);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Interactive table layout for " + floor.zone_id);
    svg.id = "map-editor-svg";
    const bg = document.createElementNS(SVG_NS, "rect");
    bg.setAttribute("width", String(floor.width)); bg.setAttribute("height", String(floor.height));
    bg.setAttribute("fill", "#f5f8fa"); svg.append(bg);
    for (const drawing of floor.tables) {
      const g = document.createElementNS(SVG_NS, "g"); g.setAttribute("class", "map-group");
      g.setAttribute("data-table-id", drawing.table_id);
      const shape = document.createElementNS(SVG_NS, drawing.shape === "rectangle" ? "rect" : "ellipse");
      if (drawing.shape === "rectangle") {
        ["x", "y", "width", "height"].forEach(k => shape.setAttribute(k, String(drawing[k])));
      } else {
        shape.setAttribute("cx", String(drawing.x + drawing.width / 2));
        shape.setAttribute("cy", String(drawing.y + drawing.height / 2));
        shape.setAttribute("rx", String(drawing.width / 2));
        shape.setAttribute("ry", String(drawing.height / 2));
      }
      shape.setAttribute("fill", "#d8eef0");
      shape.setAttribute("stroke", "#19758a");
      shape.setAttribute("stroke-width", "2");
      const label = document.createElementNS(SVG_NS, "text");
      label.setAttribute("x", String(drawing.x + drawing.width / 2));
      label.setAttribute("y", String(drawing.y + drawing.height / 2));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("fill", "#154b5a");
      label.setAttribute("font-size", "15");
      label.setAttribute("font-weight", "700");
      label.textContent = drawing.table_id;
      g.append(shape,label); svg.append(g);
      g.addEventListener("pointerdown", event => {
        event.preventDefault();
        const rect = svg.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const startX = event.clientX, startY = event.clientY;
        const oldX = drawing.x, oldY = drawing.y;
        function move(e) {
          const dx = (e.clientX - startX) * floor.width / rect.width;
          const dy = (e.clientY - startY) * floor.height / rect.height;
          drawing.x = Math.round(Math.max(0, Math.min(floor.width - drawing.width, oldX + dx)));
          drawing.y = Math.round(Math.max(0, Math.min(floor.height - drawing.height, oldY + dy)));
          if (drawing.shape === "rectangle") { shape.setAttribute("x", drawing.x); shape.setAttribute("y", drawing.y); }
          else { shape.setAttribute("cx", drawing.x + drawing.width / 2); shape.setAttribute("cy", drawing.y + drawing.height / 2); }
          label.setAttribute("x", drawing.x + drawing.width / 2);
          label.setAttribute("y", drawing.y + drawing.height / 2);
        }
        function stop() {
          document.removeEventListener("pointermove", move);
          document.removeEventListener("pointerup", stop);
          invalidate(); render();
        }
        document.addEventListener("pointermove", move);
        document.addEventListener("pointerup", stop);
      });
    }
    return svg;
  }

  function renderPlan() {
    const area = element("div");
    const controls = card("Solve seating", "Optimization runs only in the API. Hard constraints remain mandatory; time-limited results report feasible versus optimal.");
    controls.append(row(
      textField("Session ID", state.sessionId, v => { state.sessionId = v; invalidate(); },
        { id: "session-id", required: true }),
      textField("Solver time limit (seconds)", state.seconds, v => { state.seconds = Number(v); invalidate(); },
        { id: "time-limit", type: "number", min: 0.1, step: 0.1 }),
      action("Optimize seating", () => attempt(async () => {
        const problem = projectProblem();
        const plan = await api.post("/v1/solve", problem);
        state.plan = plan;
        state.view = "table";
        state.viewContent = null;
        announce("Solver returned " + plan.status.toUpperCase() + "; " +
          (plan.assignments?.length || 0) + " group assignments.");
        if (plan.status === "optimal" || plan.status === "feasible") await loadView("table");
      }), "primary", "solve-plan")
    ));
    area.append(controls);
    if (!state.plan) {
      area.append(element("div", "empty", "Import guests, configure the venue, add considerations, then optimize."));
      return area;
    }
    const plan = state.plan;
    const status = card("Solution report", "Status: " + plan.status.toUpperCase() +
      " · Score: " + (plan.total_score ?? "—") +
      " · Solver: " + Number(plan.solve_seconds || 0).toFixed(2) + " s");
    if (plan.status === "infeasible" || plan.status === "unknown") {
      status.append(element("p", "problem", plan.message));
      if ((plan.conflicting_constraints || []).length) {
        status.append(element("h3", "", "Why no seating plan fits"));
        const explanations = element("div", "stack");
        for (const explanation of plan.conflicting_constraints) {
          explanations.append(element("div", "problem", explanation));
        }
        status.append(explanations);
      }
      area.append(status);
      return area;
    }
    status.append(element("p", "muted", "Every assignment and explanation below came from the server's plan object."));
    area.append(status);
    const views = card("Plan views");
    const tabs = element("div", "view-tabs"); tabs.setAttribute("role", "tablist");
    VIEWS.forEach(([name,title]) => {
      const b = action(title, () => attempt(() => loadView(name)), "");
      b.id = "view-" + name;
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", state.view === name ? "true" : "false");
      tabs.append(b);
    });
    views.append(tabs);
    if (state.viewError) views.append(element("p", "problem", state.viewError));
    if (LIST_VIEWS.has(state.view)) {
      views.append(element("h3", "", state.view.startsWith("people") ? "People and their assigned tables" :
        "Groups and their assigned tables"));
      const toggle = element("label", "print-reasons-toggle");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.id = "print-reasons";
      checkbox.checked = Boolean(state.includeReasons);
      checkbox.addEventListener("change", () => {
        state.includeReasons = checkbox.checked;
        loadView(state.view);
      });
      toggle.append(checkbox, element("span", "", "Include written reasons (default off)"));
      views.append(toggle);
      const available = [...new Set((plan.assignments || []).flatMap(
        entry => (entry.guest_attributes || []).flatMap(attrs => Object.keys(attrs))))].sort();
      if (available.length) {
        const importHeaders = importColumnHeaders();
        const picker = element("fieldset", "list-field-picker");
        picker.append(element("legend", "", "Additional import columns"));
        for (const key of available) {
          const label = element("label", "list-field-choice");
          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.value = key;
          checkbox.checked = (state.listFields || []).includes(key);
          checkbox.addEventListener("change", () => {
            state.listFields = checkbox.checked
              ? [...(state.listFields || []).filter(k => available.includes(k)), key]
              : (state.listFields || []).filter(k => k !== key);
            loadView(state.view);
          });
          label.append(checkbox, element("span", "", attributeLabel(key, importHeaders)));
          picker.append(label);
        }
        views.append(picker);
      }
      if (typeof state.viewContent === "string") {
        const frame = element("iframe", "print-preview list-preview");
        frame.id = "list-preview";
        frame.title = "Printable assignment list";
        frame.srcdoc = state.viewContent;
        views.append(frame);
        views.append(row(
          action("Print list", () => {
            const target = document.getElementById("list-preview");
            if (!target?.contentWindow?.print) throw Error("Printing unavailable in this browser.");
            target.contentWindow.focus();
            target.contentWindow.print();
          }, "primary", "print-list"),
          action("Download list HTML", () => {
            downloadBlob(state.viewContent, state.view + (state.includeReasons ? "-reasons" : "") + ".html",
              "text/html;charset=utf-8");
          }, "secondary", "download-list")
        ));
      } else views.append(element("p", "muted", "Loading printable list…"));
    } else if (state.view === "table") {
      views.append(element("h3", "", "Table-by-table assignments"));
      views.append(element("pre", "", typeof state.viewContent === "string" ? state.viewContent : "Loading table view…"));
    } else if (state.view === "json") {
      views.append(element("h3", "", "Machine-readable plan"));
      views.append(element("pre", "", state.viewContent ? JSON.stringify(state.viewContent, null, 2) : "Loading JSON plan…"));
    } else if (state.view === "floor") {
      const pages = state.viewContent?.pages || [];
      if (!pages.length) views.append(element("p", "muted", "Loading floor-map pages…"));
      else {
        const container = element("div", "");
        const active = pages.find(p => p.zone_id === state.focusedFloor) || pages[0];
        container.append(selectField("Floor", pages.map(p => [p.zone_id, p.zone_id]), active.zone_id,
          value => { state.focusedFloor = value; render(); }, { id: "plan-floor-select" }));
        const frame = element("iframe", "floor-preview");
        frame.id = "floor-preview";
        frame.title = "Printable seating map for " + active.zone_id;
        frame.setAttribute("sandbox", "");
        frame.srcdoc = active.svg;
        container.append(frame);
        container.append(action("Download full floor-map PDF", () => attempt(async () => {
          const blob = await api.post("/v1/exports/floor-map/pdf", state.plan, "blob");
          downloadBlob(blob, "floor-maps.pdf", "application/pdf");
        }), "secondary", "download-floor-pdf"));
        views.append(container);
      }
    } else {
      views.append(element("h3", "", "Printable table cards"));
      views.append(selectField("Cards per page", [
        ["1", "1 per page (A5, current default)"],
        ["2", "2 per page (A4)"],
        ["4", "4 per page (A4)"]
      ], state.cardsPerPage, value => {
        state.cardsPerPage = Number(value);
        // Density previews are read-only; allow changes while a download is in flight.
        loadView("cards");
      }, { id: "cards-per-page" }));
      if (viewObjectUrl) {
        const frame = element("iframe", "print-preview");
        frame.id = "cards-preview"; frame.title = "Printable PDF table cards"; frame.src = viewObjectUrl;
        views.append(frame);
      } else views.append(element("p", "muted", "Loading printable PDF…"));
      views.append(action("Download table cards PDF", () => attempt(async () => {
        const blob = await api.post(tableCardsEndpoint(), state.plan, "blob");
        downloadBlob(blob, "table-cards.pdf", "application/pdf");
      }), "secondary", "download-cards"));
    }
    area.append(views);
    if ((plan.pattern_matches || []).length) {
      const matches = card("Global pattern matches",
        "Every matched table is listed, including empty tables with no guest-level explanation cards.");
      (plan.pattern_matches || []).forEach(match => {
        matches.append(element("p", "reason", match.description +
          " (" + (match.points > 0 ? "+" : "") + match.points + " points)"));
      });
      area.append(matches);
    }
    const compromises = card("Compromises and empty chairs",
      "Unmet soft considerations are listed with lost points. Hard rules cannot be traded away.");
    if (!plan.compromises?.length) compromises.append(element("p", "muted", "No reported soft compromises."));
    else compromises.append(issuesList(plan.compromises.map(c => ({
      row: null, column: c.rule_id, severity: "warning",
      message: c.description + " (lost " + c.lost_points + " points)"
    }))));
    const tableWrap = element("div", "table-scroll");
    const table = document.createElement("table");
    const head = element("tr");
    ["Table", "Floor", "Occupied", "Capacity", "Empty chairs"].forEach(x => head.append(element("th", "", x)));
    table.append(append(element("thead"),head));
    const body = element("tbody");
    (plan.tables || []).forEach(t => {
      const r = element("tr");
      [t.table_id, t.zone_id, t.occupied, t.capacity, t.empty_seats].forEach(x => r.append(element("td", "", x)));
      body.append(r);
    });
    table.append(body); tableWrap.append(table); compromises.append(tableWrap); area.append(compromises);
    const reasons = card("Per-assignment explanations", "Plain-language reasons and point contributions reported by the engine.");
    const list = element("div", "reasons");
    (plan.assignments || []).forEach(a => {
      const part = element("article", "reason-card");
      part.append(element("h4", "", a.group_id + " (" + a.guest_ids.length + " people) → " + a.table_id),
        element("p", "muted", a.guest_names.join(", ") + " · " + Number(a.points).toFixed(2) + " points"));
      const ul = document.createElement("ul");
      (a.reasons || []).forEach(r => ul.append(element("li", "",
        r.description + " (" + Number(r.points).toFixed(2) + " pts)")));
      part.append(ul); list.append(part);
    });
    reasons.append(list); area.append(reasons);
    return area;
  }

  async function loadView(view) {
    if (LIST_VIEWS.has(view) && state.view !== view) state.includeReasons = false;
    if (view === "floor" && state.plan?.layout?.floors?.length) {
      state.focusedFloor = state.plan.layout.floors[0].zone_id;
    }
    state.view = view;
    state.viewContent = null;
    state.viewError = "";
    clearObjectUrl();
    render();
    try {
      if (LIST_VIEWS.has(view)) {
        const endpoint = listEndpoint(view);
        const content = await api.post(endpoint, state.plan, "text");
        if (view !== state.view) return;
        if (endpoint !== listEndpoint(view)) return loadView(view);
        state.viewContent = content;
        listContentEndpoint = endpoint;
      }
      else if (view === "table") state.viewContent = await api.post("/v1/exports/table", state.plan, "text");
      else if (view === "json") state.viewContent = await api.post("/v1/exports/json", state.plan);
      else if (view === "floor") state.viewContent = await api.post("/v1/exports/floor-map/svg", state.plan);
      else {
        const density = state.cardsPerPage;
        const blob = await api.post(tableCardsEndpoint(), state.plan, "blob");
        if (density !== state.cardsPerPage || state.view !== "cards") return;
        if (typeof URL.createObjectURL !== "function") throw Error("PDF preview unavailable in this browser");
        viewObjectUrl = URL.createObjectURL(blob);
      }
    } catch (error) {
      state.viewError = friendlyApiError(error);
      state.notice = state.viewError;
      state.error = true;
      state.retryAction = () => loadView(view);
      render();
      return;
    }
    if (state.error) {
      state.error = false;
      state.notice = "Export preview loaded successfully.";
    }
    state.retryAction = null;
    render();
  }

  const ready = (async () => {
    try {
      state.catalog = await api.get("/v1/rules/catalog");
      if (state.catalog.shapes?.length &&
          !state.catalog.shapes.some(shape => shape.shape === state.selectedShape))
        state.selectedShape = state.catalog.shapes[0].shape;
    } catch (error) {
      state.notice = friendlyApiError(error);
      state.error = true;
      state.retryAction = async () => {
        state.catalog = await api.get("/v1/rules/catalog");
        if (state.catalog.shapes?.length &&
            !state.catalog.shapes.some(shape => shape.shape === state.selectedShape))
          state.selectedShape = state.catalog.shapes[0].shape;
        announce("Rule catalog loaded successfully.");
      };
    }
    render();
    if (state.plan && state.catalog) await loadView(state.view);
  })();
  render();
  return { state, ready, render, show: screen => { state.screen = screen; render(); },
           loadView, validateLayout, loadLayoutFiles, projectProblem, newSession };
}

if (typeof document !== "undefined") {
  const mounted = document.querySelector("[data-seat-app]");
  if (mounted) createApp(mounted);
}
