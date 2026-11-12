"""Thin, stateless FastAPI adapter over the Python package."""
from __future__ import annotations

import base64
import binascii
from importlib.resources import files
from pathlib import Path
from typing import Literal
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, FileResponse
from pydantic import BaseModel, Field

from seating_optimizer import (
    Plan, Problem, Table, Zone, VenueLayout, VenueConfiguration, SvgFloorBundle, import_layout_files,
    import_registrations, render_floor_pdf, render_floor_svg, render_table_cards_pdf,
    render_json, render_table, render_people_list_html, render_table_list_html, render_not_seated_list_html,
    solve, preview_registrations, rule_catalog,
    ImportPreview, RuleCatalog,
)
from seating_optimizer.importer import ImportResult
from seating_optimizer.generic_rules import mechanism_catalog
from seating_optimizer.generic_solver import (GenericProblem, GenericPlan, GenericVenueConfiguration, solve_generic)
from seating_optimizer.rule_migration import migrate_configuration
from seating_optimizer.reassignment import ReassignRequest, ReassignResponse, propose_reassignment
from seating_optimizer.models import ManualInstruction, Model
from seating_optimizer.reassignment import Movement


class LayoutFile(BaseModel):
    filename: str
    content_base64: str


class LayoutImportRequest(BaseModel):
    files: list[LayoutFile] = Field(min_length=1)
    zones: list[Zone] | None = None
    tables: list[Table] | None = None


class GenericReassignRequest(Model):
    problem: GenericProblem
    plan: GenericPlan
    instruction: ManualInstruction


class GenericReassignOption(Model):
    id: str
    kind: str
    title: str
    movements: list[Movement]
    score_delta: int
    soft_rule_warnings: list[str]
    plan: GenericPlan


class GenericReassignResponse(Model):
    status: str
    options: list[GenericReassignOption] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class ImportRequest(BaseModel):
    filename: str
    content_base64: str
    mapping: dict[str, str] | None = None
    header_aliases: dict[str, list[str]] | None = None


def create_app() -> FastAPI:
    app = FastAPI(
        title="Seating Plan Optimizer",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/import", response_model=ImportResult)
    def import_data(request: ImportRequest) -> ImportResult:
        try:
            content = base64.b64decode(request.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid base64 input") from exc
        return import_registrations(
            content, request.filename, mapping=request.mapping, aliases=request.header_aliases
        )

    @app.post("/v1/import/preview", response_model=ImportPreview)
    def preview_import(request: ImportRequest) -> ImportPreview:
        try:
            content = base64.b64decode(request.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid base64 input") from exc
        return preview_registrations(
            content, request.filename, mapping=request.mapping, aliases=request.header_aliases
        )

    @app.get("/v1/rules/catalog", response_model=RuleCatalog)
    def get_rule_catalog() -> RuleCatalog:
        return rule_catalog()

    @app.get("/v2/rules/catalog")
    def get_generic_rule_catalog() -> list[dict]:
        """Derive v2 catalog from the generic mechanism registry."""
        return mechanism_catalog()

    @app.post("/v2/configurations/migrate")
    def migrate_v1_configuration(configuration: VenueConfiguration) -> dict:
        """Read v1 and produce the v2-only writing representation plus ledger."""
        result, report = migrate_configuration(configuration.model_dump(mode="json"))
        return {"configuration": result, "report": report}

    @app.post("/v2/configurations/validate", response_model=GenericVenueConfiguration)
    def validate_v2_configuration(configuration: GenericVenueConfiguration) -> GenericVenueConfiguration:
        """Validate version-2 writing schema without touching legacy config."""
        return configuration

    @app.post("/v2/solve", response_model=GenericPlan)
    def solve_generic_problem(problem: GenericProblem) -> GenericPlan:
        try:
            return solve_generic(problem)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v2/reassign/options", response_model=GenericReassignResponse)
    def generic_reassignment(request: GenericReassignRequest) -> GenericReassignResponse:
        """Preview an operator direction through the SAME v2 solver and rule data.

        No local seating heuristic or v1 shape adapter is used. A preview is not
        persisted; the operator must explicitly apply the returned instruction.
        """
        problem, plan, instruction = request.problem, request.plan, request.instruction
        if plan.session_id != problem.session_id or plan.manual_instructions != problem.manual_instructions:
            raise HTTPException(status_code=409, detail="Plan changed. Solve again before previewing a move.")
        if plan.status not in {"optimal", "feasible", "needs_review"}:
            raise HTTPException(status_code=422, detail="A solved plan is required.")
        if instruction.id in {item.id for item in problem.manual_instructions}:
            raise HTTPException(status_code=422, detail="Instruction ID already exists.")
        groups = {guest.group_id or "guest:" + guest.id for guest in problem.guests}
        if instruction.group_id not in groups:
            raise HTTPException(status_code=422, detail="Choose a registered family.")
        if instruction.action == "unseat":
            raise HTTPException(status_code=422, detail="Use the explicit operator unseat action.")
        candidate = problem.model_copy(deep=True)
        candidate.manual_instructions.append(instruction)
        if instruction.allow_split and instruction.group_id not in candidate.splittable_groups:
            candidate.splittable_groups.append(instruction.group_id)
        try:
            updated = solve_generic(candidate)
        except (KeyError, ValueError) as exc:
            return GenericReassignResponse(status="blocked", blockers=[str(exc)])
        if updated.status not in {"optimal", "feasible"}:
            return GenericReassignResponse(
                status="unknown" if updated.status == "unknown" else "blocked",
                blockers=[updated.message, *updated.conflicting_constraints[:5]],
            )
        old = defaultdict(list)
        new = defaultdict(list)
        people = defaultdict(int)
        names = {}
        for guest in problem.guests:
            people[guest.group_id or "guest:" + guest.id] += 1
        for target, assignments in ((old, plan.assignments), (new, updated.assignments)):
            for assignment in assignments:
                target[assignment.group_id].append(assignment.table_id)
                names[assignment.group_id] = assignment.group_name
        moves = [Movement(group_id=gid, party_name=names.get(gid, "Unnamed family"),
                          before=sorted(set(old[gid])), after=sorted(set(new[gid])),
                          people=people[gid])
                 for gid in sorted(groups) if sorted(old[gid]) != sorted(new[gid])]
        if instruction.group_id not in {m.group_id for m in moves} and instruction.action != "seat_pending":
            return GenericReassignResponse(status="blocked",
                                           blockers=["The direction did not change this family's placement."])
        before = {score.rule_id: score.points for score in plan.score_breakdown}
        after = {score.rule_id: score.points for score in updated.score_breakdown}
        names_by_id = {rule.id: rule.display_name for rule in problem.rules}
        warnings = [names_by_id.get(rule_id, "Consideration") + ": " + str(before[rule_id] - after.get(rule_id, 0)) +
                    " fewer points"
                    for rule_id in before if after.get(rule_id, 0) < before[rule_id]]
        title = ("Seat pending family" if instruction.action == "seat_pending" else
                 "Move family to chosen destination" if instruction.action == "move_to" else
                 "Keep family away from chosen location")
        return GenericReassignResponse(status="available", options=[
            GenericReassignOption(
                id="v2-option-1", kind="solver-checked", title=title,
                movements=moves, score_delta=(updated.total_score or 0) - (plan.total_score or 0),
                soft_rule_warnings=warnings, plan=updated,
            )
        ])

    @app.post("/v1/layouts/import", response_model=VenueLayout)
    def import_venue(request: LayoutImportRequest) -> VenueLayout:
        sources = []
        for item in request.files:
            try:
                content = base64.b64decode(item.content_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"Invalid base64 input: {item.filename}") from exc
            sources.append((item.filename, content))
        try:
            return import_layout_files(sources, zones=request.zones, tables=request.tables)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/configurations/validate", response_model=VenueConfiguration)
    def validate_configuration(configuration: VenueConfiguration) -> VenueConfiguration:
        """Validate a portable guest-free configuration without saving it server-side."""
        return configuration

    @app.post("/v1/solve", response_model=Plan)
    def solve_problem(problem: Problem) -> Plan:
        try:
            return solve(problem)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/reassign/options", response_model=ReassignResponse)
    def reassignment_options(request: ReassignRequest) -> ReassignResponse:
        try:
            return propose_reassignment(request)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/exports/table", response_class=PlainTextResponse)
    def table_export(plan: Plan) -> str:
        return render_table(plan)

    @app.post("/v1/exports/json")
    def json_export(plan: Plan) -> Response:
        return Response(content=render_json(plan), media_type="application/json")

    @app.post("/v1/exports/people-list/html", response_class=HTMLResponse)
    def people_list_export(
        plan: Plan, group_by: Literal["combined", "floor"] = Query(default="combined"),
        include_reasons: bool = Query(default=False),
        fields: list[str] | None = Query(default=None),
        field_labels: list[str] | None = Query(default=None),
    ) -> HTMLResponse:
        try:
            return HTMLResponse(render_people_list_html(
                plan, group_by=group_by, include_reasons=include_reasons,
                fields=fields, field_labels=field_labels
            ))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/exports/table-list/html", response_class=HTMLResponse)
    def table_list_export(
        plan: Plan, group_by: Literal["combined", "table"] = Query(default="combined"),
        include_reasons: bool = Query(default=False),
        fields: list[str] | None = Query(default=None),
    ) -> HTMLResponse:
        try:
            return HTMLResponse(render_table_list_html(
                plan, group_by=group_by, include_reasons=include_reasons, fields=fields
            ))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/exports/not-seated-list/html", response_class=HTMLResponse)
    def not_seated_list_export(plan: Plan) -> HTMLResponse:
        """Print only explicit Plan.not_seated selections, even after an alarm."""
        try:
            return HTMLResponse(render_not_seated_list_html(plan))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/exports/floor-map/svg", response_model=SvgFloorBundle)
    def floor_map_svg_export(plan: Plan) -> SvgFloorBundle:
        try:
            return render_floor_svg(plan)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/exports/floor-map/pdf")
    def floor_map_pdf_export(plan: Plan) -> Response:
        try:
            pdf = render_floor_pdf(plan)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="floor-maps.pdf"'})

    @app.post("/v1/exports/table-cards/pdf")
    def table_cards_pdf_export(
        plan: Plan, cards_per_page: int = Query(default=1)
    ) -> Response:
        if cards_per_page not in (1, 2, 4):
            raise HTTPException(status_code=422, detail="cards_per_page must be 1, 2 or 4")
        try:
            pdf = render_table_cards_pdf(plan, cards_per_page=cards_per_page)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="table-cards.pdf"'})

    @app.get("/openapi.yaml", response_class=PlainTextResponse)
    def openapi_yaml() -> str:
        return files("seating_optimizer.api").joinpath("openapi.yaml").read_text(encoding="utf-8")

    web_dir = Path(__file__).parent / "web"

    @app.get("/", include_in_schema=False)
    def visual_client() -> FileResponse:
        return FileResponse(web_dir / "index.html", media_type="text/html")

    @app.get("/assets/app.js", include_in_schema=False)
    def visual_client_script() -> FileResponse:
        return FileResponse(web_dir / "app.js", media_type="text/javascript")

    @app.get("/assets/plan-selection.js", include_in_schema=False)
    def visual_plan_selection_script() -> FileResponse:
        return FileResponse(web_dir / "plan-selection.js", media_type="text/javascript")

    @app.get("/assets/plan-workspace.js", include_in_schema=False)
    def visual_plan_workspace_script() -> FileResponse:
        return FileResponse(web_dir / "plan-workspace.js", media_type="text/javascript")

    @app.get("/assets/v2-rules.js", include_in_schema=False)
    def visual_v2_rules_script() -> FileResponse:
        return FileResponse(web_dir / "v2-rules.js", media_type="text/javascript")

    @app.get("/assets/style.css", include_in_schema=False)
    def visual_client_styles() -> FileResponse:
        return FileResponse(web_dir / "style.css", media_type="text/css")

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def scalar_docs() -> str:
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Seating Plan Optimizer API</title></head>
<body><script id="api-reference" data-url="/openapi.yaml"></script>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script></body></html>"""

    return app


app = create_app()
