"""Copy five *real browser test* screenshots into the README gallery.

Runs only after the golden Playwright test has generated screenshots from
synthetic guest data. Fails closed when a named state wasn't captured.
"""
from pathlib import Path

from PIL import Image

STATES = {
    "02-import-mapping.png": "guest-import.jpg",
    "04-venue-tables.png": "venue-editor.jpg",
    "06-rules-accordion.png": "rules.jpg",
    "10-plan-selected.png": "working-plan.jpg",
    "14-print-tables.png": "print-preview.jpg",
}


def main() -> None:
    source = Path("test-results")
    target = Path("docs/screenshots")
    target.mkdir(parents=True, exist_ok=True)
    for screenshot, out_name in STATES.items():
        candidates = list(source.rglob(screenshot))
        if len(candidates) != 1:
            raise RuntimeError(f"Expected exactly one real browser screenshot for {screenshot}, found {len(candidates)}")
        with Image.open(candidates[0]) as image:
            frame = image.convert("RGB")
            if frame.width > 1280:
                frame.thumbnail((1280, 1500), Image.Resampling.LANCZOS)
            frame.save(target / out_name, "JPEG", quality=83, optimize=True, progressive=True)
        print(f"Captured {out_name} from {candidates[0]}")


if __name__ == "__main__":
    main()
