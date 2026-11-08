"""Thin, stateless FastAPI adapter over the Python package."""
from __future__ import annotations

import base64
import binascii
from importlib.resources import files

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from seating_optimizer import Plan, Problem, import_registrations, render_json, render_table, solve
from seating_optimizer.importer import ImportResult


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

    @app.post("/v1/solve", response_model=Plan)
    def solve_problem(problem: Problem) -> Plan:
        try:
            return solve(problem)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/exports/table", response_class=PlainTextResponse)
    def table_export(plan: Plan) -> str:
        return render_table(plan)

    @app.post("/v1/exports/json")
    def json_export(plan: Plan) -> Response:
        return Response(content=render_json(plan), media_type="application/json")

    @app.get("/openapi.yaml", response_class=PlainTextResponse)
    def openapi_yaml() -> str:
        return files("seating_optimizer.api").joinpath("openapi.yaml").read_text(encoding="utf-8")

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def scalar_docs() -> str:
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Seating Plan Optimizer API</title></head>
<body><script id="api-reference" data-url="/openapi.yaml"></script>
<script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script></body></html>"""

    return app


app = create_app()
