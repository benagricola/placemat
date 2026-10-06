"""The native sweep judges KiCad's net-tie exclusion itself: a net tie's
copper drawing has no clearance to the nets of its group
(DRC_ENGINE::EvalRules, FOOTPRINT::BuildNetTieCache), and a collision inside
a net-tie pad of the colliding item's net is let through
(DRC_ENGINE::IsNetTieExclusion). For every candidate of a part on top of,
beside and across a net tie's pads, and of a net tie over parts, tracks and
vias, on both faces, the native pass alone gives the verdict, the refusal and
the blocker that the pure-Python `legal_bucket` gives."""
import copy
import dataclasses
import random

import pytest

from placemat import layout
from placemat.copper import Track, Via
from placemat.occupancy import Occupancy, hole_shape
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location
from tests.conftest import needs_kicad, needs_native
from tests.fixtures import board_geometry, footprint, pad, rect
from tests.test_pad_on_pad_edge import _part, _tie

pytestmark = needs_native

FACES = (Face.FRONT, Face.BACK)
ROTS = (0, 90, 30)


def _natively(sweeper, triples):
    """`sweeper.run`, which is to judge no candidate in Python."""
    def refuse(*a, **kw):
        raise AssertionError("the native pass judged a candidate in Python")
    saved = Occupancy.legal, Occupancy.legal_bucket
    Occupancy.legal = Occupancy.legal_bucket = refuse
    try:
        return sweeper.run(triples, False)
    finally:
        Occupancy.legal, Occupancy.legal_bucket = saved


def _verdicts(occ, item, face, cands, rots=ROTS, clearance=None):
    """For each (x, y, turn) of `cands`: (the native pass's verdict, the pure-Python one), each None when legal,
    else (bucket, the refusal's facts, blocker)."""
    geom = occ._geometry(item)
    others = occ.obstacles(geom)
    py = copy.copy(others)
    py._native = None
    sweeper = occ.native_sweeper(item, face, rots, others, clearance)
    assert sweeper is not None
    out = []
    for x, y, turn in cands:
        found, _, refused = _natively(sweeper, [(x, y, turn)])
        nat = None if found else (refused[0][0], refused[0][3]().to_json(), refused[0][4])
        blame = []
        hit = occ.legal_bucket(item, Placement(Location(x, y), rots[turn], face), clearance, py, blame)
        ref = None if hit is None else (hit[0], hit[1]().to_json(), _blocker(blame))
        out.append(((x, y, turn), nat, ref))
    return out


def _blocker(blame):
    b = blame[0]
    return (b.kind, b.owner, "/".join(sorted(f.value for f in b.faces)))


def _cands(cx, cy, half_w, half_h, step, seed, rots=ROTS):
    """A grid round (cx, cy), each point jittered by up to a quarter step."""
    rnd = random.Random(seed)
    out = []
    nx, ny = int(2 * half_w / step) + 1, int(2 * half_h / step) + 1
    for i in range(nx):
        for j in range(ny):
            x = cx - half_w + i * step + rnd.uniform(-step / 4, step / 4)
            y = cy - half_h + j * step + rnd.uniform(-step / 4, step / 4)
            out.append((round(x, 6), round(y, 6), rnd.randrange(len(rots))))
    return out


def _assert_parity(rows):
    bad = [r for r in rows if r[1] != r[2]]
    assert not bad, "%d of %d candidates differ, first %r" % (len(bad), len(rows), bad[:3])


def _assert_scene(rows, excused):
    """The scene's candidates are both legal and refused, and KiCad's net-tie exclusion excused some pairs."""
    assert any(r[2] is None for r in rows) and any(r[2] is not None for r in rows), "the scene has both verdicts"
    assert excused[True] > 0, "the net-tie exclusion excused nothing: the scene does not test it"


@pytest.fixture
def excused(monkeypatch):
    """How many times Python's net-tie exclusions answered True and False."""
    from collections import Counter
    counts = Counter()
    for name in ("_net_tie_exclusion", "_hole_tie_exclusion"):
        real = getattr(Occupancy, name)

        def spy(self, *a, real=real, **kw):
            r = real(self, *a, **kw)
            counts[bool(r)] += 1
            return r
        monkeypatch.setattr(Occupancy, name, spy)
    return counts


def _track(net, a, b, width=0.2, layer=CopperLayer.F):
    return layout._shape_of(Track(net, layer, width, Location(*a), Location(*b)))


def _via(net, at, drill=0.3, size=0.6):
    shape = layout._shape_of(Via(net, Location(*at), drill, size))
    return [shape, hole_shape("", Location(*at), drill, net)]


def _occ(fps, movers, placed_at=(), extra_copper=(), envelope="courtyard", cells=()):
    occ = Occupancy(board_geometry(fps, cells=cells, width=40, height=40), edge_margin=1.0,
                    settings=dataclasses.replace(Settings(), place_envelope=envelope))
    for fp in fps:
        if fp in movers:
            continue
        at = dict(placed_at).get(fp.ref)
        occ.commit(fp, at or Placement(fp.location, fp.rotation, fp.face))
    if extra_copper:
        occ.add_copper(list(extra_copper))
    return occ


# ------------------------------------------------------------------ a part over a placed net tie
@pytest.mark.parametrize("tie_face", FACES)
@pytest.mark.parametrize("round_pads", [True, False])
@pytest.mark.parametrize("nets", [("A", "C"), ("B", "A"), ("A", "B")])
def test_a_part_over_a_placed_net_tie_is_judged_natively_as_python_judges_it(tie_face, round_pads, nets, excused):
    tie = _tie("NT", ("A", "B"), round_pads=round_pads)
    part = footprint("Q", 10, 10, w=2.6, h=0.6, nets=nets)
    occ = _occ([tie, part], [part], placed_at=[("NT", Placement(Location(20.25, 20.0), 0, tie_face))])
    rows = []
    for face in FACES:
        rows += _verdicts(occ, part, face, _cands(20.25, 20.0, 2.0, 1.0, 0.07, ord(nets[0]) * 31 + ord(nets[1]) + FACES.index(face)))
    _assert_parity(rows)
    _assert_scene(rows, excused)


# ------------------------------------------------------------------ a net tie over parts, tracks and vias
@pytest.mark.parametrize("round_pads", [True, False])
@pytest.mark.parametrize("courtyard", [False, True])
def test_a_net_tie_over_parts_tracks_and_vias_is_judged_natively_as_python_judges_it(round_pads, courtyard, excused):
    tie = _tie("NT", ("A", "B"), courtyard=courtyard, round_pads=round_pads)
    parts = [footprint("P1", 18.5, 20.0, w=2.0, h=0.6, nets=("C", "A")),
             footprint("P2", 22.0, 20.0, w=2.0, h=0.6, nets=("B", "D")),
             footprint("P3", 20.2, 21.6, w=2.6, h=0.6, nets=("A", "B"))]
    copper = [_track("A", (19.0, 18.6), (21.5, 18.6)), _track("B", (20.6, 18.0), (20.6, 19.2)),
              _track("C", (21.2, 21.0), (22.5, 21.0))] + _via("A", (19.4, 21.3)) + _via("D", (21.6, 18.9))
    occ = _occ([tie] + parts, [tie], extra_copper=copper)
    rows = []
    for face in FACES:
        rows += _verdicts(occ, tie, face, _cands(20.3, 20.0, 2.2, 1.8, 0.06, 7 + FACES.index(face)))
    _assert_parity(rows)
    _assert_scene(rows, excused)


# ------------------------------------------------------------------ a cell that owns a net tie
@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
def test_a_cell_owning_a_net_tie_is_judged_natively_as_python_judges_it(envelope, excused):
    tie = dataclasses.replace(_tie("NT", ("A", "B")), cell="grp")
    own = footprint("R", 21.5, 20, w=2.0, h=0.6, nets=("B", "C"), cell="grp")
    parts = [footprint("P1", 17.0, 20.0, w=2.0, h=0.6, nets=("C", "A")),
             footprint("P2", 24.0, 20.5, w=2.0, h=0.6, nets=("A", "D"))]
    occ = _occ([tie, own] + parts, [tie, own], extra_copper=[_track("A", (18.0, 19.0), (23.0, 19.0))],
               envelope=envelope, cells=("grp",))
    cell = occ.geometry.cell("grp")
    rows = []
    for face in FACES:
        rows += _verdicts(occ, cell, face, _cands(20.8, 20.0, 3.0, 1.5, 0.12, 11))
    _assert_parity(rows)
    _assert_scene(rows, excused)


# ------------------------------------------------------------------ a net tie whose pads touch
def _touching_tie(ref, nets):
    """A net tie whose two 0.3 mm square pads share an edge, pad 1 at (20, 20) and pad 2 east of it, and a bar
    between their centres: a collision with pad 2 lies on pad 1's edge, inside it by the DRC epsilon."""
    base = _tie(ref, nets, round_pads=False)
    pads = []
    for p, cx in zip(base.pads, (20.0, 20.3)):
        outline = rect(cx, 20.0, 0.3, 0.3)
        pads.append(dataclasses.replace(p, outlines=(outline,), box=Box.of_points(outline)))
    return dataclasses.replace(base, pads=tuple(pads), copper=((CopperLayer.F, rect(20.15, 20.0, 0.3, 0.1)),))


def _small(ref, nets, at=(10.0, 10.0)):
    """A part of two 0.2 mm pads 0.5 mm apart."""
    x, y = at
    return _part(ref, [pad(ref, ref.lower(), 1, nets[0], x - 0.25, y, 0.2, 0.2),
                       pad(ref, ref.lower(), 2, nets[1], x + 0.25, y, 0.2, 0.2)], x, y, fab=False)


@pytest.mark.parametrize("nets", [("A", "C"), ("B", "A")])
def test_a_small_part_and_tracks_on_a_net_tie_whose_pads_touch_are_judged_natively_as_python_judges_them(nets, excused):
    tie = _touching_tie("NT", ("A", "B"))
    part = _small("Q", nets)
    copper = [_track("A", (19.6, 20.05), (20.6, 20.05), width=0.1), _track("B", (20.5, 19.7), (19.9, 19.95), width=0.1)]
    occ = _occ([tie, part], [part], placed_at=[("NT", Placement(Location(20.25, 20.0), 0, Face.FRONT))],
               extra_copper=copper)
    rows = []
    for face in FACES:
        rows += _verdicts(occ, part, face, _cands(20.15, 20.0, 0.6, 0.4, 0.02, ord(nets[0]) + FACES.index(face)))
    _assert_parity(rows)
    _assert_scene(rows, excused)


@pytest.mark.parametrize("angle", [0, 30])
def test_a_net_tie_whose_pads_touch_over_tracks_and_vias_is_judged_natively_as_python_judges_it(angle, excused):
    tie = _touching_tie("NT", ("A", "B"))
    rnd = random.Random(angle)
    copper = []
    for k in range(12):
        net = "AB"[k % 2]
        x, y = 20.0 + rnd.uniform(-0.6, 0.6), 20.0 + rnd.uniform(-0.6, 0.6)
        copper.append(_track(net, (x, y), (x + rnd.uniform(-0.8, 0.8), y + rnd.uniform(-0.8, 0.8)), width=0.08))
    for k in range(6):
        copper += _via("AB"[k % 2], (20.0 + rnd.uniform(-1.5, 1.5), 20.0 + rnd.uniform(-1.5, 1.5)), 0.12, 0.24)
    others = [_small("P%d" % k, ("A", "B"), (17.0 + 3.0 * k, 25.0)) for k in range(3)]
    occ = _occ([tie] + others, [tie], extra_copper=copper)
    rows = []
    for face in FACES:
        rots = (angle, angle + 90)
        rows += _verdicts(occ, tie, face, _cands(20.15, 20.0, 0.8, 0.8, 0.03, angle + FACES.index(face), rots), rots)
    _assert_parity(rows)
    _assert_scene(rows, excused)


# ------------------------------------------------------------------ boards read from pcbnew, effective shapes and all
@needs_kicad
@pytest.mark.parametrize("shape,gap", [("rect", 0.5), ("circle", 0.5), ("roundrect", 0.5), ("oval", 0.5),
                                       ("rect", 0.3), ("circle", 0.25)])
def test_read_parts_and_a_read_net_tie_are_judged_natively_as_python_judges_them(tmp_path, shape, gap, excused):
    from placemat.kicad.read import read_board
    from tests.test_net_tie_collision import _Board
    b = _Board(tmp_path, shape)
    b.cap(10, 10, shape, w=0.4, h=0.4)
    b.tie(20, 20, angle=30.0, gap=gap)
    b.track("V", (20, 20), (20, 22))
    b.track("W", (21, 19.5), (23, 19.5))
    occ = Occupancy(read_board(str(b.save())), edge_margin=1.0, settings=Settings())
    occ.add_copper([_track("V", (9.0, 9.8), (11.0, 9.8), width=0.1), _track("W", (10.2, 8.8), (10.2, 11.0), width=0.1)])
    tie, cap = occ.geometry.footprint("NT"), occ.geometry.footprint("C")
    rows = []
    for item, (cx, cy) in ((cap, (20.0, 19.8)), (tie, (10.0, 10.0)), (tie, (8.5, 10.0))):
        for face in FACES:
            rows += _verdicts(occ, item, face, _cands(cx, cy, 1.6, 1.4, 0.07, 3))
    _assert_parity(rows)
    _assert_scene(rows, excused)


# ------------------------------------------------------------------ the real module with net ties
RINGSENSOR = "fixtures/fairing/modules/ringsensor/layout/layout.kicad_pcb"


@needs_kicad
@pytest.mark.parametrize("config", ["default", "physical", "solve"])
def test_the_ringsensor_module_is_swept_natively_as_python_sweeps_it(config, monkeypatch, excused):
    """Every sweep of the module's resolve: a sample of its candidates judged natively and in Python one by one
    alike; and the scans and the plan the same with the native sweep on and off."""
    import sys
    from pathlib import Path
    from placemat import occupancy, placer
    from placemat.kicad.read import read_board
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "fixtures"))
    import bench
    from tests.test_native_sweep import _plan, _record, _summary
    g = read_board(str(root / RINGSENSOR))
    make = bench.ModuleBoard(g, bench.CONFIGS[config], bench._planes(g), bench._size(g, True))
    real = occupancy.NativeSweeper.run
    rows = []

    def sampled(self, triples, stop_at_first, scoring=None):
        occ = self.occ
        for carried in (True, False):
            others = occ.obstacles(self.geom, carried=carried)
            if others._native is not None and others._native[1] is self.shapes:
                break
        else:
            return real(self, triples, stop_at_first, scoring)
        py = copy.copy(others)
        py._native = None
        step = max(1, len(triples) // 150)
        for x, y, turn in triples[:50] + triples[50::step]:
            found, _, refused = real(self, [(x, y, turn)], False)
            nat = None if found else (refused[0][0], refused[0][3]().to_json(), refused[0][4])
            blame = []
            hit = occ.legal_bucket(self.item, Placement(Location(x, y), self.rots[turn], self.face), self.clearance,
                                   py, blame)
            ref = None if hit is None else (hit[0], hit[1]().to_json(), _blocker(blame))
            rows.append(((x, y, turn), nat, ref))
        return real(self, triples, stop_at_first, scoring)

    runs = {}
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        if on:
            monkeypatch.setattr(occupancy.NativeSweeper, "run", sampled)
        seen = _record(monkeypatch)
        plan = make().resolve()
        runs[on] = (_summary(seen), _plan(plan))
    assert runs[True][0] == runs[False][0]
    assert runs[True][1] == runs[False][1]
    _assert_parity(rows)
    print("ringsensor %s: %d candidates sampled, %d refused, net-tie exclusion asked %d, excused %d" % (
        config, len(rows), sum(r[2] is not None for r in rows), excused[True] + excused[False], excused[True]))
    assert rows and excused[True] + excused[False] > 0, "the sweeps judged pairs with a net tie in them"
