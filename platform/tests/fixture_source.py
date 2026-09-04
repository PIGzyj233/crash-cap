"""Keep compiler paths independent from the host executing native qualification."""

import json
from pathlib import Path, PureWindowsPath


def fixture_source_root(fixture: Path) -> str:
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8-sig"))
    root = manifest.get("generator", {}).get("source_root")
    if not isinstance(root, str) or not PureWindowsPath(root).is_absolute():
        raise ValueError("Fixture lacks an absolute compiler source_root; rerun build_p0_b01.ps1")
    return root
