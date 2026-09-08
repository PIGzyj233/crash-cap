"""Bounded, verified disk material shared by concurrent HTTP readers.

One source process owns this directory. Visibility is checked by the caller on
every request, before acquiring a content lease. Readers pin files until their
response closes; decoding capacity is independent of download capacity.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..storage import ObjectStore
from .catalog_materials import CatalogMaterial, CatalogMaterialError, materialize_catalog_file


@dataclass
class Entry:
    path: Path
    size: int
    used_at: float
    readers: int = 0
    signature: tuple[int, int] | None = None


class MaterialCache:
    def __init__(self, settings: Settings, store: ObjectStore):
        self.settings, self.store = settings, store
        self.root = settings.catalog_source_cache_root
        self.condition = threading.Condition()
        self.entries: dict[str, Entry] = {}
        self.pending: dict[str, int] = {}
        self.weight = 0
        self.initialized = False

    def _initialize(self) -> None:
        if self.initialized:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        for path in self.root.iterdir():
            if (
                path.is_file()
                and not path.is_symlink()
                and re.fullmatch(r"[0-9a-f]{64}\.blob", path.name)
            ):
                self.entries[path.stem] = Entry(path, path.stat().st_size, path.stat().st_mtime)
            elif path.is_dir() and not path.is_symlink() and path.name.startswith("staging-"):
                shutil.rmtree(path)
        self.initialized = True

    def _evict(self, required: int) -> bool:
        occupied = sum(e.size for e in self.entries.values()) + sum(self.pending.values())
        for key, entry in sorted(self.entries.items(), key=lambda item: item[1].used_at):
            if occupied + required <= self.settings.catalog_source_cache_bytes:
                break
            if entry.readers or key in self.pending:
                continue
            entry.path.chmod(0o600)
            entry.path.unlink(missing_ok=True)
            occupied -= entry.size
            del self.entries[key]
        return occupied + required <= self.settings.catalog_source_cache_bytes

    def acquire(self, material: CatalogMaterial) -> tuple[Path, bool]:
        key = material.raw_sha256
        deadline = time.monotonic() + self.settings.catalog_source_wait_seconds
        reserved = material.raw_size + max((p.payload_size for p in material.locations), default=0)
        weight = min(reserved, self.settings.catalog_source_materialize_bytes)
        with self.condition:
            self._initialize()
            while True:
                entry = self.entries.get(key)
                if entry is not None and key not in self.pending:
                    try:
                        stat = entry.path.stat()
                        signature = (stat.st_size, stat.st_mtime_ns)
                        if stat.st_size != material.raw_size:
                            raise CatalogMaterialError("CATALOG_CACHE_SIZE_MISMATCH", "permanent")
                        # Verify retained disk bytes once after restart or external
                        # mutation. Normal GET/HEAD/Range reuse the prior proof.
                        if entry.signature != signature:
                            with entry.path.open("rb") as stream:
                                if hashlib.file_digest(stream, "sha256").hexdigest() != key:
                                    raise CatalogMaterialError(
                                        "CATALOG_CACHE_HASH_MISMATCH", "permanent"
                                    )
                            entry.signature = signature
                    except FileNotFoundError:
                        del self.entries[key]
                        continue
                    entry.readers += 1
                    entry.used_at = time.time()
                    return entry.path, True
                if (
                    key not in self.pending
                    and len(self.pending) < self.settings.catalog_source_max_concurrent
                    and self.weight + weight <= self.settings.catalog_source_materialize_bytes
                    and self._evict(reserved)
                ):
                    self.pending[key] = reserved
                    self.weight += weight
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CatalogMaterialError("CATALOG_SOURCE_BUSY", "transient")
                self.condition.wait(remaining)
        root = None
        try:
            root = Path(tempfile.mkdtemp(prefix="staging-", dir=self.root))
            path = root / "material"
            materialize_catalog_file(self.store, material, path)
            destination = self.root / f"{key}.blob"
            path.replace(destination)
            destination.chmod(0o444)
            stat = destination.stat()
            with self.condition:
                self.entries[key] = Entry(
                    destination, material.raw_size, time.time(), 1, (stat.st_size, stat.st_mtime_ns)
                )
            return destination, False
        except OSError as error:
            raise CatalogMaterialError("CATALOG_CACHE_IO_FAILED", "transient") from error
        finally:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)
            with self.condition:
                self.pending.pop(key, None)
                self.weight -= weight
                self.condition.notify_all()

    def release(self, material: CatalogMaterial) -> None:
        with self.condition:
            self.entries[material.raw_sha256].readers -= 1
            self.condition.notify_all()
