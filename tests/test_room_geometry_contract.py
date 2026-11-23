"""Cross-stack polygon acceptance uses the same fixtures as the browser helper."""
import json
from pathlib import Path
from seating_optimizer.room_geometry import rectangle_inside


def test_room_geometry_contract():
    path = Path(__file__).parent / "fixtures" / "room_geometry.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    for case in cases:
        assert rectangle_inside(case["outline"], *case["rect"]) is case["fits"], case["case"]
