"""What one routing phase routes on a board (route_phase.Phase -> Selection): whole nets, pad-to-pad tasks, differential
pairs and buses, the layers its tracks may use, and the width each is asked at. Pure: the board is a BoardGeometry, the
capture a capture_nets.Capture or None. The router calls are kicad/phase_run.py's."""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch

from ..route_phase import CAPTURE_SELECTORS, CURRENT, REST, PhaseError


@dataclass(frozen=True)
class Task:
    net: str
    start: tuple            # (ref, pad number)
    end: tuple
    widths: tuple           # ((layer name, mm), ...) in the phase's layer order
    amps: float | None = None

    def record(self) -> dict:
        return {"net": self.net, "from": {"ref": self.start[0], "pad": self.start[1]},
                "to": {"ref": self.end[0], "pad": self.end[1]}, "widths": dict(self.widths), "amps": self.amps}


@dataclass(frozen=True)
class Selection:
    phase: str
    selector: str
    nets: tuple = ()
    tasks: tuple = ()
    pairs: tuple = ()           # ((p, n), ...)
    buses: tuple = ()           # ((net, ...), ...)
    pour_nets: tuple = ()       # selected nets served by a pour, routed one at a time
    width: float | None = None  # a numeric width for whole nets
    layers: tuple = ()          # the layers its tracks may use
    rest: bool = False          # every open net not excluded


def net_matches(name: str, pattern: str) -> bool:
    """One net against one pattern as KRT reads it (py_router/net_queries.py:41-73, net_pattern_matches): an fnmatch
    glob, a pattern with no '/' also matching the last part of a sheet path. A leading backslash escapes the '!' of an
    active-low net (split_net_patterns, net_queries.py:18-52)."""
    if pattern.startswith("\\!"):
        pattern = pattern[1:]
    if fnmatch.fnmatch(name, pattern):
        return True
    return "/" not in pattern and "/" in name and fnmatch.fnmatch(name.rsplit("/", 1)[-1], pattern)


def _expand(phase, patterns, nets) -> list:
    """The nets the patterns take, as KRT's matches_net_filter (net_queries.py:81-130) reads them: "!X" excludes X
    unless "!X" itself is a net of the board; with only exclusions every other net is taken. An include pattern that
    names no net refuses the phase."""
    keep, drop = [], []
    for p in patterns:
        if p.startswith("\\!"):
            keep.append(p)
        elif p.startswith("!") and p not in nets:
            drop.append(p[1:])
        else:
            keep.append(p)
    out = {}
    for p in keep:
        hit = sorted(n for n in nets if net_matches(n, p))
        if not hit:
            raise PhaseError("not_on_board", name=phase.name, kind="net", value=p)
        out.update(dict.fromkeys(hit))      # in the order the patterns give them: a bus keeps its members' order
    if not keep:
        out = dict.fromkeys(sorted(nets))
    return [n for n in out if not any(net_matches(n, p) for p in drop)]


def layer_widths(amps: float, layers, geometry, rise_c: float, copper_oz: float) -> tuple:
    """The width `amps` needs on each layer by IPC-2221 at `rise_c`: the inner constant on an inner layer, each layer's
    own copper weight, never under the board's minimum track width."""
    from ..checks import _layer_k, _layer_oz, ipc2221_width_mm
    from ..values import CopperLayer
    out = []
    for name in layers:
        layer = CopperLayer.of(name)
        w = ipc2221_width_mm(amps, rise_c, _layer_oz(layer, geometry.copper_mm, copper_oz), _layer_k(layer))
        out.append((name, round(max(w, geometry.min_track_width or 0.0), 4)))
    return tuple(out)


def _pads_on(geometry, ref, net) -> list:
    return sorted({p.number for p in geometry.footprint(ref).pads if p.net == net}, key=lambda n: (len(n), n))


def current_tasks(geometry, nets, layers, rise_c, copper_oz) -> tuple:
    """Per net, each pair of the parts that carry current on it (`Pm.I`, checks.carriers_of), at the lesser current:
    from the first pad of each part to every pad of the other, so every pad of both on the net is joined.
    Returns (tasks, the nets with fewer than two carriers)."""
    from ..checks import carriers_of
    carriers = carriers_of(geometry)
    tasks, missing = [], []
    for net in sorted(nets):
        on = carriers.get(net, {})
        if len(on) < 2:
            missing.append(net)
            continue
        refs = sorted(on)
        for i, a in enumerate(refs):
            for b in refs[i + 1:]:
                amps = min(on[a], on[b])
                widths = layer_widths(amps, layers, geometry, rise_c, copper_oz)
                pa, pb = _pads_on(geometry, a, net), _pads_on(geometry, b, net)
                tasks.append(Task(net, (a, pa[0]), (b, pb[0]), widths, amps))
                tasks += [Task(net, (a, x), (b, pb[0]), widths, amps) for x in pa[1:]]
                tasks += [Task(net, (a, pa[0]), (b, y), widths, amps) for y in pb[1:]]
    return tuple(tasks), missing


def _end(phase, geometry, end):
    try:
        fp = geometry.footprint(end.part)
    except KeyError:
        raise PhaseError("not_on_board", name=phase.name, kind="part", value=end.part) from None
    try:
        pad = fp.pad(int(end.pad) if end.pad.isdigit() else end.pad)
    except KeyError:
        raise PhaseError("not_on_board", name=phase.name, kind="pad", value="%s %s" % (end.part, end.pad)) from None
    return fp.ref, pad.number, pad.net


def _class_widths(geometry, net, layers) -> tuple:
    nc = geometry.netclasses.get(net)
    return tuple((l, nc.track_width if nc else geometry.min_track_width or 0.2) for l in layers)


def select(phase, geometry, capture, *, open_nets, excluded, pour_nets, route_layers, rise_c, copper_oz) -> Selection:
    board_layers = [l.value for l in geometry.layers]
    layers = tuple(phase.layers or route_layers)
    missing = [l for l in layers if l not in board_layers]
    if missing:
        raise PhaseError("layer_missing", name=phase.name, layers=missing, board_layers=board_layers)
    if phase.selector in CAPTURE_SELECTORS:
        need = "types" if phase.selector == "net_types" else "interfaces"
        if capture is None or need not in capture.exports:
            raise PhaseError("needs_capture", name=phase.name, selector=phase.selector,
                             generator=capture.generator if capture is not None else None)
    numeric = phase.width if isinstance(phase.width, float) else None
    base = dict(phase=phase.name, selector=phase.selector, layers=layers)

    def whole(names):
        names = [n for n in names if n in open_nets and n not in excluded]
        if phase.width == CURRENT:
            tasks, short = current_tasks(geometry, names, layers, rise_c, copper_oz)
            if short:
                raise PhaseError("no_current", name=phase.name, nets=short)
            return Selection(tasks=tasks, **base)
        return Selection(nets=tuple(n for n in names if n not in pour_nets),
                         pour_nets=tuple(n for n in names if n in pour_nets), width=numeric, **base)

    if phase.selector == REST:
        nets = sorted(n for n in open_nets if n not in excluded and n not in pour_nets)
        return Selection(nets=tuple(nets), rest=True, width=numeric, **base)
    if phase.selector == "nets":
        return whole(_expand(phase, phase.nets, geometry.nets))
    if phase.selector == "net_classes":
        names = []
        for cls in phase.net_classes:
            hit = [n for n, nc in geometry.netclasses.items() if nc.name == cls]
            if not hit:
                raise PhaseError("not_on_board", name=phase.name, kind="class", value=cls)
            names += hit
        return whole(sorted(set(names)))
    if phase.selector == "net_types":
        for t in phase.net_types:
            if not capture.nets_of_types([t]):
                raise PhaseError("not_on_board", name=phase.name, kind="type", value=t)
        return whole(capture.nets_of_types(phase.net_types))
    if phase.selector == "buses":
        buses = tuple(tuple(n for n in _expand(phase, bus, geometry.nets) if n in open_nets and n not in excluded)
                      for bus in phase.buses)
        return Selection(buses=tuple(b for b in buses if b), width=numeric, **base)
    if phase.selector == "current_paths":
        # A numeric width is not used here: the tasks are sized from their currents (the user's decision of 2026-10-07).
        from ..checks import carriers_of
        nets = sorted(n for n, on in carriers_of(geometry).items() if len(on) >= 2 and n not in excluded)
        tasks, _ = current_tasks(geometry, nets, layers, rise_c, copper_oz)
        return Selection(tasks=tasks, **base)
    if phase.selector == "connections":
        from ..checks import carriers_of
        carriers = carriers_of(geometry) if phase.width == CURRENT else {}
        tasks, short = [], []
        for i, c in enumerate(phase.connections):
            a_ref, a_pad, a_net = _end(phase, geometry, c.start)
            b_ref, b_pad, b_net = _end(phase, geometry, c.end)
            if a_net != b_net:
                raise PhaseError("ends_on_two_nets", name=phase.name, index=i, nets=[a_net, b_net])
            if phase.width == CURRENT:
                on = carriers.get(a_net, {})
                if a_ref not in on or b_ref not in on:
                    short.append({"net": a_net, "from": a_ref, "to": b_ref})
                    continue
                amps = min(on[a_ref], on[b_ref])
                widths = layer_widths(amps, layers, geometry, rise_c, copper_oz)
            else:
                amps = None
                widths = tuple((l, numeric) for l in layers) if numeric else _class_widths(geometry, a_net, layers)
            tasks.append(Task(a_net, (a_ref, a_pad), (b_ref, b_pad), widths, amps))
        if short:
            raise PhaseError("no_current", name=phase.name, connections=short)
        return Selection(tasks=tuple(tasks), **base)
    if phase.selector == "pairs":
        # the sidecar lists one physical pair once per instance path that reaches it: dedupe by (p, n)
        pairs = tuple(dict.fromkeys((p, n) for _, p, n in capture.pairs))
        return Selection(pairs=tuple(pn for pn in pairs if all(n in open_nets and n not in excluded for n in pn)),
                         **base)
    raise PhaseError("needs_capture", name=phase.name, selector=phase.selector, generator=capture.generator)
