"""Vector floor-map and printable table-card renderers.

Layout geometry is data in Plan.layout; this module needs no HTTP or UI.
SVG pages are portable for future editor clients. PDF pages are vector prints.
"""
from __future__ import annotations

from collections import defaultdict
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Literal

from pydantic import Field
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from .models import FloorLayout, Model, Plan, TableDrawing, VenueLayout


class SvgFloorPage(Model):
    zone_id: str
    svg: str


class SvgFloorBundle(Model):
    pages: list[SvgFloorPage] = Field(default_factory=list)


def _placed(plan: Plan) -> tuple[VenueLayout, dict[str, list]]:
    if plan.status not in ("optimal", "feasible"):
        raise ValueError("Printable seating exports require a feasible plan")
    if plan.layout is None:
        raise ValueError("Floor-map export requires plan.layout with floor geometry")
    table_zone = {table.table_id: table.zone_id for table in plan.tables}
    drawings = {}
    for floor in plan.layout.floors:
        for drawing in floor.tables:
            if drawing.table_id not in table_zone:
                raise ValueError(f"Drawing {drawing.table_id} does not match a plan table")
            if table_zone[drawing.table_id] != floor.zone_id:
                raise ValueError(f"Drawing {drawing.table_id} is on the wrong floor")
            drawings[drawing.table_id] = drawing
    missing = set(table_zone) - set(drawings)
    if missing:
        raise ValueError("Missing floor layout positions for tables: " + ", ".join(sorted(missing)))
    assignments = defaultdict(list)
    for assignment in plan.assignments:
        if assignment.table_id not in table_zone:
            raise ValueError(f"Assignment {assignment.group_id} has unknown table")
        assignments[assignment.table_id].append(assignment)
    return plan.layout, assignments


def _map_font(drawing: TableDrawing, line_count: int, longest: int) -> float:
    """Choose a readable size without silently dropping assigned groups."""
    available_width = drawing.width * (0.65 if drawing.shape != "rectangle" else 0.88)
    room_height = max(0, drawing.height - 14)
    size = min(11.0, available_width / max(1, longest) / 0.59,
               room_height / max(1, line_count) / 1.22)
    if size < 2.5:
        raise ValueError(f"Table {drawing.table_id} is too small to print all groups; enlarge its drawing")
    return size


def _table_labels(assignments: dict, table_id: str) -> list[tuple[str, str]]:
    return [
        (assignment.group_id, f"{assignment.group_id} ({len(assignment.guest_ids)}): {assignment.guest_names[0] if assignment.guest_names else assignment.group_id}")
        for assignment in assignments[table_id]
    ]


def render_floor_svg(plan: Plan) -> SvgFloorBundle:
    """One full SVG page per floor, with labelled geometries and group identities."""
    layout, assignments = _placed(plan)
    pages = []
    for floor in layout.floors:
        chunks = [
            f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
            f'width="{floor.width:g}" height="{floor.height:g}" '
            f'viewBox="0 0 {floor.width:g} {floor.height:g}" '
            f'data-zone-id="{escape(floor.zone_id, quote=True)}">',
            f'<title>Floor {escape(floor.zone_id)} — session {escape(plan.session_id)}</title>',
            f'<rect width="{floor.width:g}" height="{floor.height:g}" fill="white"/>',
        ]
        for drawing in floor.tables:
            table_id = escape(drawing.table_id, quote=True)
            x, y, width, height = drawing.x, drawing.y, drawing.width, drawing.height
            cx, cy = x + width / 2, y + height / 2
            chunks.append(f'<g data-table-id="{table_id}">')
            if drawing.shape == "rectangle":
                chunks.append(f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" '
                              f'fill="#f7f9fc" stroke="#253858" stroke-width="1.5"/>')
            else:
                chunks.append(f'<ellipse cx="{cx:g}" cy="{cy:g}" rx="{width/2:g}" ry="{height/2:g}" '
                              f'fill="#f7f9fc" stroke="#253858" stroke-width="1.5"/>')
            chunks.append(f'<text x="{cx:g}" y="{y+11:g}" text-anchor="middle" '
                          f'font-size="10" font-family="sans-serif" font-weight="bold">'
                          f'{escape(drawing.table_id)}</text>')
            labels = _table_labels(assignments, drawing.table_id)
            font = _map_font(drawing, len(labels), max((len(label) for _, label in labels), default=1))
            for i, (group_id, label) in enumerate(labels):
                y_at = y + 15 + font * 1.22 * (i + 1)
                chunks.append(f'<text data-group-id="{escape(group_id, quote=True)}" '
                              f'x="{cx:g}" y="{y_at:g}" text-anchor="middle" '
                              f'font-size="{font:g}" font-family="sans-serif">'
                              f'{escape(label)}</text>')
            chunks.append("</g>")
        chunks.append("</svg>")
        pages.append(SvgFloorPage(zone_id=floor.zone_id, svg="\n".join(chunks)))
    return SvgFloorBundle(pages=pages)


def _pdf_font() -> str:
    """Use a Unicode-capable system font when present; never package font files."""
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            if "SeatingPrint" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("SeatingPrint", str(path)))
            return "SeatingPrint"
    return "Helvetica"


def _check_pdf_text(texts: list[str], font: str) -> None:
    if font == "Helvetica" and any(ord(char) > 255 for text in texts for char in text):
        raise ValueError("Unicode guest names require a Unicode TrueType font on the server; SVG remains available")


def _draw_outline(doc: canvas.Canvas, floor: FloorLayout, drawing: TableDrawing, *, margin: float) -> tuple[float, float]:
    x = margin + drawing.x
    y = margin + floor.height - drawing.y - drawing.height
    if drawing.shape == "rectangle":
        doc.roundRect(x, y, drawing.width, drawing.height, 2, fill=0, stroke=1)
    else:
        doc.ellipse(x, y, x + drawing.width, y + drawing.height, fill=0, stroke=1)
    return x + drawing.width / 2, y + drawing.height


def render_floor_pdf(plan: Plan) -> bytes:
    """Vector PDF: exactly one page per floor, using the same geometry as SVG."""
    layout, assignments = _placed(plan)
    font_name = _pdf_font()
    labels = [
        f"{assignment.group_id} ({len(assignment.guest_ids)}): {assignment.guest_names[0] if assignment.guest_names else assignment.group_id}"
        for assignment in plan.assignments
    ] + [table.table_id for table in plan.tables]
    _check_pdf_text(labels, font_name)
    output = BytesIO()
    doc = canvas.Canvas(output, pageCompression=1)
    margin = 36
    for floor in layout.floors:
        doc.setPageSize((floor.width + 2 * margin, floor.height + 2 * margin + 24))
        doc.setTitle(f"Seating floor maps — {plan.session_id}")
        doc.setFont(font_name, 13)
        doc.drawString(margin, floor.height + margin + 22, f"Floor: {floor.zone_id} — {plan.session_id}")
        for drawing in floor.tables:
            center, top = _draw_outline(doc, floor, drawing, margin=margin)
            doc.setFont(font_name, 10)
            doc.drawCentredString(center, top - 11, drawing.table_id)
            guests = _table_labels(assignments, drawing.table_id)
            font_size = _map_font(drawing, len(guests), max((len(label) for _, label in guests), default=1))
            doc.setFont(font_name, font_size)
            for index, (_, label) in enumerate(guests):
                doc.drawCentredString(center, top - 15 - font_size * 1.22 * (index + 1), label)
        doc.showPage()
    doc.save()
    return output.getvalue()


def _wrap_card(text: str, font: str, font_size: float, max_width: float) -> list[str]:
    """Wrap without dropping names; preserve original text with each space split."""
    words = text.split(" ")
    lines, line = [], ""
    for word in words:
        if pdfmetrics.stringWidth(word, font, font_size) > max_width:
            raise ValueError(f"Card contains a word too long to print at {font_size:g}pt: {word[:40]}")
        candidate = (line + " " + word).strip()
        if line and pdfmetrics.stringWidth(candidate, font, font_size) > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def render_table_cards_pdf(plan: Plan, *, cards_per_page: int = 1) -> bytes:
    """Print one A5 card by default, or an A4 cut-ready grid of 2 or 4 cards."""
    if cards_per_page not in (1, 2, 4):
        raise ValueError("cards_per_page must be 1, 2 or 4")
    if plan.status not in ("optimal", "feasible"):
        raise ValueError("Table cards require a feasible plan")
    font = _pdf_font()
    all_labels = [name for a in plan.assignments for name in a.guest_names]
    _check_pdf_text(all_labels, font)
    cards = defaultdict(list)
    for group in plan.assignments:
        cards[group.table_id].append(group)
    table_ids = {t.table_id for t in plan.tables}
    if set(cards) - table_ids:
        raise ValueError("Cannot export cards with assignments to unknown tables")
    output = BytesIO()
    doc = canvas.Canvas(output, pagesize=landscape(A5), pageCompression=1)
    width, height = landscape(A5)
    if cards_per_page == 1:
        for table in plan.tables:
            doc.setPageSize((width, height))
            doc.setTitle(f"Table cards — {plan.session_id}")
            doc.setLineWidth(1)
            doc.roundRect(14, 14, width - 28, height - 28, 8)
            doc.setFont(font, 18)
            doc.drawCentredString(width / 2, height - 43, f"Table {table.table_id}")
            doc.setFont(font, 10)
            doc.drawCentredString(width / 2, height - 59,
                                  f"Zone {table.zone_id} | {table.occupied}/{table.capacity} chairs")
            groups = cards[table.table_id]
            entries = [f"{group.group_id} ({len(group.guest_ids)}): {', '.join(group.guest_names)}" for group in groups]
            if not entries:
                entries = ["No assigned groups"]
            for fontsize in (11.0, 10.0, 9.0, 8.0, 7.0, 6.0, 5.0):
                try:
                    lines = [line for entry in entries for line in
                             _wrap_card(entry, font, fontsize, width - 70)]
                except ValueError:
                    continue
                if len(lines) * fontsize * 1.3 <= height - 95:
                    break
            else:
                raise ValueError(f"Table {table.table_id} has too much text for one printable card")
            doc.setFont(font, fontsize)
            start_y = height - 85
            for line in lines:
                doc.drawString(35, start_y, line)
                start_y -= fontsize * 1.3
            doc.showPage()
    else:
        # Keep the previous A5 drawing path untouched for cards_per_page=1.
        # Two landscape A5 signs fit on portrait A4; four smaller cards
        # occupy an A4 landscape 2 x 2 cutting grid.
        cols = 1 if cards_per_page == 2 else 2
        rows = 2
        page_width, page_height = A4 if cards_per_page == 2 else landscape(A4)
        cell_width, cell_height = page_width / cols, page_height / rows

        for index, table in enumerate(plan.tables):
            slot = index % cards_per_page
            if slot == 0:
                if index:
                    doc.showPage()
                doc.setPageSize((page_width, page_height))
                doc.setTitle(f"Table cards — {plan.session_id}")
                # Light dotted cutting guides between the bordered cards.
                doc.saveState()
                doc.setStrokeColorRGB(0.65, 0.65, 0.65)
                doc.setLineWidth(0.5)
                doc.setDash(3, 3)
                doc.line(0, cell_height, page_width, cell_height)
                if cols == 2:
                    doc.line(cell_width, 0, cell_width, page_height)
                doc.restoreState()
            col = slot % cols
            row = slot // cols
            doc.saveState()
            doc.translate(col * cell_width, page_height - (row + 1) * cell_height)
            doc.setLineWidth(0.9)
            doc.roundRect(10, 10, cell_width - 20, cell_height - 20, 5)
            center_x = cell_width / 2
            doc.setFont(font, 18 if cards_per_page == 2 else 15)
            doc.drawCentredString(center_x, cell_height - 39, f"Table {table.table_id}")
            doc.setFont(font, 10 if cards_per_page == 2 else 9)
            doc.drawCentredString(center_x, cell_height - 56,
                                  f"Zone {table.zone_id} | {table.occupied}/{table.capacity} chairs")
            groups = cards[table.table_id]
            entries = [f"{group.group_id} ({len(group.guest_ids)}): {', '.join(group.guest_names)}" for group in groups]
            if not entries:
                entries = ["No assigned groups"]
            available_width = cell_width - 50
            start_y = cell_height - 76
            for fontsize in (11.0, 10.0, 9.0, 8.0, 7.0, 6.0):
                try:
                    lines = [line for entry in entries for line in
                             _wrap_card(entry, font, fontsize, available_width)]
                except ValueError:
                    continue
                if len(lines) * fontsize * 1.3 <= start_y - 22:
                    break
            else:
                raise ValueError(f"Table {table.table_id} has too much text for {cards_per_page} cards per page")
            doc.setFont(font, fontsize)
            for line in lines:
                doc.drawString(25, start_y, line)
                start_y -= fontsize * 1.3
            doc.restoreState()
        if plan.tables:
            doc.showPage()
    doc.save()
    return output.getvalue()
