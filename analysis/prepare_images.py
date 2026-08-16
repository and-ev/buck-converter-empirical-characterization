"""Create web-ready project images from the supplied originals.

The source photographs remain untouched under ``images/source``. This script
only rotates, scales, and recompresses selected copies for README presentation.
"""

from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "images" / "source"
OUTPUT = ROOT / "images" / "featured"

SELECTIONS = {
    "components.jpg": ("IMG_7454.jpg", 0),
    "active-test-bench.jpg": ("IMG_7518.jpg", 90),
    "instrumentation.jpg": ("IMG_7519.jpg", 90),
    "current-sensor-wiring.jpg": ("IMG_7520.jpg", 90),
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for output_name, (source_name, angle) in SELECTIONS.items():
        with Image.open(SOURCE / source_name) as image:
            prepared = ImageOps.exif_transpose(image).convert("RGB")
            if angle:
                prepared = prepared.rotate(angle, expand=True)
            prepared.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            prepared.save(
                OUTPUT / output_name,
                format="JPEG",
                quality=88,
                optimize=True,
                progressive=True,
            )
        print(f"Saved images/featured/{output_name}")


if __name__ == "__main__":
    main()
