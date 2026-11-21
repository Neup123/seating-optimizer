# ADR-001 — Adapt an established constraint solver rather than fork an entire seating product

- **Status:** Accepted retrospectively, 2026-11-18
- **Context:** The build brief calls for event-meal seating by groups, table capacities, zones, conditional hard/soft rules, optional large-group splitting, explainable assignments, API parity and printable exports.
- **Decision:** Continue using maintained **Google OR-Tools CP-SAT** as the optimization engine inside the Python package, with project-specific domain models, importers, rule data and UI. Do not start a wholesale rewrite to imitate an unrelated seating app.

## Candidate search and comparison

Search carried out on 2026-11-18 across GitHub seating-arrangement repositories, available Python packages and Google's CP-SAT reference. This is a **retrospective architecture fit review**, not a claim to have fully audited every alternative's source or current build health.

| Candidate | Fit | Decision |
| --- | --- | --- |
| [Google OR-Tools](https://github.com/google/or-tools) — official [CP-SAT model documentation](https://developers.google.com/optimization/cp/cp_solver) | Maintained general-purpose constraint programming, native integer scoring, hard constraints and explicit solve statuses; Python bindings already integrated and regression-tested in this repository | **Reuse** as the engine. Avoid implementing new search algorithm |
| [seating-planner](https://pypi.org/search/?q=seating-planner) (Python package cited in [build-plan.md](build-plan.md)) | May inform input/party data shapes; the original project evaluation found no confirmed coverage for zone rules, controlled split/overflow and per-rule explanation semantics | Reference only, not adopted as the optimization model; do not transplant unverified semantics |
| [achnos/QuESO](https://github.com/achnos/QuESO) | Open-source QUBO-based office seating; different domain and model from event-table grouping, per-table chairs and interactive printed event exports | Do not fork: substantial domain and API adaptation would remain |
| [plargillier/IsThisSeatTakenSolver](https://github.com/plargillier/IsThisSeatTakenSolver) | OR-Tools-based seating **logic-puzzle** solver rather than event registration/party and venue planning software | Reuse the underlying OR-Tools idea, not puzzle-specific domain semantics |

## Why the chosen architecture wins

- The problem's **hard** conditions (capacities, placement restrictions, manual locks) must never be traded for arbitrary point gains. CP-SAT models them as actual constraints; soft rule instances become weighted objective terms.
- The project preserves headless parity: domain `models.py` + v1/v2 solvers → FastAPI adapter → browser UI; printable formats derive from plan data, not a second optimizer.
- Migrating to a different complete seating package would require rebuilding the same specialization (zones, optional split, rule explanations, API and print layout) while losing tested integrations.
- OR-Tools is a reusable maintained library rather than a bespoke algorithm; dependency compatibility and security should be checked during regular upgrades.

## Alternatives and caveats

A complete product fork would be appropriate only if a candidate demonstrably covers *all* core semantics and has a verifiable maintained codebase. The 2026-11-18 search did not identify such a candidate; this is not a proof none exists. We are not replacing dependencies or claiming complete solver quality. Existing issues #56–#59 and #83–#84 show that correct library choice does **not** guarantee a correct domain model or good unrestricted search.

## Consequences and review triggers

- Prefer enhancing the existing rule catalog and solver adapters to introducing parallel engines.
- Keep rule weights and rule instance metadata user-configurable; make new constraints/rule types data-driven, not hardcoded event exceptions.
- Re-evaluate if a genuinely maintained event-seating engine with compatible rules, split semantics, API and exports appears, or if OR-Tools support changes.
- Cite the actual upstream project and the observed version when introducing a new dependency. A new library implementation may require a new ADR.

**Verification scope:** candidate purpose and repository descriptions, OR-Tools official documentation, and source layout in this repository. No performance benchmark, install test or dependency security scan of alternative candidates was performed in this retrospective review.
