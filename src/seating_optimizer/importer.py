"""CSV/XLSX registration import with explicit mapping and data-driven auto detection."""
from __future__ import annotations

import csv
import json
import re
from difflib import SequenceMatcher
from io import BytesIO, StringIO
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError
from openpyxl.utils.exceptions import InvalidFileException
from importlib.resources import files
from typing import Literal

from openpyxl import load_workbook
from pydantic import Field

from .display import distinct_party_name
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
    """Map confident aliases and small header typos; leave ambiguity for manual mapping.

    Exact canonical/alias matches outrank fuzzy matches. Short labels like
    "Side" must never fuzzy-match "Size". At most one source column is
    auto-mapped to a canonical target; other columns remain available to map.
    """
    aliases = default_aliases() if aliases is None else aliases
    candidates: dict[str, tuple[str, float]] = {}
    issues: list[ImportIssue] = []
    normalized = {target: {_normalize(v) for v in [target, *choices]}
                  for target, choices in aliases.items()}
    for header in headers:
        label = _normalize(header)
        if not label:
            continue
        scored = {}
        for target, choices in normalized.items():
            if label == _normalize(target):
                scored[target] = 3.0
            elif label in choices:
                scored[target] = 2.0
            elif len(label) >= 6:
                # Restrict fuzzy detection to same-length-ish substantial labels.
                # A typo must be very close to a known name, not merely related.
                similarity = max(
                    (SequenceMatcher(None, label, choice).ratio()
                     for choice in choices
                     if len(choice) >= 6 and abs(len(label) - len(choice)) <= 2),
                    default=0.0,
                )
                if similarity >= 0.88:
                    scored[target] = similarity
        if not scored:
            continue
        best = max(scored.values())
        winners = [target for target, score in scored.items() if best - score < 0.02]
        if len(winners) == 1:
            candidates[header] = (winners[0], best)
        else:
            issues.append(ImportIssue(row=1, column=header, severity="warning",
                                      message=f"Ambiguous header {header!r}: {', '.join(winners)}. Map it manually."))

    detected: dict[str, str] = {}
    for target in aliases:
        matches = [(header, score) for header, (candidate, score) in candidates.items()
                   if candidate == target]
        if not matches:
            continue
        highest = max(score for _, score in matches)
        winners = [header for header, score in matches if score == highest]
        if len(winners) == 1:
            detected[winners[0]] = target
        else:
            issues.append(ImportIssue(row=1, column=None, severity="warning",
                                      message=(f"Multiple matching columns for {target}: "
                                               f"{', '.join(winners)}. Select one manually.")))
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
    name, size, group_id, group_name or attribute.<user-defined-kind>. Unmapped source data
    is retained as a free-form guest attribute, never silently discarded.
    """
    result = ImportResult()
    try:
        rows = _rows(content, filename)
    except (UnicodeError, csv.Error, OSError, ValueError, BadZipFile, InvalidFileException, ParseError) as exc:
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
        if target not in {"name", "size", "group_id", "group_name"} and (
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
    # A shared Group ID may span individually named rows. Do not turn any
    # member's own name into a party name just because it was the first row.
    party_rows: dict[str, list[tuple[str, int, str | None]]] = {}
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
        mapped_group_name = str(mapped.get("group_name") or "").strip() or None
        party_rows.setdefault(group_id, []).append((name, n, mapped_group_name))
        attrs = {}
        for source in headers:
            value = values[source]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            target = mapping_out.get(source)
            if target in ("name", "size", "group_id", "group_name"):
                continue
            key = target.removeprefix("attribute.") if target else source
            if isinstance(value, (str, int, float, bool)):
                attrs[key] = value
            else:
                attrs[key] = str(value)
        for i in range(n):
            result.guests.append(Guest(id=f"r{row_number}-m{i+1}",
                   name=name if n == 1 else f"{name} ({i+1}/{n})",
                   group_id=group_id, group_name=None, attributes=attrs))
        result.rows_imported += 1

    grouped: dict[str, list[Guest]] = {}
    for guest in result.guests:
        grouped.setdefault(guest.group_id, []).append(guest)
    for group_id, members in grouped.items():
        sources = party_rows[group_id]
        explicit = [label for _, _, label in sources if label]
        # A single registration's name is the party label at every size,
        # including size 1. Shared IDs need an explicit party-name column.
        inferred = sources[0][0] if len(sources) == 1 else None
        label = distinct_party_name(
            group_id, explicit if explicit else [inferred],
            [guest.name for guest in members])
        for guest in members:
            guest.group_name = label
    return result


class ImportPreview(Model):
    """Header/sample inspection without committing any imported guests."""
    headers: list[str] = Field(default_factory=list)
    detected_mapping: dict[str, str] = Field(default_factory=dict)
    mapping: dict[str, str] = Field(default_factory=dict)
    targets: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, str]] = Field(default_factory=list)
    issues: list[ImportIssue] = Field(default_factory=list)
    rows_seen: int = 0


def preview_registrations(
    content: bytes,
    filename: str,
    mapping: dict[str, str] | None = None,
    aliases: dict[str, list[str]] | None = None,
    sample_limit: int = 5,
) -> ImportPreview:
    """Use the exact same parsing and detection logic as the actual importer.

    Designed for clients that must show headers before a user can correct
    automatic mapping; requires no browser-side CSV/XLSX parsing.
    """
    if not 0 <= sample_limit <= 25:
        raise ValueError("sample_limit must be between 0 and 25")
    result = ImportPreview()
    if len(content) > 10_000_000:
        result.issues.append(ImportIssue(row=None, column=None, severity="error",
                                         message="Spreadsheet exceeds the 10 MB preview limit"))
        return result
    try:
        rows = _rows(content, filename)
    except (UnicodeError, csv.Error, OSError, ValueError, KeyError, BadZipFile, InvalidFileException, ParseError) as exc:
        result.issues.append(ImportIssue(row=None, column=None, severity="error", message=str(exc)))
        return result
    if not rows:
        result.issues.append(ImportIssue(row=1, column=None, severity="error", message="Empty spreadsheet"))
        return result
    result.headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    if not all(result.headers) or len(result.headers) != len(set(result.headers)):
        result.issues.append(ImportIssue(row=1, column=None, severity="error",
                                         message="Headers must be nonempty and unique"))
        return result
    choices = default_aliases() if aliases is None else aliases
    result.targets = list(choices)
    result.detected_mapping, warnings = detect_headers(result.headers, choices)
    result.rows_seen = sum(1 for raw in rows[1:]
                           if any(v is not None and str(v).strip() for v in raw))
    for raw in rows[1:1 + sample_limit]:
        result.sample_rows.append({
            h: str(raw[i]) if i < len(raw) and raw[i] is not None else ""
            for i, h in enumerate(result.headers)
        })
    imported = import_registrations(content, filename, mapping=mapping, aliases=choices)
    result.mapping = imported.mapping
    # The preview remains editable when a required column was not detected.
    # Final import still validates size/name strictly; never invent group sizes.
    result.issues = [
        ImportIssue(row=issue.row, column=issue.column,
                    severity="warning" if issue.message.startswith("Missing required mapping:") else issue.severity,
                    message=(issue.message + ". Select a source column under Map columns "
                             "or add the missing column to the spreadsheet."
                             if issue.message.startswith("Missing required mapping:") else issue.message))
        for issue in imported.issues
    ]
    # Detection warnings are already included by import_registrations.
    return result
