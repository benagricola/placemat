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

BUILTIN_ROUTER = os.path.expanduser("~/work/KiCadRoutingTools")
ROUTER_DEFAULT = os.environ.get("KRT_DIR", BUILTIN_ROUTER)   # kept: tests and callers import this name


def router_dir(cfg=None) -> str:
    """Where the router lives: the built-in default, then $KRT_DIR (a machine
    fact), then placemat.toml (a project fact), which wins."""
    from ..settings import active
    cfg = active() if cfg is None else cfg
    return cfg.route_router_dir or os.environ.get("KRT_DIR") or BUILTIN_ROUTER
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
    # Router copper inside a region that forbids it. The router honours rule
    # areas; this is what keeps that a checked fact rather than an assumed one.
    keepout_breaches: list = field(default_factory=list)
    # What the pair router did with the differential pairs (Pairs.as_dict).
    pairs: dict = field(default_factory=dict)
    # An inner layer left out of `layers` because the board's own plane
    # fills it whole, {layer: the net that fills it}; empty when the layers
    # were given (an argument or [route] layers), not defaulted.
    plane_layers: dict = field(default_factory=dict)

    def summary(self) -> str:
        head = "route %s: closure %.1f%% clean (%.1f%% raw), %d -> %d open signal item(s)" % (
            "quick" if self.quick else "full", 100 * self.closure_clean, 100 * self.closure,
            self.open_before, self.open_after)
        if not self.valid:
            head += "  INVALID: " + self.invalid_reason
        if self.shorted:
            head += "  shorted: " + ", ".join(self.shorted)
        if self.keepout_breaches:
            head += "  %d item(s) inside a keepout" % len(self.keepout_breaches)
        p = self.pairs or {}
        if any(p.get(k) for k in ("coupled", "partial", "failed", "single_ended")):
            head += "  pairs: %d coupled, %d partial, %d failed, %d single-ended" % tuple(
                len(p.get(k) or []) for k in ("coupled", "partial", "failed", "single_ended"))
        if self.plane_layers:
            head += "  " + plane_note(self.plane_layers)
        return head

    def as_dict(self) -> dict:
        return {"valid": self.valid, "closure": self.closure, "closure_clean": self.closure_clean,
                "open_before": self.open_before, "open_after": self.open_after, "open_nets": self.open_nets,
                "shorted": self.shorted, "excluded": self.excluded, "layers": self.layers,
                "seconds": self.seconds, "router_version": self.router_version, "drc_after": self.drc_after,
                "routed_pcb": str(self.routed_pcb), "log": str(self.log), "quick": self.quick,
                "invalid_reason": self.invalid_reason, "keepout_breaches": list(self.keepout_breaches),
                "pairs": self.pairs, "plane_layers": self.plane_layers}


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


def fill_zones(pcb_path: str) -> None:
    """Refill every zone and save: the router saves its new vias and tracks
    into the planes without refilling them, so the routed copy is not clean
    as it stands - only when a checker refills it."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(pcb_path)


def _copper_layers(pcb_path: str) -> list:
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
    return [board.GetLayerName(l) for l in board.GetEnabledLayers().CuStack()]


def _plane_zones(pcb_path: str) -> tuple:
    """Every non-rule-area zone's plain data off a loaded board - layer, net,
    whether it sits in a cell's group, and its own outline's area - plus the
    board outline's own area, for plane_layers to judge coverage against.
    Areas are left in pcbnew's own units: only ever compared as a ratio."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
    grouped = {it.m_Uuid.AsString() for g in board.Groups() for it in g.GetItems()}
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, False)
    zones = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea():
            continue
        area = z.Outline().Area()
        in_group = z.m_Uuid.AsString() in grouped
        for layer in z.GetLayerSet().CuStack():
            if board.IsLayerEnabled(layer):
                zones.append({"layer": board.GetLayerName(layer), "net": z.GetNetname(),
                             "in_group": in_group, "area": area})
    return tuple(zones), outline.Area()


def plane_layers(zones, board_area: float, share: float) -> list:
    """Every inner layer whose only content is the board's own plane: a
    zone that is not a rule area, not inside a cell's group (a stamped
    module's own zone is kept), covering at least `share` of the board's
    own outline. F.Cu and B.Cu never come back here - an outer layer is
    where the router reaches a pad from, plane or not."""
    if board_area <= 0:
        return []
    found = []
    for z in zones:
        layer = z["layer"]
        if layer in ("F.Cu", "B.Cu") or z["in_group"] or layer in found:
            continue
        if z["area"] / board_area >= share:
            found.append(layer)
    return sorted(found)


def resolved_layers(explicit, all_layers, zones, board_area: float, share: float) -> tuple:
    """The layers to route on, and what a plane took out of the default, as
    (layers, {layer: net}). An explicit list (an argument or [route] layers)
    is used as given; left to itself, every copper layer minus what
    plane_layers finds, F.Cu and B.Cu always among them - a real board's
    floor of two layers, so this never routes on fewer than that either."""
    if explicit:
        return list(explicit), {}
    dropped = plane_layers(zones, board_area, share)
    kept = [l for l in all_layers if l not in dropped]
    reasons = {z["layer"]: z["net"] for z in zones if z["layer"] in dropped}
    return kept, reasons


def plane_note(dropped: dict) -> str:
    """The route step's line for what a board's own plane took off the
    default layer list, and how to override it. `dropped` groups by the net
    that filled each layer, so one plane naming several layers reads as one
    clause."""
    if not dropped:
        return ""
    groups: dict = {}
    for layer in sorted(dropped):
        groups.setdefault(dropped[layer], []).append(layer)
    parts = []
    for net, layers in groups.items():
        pronoun = "it" if len(layers) == 1 else "them"
        parts.append("%s left out, the %s plane fills %s" % (", ".join(layers), net, pronoun))
    return "route layers: " + "; ".join(parts) + "; [route] layers to override"


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


@dataclass
class Pairs:
    """The pair router's outcome, from its own summary: pairs routed coupled,
    partly coupled, failed, or left to single-ended routing, and the nets of
    the pairs whose copper stays for the single-ended route to route around."""
    coupled: list = field(default_factory=list)
    partial: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    single_ended: list = field(default_factory=list)
    routed_nets: set = field(default_factory=set)

    def as_dict(self) -> dict:
        return {"coupled": self.coupled, "partial": self.partial, "failed": self.failed,
                "single_ended": self.single_ended}


def read_pairs(log: str) -> Pairs:
    """The pair router's (route_diff.py) outcome from its log: its own
    JSON_SUMMARY, the last one carrying the pair lists (a nested run prints
    summaries without them). Coupled and partial pairs keep their copper; a
    failed pair, or one the pair router left single-ended, is routed by the
    single-ended route like any other net."""
    found = None
    for line in log.splitlines():
        if line.startswith("JSON_SUMMARY: "):
            try:
                d = json.loads(line[len("JSON_SUMMARY: "):])
            except ValueError:
                continue
            if "routed_diff_pairs" in d:
                found = d
    if found is None:
        return Pairs()
    out = Pairs(sorted(found.get("routed_diff_pairs") or []), sorted(found.get("partial_diff_pairs") or []),
                sorted(found.get("failed_diff_pairs") or []), sorted(found.get("single_ended_diff_pairs") or []))
    keep = set(out.coupled) | set(out.partial)
    for r in found.get("pair_reports") or []:
        if r.get("pair") in keep:
            out.routed_nets |= {n for n in (r.get("p_net"), r.get("n_net")) if n}
    return out


def pair_command(python, script, pcb_in, pcb_out, patterns, layers, gap: float = 0.0, width: float = 0.0,
                 iterations: int | None = None, probe: int | None = None) -> list:
    """The pair router's command line. Width and gap are the net class's
    unless set (route_diff.py reads them from the board's project)."""
    cmd = [str(python), str(script), str(pcb_in), str(pcb_out), "--nets"] + list(patterns) + \
          ["--layers"] + list(layers) + ["--escalation", "off", "--keep-input-copper"]
    if gap:
        cmd += ["--diff-pair-gap", str(gap)]
    if width:
        cmd += ["--track-width", str(width)]
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    if probe is not None:
        cmd += ["--max-probe-iterations", str(probe)]
    return cmd


def route_pairs(rpy, router_dir_path, pcb_in: Path, work: Path, patterns, layers, cfg, iterations, probe,
                timeout, env) -> tuple:
    """Route the differential pairs with the router's pair router: returns
    (the board to route the rest on, Pairs). A board with no pair matching
    the patterns comes back as it went in."""
    script = Path(router_dir_path) / "py_router/route_diff.py"
    if not patterns or not script.exists():
        return pcb_in, Pairs()
    pcb_out = work / "pairs.kicad_pcb"
    cmd = pair_command(rpy, script, pcb_in, pcb_out, patterns, layers, cfg.route_diff_pair_gap,
                       cfg.route_diff_pair_width, iterations, probe)
    log = work / "pairs.log"
    with open(log, "w") as f:
        f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
        f.flush()
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir_path), env=env,
                            timeout=timeout).returncode
    text = log.read_text(errors="replace")
    pairs = read_pairs(text)
    if rc != 0 or not pcb_out.exists():
        if "matched no differential pair" in text or "No differential pairs" in text:
            return pcb_in, Pairs()
        tail = "\n".join(text.splitlines()[-8:])
        raise RuntimeError("the pair router exited %d without a routed board; log %s\n%s" % (rc, log, tail))
    for ext in (".kicad_pro", ".kicad_dru"):
        if (work / ("in" + ext)).exists():
            shutil.copy(work / ("in" + ext), work / ("pairs" + ext))
    lock_copper(str(pcb_out))
    return pcb_out, pairs


def router_version(router_dir: str) -> str:
    try:
        return (Path(router_dir) / "VERSION").read_text().strip()
    except OSError:
        return "unknown"


def router_command(python, script, pcb_in, pcb_out, excluded, layers, summary,
                   iterations: int | None = None, probe: int | None = None, quick: bool = False) -> list:
    """The router's command line. The search budget is the router's own
    default unless the caller sets one. A quick route is a measurement, so
    it skips the router's post-route smoothing pass: that pass cannot change
    what closed in one round and costs most of the run."""
    cmd = [str(python), str(script), str(pcb_in), str(pcb_out), "--nets", "*"] + \
          ["!" + n for n in sorted(excluded)] + ["--layers"] + list(layers) + ["--escalation", "off"] + \
          ["--keep-input-copper"]       # the script's copper is its intent: no cleanup pass removes it
    if quick:
        cmd.append("--no-smoothing")
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    if probe is not None:
        cmd += ["--max-probe-iterations", str(probe)]
    return cmd + ["--json-out", str(summary)]


def route_board(pcb, work, exclude_nets=(), layers=None, router_dir_override: str | None = None,
                quick: bool = False, iterations: int | None = None, probe: int | None = None,
                timeout: int | None = None) -> RouteReport:
    from ..settings import active
    cfg = active()
    router_dir_path = router_dir_override or router_dir(cfg)
    timeout = cfg.timeout_route if timeout is None else timeout
    iterations = cfg.route_iterations if iterations is None else iterations
    layers = layers if layers is not None else (list(cfg.route_layers) if cfg.route_layers else None)
    pcb, work = Path(pcb), Path(work)
    rpy = Path(router_dir_path) / ".venv/bin/python"
    route_py = Path(router_dir_path) / "py_router/route.py"
    if not (rpy.exists() and route_py.exists()):
        raise FileNotFoundError("router not found at %s (expected .venv/bin/python and py_router/route.py); "
                                "set KRT_DIR or [route] router_dir" % router_dir_path)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    pcb_in = work / "in.kicad_pcb"
    shutil.copy(pcb, pcb_in)
    for ext in (".kicad_pro", ".kicad_dru"):
        src = pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, work / ("in" + ext))
    lock_copper(str(pcb_in))
    if layers:
        all_layers, zones, board_area = [], (), 0.0
    else:
        all_layers = _copper_layers(str(pcb_in))
        zones, board_area = _plane_zones(str(pcb_in))
    layers, plane_dropped = resolved_layers(layers, all_layers, zones, board_area, cfg.route_plane_share)
    excluded = set(exclude_nets)

    before = run_drc(pcb_in, work / "drc_before.json")
    open0 = {n: v for n, v in before.open_nets.items() if n not in excluded}
    valid = not before.real

    pcb_out = work / "routed.kicad_pcb"
    summary = work / "router_summary.json"
    script = str(ONE_ROUND) if quick else str(route_py)
    env = dict(os.environ)
    env.pop("KICAD_ROUTE_TRACE", None)
    env["KRT_DIR"] = str(router_dir_path)
    t0 = time.time()
    # the differential pairs first, as pairs; the rest route around them
    board, pairs = route_pairs(rpy, router_dir_path, pcb_in, work, tuple(cfg.route_diff_pairs), layers, cfg,
                               iterations, probe, timeout, env)
    cmd = router_command(rpy, script, board, pcb_out, excluded | pairs.routed_nets, layers, summary,
                         iterations, probe, quick)
    log = work / "router.log"
    with open(log, "w") as f:
        f.write("$ %s\n\n" % " ".join(cmd))
        f.flush()
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir_path), env=env,
                            timeout=timeout).returncode
    seconds = round(time.time() - t0, 1)
    if rc != 0 or not pcb_out.exists():
        tail = "\n".join(log.read_text(errors="replace").splitlines()[-8:])
        raise RuntimeError("router exited %d without a routed board; log %s\n%s" % (rc, log, tail))
    for ext in (".kicad_pro", ".kicad_dru"):
        if (work / ("in" + ext)).exists():
            shutil.copy(work / ("in" + ext), work / ("routed" + ext))
    fill_zones(str(pcb_out))
    after = run_drc(pcb_out, work / "drc_after.json")
    open1 = {n: v for n, v in after.open_nets.items() if n not in excluded}
    violated = _nets_in_violations(json.loads((work / "drc_after.json").read_text()))
    sc = score(open0, open1, {n for n in violated if n not in excluded})
    report = RouteReport(valid, round(sc.closure, 4), round(sc.closure_clean, 4), sum(open0.values()), sum(open1.values()),
                         dict(sorted(open1.items())), sc.shorted, sorted(excluded), layers, seconds,
                         router_version(router_dir_path), after.by_type, pcb_out, log, work,
                         "" if valid else "placement DRC not clean before routing: %s" % before.real, quick,
                         router_breaches(pcb_in, pcb_out), pairs.as_dict(), plane_dropped)
    (work / "route.json").write_text(json.dumps(report.as_dict(), indent=2) + "\n")
    return report


def router_breaches(pcb_in, pcb_out) -> list:
    """What the router laid inside a region that forbids it, judged against
    the rule areas on the board it was given. Only the router's copper: the
    script's own is judged by the layout, which knows a keepout's allow=."""
    from ..board_geometry import added_copper, keepout_breaches
    from .read import read_board
    given, routed = read_board(pcb_in), read_board(pcb_out)
    return keepout_breaches(given.rule_areas, added_copper(given.copper, routed.copper))
