"""Thin, stateless FastAPI adapter over the Python package."""
from __future__ import annotations

import base64
import binascii
from importlib.resources import files
from pathlib import Path
from typing import Literal

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
from seating_optimizer.reassignment import ReassignRequest, ReassignResponse, propose_reassignment


class LayoutFile(BaseModel):
    filename: str
    content_base64: str


class LayoutImportRequest(BaseModel):
    files: list[LayoutFile] = Field(min_length=1)
    zones: list[Zone] | None = None
    tables: list[Table] | None = None


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
