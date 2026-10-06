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

from .. import route_progress
from ..childenv import child_env
from .drc import REAL_KINDS, run_drc

BUILTIN_ROUTER = os.path.expanduser("~/work/KRT-upstream")
ROUTER_DEFAULT = os.environ.get("KRT_DIR", BUILTIN_ROUTER)   # kept: tests and callers import this name



def active_settings():
    from ..settings import active
    return active()

def router_dir(cfg=None) -> str:
    """Where the router lives: the built-in default, then $KRT_DIR (a machine
    fact), then placemat.toml (a project fact), which wins."""
    from ..settings import active
    cfg = active() if cfg is None else cfg
    return cfg.route_router_dir or os.environ.get("KRT_DIR") or BUILTIN_ROUTER
ONE_ROUND = Path(__file__).with_name("route_one_round.py")
HOOKED = Path(__file__).with_name("route_hooked.py")     # runs a router entry script with the progress hooks (route_events.py)
_HOOK = False                                             # set by route_board while it routes with progress events


def _launch(python, script) -> list:
    """The start of a router command: the interpreter and the script, behind the hooking wrapper when this route reports progress (the quick
    route's own wrapper is hooked already)."""
    if _HOOK and Path(script).name != ONE_ROUND.name:
        return [str(python), str(HOOKED), str(script)]
    return [str(python), str(script)]


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
    # Partial inner-layer pours of nets left out, kept clear of other nets'
    # tracks in the router's input copy: "NET on LAYER" each.
    pours_kept: list = field(default_factory=list)
    # The island nets: {net: (open items before, after)}, their pads and
    # pieces the pours leave apart, routed first and alone.
    islands: dict = field(default_factory=dict)
    # Island nets named that the board does not have: not routed.
    islands_missing: list = field(default_factory=list)
    # The stages taken from an earlier route of the same inputs rather than run (route_state.py).
    resumed: list = field(default_factory=list)
    # The route record (route_progress.py): the events of every stage in laid order, what the studio replays the route from; "" when
    # events are off.
    record: str = ""
    # Copper the router laid under the width it was asked, from its per-stage summaries (route_widths.py): a record per net and stage.
    widths: list = field(default_factory=list)
    # `[route] pair_layers` as applied, {"P/N": [layer, ...]}, and the entries refused (resolve_pair_layers' records).
    pair_layers: dict = field(default_factory=dict)
    pair_layers_refused: list = field(default_factory=list)
    # `[route] net_halos` as applied, {net: mm}; the entries naming no net on the board; the pads a halo traps
    # (net_halos.trapped's records); and the facts of every `setup.net_halo` finding, in the order they were said.
    net_halos: dict = field(default_factory=dict)
    net_halos_missing: list = field(default_factory=list)
    net_halo_trapped: list = field(default_factory=list)
    net_halo_facts: list = field(default_factory=list)
    # The router's dangling copper taken off the routed copy (route_cleanup.py, KiCad's TRACKS_CLEANER): Cleanup.record(),
    # {"tracks": {net: n}, "vias": {net: n}, "merged": {net: n}, "unconnected": [before, after],
    # "kept_unrouted": [nets left unconnected whose dangling router copper was kept],
    # "refused_nets": [nets whose pads the dangling router copper alone joins, which keep it],
    # "vias_merged": {net: n} (router vias merged into a same-net hole within hole-to-hole),
    # "vias_kept_close": [{"net", "at_mm", "near_mm", "distance_mm", "reason"}] (such vias left in place)}.
    dangling_removed: dict = field(default_factory=dict)
    # The class stages (`class_stages`), widest clearance first: each {"clearance_mm": mm, "nets": {net: [open items before,
    # after]}}. Their nets route in their own router call before the main pass, which does not route them again.
    class_stages: list = field(default_factory=list)
    # The nets `shorted` lists, with the kinds of the real DRC violations each is in: {net: [kind, ...]}. A net named there need not be
    # shorted; a hole_to_hole between two of its own vias puts it there too.
    violations: dict = field(default_factory=dict)
    # The island nets given their own layers (`NET@LAYER,...`), {net: [layer, ...]}: their pass laid tracks on those only.
    island_layers: dict = field(default_factory=dict)

    def has_findings(self) -> bool:
        return bool(self.widths or self.pair_layers_refused or self.net_halo_facts)

    def findings(self, stated: dict | None = None) -> list:
        """The findings of the widths (route_widths.findings_of; `stated` is {net: amps} the design states), then a
        `setup.pair_layers` finding for each `[route] pair_layers` entry refused, then the `setup.net_halo` findings
        (`setup_findings`)."""
        from ..findings import Finding, FindingCause as C
        from .route_widths import findings_of
        return (findings_of(self.widths, stated) + [Finding(C.SETUP_PAIR_LAYERS, dict(r)) for r in self.pair_layers_refused]
                + self.setup_findings())

    def setup_findings(self) -> list:
        """The `setup.net_halo` findings: the ones `route_board` hands to `on_setup` before it routes."""
        from ..findings import Finding, FindingCause as C
        return [Finding(C.SETUP_NET_HALO, dict(f)) for f in self.net_halo_facts]

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
        p = self.pairs or {}
        if any(p.get(k) for k in ("coupled", "partial", "failed", "single_ended")):
            head += "  pairs: %d coupled, %d partial, %d failed, %d single-ended" % tuple(
                len(p.get(k) or []) for k in ("coupled", "partial", "failed", "single_ended"))
        if self.plane_layers:
            head += "  " + plane_note(self.plane_layers)
        if self.pours_kept:
            head += "  other nets kept out of %d pour(s)" % len(self.pours_kept)
        if self.islands:
            head += "  islands: " + ", ".join("%s %d -> %d apart" % (n, a, b) for n, (a, b) in self.islands.items())
        if self.islands_missing:
            head += "  island nets not on the board: " + ", ".join(self.islands_missing)
        if self.island_layers:
            head += "  islands on their own layers: " + "; ".join("%s on %s" % (n, ", ".join(v)) for n, v in sorted(self.island_layers.items()))
        if self.class_stages:
            head += "  class stages: " + "; ".join("%g mm %s" % (st["clearance_mm"], ", ".join(
                "%s %d -> %d" % (n, a, b) for n, (a, b) in sorted(st["nets"].items()))) for st in self.class_stages)
        if self.net_halos:
            head += "  halos: " + ", ".join("%s %g mm" % kv for kv in sorted(self.net_halos.items()))
        if self.pair_layers:
            head += "  pairs on their own layers: " + "; ".join("%s %s" % (k, ", ".join(v)) for k, v in sorted(self.pair_layers.items()))
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
                "pairs": self.pairs, "plane_layers": self.plane_layers,
                "pours_kept": list(self.pours_kept),
                "islands": {n: list(v) for n, v in self.islands.items()}, "islands_missing": list(self.islands_missing),
                "island_layers": {n: list(v) for n, v in self.island_layers.items()},
                "class_stages": [dict(st, nets={n: list(v) for n, v in st["nets"].items()}) for st in self.class_stages],
                "resumed": list(self.resumed), "record": self.record, "widths": list(self.widths),
                "pair_layers": dict(self.pair_layers), "pair_layers_refused": list(self.pair_layers_refused),
                "net_halos": dict(self.net_halos), "net_halos_missing": list(self.net_halos_missing),
                "net_halo_trapped": list(self.net_halo_trapped), "dangling_removed": dict(self.dangling_removed)}


def plane_nets_of(pcb) -> set:
    """The nets a board serves by a pour: each with a copper zone, or a
    filled copper polygon, of the board's own on it. What run --route leaves
    out as the plan's plane nets, read off the written board: a stamped
    cell's local zone or pour (in its group) does not count, its net still
    runs to parts elsewhere."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb)) if Path(pcb).stat().st_size else None
    if board is None:
        return set()
    grouped = {it.m_Uuid.AsString() for g in board.Groups() for it in g.GetItems()}
    nets = {z.GetNetname() for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname()
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
        board = pcbnew.LoadBoard(pcb_path)
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
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, False)
    board_area = outline.Area()
    routed = set(layers or ())
    out = []
    for z in list(board.Zones()):
        if z.GetIsRuleArea() or z.GetNetname() not in nets:
            continue
        if board_area and z.Outline().Area() >= share * board_area:
            continue
        for layer in z.GetLayerSet().CuStack():
            name = board.GetLayerName(layer)
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
        board = pcbnew.LoadBoard(pcb_path)
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


def _violations_by_net(drc: dict) -> dict:
    """{net: sorted kinds} of the real DRC violations the net's items are in."""
    import re
    out = {}
    for v in drc.get("violations", []):
        if v.get("type") not in REAL_KINDS:
            continue
        for item in v.get("items", []):
            m = re.search(r"\[([^\]]+)\]", item.get("description", ""))
            if m:
                out.setdefault(m.group(1), set()).add(v["type"])
    return {n: sorted(k) for n, k in out.items()}


def _nets_in_violations(drc: dict) -> set:
    return set(_violations_by_net(drc))


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
                 iterations: int | None = None, probe: int | None = None, clearances: Path | None = None) -> list:
    """The pair router's command line. Width and gap are the net class's
    unless set (route_diff.py reads them from the board's project).
    `clearances`: the per-net clearance map placemat wrote (net_halos.py);
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
    return cmd + list(active_settings().route_pair_router_args)


def resolve_pair_layers(table: dict, pairs, classes: dict, board_layers) -> tuple:
    """`[route] pair_layers` against the board: ({(p, n): [layer, ...]}, [refused entry, ...]). A key is a pair's two
    nets "P/N", in either order, or the name of a net class (`classes`: {net: class name}) holding both nets of a pair; a
    pair's own nets win over its class. The layers are put in the board's stack order (`board_layers`). An entry whose key
    names no pair of `pairs`, or that names a layer the board does not have, is not used: a record of it is returned
    (key, variant "no_pair" or "layer_missing", layers, missing, board_layers), the facts of its `setup.pair_layers`
    finding."""
    stack = list(board_layers)
    by_nets = {}
    by_class: dict = {}
    for p, n in pairs:
        by_nets["%s/%s" % (p, n)] = by_nets["%s/%s" % (n, p)] = (p, n)
        if classes.get(p) is not None and classes.get(p) == classes.get(n):
            by_class.setdefault(classes[p], []).append((p, n))
    own, of_class, refused = {}, {}, []
    for key in sorted(table):
        layers = list(table[key])
        named = [by_nets[key]] if key in by_nets else by_class.get(key, [])
        missing = [l for l in dict.fromkeys(layers) if l not in stack]
        if not named or missing:
            refused.append({"key": key, "variant": "layer_missing" if named else "no_pair", "layers": layers,
                            "missing": missing if named else [], "board_layers": stack})
            continue
        into = own if key in by_nets else of_class
        for pair in named:
            into[pair] = [l for l in stack if l in layers]
    return {**of_class, **own}, refused


def pair_layer_groups(pairs, layers, pair_layers: dict) -> list:
    """The pair router's calls: [(layers, [(p, n), ...]), ...], one per distinct layer list. A pair `pair_layers`
    ({(p, n): [layer, ...]}) names is routed on its own list, every other pair on `layers`; the named lists go first,
    as they constrain their pairs most, and each call's copper is fixed for the calls after it."""
    default = list(layers)
    groups: dict = {}
    for pair in pairs:
        groups.setdefault(tuple(pair_layers.get(pair, default)), []).append(pair)
    out = [(list(k), groups[k]) for k in sorted(groups) if list(k) != default]
    if tuple(default) in groups:
        out.append((default, groups[tuple(default)]))
    return out


def _tuning() -> list:
    """The router's turn cost, on every pass. Diverges from the router's own
    default (1000, where a 45-degree kink costs 0.05 mm of path and routes
    stair-step): see Settings.route_turn_cost."""
    return ["--turn-cost", str(int(active_settings().route_turn_cost))]


def _net_names(pcb) -> set:
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb))
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
        board = pcbnew.LoadBoard(pcb_path)
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
                timeout, env, events=None, pair_layers: dict | None = None, halos: dict | None = None) -> tuple:
    """Route the differential pairs `pairs` ([(p_net, n_net), ...], from
    pairs.board_pair_list): returns (the board to route the rest on,
    Pairs). No pairs comes back as it went in.

    A pair `pair_layers` names ({(p, n): [layer, ...]}, resolve_pair_layers)
    is routed on its own layers, the rest on `layers`: the pair router takes
    one layer list per call, so it runs once per distinct list
    (pair_layer_groups), each call on the board the one before it wrote,
    with that call's copper locked. The first call logs to pairs.log, the
    next to pairs_1.log and on.

    The router pairs nets by their suffix alone, so every pair is routed in
    a copy where its nets are renamed to a suffix pair (pairs.pair_aliases),
    whatever they were called, and renamed back in the routed board before
    anything reads it. A net the board does not have is a ValueError,
    before the router runs.

    With `halos` ({net: mm}, the ones on the board) every call is given the
    clearance map net_halos.py writes, built on the renamed copy under its
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
    router_in = work / "pairs_in.kicad_pcb"
    shutil.copy(pcb_in, router_in)
    _copy_project(pcb_in, router_in)
    rename_nets(str(router_in), renames)
    clearances = None
    if halos:
        from . import net_halos
        clearances = net_halos.write_map(rpy, router_dir_path, router_in, sorted(renames.get(n, n) for n in names),
                                         {renames.get(n, n): h for n, h in halos.items()}, work / net_halos.PAIR_MAP_NAME,
                                         net_halos.ceiling(active_settings().route_pair_router_args, env), env)
    back = {new: old for old, new in renames.items()}
    back.update({base: "%s/%s" % (p, n) for base, p, n in aliases})
    if events is not None:
        events.names = back                      # the router routes under the aliases: its events name the board's nets
    pcb_out = work / "pairs.kicad_pcb"
    groups = pair_layer_groups(pairs, layers, pair_layers or {})
    alias_of = {(p, n): base for base, p, n in aliases}
    board, found = router_in, None
    for i, (group_layers, group) in enumerate(groups):
        out = pcb_out if i == len(groups) - 1 else work / ("pairs_%d.kicad_pcb" % i)
        cmd = pair_command(rpy, script, board, out, tuple(alias_of[pair] for pair in group), group_layers,
                           cfg.route_diff_pair_gap, cfg.route_diff_pair_width, iterations, probe, clearances)
        log = work / ("pairs.log" if i == 0 else "pairs_%d.log" % i)
        with open(log, "w") as f:
            f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
            f.flush()
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir_path), env=env,
                                timeout=timeout, pass_fds=route_progress.pass_fds()).returncode
        text = log.read_text(errors="replace")
        if rc != 0 or not out.exists():
            if "matched no differential pair" in text or "No differential pairs" in text:
                continue
            tail = "\n".join(text.splitlines()[-8:])
            raise RuntimeError("the pair router exited %d without a routed board; log %s\n%s" % (rc, log, tail))
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
            shutil.copy(work / ("in" + ext), work / ("pairs" + ext))
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


from ..settings import parse_island_layers, parse_islands  # noqa: E402  (the setting's own reading, checked when it loads)


def islands_on_board(pcb, islands: dict) -> tuple:
    """The island nets the board has, and the names it does not (a stale or
    mistyped setting): ({net: width}, [missing names])."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb))
    names = {str(n) for n in board.GetNetsByName().keys()}
    return {n: w for n, w in islands.items() if n in names}, sorted(n for n in islands if n not in names)


def island_layers_on_board(island_layers: dict, board_layers) -> dict:
    """The island nets' own layers ({net: (layer, ...)}) as lists, each checked against the board's copper layers: a
    layer the board does not have is refused (ValueError)."""
    out = {}
    for net, lays in sorted(island_layers.items()):
        missing = [l for l in lays if l not in board_layers]
        if missing:
            raise ValueError("[route] islands: %s@%s: the board has no %s (its copper layers: %s)" % (
                net, ",".join(lays), ", ".join(missing), ", ".join(board_layers)))
        out[net] = list(lays)
    return out


def drop_pour_guards(pcb_path: str, nets) -> None:
    """Delete the pour guards `guard_partial_pours` added for `nets`."""
    from .quiet import import_pcbnew, quiet_stderr
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = pcbnew.LoadBoard(pcb_path)
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
    as joining the pads they reach, as route_islands relies on for a plane,
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
        board = pcbnew.LoadBoard(pcb_path)
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
        board = pcbnew.LoadBoard(pcb_path)
    zones = [z for z in board.Zones() if z.GetZoneName().startswith(POUR_ZONE + " ")]
    if not zones:
        return 0
    with quiet_stderr():
        before = pcbnew.LoadBoard(str(given))
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


def _copy_project(src_pcb, dst_pcb) -> None:
    """The board's project files beside a copy of it: the router reads the
    netclasses (their widths and clearances) from them."""
    for ext in (".kicad_pro", ".kicad_dru"):
        if Path(src_pcb).with_suffix(ext).exists():
            shutil.copy(Path(src_pcb).with_suffix(ext), Path(dst_pcb).with_suffix(ext))


def router_command(python, script, pcb_in, pcb_out, excluded, layers, summary,
                   iterations: int | None = None, probe: int | None = None, quick: bool = False,
                   nets=None, widths=None, clearances: Path | None = None) -> list:
    """The router's command line. The search budget is the router's own
    default unless the caller sets one. A quick route is a measurement, so
    it runs one routing round (route_one_round.py). The router's own
    smoothing runs unless `[route] smoothing` is off. `nets` routes those
    alone rather than every net but the excluded; `widths` ({net: mm}) sets
    their track widths over the netclass's. `clearances` is the per-net
    clearance map placemat wrote (net_halos.py); None leaves the router to
    build its own from the net classes."""
    chosen = sorted(nets) if nets is not None else ["*"] + ["!" + n for n in sorted(excluded)]
    cmd = _launch(python, script) + [str(pcb_in), str(pcb_out), "--nets"] + chosen + \
          ["--layers"] + list(layers) + ["--escalation", "off"] + \
          ["--keep-input-copper"] + _tuning()      # the script's copper is its intent: no cleanup pass removes it
    if widths:
        named = sorted(widths)
        cmd += ["--power-nets"] + named + ["--power-nets-widths"] + ["%g" % widths[n] for n in named]
    if not active_settings().route_smoothing:
        cmd.append("--no-smoothing")
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    if probe is not None:
        cmd += ["--max-probe-iterations", str(probe)]
    if clearances is not None:
        cmd += ["--net-clearances", str(clearances)]
    return cmd + list(active_settings().route_router_args) + ["--json-out", str(summary)]


def route_islands(rpy, script, router_dir_path, board: Path, work: Path, islands: dict, layers, iterations, probe,
                  quick, timeout, env, share: float, clearances: Path | None = None, island_layers: dict | None = None) -> tuple:
    """Route the island nets, one at a time: each its pads and pieces its
    pours leave apart (the router counts a net's own zones as joining what
    they reach), the other island nets' partial pours kept clear of it as
    every other excluded net's are. A net in `island_layers` ({net: [layer,
    ...]}) is routed on its own layers, the rest on `layers`. Returns (the board the main pass routes
    on, its island tracks locked and no island guard left; the breaches of
    another island net's pour)."""
    breaches = []
    for i, net in enumerate(sorted(islands)):
        inp, out = work / ("islands%d_in.kicad_pcb" % i), work / ("islands%d.kicad_pcb" % i)
        shutil.copy(board, inp)
        _copy_project(board, inp)
        drop_pour_guards(str(inp), set(islands))
        guard_partial_pours(str(inp), set(islands) - {net}, layers, share)
        pours_as_zones(str(inp), net)
        width = islands[net]
        # A net's own layers go to the router as its --layers. The router appends every board copper layer left out
        # of --layers with the forbidden cost, the same as `--layer-costs -1` on it (KRT py_router/route.py:1291-1310):
        # no track and no via end on it, but a via between two allowed layers spans it (rust_router/src/router.rs:
        # 917-923, 1283-1288), so the net's through vias still pass the inner layers and join a pour there.
        own = (island_layers or {}).get(net) or layers
        cmd = router_command(rpy, script, inp, out, set(), own, work / ("islands%d_summary.json" % i), iterations,
                             probe, quick, nets=[net], widths={net: width} if width else None, clearances=clearances)
        log = work / ("islands%d.log" % i)
        with open(log, "w") as f:
            f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
            f.flush()
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir_path), env=env,
                                timeout=timeout, pass_fds=route_progress.pass_fds()).returncode
        if rc != 0 or not out.exists():
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-8:])
            raise RuntimeError("the router exited %d routing island net %s; log %s\n%s" % (rc, net, log, tail))
        _copy_project(inp, out)
        pours_back(str(out), board)
        lock_copper(str(out))
        others = tuple("%s %s " % (POUR_GUARD, n) for n in islands if n != net)
        breaches += [b for b in router_breaches(inp, out) if any(g in b for g in others)]
        board = out
    final = work / "islands.kicad_pcb"
    shutil.copy(board, final)
    _copy_project(board, final)
    drop_pour_guards(str(final), set(islands))
    return final, breaches


def routing_clearance(default: float, args, env) -> float:
    """The clearance the router gives the Default net class, as route.py resolves it: `--clearance` in the router arguments
    when given, else the board's Default class clearance (`default`), capped at the clearance ceiling (net_halos.ceiling)."""
    from ..settings import router_flag
    from .net_halos import ceiling
    given = router_flag(args, "--clearance")
    out = default if given is None else given
    cap = ceiling(args, env)
    return out if cap is None else min(out, cap)


def class_stages(clearances: dict, base: float, nets) -> list:
    """The class stages: the nets of `nets` whose clearance in `clearances` ({net: mm}, the router's map) is above `base`
    (the Default class's), grouped by clearance, widest first: [(mm, [net, ...])].

    The router spaces every net of one call at the largest clearance among the nets the call routes (KRT
    routing_config.py set_net_clearances, the routing-side floor), and prices each foreign net's copper at the larger of
    that floor and the net's own clearance (obstacle_clearance). A call per clearance routes each net at its own; the
    copper of an earlier stage keeps its own clearance against the later ones."""
    by = {}
    for n in nets:
        c = clearances.get(n)
        if c is not None and c > base + 1e-9:
            by.setdefault(round(float(c), 6), []).append(n)
    return [(c, sorted(by[c])) for c in sorted(by, reverse=True)]


def route_class_stages(rpy, script, router_dir_path, board: Path, work: Path, stages: list, layers, iterations, probe,
                       quick, timeout, env, clearances: Path | None = None) -> Path:
    """Route the class stages (`class_stages`), one router call each, in order, each on the board the one before left with
    its copper locked. Returns the board the main pass routes on."""
    for i, (mm, nets) in enumerate(stages):
        out = work / ("classes%d.kicad_pcb" % i)
        cmd = router_command(rpy, script, board, out, set(), layers, work / ("classes%d_summary.json" % i), iterations,
                             probe, quick, nets=nets, clearances=clearances)
        log = work / ("classes%d.log" % i)
        with open(log, "w") as f:
            f.write("$ %s\n\n" % " ".join(str(c) for c in cmd))
            f.flush()
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir_path), env=env,
                                timeout=timeout, pass_fds=route_progress.pass_fds()).returncode
        if rc != 0 or not out.exists():
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-8:])
            raise RuntimeError("the router exited %d routing the %g mm class nets; log %s\n%s" % (rc, mm, log, tail))
        _copy_project(board, out)
        lock_copper(str(out))
        board = out
    return board


def _route_board(pcb, work, exclude_nets=(), layers=None, router_dir_override: str | None = None,
                quick: bool = False, iterations: int | None = None, probe: int | None = None,
                timeout: int | None = None, islands: dict | None = None, resume: bool = True, board_info: dict | None = None,
                on_setup=None, island_layers: dict | None = None) -> RouteReport:
    """Route a copy of `pcb`. `islands` ({net: width or None}; None: the
    `[route] islands` setting) are routed first and alone, then left to their
    pours with the excluded nets. `island_layers` ({net: (layer, ...)}; None:
    the setting's) are the layers an island net's tracks keep to; a net not
    in it routes on the route's layers.

    With `[route] net_halos` on the board, every router call is given the
    clearance map net_halos.py writes, and the pads a halo traps are judged
    first: the `setup.net_halo` findings go to `on_setup` (a callable taking
    the list) before the first router call, and stay on the report.

    The stages - the differential pairs, the islands, the class stages (class_stages), the main pass - are
    kept in `work` as they finish (route_state.py): a route that is stopped
    or fails leaves them, and a rerun whose inputs digest the same takes them
    instead of routing again (`resume` False starts over). The report's
    `resumed` names the stages taken."""
    from ..settings import active
    from .route_state import RouteState, digest, file_digest
    cfg = active()
    islands = parse_islands(cfg.route_islands) if islands is None else dict(islands)
    islands, islands_missing = islands_on_board(pcb, islands) if islands else ({}, [])
    island_layers = {n: v for n, v in (parse_island_layers(cfg.route_islands) if island_layers is None
                                       else island_layers).items() if n in islands}
    router_dir_path = router_dir_override or router_dir(cfg)
    timeout = cfg.timeout_route if timeout is None else timeout
    iterations = cfg.route_max_iterations if iterations is None else iterations
    pcb, work = Path(pcb).resolve(), Path(work).resolve()          # the router runs in its own folder: paths it is given are absolute
    rpy = Path(router_dir_path) / ".venv/bin/python"
    route_py = Path(router_dir_path) / "py_router/route.py"
    if not (rpy.exists() and route_py.exists()):
        raise FileNotFoundError("router not found at %s (expected .venv/bin/python and py_router/route.py); "
                                "set KRT_DIR or [route] router_dir" % router_dir_path)
    state = RouteState(work, resume)
    from .. import channel, route_progress, route_view
    global _HOOK
    rep = channel.current()
    rev = route_progress.RouteEvents(work, rep.send if rep is not None else None, dict(board_info or {}, pcb=str(pcb), doc=route_progress.BOARD))
    _HOOK = route_progress.enabled()
    pcb_in = work / "in.kicad_pcb"
    shutil.copy(pcb, pcb_in)
    for ext in (".kicad_pro", ".kicad_dru"):
        src = pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, work / ("in" + ext))
    lock_copper(str(pcb_in))
    if layers:
        all_layers, layer_types_ = [], {}
    else:
        all_layers = _copper_layers(str(pcb_in))
        from .read import read_layer_types
        layer_types_ = read_layer_types(str(pcb_in))
    layers, plane_dropped = resolved_layers(layers, all_layers, layer_types_)
    island_layers = island_layers_on_board(island_layers, all_layers or _copper_layers(str(pcb_in))) if island_layers else {}
    excluded = set(exclude_nets) | set(islands)      # the main pass leaves the island nets to their pours
    counted = excluded - set(islands)                  # what the closure leaves out: the island nets are routed

    before = run_drc(pcb_in, work / "drc_before.json")
    open0 = {n: v for n, v in before.open_nets.items() if n not in counted}
    valid = not before.real
    guard_footprint_copper(str(pcb_in))          # after the placement's own DRC: the guards are the router's
    pours = guard_partial_pours(str(pcb_in), excluded - set(islands), layers, cfg.route_plane_share)

    # What every stage's result depends on: the board and its rules as given, what is left out, how it is
    # routed and by which router. Each stage's digest chains from the one before it.
    from .. import __version__
    base = digest(file_digest(pcb), file_digest(pcb.with_suffix(".kicad_pro")), file_digest(pcb.with_suffix(".kicad_dru")),
                  sorted(exclude_nets), sorted(islands.items()), layers, quick, iterations, probe,
                  router_version(router_dir_path), __version__,
                  {k: v for k, v in sorted(json.loads(cfg.json()).items()) if k.startswith("route_") and k != "route_router_dir"})
    resumed, spent = [], 0.0

    pcb_out = work / "routed.kicad_pcb"
    raw_out = work / "router_out.kicad_pcb"      # what the router wrote: post-processing is made on a copy
    summary = work / "router_summary.json"
    script = str(ONE_ROUND) if quick else str(route_py)
    env = child_env(headless=False)
    env.pop("KICAD_ROUTE_TRACE", None)
    env.pop("KICAD_SMOOTH_ROUTE", None)     # it overrides the router's smoothing flag: [route] smoothing decides
    env["KRT_DIR"] = str(router_dir_path)
    # the differential pairs first, as pairs; the rest route around them
    from .read import read_board
    from ..pairs import board_pair_list
    geometry = read_board(str(pcb_in))
    pair_list = board_pair_list(geometry.netclasses)
    board_doc = route_view.board_doc(geometry)
    (work / route_progress.BOARD).write_text(json.dumps(board_doc, separators=(",", ":")))
    if rep is not None:                                  # the board the copper is drawn on, for a route with no placement in front of it
        rep.send({"ev": "route_board", "doc": board_doc})
    from . import net_halos
    halos, halos_missing = net_halos.on_board(cfg.route_net_halos or {}, geometry.nets)
    trapped = net_halos.trapped(geometry, halos, judged={n for n in open0 if open0[n]}) if halos else []
    halo_findings = net_halos.findings(trapped, halos_missing, cfg.route_net_halos or {})
    if halo_findings and on_setup is not None:
        on_setup(halo_findings)
    clearances = net_halos.write_map(rpy, router_dir_path, pcb_in, geometry.nets, halos, work / net_halos.MAP_NAME,
                                     net_halos.ceiling(cfg.route_router_args, env), env) if halos else None
    pair_layers, pair_layers_refused = {}, []
    if cfg.route_pair_layers:
        pair_layers, pair_layers_refused = resolve_pair_layers(
            cfg.route_pair_layers, pair_list, {n: nc.name for n, nc in geometry.netclasses.items()}, _copper_layers(str(pcb_in)))
    d_pairs = digest(base, "pairs", pair_list)
    saved = state.result("pairs", d_pairs) if pair_list else None
    if saved is not None and (work / saved["board"]).exists():
        board, pairs = work / saved["board"], Pairs.from_dict(saved["pairs"])
        resumed.append("pairs")
        spent += saved["seconds"]
        rev.resumed("pairs", saved["seconds"])
    else:
        if pair_list:                            # with none, there is no stage to drop: the later ones stand
            state.drop_from("pairs")
        t1 = time.time()
        if pair_list:
            rev.begin("pairs")
        whole = False
        try:
            board, pairs = route_pairs(rpy, router_dir_path, pcb_in, work, pair_list, layers, cfg,
                                       iterations, probe, timeout, dict(env, **rev.env("pairs")), events=rev,
                                       pair_layers=pair_layers, halos=halos)
            whole = True
        finally:
            if pair_list:
                rev.end("pairs", complete=whole)
        spent += time.time() - t1
        if board != pcb_in:                      # the pair router ran: its board is a finished stage
            state.record("pairs", d_pairs, {"board": board.name, "pairs": pairs.to_dict(),
                                            "seconds": round(time.time() - t1, 1)})
    island_breaches = []
    d_islands = digest(d_pairs, "islands", sorted(islands.items()), *([sorted(island_layers.items())] if island_layers else []))
    if islands:
        saved = state.result("islands", d_islands)
        if saved is not None and (work / saved["board"]).exists():
            board, island_breaches = work / saved["board"], list(saved["breaches"])
            pours += saved["pours"]
            resumed.append("islands")
            spent += saved["seconds"]
            rev.resumed("islands", saved["seconds"])
        else:
            state.drop_from("islands")
            t1 = time.time()
            rev.begin("islands", nets=len(islands))
            whole = False
            try:
                board, island_breaches = route_islands(rpy, script, router_dir_path, board, work, islands, layers, iterations,
                                                       probe, quick, timeout, dict(env, **rev.env("islands")), cfg.route_plane_share,
                                                       clearances, island_layers)
                whole = True
            finally:
                rev.end("islands", complete=whole)
            kept = guard_partial_pours(str(board), set(islands), layers, cfg.route_plane_share)
            pours += kept
            spent += time.time() - t1
            state.record("islands", d_islands, {"board": board.name, "breaches": island_breaches, "pours": kept,
                                                "seconds": round(time.time() - t1, 1)})
    guarded = board                              # the island nets' pours are guarded on it: the later copper is judged against them
    # the nets whose clearance is above the Default's, a stage per clearance: the router spaces every net of one call at
    # the largest clearance among them (class_stages), so routed in the main pass they would space every net at theirs
    if halos:
        clearance_map = json.loads(Path(clearances).read_text())
    else:
        clearance_map = net_halos.merged(net_halos.class_clearances(rpy, router_dir_path, pcb_in, geometry.nets, env), {},
                                         net_halos.ceiling(cfg.route_router_args, env))
    # the router's own set: every net its --nets names with two pads or more, joined or not (KRT route.py
    # resolve_net_ids, net_queries.filter_routable_nets), and its floor is taken over all of them
    pads = {}
    for fp in geometry.footprints:
        for pad in fp.pads:
            if pad.net:
                pads[pad.net] = pads.get(pad.net, 0) + 1
    routed_later = {n for n, k in pads.items() if k >= 2 and n not in excluded | pairs.routed_nets}
    stages = class_stages(clearance_map, routing_clearance(geometry.default_clearance, cfg.route_router_args, env),
                          routed_later)
    staged = {n for _, nets in stages for n in nets}
    d_classes = digest(d_islands, "classes", stages)
    if stages:
        saved = state.result("classes", d_classes)
        if saved is not None and (work / saved["board"]).exists():
            board = work / saved["board"]
            resumed.append("classes")
            spent += saved["seconds"]
            rev.resumed("classes", saved["seconds"])
        else:
            state.drop_from("classes")
            t1 = time.time()
            rev.begin("classes", nets=len(staged))
            whole = False
            try:
                board = route_class_stages(rpy, script, router_dir_path, board, work, stages, layers, iterations, probe,
                                           quick, timeout, dict(env, **rev.env("classes")), clearances)
                whole = True
            finally:
                rev.end("classes", complete=whole)
            spent += time.time() - t1
            state.record("classes", d_classes, {"board": board.name, "seconds": round(time.time() - t1, 1)})
    # a net its class stage left open is not routed again: in the main pass it would raise every net's clearance to its own
    d_main = digest(d_classes, "main", sorted(excluded | pairs.routed_nets | staged))
    log = work / "router.log"
    saved = state.result("main", d_main)
    if saved is not None and raw_out.exists():
        resumed.append("main")
        spent += saved["seconds"]
        rev.resumed("main", saved["seconds"])
    else:
        state.drop_from("main")
        t1 = time.time()
        cmd = router_command(rpy, script, board, raw_out, excluded | pairs.routed_nets | staged, layers, summary,
                             iterations, probe, quick, clearances=clearances)
        rev.begin("main")
        rc = None
        try:
            with open(log, "w") as f:
                f.write("$ %s\n\n" % " ".join(cmd))
                f.flush()
                rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(router_dir_path), env=dict(env, **rev.env("main")),
                                    timeout=timeout, pass_fds=route_progress.pass_fds()).returncode
        finally:
            rev.end("main", complete=rc == 0)
        if rc != 0 or not raw_out.exists():
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-8:])
            raise RuntimeError("router exited %d without a routed board; log %s\n%s" % (rc, log, tail))
        spent += time.time() - t1
        state.record("main", d_main, {"board": raw_out.name, "seconds": round(time.time() - t1, 1)})
    seconds = round(spent, 1)
    shutil.copy(raw_out, pcb_out)
    for ext in (".kicad_pro", ".kicad_dru"):
        if (work / ("in" + ext)).exists():
            shutil.copy(work / ("in" + ext), work / ("routed" + ext))
    remove_guards(str(pcb_out))
    fill_zones(str(pcb_out))
    from .route_cleanup import remove_dangling_router_copper
    cleanup = remove_dangling_router_copper(str(pcb_out), str(pcb_in))     # after the fill: KiCad tests a track end in a zone by its fill
    after = run_drc(pcb_out, work / "drc_after.json", refill_zones=False)     # filled just now
    open1 = {n: v for n, v in after.open_nets.items() if n not in counted}
    by_net = _violations_by_net(json.loads((work / "drc_after.json").read_text()))
    violated = set(by_net)
    sc = score(open0, open1, {n for n in violated if n not in counted})
    breaches = router_breaches(pcb_in, pcb_out) + island_breaches
    if islands:     # the island nets' own pours were guarded after their pass: the main pass's copper against them
        own = tuple("%s %s " % (POUR_GUARD, n) for n in islands)
        breaches += [b for b in router_breaches(guarded, pcb_out) if any(g in b for g in own)]
    report = RouteReport(valid, round(sc.closure, 4), round(sc.closure_clean, 4), sum(open0.values()), sum(open1.values()),
                         dict(sorted(open1.items())), sc.shorted, sorted(counted), layers, seconds,
                         router_version(router_dir_path), after.by_type, pcb_out, log, work,
                         "" if valid else "placement DRC not clean before routing: %s" % before.real, quick,
                         breaches, pairs.as_dict(), plane_dropped, pours,
                         {n: (before.open_nets.get(n, 0), after.open_nets.get(n, 0)) for n in sorted(islands)},
                         islands_missing, resumed)
    from .route_widths import read_widths
    report.class_stages = [{"clearance_mm": mm, "nets": {n: [open0.get(n, 0), after.open_nets.get(n, 0)] for n in nets}}
                           for mm, nets in stages]
    report.violations = {n: by_net[n] for n in sc.shorted}
    report.island_layers = dict(island_layers)
    # the island nets judged on the routed board (route_widths.board_widths); the router's summaries for the rest
    from .route_widths import board_widths, judged_on_board, neck_allowance
    widths = []
    if islands:
        routed = read_board(str(pcb_out))
        widths = board_widths(routed, islands, cfg.check_rise_c, None, neck_allowance(cfg.route_router_args))
        judged = judged_on_board(islands)
    else:
        judged = set()
    report.widths = widths + [r for r in read_widths(work, islands, len(stages)) if r["net"] not in judged]
    report.pair_layers = {"%s/%s" % pair: list(ls) for pair, ls in pair_layers.items()}
    report.pair_layers_refused = pair_layers_refused
    report.net_halos, report.net_halos_missing, report.net_halo_trapped = halos, halos_missing, trapped
    report.net_halo_facts = [dict(f.facts) for f in halo_findings]
    report.dangling_removed = cleanup.record()
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
