"""The native escape mirror answers `Escapes.closed` as the Python one does:
on real module boards, for every part at many spots and turns, and still
after parts are lifted, moved and put back and copper is planned."""
import random
import sys
from pathlib import Path

import pytest

native = pytest.importorskip("placemat_native")

from tests.conftest import needs_kicad, needs_native  # noqa: E402

pytestmark = [needs_native, needs_kicad]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))
import bench  # noqa: E402

MODULES = [p for p in bench.boards() if bench._name(p) in ("fairing/SlotControl", "fairing/Mcu", "mnb/MCU_RP2350B")]


def _both(occ, item, placement):
    from placemat.escapes import Escapes
    py = occ.__dict__.setdefault("_py_escapes", Escapes(occ, mirror=False))
    return occ.escapes().closed(item, placement, 0), py.closed(item, placement, 0)


@pytest.mark.parametrize("pcb", MODULES, ids=bench._name)
def test_closed_is_the_pythons_on_a_real_board(pcb):
    from placemat.kicad.read import read_board
    from placemat.placement import Placement
    from placemat.values import Location
    g = read_board(pcb)
    plan = bench.ModuleBoard(g, {}, bench._planes(g), bench._size(g, True))().resolve()
    occ = plan.occupancy
    rng = random.Random(len(g.footprints))
    fps = [fp for fp in g.footprints if fp.ref in occ.items and fp.ref not in occ.pending]
    nonzero = 0
    for trial in range(1500):
        if trial % 300 == 299:                          # a part lifted and put back elsewhere
            fp = rng.choice(fps)
            occ.lift([fp.ref])
            was = occ.items[fp.ref].reference
            occ.commit(fp, Placement(Location(was.location.x + rng.uniform(-2, 2), was.location.y + rng.uniform(-2, 2)),
                                     was.rotation, was.face))
            py = occ.__dict__.get("_py_escapes")
            if py is not None:
                py.refresh({fp.ref})
        fp = rng.choice(fps)
        at = occ.items[fp.ref].reference
        pl = Placement(Location(at.location.x + rng.uniform(-3, 3), at.location.y + rng.uniform(-3, 3)),
                       rng.choice((0.0, 90.0, 180.0, 270.0)), at.face)
        got, want = _both(occ, fp, pl)
        assert got == want, (trial, fp.ref, pl)
        nonzero += got != (0, 0, 0)
    assert nonzero > 50                                 # the question was a real one


@pytest.mark.slow
def test_native_surface_judge_matches_every_pad_of_three_modules(monkeypatch):
    from fixtures.reference.lock import realboard
    from placemat import geometry
    from placemat.escapes import judging
    from placemat.kicad.read import read_board
    module = geometry._native
    if module is None or not hasattr(module, 'surface_judge'):
        pytest.skip('native surface judge not built')
    assert len(MODULES) == 3
    with realboard():
        for pcb in MODULES:
            g = read_board(pcb)
            plan = bench.ModuleBoard(g, {}, bench._planes(g), bench._size(g, True))().resolve()
            esc = judging(plan.occupancy)
            for ref in sorted(plan.occupancy.items):
                if ref in plan.occupancy.pending:
                    continue
                for number in esc._lanes_of(ref)[2]:
                    monkeypatch.setattr(geometry, '_native', None)
                    expected = esc.judge(ref, number)
                    monkeypatch.setattr(geometry, '_native', module)
                    assert esc.judge_native(ref, number) == expected, (bench._name(pcb), ref, number)


def test_native_exact_surface_path_matches_python_ring_and_lattices(monkeypatch):
    from placemat import geometry
    from placemat.escapes import path_out
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _via_only_board
    module = geometry._native
    if module is None or not hasattr(module, 'surface_path_out'):
        pytest.skip('native surface path kernel not built')
    for gap in (0.1, 0.4, 0.8, 1.0):
        occ = _via_only_board(_walled_in(gap)).resolve().occupancy
        for toward in (None, (-1.0, 0.0), (1.0, 0.0), (-1.0, -1.0)):
            for via_exit in (False, True):
                monkeypatch.setattr(geometry, '_native', None)
                expected = path_out(occ, 'U9', '1', exact=True, toward=toward, via_exit=via_exit)
                monkeypatch.setattr(geometry, '_native', module)
                assert path_out(occ, 'U9', '1', exact=True, toward=toward,
                                via_exit=via_exit, native=True) == expected, (gap, toward, via_exit)


def test_native_surface_path_refuses_malformed_or_unbounded_search():
    from placemat import geometry
    module = geometry._native
    if module is None or not hasattr(module, 'surface_path_out'):
        pytest.skip('native surface path kernel not built')
    start = ([(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)], (-0.5, -0.5, 0.5, 0.5), 1, [], 0.0)
    args = ([start], [], 1, (-3.0, -3.0, 3.0, 3.0), 0.2, 0.4, None, [], 0.2, 0.0005)
    assert module.surface_path_out(*args)
    for index, invalid in ((0, []), (2, 0), (3, (0.0, 0.0, float('inf'), 3.0)),
                           (8, 0.0), (8, 1e-9), (8, 1e308), (4, -1.0), (6, (float('nan'), 0.0))):
        changed = list(args)
        changed[index] = invalid
        with pytest.raises(ValueError, match='surface escape'):
            module.surface_path_out(*changed)
    for invalid in (([(0.0, 0.0)] * 3, (0.0, 0.0, 0.0, 0.0), 1, [], 0.0),
                    (start[0], start[1], 0, [], 0.0),
                    ([(1e8, 1e8), (1e8 + 1, 1e8), (1e8, 1e8 + 1)],
                     (1e8, 1e8, 1e8 + 1, 1e8 + 1), 1, [], 0.0)):
        with pytest.raises(ValueError, match='surface escape'):
            module.surface_path_out([invalid], *args[1:])


def test_native_surface_judge_matches_python_for_signal_quiet_and_unconnected_pads(monkeypatch):
    from placemat import geometry
    from placemat.escapes import judging
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _via_only_board
    module = geometry._native
    if module is None or not hasattr(module, 'surface_judge'):
        pytest.skip('native surface judge not built')
    for gap in (0.1, 0.4, 0.8, 1.0):
        for quiet in (False, True):
            occ = _via_only_board(_walled_in(gap)).resolve().occupancy
            if quiet:
                occ.quiet_nets = {'IN'}
            esc = judging(occ)
            for ref in sorted(occ.items):
                for number in esc._lanes_of(ref)[2]:
                    monkeypatch.setattr(geometry, '_native', None)
                    expected = esc.judge(ref, number)
                    monkeypatch.setattr(geometry, '_native', module)
                    assert esc.judge_native(ref, number) == expected, (gap, quiet, ref, number)


def test_native_surface_judge_validates_search_even_when_a_lane_is_open():
    from placemat import geometry
    module = geometry._native
    if module is None or not hasattr(module, 'surface_judge'):
        pytest.skip('native surface judge not built')
    start = ([(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)], (-0.5, -0.5, 0.5, 0.5), 1, [], 0.0)
    path = ([start], [], 1, (-3.0, -3.0, 3.0, 3.0), 0.2, 0.4, None, [], 0.2, 0.0005, False)
    lane = ([((0.0, 0.0), (0.0, 0.0)), ((0.0, 0.0), (3.0, 0.0))], 1, (0.0, 0.0, 3.0, 0.0))
    assert module.surface_judge([lane], [], [], [], (1.0, 0.0), (0.0, 0.0), False, path) == 0
    invalid = list(path)
    invalid[8] = float('nan')
    with pytest.raises(ValueError, match='surface escape'):
        module.surface_judge([lane], [], [], [], (1.0, 0.0), (0.0, 0.0), False, tuple(invalid))
    invalid = list(path)
    invalid[10] = True  # a via cannot be counted as a free surface route
    with pytest.raises(ValueError, match='surface escape'):
        module.surface_judge([lane], [], [], [], (1.0, 0.0), (0.0, 0.0), False, tuple(invalid))


def test_native_surface_search_obeys_python_stop_without_a_partial_verdict():
    import signal
    from placemat import geometry
    module = geometry._native
    if module is None or not hasattr(module, 'surface_path_out'):
        pytest.skip('native surface path kernel not built')
    start = ([(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)], (-0.5, -0.5, 0.5, 0.5), 1, [], 0.0)
    def stop(*_):
        raise TimeoutError('surface search stopped')
    previous = signal.signal(signal.SIGALRM, stop)
    try:
        signal.setitimer(signal.ITIMER_REAL, 0.01)
        with pytest.raises(TimeoutError, match='surface search stopped'):
            module.surface_path_out([start], [], 1, (-100.0, -100.0, 100.0, 100.0),
                                    0.2, 0.4, (0.0, 0.0), [], 0.2, 0.0005)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_native_surface_path_keeps_exact_clearance_ties_and_negative_coordinates(monkeypatch):
    import math
    from types import SimpleNamespace
    from placemat import geometry
    from placemat.escapes import _path_out_exact, _path_out_native
    from placemat.values import Box, CopperLayer
    module = geometry._native
    if module is None or not hasattr(module, 'surface_path_out'):
        pytest.skip('native surface path kernel not built')
    layers = frozenset({CopperLayer.F})
    def rectangle(left, top, right, bottom):
        return SimpleNamespace(poly=((left, top), (right, top), (right, bottom), (left, bottom)),
                               box=Box(left, top, right, bottom), layers=layers, ends=())
    occ = SimpleNamespace(settings=SimpleNamespace(place_escape_cell=0.2),
                          geometry=SimpleNamespace(drc_epsilon=0.0005))
    start = [rectangle(-0.3, -0.05, 0.3, 0.05)]
    clearance = 0.2 - occ.geometry.drc_epsilon
    for half_gap in (math.nextafter(clearance, 0.0), clearance, math.nextafter(clearance, math.inf)):
        foes = [rectangle(-3, -3, -0.6, 3), rectangle(-0.6, -3, 3, -half_gap),
                rectangle(-0.6, half_gap, 3, 3)]
        args = (occ, start, foes, layers, Box(-2, -2, 2, 2), 0.2, 0.4, (1.0, 0.0))
        monkeypatch.setattr(geometry, '_native', None)
        expected = _path_out_exact(*args, via_exit=False)
        monkeypatch.setattr(geometry, '_native', module)
        for _ in range(3):
            assert _path_out_native(*args, via_exit=False) == expected


def test_native_lane_generation_matches_exact_pad_fields_split_lands_and_turns():
    from placemat import geometry
    from placemat.escapes import _pads_of, native_pad_lanes, pad_lanes
    from placemat.placement import Placement
    from placemat.values import Face, Location
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _via_only_board
    if not hasattr(geometry._native, 'surface_lanes'):
        pytest.skip('native surface lane generator not built')
    board = _via_only_board(_walled_in(0.1))
    plan = board.resolve()
    occ = plan.occupancy
    moving = board.geometry.footprint('R9')
    for face in (Face.FRONT, Face.BACK, Face.FRONT):
        for rotation in (0, 37, 90, 143):
            occ.commit(moving, Placement(Location(30.0000000005, 29.9999999995), rotation, face))
            for ref, geom in occ.items.items():
                pads = _pads_of(geom.shapes, ref)
                polys = {number: [s.poly for s in geom.shapes
                                  if s.owner == ref and s.label == number and s.kind in ('pad', 'through')]
                         for number in pads}
                for outlines in (None, polys):
                    expected = pad_lanes(occ, ref, pads, geom.reference.rotation, polys=outlines)
                    actual = native_pad_lanes(occ, ref, pads, geom.reference.rotation, polys=outlines)
                    assert actual == expected, (ref, rotation, face, outlines is None)


def test_native_lane_generation_preserves_blind_split_pad_contacts_and_toward_flags():
    from placemat import geometry
    from placemat.escapes import _pads_of, native_pad_lanes, pad_lanes
    from placemat.values import Face
    from tests.fixtures import pad
    from tests.test_surface_escapes import _part_of, _via_only_board
    if not hasattr(geometry._native, 'surface_lanes'):
        pytest.skip('native surface lane generator not built')
    split = _part_of('P1', 'p1', [pad('P1', 'p1', 1, 'S', -1.6, -10, 0.4, 0.4),
                                 pad('P1', 'p1', 1, 'S', 1.6, -10, 0.4, 0.4, face=Face.BACK)], 0, -10)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, -10, 0.4, 0.4)], 10, -10)
    board = _via_only_board([split, target])
    plan = board.resolve()
    occ = plan.occupancy
    geom = occ.items['P1']
    pads = _pads_of(geom.shapes, 'P1')
    polys = {'1': [s.poly for s in geom.shapes if s.kind in ('pad', 'through')]}
    for outlines in (polys, None):
        aims = {'1': (10.0, 0.0)}
        expected = pad_lanes(occ, 'P1', pads, 0, toward=aims, polys=outlines)
        actual = native_pad_lanes(occ, 'P1', pads, 0, toward=aims, polys=outlines)
        assert actual == expected
    assert not native_pad_lanes(occ, 'P1', pads, 0, polys=polys)[0]


def test_native_lane_generator_refuses_invalid_boundary_records():
    from placemat import geometry
    if not hasattr(geometry._native, 'surface_lanes'):
        pytest.skip('native surface lane generator not built')
    module = geometry._native
    good = ('1', 1, (-1.0, -1.0, 1.0, 1.0), None, True, 0.3, 0.3, 0.15, 0.2)
    for turn in ((0.0, 0.0), (float('nan'), 0.0), (2.0, 0.0)):
        with pytest.raises(ValueError):
            module.surface_lanes([good], 0.0, turn, 2.0, 1)
    for rows in ([good, good], [good[:1] + (0,) + good[2:]],
                 [good[:2] + ((0, 0, float('inf'), 1),) + good[3:]],
                 [good[:3] + ([[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]],) + good[4:]]):
        with pytest.raises(ValueError):
            module.surface_lanes(rows, 0.0, (1.0, 0.0), 2.0, 1)
    edge = good[:2] + ((1e9 - 1, 0, 1e9, 1),) + good[3:]
    with pytest.raises(ValueError, match='coordinate bounds'):
        module.surface_lanes([edge], 0.0, (1.0, 0.0), 2.0, 1)
