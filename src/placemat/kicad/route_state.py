"""What a route keeps in its work folder so a stop or a failure costs only the
stage in hand: `state.json` names each finished stage (pairs, islands, main)
with the digest of everything that stage's result depends on, chained from
the stage before it. A rerun whose digest for a stage matches takes that
stage's saved result instead of running the router again; the first stage
that does not match drops itself, its files and every later stage's, and
runs.

Only whole stages: inside the main router pass nothing is kept (the router's
own checkpoint_stop, KICAD_STOP_AFTER / KICAD_STOP_FILE in its
single_ended_loop.py, writes a partial board and could be a later step)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

VERSION = 1
STAGES = ("pairs", "islands", "main")
# What each stage leaves in the work folder (the folder's other files are
# made again every time, from the board and the settings).
FILES = {"pairs": ("pairs*",), "islands": ("islands*",),
         "main": ("router*", "routed*", "drc_after.json", "route.json")}


def digest(*parts) -> str:
    """A digest of `parts` (JSON values, or text): equal parts, equal digest."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def file_digest(path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


class RouteState:
    """The finished stages of the route in `work`. With `resume` False the
    folder is emptied: nothing is taken from what was there."""

    def __init__(self, work, resume: bool = True):
        self.work = Path(work)
        self.stages: dict = {}
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
        return [s for s in STAGES if s in self.stages]

    def _load(self) -> None:
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        if isinstance(doc, dict) and doc.get("version") == VERSION and isinstance(doc.get("stages"), dict):
            self.stages = {k: v for k, v in doc["stages"].items() if k in STAGES and isinstance(v, dict)}

    def _save(self) -> None:
        tmp = self.path.with_name("state.json.tmp")
        tmp.write_text(json.dumps({"version": VERSION, "stages": self.stages}, indent=1) + "\n")
        os.replace(tmp, self.path)

    def result(self, stage: str, digest_: str):
        """The saved result of a finished `stage` whose inputs digest to
        `digest_`, or None."""
        saved = self.stages.get(stage)
        return saved["result"] if saved is not None and saved.get("digest") == digest_ else None

    def record(self, stage: str, digest_: str, result: dict) -> None:
        """`stage` is finished, with this result, on inputs that digest to `digest_`."""
        self.stages[stage] = {"digest": digest_, "result": result}
        self._save()

    def drop_from(self, stage: str) -> None:
        """Forget `stage` and every stage after it, and delete their files:
        what a partial stage left is not to be taken for a finished one."""
        for later in STAGES[STAGES.index(stage):]:
            self.stages.pop(later, None)
            for pattern in FILES[later]:
                for p in self.work.glob(pattern):
                    try:
                        p.unlink() if p.is_file() else shutil.rmtree(p)
                    except OSError:
                        pass
        self._save()
