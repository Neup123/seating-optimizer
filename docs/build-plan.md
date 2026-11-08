# Build Brief — Seating Plan Optimizer (core + API + visual wrapper)

A focused tool that turns a list of registered guests for an event meal
into a seating plan: who sits at which table, computed automatically and
fast, with a reason attached to every assignment. This brief is the single
source of instructions for the build. Where this brief makes a planning
decision, it is deliberate; where it flags an open question, do not invent
an answer — build the stated default and leave the flag visible.

## 1. Purpose and scope discipline

IN SCOPE: guest/group import, a dynamic rule (consideration) model, an
optimization engine, a plan with per-assignment reasons, pluggable
exports/views, a programmatic API, and a comfortable visual UI on top.

OUT OF SCOPE (belongs in separate tools that connect to this one, never
inside it): registrations/forms themselves, payments, invitations and
messaging, CRM features, anything not part of the seating problem.

## 2. Architecture — core first

Three layers, strictly separated:

1. **Core engine** (Python package): domain model + rule evaluation +
   solver. No UI, no HTTP. Fully usable from code.
2. **API**: a REST API over the core, described by an OpenAPI YAML spec
   rendered with Scalar (the owner's standing preference where an API
   exists). Every capability of the core — including every export — is
   reachable through the API. Headless parity is a hard requirement:
   nothing may exist only in the UI.
3. **Visual wrapper** (web UI): a client of the API. Comfortable and
   visual, but holds no logic the API does not expose.

The core must be embeddable as a plugin/component inside a larger software
system later: clean package boundaries, no global state, configuration
passed in, results returned as data.

## 3. Solver

Use **Google OR-Tools CP-SAT** (open source). Do not write a solver from
scratch. The PyPI package `seating-planner` may be read as a reference for
data shapes, but its model is insufficient (no zones, soft-only conflicts,
capacity overflow) — do not adopt its semantics.

Semantics:
- **Hard considerations are true constraints.** The owner's phrasing is
  "infinite points"; in CP-SAT they are implemented as constraints that
  cannot be violated. If the hard constraints conflict, the solve returns
  an explicit INFEASIBLE report naming the conflicting constraints —
  never a silent violation.
- **Soft considerations are weighted points** in the objective; the solver
  maximizes the total score. Every weight lives in data (rule records /
  configuration), visible and tunable — never hardcoded.
- Performance target: a few seconds for ~300 guests. A configurable time
  limit returns the best plan found so far, with its status (optimal /
  feasible / infeasible) reported honestly.

## 4. Domain model

- **Venue**: floors/zones (e.g. ground floor, first floor, courtyard).
  Each **table** belongs to one zone and has its OWN capacity (chair
  count) — there is no global table size. A table also has an optional
  position/shape in a floor layout (see §7).
- **Venue layout as data**: for the visual map export, each floor has a
  layout — tables drawn and numbered — supplied either as a pre-drawn
  numbered draft converted to layout data, or imported as a structured
  layout file. The same layout data serves the visual editor and the
  code-only exports.
- **Session**: one meal sitting. If an event has two sittings, each
  sitting is a separate solve over the same venue (default; flagged).
- **Guests and groups**: a registration produces one or more guests.
  Guests may belong to a **group** (family/party). GROUPS ARE ATOMIC:
  a group is never split across tables.
- **Attributes**: guests carry attributes — language, age layer, mobility
  or other zone-relevant restrictions, plus free-form attributes defined
  by the operator. Attributes are data, not a fixed enum: new attribute
  kinds can be introduced without code changes.
- **Constraint propagation**: a restriction on ONE group member binds the
  WHOLE group (e.g. one wheelchair user ⇒ the entire family is placed on
  the ground floor). A group's effective restriction is the strictest
  among its members.

## 5. The dynamic rule model (the heart of the tool)

Considerations are **rule records**, added and edited as data — never
code. A rule has: a shape (below), parameters, and either a point weight
or HARD. New instances of an existing shape require no programming; the
set of considerations is expected to grow over time.

Rule shapes to implement generically:
1. **Attribute grouping** — guests sharing an attribute value (same
   language, same age layer, same family…) score points for sitting at
   the same table. Weight per rule.
2. **Zone restriction by attribute** — guests with a given attribute may
   sit only in a given zone (mobility ⇒ ground floor). Hard or weighted.
   Applies at group level via §4 propagation.
3. **Pair rules** — two named guests/groups: together, or apart. Weighted
   or hard.
4. **Capacity** — a table's own chair count is a hard ceiling.
5. **Fill efficiency** — the objective prefers full tables: empty seats
   ("holes") cost points, scaled so fragmentation is discouraged without
   overriding real considerations. Weight tunable.
6. **Locked assignments (pins)** — the operator may pin a guest/group to
   a table; pins are hard, and the rest re-optimizes around them.

## 6. Import

Spreadsheet import (CSV/XLSX) of the guest list:
- **Manual column mapping**: the operator connects each source column to
  its target field. Always available.
- **Automatic detection by column headers** wherever it can succeed,
  with the manual mapping as correction/fallback. Header aliases are data.
- Import validates and reports problems (missing sizes, duplicate names);
  it never silently merges or drops rows.

## 7. Outputs — one plan, many renderers

The solve returns ONE plan object: assignments (guest/group → table),
total score, per-assignment reasons, and a compromises report (soft rules
not fully satisfied and why; empty seats per table). Exports are
**pluggable renderers** of that plan, all available via the API:

1. **Table view** — the classic list: table by table, who sits there.
2. **Floor-map view** — per floor, one page per floor, the drawn layout
   with the assigned groups printed onto the table drawings (SVG/PDF).
3. **Table cards** — one printable card per table listing its families;
   printed, cut, and placed on the physical tables.
4. **Machine-readable plan** — JSON of the full plan including reasons
   and score breakdown.

Per-assignment **reasons** are generated from the rules actually satisfied
by that assignment (and the points they contributed), in plain language.

## 8. Phasing (one PR per phase — the owner's standing rule)

- **Phase 1**: core model + rule shapes + CP-SAT solve + import (manual
  mapping + header detection) + table-view and JSON exports + API with
  OpenAPI/Scalar. Tests for every rule shape.
- **Phase 2**: venue layout model + floor-map export + table cards.
- **Phase 3**: the visual wrapper UI over the API (import mapping screen,
  rule editor, plan views, map editor for layouts).

Each phase: code + tests in the same PR, local test run reported, no
unrelated changes, no other issues touched.

## 9. Testing requirements

- Unit tests per rule shape, including: group atomicity, wheelchair
  propagation to the whole family, per-table capacities, hard-conflict
  infeasibility naming the conflicting constraints, fill-efficiency
  behaviour, pins respected on re-solve.
- Import tests: manual mapping, header auto-detection, malformed rows.
- API contract tests against the OpenAPI spec.
- A golden end-to-end case: a realistic guest list (~120 guests, mixed
  languages, age layers, one wheelchair family, two floors) that must
  solve in seconds with zero hard violations.

## 10. Standing rules for the builder

- Software and UI copy in **English**. Never infer additional languages
  or localization scope from context.
- One PR per topic/phase; a PR covers its topic completely.
- License: the owner's standard source-available license (BSL 1.1 +
  Additional Use Grant) — apply the LICENSE file as in the owner's other
  repos; if the repo has none yet, flag it instead of choosing another.
- OpenAPI spec is a YAML file in the repo, rendered with Scalar; do not
  substitute Swagger UI.

## 11. Open questions (build the default, keep the flag)

- Seat ORDER within a table is out of scope (assignment is to tables).
- Two sittings = separate solves (default above).
- Whether tables may be joined/split per event is undecided; model a
  table as fixed per venue until told otherwise.
