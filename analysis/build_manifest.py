"""Build a SHA-256 manifest for every supplied source artifact."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "source_manifest.json"
SOURCE_PATHS = [ROOT / "data" / "raw", ROOT / "images" / "source"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    files = sorted(
        file
        for directory in SOURCE_PATHS
        for file in directory.iterdir()
        if file.is_file()
    )
    manifest = {
        str(file.relative_to(ROOT)).replace("\\", "/"): {
            "bytes": file.stat().st_size,
            "sha256": sha256(file),
        }
        for file in files
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(manifest)} source artifacts in {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
