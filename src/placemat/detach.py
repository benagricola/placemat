"""A long command run apart from the shell that started it, and its outcome once it has ended.

`placemat run|preview|route ... --detach` starts the same command in a session of its own (setsid), its stdout and stderr
to `<project root>/.placemat/detached/<pid>.log`, writes `<pid>.json` beside it (the pid, the command, its arguments, the
script, the label, the log, when it started) and returns at once. The pid is the command's own: what its socket is named
by (channel.py), what `placemat watch` takes, and what a SIGTERM goes to - which stops it as it stops a command run in
the foreground, keeping its work.

`placemat watch <pid> --summary` says nothing until the command has ended, then its outcome (`outcome`): how it ended,
from the last event in its progress file (channel.py mirrors `done`, `error` and `explore_done` there), the run's record
(run.json: status, DRC, measures, the explore's report) and, for an explore outside a run, its own record. Nothing is
read from the command's printed text."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

DIR = (".placemat", "detached")
KEEP = 20                   # entries and logs of ended commands kept: the oldest beyond these are deleted at the next --detach
POLL_S = 1.0                # how often a summary looks whether the command has ended
COMMANDS = ("run", "preview", "route")      # the commands that take --detach: the long ones, which a stop keeps the work of


def directory(root) -> Path:
    return Path(root).joinpath(*DIR)


def _target(args) -> Path:
    """The script (or, for route, the board) the command names."""
    return Path(getattr(args, "script", None) or getattr(args, "pcb", None) or ".").resolve()


def root_of(args) -> Path:
    """The project the command belongs to (studio.project_root): where its socket and its detached files go."""
    from .studio import project_root
    t = _target(args)
    return project_root(t if t.is_dir() else t.parent)


def without_detach(argv) -> list:
    return [a for a in argv if a != "--detach"]


def start(args, argv, cwd=None) -> dict:
    """Start the command `argv` (the arguments as given, --detach among them) detached; returns its entry: `pid`,
    `command`, `args`, `script`, `label`, `log`, `entry`, `started`, `cwd`."""
    from .childenv import child_env
    root = root_of(args)
    d = directory(root)
    d.mkdir(parents=True, exist_ok=True)
    prune(d)
    cwd = str(cwd or os.getcwd())
    rest = without_detach(argv)
    started = time.time()
    tmp = d / (".starting-%d-%d.log" % (os.getpid(), int(started * 1000)))
    with open(tmp, "wb") as log:
        # the C environment less KIPRJMOD, the display kept: the command runs as it would in the foreground
        proc = subprocess.Popen([sys.executable, "-m", "placemat", *rest], cwd=cwd, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
                                env=child_env(headless=False))
    path = d / ("%d.log" % proc.pid)
    tmp.rename(path)                                    # the child writes on through its open descriptor
    entry = {"pid": proc.pid, "command": args.command, "args": rest, "script": str(_target(args)),
             "label": getattr(args, "label", None) or "", "log": str(path), "started": started, "cwd": cwd}
    (d / ("%d.json" % proc.pid)).write_text(json.dumps(entry, indent=1))
    entry["entry"] = str(d / ("%d.json" % proc.pid))
    return entry


def prune(d: Path, keep: int = KEEP) -> None:
    """Delete the entries and logs of ended commands beyond the newest `keep`."""
    from .channel import pid_alive
    ended = []
    for f in d.glob("*.json"):
        try:
            pid = int(f.stem)
        except ValueError:
            continue
        if not pid_alive(pid):
            ended.append((f.stat().st_mtime, f))
    for _, f in sorted(ended, reverse=True)[keep:]:
        for p in (f, f.with_suffix(".log")):
            try:
                p.unlink()
            except OSError:
                pass


def started_text(entry: dict) -> list:
    """What `--detach` prints: the pid, the label, the log and the command that follows it."""
    return ["detached %s, pid %d%s" % (entry["command"], entry["pid"], (", label %s" % entry["label"]) if entry["label"] else ""),
            "log %s" % entry["log"],
            "its outcome, when it ends: placemat watch %d --summary" % entry["pid"]]


# ------------------------------------------------------------------ the outcome
def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _find_pid(root, selector) -> int | None:
    """The pid `selector` names: a number, or the label of a live command (its socket entry) or a detached one (the
    newest)."""
    from . import channel
    if str(selector).isdigit():
        return int(selector)
    live, _ = channel.scan(channel.sockets_dir(root))
    hit = [e for e in live if e.get("label") == selector]
    if hit:
        return int(hit[0]["pid"])
    detached = [e for e in (_read_json(f) for f in directory(root).glob("*.json")) if e and e.get("label") == selector]
    if detached:
        return int(max(detached, key=lambda e: e.get("started", 0))["pid"])
    return None


def wait(root, pid: int, poll: float = POLL_S) -> dict:
    """Wait for the command `pid` to end; returns what was seen of it while it ran: its socket entry (`channel`, None if
    it never opened one) and its detached entry (`detached`, None if it was not detached)."""
    from . import channel
    seen = None
    while True:
        live, _ = channel.scan(channel.sockets_dir(root))
        mine = next((e for e in live if int(e.get("pid", -1)) == pid), None)
        if mine is not None:
            seen = mine
        if not channel.pid_alive(pid):
            break
        time.sleep(poll)
    if seen is None:                                    # ended before a look found it live: its entry may still be there
        seen = _read_json(channel.sockets_dir(root) / ("%d.json" % pid))
    return {"channel": seen, "detached": _read_json(directory(root) / ("%d.json" % pid))}


def _progress_files(board_dir: Path, pid: int) -> list:
    """The progress files a command `pid` of this board may have left (channel.Beacon): a run's in its folder, another
    command's in views/<command>/."""
    base = board_dir / ".placemat"
    out = list(base.glob("views/*/progress-%d.jsonl" % pid))
    for f in base.glob("runs/*/progress.jsonl"):
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                if json.loads(fh.readline() or "{}").get("pid") == pid:
                    out.append(f)
        except (OSError, ValueError):
            continue
    return out


def _run_records(board_dir: Path, pid: int) -> list:
    """The run records a command `pid` made: those naming its pid, or in a folder its own staging left (a run that failed
    before it took its id)."""
    runs = board_dir / ".placemat" / "runs"
    out = []
    for f in list(runs.glob("*/run.json")) + list(runs.glob(".*/run.json")):
        if f.parent.is_symlink():
            continue
        doc = _read_json(f)
        if doc is not None and (doc.get("pid") == pid or f.parent.name.endswith("-%d" % pid)):
            out.append(f)
    return sorted(out, key=lambda f: f.stat().st_mtime)


def outcome(root, pid: int, seen: dict | None = None) -> dict:
    """What the ended command `pid` came to, as a record: `ended` ("done", "error", "died": no last word, "not_found":
    nothing of it is here), `error` (the error event), `record` (the record's path), `run` (`run_facts`), `explore`
    (`explore_facts`), and `pid`, `command`, `script`, `label`, `log`. `seen` is what `wait` saw."""
    seen = seen or {"channel": None, "detached": _read_json(directory(root) / ("%d.json" % pid))}
    ch, det = seen.get("channel") or {}, seen.get("detached") or {}
    script = ch.get("script") or det.get("script") or ""
    out = {"pid": pid, "command": ch.get("command") or det.get("command") or "", "script": script,
           "label": ch.get("label") or det.get("label") or "", "log": det.get("log"), "ended": "not_found",
           "error": None, "record": None, "run": None, "explore": None}
    board_dir = Path(script).parent if script else None
    progress = [Path(ch["progress"])] if ch.get("progress") else []
    if board_dir is not None and not any(p.is_file() for p in progress):
        progress = _progress_files(board_dir, pid)
    from .channel import last_state
    events = []
    for p in progress:
        if p.is_file():
            events = last_state(p, limit=100000)
            progress = [p]
            break
    final = next((e for e in reversed(events) if e.get("ev") in ("done", "error")), None)
    explore_ev = next((e for e in reversed(events) if e.get("ev") == "explore_done"), None)
    if final is not None:
        out["ended"] = final["ev"]
        if final["ev"] == "error":
            out["error"] = final
        record = final.get("record") or ""
    else:
        record = ""
        if events or det or ch:
            out["ended"] = "died"
    if not record and progress and (progress[0].parent / "run.json").is_file():
        record = str(progress[0].parent / "run.json")       # a run that failed: its record sits beside its progress file
    if not record and board_dir is not None and out["command"] == "run":
        found = _run_records(board_dir, pid)
        if found:
            record = str(found[-1])
    out["record"] = record or None
    doc = _read_json(record) if record and record.endswith("run.json") else None
    if doc is not None:
        out["run"] = run_facts(doc, Path(record))
        if out["ended"] in ("not_found", "died") and doc.get("status") in ("ok", "failed", "stopped"):
            # no progress file (a run that failed before its first resolve): its record says how it ended
            out["ended"] = "done" if doc["status"] == "ok" else "error"
            f = doc.get("failure") or {}
            if doc["status"] == "stopped":
                out["error"] = {"ev": "error", **f}
            elif doc["status"] == "failed":
                out["error"] = {"ev": "error", "kind": "run_failure", "failure": f.get("kind", ""),
                                "detail": f.get("error") or f.get("message") or ""}
    report = None
    if doc is not None:
        report = (doc.get("metrics") or {}).get("explore") or (doc.get("failure") or {}).get("explore")
    if report is None and out["error"] is not None and out["error"].get("kind") == "stopped":
        report = out["error"].get("explore")
    out["explore"] = explore_facts(report, explore_ev)
    return out


def run_facts(doc: dict, path: Path) -> dict:
    """What the summary keeps of a run record: id, status, the run's folder, its failure, the DRC counts, the airwires and
    crossings, the congestion and the run score with its terms."""
    m = doc.get("metrics") or {}
    out = {"id": doc.get("run_id"), "status": doc.get("status"), "dir": str(path.parent), "failure": doc.get("failure"),
           "findings": len(doc.get("findings") or ())}
    for k in ("drc_real", "unconnected", "outstanding", "airwire_mm", "crossings", "congestion"):
        if k in m:
            out[k] = m[k]
    if "measures" in m:
        try:
            from . import score, settings
            script = (doc.get("paths") or {}).get("script")
            cfg = settings.load(Path(script).parent, script=script) if script else settings.active()
            terms = score.terms(m["measures"], cfg)
            out["score"] = round(sum(terms.values()), 1)
            out["terms"] = {k: round(v, 1) for k, v in terms.items() if v}
        except Exception:                               # a record the settings no longer read: no score, the rest stands
            pass
    return out


def explore_facts(report, event=None) -> dict | None:
    """What the summary keeps of an explore: from the run's report of it (run.json's metrics.explore, or failure.explore
    when it was stopped), else from its `explore_done` event and the record that names (a preview's)."""
    if not report and not event:
        return None
    src = dict(report or {})
    if not report and event:
        src = {k: event.get(k) for k in ("tried", "baseline", "best", "best_seed", "taken_seed", "routes", "routes_skipped",
                                          "baseline_remapped", "best_remapped", "record") if k in event}
        src["accepted"] = bool(event.get("kept"))
        rec = _read_json(event["record"]) if event.get("record") else None
        if rec is not None:
            src.setdefault("seconds", rec.get("seconds"))
    keys = ("tried", "seconds", "baseline", "best", "best_seed", "taken_seed", "baseline_remapped", "best_remapped",
            "accepted", "accept", "stopped", "record", "empty")
    out = {k: src[k] for k in keys if src.get(k) is not None}
    out["accepted"] = bool(src.get("accepted"))
    out["moves"] = len(src.get("moves") or ())
    out["routes"] = [{k: r[k] for k in ("seed", "score", "score_remapped", "closure", "closure_clean", "open_after", "seconds",
                                        "valid", "remapped", "error") if k in r} for r in (src.get("routes") or ())]
    return out


# ------------------------------------------------------------------ the edge: the summary as text
def summary_lines(o: dict) -> list:
    from .channel import failure_text
    head = "%s %s%s: " % (o["command"] or "command", o["pid"], (", label %s" % o["label"]) if o["label"] else "")
    lines = []
    if o["ended"] == "not_found":
        return [head + "not found: no command, record or log of this pid in the project"]
    ended = {"done": "ended", "died": "died without saying it was done"}.get(o["ended"])
    if o["ended"] == "error":
        ended = failure_text(o["error"] or {})
    lines.append(head + ended)
    lines += explore_lines(o["explore"])
    r = o["run"]
    if r is not None:
        lines.append("run %s: %s" % (r["id"], r["status"]))
        if "drc_real" in r:
            drc = "DRC clean" if not r["drc_real"] else "DRC " + ", ".join("%d %s" % (v, k) for k, v in sorted(r["drc_real"].items()))
            parts = [drc, "unconnected %s" % r.get("unconnected", "-")]
            if r.get("outstanding"):
                parts.append("outstanding " + ", ".join("%d %s" % (v, k) for k, v in sorted(r["outstanding"].items())))
            lines.append("  %s | airwires %.1f mm, %s crossings, congestion %s" % (
                ", ".join(parts), r.get("airwire_mm") or 0.0, r.get("crossings", "-"),
                "-" if r.get("congestion") is None else "%.2f/cm2" % r["congestion"]))
        if "score" in r:
            lines.append("  score %.1f mm%s" % (r["score"], (": " + ", ".join("%s %.1f" % kv for kv in r["terms"].items()))
                                                if r.get("terms") else ""))
        if r["findings"]:
            lines.append("  %d finding%s in the record" % (r["findings"], "" if r["findings"] == 1 else "s"))
        lines.append("run dir %s" % r["dir"])
    if o["record"]:
        lines.append("record %s" % o["record"])
    if o["log"]:
        lines.append("log %s" % o["log"])
    return lines


def explore_lines(e) -> list:
    if not e:
        return []
    from .explore import duration, route_line
    if e.get("empty"):
        return ["explore: nothing to explore: no searched item is in focus"]
    head = "explore: %s variants%s" % (e.get("tried", "?"), (" in %s" % duration(e["seconds"])) if e.get("seconds") else "")
    if e.get("stopped"):
        head += ", stopped by %s" % e["stopped"]
    if e.get("best_seed"):
        head += "; best seed %d: %.1f -> %.1f mm" % (e["best_seed"], e["baseline"], e["best"])
        if e["moves"]:
            head += ", %d item%s would move" % (e["moves"], "" if e["moves"] == 1 else "s")
    elif "baseline" in e:
        head += "; no variant beat the current placement (%.1f mm)" % e["baseline"]
    lines = [head]
    if e.get("best_remapped") is not None:
        lines.append("  ranked after each variant's pin remap: %.1f -> %.1f mm" % (e["baseline_remapped"], e["best_remapped"]))
    for r in e["routes"]:
        lines.append(route_line({"error": None, "closure": 0.0, "closure_clean": 0.0, "open_after": 0, "seconds": 0.0, **r}))
    if e.get("taken_seed") is not None and e["routes"]:
        lines.append("  taken by route closure: seed %d%s" % (e["taken_seed"], ", the current placement" if e["taken_seed"] == 0 else ""))
    if e["accepted"]:
        lines.append("  accepted: written to the lock")
    elif e.get("accept"):
        lines.append("  not accepted; accept it with: %s" % e["accept"])
    else:
        lines.append("  not accepted")
    return lines


def summary(root, selector, as_json: bool = False, out=None, poll: float = POLL_S) -> int:
    """`placemat watch <pid|label> --summary`: wait for the command to end, then print its outcome. Exit as `watch` does:
    0 done, 1 an error (a stop among them), 2 died or not found."""
    out = out or sys.stdout
    pid = _find_pid(root, selector)
    if pid is None:
        o = {"pid": selector, "command": "", "label": "", "ended": "not_found"}
        print(json.dumps(o) if as_json else "no command %r in %s" % (selector, root), file=out, flush=True)
        return 2
    o = outcome(root, pid, wait(root, pid, poll))
    if as_json:
        print(json.dumps(o, default=str, indent=2), file=out, flush=True)
    else:
        print("\n".join(summary_lines(o)), file=out, flush=True)
    return {"done": 0, "error": 1}.get(o["ended"], 2)
