"""What the pin map study reads from a placed board, as data: the studied parts and their pins, every net that touches
them, and the board's other airwires.

Scored as unrouted: the nets come from the pads alone (`ratsnest.board_nets(pads, copper=())`). A laid board's tracks,
vias and pours would join a routed net's pads into one cluster with no airwire left to move, so they are ignored for
connectivity - never torn up - and a first preview and a laid board are scored on the same terms. Pads that touch are
still one cluster, as KiCad has them.

A net that reaches a studied pin through a two-pad series part (a termination resistor) and nothing else is followed on
to the series part's far net, as one connection (`pins.follow_series`)."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

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


@dataclass(frozen=True)
class Pin:
    """A studied part's pad: its anchor in the part's own frame (the courtyard box's centre, as the part stands) and the
    outward normal of the box side it is nearest."""
    number: str
    name: str
    x: float
    y: float
    nx: float
    ny: float


@dataclass(frozen=True)
class StudiedPart:
    ref: str
    cx: float
    cy: float
    hw: float                   # half the courtyard box's width and height
    hh: float
    rotation: float
    face: str
    may_flip: bool
    pins: tuple                 # Pin, by pad number
    slots: object               # pinmap_rules.PartPins

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

    def part(self, ref: str) -> StudiedPart:
        return next(p for p in self.parts if p.ref == ref)


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
          follow_prefixes: tuple = ("R", "L", "FB")) -> tuple:
    """(StudyInput or None, [Problem]): `pads` every placed pad (PlacedPad), `parts` {ref: PlacedPart} of the placed
    parts, `names` {ref: {pad number: pin name}}, `quiet` the plane and free nets, `partners` {net: its pair's other
    half}, `netclasses` {net: NetClass}, `follow_prefixes` the reference prefixes of the series parts to follow. None when no part has a pool and a net that may move."""
    pads = _merged(pads)
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
    connected = frozenset(n for n, (anchors, _) in by_net.items() if len({(a.ref, a.number) for a in anchors}) >= 2)
    studied = []
    for ref, rules in read:
        part, mine = parts[ref], of_ref.get(ref, [])
        slots, said = part_pins(rules, [(p.number, p.net, p.no_connect) for p in mine], connected, quiet)
        problems += said
        if slots is None or not slots.movable:
            continue
        c = part.courtyard.center
        hw, hh = part.courtyard.width / 2.0, part.courtyard.height / 2.0
        pins = []
        for p in mine:
            x, y = p.anchor.x - c.x, p.anchor.y - c.y
            nx, ny = outward(x, y, hw, hh)
            pins.append(Pin(p.number, names.get(ref, {}).get(p.number, ""), x, y, nx, ny))
        studied.append(StudiedPart(ref, c.x, c.y, hw, hh, part.rotation, part.face, part.may_flip, tuple(pins), slots))
    if not studied:
        return None, problems
    on = {s.ref for s in studied}
    kind = lambda n: net_kind(n, quiet, partners, netclasses)
    nets, used = [], set()
    for net in sorted(by_net):
        anchors, joined = by_net[net]
        if net in quiet or not any(a.ref in on for a in anchors):
            continue
        ends = tuple(sorted({(a.ref, a.number) for a in anchors if a.ref in on}, key=lambda e: (e[0], natural(e[1]))))
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
    return StudyInput(tuple(studied), tuple(nets), tuple(background),
                      {s.ref: dict(names.get(s.ref, {})) for s in studied}, tuple(posed)), problems


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


def placed_from_geometry(geometry, either=frozenset()) -> tuple:
    """(pads, {ref: PlacedPart}) of a board where its file has its parts (a laid board read from disk, a bench case).
    Its copper is not read: the study is scored as unrouted. `either` are the parts that may stand on the other face."""
    pads, parts = [], {}
    for fp in geometry.footprints:
        for p in fp.pads:
            pads.append(PlacedPad(fp.ref, p.number, p.net, frozenset(p.layers), tuple(p.outlines), p.box, p.airwire_end,
                                  p.no_connect))
        parts[fp.ref] = PlacedPart(fp.ref, fp.courtyard_box, fp.rotation, fp.face.value, fp.ref in either, dict(fp.fields))
    return pads, parts
