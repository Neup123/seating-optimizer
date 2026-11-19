"""Room-outline geometry for venue drawings (pure and transport-independent).

A room outline is a simple polygon, not a decorative overlay. It is optional:
legacy rectangular canvases still allow any drawing inside their bounds.
For safety we require each drawing's full rectangular bounding box to fit,
including ellipse/circle tables. That is conservative but never admits an
out-of-room table based solely on its centre.
"""
from __future__ import annotations

from math import isfinite

EPS = 1e-7
Point = tuple[float, float]


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_edge(point: Point, a: Point, b: Point) -> bool:
    return (abs(_cross(a, b, point)) < EPS
            and min(a[0], b[0]) - EPS <= point[0] <= max(a[0], b[0]) + EPS
            and min(a[1], b[1]) - EPS <= point[1] <= max(a[1], b[1]) + EPS)


def point_inside(point: Point, polygon: list[Point]) -> bool:
    """Inside or on polygon boundary; simple polygon is a precondition."""
    inside = False
    x, y = point
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        if _on_edge(point, a, b):
            return True
        if (a[1] > y) != (b[1] > y):
            x_at_y = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < x_at_y:
                inside = not inside
    return inside


def _intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Inclusive segment intersection (including collinear/touching)."""
    ca, cb = _cross(a, b, c), _cross(a, b, d)
    ac, ad = _cross(c, d, a), _cross(c, d, b)
    if (ca > EPS and cb < -EPS or ca < -EPS and cb > EPS) and (
            ac > EPS and ad < -EPS or ac < -EPS and ad > EPS):
        return True
    return ((abs(ca) < EPS and _on_edge(c, a, b)) or
            (abs(cb) < EPS and _on_edge(d, a, b)) or
            (abs(ac) < EPS and _on_edge(a, c, d)) or
            (abs(ad) < EPS and _on_edge(b, c, d)))


def validate_outline(points: list[Point], width: float, height: float) -> None:
    if not 3 <= len(points) <= 100:
        raise ValueError("Room outline must have between 3 and 100 corners")
    if any(not all(isfinite(n) for n in point) for point in points):
        raise ValueError("Room outline coordinates must be finite numbers")
    if any(x < 0 or y < 0 or x > width or y > height for x, y in points):
        raise ValueError("Room outline corner is outside floor canvas bounds")
    twice_area = sum(p[0] * points[(i + 1) % len(points)][1]
                     - points[(i + 1) % len(points)][0] * p[1]
                     for i, p in enumerate(points))
    if abs(twice_area) < EPS:
        raise ValueError("Room outline must enclose a nonzero area")
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        if abs(a[0] - b[0]) < EPS and abs(a[1] - b[1]) < EPS:
            raise ValueError("Room outline contains a repeated consecutive corner")
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        for j in range(i + 1, len(points)):
            if j == i + 1 or (i == 0 and j == len(points) - 1):
                continue
            c, d = points[j], points[(j + 1) % len(points)]
            if _intersects(a, b, c, d):
                raise ValueError("Room outline must not cross or touch itself")


def _segment_covered(a: Point, b: Point, polygon: list[Point]) -> bool:
    """Split at wall intersections and ensure each open interval stays inside."""
    if not (point_inside(a, polygon) and point_inside(b, polygon)):
        return False
    locations = [0.0, 1.0]
    dx, dy = b[0] - a[0], b[1] - a[1]
    for i, c in enumerate(polygon):
        d = polygon[(i + 1) % len(polygon)]
        ex, ey = d[0] - c[0], d[1] - c[1]
        denominator = dx * ey - dy * ex
        if abs(denominator) < EPS:
            if _on_edge(c, a, b):
                locations.append(((c[0] - a[0]) / dx) if abs(dx) > EPS else
                                 ((c[1] - a[1]) / dy))
            if _on_edge(d, a, b):
                locations.append(((d[0] - a[0]) / dx) if abs(dx) > EPS else
                                 ((d[1] - a[1]) / dy))
            continue
        t = ((c[0] - a[0]) * ey - (c[1] - a[1]) * ex) / denominator
        u = ((c[0] - a[0]) * dy - (c[1] - a[1]) * dx) / denominator
        if -EPS <= t <= 1 + EPS and -EPS <= u <= 1 + EPS:
            locations.append(max(0.0, min(1.0, t)))
    stops = sorted(set(locations))
    return all(point_inside((a[0] + dx * (lo + hi) / 2,
                             a[1] + dy * (lo + hi) / 2), polygon)
               for lo, hi in zip(stops, stops[1:]) if hi - lo > EPS)


def rectangle_inside(polygon: list[Point], x: float, y: float,
                     width: float, height: float) -> bool:
    corners = [(x, y), (x + width, y),
               (x + width, y + height), (x, y + height)]
    return all(_segment_covered(corners[i], corners[(i + 1) % 4], polygon)
               for i in range(4))
