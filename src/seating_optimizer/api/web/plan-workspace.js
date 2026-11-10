/* Interactive v2 working surfaces. All placement data comes from the solved API Plan. */
import { assignmentMatchesSelection, selectedPlanAssignments, togglePlanSelection,
  partyTotals, portionLabel } from "./plan-selection.js";

function el(tag, css = "", text) {
  const node = document.createElement(tag);
  if (css) node.className = css;
  if (text !== undefined) node.textContent = String(text);
  return node;
}
function clicker(text, fn, css = "secondary small", id) {
  const node = el("button", css, text);
  node.type = "button";
  if (id) node.id = id;
  node.addEventListener("click", fn);
  return node;
}
function choice(label, options, current, fn, id) {
  const holder = el("label", "field");
  holder.append(el("span", "", label));
  const select = el("select");
  select.id = id;
  for (const [value, text] of options) {
    const option = el("option", "", text);
    option.value = value; select.append(option);
  }
  select.value = current;
  select.addEventListener("change", () => fn(select.value));
  holder.append(select);
  return holder;
}
function tableOf(plan, id) {
  return (plan.tables || []).find(table => table.table_id === id);
}
function floorOf(plan, assignment) {
  return tableOf(plan, assignment.table_id)?.zone_id || "";
}
function memberNames(assignment, partyMembers) {
  const names = partyMembers(assignment);
  return names.length === (assignment.guest_ids || []).length ? names : [];
}

export function renderPlanWorkspace(state, {
  partyName, partyMembers, refresh, proposeReassignment, applyReassignment, removeInstruction, unseatParty
}) {
  const plan = state.plan;
  const area = el("div", "plan-workspace");
  const totals = partyTotals(plan);
  const assignments = plan.assignments || [];
  const floors = [...new Set((plan.tables || []).map(table => table.zone_id || ""))];
  const selectItem = (kind, id) => {
    state.selectedPlanItem = togglePlanSelection(state.selectedPlanItem, kind, id);
    state.reassignMode = null;
    state.reassignResponse = null;
    state.pendingUnseatGroupId = null;
    refresh();
  };
  const chooseIntent = (assignment, action) => {
    if (assignment) state.selectedPlanItem = { kind: "party", id: assignment.group_id };
    const current = assignment?.table_id ||
      selectedPlanAssignments(plan, state.selectedPlanItem)[0]?.table_id;
    state.reassignMode = action;
    state.pendingUnseatGroupId = null;
    state.reassignPlaceType = "table";
    state.reassignPlaceId = action === "not_here" ? current :
      ((plan.tables || []).find(t => t.table_id !== current)?.table_id || current);
    state.reassignAllowSplit = false;
    state.reassignResponse = null;
    refresh();
  };
  const nameFor = a => portionLabel(a, totals, partyName);
  const sorted = items => [...items].sort((left, right) => {
    const by = state.workspaceSort || "table";
    const key = a => by === "name" ? partyName(a).toLocaleLowerCase() :
      by === "size" ? (a.guest_ids || []).length : a.table_id;
    const a = key(left), b = key(right);
    return (typeof a === "number" ? a - b : String(a).localeCompare(String(b))) ||
      left.table_id.localeCompare(right.table_id) || left.group_id.localeCompare(right.group_id);
  });
  const query = (state.workspaceQuery || "").toLocaleLowerCase().trim();
  const matches = a => {
    if (state.workspaceFloor && floorOf(plan, a) !== state.workspaceFloor) return false;
    if (!query) return true;
    return [partyName(a), a.table_id, floorOf(plan, a),
      ...(a.guest_names || []), ...(a.reasons || []).map(r => r.description)]
      .some(value => String(value || "").toLocaleLowerCase().includes(query));
  };

  if (state.selectedPlanItem) {
    const chosen = selectedPlanAssignments(plan, state.selectedPlanItem);
    if (chosen.length) {
      const selection = el("section", "plan-selection", "");
      selection.id = "plan-selection";
      const isPerson = state.selectedPlanItem.kind === "person";
      const name = isPerson
        ? (chosen[0].guest_names || [])[chosen[0].guest_ids.indexOf(state.selectedPlanItem.id)] || "Person"
        : partyName(chosen[0]);
      selection.append(el("strong", "", "Selected " + (isPerson ? "person: " : "party: ") + name),
        el("span", "muted", " At " + [...new Set(chosen.map(a => a.table_id))].join(", ") + "."));
      const bar = el("div", "row");
      bar.append(clicker("Inspect selection", () => {
        state.expandedPartyKey = chosen[0].group_id + "@" + chosen[0].table_id;
        refresh();
      }, "secondary small", "inspect-selection"));
      if (isPerson) bar.append(clicker("Select whole party", () => {
        state.selectedPlanItem = { kind: "party", id: chosen[0].group_id };
        refresh();
      }, "secondary small", "select-whole-party"));
      bar.append(clicker("Focus table", () => {
        state.workspaceFloor = floorOf(plan, chosen[0]);
        state.focusedTableId = chosen[0].table_id;
        refresh();
      }, "secondary small", "focus-selected-table"));
      bar.append(clicker("Not here", () => chooseIntent(chosen[0], "not_here"),
        "secondary small", "intent-not-here"));
      bar.append(clicker("Move to", () => chooseIntent(chosen[0], "move_to"),
        "secondary small", "intent-move-to"));
      // A person selection does not silently remove their entire registration.
      // Select the whole party first, then explicitly confirm the removal.
      if (!isPerson) bar.append(clicker("Not seated", () => {
        state.pendingUnseatGroupId = chosen[0].group_id;
        state.reassignMode = null;
        state.reassignResponse = null;
        refresh();
      }, "secondary small", "intent-unseat-party"));
      bar.append(clicker("Clear selection", () => {
        state.selectedPlanItem = null; state.reassignMode = null;
        state.reassignResponse = null;
        state.pendingUnseatGroupId = null;
        refresh();
      }, "quiet small", "clear-plan-selection"));
      selection.append(bar);

      if (!isPerson && state.pendingUnseatGroupId === chosen[0].group_id) {
        const confirm = el("div", "reassign-editor");
        confirm.append(el("p", "muted", "Move the whole party " + partyName(chosen[0]) +
          " to the not-seated list? Only your confirmation changes the plan."));
        confirm.append(clicker("Confirm removal", () => unseatParty(chosen[0].group_id),
          "secondary small", "confirm-unseat-party"));
        confirm.append(clicker("Cancel", () => {
          state.pendingUnseatGroupId = null;
          refresh();
        }, "quiet small", "cancel-unseat-party"));
        selection.append(confirm);
      }

      if (state.reassignMode) {
        const editor = el("div", "reassign-editor");
        const isMove = state.reassignMode === "move_to";
        editor.append(el("h4", "", isMove ? "Move party to a place" : "Exclude party from a place"));
        const kinds = [["table", "Table"], ["floor", "Floor"], ["zone", "Zone"]];
        editor.append(choice("Place type", kinds, state.reassignPlaceType || "table", type => {
          state.reassignPlaceType = type;
          const locations = type === "table" ? (plan.tables || []).map(t => t.table_id) :
            [...new Set((plan.tables || []).map(t => t.zone_id))];
          state.reassignPlaceId = type === "table" ? chosen[0].table_id :
            (floorOf(plan, chosen[0]) || locations[0] || "");
          if (isMove) state.reassignPlaceId = locations.find(v => v !== state.reassignPlaceId) ||
            locations[0] || "";
          state.reassignResponse = null;
          refresh();
        }, "reassign-place-type"));
        const locations = state.reassignPlaceType === "table"
          ? (plan.tables || []).map(t => [t.table_id, "Table " + t.table_id])
          : [...new Set((plan.tables || []).map(t => t.zone_id))].map(zone => [zone, zone]);
        editor.append(choice(isMove ? "Destination" : "Excluded place", locations,
          state.reassignPlaceId || "", value => {
            state.reassignPlaceId = value; state.reassignResponse = null; refresh();
          }, "reassign-place"));
        const splitLabel = el("label", "reassign-split");
        const split = el("input"); split.type = "checkbox"; split.id = "reassign-allow-split";
        split.checked = Boolean(state.reassignAllowSplit);
        split.addEventListener("change", () => {
          state.reassignAllowSplit = split.checked; state.reassignResponse = null; refresh();
        });
        splitLabel.append(split, el("span", "", "Allow this party to split across tables (show fractions)"));
        editor.append(splitLabel);
        editor.append(clicker("Find feasible options", () => proposeReassignment({
          group_id: chosen[0].group_id, action: state.reassignMode,
          place_type: state.reassignPlaceType, place_id: state.reassignPlaceId,
          allow_split: Boolean(state.reassignAllowSplit)
        }), "primary small", "find-reassign-options"));
        selection.append(editor);
      }
      area.append(selection);
    } else {
      // Invalidate stale selections after a new solve or replacement plan.
      state.selectedPlanItem = null;
    }
  }

  if (state.reassignResponse) {
    const response = state.reassignResponse;
    const panel = el("section", "reassign-results");
    panel.id = "reassign-results";
    panel.append(el("h3", "", response.status === "available"
      ? "Feasible reassignment options — review before applying"
      : response.status === "unknown"
        ? "No option confirmed within the solver time limit"
        : "No feasible option"));
    if (!response.options?.length) {
      panel.append(el("p", "problem", response.status === "unknown"
        ? "The solver has not proved infeasibility. Raise the time limit and try again."
        : "All routes must satisfy infinite-weight rules and table capacities."));
      const details = el("ul");
      for (const blocker of response.blockers || []) details.append(el("li", "", blocker));
      panel.append(details);
    }
    for (const option of response.options || []) {
      const optionCard = el("article", "reassign-option");
      optionCard.append(el("h4", "", option.title + " · " + option.kind));
      optionCard.append(el("p", "muted", "Score change: " +
        (option.score_delta > 0 ? "+" : "") + option.score_delta + " points"));
      const affected = el("ul");
      for (const move of option.movements || []) {
        const portions = (option.plan.assignments || []).filter(a => a.group_id === move.group_id)
          .map(a => a.table_id + " (" + a.guest_ids.length + "/" + move.people + ")").join(", ");
        affected.append(el("li", "", move.party_name + ": " +
          move.before.join(", ") + " → " + portions));
      }
      optionCard.append(el("strong", "", "People affected"), affected);
      if (option.soft_rule_warnings?.length) {
        const warning = el("div", "problem warning");
        warning.append(el("strong", "", "Warning: ordinary rules overridden (finite weights only)"));
        const list = el("ul");
        for (const text of option.soft_rule_warnings) list.append(el("li", "", text));
        warning.append(list);
        optionCard.append(warning);
      } else optionCard.append(el("p", "muted", "No additional finite-weight rule losses."));
      optionCard.append(el("p", "muted", "All infinite-weight rules and table chair limits remain satisfied."));
      optionCard.append(clicker("Apply this option", () => applyReassignment(option),
        "primary small", "apply-" + option.id));
      panel.append(optionCard);
    }
    area.append(panel);
  }

  if (state.manualInstructions?.length) {
    const stored = el("section", "reassign-stored");
    stored.id = "stored-instructions";
    stored.append(el("h3", "", "Active manual directions (honoured on every re-solve)"));
    for (const item of state.manualInstructions) {
      const line = el("div", "row");
      const name = assignments.find(a => a.group_id === item.group_id);
      line.append(el("span", "", (name ? partyName(name) : item.group_id) + " · " +
        (item.action === "unseat" ? "Not seated" :
          item.action === "pin_placement" ? "Confirmed placement" :
          (item.action === "not_here" ? "Not here: " : "Move to: ") +
          item.place_type + " " + item.place_id) +
        (item.allow_split ? " · splitting permitted" : "")));
      line.append(clicker("Remove direction", () => removeInstruction(item.id),
        "quiet small", "remove-instruction-" + item.id));
      stored.append(line);
    }
    area.append(stored);
  }

  const listLike = ["table", "people", "people-floor", "groups", "groups-table"].includes(state.view);
  if (listLike) {
    const toolbar = el("div", "plan-toolbar");
    const search = el("label", "field");
    search.append(el("span", "", "Search parties, people, tables, reasons"));
    const input = el("input");
    input.type = "search"; input.id = "plan-search"; input.value = state.workspaceQuery || "";
    input.placeholder = "Search this view";
    input.addEventListener("input", () => {
      state.workspaceQuery = input.value;
      const caret = input.selectionStart;
      refresh();
      const next = document.getElementById("plan-search");
      if (next) { next.focus(); if (caret !== null) next.setSelectionRange(caret, caret); }
    });
    search.append(input);
    toolbar.append(search,
      choice("Floor", [["", "All floors"], ...floors.map(f => [f, f || "Unspecified"])],
        state.workspaceFloor || "", value => { state.workspaceFloor = value; refresh(); }, "plan-filter-floor"),
      choice("Sort", [["table", "Table"], ["name", "Party name"], ["size", "Party size"]],
        state.workspaceSort || "table", value => { state.workspaceSort = value; refresh(); }, "plan-sort"));
    area.append(toolbar);
  }

  function detail(a) {
    const details = el("div", "plan-details");
    const people = memberNames(a, partyMembers);
    details.append(el("h4", "", nameFor(a) + " · Table " + a.table_id));
    details.append(el("p", "muted", "Members: " +
      (people.length ? people.join(", ") : (a.guest_ids || []).length + " registered " +
      ((a.guest_ids || []).length === 1 ? "person" : "people"))));
    const ruleIds = new Set((a.reasons || []).map(reason => reason.rule_id));
    const related = (state.rules || []).filter(rule => ruleIds.has(rule.id) ||
      (rule.shape === "pin" && (rule.parameters?.target === a.group_id ||
        (a.guest_ids || []).includes(rule.parameters?.target))));
    const members = el("div", "plan-members");
    (a.guest_ids || []).forEach((id, index) => {
      const member = clicker(people[index] || "Member " + (index + 1),
        () => selectItem("person", id), "plan-person");
      member.setAttribute("aria-pressed", String(state.selectedPlanItem?.kind === "person" &&
        state.selectedPlanItem.id === id));
      members.append(member);
    });
    details.append(members);
    details.append(el("h4", "", "Rules for this assignment"));
    if (related.length) {
      const rules = el("ul");
      for (const rule of related) rules.append(el("li", "", (rule.shape || "Rule") +
        " (" + rule.id + "; " + (rule.mode || "soft") + ")"));
      details.append(rules);
    } else details.append(el("p", "muted", "No matching rule records in the current editor."));
    details.append(el("h4", "", "Solver explanation"));
    if (!(a.reasons || []).length) details.append(el("p", "muted", "No individual explanation recorded."));
    else {
      const reasons = el("ul");
      for (const reason of a.reasons) reasons.append(el("li", "",
        reason.description + " (" + Number(reason.points || 0).toFixed(2) + " points)"));
      details.append(reasons);
    }
    return details;
  }

  function assignmentRow(a, withPeople = false) {
    const key = a.group_id + "@" + a.table_id;
    const holder = el("article", "plan-entry");
    holder.dataset.groupId = a.group_id;
    holder.dataset.tableId = a.table_id;
    if (assignmentMatchesSelection(a, state.selectedPlanItem)) holder.classList.add("is-selected");
    const line = el("div", "plan-entry-line");
    const party = clicker(nameFor(a), () => selectItem("party", a.group_id), "plan-target");
    party.setAttribute("aria-pressed", String(state.selectedPlanItem?.kind === "party" &&
      state.selectedPlanItem.id === a.group_id));
    line.append(party, el("span", "muted", "Table " + a.table_id +
      " · " + (floorOf(plan, a) || "Unspecified floor")));
    line.append(clicker("Not here", () => chooseIntent(a, "not_here"),
      "quiet small"));
    line.append(clicker("Move to", () => chooseIntent(a, "move_to"),
      "quiet small"));
    const show = state.expandedPartyKey === key;
    line.append(clicker(show ? "Hide details" : "Details", () => {
      state.expandedPartyKey = show ? null : key; refresh();
    }, "quiet small", "details-" + encodeURIComponent(key).replace(/%/g, "_")));
    holder.append(line);
    if (withPeople) {
      const named = memberNames(a, partyMembers);
      if (named.length) {
        const members = el("div", "plan-members");
        named.forEach((name, index) => {
          const id = a.guest_ids[index];
          const b = clicker(name, () => selectItem("person", id), "plan-person");
          b.setAttribute("aria-pressed", String(state.selectedPlanItem?.kind === "person" &&
            state.selectedPlanItem.id === id));
          members.append(b);
        });
        holder.append(members);
      }
    }
    if (show) holder.append(detail(a));
    return holder;
  }
  function tableSection(t, variant) {
    const holder = el("section", variant === "cards" ? "working-table-card" : "working-table-section");
    holder.dataset.tableId = t.table_id;
    holder.append(el("h3", "", "Table " + t.table_id),
      el("p", "muted", (t.zone_id || "Unspecified floor") + " · " +
        t.occupied + "/" + t.capacity + " chairs · " + t.empty_seats + " empty"));
    const items = sorted(assignments.filter(a => a.table_id === t.table_id && matches(a)));
    if (!items.length) holder.append(el("p", "muted", "No matching parties at this table."));
    else for (const a of items) holder.append(assignmentRow(a, true));
    return holder;
  }

  if (state.view === "floor") {
    const active = state.focusedFloor || floors[0] || "";
    const switcher = choice("Floor", floors.map(f => [f, f || "Unspecified floor"]),
      active, value => { state.focusedFloor = value; state.focusedTableId = ""; refresh(); }, "plan-floor-select");
    area.append(switcher);
    const layout = (plan.layout?.floors || []).find(f => f.zone_id === active);
    if (layout) {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.id = "working-floor-svg";
      svg.setAttribute("viewBox", "0 0 " + layout.width + " " + layout.height);
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", "Interactive floor layout for " + active);
      for (const drawing of layout.tables || []) {
        const table = tableOf(plan, drawing.table_id);
        const group = document.createElementNS(svg.namespaceURI, "g");
        group.setAttribute("data-table-id", drawing.table_id);
        group.setAttribute("role", "button");
        group.setAttribute("tabindex", "0");
        group.setAttribute("aria-label", "Focus table " + drawing.table_id);
        group.setAttribute("class", state.focusedTableId === drawing.table_id ? "focused" : "");
        const shape = document.createElementNS(svg.namespaceURI,
          drawing.shape === "circle" ? "circle" : drawing.shape === "ellipse" ? "ellipse" : "rect");
        if (drawing.shape === "rectangle") {
          ["x","y","width","height"].forEach(k => shape.setAttribute(k, drawing[k]));
        } else {
          shape.setAttribute("cx", drawing.x + drawing.width / 2);
          shape.setAttribute("cy", drawing.y + drawing.height / 2);
          shape.setAttribute("rx", drawing.width / 2);
          shape.setAttribute("ry", drawing.height / 2);
          if (drawing.shape === "circle") { shape.removeAttribute("rx"); shape.removeAttribute("ry");
            shape.setAttribute("r", Math.min(drawing.width, drawing.height) / 2); }
        }
        const title = document.createElementNS(svg.namespaceURI, "text");
        title.setAttribute("x", drawing.x + drawing.width / 2);
        title.setAttribute("y", drawing.y + drawing.height / 2);
        title.setAttribute("text-anchor", "middle");
        title.textContent = drawing.table_id + " · " + (table?.occupied || 0) +
          "/" + (table?.capacity || 0);
        group.append(shape, title);
        const focus = () => { state.focusedTableId = drawing.table_id; refresh(); };
        group.addEventListener("click", focus);
        group.addEventListener("keydown", e => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); focus(); }
        });
        svg.append(group);
      }
      area.append(el("div", "working-floor-map"));
      area.lastChild.append(svg);
    }
    const tables = (plan.tables || []).filter(t => t.zone_id === active &&
      (!state.focusedTableId || state.focusedTableId === t.table_id));
    area.append(clicker("Show all floor tables", () => { state.focusedTableId = ""; refresh(); }, "quiet small"));
    for (const t of tables) area.append(tableSection(t, "floor"));
  } else if (state.view === "table" || state.view === "groups-table" || state.view === "cards") {
    const tables = [...(plan.tables || [])].filter(t => !state.workspaceFloor ||
      t.zone_id === state.workspaceFloor);
    const grid = el("div", state.view === "cards" ? "working-card-grid" : "working-table-grid");
    for (const t of tables) grid.append(tableSection(t, state.view));
    area.append(grid);
  } else if (["people", "people-floor", "groups"].includes(state.view)) {
    const items = sorted(assignments.filter(matches));
    if (state.view === "people-floor") {
      for (const floor of floors) {
        const section = el("section", "working-table-section");
        section.append(el("h3", "", floor || "Unspecified floor"));
        const matching = items.filter(a => floorOf(plan, a) === floor);
        for (const a of matching) section.append(assignmentRow(a, true));
        if (!matching.length) section.append(el("p", "muted", "No matching people."));
        area.append(section);
      }
    } else {
      for (const a of items) area.append(assignmentRow(a, state.view === "people"));
      if (!items.length) area.append(el("p", "empty", "No entries match these filters."));
    }
  }
  return area;
}
