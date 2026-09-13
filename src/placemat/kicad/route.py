"""Routes a placed board with KiCadRoutingTools on a copy, and scores how
much of the open signal ratsnest it closed under the board's own rules.

Existing copper is locked first so the router adds to the placement and
never reworks it. Plane nets are excluded: a plane reaches its pads by a
via, not a track. Closure is the share of open signal connections the
router closed; clean closure counts a net it closed through a short or
clearance violation as still open. A board whose own DRC has real
violations before routing is scored but marked invalid.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from .drc import REAL_KINDS, run_drc

ROUTER_DEFAULT = os.environ.get("KRT_DIR", os.path.expanduser("~/work/KiCadRoutingTools"))
ONE_ROUND = Path(__file__).with_name("route_one_round.py")


@dataclass
class Score:
    closure: float
    closure_clean: float
    shorted: list


def score(open_before: dict, open_after: dict, violated_nets: set) -> Score:
    """open_before/after: {net: open items} over the signal nets only."""
    items0, items1 = sum(open_before.values()), sum(open_after.values())
    shorted = sorted(n for n in violated_nets if n in open_before)
    nets = set(open_before) | set(open_after)
    items1_clean = sum(open_before.get(n, open_after.get(n, 0)) if n in shorted else open_after.get(n, 0)
                       for n in nets)
    closure = (1.0 - items1 / items0) if items0 else 1.0
    clean = (1.0 - items1_clean / items0) if items0 else 1.0
    return Score(closure, clean, shorted)


@dataclass
class RouteReport:
    valid: bool
    closure: float
    closure_clean: float
    open_before: int
    open_after: int
    open_nets: dict                       # signal nets still open -> open items
    shorted: list
    excluded: list
    layers: list
    seconds: float
    router_version: str
    drc_after: dict
    routed_pcb: Path
    log: Path
    work: Path
    invalid_reason: str = ""
    quick: bool = False

    def summary(self) -> str:
        head = "route %s: closure %.1f%% clean (%.1f%% raw), %d -> %d open signal item(s)" % (
            "quick" if self.quick else "full", 100 * self.closure_clean, 100 * self.closure,
            self.open_before, self.open_after)
        if not self.valid:
            head += "  INVALID: " + self.invalid_reason
        if self.shorted:
            head += "  shorted: " + ", ".join(self.shorted)
        return head

    def as_dict(self) -> dict:
        return {"valid": self.valid, "closure": self.closure, "closure_clean": self.closure_clean,
                "open_before": self.open_before, "open_after": self.open_after, "open_nets": self.open_nets,
                "shorted": self.shorted, "excluded": self.excluded, "layers": self.layers,
                "seconds": self.seconds, "router_version": self.router_version, "drc_after": self.drc_after,
                "routed_pcb": str(self.routed_pcb), "log": str(self.log), "quick": self.quick,
                "invalid_reason": self.invalid_reason}


def lock_copper(pcb_path: str) -> int:
    """Lock every track, via and copper polygon so the router keeps them."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
    n = 0
    for t in board.GetTracks():
        t.SetLocked(True)
        n += 1
    for d in board.GetDrawings():
        if d.GetClass() == "PCB_SHAPE" and d.IsOnCopperLayer():
            d.SetLocked(True)
            n += 1
    with quiet_stderr():
        board.Save(pcb_path)
    return n


def _copper_layers(pcb_path: str) -> list:
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
    return [board.GetLayerName(l) for l in board.GetEnabledLayers().CuStack()]


def _nets_in_violations(drc: dict) -> set:
    import re
    out = set()
    for v in drc.get("violations", []):
        if v.get("type") not in REAL_KINDS:
            continue
        for item in v.get("items", []):
            m = re.search(r"\[([^\]]+)\]", item.get("description", ""))
            if m:
                out.add(m.group(1))
    return out


def router_version(router_dir: str) -> str:
    try:
        return (Path(router_dir) / "VERSION").read_text().strip()
    except OSError:
        return "unknown"


def router_command(python, script, pcb_in, pcb_out, excluded, layers, summary,
                   iterations: int | None = None, probe: int | None = None) -> list:
    """The router's command line. The search budget is the router's own
    default unless the caller sets one."""
    cmd = [str(python), str(script), str(pcb_in), str(pcb_out), "--nets", "*"] + \
          ["!" + n for n in sorted(excluded)] + ["--layers"] + list(layers) + ["--escalation", "off"]
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    if probe is not None:
        cmd += ["--max-probe-iterations", str(probe)]
    return cmd + ["--json-out", str(summary)]


def route_board(pcb, work, exclude_nets=(), layers=None, router_dir: str = ROUTER_DEFAULT,
                quick: bool = False, iterations: int | None = None, probe: int | None = None,
                timeout: int = 3600) -> RouteReport:
    pcb, work = Path(pcb), Path(work)
    rpy = Path(router_dir) / ".venv/bin/python"
    route_py = Path(router_dir) / "py_router/route.py"
    if not (rpy.exists() and route_py.exists()):
        raise FileNotFoundError("router not found at %s (expected .venv/bin/python and py_router/route.py); "
                                "set KRT_DIR" % router_dir)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pcb_in = work / "in.kicad_pcb"
    shutil.copy(pcb, pcb_in)
    for ext in (".kicad_pro", ".kicad_dru"):
        src = pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, work / ("in" + ext))
    lock_copper(str(pcb_in))
    layers = list(layers or _copper_layers(str(pcb_in)))
    excluded = set(exclude_nets)

    before = run_drc(pcb_in, work / "drc_before.json")
    open0 = {n: v for n, v in before.open_nets.items() if n not in excluded}
    valid = not before.real

    pcb_out = work / "routed.kicad_pcb"
    summary = work / "router_summary.json"
    script = str(ONE_ROUND) if quick else str(route_py)
    cmd = router_command(rpy, script, pcb_in, pcb_out, excluded, layers, summary, iterations, probe)
    env = dict(os.environ)
    env.pop("KICAD_ROUTE_TRACE", None)
    env["KRT_DIR"] = str(router_dir)
    log = work / "router.log"
    t0 = time.time()
    with open(log, "w") as f:
        f.write("$ %s\n\n" % " ".join(cmd))
        f.flush()
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir), env=env,
                            timeout=timeout).returncode
    seconds = round(time.time() - t0, 1)
    if rc != 0 or not pcb_out.exists():
        tail = "\n".join(log.read_text(errors="replace").splitlines()[-8:])
        raise RuntimeError("router exited %d without a routed board; log %s\n%s" % (rc, log, tail))
    for ext in (".kicad_pro", ".kicad_dru"):
        if (work / ("in" + ext)).exists():
            shutil.copy(work / ("in" + ext), work / ("routed" + ext))
    after = run_drc(pcb_out, work / "drc_after.json")
    open1 = {n: v for n, v in after.open_nets.items() if n not in excluded}
    violated = _nets_in_violations(json.loads((work / "drc_after.json").read_text()))
    sc = score(open0, open1, {n for n in violated if n not in excluded})
    report = RouteReport(valid, round(sc.closure, 4), round(sc.closure_clean, 4), sum(open0.values()), sum(open1.values()),
                         dict(sorted(open1.items())), sc.shorted, sorted(excluded), layers, seconds,
                         router_version(router_dir), after.by_type, pcb_out, log, work,
                         "" if valid else "placement DRC not clean before routing: %s" % before.real, quick)
    (work / "route.json").write_text(json.dumps(report.as_dict(), indent=2) + "\n")
    return report
