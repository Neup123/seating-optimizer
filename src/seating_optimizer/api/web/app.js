/* Phase 3: an API-driven visual client, with no seating or rule evaluation. */
import { renderPlanWorkspace } from "./plan-workspace.js";
import { renderGenericRules, tablePropertyVocabulary, displayRuleName } from "./v2-rules.js";
const SVG_NS = "http://www.w3.org/2000/svg";
const SCREENS = [["import", "Guest import"], ["rules", "Rules"], ["map", "Venue map"], ["plan", "Seating plan"]];
const LIST_VIEWS = new Set(["people", "people-floor", "groups", "groups-table", "not-seated"]);
const SESSION_KEY = "seating-optimizer:session:v2";
const LEGACY_SESSION_KEY = "seating-optimizer:session:v1";
const TEMPLATES_KEY = "seating-optimizer:templates:v2";
const LEGACY_TEMPLATES_KEY = "seating-optimizer:templates:v1";
const SESSION_FIELDS = ["screen", "view", "importFile", "preview", "mapping", "importResult",
  "guests", "ruleEngine", "ruleMechanism", "expandedRuleId", "rules", "nextRule", "zones", "tables", "layout",
  "focusedFloor", "sessionId", "seconds", "reviewListMode", "plan", "cardsPerPage", "includeReasons", "listFields", "notice", "error", "templateName", "templateSelected", "templateDrawerOpen", "selectedPlanItem", "expandedPartyKey", "workspaceQuery", "workspaceFloor", "workspaceSort", "focusedTableId", "printFormat", "manualInstructions", "nextManualId", "advancedSolver"];

function storedJSON(key, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) : fallback;
  } catch (_) { return fallback; }
}
function deepCopy(value) { return JSON.parse(JSON.stringify(value)); }

function partyName(assignment) {
  const names = assignment.guest_names || [];
  const proposed = assignment.group_name?.trim();
  if (proposed && !/^(registration:|guest:)/i.test(proposed) &&
      (names.length === 1 ||
       !names.some(name => name.trim().toLocaleLowerCase() === proposed.toLocaleLowerCase())))
    return proposed;
  const parts = names.map(name => /^(.*) \((\d+)\/(\d+)\)$/.exec(name));
  if (parts.length && parts.every(part => part && part[1] === parts[0][1] && part[3] === parts[0][3]) &&
      !names.some(name => name === parts[0][1]))
    return parts[0][1];
  if (names.length === 1 && names[0]?.trim() &&
      !/^(registration:|guest:)/i.test(names[0].trim()))
    return names[0].trim();
  let neutral = names.length === 1 ? "Guest" : "Party";
  while (names.some(name => name.trim().toLocaleLowerCase() === neutral.toLocaleLowerCase()))
    neutral = "Unnamed " + neutral;
  return neutral;
}
function ruleLabel(rule, fallback) {
  // Never surface an internal rule ID as an operator-facing label.
  if (rule) return displayRuleName(rule);
  if (["capacity", "table_capacity"].includes(fallback)) return "Chair capacity";
  return "Solver constraint";
}
function importedPartyName(guest) {
  if (guest.group_name?.trim()) return guest.group_name.trim();
  const generated = /^(.*) \((\d+)\/(\d+)\)$/.exec(guest.name || "");
  return generated ? generated[1] : (guest.name || guest.group_id || guest.id);
}
function partyMembers(assignment) {
  const names = assignment.guest_names || [];
  const parts = names.map(name => /^(.*) \((\d+)\/(\d+)\)$/.exec(name));
  const generated = parts.length && parts.every(part => part && part[1] === parts[0][1] &&
    part[3] === parts[0][3]) && parts[0][1] === partyName(assignment);
  if (generated || names.every(name => !name.trim() || name === partyName(assignment))) return [];
  return names;
}


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
function iconAction(title, kind, callback, className = "secondary icon-button", id, showText = false) {
  const b = action("", callback, className, id);
  b.title=title;b.setAttribute("aria-label", title);
  const svg=document.createElementNS(SVG_NS,"svg");
  svg.setAttribute("width","19");svg.setAttribute("height","19");
  svg.setAttribute("viewBox","0 0 24 24");
  svg.setAttribute("fill","none");svg.setAttribute("stroke","currentColor");
  svg.setAttribute("stroke-width","2");svg.setAttribute("stroke-linejoin","round");
  svg.setAttribute("stroke-linecap","round");svg.setAttribute("aria-hidden","true");
  const shapes={
    download:["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4","m7 10 5 5 5-5","M12 15V3"],
    printer:["M6 9V2h12v7","M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2","M6 14h12v8H6z"],
    list:["M8 6h13","M8 12h13","M8 18h13","M3 6h.01","M3 12h.01","M3 18h.01"],
    map:["M3 6 9 3l6 3 6-3v15l-6 3-6-3-6 3z","M9 3v15","M15 6v15"],
    tables:["M3 3h18v18H3z","M3 10h18","M10 3v18"],
    people:["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2","M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8","M22 21v-2a4 4 0 0 0-3-3.87","M16 3.13a4 4 0 0 1 0 7.75"],
    check:["M20 6 9 17l-5-5"],
    upload:["M12 16V3","m5 10 7-7 7 7","M3 16v4a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-4"],
    plus:["M12 5v14","M5 12h14"]
  };
  for (const path of shapes[kind] || shapes.list) {
    const item=document.createElementNS(SVG_NS,"path");
    item.setAttribute("d",path);svg.append(item);
  }
  b.append(svg);
  if (showText) b.append(element("span","",title));
  return b;
}
function fileControl(title, input) {
  // Keep the file input programmable and accessible without native chooser chrome.
  input.classList.add("visually-hidden-file");
  input.setAttribute("aria-label", title);
  const chooser = iconAction(title, "upload", () => input.click(),
    "secondary icon-button", input.id + "-trigger");
  return append(element("div", "file-picker"), chooser, input);
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
      catalog: [], ruleEngine: "intra", ruleMechanism: "split_term", expandedRuleId: null, rules: [], nextRule: 1,
      zones: [], tables: [], layout: { floors: [] }, focusedFloor: "",
      sessionId: "session-" + Date.now().toString(36), seconds: 5, reviewListMode:"table", advancedSolver: false, solving: false, plan: null, lastGoodPlan: null, restoredAfterFailure: false, mobileVenuePane: "map", cardsPerPage: 1, includeReasons: false, listFields: [],
       selectedPlanItem: null, expandedPartyKey: null, workspaceQuery: "", workspaceFloor: "",
       workspaceSort: "table", focusedTableId: "", printFormat: "groups-table",
       manualInstructions: [], nextManualId: 1, overflowChoice: "", pendingUnseatGroupId: null, reassignMode: null,
       reassignResponse: null, reassignPlaceType: "table",
       reassignPlaceId: "", reassignAllowSplit: false,
      notice: "", error: false, retryAction: null,
      templateName: "", templateSelected: "", templateDrawerOpen: false, storageWarning: ""
    };
  }
  const state = emptySession();
  // Uncommitted invalid text stays visible through re-renders, but never enters rules.
  const invalidPatternDrafts = new WeakMap();
  const savedTemplates = storedJSON(TEMPLATES_KEY, storedJSON(LEGACY_TEMPLATES_KEY, []));
  const templates = Array.isArray(savedTemplates) ? savedTemplates : [];
  const previous = storedJSON(SESSION_KEY, storedJSON(LEGACY_SESSION_KEY, null));
  if ([1, 2].includes(previous?.version) && previous.data && Array.isArray(previous.data.guests) &&
      Array.isArray(previous.data.rules) && Array.isArray(previous.data.tables) &&
      Array.isArray(previous.data.zones) && Array.isArray(previous.data.layout?.floors)) {
    for (const key of SESSION_FIELDS) {
      if (Object.hasOwn(previous.data, key)) state[key] = previous.data[key];
    }
    if (!Array.isArray(state.manualInstructions))
      state.manualInstructions = state.plan?.manual_instructions || [];
    state.notice = "Restored your previous planning session.";
    state.needsMigration = previous.version === 1 || state.rules.some(rule => rule.shape);
    state.error = false;
  }
  if (!state.needsMigration) for (const rule of state.rules) {
    if (rule.mechanism && !rule.name?.trim()) rule.name = displayRuleName(rule);
  }
  if (["optimal", "feasible"].includes(state.plan?.status)) state.lastGoodPlan = deepCopy(state.plan);
  let viewObjectUrl = null;
  let listContentEndpoint = null;
  let viewRequest = 0;
  let working = false;
  let noticesIssued = 0;

  function hasInvalidStoredPatternCounts(rules) {
    return (rules || []).some(rule => rule.enabled !== false && rule.shape === "global_pattern" &&
      (!Array.isArray(rule.parameters?.conditions) ||
        rule.parameters.conditions.some(condition =>
          !condition || typeof condition.value !== "number" || patternCountError(condition.value))));
  }
  function assertValidPatternCounts() {
    const invalidDraft = state.rules.some(rule => rule.enabled !== false && rule.shape === "global_pattern" &&
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
      window.localStorage.setItem(SESSION_KEY, JSON.stringify({ version: 2, data }));
      state.storageWarning = "";
    } catch (_) {
      // Import source data can exceed the per-origin quota; retain all imported
      // guests, mapping, rules, layout and solution instead of losing the session.
      if (data.importFile?.content_base64) {
        data.importFile = { filename: data.importFile.filename };
        try {
          window.localStorage.setItem(SESSION_KEY, JSON.stringify({ version: 2, data }));
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
      version: 2, name, zones: state.zones, tables: state.tables,
      layout: state.layout, rules: state.rules
    });
  }
  function applyConfiguration(config) {
    const copy = deepCopy(config);
    if (copy.version !== 2) throw Error("Migrate this template through the API first.");
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
    for (const rule of state.rules) {
      if (rule.mechanism && !rule.name?.trim()) rule.name = displayRuleName(rule);
    }
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
    if (Array.isArray(catalog) && catalog.length) { state.ruleEngine = catalog[0].engine; state.ruleMechanism = catalog[0].mechanism; }
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
  function invalidate() {
    if (["optimal", "feasible"].includes(state.plan?.status))
      state.lastGoodPlan = deepCopy(state.plan);
    state.plan = null; state.viewContent = null; state.selectedPlanItem = null;
    state.reassignMode = null; state.reassignResponse = null;
    state.pendingUnseatGroupId = null;
    clearObjectUrl(); ++viewRequest;
  }
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
      manual_instructions: state.manualInstructions || [],
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
    if (view === "not-seated") return "/v2/exports/not-seated-list/html";
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
    return "/v2/exports/" + (people ? "people-list" : "table-list") + "/html?" + query.toString();
  }
  function tableCardsEndpoint() {
    return "/v2/exports/table-cards/pdf" +
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
    sidebar.append(nav);
    return sidebar;
  }
  function render() {
    if (state.screen === "plan" && state.view === "print" &&
        LIST_VIEWS.has(state.printFormat) && typeof state.viewContent === "string" &&
        listContentEndpoint !== listEndpoint(state.printFormat)) {
      void loadView("print");
      return;
    }
    if (!state.needsMigration) saveSession();
    root.replaceChildren();
    const shell = element("div", "shell");
    shell.append(drawHeader());
    const main = element("main", "workspace");
    const header = element("div", "topline");
    const text = element("div");
    const title = SCREENS.find(([screen]) => screen === state.screen)?.[1] || "Seating Plan";
    const subtitles = {
      import: "Map registration fields for use in rules",
      rules: "Define who, what, where and priority",
      map: "Place tables and set chair counts",
      plan: "Solve and review the operator's choices"
    };
    text.append(element("h1", "", title), element("p", "", subtitles[state.screen]));
    const stats = element("div", "stats");
    stats.append(element("span", "pill", state.guests.length + " guests"),
      element("span", "pill", state.tables.length + " tables"),
      element("span", "pill", state.rules.length + " rules"));
    header.append(text, stats);
    main.append(header);
    const newButton = action("＋", newSession, "quiet small icon-button", "new-session");
    newButton.title = "Start a new empty session";
    newButton.setAttribute("aria-label", newButton.title);
    main.append(row(newButton, element("span", "save-state", state.storageWarning
      ? "Changes could not be saved" : "✓ Saved locally")));
    if (state.storageWarning) main.append(element("p", "problem", state.storageWarning));
    const notice = element("div", "notice" + (state.error ? " error" : ""), state.notice);
    notice.setAttribute("role", "status");
    notice.id = "notice";
    if (state.notice) main.append(notice);
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
    const form = card("Guest registrations");
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
    form.append(fileControl("Choose guest list spreadsheet (CSV or XLSX)", file));
    if (state.importFile) form.append(element("p", "muted", "Selected: " + state.importFile.filename));
    area.append(form);
    if (!state.preview) return area;

    const mappingCard = card("Map columns");
    mappingCard.append(element("span", "draft-status", "Draft mapping · Saved locally"));
    const choices = [["", "Unmapped (preserve as attribute)"],
      ["name", "Guest / registration name"], ["size", "Party size"],
      ["group_id", "Group ID"], ["group_name", "Group name"],
      ["attribute.language", "Attribute: language"],
      ["attribute.age_layer", "Attribute: age layer"],
      ["attribute.mobility", "Attribute: mobility"], ["custom", "Custom attribute..."]];
    const sheet = element("div", "table-scroll");
    const table = document.createElement("table");
    const head = element("thead");
    const tr = element("tr");
    ["Source column", "Criterion", "Target field", "Preview value"].forEach(t => tr.append(element("th", "", t)));
    head.append(tr); table.append(head);
    const body = element("tbody");
    state.preview.headers.forEach(header => {
      const rowEl = element("tr");
      rowEl.append(element("td", "", header));
      const targetIsCriterion = (state.mapping[header] || "").startsWith("attribute.") ||
        !["name","size","group_id","group_name"].includes(state.mapping[header]);
      rowEl.append(element("td", targetIsCriterion ? "criterion-ready" : "muted",
        targetIsCriterion ? "◇ Rule field" : "—"));
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
          value.slice(10) : "", next => { state.mapping[header] = "attribute." + next; render(); }, {
          id: "custom-" + header.replace(/[^a-z0-9]+/gi, "-").toLowerCase()
        });
        cell.append(custom);
      }
      rowEl.append(cell, element("td", "sample", state.preview.sample_rows[0]?.[header] || "—"));
      body.append(rowEl);
    });
    table.append(body); sheet.append(table); mappingCard.append(sheet);
    // The API rejects duplicate targets; surface the conflict at selection time
    // instead of letting a zero-guest response be the first indication.
    const mappedSources = new Map();
    for (const header of state.preview.headers) {
      const target = state.mapping[header];
      if (!target) continue;
      mappedSources.set(target, [...(mappedSources.get(target) || []), header]);
    }
    const duplicateMappings = [...mappedSources].filter(([, sources]) => sources.length > 1);
    for (const [target, sources] of duplicateMappings) {
      mappingCard.append(element("p", "problem warning",
        "Multiple columns mapped to " + target + ": " + sources.join(", ") +
        ". Choose a different target before importing."));
    }
    const buttons = row(iconAction("Review corrected mapping", "check", () => attempt(async () => {
      if (!state.importFile?.content_base64) throw Error("Re-select the spreadsheet to review its mapping.");
      state.preview = await api.post("/v1/import/preview", { ...state.importFile, mapping: state.mapping, header_aliases: {} });
      announce("Mapping checked by the API. Review any row-level issues below.");
    }), "secondary icon-button", "preview-mapping"), iconAction("Import guests", "upload", () => attempt(async () => {
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
    }), "primary icon-button", "import-guests"));
    buttons.querySelector("#import-guests").disabled = duplicateMappings.length > 0;
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

  function renderRules() {
    return renderGenericRules(state, {
      changed: (invalidatePlan = true) => { if (invalidatePlan) invalidate(); saveSession(); render(); },
      announce
    });
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

  function propertyControl(label, selected, id) {
    const block = element("fieldset", "property-picker");
    block.append(element("legend", "", label));
    const hidden = document.createElement("input");
    hidden.type="hidden"; hidden.id=id; hidden.value=selected.join(", ");
    const list = element("div", "property-options");
    const choices = [...new Set([...tablePropertyVocabulary(state.tables),...selected])].sort();
    const valueSet = new Set(selected);
    const changed = () => {
      hidden.value=[...valueSet].join(", ");
      hidden.dispatchEvent(new window.Event("change", {bubbles:true}));
    };
    for (const property of choices) {
      const tag = element("label", "check-inline");
      const check=document.createElement("input");check.type="checkbox";
      check.checked=valueSet.has(property);
      check.addEventListener("change",()=>{
        if(check.checked)valueSet.add(property);else valueSet.delete(property);
        changed();
      });
      tag.append(check,element("span","",property));list.append(tag);
    }
    const newTag=document.createElement("input");
    newTag.type="text";newTag.placeholder="New table property";
    newTag.setAttribute("aria-label","New table property");
    const add=action("+",()=>{
      const next=newTag.value.trim();
      if(!next||next.includes(","))return;
      if(!valueSet.has(next)) {valueSet.add(next);changed();}
      newTag.value="";
      if (!choices.includes(next)) {
        const option=element("label","check-inline");
        const check=document.createElement("input");check.type="checkbox";check.checked=true;
        check.addEventListener("change",()=>{if(check.checked)valueSet.add(next);else valueSet.delete(next);changed();});
        option.append(check,element("span","",next));list.append(option);
      }
    },"quiet small icon-button");
    add.title="Add table property";add.setAttribute("aria-label",add.title);
    newTag.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();add.click();}});
    block.append(hidden,list,row(newTag,add));
    return block;
  }

  function renderMap() {
    const area = element("div");
    const templatesCard = card("Venue templates");
    templatesCard.classList.add("form-measure");
    templatesCard.append(textField("Configuration name", state.templateName, value => {
      state.templateName = value;
    }, { id: "template-name", placeholder: "e.g. Weekly dinner" }));
    templatesCard.append(row(
      action("Save / update template", () => attempt(async () => {
        const name = document.getElementById("template-name").value.trim();
        const validated = await api.post("/v2/configurations/validate", configuration(name));
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
        const validated = await api.post("/v2/configurations/validate", configuration(name));
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
        const migrated = found.version === 2 ? found : (await api.post("/v2/configurations/migrate", found)).configuration;
        const validated = await api.post("/v2/configurations/validate", migrated);
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
    const configFile = document.createElement("input");
    configFile.id = "configuration-file";
    configFile.type = "file";
    configFile.accept = ".json,application/json";
    configFile.addEventListener("change", () => attempt(async () => {
      const file = configFile.files?.[0];
      if (!file) return;
      if (file.size > 2_000_000) throw Error("Configuration JSON must be smaller than 2 MB.");
      const incoming = JSON.parse(await file.text());
      const migrated = incoming.version === 2 ? incoming : (await api.post("/v2/configurations/migrate", incoming)).configuration;
      const validated = await api.post("/v2/configurations/validate", migrated);
      applyConfiguration(validated);
      announce("Imported complete configuration " + validated.name + ".");
    }));
    templatesCard.append(fileControl("Import full configuration JSON", configFile));
    const templateActions = [
      ["save-template","Save or update venue template","✓"],
      ["export-configuration","Download full configuration JSON","⤓"],
      ["load-template","Load selected venue template","↥"],
      ["duplicate-template","Duplicate selected venue template","⧉"],
      ["delete-template","Delete selected venue template","🗑"]
    ];
    for (const [id,title,glyph] of templateActions) {
      const b=templatesCard.querySelector("#"+id);
      b.textContent=glyph;b.classList.add("icon-button");
      b.title=title;b.setAttribute("aria-label",title);
    }
    const templateDrawer=element("details","card form-measure template-drawer");
    templateDrawer.open=Boolean(state.templateDrawerOpen);
    const templateToggle=element("summary","","Venue templates");
    templateToggle.id="template-toggle";
    templateToggle.title="Expand or collapse saved venue templates";
    templateToggle.setAttribute("aria-label", templateToggle.title);
    templateDrawer.append(templateToggle);
    templatesCard.querySelector("h2")?.remove();
    templatesCard.classList.remove("card","form-measure");
    templatesCard.classList.add("template-content");
    templateDrawer.append(templatesCard);
    templateDrawer.addEventListener("toggle",()=>{
      state.templateDrawerOpen=templateDrawer.open;saveSession();
    });
    area.append(templateDrawer);
    const intro = card("Floor layout");
    intro.classList.add("form-measure");
    const file = document.createElement("input");
    file.type = "file"; file.id = "layout-file"; file.accept = ".json,.svg"; file.multiple = true;
    file.addEventListener("change", () => attempt(async () => {
      if (file.files?.length) await loadLayoutFiles(Array.from(file.files));
    }));
    intro.append(fileControl("Import venue layout files (JSON or SVG)", file));
    intro.append(row(
      action("✓", () => attempt(validateLayout), "primary icon-button", "validate-layout"),
      action("↓", () => attempt(async () => {
        const validated = await api.post("/v1/layouts/import", {
          files: [{ filename: "layout.json", content_base64: encodeText(JSON.stringify(state.layout)) }]
        });
        downloadBlob(JSON.stringify(validated, null, 2), "venue-layout.json", "application/json");
      }), "secondary icon-button", "export-layout")
    ));
    for (const [id,title] of [["validate-layout","Validate layout"],["export-layout","Export layout JSON"]]) {
      const b=intro.querySelector("#"+id);b.title=title;b.setAttribute("aria-label",title);
    }
    area.append(intro);
    const floorForm = card("Create a floor");
    floorForm.classList.add("form-measure");
    const addFloor = element("form", "grid three");
    addFloor.id = "floor-form";
    const inputs = {};
    [["name", "Floor name", "Ground floor"],
     ["width", "Canvas width", "700"], ["height", "Canvas height", "450"]].forEach(([key,label,placeholder]) => {
      const input = document.createElement("input");
      input.name = key; input.placeholder = placeholder; input.required = true;
      input.type = key === "width" || key === "height" ? "number" : "text";
      if (input.type === "number") { input.min = "1"; input.value = placeholder; }
      inputs[key] = input;
      addFloor.append(append(element("label"), element("span", "", label), input));
    });
    const submit = element("button", "primary icon-button", "＋");
    submit.title = "Create floor"; submit.setAttribute("aria-label", "Create floor");
    submit.type = "submit"; submit.id = "add-floor";
    addFloor.append(submit);
    addFloor.addEventListener("submit", event => {
      event.preventDefault();
      let sequence = state.zones.length + 1;
      while (state.zones.some(zone => zone.id === "floor-" + sequence)) sequence++;
      const id = "floor-" + sequence;
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
    const panel = card("Tables on " + (state.zones.find(z => z.id === layout.zone_id)?.name || layout.zone_id));
    panel.append(selectField("Floor", state.layout.floors.map(f => [f.zone_id,
      state.zones.find(z => z.id === f.zone_id)?.name || f.zone_id]),
      state.focusedFloor, value => { state.focusedFloor = value; render(); }, { id: "floor-select" }));

    const mobileTabs = element("div", "venue-mobile-tabs segmented");
    mobileTabs.setAttribute("role", "group");
    mobileTabs.setAttribute("aria-label", "Venue editor section");
    for (const [mode, title] of [["map", "Map"], ["tables", "Table settings"]]) {
      const tab = action(title, () => { state.mobileVenuePane = mode; render(); },
        "secondary small", "venue-mobile-" + mode);
      tab.setAttribute("aria-pressed", String((state.mobileVenuePane || "map") === mode));
      tab.title = "Show venue " + (mode === "map" ? "map" : "table settings");
      mobileTabs.append(tab);
    }
    panel.append(mobileTabs);
    const split = element("div", "map-layout");
    split.dataset.mobilePane = state.mobileVenuePane || "map";
    const canvas = element("div", "map-canvas");
    canvas.append(makeEditorSvg(layout));
    split.append(canvas);
    const controls = element("div", "venue-table-settings");
    const tableForm = element("form", "stack");
    tableForm.id = "table-form";
    tableForm.append(element("h3", "", "Add numbered table"));
    const idInput = textField("Table ID", "", () => {}, { id: "new-table-id", required: true });
    const capacityInput = textField("Chair count", "10", () => {}, { id: "new-table-capacity", type: "number", min: 1, step: 1 });
    const shapeInput = selectField("Shape", ["rectangle", "ellipse", "circle"], "rectangle", () => {}, { id: "new-table-shape" });
    const propertyInput = propertyControl("Table properties", [], "new-table-properties");
    const priorityLabel = element("label", "priority-checkbox");
    const priorityInput = document.createElement("input");
    priorityInput.type = "checkbox"; priorityInput.id = "new-table-small-priority";
    priorityLabel.append(priorityInput, element("span", "", "Priority for couples and singles (soft)"));
    tableForm.append(grid(idInput, capacityInput, shapeInput), propertyInput, priorityLabel);
    const create = element("button", "secondary icon-button", "＋");
    create.type = "submit"; create.id = "add-table";
    create.title = "Add table to floor"; create.setAttribute("aria-label", create.title);
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
      editor.append(fields, propertyControl("Table properties",
        table?.properties || drawing.properties || [], "table-" + drawing.table_id + "-properties"));
      const priorityLabel = element("label", "priority-checkbox");
      const priorityInput = document.createElement("input");
      priorityInput.type = "checkbox";
      priorityInput.id = "table-" + drawing.table_id + "-small-priority";
      priorityInput.checked = Boolean(table?.small_group_priority);
      priorityLabel.append(priorityInput, element("span", "",
        "Priority for couples and singles (soft)"));
      editor.append(priorityLabel);
      const save = element("button", "secondary small icon-button", "✓");
      save.type = "submit"; save.title="Save table";save.setAttribute("aria-label",save.title);
      save.hidden=true;
      const indicator=element("span","save-state","✓ Saved locally");
      editor.addEventListener("input",e=>{
        if(e.target.type==="hidden")return;
        indicator.textContent="Editing draft";indicator.classList.add("unsaved");
      });
      editor.addEventListener("change",e=>{
        if(e.target.matches('input,select'))editor.requestSubmit();
      });
      const remove = action("⌫", () => {
        layout.tables = layout.tables.filter(d => d.table_id !== drawing.table_id);
        state.tables = state.tables.filter(t => t.id !== drawing.table_id);
        invalidate(); announce("Removed table " + drawing.table_id + ".");
      }, "danger small icon-button");
      remove.title="Remove table";remove.setAttribute("aria-label",remove.title);
      editor.append(row(save, indicator, remove));
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
        invalidate(); announce("Saved table " + drawing.table_id + ". Validate layout to check geometry.");
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
      g.setAttribute("tabindex","0");
      g.setAttribute("role","button");
      g.setAttribute("aria-label","Move table "+drawing.table_id+" using arrow keys");
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
      g.addEventListener("keydown", event => {
        const delta = {ArrowLeft:[-5,0],ArrowRight:[5,0],ArrowUp:[0,-5],ArrowDown:[0,5]}[event.key];
        if (!delta) return;
        event.preventDefault();
        drawing.x = Math.max(0,Math.min(floor.width-drawing.width,drawing.x+delta[0]));
        drawing.y = Math.max(0,Math.min(floor.height-drawing.height,drawing.y+delta[1]));
        invalidate();render();
        const active = root.querySelector('#map-editor-svg [data-table-id="'+drawing.table_id+'"]');
        active?.focus();
      });
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

  function resetPlanPreview() {
    state.viewContent = null; state.viewError = "";
    state.reassignMode = null; state.reassignResponse = null;
    clearObjectUrl(); ++viewRequest;
  }

  function proposeReassignment(direction) {
    void attempt(async () => {
      if (!state.plan || !(["optimal", "feasible"].includes(state.plan.status) ||
            (direction.action === "seat_pending" && state.plan.status === "needs_review")))
        throw Error("A solved plan or low-priority review is required before checking options.");
      const instruction = { ...direction, id: "manual-" + (state.nextManualId++) };
      const previousPlan = state.plan;
      const response = await api.post("/v2/reassign/options", {
        problem: projectProblem(), plan: previousPlan, instruction
      });
      if (state.plan !== previousPlan)
        throw Error("The seating plan changed. Select the party and check the move again.");
      state.reassignIntent = instruction;
      state.reassignResponse = response;
      announce(response.options?.length
        ? "Found " + response.options.length + " solver-checked options. Review consequences before applying."
        : "No confirmed move. Review the named hard-rule and capacity blockers.",
        response.status === "blocked");
    });
  }

  function applyReassignment(option) {
    if (!state.reassignResponse?.options?.includes(option) || !state.reassignIntent)
      throw Error("Re-check the intended move before applying.");
    const instructions = option.plan.manual_instructions || [];
    if (!instructions.some(item => item.id === state.reassignIntent.id))
      throw Error("The chosen solution does not retain the manual direction.");
    state.manualInstructions = deepCopy(instructions);
    state.plan = deepCopy(option.plan);
    resetPlanPreview();
    announce("Operator decision saved: " + option.title +
      ". The updated plan retains the confirmed direction.");
  }

  function unseatParty(groupId) {
    // Both workspace removal and the over-capacity chooser use the exact
    // operator-authored "unseat" instruction from Topic 2.
    void attempt(async () => {
      const registered = state.guests.some(g => (g.group_id || "guest:" + g.id) === groupId);
      if (!registered) throw Error("Select a registered party before moving it off the plan.");
      if (state.manualInstructions.some(i => i.group_id === groupId && i.action === "unseat"))
        throw Error("That party is already marked not seated.");
      const previous = state.manualInstructions;
      const direction = { id: "manual-" + state.nextManualId++, group_id: groupId, action: "unseat" };
      state.manualInstructions = [...previous, direction];
      try {
        const updated = await api.post("/v2/solve", projectProblem());
        state.plan = updated;
        state.manualInstructions = deepCopy(updated.manual_instructions || state.manualInstructions);
        state.selectedPlanItem = null;
        resetPlanPreview();
        const label=state.guests.find(g=>(g.group_id || "guest:"+g.id)===groupId);
        announce("Operator moved " + (label?.group_name || label?.name || "the selected family") +
          " to the not-seated list.");
      } catch (error) {
        state.manualInstructions = previous;
        throw error;
      }
    });
  }

  function removeInstruction(id) {
    void attempt(async () => {
      const remaining = state.manualInstructions.filter(item => item.id !== id);
      if (remaining.length === state.manualInstructions.length)
        throw Error("Instruction not found.");
      const old = state.manualInstructions;
      state.manualInstructions = remaining;
      try {
        const updated = await api.post("/v2/solve", projectProblem());
        state.plan = updated;
        state.manualInstructions = deepCopy(updated.manual_instructions || remaining);
        resetPlanPreview();
        announce("Manual direction removed. Solver re-optimized using the remaining instructions.");
      } catch (error) {
        state.manualInstructions = old;
        throw error;
      }
    });
  }

  function explainRuleRefs(value) {
    // Keep the server's machine identifiers intact in Plan/JSON, but show
    // the operator's name next to them in human-facing diagnostics.
    let output = String(value);
    for (const rule of state.rules) {
      if (!rule?.name) continue;
      output = output.replaceAll("rule:" + rule.id, rule.name);
    }
    return output.replace(/rule:[\w.-]+/g, "an unnamed consideration");
  }
  function renderPlan() {
    const area = element("div");
    const controls = card("Solve seating");
    const advanced = element("details", "advanced-settings");
    if (state.advancedSolver) advanced.open = true;
    advanced.addEventListener("toggle", () => { state.advancedSolver = advanced.open; saveSession(); });
    advanced.append(element("summary", "", "Advanced solver settings"),
      textField("Time limit (seconds)", state.seconds, v => { state.seconds = Number(v); invalidate(); },
        { id: "time-limit", type: "number", min: 0.1, step: 0.1 }));
    controls.append(row(
      action("Optimize seating", () => attempt(async () => {
        const problem = projectProblem();
        state.solving = true; render();
        let plan;
        try { plan = await api.post("/v2/solve", problem); }
        catch (error) {
          // An unsuccessful request is not an instruction to discard the last solved seating.
          if (!state.plan && state.lastGoodPlan) state.plan = deepCopy(state.lastGoodPlan);
          state.restoredAfterFailure = Boolean(state.plan);
          throw error;
        }
        finally { state.solving = false; render(); }
        state.plan = plan;
        state.restoredAfterFailure = false;
        if (["optimal", "feasible"].includes(plan.status))
          state.lastGoodPlan = deepCopy(plan);
        state.manualInstructions = deepCopy(plan.manual_instructions || state.manualInstructions);
        state.reassignResponse = null;
        state.reassignMode = null;
        state.view = "table";
        state.viewContent = null;
        state.selectedPlanItem = null;
        state.expandedPartyKey = null;
        state.workspaceFloor = "";
        state.focusedTableId = "";
        ++viewRequest;
        clearObjectUrl();
        announce("Solver returned " + plan.status.toUpperCase() + "; " +
          (plan.assignments?.length || 0) + " group " +
          ((plan.assignments?.length || 0) === 1 ? "assignment." : "assignments."));
        if (plan.status === "optimal" || plan.status === "feasible") await loadView("table");
      }), "primary", "solve-plan")
    ));
    controls.append(advanced);
    if (state.solving) {
      const progress = element("div", "solve-progress");
      progress.setAttribute("role","status");
      progress.append(element("div","skeleton-block"),element("div","skeleton-block short"),
        element("p","muted","Checking seating constraints in the solver…"));
      controls.append(progress);
    }
    area.append(controls);
    if (!state.plan) {
      area.append(element("div", "empty", "Import guests, configure the venue, add considerations, then optimize."));
      if (state.manualInstructions.length) {
        const stored = card("Saved manual directions", "These remain mandatory when seating is re-optimized.");
        for (const instruction of state.manualInstructions) {
          stored.append(row(element("span", "", instruction.group_id + " · " + instruction.action +
            (instruction.place_id ? " · " + instruction.place_type + " " + instruction.place_id : "")),
          action("Remove", () => {
            state.manualInstructions = state.manualInstructions.filter(item => item.id !== instruction.id);
            render();
          }, "quiet small")));
        }
        area.append(stored);
      }
      return area;
    }
    const plan = state.plan;
    function renderListPreview() {
      const content = element("div");
      if (state.viewError) content.append(element("p", "problem", state.viewError));
      if (typeof state.viewContent !== "string") {
        content.append(element("p", "muted", "Loading print pages…"));
        return content;
      }
      const frame = element("iframe", "print-preview list-preview");
      frame.id = "list-preview";
      frame.title = "Print preview of " + state.printFormat;
      frame.srcdoc = state.viewContent;
      content.append(frame);
      content.append(row(
        action("Print from preview", () => {
          const target = document.getElementById("list-preview");
          if (!target?.contentWindow?.print) throw Error("Printing unavailable in this browser.");
          target.contentWindow.focus();
          target.contentWindow.print();
        }, "primary", "print-list"),
        action("Download list HTML", () => {
          downloadBlob(state.viewContent, state.printFormat +
            (state.includeReasons && state.printFormat !== "not-seated" ? "-reasons" : "") +
            ".html", "text/html;charset=utf-8");
        }, "secondary", "download-list")
      ));
      return content;
    }
    function renderNotSeatedInAlarm() {
      if (state.view !== "print" || state.printFormat !== "not-seated" ||
          !plan.not_seated?.length) return null;
      const preview = card("Not seated in the main room");
      preview.append(renderListPreview());
      return preview;
    }
    function renderNotSeated() {
      const recorded = plan.unseated_reasons || [];
      if (!recorded.length && !plan.not_seated?.length) return null;
      const panel = card("Not seated");
      for (const group of (recorded.length ? recorded : plan.not_seated)) {
        const instruction = state.manualInstructions.find(i =>
          i.group_id === group.group_id && i.action === "unseat");
        panel.append(row(
          element("span", "", group.group_name + " · " + group.guest_ids.length + " people" +
            (group.reason ? " · " + (group.reason === "lack_of_space" ? "Shortage" : "Operator decision") : "")),
          instruction ? action("Restore", () => removeInstruction(instruction.id),
            "quiet small", "restore-" + group.group_id) : element("span", "", "")));
      }
      if (!["optimal", "feasible"].includes(plan.status)) {
        panel.append(action("Print list", () => {
          state.printFormat = "not-seated";
          void loadView("print");
        }, "secondary small", "open-not-seated-print"));
      }
      return panel;
    }
    function renderOvercapacity() {
      const panel = card("Over-capacity — human selection required",
        "No family has been dropped automatically. Choose explicitly who belongs on the not-seated list.");
      const grouped = new Map();
      state.guests.forEach(g => {
        const gid = g.group_id || "guest:" + g.id;
        if (!grouped.has(gid)) grouped.set(gid, []);
        grouped.get(gid).push(g);
      });
      const marked = new Map((plan.priority_marks || []).map(m => [m.group_id, m]));
      const excluded = new Set((plan.not_seated || []).map(g => g.group_id));
      const choices = [...grouped.entries()].filter(([gid]) => !excluded.has(gid))
        .map(([gid, members]) => {
          const mark = marked.get(gid);
          const title = mark?.group_name || importedPartyName(members[0]) || gid;
          const grade = mark ? " · grade " + mark.grade : "";
          return { gid, mark, title: title + " (" + members.length + ")" + grade };
        })
        .sort((a,b) => {
          if (!!a.mark !== !!b.mark) return a.mark ? -1 : 1;
          return (b.mark?.grade || 0) - (a.mark?.grade || 0) ||
            a.title.localeCompare(b.title);
        });
      if (!choices.length) return panel;
      if (!choices.some(x => x.gid === state.overflowChoice))
        state.overflowChoice = choices[0].gid;
      panel.append(row(
        selectField("Choose family", choices.map(x => [x.gid, x.title]),
          state.overflowChoice, v => { state.overflowChoice = v; },
          { id: "overflow-choice" }),
        action("Move to not seated", () => unseatParty(state.overflowChoice),
          "secondary small", "confirm-unseat")));
      return panel;
    }
    const status = card("Solution · " + plan.status.toUpperCase(), "Score: " + (plan.total_score ?? "—") +
      " · Solver: " + Number(plan.solve_seconds || 0).toFixed(2) + " s");
    if (state.restoredAfterFailure) status.append(element("p", "problem warning",
      "Showing the last successful plan; the latest solve failed and current inputs may differ."));
    if (plan.score_breakdown?.length) {
      // Score entries are plan-wide: do not misattribute them to individual assignments.
      const breakdown = element("section", "score-breakdown");
      breakdown.setAttribute("aria-label", "Plan score breakdown");
      breakdown.append(element("h3", "", "Score breakdown"));
      const entries = element("ul");
      for (const entry of plan.score_breakdown) {
        const name = ruleLabel(state.rules.find(rule => rule.id === entry.rule_id));
        const points = Number(entry.points || 0);
        entries.append(element("li", "", name + ": " + (points > 0 ? "+" : "") +
          points + (Math.abs(points) === 1 ? " point" : " points")));
      }
      breakdown.append(entries); status.append(breakdown);
    }
    if (plan.status === "infeasible" || plan.status === "unknown") {
      status.append(element("p", "problem", plan.message));
      if ((plan.conflicting_constraints || []).length) {
        status.append(element("h3", "", "Why no seating plan fits"));
        const explanations = element("div", "stack");
        for (const explanation of plan.conflicting_constraints) {
          const line = element("div","problem conflict-row");
          line.append(element("span","",explainRuleRefs(explanation)));
          const match = state.rules.find(rule => explanation.includes(rule.id) ||
            (rule.name && explanation.includes(rule.name)));
          if (match) {
            const fix = action("Edit rule",()=>{
              state.screen="rules";state.expandedRuleId=match.id;render();
            },"secondary small");
            fix.title="Edit "+match.name;line.append(fix);
          }
          explanations.append(line);
        }
        status.append(explanations);
      }
      area.append(status);
      const unseated = renderNotSeated();
      if (unseated) area.append(unseated);
      if (plan.message?.toLowerCase().includes("short by"))
        area.append(renderOvercapacity());
      const overflowPreview = renderNotSeatedInAlarm();
      if (overflowPreview) area.append(overflowPreview);
      return area;
    }
    status.classList.add("compact-status");
    for (const warning of plan.validation_warnings || []) status.append(element("p", "problem warning", warning));
    area.append(status);
    const unseated = renderNotSeated();
    if (unseated) area.append(unseated);
    if (plan.status === "needs_review") {
      const panel = card("Low-priority placement needs a decision",
        "Earlier families remain seated. Nothing pending was moved to not seated.");
      panel.append(element("p", "problem", plan.message));
      for (const mark of plan.pending_groups || []) {
        const line = element("div", "row between");
        line.append(element("span", "", mark.group_name + " · " +
          mark.guest_count + " people · grade " + mark.grade));
        line.append(action("Find options", () => proposeReassignment({
          group_id: mark.group_id, action: "seat_pending"
        }), "secondary small", "pending-options-" + mark.group_id));
        panel.append(line);
      }
      area.append(panel);
      area.append(renderPlanWorkspace(state, {
        partyName, partyMembers, refresh: render,
        proposeReassignment, applyReassignment, removeInstruction, unseatParty
      }));
      const overflowPreview = renderNotSeatedInAlarm();
      if (overflowPreview) area.append(overflowPreview);
      return area;
    }
    const views = card("Review seating");
    const toolbar = element("div","plan-view-toolbar");
    const review = element("div","review-cluster");
    const tabs = element("div", "view-tabs segmented");tabs.setAttribute("role","tablist");
    const listSelected=["table","people"].includes(state.view);
    const listMode = iconAction("List","list",()=>loadView(state.reviewListMode || "table"),
      "secondary small", "view-list",true);
    listMode.setAttribute("role","tab");
    listMode.setAttribute("aria-selected",String(listSelected));
    const mapMode = iconAction("Map","map",()=>loadView("floor"),
      "secondary small","view-floor",true);
    mapMode.setAttribute("role","tab");
    mapMode.setAttribute("aria-selected",String(state.view==="floor"));
    tabs.append(listMode,mapMode);review.append(tabs);
    if (listSelected) {
      const format = element("div","list-modes");format.setAttribute("role","group");
      format.setAttribute("aria-label","List grouping");
      for (const [mode,title,icon] of [["table","Tables","tables"],["people","People","people"]]) {
        const b=iconAction(title,icon,()=>loadView(mode),"quiet small","view-"+mode,true);
        b.setAttribute("aria-selected",String(state.view===mode));format.append(b);
      }
      review.append(format);
    }
    const exports = element("fieldset","export-cluster");
    exports.append(element("legend","","Exports"));
    const printButton=iconAction("Print and PDF","printer",()=>loadView("print"),
      "quiet small icon-button","view-print");
    const exportButton=iconAction("Download plan JSON","download",()=>attempt(async()=>{
      const result = await api.post("/v2/exports/json",state.plan);
      downloadBlob(JSON.stringify(result,null,2),"seating-plan.json","application/json");
    }),"quiet small icon-button","download-json");
    exports.append(printButton,exportButton);
    toolbar.append(review,exports);
    views.append(toolbar);
    if (state.viewError) views.append(element("p", "problem", state.viewError));
    if (state.view === "print") {

      views.append(selectField("Document", [
        ["people", "People list"], ["people-floor", "People by floor"],
        ["groups", "Table list"], ["groups-table", "Per-table pages"],
        ["not-seated", "Not seated in main room"],
        ["floor", "Floor maps PDF"], ["cards", "Table cards PDF"]
      ], state.printFormat, value => {
        state.printFormat = value;
        state.includeReasons = false;
        loadView("print");
      }, { id: "print-format" }));
      if (LIST_VIEWS.has(state.printFormat)) {
        if (state.printFormat !== "not-seated") {
          const toggle = element("label", "print-reasons-toggle");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.id = "print-reasons";
        checkbox.checked = Boolean(state.includeReasons);
        checkbox.addEventListener("change", () => {
          state.includeReasons = checkbox.checked;
          loadView("print");
        });
          toggle.append(checkbox, element("span", "", "Include written reasons (default off)"));
          views.append(toggle);
        }
        if (state.printFormat.startsWith("people")) {
          const available = [...new Set((plan.assignments || []).flatMap(
            entry => (entry.guest_attributes || []).flatMap(attrs => Object.keys(attrs))))].sort();
          if (available.length) {
            const importHeaders = importColumnHeaders();
            const picker = element("fieldset", "list-field-picker");
            picker.append(element("legend", "", "Additional import columns"));
            for (const key of available) {
              const label = element("label", "list-field-choice");
              const choice = document.createElement("input");
              choice.type = "checkbox";
              choice.value = key;
              choice.checked = (state.listFields || []).includes(key);
              choice.addEventListener("change", () => {
                state.listFields = choice.checked
                  ? [...(state.listFields || []).filter(k => available.includes(k)), key]
                  : (state.listFields || []).filter(k => k !== key);
                loadView("print");
              });
              label.append(choice, element("span", "", attributeLabel(key, importHeaders)));
              picker.append(label);
            }
            views.append(picker);
          }
        }
        views.append(renderListPreview());
      } else {
        if (state.printFormat === "cards") views.append(selectField("Cards per page", [
          ["1", "1 per page (A5)"], ["2", "2 per page (A4)"], ["4", "4 per page (A4)"]
        ], state.cardsPerPage, value => {
          state.cardsPerPage = Number(value); loadView("print");
        }, { id: "cards-per-page" }));
        if (viewObjectUrl) {
          const frame = element("iframe", "print-preview");
          frame.id = state.printFormat === "cards" ? "cards-preview" : "floor-preview";
          frame.title = "Printable " + state.printFormat + " PDF";
          frame.src = viewObjectUrl;
          views.append(frame);
          views.append(row(
            action("Print from preview", () => {
              const target = document.getElementById(frame.id);
              if (!target?.contentWindow?.print) throw Error("PDF printing unavailable in this browser. Download the PDF to print it.");
              target.contentWindow.focus();
              target.contentWindow.print();
            }, "primary", "print-preview-document"),
            action("Download PDF", () => attempt(async () => {
              const endpoint = state.printFormat === "floor"
                ? "/v2/exports/floor-map/pdf" : tableCardsEndpoint();
              const blob = await api.post(endpoint, state.plan, "blob");
              downloadBlob(blob, state.printFormat === "floor" ? "floor-maps.pdf" : "table-cards.pdf",
                "application/pdf");
            }), "secondary", state.printFormat === "cards" ? "download-cards" : "download-floor-pdf")
          ));
        } else views.append(element("p", "muted", "Loading PDF preview…"));
      }
    } else {
      views.append(renderPlanWorkspace(state, {
        partyName, partyMembers, refresh: render,
        proposeReassignment, applyReassignment, removeInstruction, unseatParty, explainRuleRefs
      }));
    }
    area.append(views);
    const ruleDisplay = id => ruleLabel(state.rules.find(rule => rule.id === id), id);
    if ((plan.pattern_matches || []).length) {
      const matches = card("Table patterns");
      (plan.pattern_matches || []).forEach(match => {
        matches.append(element("p", "reason", ruleDisplay(match.rule_id) + ": " + match.description +
          " (" + (match.points > 0 ? "+" : "") + match.points +
          (Math.abs(Number(match.points)) === 1 ? " point)" : " points)")));
      });
      area.append(matches);
    }
    const compromises = card("Compromises and empty chairs");
    if (!plan.compromises?.length) compromises.append(element("p", "muted", "No reported soft compromises."));
    else compromises.append(issuesList(plan.compromises.map(c => ({
      row: null, column: ruleDisplay(c.rule_id), severity: "warning",
      message: c.description + " (lost " + c.lost_points + (c.lost_points === 1 ? " point)" : " points)")
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
    const reasons = card("Reasons by assignment");
    const list = element("div", "reasons");
    const partyTotals = new Map();
    (plan.assignments || []).forEach(a =>
      partyTotals.set(a.group_id, (partyTotals.get(a.group_id) || 0) + a.guest_ids.length));
    (plan.assignments || []).forEach(a => {
      const part = element("article", "reason-card");
      const people = partyMembers(a);
      const total = partyTotals.get(a.group_id);
      const sizeLabel = total > a.guest_ids.length
        ? a.guest_ids.length + "/" + total
        : String(a.guest_ids.length);
      part.append(element("h4", "", partyName(a) + " — " + sizeLabel + " → " + a.table_id),
        element("p", "muted", (people.length ? people.join(", ") + " · " : "") +
          (!Number(a.points || 0) && plan.score_breakdown?.length
            ? "No assignment-specific score — see plan breakdown"
            : Number(a.points || 0).toFixed(2) +
              (Math.abs(Number(a.points || 0)) === 1 ? " point" : " points"))));
      const ul = document.createElement("ul");
      (a.reasons || []).forEach(r => ul.append(element("li", "",
        ruleDisplay(r.rule_id) + ": " + r.description +
        " (" + Number(r.points).toFixed(2) + " pts)")));
      part.append(ul); list.append(part);
    });
    reasons.append(list); area.append(reasons);
    return area;
  }

  async function loadView(view) {
    const request = ++viewRequest;
    if (view === "print" && state.view !== view) state.includeReasons = false;
    if (view === "floor" && state.view !== "floor" &&
        state.plan?.layout?.floors?.length)
      state.focusedFloor = state.plan.layout.floors[0].zone_id;
    if (view === "table" || view === "people") state.reviewListMode=view;
    state.view = view;
    state.viewContent = null;
    state.viewError = "";
    clearObjectUrl();
    render();
    try {
      if (view === "print") {
        const format = state.printFormat;
        if (LIST_VIEWS.has(format)) {
          const endpoint = listEndpoint(format);
          const result = await api.post(endpoint, state.plan, "text");
          if (request !== viewRequest) return;
          if (endpoint !== listEndpoint(format)) return loadView("print");
          state.viewContent = result;
          listContentEndpoint = endpoint;
        } else {
          const density = state.cardsPerPage;
          const endpoint = format === "floor" ? "/v2/exports/floor-map/pdf" : tableCardsEndpoint();
          const blob = await api.post(endpoint, state.plan, "blob");
          if (request !== viewRequest || (format === "cards" && density !== state.cardsPerPage)) return;
          if (typeof URL.createObjectURL !== "function") throw Error("PDF preview unavailable in this browser.");
          viewObjectUrl = URL.createObjectURL(blob);
        }
      } else if (view === "json") {
        const json = await api.post("/v2/exports/json", state.plan);
        if (request !== viewRequest) return;
        state.viewContent = json;
      }
    } catch (error) {
      if (request !== viewRequest) return;
      state.viewError = friendlyApiError(error);
      state.notice = state.viewError;
      state.error = true;
      state.retryAction = () => loadView(view);
      render();
      return;
    }
    if (request !== viewRequest) return;
    if (state.error) {
      state.error = false;
      state.notice = "Export preview loaded successfully.";
    }
    state.retryAction = null;
    render();
  }

  const ready = (async () => {
    try {
      state.catalog = await api.get("/v2/rules/catalog");
    } catch (error) {
      state.notice = friendlyApiError(error);
      state.error = true;
      state.retryAction = async () => {
        state.catalog = await api.get("/v2/rules/catalog");
        announce("Rule catalog loaded successfully.");
      };
    }
    if (state.needsMigration) {
      try {
        const old = {version:1,name:"Restored venue",zones:state.zones,
          tables:state.tables,layout:state.layout,rules:state.rules};
        const migrated = await api.post("/v2/configurations/migrate",old);
        state.rules = migrated.configuration.rules;
        state.needsMigration = false; state.plan = null; state.viewContent = null;
        state.notice = "Legacy rules migrated to v2. Review them before optimizing.";
      } catch (error) {
        state.error = true; state.notice = "Legacy session needs migration: " + friendlyApiError(error);
        state.rules = [];
      }
    }
    render();
    if (state.plan && Array.isArray(state.catalog)) await loadView(state.view);
  })();
  render();
  return { state, ready, render, show: screen => { state.screen = screen; render(); },
           loadView, validateLayout, loadLayoutFiles, projectProblem, newSession };
}

if (typeof document !== "undefined") {
  const mounted = document.querySelector("[data-seat-app]");
  if (mounted) createApp(mounted);
}
