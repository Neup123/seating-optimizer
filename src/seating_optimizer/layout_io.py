"""Portable layout import: structured JSON or annotated numbered SVG drafts.

The SVG conversion deliberately uses explicit data-table-id labels rather than
guessing table identities from an unstructured bitmap or untrusted OCR.
"""
from __future__ import annotations

from collections.abc import Sequence

from defusedxml import ElementTree as SafeET

from .models import (
    FloorLayout, Table, TableDrawing, VenueLayout, Zone, validate_layout_references,
)


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _number(value: str | None, name: str) -> float:
    try:
        if value is None or not value.strip() or value.strip().endswith("%"):
            raise ValueError()
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"SVG has invalid numeric {name}: {value!r}") from exc
    if not -100000.0 < parsed < 100000.0:
        raise ValueError(f"SVG {name} is out of supported range")
    return parsed


def _svg_floor(content: bytes) -> FloorLayout:
    """Convert one annotated floor draft without image recognition.

    The root is <svg data-zone-id="ground" viewBox="0 0 600 400">.
    Each table is grouped as <g data-table-id="T1"><rect .../><text>T1</text></g>
    (ellipse and circle supported as well). Transforms are rejected rather
    than giving incorrectly placed tables.
    """
    if len(content) > 2_000_000:
        raise ValueError("SVG draft exceeds the 2 MB import limit")
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:
        raise ValueError(f"Invalid or unsafe SVG draft: {exc}") from exc
    if _tag(root) != "svg":
        raise ValueError("SVG layout must have an svg root element")
    zone_id = root.get("data-zone-id")
    if not zone_id:
        raise ValueError("SVG draft root must specify data-zone-id")
    view_box = (root.get("viewBox") or "").replace(",", " ").split()
    if len(view_box) != 4:
        raise ValueError("SVG floor layout requires viewBox='0 0 width height'")
    bx, by, width, height = (_number(v, "viewBox") for v in view_box)
    if bx != 0 or by != 0:
        raise ValueError("SVG viewBox origin must be 0 0")
    drawings = []
    for element in root.iter():
        if element.get("transform"):
            raise ValueError("SVG transforms are not supported in numbered layout drafts")
        if _tag(element) != "g" or not element.get("data-table-id"):
            continue
        table_id = element.get("data-table-id")
        shapes = [node for node in element.iter() if _tag(node) in {"rect", "ellipse", "circle"}]
        if len(shapes) != 1:
            raise ValueError(f"Table {table_id} needs exactly one rect, ellipse or circle")
        node = shapes[0]
        kind = _tag(node)
        if kind == "rect":
            x, y = _number(node.get("x", "0"), "x"), _number(node.get("y", "0"), "y")
            w, h = _number(node.get("width"), "width"), _number(node.get("height"), "height")
            shape = "rectangle"
        else:
            cx, cy = _number(node.get("cx"), "cx"), _number(node.get("cy"), "cy")
            rx = _number(node.get("r" if kind == "circle" else "rx"), "radius-x")
            ry = rx if kind == "circle" else _number(node.get("ry"), "radius-y")
            x, y, w, h = cx - rx, cy - ry, rx * 2, ry * 2
            shape = kind
        numbered = ["".join(node.itertext()).strip() for node in element.iter()
                    if _tag(node) == "text" and "".join(node.itertext()).strip()]
        if numbered and (len(numbered) != 1 or numbered[0] != table_id):
            raise ValueError(f"Table {table_id} text label must match its data-table-id")
        priority = element.get("data-small-group-priority", "false").lower()
        if priority not in ("true", "false", "1", "0"):
            raise ValueError(f"Table {table_id} has invalid small-group priority flag")
        drawings.append(TableDrawing(table_id=table_id, x=x, y=y,
                                     width=w, height=h, shape=shape,
                                     small_group_priority=priority in ("true", "1")))
    if not drawings:
        raise ValueError("SVG draft must contain at least one numbered table group")
    return FloorLayout(zone_id=zone_id, width=width, height=height, tables=drawings)


def import_layout(
    content: bytes, filename: str,
    *,
    zones: list[Zone] | None = None,
    tables: list[Table] | None = None,
) -> VenueLayout:
    """Import a complete JSON venue layout or one annotated SVG floor draft."""
    if filename.casefold().endswith(".json"):
        if len(content) > 2_000_000:
            raise ValueError("JSON layout exceeds the 2 MB import limit")
        layout = VenueLayout.model_validate_json(content)
    elif filename.casefold().endswith(".svg"):
        layout = VenueLayout(floors=[_svg_floor(content)])
    else:
        raise ValueError("Supported venue layout files are JSON and annotated SVG")
    if (zones is None) != (tables is None):
        raise ValueError("Provide both zones and tables to validate layout references")
    if zones is not None and tables is not None:
        validate_layout_references(layout, zones, tables)
    return layout


def import_layout_files(
    sources: Sequence[tuple[str, bytes]],
    *,
    zones: list[Zone] | None = None,
    tables: list[Table] | None = None,
) -> VenueLayout:
    """Combine multiple per-floor SVGs and/or JSON layouts into one venue layout."""
    if not sources:
        raise ValueError("At least one layout file is required")
    floors = []
    for filename, content in sources:
        floors.extend(import_layout(content, filename).floors)
    layout = VenueLayout(floors=floors)
    if (zones is None) != (tables is None):
        raise ValueError("Provide both zones and tables to validate layout references")
    if zones is not None and tables is not None:
        validate_layout_references(layout, zones, tables)
    return layout
