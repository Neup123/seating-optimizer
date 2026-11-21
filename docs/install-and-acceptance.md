# Installation, upgrade, and acceptance

The supported deployment is an operator-controlled local computer on the loopback interface. The HTTP API currently has **no authentication**; do not expose it to an untrusted network. See [architecture and trust boundaries](orientation.md) (PR #100 until merged) and issue #86.

## Requirements

- Python 3.11 or 3.12 (the CI validation matrix).
- A working pip installation path for OR-Tools, Pydantic, FastAPI, Uvicorn, openpyxl, and ReportLab.
- Node.js 22 only when running UI tests, with Playwright Chromium available for browser E2E.
- A browser with JavaScript enabled, and permission to use local browser storage if session recovery is desired.

## Fresh installation

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[api,test]"
python -m pytest -v -s
uvicorn seating_optimizer.api.app:app --host 127.0.0.1 --port 8000
```

Use `.venv\Scripts\activate` instead of the POSIX activation command on Windows. Open `http://127.0.0.1:8000/`. The API reference is `/docs`, the OpenAPI source is `/openapi.yaml`, and `/healthz` returns a health payload. Use a compatible Python environment rather than installing into the system interpreter.

## Upgrade and rollback

1. Before upgrading, export any important venue/configuration JSON and keep the source CSV/XLSX files outside the browser. Save printed/exported plans separately if needed.
2. Record the current Git commit or release; install the intended version in a new virtual environment, keeping the older one available for rollback.
3. Reinstall Python dependencies and re-run the acceptance commands below. In particular, validate older v1 configuration JSON with `/v2/configurations/migrate` and `/v2/configurations/validate` before using it for a new live event.
4. Browser storage is local to its origin. A new host/port, browser profile, or cleared site data is **not** an automatic migration; the API has no persistent server database.
5. If acceptance fails, stop using the upgraded environment, return to the recorded version, and restore an exported source/configuration. A printed plan is an output, not a full editable backup.
6. Do not assume older saved rule references remain valid if guest identifiers or source rows changed (issue #57). Audit pinned and paired parties after every re-import.

There is no automatic database schema migration or central backup because the HTTP API is stateless. Browser `localStorage` may contain guest-identifying data; use an appropriate browser profile for each operator, and clear site data on shared machines when finished. Issue #85 tracks a first-class retention/clear action.

## Acceptance checklist

Run the following on the candidate commit before using it with actual guest information.

```sh
python -m pytest -v -s
npm install --no-audit --no-fund
npm run test:ui
npx playwright install chromium
npm run test:browser
```

A local API smoke check after startup:

```sh
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/openapi.yaml
```

For release acceptance, record these results:

- [ ] Python unit tests pass on supported Python versions, including imported guest/group sizes, hard constraints, reasons, rule scoring and exports.
- [ ] Node/jsdom UI tests pass. The current JavaScript dependency lockfile is not yet enforced (issue #98).
- [ ] Playwright tests pass against live FastAPI and actual Chromium, including import, venue/rules and plan/print workflow.
- [ ] Manually test an event-sized **synthetic** guest list: import and correct mappings, create/validate venue geometry, add/change rule instances, solve, inspect infeasible and feasible messages, review a pending family, reassign, print, reload and restore session.
- [ ] Confirm that no raw internal IDs replace operator-facing labels in the important screens.
- [ ] Test the user interface with a keyboard and at narrow viewport width; ongoing gaps are documented in #91–#96.
- [ ] Confirm `/v2/solve` does not expose authentication-free access outside the trusted local host.
- [ ] Verify score/search quality for intended live instance sizes. The solver can return FEASIBLE within a time limit; do not claim optimality without OPTIMAL.
- [ ] Confirm source files/configuration backups are accessible independent of localStorage.

**Coverage/exclusions:** These commands exercise the unit/API/browser suite and smoke-check HTTP endpoints. They do not establish production security, network authentication, data-retention compliance, all event sizes, or a human usability review. Issues #56–#59 and #83–#88 track known acceptance risks.

## Troubleshooting

- **API unavailable:** check the process, correct loopback address/port and `/healthz`; do not solve by binding publicly to `0.0.0.0`.
- **Import blocked:** correct row-level errors and mapping; never ignore missing size, duplicate name or malformed rows.
- **No feasible plan:** inspect hard-rule conflict diagnostics, chair capacity, floors and group restrictions before relaxing a hard rule.
- **Unknown solver status:** increase the configured time budget or simplify rules and retry; UNKNOWN is not proof of infeasibility.
- **Browser draft lost:** localStorage may have been disabled, cleared or exceeded quota; re-import the source and restore a saved configuration.
- **Print missing non-Latin glyphs:** install suitable system Unicode fonts for PDF output.
- **E2E browser missing:** install the Playwright Chromium binary for the tested Node/OS environment.

## Documentation maintenance

Update this checklist whenever dependencies, supported environments, persistence, route semantics, operator paths or release gates change. [Operator guide](operator-guide.md) covers day-to-day operation; [README](../README.md) contains programmatic usage.
