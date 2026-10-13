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

from .. import route_progress
from ..childenv import child_env
from .drc import run_drc

ROUTER_SETTING = "[route] router_dir"
ROUTER_ENV = "KRT_DIR"
ROUTER_FILES = (".venv/bin/python", "py_router/route.py")   # what a router checkout holds


def active_settings():
    from ..settings import active
    return active()


class RouterMissing(RuntimeError):
    """No router to route with: `code` is "router_unset" (neither `[route] router_dir` nor $KRT_DIR names one) or
    "router_not_found" (the folder named lacks ROUTER_FILES), and `facts` its values. The text is
    router_missing_text's."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, dict(facts)
        super().__init__(router_missing_text(code, self.facts))

    def record(self) -> dict:
        return {"code": self.code, **self.facts}


def router_missing_text(code: str, facts: dict) -> str:
    """The console sentence of a RouterMissing (its code, and its facts or the whole record)."""
    if code == "router_unset":
        return "no router: set %s in placemat.toml or $%s to a KiCadRoutingTools checkout" % (facts["setting"], facts["env"])
    return "no router at %s (named by %s): it has no %s" % (facts["path"], facts["source"], " or ".join(facts["missing"]))


def configured_router(cfg=None) -> tuple:
    """(the router's folder, what named it) - placemat.toml's `[route] router_dir` (a project fact), else $KRT_DIR (a
    machine fact) - or (None, None) when neither is set."""
    from ..settings import active
    cfg = active() if cfg is None else cfg
    if cfg.route_router_dir:
        return cfg.route_router_dir, ROUTER_SETTING
    if os.environ.get(ROUTER_ENV):
        return os.environ[ROUTER_ENV], "$" + ROUTER_ENV
    return None, None


def router_dir(cfg=None) -> str:
    """Where the router lives (configured_router); RouterMissing "router_unset" when nothing names it."""
    path, _ = configured_router(cfg)
    if path is None:
        raise RouterMissing("router_unset", setting=ROUTER_SETTING, env=ROUTER_ENV)
    return path


def checked_router(path: str, source: str) -> str:
    """`path`, when it holds a router checkout; RouterMissing "router_not_found" naming the files it lacks."""
    missing = [f for f in ROUTER_FILES if not (Path(path) / f).exists()]
    if missing:
        raise RouterMissing("router_not_found", path=str(path), source=source, missing=missing)
    return path


ONE_ROUND = Path(__file__).with_name("route_one_round.py")
HOOKED = Path(__file__).with_name("route_hooked.py")     # runs a router entry script with the progress hooks (route_events.py)
_HOOK = False                                             # set by route_board while it routes with progress events


def _load_board(path):
    """A board loaded with KiCad's UUID generator seeded from its file (write.load_board): the same input gives the
    same item ids in every run."""
    from .write import load_board
    return load_board(path)


def _launch(python, script) -> list:
    """The start of a router command: the interpreter and the script, behind the hooking wrapper when this route reports progress (the quick
    route's own wrapper is hooked already)."""
    if _HOOK and Path(script).name != ONE_ROUND.name:
        return [str(python), str(HOOKED), str(script)]
    return [str(python), str(script)]


_REFUSED = {
    "no_phases": "route: no routing phases in placemat.toml; `placemat settings --example` writes a placemat.toml with "
                 "example phases",

    "unknown_phase": "route: no phase %(phase)r; the phases are %(phases)s",
    "capture": "route: %(path)s: %(reason)s %(detail)s",
    "router_old": "route: the router at %(router)s lacks %(missing)s: route with the placemat fork of KiCadRoutingTools",
    "width_policy_unavailable": "route: the router at %(router)s cannot answer the width query %(script)s: route with "
                                "the placemat fork of KiCadRoutingTools",
    "width_policy_failed": "route: the router's width query gave no widths: %(failure)s; its output is in %(log)s",
    "router_refused": "route: phase %(phase)r: the router refused %(what)s",
    "pair_flag": "route: phase %(phase)r: router_args %(flag)s is not a flag of the pair router (route_diff.py), which "
                 "this phase's pair call runs",
    "router_owned": "route: %(where)s: router_args %(flag)s is the router's %(owned)s, which placemat sets itself",
}



def refused_text(code: str, facts: dict) -> str:
    """A RouteRefused as a sentence: the edge's rendering of its code and facts."""
    if code == "router_refused":
        facts = dict(facts, what=", ".join("%s %s.%s-%s.%s %s" % (t["net"], t["from"]["ref"], t["from"]["pad"],
                                                                  t["to"]["ref"], t["to"]["pad"], t["reason"])
                                           for t in facts["tasks"]))

    elif code == "router_old":
        def said(m):
            if "form" in m:
                return "%s as %s" % (m["flag"], {"per_layer": "LAYER=MM"}.get(m["form"], m["form"]))
            if "pad_field" in m:
                return "--pads field %r" % m["pad_field"]
            return m["flag"] if "flag" in m else "task field %r" % m["field"]
        facts = dict(facts, missing=", ".join("%s %s" % (m["module"], said(m)) for m in facts["missing"]))
    elif code == "router_owned":
        facts = dict(facts, where="[route]" if facts.get("phase") is None else "phase %r" % facts["phase"])
    elif code == "capture":
        facts = dict(facts, detail=", ".join("%s %s" % kv for kv in sorted((facts.get("detail") or {}).items())))
    return _REFUSED[code] % facts


class RouteRefused(ValueError):
    """A route placemat will not start or go on with: `code` (a key of _REFUSED: no_phases,
    unknown_phase, capture, router_old, pair_flag, router_owned, router_refused) and its `facts`; refused_text renders it."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, dict(facts)
        super().__init__(refused_text(code, self.facts))

    def record(self) -> dict:
        return {"code": self.code, **self.facts}


class RouterFailed(RuntimeError):
    """A router call that exited non-zero or wrote no board: `what` failed, the call's `exit_code`, its `log` and the log's
    last lines (`tail`)."""

    def __init__(self, what: str, exit_code, log, tail: str, *, code="router_failed", facts=None):
        super().__init__("%s; log %s\n%s" % (what, log, tail))
        self.what, self.exit_code, self.log, self.tail = what, exit_code, Path(log), tail
        self.code, self.facts = code, dict(facts or {})


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
    # An inner layer left out of `layers` because the board's own plane
    # fills it whole, {layer: the net that fills it}; empty when the layers
    # were given (an argument or [route] layers), not defaulted.
    plane_layers: dict = field(default_factory=dict)
    # Partial inner-layer pours of nets left out, kept clear of other nets'
    # tracks in the router's input copy: "NET on LAYER" each.
    pours_kept: list = field(default_factory=list)
    # The stages taken from an earlier route of the same inputs rather than run (route_state.py).
    resumed: list = field(default_factory=list)
    # The route record (route_progress.py): the events of every stage in laid order, what the studio replays the route from; "" when
    # events are off.
    record: str = ""
    # Copper laid under the width it was asked (route_widths.py): each phase's per-call records (phase_run.phase_widths,
    # task_widths), the router's per-stage summaries, and one record per obligation the final board joins under its
    # width on its joining path, whichever call laid it (phase_run.judged_widths, "source": "judged").
    widths: list = field(default_factory=list)
    # Capture clearances as applied, trapped pads, and structured setup findings in presentation order.
    net_clearances: dict = field(default_factory=dict)
    net_clearance_trapped: list = field(default_factory=list)
    net_clearance_facts: list = field(default_factory=list)
    duplicate_references: list = field(default_factory=list)   # phase_select.duplicate_references on the routed nets
    # The router's dangling copper taken off the routed copy (route_cleanup.py, KiCad's TRACKS_CLEANER): Cleanup.record(),
    # {"tracks": {net: n}, "vias": {net: n}, "merged": {net: n}, "unconnected": [before, after],
    # "kept_unrouted": [nets left unconnected whose dangling router copper was kept],
    # "refused_nets": [nets whose pads the dangling router copper alone joins, which keep it],
    # "vias_merged": {net: n} (router vias merged into a same-net hole within hole-to-hole),
    # "vias_kept_close": [{"net", "at_mm", "near_mm", "distance_mm", "reason"}] (such vias left in place)}.
    dangling_removed: dict = field(default_factory=dict)
    # The nets `shorted` lists, with the kinds of the real DRC violations each is in: {net: [kind, ...]}. A net named there need not be
    # shorted; a hole_to_hole between two of its own vias puts it there too.
    violations: dict = field(default_factory=dict)
    # Each routing phase's record (phase_run.phase_record), in order: what it was asked (`asked`, its obligations fixed
    # from the input board), what it left clean (`joined`, `closure_clean`) and open (`open`), and the same obligations
    # judged on the final board (`final_closure_clean`, `final_open`).
    phases: list = field(default_factory=list)
    # With `only`: the earlier phases none of whose nets has a track on the board (D26).
    phases_without_copper: list = field(default_factory=list)
    # {pour net: the first phase that routes it in a pour call (D15)}, for the phase lines (phase_lines).
    pour_routed_by: dict = field(default_factory=dict)
    # Obligations joined on the final board whose joining path is under their width, or not measured (Task 15; S8).
    widths_failed: int = 0
    # Real-bucket DRC errors on the final board beyond the input board's (drc.real_errors, drc.new_errors); None when
    # either DRC wrote no report.
    drc_new: int | None = None
    # The routed copper on the final board (routed_copper): vias, track length (mm), straight track segments.
    vias: int = 0
    track_mm: float = 0.0
    segments: int = 0
    # Each phase's obligations and their judgement on the final board, in phase order (Task 15 reads them; not in
    # as_dict).
    asked: list = field(default_factory=list)
    final_judged: list = field(default_factory=list)

    def has_findings(self) -> bool:
        return bool(self.widths or self.net_clearance_facts or self.duplicate_references)

    def findings(self, stated: dict | None = None) -> list:
        """Width findings followed by capture-clearance setup findings."""
        from .route_widths import findings_of
        return findings_of(self.widths, stated) + self.setup_findings()

    def setup_findings(self) -> list:
        """The setup findings `route_board` hands to `on_setup` before it routes: `setup.net_clearance` and
        `setup.duplicate_reference`."""
        from ..findings import Finding, FindingCause as C
        return ([Finding(C.SETUP_NET_CLEARANCE, dict(f)) for f in self.net_clearance_facts]
                + [Finding(C.SETUP_DUPLICATE_REFERENCE, dict(f)) for f in self.duplicate_references])

    def summary(self) -> str:
        head = "route %s: closure %.1f%% clean (%.1f%% raw), %d -> %d open signal item(s)" % (
            "quick" if self.quick else "full", 100 * self.closure_clean, 100 * self.closure,
            self.open_before, self.open_after)
        if not self.valid:
            head += "  INVALID: " + self.invalid_reason
        if self.shorted:
            head += "  with DRC violations: " + ", ".join(
                "%s (%s)" % (n, ", ".join(self.violations[n])) if self.violations.get(n) else n for n in self.shorted)
        if self.keepout_breaches:
            head += "  %d item(s) inside a keepout" % len(self.keepout_breaches)
        if self.plane_layers:
            head += "  " + plane_note(self.plane_layers)
        if self.pours_kept:
            head += "  other nets kept out of %d pour(s)" % len(self.pours_kept)
        if self.net_clearances:
            head += "  clearances: " + ", ".join("%s %g mm" % kv for kv in sorted(self.net_clearances.items()))
        d = self.dangling_removed or {}
        tracks, vias = sum((d.get("tracks") or {}).values()), sum((d.get("vias") or {}).values())
        if tracks or vias:
            nets = len(set(d.get("tracks") or {}) | set(d.get("vias") or {}))
            head += "  dangling router copper removed: %d track(s), %d via(s) on %d net(s)" % (tracks, vias, nets)
        if d.get("kept_unrouted"):
            head += "  dangling router copper kept on %d unrouted net(s): %s" % (len(d["kept_unrouted"]), ", ".join(d["kept_unrouted"]))
        if d.get("refused_nets"):
            head += "  dangling router copper kept on %d net(s) whose pads it alone joins: %s" % (
                len(d["refused_nets"]), ", ".join(d["refused_nets"]))
        if d.get("vias_merged"):
            head += "  same-net vias within hole-to-hole merged: %d via(s) on %d net(s)" % (
                sum(d["vias_merged"].values()), len(d["vias_merged"]))
        if d.get("vias_kept_close"):
            head += "  same-net vias within hole-to-hole kept: " + ", ".join(
                "%s at (%g, %g)" % (k["net"], k["at_mm"][0], k["at_mm"][1]) for k in d["vias_kept_close"])
        if self.phases:
            head += "  phases: " + ", ".join("%s %.0f%%" % (p["name"], 100 * p["closure_clean"]) for p in self.phases)
        if self.widths_failed:
            head += "  %d connection(s) under their width or not measured" % self.widths_failed
        if self.drc_new:
            head += "  %d new DRC error(s)" % self.drc_new
        if self.widths:
            from .route_widths import brief
            head += "  UNDER WIDTH: " + "; ".join(brief(r) for r in self.widths)
        return head

    def as_dict(self) -> dict:
        return {"valid": self.valid, "closure": self.closure, "closure_clean": self.closure_clean,
                "open_before": self.open_before, "open_after": self.open_after, "open_nets": self.open_nets,
                "shorted": self.shorted, "violations": {n: list(k) for n, k in self.violations.items()}, "excluded": self.excluded, "layers": self.layers,
                "seconds": self.seconds, "router_version": self.router_version, "drc_after": self.drc_after,
                "routed_pcb": str(self.routed_pcb), "log": str(self.log), "quick": self.quick,
                "invalid_reason": self.invalid_reason, "keepout_breaches": list(self.keepout_breaches),
                "plane_layers": self.plane_layers,
                "pours_kept": list(self.pours_kept),
                "resumed": list(self.resumed), "record": self.record, "widths": list(self.widths),
                "net_clearances": dict(self.net_clearances),
                "net_clearance_trapped": list(self.net_clearance_trapped), "duplicate_references": list(self.duplicate_references), "dangling_removed": dict(self.dangling_removed),
                "phases": list(self.phases), "phases_without_copper": list(self.phases_without_copper),
                "pour_routed_by": dict(self.pour_routed_by), "widths_failed": self.widths_failed, "drc_new": self.drc_new, "vias": self.vias,
                "track_mm": self.track_mm, "segments": self.segments}


def plane_nets_of(pcb) -> set:
    """The nets a board serves by a pour: each with a copper zone, or a
    filled copper polygon, of the board's own on it. What run --route leaves
    out as the plan's plane nets, read off the written board: a stamped
    cell's local zone or pour (in its group) does not count, its net still
    runs to parts elsewhere."""
    from .quiet import import_pcbnew, quiet_stderr
    from .read import is_pour
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(str(pcb)) if Path(pcb).stat().st_size else None
    if board is None:
        return set()
    grouped = {it.m_Uuid.AsString() for g in board.Groups() for it in g.GetItems()}
    nets = {z.GetNetname() for z in board.Zones() if is_pour(z) and z.GetNetname()
            and z.m_Uuid.AsString() not in grouped}
    nets |= {d.GetNetname() for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE) and d.GetNetname()
             and d.IsOnCopperLayer() and (d.IsSolidFill() if hasattr(d, "IsSolidFill") else False)
             and d.m_Uuid.AsString() not in grouped}
    return nets


GUARD = "placemat footprint copper"


def guard_footprint_copper(pcb_path: str) -> int:
    """Keep the router off every footprint's copper graphics: it reads a
    footprint's graphics only on Edge.Cuts, so a net-tie's winding is not an
    obstacle to it. Each graphic gets a rule area on its own layer, drawn as
    its copper outline, forbidding tracks and vias, named for its footprint
    so `remove_guards` finds it. The graphics guarded."""
    from .quiet import import_pcbnew, quiet_stderr
    from .read import CLEAR_ERR_NM
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    n = 0
    for fp in board.GetFootprints():
        for d in fp.GraphicalItems():
            layer = d.GetLayer()
            if not (isinstance(d, pcbnew.PCB_SHAPE) and pcbnew.IsCopperLayer(layer)):
                continue
            ps = pcbnew.SHAPE_POLY_SET()        # a stroked shape comes as its fill and each stroke: one outline
            d.TransformShapeToPolySet(ps, layer, 0, CLEAR_ERR_NM, pcbnew.ERROR_OUTSIDE)
            ps.Simplify()
            # the footprint's own pads stay reachable: the router keeps every net, the pad's own
            # included, off a rule area, and a winding that ends on a small pad would close it
            own = pcbnew.SHAPE_POLY_SET()
            for pad in fp.Pads():
                if pad.IsOnLayer(layer):
                    pad.TransformShapeToPolygon(own, layer, 0, CLEAR_ERR_NM, pcbnew.ERROR_OUTSIDE)
            if own.OutlineCount():
                ps.BooleanSubtract(own)
            if ps.OutlineCount():
                n += 1
            for i in range(ps.OutlineCount()):  # a zone a piece: placemat reads a rule area's first outline
                z = pcbnew.ZONE(board)
                z.SetIsRuleArea(True)
                ls = pcbnew.LSET()
                ls.AddLayer(layer)
                z.SetLayerSet(ls)
                z.SetDoNotAllowTracks(True)
                z.SetDoNotAllowVias(True)
                z.SetDoNotAllowPads(False)
                z.SetDoNotAllowZoneFills(False)
                z.SetDoNotAllowFootprints(False)
                o = z.Outline()
                k = o.AddOutline(ps.Outline(i))
                for j in range(ps.HoleCount(i)):
                    o.AddHole(ps.Hole(i, j), k)
                z.SetZoneName("%s %s" % (GUARD, fp.GetReference()))
                board.Add(z)
    if n:
        with quiet_stderr():
            board.Save(pcb_path)
    return n


POUR_GUARD = "placemat pour"


def guard_partial_pours(pcb_path: str, nets, layers, share: float) -> list:
    """Keep other nets' tracks out of each partial inner-layer pour of a net
    the route leaves out: the router does not see copper zones when it
    routes other nets, so it would lay tracks through the pour's outline and
    the refill would split it. Each such zone gets a rule area over its
    outline on each inner layer the route uses, forbidding tracks (vias,
    pads and fills may pass: the pour is refilled round a via), named for
    the pour so `remove_guards` removes it. A pour covering at
    least `share` of the board is a plane, and an outer layer's pours hold
    other nets' surface pads: neither is guarded. "NET on LAYER" per guard."""
    from .quiet import import_pcbnew, quiet_stderr
    from .read import is_pour, standard_layer_name
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, False)
    board_area = outline.Area()
    routed = set(layers or ())
    out = []
    for z in list(board.Zones()):
        if not is_pour(z) or z.GetNetname() not in nets:
            continue
        if board_area and z.Outline().Area() >= share * board_area:
            continue
        for layer in z.GetLayerSet().CuStack():
            name = standard_layer_name(layer)
            if layer in (pcbnew.F_Cu, pcbnew.B_Cu) or name not in routed or not board.IsLayerEnabled(layer):
                continue
            g = pcbnew.ZONE(board)
            g.SetIsRuleArea(True)
            ls = pcbnew.LSET()
            ls.AddLayer(layer)
            g.SetLayerSet(ls)
            g.SetDoNotAllowTracks(True)
            g.SetDoNotAllowVias(False)
            g.SetDoNotAllowPads(False)
            g.SetDoNotAllowZoneFills(False)
            g.SetDoNotAllowFootprints(False)
            g.Outline().Append(z.Outline())
            g.SetZoneName("%s %s %s" % (POUR_GUARD, z.GetNetname(), name))
            board.Add(g)
            out.append("%s on %s" % (z.GetNetname(), name))
    if out:
        with quiet_stderr():
            board.Save(pcb_path)
    return out


def remove_guards(pcb_path: str) -> int:
    """Delete the guards `guard_footprint_copper` and `guard_partial_pours`
    added from the routed copy. The guards removed."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    guards = [z for z in board.Zones() if z.GetZoneName().startswith((GUARD, POUR_GUARD))]
    for z in guards:
        board.Delete(z)
    if guards:
        with quiet_stderr():
            board.Save(pcb_path)
    return len(guards)


def lock_copper(pcb_path: str) -> int:
    """Lock every track, via and copper polygon so the router keeps them."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
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
        board = _load_board(pcb_path)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        board.Save(pcb_path)


def _copper_layers(pcb_path: str) -> list:
    from .quiet import import_pcbnew, quiet_stderr
    from .read import standard_layer_name
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    return [standard_layer_name(l) for l in board.GetEnabledLayers().CuStack()]


def resolved_layers(explicit, board_layers, layer_types) -> tuple:
    """The layers to route on, and what the default left out and why
    ({layer: role}). An explicit list (an argument only - [route] layers is
    retired; `placemat route --layers` is the sole override) is used as
    given. Left to itself, every layer whose role is signal or mixed, F.Cu
    and B.Cu always among them - a real board's floor of two layers, so
    this never routes on fewer than that either."""
    if explicit:
        return list(explicit), {}
    kept, dropped = [], {}
    for l in board_layers:
        role = layer_types.get(l, "signal")
        if l in ("F.Cu", "B.Cu") or role in ("signal", "mixed"):
            kept.append(l)
        else:
            dropped[l] = role
    return kept, dropped


def plane_note(dropped: dict) -> str:
    """The route step's line for what the default layer list left out and
    why (its role), and how to override it."""
    if not dropped:
        return ""
    groups: dict = {}
    for layer in sorted(dropped):
        groups.setdefault(dropped[layer], []).append(layer)
    parts = []
    for role, layers in sorted(groups.items()):
        parts.append("%s left out, role %s" % (", ".join(layers), role))
    return "route layers: " + "; ".join(parts) + "; placemat route --layers to override"


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

    def to_dict(self) -> dict:
        """Every field, for a route's saved state."""
        return {**self.as_dict(), "routed_nets": sorted(self.routed_nets)}

    @staticmethod
    def from_dict(d: dict) -> "Pairs":
        return Pairs(list(d["coupled"]), list(d["partial"]), list(d["failed"]), list(d["single_ended"]),
                     set(d.get("routed_nets", ())))

    def renamed(self, names: dict) -> "Pairs":
        """The same outcome with each pair and net named by `names` where it
        has an entry: an explicit pair's alias back to its own names."""
        def back(items):
            return sorted(names.get(x, x) for x in items)
        return Pairs(back(self.coupled), back(self.partial), back(self.failed), back(self.single_ended),
                     {names.get(n, n) for n in self.routed_nets})


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
                 iterations: int | None = None, probe: int | None = None, clearances: Path | None = None,
                 extra_args=()) -> list:
    """The pair router's command line. `extra_args` are a phase's own router flags, after `[route] pair_router_args`. Width and gap are the net class's
    unless set (route_diff.py reads them from the board's project).
    `clearances`: the per-net clearance map placemat wrote (net_clearance.py);
    None leaves the router to build its own from the net classes."""
    cmd = _launch(python, script) + [str(pcb_in), str(pcb_out), "--nets"] + list(patterns) + \
          ["--layers"] + list(layers) + ["--escalation", "off", "--keep-input-copper"] + _tuning()
    if gap:
        cmd += ["--diff-pair-gap", str(gap)]
    if width:
        cmd += ["--track-width", str(width)]
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    if probe is not None:
        cmd += ["--max-probe-iterations", str(probe)]
    if clearances is not None:
        cmd += ["--net-clearances", str(clearances)]
    return cmd + list(active_settings().route_pair_router_args) + list(extra_args)






def _tuning() -> list:
    """The router's turn cost, on every pass. Diverges from the router's own
    default (1000, where a 45-degree kink costs 0.05 mm of path and routes
    stair-step): see Settings.route_turn_cost."""
    return ["--turn-cost", str(int(active_settings().route_turn_cost))]


def _net_names(pcb) -> set:
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(str(pcb))
    return {str(n) for n in board.GetNetsByName().keys() if str(n)}


def rename_nets(pcb_path: str, names: dict) -> None:
    """Rename the board's nets {old: new}, the copper on them with them. The
    router reads a net's class from the project by its name, so each new
    name is given the classes the old one had there (its own assignment and
    the patterns that matched it), and the old name's assignment goes."""
    from fnmatch import fnmatchcase
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    by_name = board.GetNetsByName()
    for old, new in names.items():
        by_name[old].SetNetname(new)
    with quiet_stderr():
        board.Save(pcb_path)
    pro = Path(pcb_path).with_suffix(".kicad_pro")
    if not pro.exists():
        return
    data = json.loads(pro.read_text())
    ns = data.get("net_settings") or {}
    assigned = ns.get("netclass_assignments") or {}
    patterns = [(e.get("pattern"), e.get("netclass")) for e in ns.get("netclass_patterns") or []]
    moved = {}
    for old, new in names.items():
        own = assigned.get(old) or []
        classes = list(own) if isinstance(own, list) else [own]
        classes += [c for pat, c in patterns if pat and c and fnmatchcase(old, pat) and c not in classes]
        if classes:
            moved[new] = classes
    if not moved and not set(names) & set(assigned):
        return
    ns["netclass_assignments"] = {**{k: v for k, v in assigned.items() if k not in names}, **moved}
    data["net_settings"] = ns
    pro.write_text(json.dumps(data, indent=2) + "\n")


def route_pairs(rpy, router_dir_path, pcb_in: Path, work: Path, pairs, layers, cfg, iterations, probe,
                timeout, env, events=None, clearances: dict | None = None,
                stem: str = "pairs", extra_args=()) -> tuple:
    """Route the phase's differential pairs on its layers, returning the board and Pairs result.

    The router pairs nets by their suffix alone, so every pair is routed in
    a copy where its nets are renamed to a suffix pair (pairs.pair_aliases),
    whatever they were called, and renamed back in the routed board before
    anything reads it. A net the board does not have is a ValueError,
    before the router runs.

    With `halos` ({net: mm}, the ones on the board) every call is given the
    clearance map net_clearance.py writes, built on the renamed copy under its
    names."""
    from ..pairs import pair_aliases
    if not pairs:
        return pcb_in, Pairs()
    names = _net_names(pcb_in)
    missing = [n for pair in pairs for n in pair if n not in names]
    if missing:
        raise ValueError("the board's net classes name %s for a differential pair, which it has no net called"
                         % ", ".join(missing))
    aliases = pair_aliases(pairs, names)
    script = Path(router_dir_path) / "py_router/route_diff.py"
    if not script.exists():
        return pcb_in, Pairs()
    renames = {old: base + suffix for base, p, n in aliases for old, suffix in ((p, "_P"), (n, "_N"))}
    router_in = work / (stem + "_in.kicad_pcb")
    shutil.copy(pcb_in, router_in)
    _copy_project(pcb_in, router_in)
    rename_nets(str(router_in), renames)
    stated_clearances = clearances
    clearances = None
    if stated_clearances:
        from . import net_clearance
        clearances = net_clearance.write_map(rpy, router_dir_path, router_in, sorted(renames.get(n, n) for n in names),
                                         {renames.get(n, n): h for n, h in stated_clearances.items()}, work / net_clearance.PAIR_MAP_NAME,
                                         net_clearance.ceiling(tuple(active_settings().route_pair_router_args) + tuple(extra_args), env), env)
    back = {new: old for old, new in renames.items()}
    back.update({base: "%s/%s" % (p, n) for base, p, n in aliases})
    if events is not None:
        events.names = back                      # the router routes under the aliases: its events name the board's nets
    pcb_out = work / (stem + ".kicad_pcb")
    groups = [(layers, pairs)]
    alias_of = {(p, n): base for base, p, n in aliases}
    board, found = router_in, None
    for i, (group_layers, group) in enumerate(groups):
        out = pcb_out if i == len(groups) - 1 else work / ("%s_%d.kicad_pcb" % (stem, i))
        cmd = pair_command(rpy, script, board, out, tuple(alias_of[pair] for pair in group), group_layers,
                           cfg.route_diff_pair_gap, cfg.route_diff_pair_width, iterations, probe, clearances,
                           extra_args)
        log = work / (stem + ".log" if i == 0 else "%s_%d.log" % (stem, i))
        rc = run_router(cmd, log, router_dir_path, env, timeout)
        text = log.read_text(errors="replace")
        if rc != 0 or not out.exists():
            if "matched no differential pair" in text or "No differential pairs" in text:
                continue
            tail = "\n".join(text.splitlines()[-8:])
            raise RouterFailed("the pair router exited %d without a routed board" % rc, rc, log, tail)
        found = _merged(found, read_pairs(text))
        _copy_project(router_in, out)             # the next call reads the renamed nets' classes beside its board
        lock_copper(str(out))                     # and keeps this call's copper as it stands
        board = out
    if found is None:
        return pcb_in, Pairs()
    if board != pcb_out:
        shutil.copy(board, pcb_out)
    result_pairs = found.renamed(back)
    rename_nets(str(pcb_out), {new: old for old, new in renames.items()})
    for ext in (".kicad_pro", ".kicad_dru"):
        if (work / ("in" + ext)).exists():
            shutil.copy(work / ("in" + ext), work / (stem + ext))
    lock_copper(str(pcb_out))
    return pcb_out, result_pairs


def _merged(a: "Pairs | None", b: Pairs) -> Pairs:
    """Two pair router calls' outcomes as one."""
    if a is None:
        return b
    return Pairs(sorted(a.coupled + b.coupled), sorted(a.partial + b.partial), sorted(a.failed + b.failed),
                 sorted(a.single_ended + b.single_ended), a.routed_nets | b.routed_nets)


def router_version(router_dir: str) -> str:
    try:
        return (Path(router_dir) / "VERSION").read_text().strip()
    except OSError:
        return "unknown"









def drop_pour_guards(pcb_path: str, nets) -> None:
    """Delete the pour guards `guard_partial_pours` added for `nets`."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    names = tuple("%s %s " % (POUR_GUARD, n) for n in nets)
    guards = [z for z in board.Zones() if z.GetIsRuleArea() and z.GetZoneName().startswith(names)]
    for z in guards:
        board.Delete(z)
    if guards:
        with quiet_stderr():
            board.Save(pcb_path)


POUR_ZONE = "placemat graphic pour"


def pours_as_zones(pcb_path: str, net: str) -> int:
    """Hand the router `net`'s own filled copper graphics as zones, for a
    call that routes `net` alone. `board.pour` draws a pour as a filled
    graphic polygon (write.py _draw_pour). The router credits a net's zones
    as joining the pads they reach for a plane,
    but it reads a filled graphic as scanline bands
    (KRT kicad_parser.py filled_area_spans) and takes each band for an
    island of the net to join (connectivity.py
    _get_multipoint_net_pads_unordered, one terminal per copper group): it
    then lays a mesh of short tracks over the pour, and their ends stand
    past its edge into the clearance the pour kept. Each graphic gives way
    to a zone over its copper outline (stroke included), solid to pads,
    keeping its islands, filled, named for the graphic so `pours_back` puts
    the graphic back. The graphics replaced."""
    from .quiet import import_pcbnew, quiet_stderr
    from .read import CLEAR_ERR_NM
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    shapes = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE) and d.GetNetname() == net
              and d.IsOnCopperLayer() and d.IsSolidFill()]
    ds = board.GetDesignSettings()
    zones = []
    for d in shapes:
        layer = d.GetLayer()
        ps = pcbnew.SHAPE_POLY_SET()
        d.TransformShapeToPolySet(ps, layer, 0, CLEAR_ERR_NM, pcbnew.ERROR_OUTSIDE)
        ps.Simplify()
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNetCode(d.GetNetCode())
        z.SetLocalClearance(0)                  # the net classes' clearances, as the pour was fitted to
        z.SetMinThickness(ds.m_TrackMinWidth or ds.GetDefault().GetTrackWidth())
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        z.Outline().Append(ps)
        z.SetZoneName("%s %s" % (POUR_ZONE, d.m_Uuid.AsString()))
        group = d.GetParentGroup()
        if group is not None:
            group.RemoveItem(d)
        board.Delete(d)
        board.Add(z)
        if group is not None:                   # the zone holds the graphic's place in its group (an empty one is not saved)
            group.AddItem(z)
        zones.append(z)
    if zones:
        with quiet_stderr():
            pcbnew.ZONE_FILLER(board).Fill(zones)
            board.Save(pcb_path)
    return len(zones)


def pours_back(pcb_path: str, given: str) -> int:
    """Undo `pours_as_zones` on the router's output: delete each zone it
    drew and put back the graphic it stood for, as drawn on `given` (the
    board before), its uuid kept, in the group the zone held its place in.
    The graphics put back."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(pcb_path)
    zones = [z for z in board.Zones() if z.GetZoneName().startswith(POUR_ZONE + " ")]
    if not zones:
        return 0
    with quiet_stderr():
        before = _load_board(str(given))
    by_uuid = {d.m_Uuid.AsString(): d for d in before.GetDrawings()}
    n = 0
    for z in zones:
        d = by_uuid.get(z.GetZoneName()[len(POUR_ZONE) + 1:])
        group = z.GetParentGroup()
        if group is not None:
            group.RemoveItem(z)
        board.Delete(z)
        if d is None:
            continue
        sh = d.Duplicate()                      # (PCB_SHAPE(d) is the constructor taking a parent, not a copy)
        sh.SetUuid(d.m_Uuid)
        sh.SetParentGroup(None)                 # the copy names `given`'s group; it takes the zone's place here
        sh.SetParent(board)
        board.Add(sh)
        sh.SetNetCode(board.GetNetcodeFromNetname(d.GetNetname()))
        if group is not None:
            group.AddItem(sh)
        n += 1
    with quiet_stderr():
        board.Save(pcb_path)
    return n


def run_router(cmd, log: Path, router_dir, env, timeout, stdin: str | None = None) -> int:
    """One router process in the router's checkout: its command line and output in `log`, `stdin` its input; its exit
    code. subprocess.TimeoutExpired after `timeout` seconds."""
    with open(log, "w") as f:
        f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
        f.flush()
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir), env=env, timeout=timeout,
                              input=stdin.encode() if stdin is not None else None,
                              pass_fds=route_progress.pass_fds()).returncode


def _copy_project(src_pcb, dst_pcb) -> None:
    """The board's project files beside a copy of it: the router reads the
    netclasses (their widths and clearances) from them."""
    copy_source_rules(src_pcb, dst_pcb)


def router_net_pattern(name: str, form: str) -> str:
    """One net name written as the router reads it for `form`, so that it takes that net and no other:
    "include" (`--nets`, `--bus-nets`), "exclude" (a `'!NET'` after `--nets '*'`) or "power" (`--power-nets`).

    KRT reads every one as an fnmatch pattern (net_queries.py:55-84 net_pattern_matches for --nets; :916-954
    identify_power_nets, plain fnmatch, for --power-nets), so '[', '*' and '?' in a name are written '[[]', '[*]' and
    '[?]': D[0] then takes the net D[0], not D0. In an include a leading '!' would be an exclusion, so a net named '!RST'
    is written '\\!RST' (net_queries.py:17-52, split_net_patterns); --power-nets knows no such escape.

    Limitation: a name with no '/' also takes a sheet-qualified net of the same last part (KRT's leaf rule,
    net_pattern_matches: 'GND' takes '/Sub/GND'), and KRT has no pattern for an unqualified name that does not. The
    phases select nets by the same rule (phase_select.net_matches), so what a phase selects and what its call routes
    agree."""
    lit = "".join("[%s]" % c if c in "[*?" else c for c in name)
    if form == "include":
        return "\\" + lit if lit.startswith("!") else lit
    if form == "exclude":
        return "!" + lit
    if form == "power":
        return lit
    raise ValueError("pattern_form", form)


def main_pass_nets(nets, excluded) -> set:
    """The nets of `nets` the main pass's `--nets '*' '!NET' ...` (router_command) matches, as the router expands it: a
    port of KRT net_queries.py expand_net_patterns and net_pattern_matches. The wildcard takes every named net but the
    'unconnected-*' ones; each '!NET' is written by router_net_pattern, so it names NET alone, and also matches the last
    path component of a sheet-qualified net when it names no path; and a '!NET' that is itself the name of a net on the
    board is that net, included, not an exclusion of NET."""
    import fnmatch

    def matches(name, pattern):                  # net_pattern_matches
        if fnmatch.fnmatch(name, pattern):
            return True
        return "/" not in pattern and "/" in name and fnmatch.fnmatch(name.rsplit("/", 1)[-1], pattern)
    known = {n for n in nets if n}
    pool = {n for n in known if not n.lower().startswith("unconnected-")}
    result, dropped = set(pool), set()           # '*' first
    for x in sorted(excluded):
        raw = router_net_pattern(x, "exclude")
        pat = raw[1:]
        if raw in known:                         # a literal active-low net: an include
            hit = {n for n in pool if matches(n, raw) and n not in dropped}
            result |= hit if hit else ({raw} - dropped)
            continue
        hit = {n for n in pool if matches(n, pat)}
        if "*" not in pat and "?" not in pat:
            dropped.add(pat)
        dropped |= hit
        result -= hit
    return result


def router_command(python, script, pcb_in, pcb_out, excluded, layers, summary,
                   iterations: int | None = None, probe: int | None = None, quick: bool = False,
                   nets=None, widths=None, clearances: Path | None = None, connections: Path | None = None,
                   bus_nets=None, neckdown: bool = True, extra_args=()) -> list:
    """The router's command line. The search budget is the router's own default unless the caller sets one. A quick
    route is a measurement, so it runs one routing round (route_one_round.py). The router's own smoothing runs unless
    `[route] smoothing` is off. `nets` routes those alone rather than every net but the excluded; `connections` (a
    file, phase_run.write_connections) routes given pad pairs instead and names no nets; `bus_nets` routes `nets` as
    one stated bus (`--bus-nets`); `widths` ({net: mm}) sets whole nets' widths over the netclass's; `neckdown` False
    turns the router's neck-down of a wide tap off for this call; `extra_args` are a phase's own router flags, after
    `[route] router_args`. `clearances` is the per-net clearance map placemat wrote (net_clearance.py); None leaves the
    router to build its own from the net classes."""
    if connections is not None:
        # KRT refuses --nets and --power-nets beside --connections (exit 2, docs/connections.md), and a `*` call's
        # exclusions would be dropped: either is a caller's mistake
        given = [k for k, v in (("nets", nets), ("widths", widths), ("excluded", excluded)) if v]
        if given:
            raise ValueError("connections_with", given)
        chosen = []
    elif nets is not None:
        chosen = ["--nets"] + [router_net_pattern(n, "include") for n in sorted(nets)]
    else:
        chosen = ["--nets", "*"] + [router_net_pattern(n, "exclude") for n in sorted(excluded)]
    cmd = _launch(python, script) + [str(pcb_in), str(pcb_out)] + chosen + \
          ["--layers"] + list(layers) + ["--escalation", "off"] + \
          ["--keep-input-copper"] + _tuning()      # the script's copper is its intent: no cleanup pass removes it
    if connections is not None:
        cmd += ["--connections", str(connections)]
    if bus_nets:
        cmd += ["--bus-nets"] + [router_net_pattern(n, "include") for n in bus_nets]
    if widths:
        named = sorted(widths)
        cmd += ["--power-nets"] + [router_net_pattern(n, "power") for n in named] + \
               ["--power-nets-widths"] + ["%g" % widths[n] for n in named]
    if not neckdown:
        cmd.append("--no-power-tap-neckdown")
    if not active_settings().route_smoothing:
        cmd.append("--no-smoothing")
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    if probe is not None:
        cmd += ["--max-probe-iterations", str(probe)]
    if clearances is not None:
        cmd += ["--net-clearances", str(clearances)]
    return cmd + list(active_settings().route_router_args) + list(extra_args) + ["--json-out", str(summary)]


REQUIRES = ("route.py:--connections", "route.py:--bus-nets")


_CAPS: dict = {}            # (router folder, its capability script's mtime and size) -> its listing: one a process


def router_capabilities(rpy, router_dir) -> dict | None:
    """The router's capability listing (KRT krt_capabilities.py, JSON: `modules` {name: present}, `flags` {module:
    [flag, ...]}), read once a process per router folder and script version; None when it has none or cannot give it."""
    script = Path(router_dir) / "krt_capabilities.py"
    try:
        st = script.stat()
    except OSError:
        return None
    key = (str(router_dir), st.st_mtime_ns, st.st_size)
    if key not in _CAPS:
        try:
            r = subprocess.run([str(rpy), str(script)], capture_output=True, text=True, cwd=str(router_dir), timeout=60,
                               env=child_env())
            caps = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            caps = None
        _CAPS[key] = caps if isinstance(caps, dict) else None
    return _CAPS[key]


def pair_flags_refused(caps, phases) -> list:
    """Each flag a phase that routes pairs gives in its `router_args` that the pair router (route_diff.py) does not
    accept, as {"phase", "flag"}: its pair call takes the phase's flags and route_diff.py parses its arguments strictly
    (KRT py_router/route_diff.py, parse_args), so such a flag would fail the call mid-route. The accepted set is the
    router's own listing (`flags["route_diff.py"]`), a flag read as its argparse reads it (settings.resolve_flag: the
    flag, or the one flag it abbreviates); with no listing, no flag is accepted."""
    from ..settings import resolve_flag
    accepted = set(((caps or {}).get("flags") or {}).get("route_diff.py") or ())
    def flag(a):            # a negative number ("-1", "-.5") is a value, not a flag
        return a.startswith("--") or (len(a) > 1 and a[0] == "-" and not (a[1].isdigit() or a[1] == "."))
    return [{"phase": p.name, "flag": a.split("=", 1)[0]} for p in phases if p.selector == "pairs"
            for a in p.router_args if flag(a) and resolve_flag(a, accepted) is None]


def router_flags(caps) -> list | None:
    """The router's long flags (route.py's, from its capability listing); None when it gave none."""
    flags = ((caps or {}).get("flags") or {}).get("route.py")
    return list(flags) if flags else None


def owned_args_refused(caps, router_args, phases) -> list:
    """Each router argument that names a flag placemat sets, read against the router's own flag list (router_flags), as
    {"phase" (None for `[route] router_args`), "flag", "owned"}. The settings check these against
    settings.ROUTER_KNOWN when they are read; the router's list tells an abbreviation of one of its other flags from
    an owned one. [] when the router gave no list."""
    from ..route_phase import phase_owned
    from ..settings import router_owned
    known = router_flags(caps)
    if known is None:
        return []
    out = []
    for name, args in [(None, router_args)] + [(p.name, p.router_args) for p in phases]:
        for a in args:
            owned = router_owned(a, known) or (phase_owned(a, known) if name is not None else None)
            if owned:
                out.append({"phase": name, "flag": a.split("=", 1)[0], "owned": owned})
    return out


def router_capable(rpy, router_dir) -> list:
    """The REQUIRES this router lacks, from its capability list (KRT krt_capabilities.py, JSON: `modules` {name:
    present}, `flags` {module: [flag, ...]}): a router older than the fork's phase work is refused by name rather
    than failing in a call. A router with no capability list, or one that cannot give it, lacks every one.
    Divergence from `krt_capabilities.py --require`, which answers in sentences: the JSON is read instead, and each
    token checked as `missing()` there checks it (krt_capabilities.py:481-512)."""
    caps = router_capabilities(rpy, router_dir)
    if caps is None:
        return list(REQUIRES)
    out = []
    for token in REQUIRES:
        mod, _, flag = token.partition(":")
        if not (caps.get("modules") or {}).get(mod) or flag not in ((caps.get("flags") or {}).get(mod) or ()):
            out.append(token)
    return out




def own_pour_breach(breach: str, nets) -> bool:
    """A breach (keepout_breaches' record) that is a pour net's own copper inside its own pour's guard: the guard keeps
    other nets out, not the net it guards."""
    return any(("of %s inside %s %s " % (n, POUR_GUARD, n)) in breach for n in nets)


def routing_clearance(default: float, args, env, known=None) -> float:
    """The clearance the router gives the Default net class, as route.py resolves it: `--clearance` in the router arguments
    when given, else the board's Default class clearance (`default`), capped at the clearance ceiling (net_clearance.ceiling).
    `known`: the router's long flags (its krt_capabilities listing), None: settings.ROUTER_KNOWN."""
    from ..settings import router_flag
    from .net_clearance import ceiling
    given = router_flag(args, "--clearance", known)
    out = default if given is None else given
    cap = ceiling(args, env, known)
    return out if cap is None else min(out, cap)


def clearance_groups(clearances: dict, base: float, nets) -> list:
    """The clearance groups (the class stages): the nets of `nets` whose clearance in `clearances` ({net: mm}, the
    router's map) is above `base` (the Default class's), grouped by clearance, widest first: [(mm, [net, ...])].

    The router spaces every net of one call at the largest clearance among the nets the call routes (KRT
    routing_config.py set_net_clearances, the routing-side floor), and prices each foreign net's copper at the larger of
    that floor and the net's own clearance (obstacle_clearance). A call per clearance routes each net at its own; the
    copper of an earlier stage keeps its own clearance against the later ones."""
    by = {}
    for n in nets:
        c = group_clearance(clearances, n, base)
        if c is not None:
            by.setdefault(c, []).append(n)
    return [(c, sorted(by[c])) for c in sorted(by, reverse=True)]


def group_clearance(clearances: dict, net, base: float) -> float | None:
    """The clearance group `net` routes in (clearance_groups): its clearance in `clearances` rounded to 6 places when
    above `base` by more than 1e-9, else None (the Default group)."""
    c = clearances.get(net)
    return round(float(c), 6) if c is not None and c > base + 1e-9 else None




def _router_lacks(rpy, router_dir_path, phases) -> list:
    """The REQUIRES this route needs that the router lacks: `--bus-nets` only when a phase states a bus. Divergence
    from Task 13's brief, which asks every REQUIRES always: the fork's `--bus-nets` (Task 6) has not landed, and
    asking it of a route with no bus would refuse every route until it does."""
    buses = any(p.selector in ("buses", "interfaces") for p in phases)
    return [m for m in router_capable(rpy, router_dir_path) if buses or not m.endswith(":--bus-nets")]


def pour_flags_lacking(caps, current=False) -> list:
    """The flags a pour net's calls give the router (pour_join.REPAIR_FLAGS on its plane repair, TASK_FLAGS on its
    tasks) and the task fields its tasks carry (TASK_FIELDS, the listing's `task_fields`) that its capability listing
    (router_capabilities) does not have, as {"module", "flag"} or {"module", "field"} records; every one when it has
    no listing. `current`: a pour net a current_paths phase leaves to its pour is joined too, whose drops take a
    width per layer and per pad (pour_join.join_pour), so the plane repair's per-layer `--max-track-width`
    (`flag_forms`, {"module", "flag", "form"}) and its `--pads` `width` (`pad_fields`, {"module", "pad_field"}) are
    asked as well."""
    from .pour_join import PAD_FIELDS, REPAIR_FLAGS, REPAIR_FORMS, TASK_FIELDS, TASK_FLAGS
    caps = caps or {}
    flags = caps.get("flags") or {}
    fields = (caps.get("task_fields") or {}).get("route.py") or ()
    out = [{"module": mod, "flag": f} for mod, want in (("repair_planes.py", REPAIR_FLAGS), ("route.py", TASK_FLAGS))
           for f in want if f not in (flags.get(mod) or ())] + \
        [{"module": "route.py", "field": f} for f in TASK_FIELDS if f not in fields]
    if current:
        forms = (caps.get("flag_forms") or {}).get("repair_planes.py") or {}
        pads = (caps.get("pad_fields") or {}).get("repair_planes.py") or ()
        out += [{"module": "repair_planes.py", "flag": f, "form": form} for f, form in REPAIR_FORMS
                if form not in (forms.get(f) or ())]
        out += [{"module": "repair_planes.py", "pad_field": f} for f in PAD_FIELDS if f not in pads]
    return out


def new_error_count(before_json, after_json, is_real) -> int | None:
    """How many real errors (drc.real_errors) the DRC at `after_json` has beyond the baseline at `before_json`
    (drc.new_errors); None when either DRC wrote no report."""
    from .drc import new_errors, real_errors
    if not (Path(before_json).exists() and Path(after_json).exists()):
        return None
    return len(new_errors(real_errors(json.loads(Path(after_json).read_text()), is_real),
                          real_errors(json.loads(Path(before_json).read_text()), is_real)))


def copper_key(pcbnew, t) -> tuple:
    """A track, arc or via as the route's copper comparisons key it: kind, net, layer and ends (mm, 4 places)."""
    kind = "via" if t.Type() == pcbnew.PCB_VIA_T else "arc" if t.Type() == pcbnew.PCB_ARC_T else "segment"
    ends = tuple(round(pcbnew.ToMM(v), 4) for p in (t.GetStart(), t.GetEnd()) for v in (p.x, p.y))
    return (kind, t.GetNetname(), t.GetLayer(), ends)


def copper_items(path) -> set:
    """copper_key of every track, arc and via on the board at `path`."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = _load_board(str(path))
    return {copper_key(pcbnew, t) for t in board.GetTracks()}


def routed_copper(given_pcb, routed_pcb) -> tuple:
    """(vias, track mm, straight segments) of the copper the route added: the final board's tracks and vias that the
    given board has not, keyed by kind, net, layer and ends. KRT's quality key counts a board's vias and its straight
    segments, and its copper_mm is those segments' lengths end to end (KRT-upstream c98d38eb py_tools/board_score.py:
    1048-1052, py_router/ledger_score.py:76-82): this counts the same over routed copper only, arcs left out as there."""
    new = copper_items(routed_pcb) - copper_items(given_pcb)
    segs = [k for k in new if k[0] == "segment"]
    mm = sum(((k[3][2] - k[3][0]) ** 2 + (k[3][3] - k[3][1]) ** 2) ** 0.5 for k in segs)
    return sum(1 for k in new if k[0] == "via"), round(mm, 3), len(segs)


def _phase_nets(sel) -> set:
    return (set(sel.nets) | set(sel.pour_nets) | {t.net for t in sel.tasks} | {n for b in sel.buses for n in b}
            | {n for q in sel.pairs for n in q})


def without_copper(selections, geometry) -> list:
    """The phases (their Selections, taken on every net of the board) none of whose nets has a track on `geometry`
    (D26: `--only` routes against the board's copper, so the board is what is read), by name, in order."""
    tracked = {c.net for c in geometry.copper if c.kind in ("track", "via")}
    # a phase with nothing to route (a current_paths phase whose connections are all left to pours) is not listed
    return [sel.phase for sel in selections if _phase_nets(sel) and not (_phase_nets(sel) & tracked)]


def ctx_for(ctx, rev, name: str):
    """The phase context with the router's events going to the phase `name`'s pipe."""
    import dataclasses
    return dataclasses.replace(ctx, env=dict(ctx.env, **rev.env(name)))


def copy_source_rules(source_pcb, pcb_out):
    """The source board's .kicad_pro and .kicad_dru beside `pcb_out`; a file the source lacks is removed there, so a
    reused work folder keeps no rules from another board."""
    for ext in (".kicad_pro", ".kicad_dru"):
        source, target = Path(source_pcb).with_suffix(ext), Path(pcb_out).with_suffix(ext)
        if source.is_file():
            shutil.copy(source, target)
        elif target.exists():
            target.unlink()


def finalize_copper(raw_board, pcb_out, given, source_pcb, drc_path):
    """The routed board `pcb_out`: a copy of the router's `raw_board` beside the source board's rules, its guards taken
    off, its zones filled and the router's dangling copper removed (copper already on `given` is kept); the
    clean-up's record and the board's DRC (written to `drc_path`)."""
    from .route_cleanup import remove_dangling_router_copper
    shutil.copy(raw_board, pcb_out)
    copy_source_rules(source_pcb, pcb_out)
    remove_guards(str(pcb_out))
    fill_zones(str(pcb_out))
    cleanup = remove_dangling_router_copper(str(pcb_out), str(given))
    return cleanup, run_drc(pcb_out, drc_path, refill_zones=False)


def summary_widths(routeds, gone, judged) -> list:
    """read_widths of each phase's summaries (`routeds`, each phase's Routed in order) for the nets not in `judged`,
    without the rows of copper a kept attempt took off: phase k's rows of a net when (k, net) is in `gone`
    (rip_reroute.moved_nets), and a phase's rows of an attempt's victims from the summaries before it (Routed.stale)."""
    from .route_widths import read_widths
    out = []
    for k, routed in enumerate(routeds):
        for q, s in enumerate(routed.summaries):
            off = {n for at, nets in routed.stale if q < at for n in nets}
            out += [w for w in read_widths([tuple(s)], judged) if (k, w["net"]) not in gone and w["net"] not in off]
    return out


def recheck_final_phases(report, asked, run_list, width_receipt, pcb_out, drc_path, after, cfg):
    """Ruling S6: every phase's obligations (`asked`, obligations_of, fixed from the input board before routing) judged
    again on the routed board `pcb_out`, after the last phase and the clean-up. Fills each phase record's final_* counts, `report.final_judged`,
    `report.widths_failed` and `report.asked`."""
    from .phase_run import is_clean, judge_obligations, phase_input_drc, phase_neck, widths_failed
    if not (len(report.phases) == len(asked) == len(run_list)):
        raise ValueError("final phase/obligation count mismatch")
    report.final_judged = []
    for i, (rec, obs, phase) in enumerate(zip(report.phases, asked, run_list)):
        rec["width_policy"] = [p for p in width_receipt['policies'] if p['name'] == phase.name]
        rec["final_asked"] = len(obs)
        got = judge_obligations(pcb_out, obs, drc_path, phase_neck(cfg, phase), after.is_real_kind,
                                phase_input_drc(Path(drc_path).parent, i) if drc_path is not None else None)
        report.final_judged.append(got)
        if len(got) != len(obs):
            raise ValueError("final phase judgment/obligation count mismatch")
        clean = [is_clean(j) for j in got]
        rec["final_joined"] = sum(clean)
        # joined at all, whatever its width or DRC
        rec["final_connected"] = sum(j["joined"] for j in got)
        rec["final_width_known_under"] = sum(bool(j["under"]) for j in got if j["joined"])
        rec["final_width_unknown"] = sum(bool(j.get("width_unknown")) for j in got if j["joined"])
        rec["final_closure_clean"] = round(sum(clean) / len(obs), 4) if obs else 1.0
        rec["final_open"] = [dict(o, **({"violated": True} if j["joined"] and j["violated"] else {}),
                                  **({"under": dict(j["under"])} if j["joined"] and j["under"] else {}),
                                  **({"width_unknown": True} if j.get("width_unknown") else {}))
                             for o, j, ok in zip(obs, got, clean) if not ok]
    # joined on the final board narrower than asked along its joining path (S8), or not measured
    report.widths_failed = widths_failed(report.final_judged)
    report.asked = asked


def _route_board(pcb, work, exclude_nets=(), layers=None, router_dir_override: str | None = None,
                 quick: bool = False, iterations: int | None = None, probe: int | None = None,
                 timeout: int | None = None, resume: bool = True, board_info: dict | None = None,
                 on_setup=None, phases=None, upto: str | None = None, only: bool = False, pour_nets=(),
                 capture_path=None) -> RouteReport:
    """Route a copy of `pcb` through the project's routing phases (route_phase.py; `phases` None: the bound settings'),
    in order, each phase on the board the one before it left, its copper locked. `upto` routes the phases up to and
    including the one named; with `only`, that phase alone on the board as given. `exclude_nets` are left out of
    every phase; `pour_nets` are the nets the board serves by a pour: a phase that names one routes it alone with its
    pour handed to the router as a zone (D15), and the ones no phase names are left to their pours, other nets kept
    out of their partial inner-layer pours. `capture_path` is the capture's nets.layout.json (None: beside `pcb`).

    Each phase's asked set (its obligations, phase_run.obligations_of) is fixed from the input board before any phase
    runs, judged after the phase, and judged again on the final board (ruling S6). Each phase's result is kept in
    `work` (route_state.py) under a digest chained from the phases before it: a rerun reuses a phase while its key
    and every earlier one hold (`resume` False starts over); the report's `resumed` names the phases taken.

    Refusals (RouteRefused) come before anything routes: no phases, a `[route]` setting the phases replaced, an
    unknown `upto`, an unreadable capture, a router without the flags the phases need; a phase that cannot be
    obeyed on this board is a route_phase.PhaseError. `on_setup` is kept for the setup findings a route says before
    its first router call (none since the net halos gave way to phases)."""
    from ..settings import active
    from ..route_phase import phases_of
    from ..capture_nets import CaptureError, capture_beside, read_capture
    from ..checks import COPPER_OZ
    from .route_state import RouteState, digest, file_digest
    from .phase_run import (PhaseContext, Routed, judge_phase, obligations_of, open_connections, route_calls)
    from .phase_select import select
    cfg = active()
    phases = phases_of(cfg) if phases is None else tuple(phases)
    if not phases:
        raise RouteRefused("no_phases")

    names = [p.name for p in phases]
    if upto is not None and upto not in names:
        raise RouteRefused("unknown_phase", phase=upto, phases=", ".join(names))
    if only and upto is None:
        raise ValueError("only_needs_upto")
    run_list = [phases[names.index(upto)]] if only else list(phases[:names.index(upto) + 1] if upto else phases)
    if router_dir_override:
        router_dir_path = checked_router(router_dir_override, ROUTER_SETTING)
    else:
        router_dir_path = checked_router(router_dir(cfg), configured_router(cfg)[1])
    timeout = cfg.timeout_route if timeout is None else timeout
    iterations = cfg.route_max_iterations if iterations is None else iterations
    pcb, work = Path(pcb).resolve(), Path(work).resolve()          # the router runs in its own folder: paths it is given are absolute
    rpy = Path(router_dir_path) / ".venv/bin/python"
    route_py = Path(router_dir_path) / "py_router/route.py"
    missing = _router_lacks(rpy, router_dir_path, run_list)
    if missing:
        raise RouteRefused("router_old", router=str(router_dir_path),
                           missing=[dict(zip(("module", "flag"), m.split(":", 1))) for m in missing])
    caps = router_capabilities(rpy, router_dir_path)
    bad = pair_flags_refused(caps, run_list)
    if bad:
        raise RouteRefused("pair_flag", **bad[0])
    owned = owned_args_refused(caps, cfg.route_router_args, run_list)
    if owned:
        raise RouteRefused("router_owned", **owned[0])
    known = router_flags(caps)
    from ..capture_nets import SIDECAR
    try:
        capture = read_capture(capture_path) if capture_path else capture_beside(pcb)
    except CaptureError as e:
        raise RouteRefused("capture", path=str(capture_path or Path(pcb).with_name(SIDECAR)), reason=e.code,
                           detail=dict(e.facts)) from None
    state = RouteState(work, resume)
    from .. import channel, route_progress, route_view
    global _HOOK
    rep = channel.current()
    rev = route_progress.RouteEvents(work, rep.send if rep is not None else None, dict(board_info or {}, pcb=str(pcb), doc=route_progress.BOARD))
    _HOOK = route_progress.enabled()
    pcb_in = work / "in.kicad_pcb"
    shutil.copy(pcb, pcb_in)
    copy_source_rules(pcb, pcb_in)
    lock_copper(str(pcb_in))
    if layers:
        all_layers, layer_types_ = [], {}
    else:
        all_layers = _copper_layers(str(pcb_in))
        from .read import read_layer_types
        layer_types_ = read_layer_types(str(pcb_in))
    layers, plane_dropped = resolved_layers(layers, all_layers, layer_types_)
    from .read import read_board
    geometry = read_board(str(pcb_in))
    board_doc = route_view.board_doc(geometry)
    (work / route_progress.BOARD).write_text(json.dumps(board_doc, separators=(",", ":")))
    if rep is not None:                                  # the board the copper is drawn on, for a route with no placement in front of it
        rep.send({"ev": "route_board", "doc": board_doc})
    excluded, pours = set(exclude_nets), set(pour_nets) & set(geometry.nets)
    # every phase is checked against the board before anything routes (a PhaseError names the first that cannot be
    # obeyed); the pour nets some phase names are routed (D15), the rest left to their pours
    every = set(geometry.nets)
    picked = {}
    for p in phases:
        picked[p.name] = select(p, geometry, capture, open_nets=every, excluded=excluded, pour_nets=pours,
                                route_layers=layers, rise_c=cfg.check_rise_c, copper_oz=COPPER_OZ)
    chosen_pours = set().union(*(set(picked[p.name].pour_nets) for p in run_list))
    # the user's decision of 2026-10-13: a pour net a current_paths phase leaves to its pour (S13) is joined to it at
    # the current that phase asks of it: per pad, the most of the connections it ends (pour_join.join_widths)
    pour_currents = {}
    for p in phases:
        if p.selector == "current_paths":
            for t in picked[p.name].pour_served:
                on = pour_currents.setdefault(t.net, {})
                for end in (tuple(t.start), tuple(t.end)):
                    on[end] = max(on.get(end, 0.0), t.amps)
    lacking = pour_flags_lacking(caps, current=bool(chosen_pours & set(pour_currents))) if chosen_pours else []
    if lacking:                     # a phase names a pour net: its calls need the router's plane repair flags
        raise RouteRefused("router_old", router=str(router_dir_path), missing=lacking)
    counted = excluded | (pours - chosen_pours)          # what the closure leaves out
    before = run_drc(pcb_in, work / "drc_before.json")
    # ruling S6: each phase's asked set, fixed from the input board before anything routes (and before the guards
    # below edit pcb_in); the rest phase never takes a pour net (D15)
    input_open = open_connections(pcb_in, work / "drc_before.json")
    asked = obligations_of([picked[p.name] for p in run_list], input_open, excluded | pours)
    open0 = {n: v for n, v in before.open_nets.items() if n not in counted}
    valid = not before.real
    guard_footprint_copper(str(pcb_in))          # after the placement's own DRC: the guards are the router's
    # every pour net's partial inner-layer pours kept clear of other nets, on the route's layers: a pour net a phase
    # routes takes its own guard off for its own call only (pour_join.join_pour)
    kept_pours = guard_partial_pours(str(pcb_in), pours, layers, cfg.route_plane_share)
    from . import net_clearance
    env = child_env(headless=False)
    env.pop("KICAD_ROUTE_TRACE", None)
    env.pop("KICAD_SMOOTH_ROUTE", None)     # it overrides the router's smoothing flag: [route] smoothing decides
    env["KRT_DIR"] = str(router_dir_path)
    from . import width_policy
    width_receipt = width_policy.resolve(rpy, router_dir_path, pcb, run_list, [picked[p.name] for p in run_list], cfg,
                                         work / "width_policy.log", env, timeout=timeout)
    (work / "width_policy.json").write_text(json.dumps(width_receipt, sort_keys=True) + "\n")
    failure = width_receipt.get("failure")
    if failure is not None:                 # every join would be width-unknown: the route says why instead
        if failure["code"] == "unavailable":
            raise RouteRefused("width_policy_unavailable", router=str(router_dir_path), **failure["facts"])
        raise RouteRefused("width_policy_failed", router=str(router_dir_path), failure=failure["code"],
                           **failure["facts"])
    asked = width_policy.apply(asked, [picked[p.name] for p in run_list], run_list, width_receipt)
    # what rip and reroute needs of the phases before an attempt, read after the guards
    from . import rip_reroute
    hist = rip_reroute.History(tuple(run_list), tuple(picked[p.name] for p in run_list), tuple(asked), width_receipt,
                               frozenset(copper_items(pcb_in)), tuple(input_open))
    stated = {n: c for n, c in (capture.clearances() if capture else {}).items() if n in geometry.nets}
    trapped = net_clearance.trapped(geometry, stated, judged={n for n in open0 if open0[n]}) if stated else []
    clearance_findings = net_clearance.findings(trapped)
    from ..findings import Finding, FindingCause
    from .phase_select import duplicate_references
    shared = duplicate_references(geometry, set().union(*(_phase_nets(picked[p.name]) for p in run_list)))
    clearance_findings += [Finding(FindingCause.SETUP_DUPLICATE_REFERENCE, f) for f in shared]
    if clearance_findings and on_setup is not None:
        on_setup(clearance_findings)
    class_clearances = net_clearance.class_clearances(rpy, router_dir_path, pcb_in, geometry.nets, env)
    ceiling = net_clearance.ceiling(cfg.route_router_args, env, known)
    clearance_map = net_clearance.merged(class_clearances, stated, ceiling)
    clearances_file = work / net_clearance.MAP_NAME if stated else None
    if clearances_file:
        clearances_file.write_text(json.dumps(clearance_map, sort_keys=True) + "\n")
    base_clearance = routing_clearance(geometry.default_clearance, cfg.route_router_args, env, known)

    # What every phase's result depends on: the board and its rules as given, the capture, what is left out or
    # poured, how it is routed and by which router. Each phase's digest chains from the one before it.
    from .. import __version__
    settings_part = {k: v for k, v in sorted(json.loads(cfg.json()).items())
                     if k.startswith("route_") and k not in ("route_router_dir", "route_phase")}
    base = digest("phase-judgement-v10", file_digest(pcb), file_digest(pcb.with_suffix(".kicad_pro")), file_digest(pcb.with_suffix(".kicad_dru")),
                  capture.digest if capture else "", sorted(excluded), sorted(pours), layers, quick, iterations, probe,
                  router_version(router_dir_path), __version__, settings_part, cfg.check_rise_c)     # rise_c: current widths
    state.set_order(["only:" + run_list[0].name] if only else [p.name for p in run_list])
    script = str(ONE_ROUND) if quick else str(route_py)
    ctx = PhaseContext(rpy, script, router_dir_path, work, layers, iterations, probe, quick, timeout, env, cfg,
                       geometry, clearance_map, base_clearance, clearances_file, excluded, pours, rev,
                       class_clearances, stated, pour_currents, history=hist)
    pcb_out = work / "routed.kicad_pcb"
    raw_out = work / "router_out.kicad_pcb"      # the last phase's board: post-processing is made on a copy
    board, prev, records, routeds, spent, resumed = pcb_in, base, [], [], 0.0, []
    open_now = dict(before.open_nets)
    for i, phase in enumerate(run_list):
        phase_identity = (phase.key(), width_policy.phase_key(width_receipt, phase.name))
        currents = {n: sorted([list(e), a] for e, a in pour_currents[n].items())
                    for n in sorted(picked[phase.name].pour_nets) if n in pour_currents}
        if currents:                    # its pour joins are laid at these currents' widths (pour_join.join_widths)
            phase_identity += (currents,)
        key = digest(base, "only", *phase_identity) if only else digest(prev, *phase_identity)
        label = state.order[i]
        saved = state.result(label, key)
        if saved is not None and (work / saved["routed"]["board"]).exists():
            routed = Routed.of(saved["routed"], work)
            if "record" not in saved:           # routed, not judged: a failure judging it keeps the routing (keep-work)
                sel = select(phase, geometry, capture, open_nets={n for n, v in open_now.items() if v},
                             excluded=excluded, pour_nets=pours, route_layers=layers, rise_c=cfg.check_rise_c,
                             copper_oz=COPPER_OZ)
                record, judged_open = judge_phase(ctx, i, phase, sel, routed, asked[i])
                saved = dict(saved, record=record, open_nets=judged_open)
                state.record(label, key, saved)
            resumed.append(phase.name)
            rev.resumed(phase.name, saved["record"]["seconds"])
            board, open_now = routed.board, dict(saved["open_nets"])
            records.append(dict(saved["record"], reused=True))
            hist.finish(i, board, saved["record"], reused=True)
            routeds.append(routed)
            spent += saved["record"]["seconds"]
            prev = key
            continue
        state.drop_from(label)
        sel = select(phase, geometry, capture, open_nets={n for n, v in open_now.items() if v}, excluded=excluded,
                     pour_nets=pours, route_layers=layers, rise_c=cfg.check_rise_c, copper_oz=COPPER_OZ)
        rev.begin(phase.name, nets=len(_phase_nets(sel)), phase=i + 1, of=len(run_list))
        done = False
        try:
            outcome = route_calls(ctx_for(ctx, rev, phase.name), i, phase, sel, board)
            done = True
        finally:
            rev.end(phase.name, complete=done)
        state.record(label, key, {"routed": outcome.routed})
        routed = Routed.of(outcome.routed, work)
        record, open_now = judge_phase(ctx, i, phase, sel, routed, asked[i])
        state.record(label, key, {"routed": outcome.routed, "record": record, "open_nets": open_now})
        board = routed.board
        records.append(record)
        hist.finish(i, board, record, reused=False)
        routeds.append(routed)
        spent += record["seconds"]
        prev = key
    seconds = round(spent, 1)
    shutil.copy(board, raw_out)
    for ext in (".kicad_pro", ".kicad_dru"):
        if (work / ("in" + ext)).exists():
            shutil.copy(work / ("in" + ext), work / ("router_out" + ext))
    cleanup, after = finalize_copper(board, pcb_out, pcb_in, work / "in.kicad_pcb", work / "drc_after.json")
    open1 = {n: v for n, v in after.open_nets.items() if n not in counted}
    # ruling S15, at the route level: a net counts as shorted only by an error of a real kind the unrouted board did not have (S24)
    from .drc import new_error_kinds, real_errors
    violated = new_error_kinds(real_errors(json.loads((work / "drc_after.json").read_text()), after.is_real_kind),
                               real_errors(json.loads((work / "drc_before.json").read_text()), after.is_real_kind))
    sc = score(open0, open1, {n for n in violated if n not in counted})
    breaches = [b for b in router_breaches(pcb_in, pcb_out) if not own_pour_breach(b, chosen_pours)]
    log = work / "route.json"
    for i in reversed(range(len(run_list))):
        logs = sorted(l for l in work.glob("p%d_*.log" % i) if "_rip" not in l.name)    # an attempt's logs: not the call's
        if logs:
            log = logs[-1]
            break
    report = RouteReport(valid, round(sc.closure, 4), round(sc.closure_clean, 4), sum(open0.values()), sum(open1.values()),
                         dict(sorted(open1.items())), sc.shorted, sorted(counted), layers, seconds,
                         router_version(router_dir_path), after.by_type, pcb_out, log, work,
                         "" if valid else "placement DRC not clean before routing: %s" % before.real, quick,
                         breaches, plane_dropped, list(kept_pours), resumed)
    report.net_clearances = stated
    report.net_clearance_trapped = trapped
    report.net_clearance_facts = [dict(f.facts) for f in clearance_findings
                                  if f.cause is FindingCause.SETUP_NET_CLEARANCE]
    report.duplicate_references = shared
    report.violations = {n: violated[n] for n in sc.shorted}   # the new errors that shorted it (S15)
    from .rip_reroute import moved_nets
    gone = moved_nets(records)
    report.widths = [w for j, rec in enumerate(records) for w in rec.get("widths", [])
                     if (j, w.get("net")) not in gone]
    report.widths += summary_widths(routeds, gone, {w["net"] for w in report.widths})
    report.dangling_removed = cleanup.record()
    report.phases = records
    for p in run_list:
        for n in picked[p.name].pour_nets:
            report.pour_routed_by.setdefault(n, p.name)
    recheck_final_phases(report, asked, run_list, width_receipt, pcb_out,
                         work / "drc_after.json", after, cfg)
    from .phase_run import judged_widths, one_line_per_connection, path_tracks, phase_neck
    judged = judged_widths(run_list, asked, report.final_judged)
    paths = path_tracks(pcb_out, judged, {p.name: phase_neck(cfg, p) for p in run_list})
    report.widths = one_line_per_connection(report.widths, judged, paths) + judged
    report.drc_new = new_error_count(work / "drc_before.json", work / "drc_after.json", after.is_real)
    report.vias, report.track_mm, report.segments = routed_copper(pcb, pcb_out)
    if only:
        report.phases_without_copper = without_copper([picked[p.name] for p in phases[:names.index(upto)]],
                                                      geometry)
    if rep is not None:
        for r in report.widths:
            rep.send(dict(r, ev="route_width"))
    if route_progress.enabled():
        report.record = str(route_progress.write_record(work, rev.info, rev.stages, report.as_dict(), complete=True))
    _HOOK = False
    (work / "route.json").write_text(json.dumps(report.as_dict(), indent=2) + "\n")
    return report


def route_board(*args, **kwargs) -> RouteReport:
    """Route a copy of a board (`_route_board`), reporting progress to the command's socket and writing the route record."""
    global _HOOK
    try:
        return _route_board(*args, **kwargs)
    finally:
        _HOOK = False


def router_breaches(pcb_in, pcb_out) -> list:
    """What the router laid inside a region that forbids it, judged against
    the rule areas on the board it was given. Only the router's copper: the
    script's own is judged by the layout, which knows a keepout's allow=."""
    from ..board_geometry import added_copper, keepout_breaches
    from .read import read_board
    given, routed = read_board(pcb_in), read_board(pcb_out)
    return keepout_breaches(given.rule_areas, added_copper(given.copper, routed.copper))


def _phase_end(end: dict) -> str:
    """An open connection's end as a line names it: REF.PAD, or the place (mm) of an end that is no pad."""
    return "%s.%s" % (end["ref"], end["pad"]) if end.get("ref") else "%.2f,%.2f" % tuple(end["at"])


def _router_said(o: dict) -> str:
    """What the router reported of an open connection, from its record: its outcome, KRT's diagnosis unless unknown,
    and what its search met (a part by ref, other copper by net)."""
    out = " " + o["outcome"] if o.get("outcome") else ""
    ev = o.get("evidence") or {}
    if ev.get("diagnosis") not in (None, "unknown"):
        out += " " + ev["diagnosis"]
    met = []
    for b in ev.get("blocked_by") or ():
        name = b["ref"] if b.get("ref") else "%s copper" % b["net"]
        if name not in met:
            met.append(name)
    return out + (" against " + "/".join(met) if met else "")


def _pour_join_said(j) -> str:
    """One pour_joins record (pour_join.join_pour) as the phase line says it."""
    out = "%s: %d pad%s on the pour, %d of %d apart tapped (%d via%s in a pad, %d beside)" % (
        j["net"], j["joined_before"], "" if j["joined_before"] == 1 else "s", j["tapped"], j["apart_before"],
        j["vias"]["in_pad"], "" if j["vias"]["in_pad"] == 1 else "s", j["vias"]["beside"])
    if j["vias"].get("joins"):
        out += ", %d via%s in joins of the pour's pieces" % (j["vias"]["joins"], "" if j["vias"]["joins"] == 1 else "s")
    if j["groups_left"]:
        done = sum(1 for t in j["tasks"] if t.get("status") == "routed")
        out += ", %d of %d groups left joined by a track" % (done, j["groups_left"])
    return out


_RESTORED = {"blocked_not_clean": "not joined clean", "net_open_rose": "%s left with more open items",
             "off_layer": "copper off its phase's layers",
             "router_failed": "the router failed", "router_refused": "the router refused a task",
             "router_timeout": "the router timed out"}
_NOT_MOVED = {"too_many_victims": "too many nets named", "limit": "attempt limit", "tried": "same nets restored before",
              "stopped": "an earlier attempt's router call failed", "victim_width_unknown": "a moved connection's width unknown",
              "victim_end_not_pad": "a moved connection's end is no pad", "blocked_width_unknown": "width unknown",
              "blocked_end_not_pad": "an end is no pad", "joined_since": "joined by an earlier attempt"}


def _blocked_said(a: dict) -> str:
    return ", ".join("%s %s-%s" % (b["net"], _phase_end(b["from"]), _phase_end(b["to"])) for b in a["blocked"])


def _restored_why(a: dict) -> str:
    """Why a rip attempt was restored, from its record."""
    reason = a["reason"]
    if reason == "obligation_worse" and a.get("worse"):
        w = a["worse"][0]
        return "%s %s-%s %s" % (w["net"], _phase_end(w["from"]), _phase_end(w["to"]),
                                "would no longer be clean" if w["after"] == "joined" else "would be open")
    if reason == "drc_new":
        n = a.get("drc_new", 0)
        return "%d new DRC error%s" % (n, "" if n == 1 else "s")
    if reason == "net_open_rose":
        return _RESTORED[reason] % next(iter(a.get("open_rose") or {"a net": 0}))
    return _RESTORED.get(reason, reason.replace("_", " "))


def _rip_said(p: dict) -> str:
    """A phase's rip attempts and skipped nets as its line says them."""
    out = ""
    rip = p.get("rip") or {}
    for a in rip.get("attempts") or ():
        victims = ", ".join(a["victims"])
        if a["kept"]:
            owners = list(dict.fromkeys(r["phase"] for r in a["rerouted"]))
            n = len(a["rerouted"])
            out += "; moved earlier copper: %s joined after moving %s (%s, %d connection%s)" % (
                _blocked_said(a), victims, ", ".join(owners), n, "" if n == 1 else "s")
        else:
            out += "; restored: %s after moving %s: %s" % (_blocked_said(a), victims, _restored_why(a))
    for s in rip.get("skipped") or ():
        if s["reason"] != "no_victim":
            out += "; not moved for %s: %s" % (s["net"], _NOT_MOVED.get(s["reason"], s["reason"].replace("_", " ")))
    return out


def phase_lines(phases: list, without_copper=(), pour_routed_by=None) -> list:
    """Each phase's line. `pour_routed_by`: {pour net: the first phase that routes it in a pour call}
    (RouteReport.pour_routed_by); a net a phase left to its pour that a later phase routes says so."""
    from .rip_reroute import moves_of
    out = []
    names = [p["name"] for p in phases]
    ripped = [p if "rip" in p else dict(p, rip={"attempts": [], "skipped": []}) for p in phases]   # records of older runs
    for i, p in enumerate(phases):
        line = "phase %s (%s): %d of %d joined clean (%.1f%%), %.0f s%s" % (
            p["name"], p["selector"], p["joined"], p["asked"], 100 * p["closure_clean"], p["seconds"],
            ", reused" if p.get("reused") else "")
        final = p.get("final_closure_clean")
        if final is not None and final != p["closure_clean"]:
            line += ", final %.1f%%" % (100 * final)
        opened, said, unreached = [], set(), []
        for o in p.get("final_open", p.get("open")) or ():
            if o.get("pour_served") and not o.get("violated") and not o.get("under") and not o.get("width_unknown"):
                unreached.append(o)
            elif o.get("violated"):
                if o["net"] not in said:
                    said.add(o["net"])
                    opened.append("%s has a DRC error" % o["net"])
            elif o.get("under"):
                opened.append("%s %s-%s under %s" % (o["net"], _phase_end(o["from"]), _phase_end(o["to"]), " ".join(
                    "%s %g" % (layer, mm) for layer, mm in sorted(o["under"].items()))))
            elif o.get("width_unknown"):
                opened.append("%s %s-%s width not measured" % (o["net"], _phase_end(o["from"]), _phase_end(o["to"])))
            else:
                opened.append("%s %s-%s%s" % (o["net"], _phase_end(o["from"]), _phase_end(o["to"]), _router_said(o)))
        if opened:
            line += "; open: " + ", ".join(opened)
        served = {}
        for t in p.get("pour_served") or ():
            served[t["net"]] = served.get(t["net"], 0) + 1
        for o in p.get("final_open", p.get("open")) or ():
            if o.get("pour_served") and not o.get("violated"):      # not reached, or joined under its width
                served[o["net"]] = served.get(o["net"], 0) - 1
        later = {n: by for n, by in (pour_routed_by or {}).items() if by in names[i + 1:]}
        left = ["%s %d connection%s%s" % (n, k, "" if k == 1 else "s", " routed by phase %s" % later[n] if n in later
                                         else "") for n, k in served.items() if k > 0]
        if left:
            line += "; left to their pours: " + ", ".join(left)
        if unreached:
            line += "; not reached by the pour: " + ", ".join(
                "%s %s-%s" % (o["net"], _phase_end(o["from"]), _phase_end(o["to"])) for o in unreached)
        for j in p.get("pour_joins") or ():
            line += "; " + _pour_join_said(j)
            if j.get("rejoin"):
                line += "; %s split by a later call, joined again: %s" % (j["net"], _pour_join_said(j["rejoin"]))
        line += _rip_said(p)
        by_mover = {}
        for j, r in moves_of(ripped, i):
            nets = by_mover.setdefault(names[j], [])
            if r["net"] not in nets:
                nets.append(r["net"])
        for mover, nets in by_mover.items():
            line += "; moved by phase %s: %s" % (mover, ", ".join(nets))
        out.append(line)
    if without_copper:
        out.append("earlier phases with no copper on this board: " + ", ".join(without_copper))
    return out
