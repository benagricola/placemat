"""The shared model cache: converted meshes by content id, in the user's own cache folder, used by every project and every studio.

`<folder>/v<converter version>-<id>.pmm` is a mesh and `.fail` the message of a conversion that failed (not retried until the version
changes or `retry`). A file is written under a temporary name and renamed, so a reader never sees half a file and two processes may share
the folder. Each use touches the file's mtime; over the size bound the least recently used files are removed until the folder is 20% under
it, never one in use by the plan on screen."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

from .model_mesh import CONVERTER_VERSION

_VERSIONED = re.compile(r"^v(\d+)-")


def default_dir(setting: str = "") -> Path:
    """`studio_3d_cache_dir` when set, else the platform's user cache folder: $XDG_CACHE_HOME (default ~/.cache) on Linux,
    ~/Library/Caches on macOS, the local app-data folder on Windows, then `placemat/models`."""
    if setting:
        return Path(setting).expanduser()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "placemat" / "models"


class Cache:
    def __init__(self, folder, mb: int = 512):
        self.dir, self.bound = Path(folder), int(mb) * 1024 * 1024

    def name(self, id: str, ext: str = "pmm") -> str:
        return "v%d-%s.%s" % (CONVERTER_VERSION, id, ext)

    def _ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def put(self, id: str, data: bytes) -> Path:
        return self._write(self.name(id), data)

    def _write(self, name: str, data: bytes) -> Path:
        self._ensure()
        fd, tmp = tempfile.mkstemp(dir=str(self.dir), prefix=name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, self.dir / name)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return self.dir / name

    def get(self, id: str) -> Path | None:
        """The mesh file for `id`, its use noted, or None."""
        p = self.dir / self.name(id)
        try:
            os.utime(p)
        except OSError:
            return None
        return p

    def has(self, id: str) -> bool:
        return (self.dir / self.name(id)).is_file()

    def put_failure(self, id: str, message: str) -> None:
        self._write(self.name(id, "fail"), message.encode("utf-8", errors="replace"))

    def failure(self, id: str) -> str | None:
        try:
            return (self.dir / self.name(id, "fail")).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def retry(self, id: str | None = None) -> None:
        """Forget a failure (every one when `id` is None) so the model is tried again."""
        if id is not None:
            (self.dir / self.name(id, "fail")).unlink(missing_ok=True)
            return
        if self.dir.is_dir():
            for p in self.dir.glob("v%d-*.fail" % CONVERTER_VERSION):
                p.unlink(missing_ok=True)

    def sweep_versions(self) -> int:
        """Remove what an older (or newer) converter made; files that are not named like the cache's are left. Returns how many."""
        n = 0
        if not self.dir.is_dir():
            return 0
        for p in self.dir.iterdir():
            m = _VERSIONED.match(p.name)
            if m and int(m.group(1)) != CONVERTER_VERSION and p.suffix in (".pmm", ".fail"):
                p.unlink(missing_ok=True)
                n += 1
        return n

    def trim(self, in_use=frozenset()) -> int:
        """Over the bound, remove the least recently used meshes (not those of `in_use` ids) until 20% under it. Returns how many went."""
        if not self.dir.is_dir():
            return 0
        files = []
        for p in self.dir.glob("v%d-*.pmm" % CONVERTER_VERSION):
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
        total = sum(f[1] for f in files)
        if total <= self.bound:
            return 0
        keep = {self.name(i) for i in in_use}
        goal, gone = self.bound * 0.8, 0
        for _, size, p in sorted(files, key=lambda f: f[0]):
            if total <= goal:
                break
            if p.name in keep:
                continue
            try:
                p.unlink()
            except OSError:
                continue
            total -= size
            gone += 1
        return gone
