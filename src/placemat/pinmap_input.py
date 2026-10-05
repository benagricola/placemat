"""What the pin map study reads from a placed board, as data: the studied parts and their pins, every net that touches
them, and the board's other airwires.

Scored as unrouted: the nets come from the pads alone (`ratsnest.board_nets(pads, copper=())`). A laid board's tracks,
vias and pours would join a routed net's pads into one cluster with no airwire left to move, so they are ignored for
connectivity - never torn up - and a first preview and a laid board are scored on the same terms. Pads that touch are
still one cluster, as KiCad has them.

A net that reaches a studied pin through a two-pad series part (a termination resistor) and nothing else is followed on
to the series part's far net, as one connection (`pins.follow_series`).

A studied part that is a member of a cell (a stamped module instance) is studied as the cell: its body is the cell's
envelope, centred on the envelope's centre, and it holds every member's pads, so its poses turn the whole cell. Only the
part's own pool pins move; its pins keep the outward normals of its own courtyard and leave by that side of the
envelope, and the other members' pads leave by the envelope side they are nearest. A net with every pad inside the cell
and none movable turns with the cell as a posed net of the background (its airwires straight between its pads).

A part not placed yet has no place to pull toward: a studied net with no pad placed but the part's own keeps its pin
(pinmap_rules.part_pins, `waiting`), and each studied net's pads on unplaced parts are listed (`StudyInput.unplaced`)."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import NamedTuple

from .ratsnest import Anchor, board_nets, mst
from .values import Box, Location

from .pinmap_rules import natural, part_pins, read_rules

KINDS = ("plain", "impedance", "pair", "plane")      # a net's crossing class, weakest of the signal ones first


@dataclass(frozen=True)
class PlacedPad:
    """A pad where the placement put it: what `board_nets` takes, and whether the capture marks it unconnected."""
    ref: str
    number: str
    net: str
    layers: frozenset
    outlines: tuple
    box: Box
    anchor: Location
    no_connect: bool = False


@dataclass(frozen=True)
class PlacedPart:
    """A part where the placement put it: its courtyard's box, rotation and face, whether its declaration lets it stand
    on the other face (`face=Face.EITHER`), and its footprint's fields (the capture's `Pm.*`)."""
    ref: str
    courtyard: Box
    rotation: float
    face: str
    may_flip: bool = False
    fields: dict = field(default_factory=dict, compare=False)
    cell: str = ""              # the cell it is a member of, if any


@dataclass(frozen=True)
class PlacedCell:
    """A cell (a stamped module instance) where the placement put it: its members' refs, its envelope (the box round
    its members' courtyards and its own copper), the rotation and face it stands at (0 and the front as stamped), whether
    that face is the other one from its stamp's, its module's name (None when the board does not say), how many cells of
    that module the board has, what tells that module from another (`module_key`), the arrangement of its module it
    stands in ("default" for the module's own layout), and the members not placed (`missing`, left out of `members`)."""
    name: str
    members: tuple
    envelope: Box
    rotation: float
    face: str
    flipped: bool = False
    module: str | None = None
    stamps: int = 1
    module_key: str = ""
    arrangement: str = "default"
    missing: tuple = ()


@dataclass(frozen=True)
class Pin:
    """A studied part's pad: its anchor in the part's own frame (the body box's centre, as the part stands) and the
    outward normal of the box side it is nearest. A cell's other members' pads are pins of the part studied as the cell:
    `owner` and `pad` name the member and its pad, and `number` is a label unique on the part."""
    number: str
    name: str
    x: float
    y: float
    nx: float
    ny: float
    owner: str = ""
    pad: str = ""

    def key(self, ref: str) -> tuple:
        """(ref, pad number) of the board pad this pin is: the part's own, else the member's."""
        return (self.owner, self.pad) if self.owner else (ref, self.number)


@dataclass(frozen=True)
class StudiedPart:
    ref: str
    cx: float                   # the body's centre: the courtyard box's, or the cell envelope's for a part in a cell
    cy: float
    hw: float                   # half the body box's width and height
    hh: float
    rotation: float
    face: str
    may_flip: bool
    pins: tuple                 # Pin, by pad number
    slots: object               # pinmap_rules.PartPins
    cell: str = ""              # the cell it is studied as, if any
    at: tuple = ()              # its own courtyard box's centre

    def pin(self, number: str) -> Pin:
        return next(p for p in self.pins if p.number == number)


@dataclass(frozen=True)
class StudyNet:
    """A net with a pad on a studied part. `fixed` are its anchors on other parts, `joined` index pairs of them that
    touch, `ends` its (ref, pad number) on studied parts as they stand. A followed net keeps its own name and carries the
    series part (`via`) and the net it is followed on to (`far`), whose anchors are its `fixed`."""
    net: str
    kind: str
    fixed: tuple
    joined: tuple
    ends: tuple
    via: str = ""
    far: str = ""


@dataclass(frozen=True)
class Wire:
    """One of the board's other airwires: a straight segment of `net`, crossing class `kind`."""
    net: str
    kind: str
    a: tuple
    b: tuple


@dataclass(frozen=True)
class PosedNet:
    """A background net with a pad on a studied part (a plane's, on the part's ground pins): its pads (`anchors`) and
    the pairs of them that touch, so the study can work out its airwires again when the part turns."""
    net: str
    kind: str
    anchors: tuple
    joined: tuple


@dataclass(frozen=True)
class StudyInput:
    parts: tuple                # StudiedPart, by ref
    nets: tuple                 # StudyNet, by net
    background: tuple           # Wire, every one: a posed net's at its pads' present places
    names: dict = field(default_factory=dict)      # ref -> {pad number: pin name}
    posed: tuple = ()           # PosedNet, by net
    cells: tuple = ()           # PlacedCell of the cells studied parts are in, by name
    unplaced: tuple = ()        # (studied part, net, unplaced part, series part, far net): each pad not placed yet of a
                                # studied part's net, or of the far net a series part takes it on to ("" "" for none);
                                # a cell member not placed that carries none of its nets has net ""
    inside: tuple = ()          # (studied part, net, member): a net held because its other pads are on its cell's members

    def part(self, ref: str) -> StudiedPart:
        return next(p for p in self.parts if p.ref == ref)

    def cell(self, name: str):
        return next(c for c in self.cells if c.name == name)


_SIDES = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))     # east, south, west, north: the order a tie is broken in


def outward(x: float, y: float, hw: float, hh: float) -> tuple:
    """The outward normal of the box side nearest a pin at (x, y) in the part's frame, the box being (-hw, -hh) to (hw, hh);
    ties go east, south, west, north."""
    gaps = (hw - x, hh - y, x + hw, y + hh)
    return _SIDES[min(range(4), key=lambda k: (gaps[k], k))]


def net_kind(net: str, quiet, partners: dict, netclasses: dict) -> str:
    """A net's crossing class: plane (a plane's or a free net), pair (a differential pair's half), impedance (its net
    class names a tuning profile: a controlled impedance, as KiCad 10 declares one), else plain."""
    if net in quiet:
        return "plane"
    if net in partners:
        return "pair"
    nc = netclasses.get(net)
    if nc is not None and getattr(nc, "tuning_profile", ""):
        return "impedance"
    return "plain"


def _merged(pads) -> list:
    """One PlacedPad per (ref, pad number): a pad drawn as several lands is one pin to the study."""
    out: dict = {}
    for p in pads:
        k = (p.ref, p.number)
        was = out.get(k)
        if was is None:
            out[k] = p
        else:
            out[k] = PlacedPad(p.ref, p.number, was.net or p.net, was.layers | p.layers, was.outlines + p.outlines,
                               Box.union([was.box, p.box]), was.anchor, was.no_connect or p.no_connect)
    return [out[k] for k in sorted(out, key=lambda k: (k[0], natural(k[1])))]


def build(pads, parts: dict, names: dict, quiet, partners: dict, netclasses: dict, follow_series: bool = True,
          follow_prefixes: tuple = ("R", "L", "FB"), cells=None, unplaced=()) -> tuple:
    """(StudyInput or None, [Problem]): `pads` every placed pad (PlacedPad), `parts` {ref: PlacedPart} of the placed
    parts, `names` {ref: {pad number: pin name}}, `quiet` the plane and free nets, `partners` {net: its pair's other
    half}, `netclasses` {net: NetClass}, `follow_prefixes` the reference prefixes of the series parts to follow, `cells`
    {name: PlacedCell} of the placed cells, `unplaced` (ref, pad number, net) of each pad of a part not placed. None when
    no part has a pool and a net that may move or waits on placement."""
    pads = _merged(pads)
    cells = dict(cells or {})
    of_ref: dict = {}
    for p in pads:
        of_ref.setdefault(p.ref, []).append(p)
    problems, read = [], []
    for ref in sorted(parts):
        mine = of_ref.get(ref, [])
        rules, said = read_rules(ref, parts[ref].fields, [(p.number, p.net) for p in mine], names.get(ref, {}))
        problems += said
        if rules is not None:
            read.append((ref, rules))
    if not read:
        return None, problems
    by_net = board_nets([(p.ref, p.number, p.net, p.layers, p.outlines, p.box, p.anchor) for p in pads], copper=())
    away: dict = {}                     # net -> {(ref, pad number)} of its pads on parts not placed
    for ref, number, net in unplaced:
        if net:
            away.setdefault(net, set()).add((ref, number))
    connected = frozenset(n for n in set(by_net) | set(away)
                          if len({(a.ref, a.number) for a in by_net.get(n, ((), ()))[0]} | away.get(n, set())) >= 2)
    pooled = {r for r, _ in read}
    cell_follow: dict = {}              # (part, net) -> (series member, far net): followed out of the part's cell
    inside_of: dict = {}                # part -> {net: [members]}: held, its other pads all on the part's cell
    for ref, rules in read:
        cell = cells.get(parts[ref].cell)
        if cell is None:
            continue
        members = frozenset(cell.members)
        for p in of_ref.get(ref, []):
            net = p.net
            if not net or net in quiet or net in away or p.number not in rules.pool or p.number in rules.fixed:
                continue
            anchors = by_net.get(net, ((), ()))[0]
            others = [a for a in anchors if a.ref != ref]
            if not others or any(a.ref not in members for a in others) or len(anchors) - len(others) != 1:
                continue
            got = _follow_out(net, others, of_ref, members, by_net, quiet, follow_prefixes, pooled) \
                if follow_series else None
            if got is not None:
                cell_follow[(ref, net)] = got
            else:
                inside_of.setdefault(ref, {})[net] = sorted({a.ref for a in others})
    slots_of = {}
    for ref, rules in read:
        mine = of_ref.get(ref, [])
        waiting = frozenset(n for n in away if not any(a.ref != ref for a in by_net.get(n, ((), ()))[0]))
        slots, said = part_pins(rules, [(p.number, p.net, p.no_connect) for p in mine], connected, quiet, waiting,
                                frozenset(inside_of.get(ref, ())))
        problems += said
        if slots is None or not (slots.movable or any(h.why == "unplaced" for h in slots.held)):
            continue
        slots_of[ref] = slots
    if not slots_of:
        return None, problems
    cell_of = {r: parts[r].cell for r in sorted(slots_of) if parts[r].cell in cells}
    lead: dict = {}                     # cell -> the studied part that holds its other members' pads
    for r in sorted(cell_of):
        lead.setdefault(cell_of[r], r)
    end_of: dict = {}                   # (ref, pad number) of a pad on a studied body -> (body, pin number)
    studied = []
    for ref in sorted(slots_of):
        part, mine = parts[ref], of_ref.get(ref, [])
        cell = cells.get(cell_of.get(ref, ""))
        own = part.courtyard.center
        ohw, ohh = part.courtyard.width / 2.0, part.courtyard.height / 2.0
        body = cell.envelope if cell is not None else part.courtyard
        c = body.center
        hw, hh = body.width / 2.0, body.height / 2.0
        pins = []
        for p in mine:
            nx, ny = outward(p.anchor.x - own.x, p.anchor.y - own.y, ohw, ohh)
            pins.append(Pin(p.number, names.get(ref, {}).get(p.number, ""), p.anchor.x - c.x, p.anchor.y - c.y, nx, ny))
            end_of[(ref, p.number)] = (ref, p.number)
        if cell is not None and lead[cell.name] == ref:
            for m in cell.members:
                if m in slots_of:
                    continue
                for p in of_ref.get(m, []):
                    x, y = p.anchor.x - c.x, p.anchor.y - c.y
                    label = "%s:%s" % (m, p.number)
                    nx, ny = outward(x, y, hw, hh)
                    pins.append(Pin(label, "", x, y, nx, ny, m, p.number))
                    end_of[(m, p.number)] = (ref, label)
        studied.append(StudiedPart(ref, c.x, c.y, hw, hh, part.rotation, part.face, part.may_flip and cell is None,
                                   tuple(pins), slots_of[ref], cell.name if cell is not None else "", (own.x, own.y)))
    on = {r for r, _ in end_of}
    in_cell = {s.ref for s in studied if s.cell}
    kind = lambda n: net_kind(n, quiet, partners, netclasses)
    out_of = {net: (r, via, far) for (r, net), (via, far) in cell_follow.items() if r in slots_of}
    nets, used = [], {far for _, _, far in out_of.values()}
    for net in sorted(by_net):
        anchors, joined = by_net[net]
        if net in quiet or net in used or not any(a.ref in on for a in anchors):
            continue
        if net in out_of:           # through a series member of the cell, on to the far net's pads outside it
            r, via, far = out_of[net]
            fa, fj = by_net[far]
            fixed = _fixed(fa, fj, [i for i, a in enumerate(fa) if a.ref not in on])
            ends = tuple(sorted((end_of[(a.ref, a.number)] for a in anchors if a.ref == r), key=lambda e: natural(e[1])))
            nets.append(StudyNet(net, max(kind(net), kind(far), key=KINDS.index), fixed[0], fixed[1], ends, via, far))
            continue
        ends = tuple(sorted({end_of[(a.ref, a.number)] for a in anchors if a.ref in on}, key=lambda e: (e[0], natural(e[1]))))
        bodies = {b for b, _ in ends}
        if len(bodies) == 1 and bodies <= in_cell and all(a.ref in on for a in anchors) and net not in away and \
                net not in slots_of[ends[0][0]].movable:
            continue            # inside one cell and held: it turns with the cell, a posed net of the background
        keep = [i for i, a in enumerate(anchors) if a.ref not in on]
        fixed, via, far, k = _fixed(anchors, joined, keep), "", "", kind(net)
        followed = _follow(net, ends, fixed[0], of_ref, on, by_net, quiet, follow_prefixes) if follow_series else None
        if followed is not None and followed[1] in used:          # another pin's net already carries this far net
            followed = None
        if followed is not None:
            via, far, fixed = followed
            used.add(far)
            k = max(k, kind(far), key=KINDS.index)
        nets.append(StudyNet(net, k, fixed[0], fixed[1], ends, via, far))
    studied_nets = {n.net for n in nets}
    background, posed = [], []
    for net in sorted(by_net):
        if net in studied_nets or net in used:
            continue
        anchors, joined = by_net[net]
        for e in mst(net, anchors, joined):
            background.append(Wire(net, kind(net), (e.a.x, e.a.y), (e.b.x, e.b.y)))
        if any(a.ref in on for a in anchors):
            posed.append(PosedNet(net, kind(net), tuple(anchors), tuple(tuple(p) for p in joined)))
    waits = []
    for s in studied:
        own = sorted({p.net for p in of_ref.get(s.ref, []) if p.net and p.net not in quiet})
        mine = [(s.ref, net, r, "", "") for net in own if net in away for r in sorted({r for r, _ in away[net]})]
        for net in own if follow_series else ():
            for via, far in _series_on(net, s.ref, by_net, of_ref, quiet, follow_prefixes):
                mine += [(s.ref, net, r, via, far) for r in sorted({r for r, _ in away.get(far, ())})]
        if s.cell:
            listed = {w[2] for w in mine}
            mine += [(s.ref, "", m, "", "") for m in cells[s.cell].missing if m not in listed]
        waits += sorted(set(mine), key=lambda w: (w[1], w[2], w[3]))
    inside = tuple((r, net, m) for r in sorted(slots_of) for net, ms in sorted(inside_of.get(r, {}).items()) for m in ms)
    return StudyInput(tuple(studied), tuple(nets), tuple(background),
                      {s.ref: dict(names.get(s.ref, {})) for s in studied}, tuple(posed),
                      tuple(cells[n] for n in sorted({s.cell for s in studied if s.cell})), tuple(waits), inside), problems


def _series(ref: str, of_ref, prefixes) -> bool:
    """Whether `ref` is a two-pad part whose reference's leading letters equal one of `prefixes`, in any case."""
    return len(of_ref.get(ref, ())) == 2 and \
        re.match(r"[A-Za-z]*", ref).group().upper() in {x.upper() for x in prefixes}


def _series_on(net, ref, by_net, of_ref, quiet, prefixes) -> list:
    """(series part, far net) of each placed series part on `net` but `ref`, its other pad on a net not quiet."""
    out = []
    for v in sorted({a.ref for a in by_net.get(net, ((), ()))[0] if a.ref != ref}):
        if not _series(v, of_ref, prefixes):
            continue
        far = next((p.net for p in of_ref[v] if p.net != net), "")
        if far and far not in quiet:
            out.append((v, far))
    return out


def _follow_out(net, others, of_ref, members, by_net, quiet, prefixes, pooled):
    """(series member, far net) when `net`'s one other pad is on a series member of the cell (`members`) whose other pad
    is on a net that is not quiet, has pads outside the cell, none on a part with a pool, and on the cell no pad but
    that member's: the net's pull is that far net's pads outside. None otherwise."""
    if len(others) != 1 or not _series(others[0].ref, of_ref, prefixes):
        return None
    via = others[0].ref
    far = next((p.net for p in of_ref[via] if p.number != others[0].number), "")
    if not far or far == net or far in quiet or far not in by_net:
        return None
    anchors = by_net[far][0]
    if any(a.ref in members and a.ref != via for a in anchors) or any(a.ref in pooled for a in anchors):
        return None
    if not any(a.ref not in members for a in anchors):
        return None
    return via, far


def _fixed(anchors, joined, keep) -> tuple:
    """(anchors, joined) of the anchors at `keep`, renumbered."""
    at = {i: k for k, i in enumerate(keep)}
    return (tuple(Anchor(anchors[i].ref, anchors[i].number, anchors[i].x, anchors[i].y) for i in keep),
            tuple((at[i], at[j]) for i, j in joined if i in at and j in at))


def _follow(net, ends, fixed, of_ref, on, by_net, quiet, prefixes):
    """(series part, far net, (anchors, joined)) when `net` joins one studied pin to one pad of a two-pad part not studied,
    whose reference's leading letters equal one of `prefixes` in any case, and whose other pad is on a net that is
    not quiet, reaches no studied part, and has other pads: that net's anchors less the series part's own. None
    otherwise."""
    if len(ends) != 1 or len(fixed) != 1:
        return None
    via = fixed[0].ref
    pads = of_ref.get(via, [])
    if via in on or len(pads) != 2:
        return None
    if re.match(r"[A-Za-z]*", via).group().upper() not in {x.upper() for x in prefixes}:
        return None
    other = next(p for p in pads if p.number != fixed[0].number)
    far = other.net
    if not far or far == net or far in quiet or far not in by_net:
        return None
    anchors, joined = by_net[far]
    if any(a.ref in on for a in anchors):
        return None
    keep = [i for i, a in enumerate(anchors) if a.ref != via]
    if not keep:
        return None
    return via, far, _fixed(anchors, joined, keep)


class Placed(NamedTuple):
    """What the study reads of a placed board: every placed pad (PlacedPad), {ref: PlacedPart} of the placed parts,
    {name: PlacedCell} of the placed cells, and (ref, pad number, net) of each pad of a part not placed."""
    pads: list
    parts: dict
    cells: dict
    unplaced: tuple


def placed_from_geometry(geometry, either=frozenset(), cell_rotations=None) -> Placed:
    """The Placed of a board where its file has its parts (a laid board read from
    disk, a bench case). Its copper is not read: the study is scored as unrouted. `either` are the parts that may stand
    on the other face. A file does not say how its cells were turned from their stamps: `cell_rotations` {name:
    degrees} does, and a cell it leaves out is taken at 0 degrees. A cell's face is its member with the most pads',
    and a cell on the back is taken as flipped from its stamp (a module is laid with its main part on the front)."""
    pads, parts = [], {}
    for fp in geometry.footprints:
        for p in fp.pads:
            pads.append(PlacedPad(fp.ref, p.number, p.net, frozenset(p.layers), tuple(p.outlines), p.box, p.airwire_end,
                                  p.no_connect))
        parts[fp.ref] = PlacedPart(fp.ref, fp.courtyard_box, fp.rotation, fp.face.value, fp.ref in either, dict(fp.fields),
                                   fp.cell or "")
    modules = cell_modules(geometry)
    stamps = stamp_counts(modules)
    turned = dict(cell_rotations or {})
    cells = {}
    for name, cg in sorted(geometry.cells.items()):
        members = tuple(sorted(fp.ref for fp in cg.members))
        if not members:
            continue
        module, key = modules[name]
        face = max(cg.members, key=lambda fp: (len(fp.pads), fp.ref)).face.value
        cells[name] = PlacedCell(name, members, cg.courtyard_box, float(turned.get(name, 0.0)), face, face != "front",
                                 module, stamps[key], key, cg.arrangement or "default")
    return Placed(pads, parts, cells, ())


def stamp_counts(modules: dict) -> dict:
    """{module key: how many cells have it}."""
    out: dict = {}
    for _, key in modules.values():
        out[key] = out.get(key, 0) + 1
    return out


def cell_modules(geometry) -> dict:
    """{cell: (module name or None, module key)} of every cell on the board. The generator's log beside the board names
    the module a cell was stamped from by its layout path: the name is that path's folder (the one holding `layout`),
    the key the path. A cell the log does not name (or a board with no log) has no name, and its key is what it holds:
    each member's place in the cell's instance path and its footprint, alike in every stamp of one module."""
    from .describe import layout_log
    try:
        layouts = layout_log(Path(geometry.path).parent / "layout.log").layouts if geometry.path else {}
    except OSError:
        layouts = {}
    out = {}
    for name, cg in geometry.cells.items():
        path = layouts.get(name)
        if path is not None:
            parts = [x for x in path.rstrip("/").split("/") if x]
            folder = parts[-2] if len(parts) >= 2 and parts[-1] == "layout" else parts[-1]
            out[name] = (folder, path)
            continue
        held = sorted("%s=%s" % (fp.inst[len(name) + 1:] if fp.inst.startswith(name + ".") else fp.inst, fp.lib_id)
                      for fp in cg.members)
        out[name] = (None, "members:" + hashlib.sha256("\n".join(held).encode()).hexdigest()[:16])
    return out
