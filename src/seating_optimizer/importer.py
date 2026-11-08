"""CSV/XLSX registration import with explicit mapping and data-driven auto detection."""
from __future__ import annotations

import csv
import json
import re
from io import BytesIO, StringIO
from importlib.resources import files
from typing import Literal

from openpyxl import load_workbook
from pydantic import Field

from .models import Guest, Model


class ImportIssue(Model):
    row: int | None
    column: str | None
    severity: Literal["error", "warning"]
    message: str


class ImportResult(Model):
    guests: list[Guest] = Field(default_factory=list)
    mapping: dict[str, str] = Field(default_factory=dict)
    issues: list[ImportIssue] = Field(default_factory=list)
    rows_seen: int = 0
    rows_imported: int = 0

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


def default_aliases() -> dict[str, list[str]]:
    return json.loads(files("seating_optimizer").joinpath("header_aliases.json").read_text(encoding="utf-8"))


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value).casefold(), flags=re.UNICODE)


def detect_headers(headers: list[str], aliases: dict[str, list[str]] | None = None) -> tuple[dict[str, str], list[ImportIssue]]:
    """Return source-column -> canonical target; ambiguous matches are errors."""
    aliases = default_aliases() if aliases is None else aliases
    detected = {}
    issues = []
    for header in headers:
        matches = [target for target, choices in aliases.items()
                   if _normalize(header) in {_normalize(v) for v in [target, *choices]}]
        if len(matches) == 1:
            detected[header] = matches[0]
        elif len(matches) > 1:
            issues.append(ImportIssue(row=1, column=header, severity="error",
                                      message=f"Ambiguous header {header!r}: {', '.join(matches)}"))
    return detected, issues


def _rows(content: bytes, filename: str) -> list[list]:
    lower = filename.casefold()
    if lower.endswith(".csv"):
        data = content.decode("utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(data[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.reader(StringIO(data), dialect=dialect, strict=True))
    if lower.endswith(".xlsx"):
        book = load_workbook(BytesIO(content), read_only=True, data_only=True)
        try:
            return [list(row) for row in book.active.iter_rows(values_only=True)]
        finally:
            book.close()
    raise ValueError("Supported import formats are CSV and XLSX")


def import_registrations(
    content: bytes,
    filename: str,
    mapping: dict[str, str] | None = None,
    aliases: dict[str, list[str]] | None = None,
) -> ImportResult:
    """Each source row is one registration. Size N expands to N atomic-group guests.

    Mapping direction is source header -> canonical target. Canonical fields are
    name, size, group_id or attribute.<user-defined-kind>. Unmapped source data
    is retained as a free-form guest attribute, never silently discarded.
    """
    result = ImportResult()
    try:
        rows = _rows(content, filename)
    except (UnicodeError, csv.Error, OSError, ValueError) as exc:
        result.issues.append(ImportIssue(row=None, column=None, severity="error", message=str(exc)))
        return result
    if not rows:
        result.issues.append(ImportIssue(row=1, column=None, severity="error", message="Empty spreadsheet"))
        return result
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    if not all(headers) or len(headers) != len(set(headers)):
        result.issues.append(ImportIssue(row=1, column=None, severity="error",
                      message="Headers must be nonempty and unique"))
        return result
    detected, detection_issues = detect_headers(headers, aliases)
    manual = mapping or {}
    for source, target in manual.items():
        if source not in headers:
            result.issues.append(ImportIssue(row=1, column=source, severity="error",
                                              message="Mapped source column not found"))
        if target not in {"name", "size", "group_id"} and (
            not target.startswith("attribute.") or not target.removeprefix("attribute.")
        ):
            result.issues.append(ImportIssue(row=1, column=source, severity="error",
                                              message=f"Unsupported mapping target: {target}"))
    # Manual mapping takes precedence over auto-detected candidates for the same target.
    mapping_out = {src: target for src, target in detected.items()
                   if src not in manual and target not in manual.values()}
    mapping_out.update({source: target for source, target in manual.items() if source in headers})
    for src, target in mapping_out.items():
        if list(mapping_out.values()).count(target) > 1:
            result.issues.append(ImportIssue(row=1, column=src, severity="error",
                                              message=f"Multiple columns mapped to {target}"))
    result.mapping = mapping_out
    result.issues.extend(issue for issue in detection_issues if issue.column not in manual)
    for required in ("name", "size"):
        if required not in mapping_out.values():
            result.issues.append(ImportIssue(row=1, column=None, severity="error",
                                             message=f"Missing required mapping: {required}"))
    if result.has_errors:
        return result
    seen_names = {}
    for row_number, raw in enumerate(rows[1:], start=2):
        if not any(v is not None and str(v).strip() for v in raw):
            result.issues.append(ImportIssue(row=row_number, column=None, severity="warning",
                                             message="Blank row skipped"))
            continue
        result.rows_seen += 1
        if len(raw) > len(headers) and any(v is not None and str(v).strip() for v in raw[len(headers):]):
            result.issues.append(ImportIssue(row=row_number, column=None, severity="error",
                                             message="Row contains values beyond the header columns"))
            continue
        values = {head: raw[i] if i < len(raw) else None for i, head in enumerate(headers)}
        mapped = {target: values[source] for source, target in mapping_out.items()}
        name = str(mapped.get("name") or "").strip()
        if not name:
            result.issues.append(ImportIssue(row=row_number, column="name", severity="error",
                                             message="Guest/registration name missing"))
            continue
        if name.casefold() in seen_names:
            result.issues.append(ImportIssue(row=row_number, column="name", severity="error",
                              message=f"Duplicate registration name {name!r}; first at row {seen_names[name.casefold()]}"))
        else:
            seen_names[name.casefold()] = row_number
        size = mapped.get("size")
        try:
            if isinstance(size, bool) or size is None or str(size).strip() == "":
                raise ValueError
            n = int(size)
            if float(size) != n or not 1 <= n <= 10000:
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            result.issues.append(ImportIssue(row=row_number, column="size", severity="error",
                                    message=f"Invalid or missing group size {size!r}"))
            continue
        group_id = str(mapped.get("group_id") or f"registration:{row_number}").strip()
        attrs = {}
        for source in headers:
            value = values[source]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            target = mapping_out.get(source)
            if target in ("name", "size", "group_id"):
                continue
            key = target.removeprefix("attribute.") if target else source
            if isinstance(value, (str, int, float, bool)):
                attrs[key] = value
            else:
                attrs[key] = str(value)
        for i in range(n):
            result.guests.append(Guest(id=f"r{row_number}-m{i+1}",
                   name=name if n == 1 else f"{name} ({i+1}/{n})",
                   group_id=group_id, attributes=attrs))
        result.rows_imported += 1
    return result
