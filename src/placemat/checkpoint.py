"""What an explore keeps on disk as it goes, so a stop or a crash costs
nothing and a rerun continues instead of repeating. Resumable state, not
the progress log: nothing here is for display.

Under `<board>/.placemat/explore/<script stem>/`:

- `checkpoint.jsonl`: a header line (a digest of everything that decides a
  variant, with the parts it was made of, the focus, the baseline's score and
  measures, the budget; the script's part is of its code and its imports',
  without comments or docstrings, and `script_files` keeps each file's, for an
  accept to name what changed), then one line per finished variant ({"v": seed, "s":
  score, "t": seconds spent in all, and "r", the score it is ranked by, when that is
  not the run score: `explore.rank_remapped`}; a variant better than any before it also
  carries "m", its measures), flushed as it is written, a "stop" line when
  the process was stopped, a "done" line when the explore finished, and a
  "recorded" line once the command that ran it has recorded its result. A
  line cut short by a kill is ignored.
- `best.json`: the best variant's lock entries, replaced atomically whenever
  a better one is found: what `placemat lock --accept-seed` writes, and what
  a resume keeps.
- `entries.jsonl`: every variant's lock entries, a line each ({"v": seed,
  "entries", "orders"}), so `placemat lock --accept-seed S` takes any of them.

A recorded explore stays, so its variants can still be accepted, until the
next explore of the script replaces it; it is never resumed. One that
finished without being recorded (its run failed after it) is."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from typing import NamedTuple

BEST_VERSION = 1
FORMAT = 1
ENTRIES = "entries.jsonl"

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
        if mode == "a":
            _drop_partial_tail(self.path)
        self._f = open(self.path, mode)

    def write(self, doc: dict) -> None:
        self._f.write(json.dumps(doc, separators=(",", ":")) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def _drop_partial_tail(path: Path) -> None:
    """A last line cut short by a kill, taken off before more is appended: glued to it, the next line would be lost
    with it (`read_lines` stops at a line that is not JSON)."""
    try:
        with open(path, "rb+") as f:
            data = f.read()
            if data and not data.endswith(b"\n"):
                f.truncate(data.rfind(b"\n") + 1)
    except FileNotFoundError:
        pass


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
    ranks: dict = {}       # {seed: the score it is ranked by} where that is not its run score (`explore.rank_remapped`), 0 too


class Checkpoint:
    """The state of one explore in `directory`. `header` has the digest
    `parts` ({name in PARTS: digest}) and the `focus`. `resume` is "auto"
    (continue a saved explore that is this one, else start over), "yes"
    (continue it or refuse, saying what changed) or "no" (start over)."""

    def __init__(self, directory, parts: dict, focus, resume: str = "auto", max_variants: int = 100000,
                 script_files: dict | None = None):
        self.dir = Path(directory)
        self.parts = dict(parts)
        self.script_files = dict(script_files or {})     # {file: digest of its code}: what an accept names when the script's changed
        self.focus = sorted(focus)
        self.digest = sha(json.dumps(self.parts, sort_keys=True))
        self.resume = resume
        self.max_variants = max_variants
        self.baseline = None
        self.baseline_rank = None       # the baseline's score to rank by, when it is not its run score
        self.best_key = None            # (score to rank by, seed) of the best seen: a variant better than it carries its measures
        self.n = 0
        self._out = None
        self._entries = None
        self._best_written = None       # (score, seed) of the variant best.json holds
        self.resumed = None             # the Prior this explore continued, or None
        self.discarded = []             # what changed, when a saved explore that was not this one was cleared

    @property
    def path(self) -> Path:
        return self.dir / "checkpoint.jsonl"

    @property
    def best_path(self) -> Path:
        return self.dir / "best.json"

    @property
    def entries_path(self) -> Path:
        return self.dir / ENTRIES

    # ---------------------------------------------------------- reading
    def load(self):
        """The saved explore this one continues, or None to start over (what
        was there is cleared when it is not this explore's). Raises
        ResumeRefused when asked to resume ("yes") one that is not this."""
        lines = read_lines(self.path)
        if self.resume == "no" or not lines or lines[0].get("kind") != "header" or any("recorded" in d for d in lines):
            self.clear()                # a recorded explore is kept for accepting, not resumed: this one replaces it
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
        done, spent, finished, ranks = {}, 0.0, False, {}
        for d in lines[1:]:
            if "v" in d:
                done[d["v"]] = (d["v"], d["s"], d.get("m"))
                if "r" in d:
                    ranks[d["v"]] = d["r"]
                spent = max(spent, d.get("t", 0.0))
            elif "stop" in d or "done" in d:
                spent = max(spent, d.get("t", 0.0))
                finished = finished or "done" in d
        done.pop(0, None)
        self.n = len(done)
        scored = [(ranks.get(r[0], r[1]), r[0]) for r in done.values()]
        base = head["baseline"]
        self.baseline = base["score"]
        self.baseline_rank = base.get("rank")
        if self.baseline_rank is not None:
            ranks[0] = self.baseline_rank
        best = min(scored + [(base["score"] if self.baseline_rank is None else self.baseline_rank, 0)])
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
            self._best_written = (saved.get("score_remapped", saved["score"]), saved["seed"])
        curve = [(d["v"], d["s"], d.get("t", 0.0)) for d in lines[1:] if "v" in d and d["v"]]
        self.resumed = Prior(base["score"], base["measures"], done, spent, finished, best[1], curve, ranks)
        return self.resumed

    def best_measures(self, prior: Prior):
        return prior.measures if not prior.best_seed else prior.done[prior.best_seed][2]

    # ---------------------------------------------------------- writing
    def clear(self) -> None:
        """No saved explore: the checkpoint and the best it kept, gone."""
        for p in (self.path, self.best_path, self.dir / "best.json.tmp", self.entries_path):
            try:
                p.unlink()
            except OSError:
                pass

    def start(self, baseline: float, measures: dict, seconds: float, seeds, rank: float | None = None) -> None:
        """A fresh explore: the header, with the baseline (and `rank`, its score to rank by when that is not its run
        score) and the budget."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clear()
        self.baseline = baseline
        self.baseline_rank = rank
        self.best_key = (baseline if rank is None else rank, 0)
        self._open("w").write({
            "kind": "header", "version": FORMAT, "digest": self.digest, "parts": self.parts, "script_files": self.script_files,
            "focus": self.focus, "baseline": dict({"score": baseline, "measures": measures},
                                                  **({"rank": rank} if rank is not None else {})),
            "budget": {"seconds": seconds, "seeds": None if seeds is None else len(list(seeds))},
            "started": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def _open(self, mode: str) -> Appender:
        if self._out is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._out = Appender(self.path, mode)
        return self._out

    def variant(self, seed: int, score: float, measures: dict, elapsed: float, payload, rank: float | None = None) -> None:
        """One finished variant: a line (its measures when it beat every one
        before it; at the cap on lines, nothing), its entries' line when it
        brought its entries (`payload`), and best.json when those beat the
        baseline and the best written. `rank` is the score it is ranked by
        when that is not `score` (`explore.rank_remapped`): what "better" means."""
        by = score if rank is None else rank
        if self.n < self.max_variants and payload is not None and seed:
            if self._entries is None:
                self._entries = Appender(self.entries_path, "a")
            self._entries.write({"v": seed, "entries": payload["entries"], "orders": payload["orders"]})
        if self.n < self.max_variants:
            line = {"v": seed, "s": score, "t": round(elapsed, 2)}
            if rank is not None:
                line["r"] = rank
            if self.best_key is None or (by, seed) < self.best_key:
                line["m"] = measures
            self._open("a").write(line)
            self.n += 1
            if self.n == self.max_variants:
                self._open("a").write({"full": self.n})      # no more lines: a resume tries what follows again
        key = (by, seed)
        if self.best_key is None or key < self.best_key:
            self.best_key = key
        if payload is None or not seed:
            return
        base = self.baseline if self.baseline_rank is None else self.baseline_rank
        if base is not None and by >= base - 1e-9:
            return
        if self._best_written is not None and key >= self._best_written:
            return
        self._best_written = key
        write_atomic(self.best_path, json.dumps({
            "version": BEST_VERSION, "seed": seed, "score": score, "baseline": self.baseline,
            **({"score_remapped": rank} if rank is not None else {}), "focus": self.focus, "script": self.parts["script"],
            "script_files": self.script_files, "lock": self.parts["lock"], "entries": payload["entries"], "orders": payload["orders"]}, indent=1) + "\n")

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
        if self._entries is not None:
            self._entries.close()
            self._entries = None

    def finish(self) -> None:
        """The explore is complete and its result is where it goes: marked
        recorded (`finish_dir`), and kept for accepting any of its variants."""
        self.close()
        finish_dir(self.dir)


def read_best(directory):
    """best.json's document, or None when there is none or it is unreadable."""
    try:
        doc = json.loads((Path(directory) / "best.json").read_text())
    except (OSError, ValueError):
        return None
    return doc if doc.get("version") == BEST_VERSION else None


def finish_dir(directory) -> None:
    """A completed explore whose result is recorded: its checkpoint gets a
    "recorded" line, so it is not resumed, and stays with its entries for
    accepting any variant until the next explore replaces it."""
    path = Path(directory) / "checkpoint.jsonl"
    lines = read_lines(path)
    if lines and not any("recorded" in d for d in lines):
        Appender(path, "a").write({"recorded": True})


def read_variant(directory, seed: int):
    """A saved variant as best.json holds the best (seed, score, baseline,
    focus, script, lock, entries, orders), from the checkpoint's header and
    lines and `entries.jsonl`; None when the explore did not keep it."""
    lines = read_lines(Path(directory) / "checkpoint.jsonl")
    if not lines or lines[0].get("kind") != "header":
        return None
    head = lines[0]
    score = next((d["s"] for d in lines if d.get("v") == seed), None)
    kept = next((d for d in read_lines(Path(directory) / ENTRIES) if d.get("v") == seed), None)
    if score is None or kept is None:
        return None
    return {"version": BEST_VERSION, "seed": seed, "score": score, "baseline": head["baseline"]["score"],
            "focus": head["focus"], "script": head["parts"]["script"], "script_files": head.get("script_files") or {},
            "lock": head["parts"]["lock"],
            "entries": kept["entries"], "orders": kept["orders"]}


def saved(directory, seed: int) -> bool:
    """Whether `placemat lock --accept-seed` can take this seed from the saved explore."""
    if not seed:
        return False
    best = read_best(directory)
    return (best is not None and best["seed"] == seed) or read_variant(directory, seed) is not None
