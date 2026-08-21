from __future__ import annotations

import subprocess
from pathlib import Path

from crashcap_api.config import Settings
from crashcap_api.ids import validate_id


class SymbolIngestError(RuntimeError):
    pass


class SymbolIngestor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def publish_pair(self, workspace_id: str, pe_path: Path, pdb_path: Path) -> None:
        validate_id(workspace_id, "wsp")
        if self.settings.symbol_ingest_mode == "fake":
            return
        destination = (self.settings.unified_symbol_root / workspace_id).resolve()
        root = self.settings.unified_symbol_root.resolve()
        if root not in destination.parents:
            raise SymbolIngestError("Workspace symbol path escaped the Unified root")
        destination.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(  # noqa: S603 - fixed argv, never a shell
            [
                self.settings.symsorter_command,
                "--output",
                str(destination),
                str(pe_path),
                str(pdb_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
        )
        if result.returncode != 0:
            raise SymbolIngestError(
                f"symsorter exited {result.returncode}: {result.stderr[-2000:]}"
            )
