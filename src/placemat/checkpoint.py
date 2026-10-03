"""What an explore keeps on disk as it goes, so a stop or a crash costs
nothing: `best.json`, the best variant's lock entries, replaced atomically
whenever a better one is found (what `placemat lock --accept-seed` writes
to the lock). Resumable state, not the progress log: nothing here is for
display."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path

BEST_VERSION = 1


def state_dir(board_dir, script) -> Path:
    """Where a script's explore state lives: beside the board's runs."""
    return Path(board_dir) / ".placemat" / "explore" / Path(script).stem


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def lock_digest(entries) -> str:
    """The lock as an explore began with it."""
    return sha(json.dumps([asdict(e) for e in sorted(entries, key=lambda e: e.key)], sort_keys=True))


def write_atomic(path, text: str) -> None:
    """The file whole or not at all: written beside, then renamed over."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Checkpoint:
    """The state of one explore: `directory`, and the `header` facts
    (digest parts, focus, lock digest) search() knows."""

    def __init__(self, directory, header: dict):
        self.dir = Path(directory)
        self.header = header
        self.best_key = None
        self.baseline = None

    @property
    def best_path(self) -> Path:
        return self.dir / "best.json"

    def begin(self, baseline: float, measures: dict, seconds: float, seeds) -> tuple:
        """Start the explore: ({seed: (seed, score, measures)} already
        tried, seconds already spent)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.baseline = baseline
        return {}, 0.0

    def variant(self, seed: int, score: float, measures: dict, elapsed: float, payload) -> None:
        if payload is None:
            return
        key = (score, seed)
        if self.best_key is not None and key >= self.best_key:
            return
        self.best_key = key
        write_atomic(self.best_path, json.dumps({
            "version": BEST_VERSION, "seed": seed, "score": score, "baseline": self.baseline,
            "focus": sorted(self.header["focus"]), "script": self.header["script"],
            "lock": self.header["lock"], "entries": payload["entries"], "orders": payload["orders"]}, indent=1) + "\n")


def read_best(directory):
    """best.json's document, or None when there is none or it is unreadable."""
    try:
        doc = json.loads((Path(directory) / "best.json").read_text())
    except (OSError, ValueError):
        return None
    return doc if doc.get("version") == BEST_VERSION else None
