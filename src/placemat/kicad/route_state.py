"""What a route keeps in its work folder so a stop or a failure costs only the phase in hand: `state.json` names each
finished routing phase with the digest of everything its result depends on, chained from the phase before it (the
board and its rules, the capture, the route's settings, the earlier phases' keys, the phase's own definition, the
router's and placemat's versions). A rerun whose digest for a phase matches takes that phase's saved result instead of
routing it again; the first phase that does not match drops itself, its files and every later phase's, and routes.

Phase i's files are `p<i>_*`; what the end of the route makes (FINAL) goes with any dropped phase. Only whole phases
are kept: inside a router call nothing is."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

VERSION = 2
FINAL = ("router*", "routed*", "drc_after.json", "route.json", "route_record.json", "route_summary.json")


# Transitional (Task 13 removes it): what the fixed-stage route leaves for each of its stages.
LEGACY_FILES = {"pairs": ("pairs*",), "islands": ("islands*",), "classes": ("classes*",)}


def digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def file_digest(path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def files_of(index: int) -> tuple:
    return ("p%d_*" % index,)


class RouteState:
    def __init__(self, work, resume: bool = True):
        self.work = Path(work)
        self.order: list = []
        self.phases: dict = {}
        self._saved_order: list = []
        if not resume:
            shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(parents=True, exist_ok=True)
        if resume:
            self._load()

    @property
    def path(self) -> Path:
        return self.work / "state.json"

    @property
    def finished(self) -> list:
        # Before set_order, the saved route's own order.
        return [n for n in (self.order or self._saved_order) if n in self.phases]

    def _load(self) -> None:
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(doc, dict) and doc.get("version") == VERSION and isinstance(doc.get("phases"), dict):
            self._saved_order = [n for n in doc.get("order", []) if isinstance(n, str)]
            self.phases = {k: v for k, v in doc["phases"].items() if isinstance(v, dict)}

    def set_order(self, names) -> None:
        self.order = list(names)
        head = 0
        while head < min(len(self.order), len(self._saved_order)) and self.order[head] == self._saved_order[head]:
            head += 1
        keep = set(self.order[:head])
        for name in list(self.phases):
            if name not in keep:
                self.phases.pop(name)
        if head < len(self._saved_order):                     # something saved is dropped
            self._delete_from(head)
        self._saved_order = list(self.order)
        self._save()

    def _save(self) -> None:
        tmp = self.path.with_name("state.json.tmp")
        tmp.write_text(json.dumps({"version": VERSION, "order": self.order, "phases": self.phases}, indent=1) + "\n")
        os.replace(tmp, self.path)

    def result(self, name: str, digest_: str):
        saved = self.phases.get(name)
        return saved["result"] if saved is not None and saved.get("digest") == digest_ else None

    def record(self, name: str, digest_: str, result: dict) -> None:
        self.phases[name] = {"digest": digest_, "result": result}
        self._save()

    def _delete_from(self, index: int) -> None:
        last = max(len(self._saved_order), len(self.order))       # every index either phase list used
        patterns = [p for i in range(index, max(index, last)) for p in files_of(i)] + list(FINAL)
        # Transitional, until the phase engine replaces the fixed-stage route (Task 13): the files of its stages.
        for name in self.order[index:] + self._saved_order[index:]:
            patterns += LEGACY_FILES.get(name, ())
        for pattern in patterns:
            for p in self.work.glob(pattern):
                try:
                    p.unlink() if p.is_file() else shutil.rmtree(p)
                except OSError:
                    pass

    def drop_from(self, name: str) -> None:
        index = self.order.index(name)
        for later in self.order[index:]:
            self.phases.pop(later, None)
        self._delete_from(index)
        self._save()
