"""What an explore keeps on disk as it goes, so a stop or a crash costs
nothing and a rerun continues instead of repeating. Resumable state, not
the progress log: nothing here is for display.

Under `<board>/.placemat/explore/<script stem>/`:

- `checkpoint.jsonl`: a header line (a digest of everything that decides a
  variant, with the parts it was made of, the focus, the baseline's score and
  measures, the budget), then one line per finished variant ({"v": seed, "s":
  score, "t": seconds spent in all}; a variant better than any before it also
  carries "m", its measures), flushed as it is written, a "stop" line when
  the process was stopped, and a "done" line when the explore finished. A
  line cut short by a kill is ignored.
- `best.json`: the best variant's lock entries, replaced atomically whenever
  a better one is found: what `placemat lock --accept-seed` writes, and what
  a resume keeps."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from typing import NamedTuple

BEST_VERSION = 1
FORMAT = 1

# What the digest is made of, and what a change to each is called.
PARTS = {"script": "the script", "board": "the generated board", "settings": "the settings",
         "fab": "the fab profile", "version": "the placemat version", "lock": "the lock", "focus": "the focus"}


class ResumeRefused(ValueError):
    """A saved explore that was asked to be resumed and is not this one."""


def state_dir(board_dir, script) -> Path:
    """Where a script's explore state lives: beside the board's runs."""
    return Path(board_dir) / ".placemat" / "explore" / Path(script).stem


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def lock_digest(entries) -> str:
    """The lock as an explore began with it."""
    from .lock import _doc          # the entry as the lock file writes it: one with no arrangement digests as it always did
    return sha(json.dumps([_doc(e) for e in sorted(entries, key=lambda e: e.key)], sort_keys=True))


def write_atomic(path, text: str) -> None:
    """The file whole or not at all: written beside, then renamed over."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Appender:
    """A JSONL file written a line at a time and flushed with each, so a
    process killed at any moment leaves whole lines and at most one cut
    short (which readers drop). Small and local on purpose: the progress
    trail has its own writer."""

    def __init__(self, path, mode: str = "a"):
        self.path = Path(path)
        self._f = open(self.path, mode)

    def write(self, doc: dict) -> None:
        self._f.write(json.dumps(doc, separators=(",", ":")) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def read_lines(path) -> list:
    """The whole lines of a JSONL file as documents; a last line cut short
    (or one that is not JSON) is dropped."""
    try:
        text = Path(path).read_text()
    except OSError:
        return []
    out = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            break
    return out


class Prior(NamedTuple):
    baseline: float
    measures: dict
    done: dict            # {seed: (seed, score, measures or None)}
    spent: float          # seconds, over every session
    finished: bool
    best_seed: int
    curve: list = []       # [(seed, score, t)] of the variants, in the order they finished


class Checkpoint:
    """The state of one explore in `directory`. `header` has the digest
    `parts` ({name in PARTS: digest}) and the `focus`. `resume` is "auto"
    (continue a saved explore that is this one, else start over), "yes"
    (continue it or refuse, saying what changed) or "no" (start over)."""

    def __init__(self, directory, parts: dict, focus, resume: str = "auto", max_variants: int = 100000):
        self.dir = Path(directory)
        self.parts = dict(parts)
        self.focus = sorted(focus)
        self.digest = sha(json.dumps(self.parts, sort_keys=True))
        self.resume = resume
        self.max_variants = max_variants
        self.baseline = None
        self.best_key = None            # (score, seed) of the best seen: a variant better than it carries its measures
        self.n = 0
        self._out = None
        self._best_written = None       # (score, seed) of the variant best.json holds
        self.resumed = None             # the Prior this explore continued, or None
        self.discarded = []             # what changed, when a saved explore that was not this one was cleared

    @property
    def path(self) -> Path:
        return self.dir / "checkpoint.jsonl"

    @property
    def best_path(self) -> Path:
        return self.dir / "best.json"

    # ---------------------------------------------------------- reading
    def load(self):
        """The saved explore this one continues, or None to start over (what
        was there is cleared when it is not this explore's). Raises
        ResumeRefused when asked to resume ("yes") one that is not this."""
        lines = read_lines(self.path)
        if self.resume == "no" or not lines or lines[0].get("kind") != "header":
            self.clear()
            return None
        head = lines[0]
        if head.get("version") != FORMAT or head.get("digest") != self.digest:
            changed = [PARTS[k] for k in PARTS if head.get("parts", {}).get(k) != self.parts.get(k)]
            if head.get("version") != FORMAT:
                changed = ["the checkpoint's format"]
            if self.resume == "yes":
                raise ResumeRefused("the saved explore is not this one: %s changed since it began; run without "
                                    "--resume to start over" % (" and ".join(changed) or "something"))
            self.clear()
            self.discarded = changed
            return None
        done, spent, finished = {}, 0.0, False
        for d in lines[1:]:
            if "v" in d:
                done[d["v"]] = (d["v"], d["s"], d.get("m"))
                spent = max(spent, d.get("t", 0.0))
            elif "stop" in d or "done" in d:
                spent = max(spent, d.get("t", 0.0))
                finished = finished or "done" in d
        done.pop(0, None)
        self.n = len(done)
        scored = [(r[1], r[0]) for r in done.values()]
        base = head["baseline"]
        self.baseline = base["score"]
        best = min(scored + [(base["score"], 0)])
        self.best_key = best
        if best[1] and done[best[1]][2] is None:           # a best always carries them: a line was edited
            if self.resume == "yes":
                raise ResumeRefused("the saved explore is damaged (its best variant has no measures); run with "
                                    "--no-resume to start over")
            self.clear()
            self.discarded = ["the checkpoint (damaged)"]
            return None
        saved = read_best(self.dir)
        if saved is not None:
            self._best_written = (saved["score"], saved["seed"])
        curve = [(d["v"], d["s"], d.get("t", 0.0)) for d in lines[1:] if "v" in d and d["v"]]
        self.resumed = Prior(base["score"], base["measures"], done, spent, finished, best[1], curve)
        return self.resumed

    def best_measures(self, prior: Prior):
        return prior.measures if not prior.best_seed else prior.done[prior.best_seed][2]

    # ---------------------------------------------------------- writing
    def clear(self) -> None:
        """No saved explore: the checkpoint and the best it kept, gone."""
        for p in (self.path, self.best_path, self.dir / "best.json.tmp"):
            try:
                p.unlink()
            except OSError:
                pass

    def start(self, baseline: float, measures: dict, seconds: float, seeds) -> None:
        """A fresh explore: the header, with the baseline and the budget."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clear()
        self.baseline = baseline
        self.best_key = (baseline, 0)
        self._open("w").write({
            "kind": "header", "version": FORMAT, "digest": self.digest, "parts": self.parts,
            "focus": self.focus, "baseline": {"score": baseline, "measures": measures},
            "budget": {"seconds": seconds, "seeds": None if seeds is None else len(list(seeds))},
            "started": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def _open(self, mode: str) -> Appender:
        if self._out is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._out = Appender(self.path, mode)
        return self._out

    def variant(self, seed: int, score: float, measures: dict, elapsed: float, payload) -> None:
        """One finished variant: a line (its measures when it beat every one
        before it; at the cap on lines, nothing), and best.json when it
        brought entries to replace it."""
        if self.n < self.max_variants:
            line = {"v": seed, "s": score, "t": round(elapsed, 2)}
            if self.best_key is None or (score, seed) < self.best_key:
                line["m"] = measures
            self._open("a").write(line)
            self.n += 1
            if self.n == self.max_variants:
                self._open("a").write({"full": self.n})      # no more lines: a resume tries what follows again
        key = (score, seed)
        if self.best_key is None or key < self.best_key:
            self.best_key = key
        if payload is None or not seed:
            return
        if self._best_written is not None and key >= self._best_written:
            return
        self._best_written = key
        write_atomic(self.best_path, json.dumps({
            "version": BEST_VERSION, "seed": seed, "score": score, "baseline": self.baseline,
            "focus": self.focus, "script": self.parts["script"],
            "lock": self.parts["lock"], "entries": payload["entries"], "orders": payload["orders"]}, indent=1) + "\n")

    def stopped(self, name: str, elapsed: float) -> None:
        self._open("a").write({"stop": name, "t": round(elapsed, 2)})
        self.close()

    def done(self, elapsed: float, best_seed: int, ended: dict | None = None) -> None:
        self._open("a").write({"done": True, "best": best_seed, "t": round(elapsed, 2), "ended": ended})
        self.close()

    def close(self) -> None:
        if self._out is not None:
            self._out.close()
            self._out = None

    def finish(self) -> None:
        """The explore is complete and its result is where it goes: the
        checkpoint is not needed. (best.json stays, for accepting later.)"""
        self.close()
        try:
            self.path.unlink()
        except OSError:
            pass


def read_best(directory):
    """best.json's document, or None when there is none or it is unreadable."""
    try:
        doc = json.loads((Path(directory) / "best.json").read_text())
    except (OSError, ValueError):
        return None
    return doc if doc.get("version") == BEST_VERSION else None


def finish_dir(directory) -> None:
    """A completed explore whose result is recorded: its checkpoint is not
    needed (best.json stays, for accepting it later)."""
    try:
        (Path(directory) / "checkpoint.jsonl").unlink()
    except OSError:
        pass
