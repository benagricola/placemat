"""What one routing phase routes on a board (route_phase.Phase -> Selection): whole nets, pad-to-pad tasks, differential
pairs and buses, the layers its tracks may use, and the width each is asked at. Pure: the board is a BoardGeometry, the
capture a capture_nets.Capture or None. The router calls are kicad/phase_run.py's."""
from __future__ import annotations

from dataclasses import dataclass
import fnmatch

from ..route_phase import CAPTURE_SELECTORS, CURRENT, REST, PhaseError


def end_record(end) -> dict:
    """A task end as records name it: {"ref", "pad"}, and "fp" (the footprint's uuid) when the end carries one."""
    return {"ref": end[0], "pad": end[1], "fp": end[2]} if len(end) > 2 else {"ref": end[0], "pad": end[1]}


@dataclass(frozen=True)
class Task:
    net: str
    start: tuple            # (ref, pad number), with the footprint's uuid third when another footprint has its ref
    end: tuple
    widths: tuple           # ((layer name, mm), ...) in the phase's layer order
    amps: float | None = None

    def record(self) -> dict:
        return {"net": self.net, "from": end_record(self.start), "to": end_record(self.end),
                "widths": dict(self.widths), "amps": self.amps}


def shared_refs(geometry) -> set:
    """The references two or more footprints of the board share."""
    seen, out = set(), set()
    for fp in geometry.footprints:
        (out if fp.ref in seen else seen).add(fp.ref)
    return out


def _task_end(fp, number, shared) -> tuple:
    """A task end on footprint `fp`'s pad `number`: (ref, pad), with its uuid when its ref is in `shared`."""
    return (fp.ref, number, fp.uuid) if fp.ref in shared else (fp.ref, number)


@dataclass(frozen=True)
class Selection:
    phase: str
    selector: str
    nets: tuple = ()
    tasks: tuple = ()
    pairs: tuple = ()           # ((p, n), ...)
    buses: tuple = ()           # ((net, ...), ...)
    pour_nets: tuple = ()       # selected nets served by a pour, whole nets or the nets of tasks. The call planner
                                # (kicad/phase_run.py) routes each such net alone in a call of its own, its pour
                                # handed to the router as a zone (D15); a task set's pour nets are named here too
    width: float | None = None  # a numeric width for whole nets
    layers: tuple = ()          # the layers its tracks may use
    rest: bool = False          # every open net not excluded


def net_matches(name: str, pattern: str) -> bool:
    """One net against one pattern as KRT reads it (py_router/net_queries.py:55-84, net_pattern_matches): an fnmatch
    glob, a pattern with no '/' also matching the last part of a sheet path. A leading backslash escapes the '!' of an
    active-low net (net_queries.py:17-52, split_net_patterns)."""
    if pattern.startswith("\\!"):
        pattern = pattern[1:]
    if fnmatch.fnmatch(name, pattern):
        return True
    return "/" not in pattern and "/" in name and fnmatch.fnmatch(name.rsplit("/", 1)[-1], pattern)


def _expand(phase, patterns, nets) -> list:
    """The nets the patterns take, as KRT's expand_net_patterns (net_queries.py:548-734, what route.py --nets uses):
    the wildcard pool leaves out 'unconnected-*' nets (584-610) and a net with no name, a literal naming one still
    takes it (719-725); "!X" excludes unless "!X" is a net of the board (655-660); a list of only exclusions implies
    '*' (612-621); an exclusion removes what is already taken and keeps a later include of it out (690-707).
    Divergence from upstream (which warns and carries on, 678-682, 727-732): a pattern that matches no net, include
    or exclusion, refuses the phase (not_on_board) instead."""
    known = set(nets)
    pool = sorted(n for n in known if n and not n.lower().startswith("unconnected-"))
    patterns = list(patterns)

    def exclusion(p):
        return p.startswith("!") and not p.startswith("\\!") and p not in known
    if patterns and all(exclusion(p) for p in patterns):
        patterns = ["*"] + patterns
    out, excluded = {}, set()
    for raw in patterns:
        if exclusion(raw):
            pat = raw[1:]
            hit = [n for n in pool if net_matches(n, pat)]
            if not hit and pat not in known:
                raise PhaseError("not_on_board", name=phase.name, kind="net", value=pat)
            if not any(c in pat for c in "*?"):
                excluded.add(pat)
            for n in hit:
                excluded.add(n)
                out.pop(n, None)
            continue
        pat = raw[1:] if raw.startswith("\\!") else raw
        hit = [n for n in pool if net_matches(n, pat) and n not in excluded]
        if not hit and pat in known and pat not in excluded:
            hit = [pat]
        if not hit and (any(c in pat for c in "*?") or pat not in known):
            raise PhaseError("not_on_board", name=phase.name, kind="net", value=pat)
        out.update(dict.fromkeys(hit))      # in the order the patterns give them: a bus keeps its members' order
    return list(out)


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


def _pads_on(fp, net) -> list:
    return sorted({p.number for p in fp.pads if p.net == net}, key=lambda n: (len(n), n))


def current_tasks(geometry, nets, layers, rise_c, copper_oz) -> tuple:
    """Per net, each pair of the footprints that carry current on it (`Pm.I`, checks.carrier_footprints: two that
    share a reference are two carriers), at the lesser current: from the first pad of each to every pad of the other,
    so every pad of both on the net is joined. Returns (tasks, the nets with fewer than two carriers)."""
    from ..checks import carrier_footprints
    carriers = carrier_footprints(geometry)
    shared = shared_refs(geometry)
    fps = geometry.footprints
    tasks, missing = [], []
    for net in sorted(nets):
        on = carriers.get(net, {})
        if len(on) < 2:
            missing.append(net)
            continue
        order = sorted(on, key=lambda i: (fps[i].ref, fps[i].uuid, i))
        for k, a in enumerate(order):
            for b in order[k + 1:]:
                amps = min(on[a], on[b])
                widths = layer_widths(amps, layers, geometry, rise_c, copper_oz)
                fa, fb = fps[a], fps[b]
                pa, pb = _pads_on(fa, net), _pads_on(fb, net)
                ea, eb = (lambda n: _task_end(fa, n, shared)), (lambda n: _task_end(fb, n, shared))
                tasks.append(Task(net, ea(pa[0]), eb(pb[0]), widths, amps))
                tasks += [Task(net, ea(x), eb(pb[0]), widths, amps) for x in pa[1:]]
                tasks += [Task(net, ea(pa[0]), eb(y), widths, amps) for y in pb[1:]]
    return tuple(tasks), missing


def _ends(phase, geometry, end) -> list:
    """The footprints and pads a connection end names, [(index in geometry.footprints, pad)]: the footprint whose
    instance it names, else every footprint with that reference (two may share one) that has the pad."""
    fps = geometry.footprints
    named = [i for i, fp in enumerate(fps) if fp.inst == end.part] or [i for i, fp in enumerate(fps) if fp.ref == end.part]
    if not named:
        raise PhaseError("not_on_board", name=phase.name, kind="part", value=end.part)
    out = []
    for i in named:
        try:
            out.append((i, fps[i].pad(int(end.pad) if end.pad.isdigit() else end.pad)))
        except KeyError:
            pass
    if not out:
        raise PhaseError("not_on_board", name=phase.name, kind="pad", value="%s %s" % (end.part, end.pad))
    return out


def _class_widths(geometry, net, layers) -> tuple:
    nc = geometry.netclasses.get(net) or next((c for c in geometry.netclasses.values() if c.name == "Default"), None)
    return tuple((l, nc.track_width if nc else geometry.min_track_width) for l in layers)


def _pours(tasks, pour_nets) -> tuple:
    return tuple(sorted({t.net for t in tasks} & set(pour_nets)))


def select(phase, geometry, capture, *, open_nets, excluded, pour_nets, route_layers, rise_c, copper_oz) -> Selection:
    board_layers = [l.value for l in geometry.layers]
    layers = tuple(phase.layers or route_layers)
    missing = [l for l in layers if l not in board_layers]
    if missing:
        raise PhaseError("layer_missing", name=phase.name, layers=missing, board_layers=board_layers)
    if phase.selector in CAPTURE_SELECTORS and not (phase.selector == "pairs" and phase.pairs):
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
            return Selection(tasks=tasks, pour_nets=_pours(tasks, pour_nets), **base)
        return Selection(nets=tuple(n for n in names if n not in pour_nets),
                         pour_nets=tuple(n for n in names if n in pour_nets), width=numeric, **base)

    if phase.selector == REST:
        nets = sorted(n for n in open_nets if n not in excluded and n not in pour_nets)
        return whole(nets) if phase.width == CURRENT else Selection(nets=tuple(nets), rest=True, width=numeric, **base)
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
        if phase.width == CURRENT:
            tasks, short = current_tasks(geometry, {n for bus in buses for n in bus}, layers, rise_c, copper_oz)
            if short:
                raise PhaseError("no_current", name=phase.name, nets=short)
            return Selection(buses=tuple(b for b in buses if b), tasks=tasks, pour_nets=_pours(tasks, pour_nets), **base)
        return Selection(buses=tuple(b for b in buses if b), width=numeric, **base)
    if phase.selector == "current_paths":
        # A numeric width is not used here: the tasks are sized from their currents (the user's decision of 2026-10-07).
        from ..checks import carrier_footprints
        nets = sorted(n for n, on in carrier_footprints(geometry).items() if n and n in geometry.nets and len(on) >= 2
                      and n not in excluded)
        tasks, _ = current_tasks(geometry, nets, layers, rise_c, copper_oz)
        return Selection(tasks=tasks, pour_nets=_pours(tasks, pour_nets), **base)
    if phase.selector == "connections":
        from ..checks import carrier_footprints
        carriers = carrier_footprints(geometry) if phase.width == CURRENT else {}
        shared = shared_refs(geometry)
        fps = geometry.footprints
        tasks, short = [], []
        for i, c in enumerate(phase.connections):
            starts, ends = _ends(phase, geometry, c.start), _ends(phase, geometry, c.end)
            for fi, pad in starts + ends:
                if not pad.net:
                    raise PhaseError("not_on_board", name=phase.name, kind="pad",
                                     value="%s %s on a net" % (fps[fi].ref, pad.number))
            # an end on a reference two footprints share names each of them: one task per pair of ends on one net
            pairs = [(a, b) for a in starts for b in ends if a[1].net == b[1].net]
            if not pairs:
                raise PhaseError("ends_on_two_nets", name=phase.name, index=i, nets=[starts[0][1].net, ends[0][1].net])
            for (fa, pa), (fb, pb) in pairs:
                net = pa.net
                if phase.width == CURRENT:
                    on = carriers.get(net, {})
                    if fa not in on or fb not in on:
                        short.append({"net": net, "from": fps[fa].ref, "to": fps[fb].ref})
                        continue
                    amps = min(on[fa], on[fb])
                    widths = layer_widths(amps, layers, geometry, rise_c, copper_oz)
                else:
                    amps = None
                    widths = tuple((l, numeric) for l in layers) if numeric else _class_widths(geometry, net, layers)
                tasks.append(Task(net, _task_end(fps[fa], pa.number, shared), _task_end(fps[fb], pb.number, shared),
                                  widths, amps))
        if short:
            raise PhaseError("no_current", name=phase.name, connections=short)
        return Selection(tasks=tuple(tasks), pour_nets=_pours(tasks, pour_nets), **base)
    if phase.selector == "pairs" and phase.pairs:
        for n in (n for pn in phase.pairs for n in pn):
            if n not in geometry.nets:
                raise PhaseError("not_on_board", name=phase.name, kind="net", value=n)
        return Selection(pairs=tuple(pn for pn in phase.pairs if any(n in open_nets for n in pn) and all(n not in excluded for n in pn)),
                         **base)
    if phase.selector == "pairs":
        # the sidecar lists one physical pair once per instance path that reaches it: dedupe by (p, n)
        pairs = tuple(dict.fromkeys((p, n) for _, p, n in capture.pairs))
        if not pairs:
            raise PhaseError("not_on_board", name=phase.name, kind="pair", value="")
        for n in (n for pn in pairs for n in pn):
            if n not in geometry.nets:
                raise PhaseError("not_on_board", name=phase.name, kind="net", value=n)
        return Selection(pairs=tuple(pn for pn in pairs if any(n in open_nets for n in pn) and all(n not in excluded for n in pn)),
                         **base)
    if phase.selector == "interfaces":
        chosen = []
        for want in phase.interfaces:
            hit = [i for i in capture.instances.values() if i.path == want or i.type == want]
            if not hit:
                raise PhaseError("not_on_board", name=phase.name, kind="interface", value=want)
            chosen += [i for i in hit if i not in chosen]
        routable = {n for n in geometry.nets if sum(1 for fp in geometry.footprints for p in fp.pads if p.net == n) >= 2}
        pairs, buses = [], []
        for inst in chosen:
            if inst.type == "DiffPair":
                pair = (inst.members["P"], inst.members["N"])
                for n in pair:
                    if n not in geometry.nets:
                        raise PhaseError("not_on_board", name=phase.name, kind="net", value=n)
                if any(n in open_nets for n in pair) and all(n not in excluded for n in pair) and pair not in pairs:
                    pairs.append(pair)
                continue
            nets = tuple(sorted({n for n in inst.members.values() if n in routable and n in open_nets and n not in excluded}))
            if nets and nets not in buses:
                buses.append(nets)
        if pairs and phase.width is not None:
            raise PhaseError("pair_width", name=phase.name)
        if phase.width == CURRENT:
            tasks, short = current_tasks(geometry, {n for bus in buses for n in bus}, layers, rise_c, copper_oz)
            if short:
                raise PhaseError("no_current", name=phase.name, nets=short)
            return Selection(buses=tuple(buses), tasks=tasks, pour_nets=_pours(tasks, pour_nets), **base)
        return Selection(pairs=tuple(pairs), buses=tuple(buses), width=numeric, **base)
    raise PhaseError("needs_capture", name=phase.name, selector=phase.selector, generator=capture.generator)


def duplicate_references(geometry, nets) -> list:
    """Each reference two or more footprints share among the footprints with a pad on `nets`, in reference order:
    {"ref", "nets": [the nets of `nets` its pads are on], "footprints": [{"uuid", "at": [x, y]}, ...]}. KiCad allows
    it; a connection's end then names its footprint by uuid as well (phase_run.open_connections)."""
    by_ref = {}
    for fp in geometry.footprints:
        if any(p.net in nets for p in fp.pads):
            by_ref.setdefault(fp.ref, []).append(fp)
    out = []
    for ref, fps in sorted(by_ref.items()):
        if len(fps) > 1:
            out.append({"ref": ref, "nets": sorted({p.net for fp in fps for p in fp.pads if p.net in nets}),
                        "footprints": [{"uuid": fp.uuid, "at": [fp.location.x, fp.location.y]} for fp in fps]})
    return out
