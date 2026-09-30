"""A carried via gives way the same whether its move and its share tails are judged by the native
calls (`first_move`, `tail_clear`) or by the Python loop they replace: over random boards, random
vias and random item copper, `giveway._give` decides alike."""
import random
from dataclasses import replace

import pytest

from placemat import geometry as _geometry, giveway
from placemat.copper import Track
from placemat.geometry import via_ring
from placemat.occupancy import Occupancy, Shape, hole_shape
from placemat.values import Box, CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint

pytestmark = pytest.mark.skipif(_geometry._native is None, reason="no native module")

_F, _B = CopperLayer.F, CopperLayer.B
_BOTH_FACES = frozenset([Face.FRONT, Face.BACK])
_CASES = 1000


def _pad(owner, x, y, w, h, net, layers, label="1"):
    poly = ((x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2))
    faces = frozenset(l.face for l in layers)
    return Shape(owner, "pad", faces, frozenset(layers), net, poly, Box.of_points(poly), label)


def _ring(owner, x, y, size, net, carried="", layers=(_F, _B)):
    poly = via_ring(Location(x, y), size)
    return Shape(owner, "through", _BOTH_FACES, frozenset(layers), net, poly, Box.of_points(poly), carried=carried,
                 points=((x, y),) if carried else ())


def _track(owner, a, b, w, net, layer):
    t = Track(net, layer, w, Location(*a), Location(*b))
    return Shape(owner, "copper", frozenset([layer.face]), frozenset([layer]), net, t.polygon, t.box)


def _scene(rnd):
    """A random board, a carried via on it, the item's own copper and what first met the via."""
    ox, oy = (rnd.uniform(1.0, 3.0), rnd.uniform(1.0, 3.0)) if rnd.random() < 0.15 else (25.0, 25.0)

    def at(spread):
        return ox + rnd.uniform(-spread, spread), oy + rnd.uniform(-spread, spread)
    nets = ("A", "B", "C")
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="u1", nets=("B", "C")),
           footprint("U2", 10, 10, w=3, h=1, inst="u2", nets=("A", "B"))]
    g = board_geometry(fps, width=50, height=50, extra_nets=nets)
    occ = Occupancy(g, 0.5)
    board = []
    for _ in range(rnd.randint(3, 14)):
        net = rnd.choice(nets)
        kind = rnd.random()
        x, y = at(2.5)
        if kind < 0.35:
            size = rnd.choice([0.45, 0.6, 0.8])
            board.append(_ring("", x, y, size, net))
            board.append(hole_shape("", Location(x, y), size / 2.0, net))
        elif kind < 0.65:
            x2, y2 = at(2.5)
            board.append(_track("", (x, y), (x2, y2), rnd.choice([0.15, 0.2, 0.3]), net, rnd.choice([_F, _B])))
        else:
            board.append(_pad("", x, y, rnd.uniform(0.4, 1.4), rnd.uniform(0.4, 1.4), net,
                              rnd.choice([(_F,), (_B,), (_F, _B)])))
    cx, cy = at(1.0)
    net = "A"
    size = rnd.choice([0.45, 0.6])
    far = at(2.0) if rnd.random() < 0.7 else None
    layer = rnd.choice([_F, _B])
    shapes = [_ring("cell", cx, cy, size, net, carried="v"),
              replace(hole_shape("cell", Location(cx, cy), 0.2, net), carried="v")]
    if far is not None:
        _, tail = giveway._tail_shape("cell", net, layer, 0.2, far, (cx, cy), carried="v")
        shapes.append(tail)
    own = []
    for _ in range(rnd.randint(0, 5)):
        x, y = at(1.5)
        if rnd.random() < 0.8:
            own.append(_pad("U1", x, y, rnd.uniform(0.4, 1.4), rnd.uniform(0.4, 1.4), rnd.choice(("B", "C")),
                            rnd.choice([(_F,), (_B,), (_F, _B)])))
        else:
            own.append(replace(hole_shape("U1", Location(x, y), rnd.choice([0.4, 0.8]), "B"), kind="npth"))
    pads = []
    if rnd.random() < 0.4:                                     # the via lies in a pad of its own net
        pad = _pad("U1", cx + rnd.uniform(-0.2, 0.2), cy + rnd.uniform(-0.2, 0.2), rnd.uniform(1.0, 1.8),
                   rnd.uniform(1.0, 1.8), net, (_F, _B))
        pads.append((("U1", "1"), pad))
        own.append(pad)
    if rnd.random() < 0.3:                                     # a same-net via of the board, to share
        x, y = at(1.2)
        board.append(_ring("", x, y, 0.45, net))
    placed = rnd.random() < 0.5
    if placed:
        board += shapes
    occ.add_copper(board)
    grp = giveway.groups(occ, shapes)["v"]
    judge = giveway._Judge(occ, occ.obstacles(occ._geometry(g.footprint("u1"))), rnd.choice([None, None, 0.3]))
    if placed:
        judge.hidden.add("v")
    judge.extra = [_pad("", *at(1.5), 0.6, 0.6, rnd.choice(nets), (_F, _B)) for _ in range(rnd.randint(0, 2))]
    first = None
    for x in own + board:
        if x.kind in ("pad", "through", "copper") and x.box.overlaps(grp.ring.box, gap=0.3):
            first = x
            break
    who = giveway._Owner(occ, pads, Face.FRONT, {"v": grp})
    return occ, grp, judge, own, who, first


def _gave(out):
    a, why, needs = out
    if a is None:
        return None, why, needs
    return (a.kind, a.via, a.at, a.to, a.tail, a.old_tail, a.cost, a.target, a.pad), why, needs


def test_give_way_decides_the_same_with_the_native_calls_as_with_the_python_loop(monkeypatch):
    rnd = random.Random(20260930)
    used = []
    real = giveway._native_first_move

    def counting(*a, **k):
        out = real(*a, **k)
        used.append(out[0])
        return out
    monkeypatch.setattr(giveway, "_native_first_move", counting)
    kinds = {}
    judged_native = 0
    for n in range(_CASES):
        occ, grp, judge, own, who, first = _scene(rnd)
        monkeypatch.setattr(giveway, "_NATIVE_FIRST_MOVE", False)
        monkeypatch.setattr(giveway, "_NATIVE_TAIL_CLEAR", False)
        ref = _gave(giveway._give(occ, grp, judge, own, who, "met", {}, first))
        monkeypatch.setattr(giveway, "_NATIVE_FIRST_MOVE", True)
        monkeypatch.setattr(giveway, "_NATIVE_TAIL_CLEAR", True)
        used.clear()
        got = _gave(giveway._give(occ, grp, judge, own, who, "met", {}, first))
        assert got == ref, "case %d" % n
        kind = got[0][0] if got[0] else "refused"
        kinds[kind] = kinds.get(kind, 0) + 1
        judged_native += any(used)
    assert kinds.get("move", 0) >= 100 and kinds.get("refused", 0) >= 50, kinds
    assert judged_native >= 100, judged_native


def test_a_share_tail_is_judged_the_same_by_tail_clear_as_by_hit(monkeypatch):
    rnd = random.Random(20260931)
    clear = blocked = 0
    for n in range(_CASES):
        occ, grp, judge, own, who, first = _scene(rnd)
        end = (grp.centre[0] + rnd.uniform(-1.2, 1.2), grp.centre[1] + rnd.uniform(-1.2, 1.2))
        _, shape = giveway._tail_shape(grp.owner, grp.net, rnd.choice([_F, _B]), 0.2, grp.far or grp.centre, end,
                                       given=grp.id)
        monkeypatch.setattr(giveway, "_NATIVE_TAIL_CLEAR", False)
        ref = giveway._tail_hit(judge, shape, own)
        monkeypatch.setattr(giveway, "_NATIVE_TAIL_CLEAR", True)
        assert giveway._native_tail_clear(judge, shape, own) is not None
        assert giveway._tail_hit(judge, shape, own) == ref, "case %d" % n
        clear, blocked = clear + (not ref), blocked + ref
    assert clear >= 100 and blocked >= 100, (clear, blocked)
