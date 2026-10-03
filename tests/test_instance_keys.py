"""The lock and adopted routes name parts by instance path: a refdes
renumbering elsewhere on the board (a capacitor removed, the rest
renumbered) moves nothing and drops nothing."""
import dataclasses

from placemat.refusals import Refusal
from placemat import lock, routes
from placemat.explore import Explore
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint
from tests.test_lock import FOCUS, _accepted, _where
from tests.test_routes import _parts, _routed


def _renumbered_lock_board():
    """test_lock's board with every refdes changed, and a decoy standing
    under the anchor's old refdes."""
    fps = [footprint("U5", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B")),
           footprint("R11", 60, 60, w=2, h=1, inst="r1", nets=("A", "X")),
           footprint("R12", 60, 62, w=2, h=1, inst="r2", nets=("B", "Y")),
           footprint("R13", 60, 64, w=2, h=1, inst="r3", nets=("A", "Z")),
           footprint("C9", 60, 66, w=2, h=1, inst="c1", nets=("B", "Q")),
           footprint("W1", 70, 70, w=2, h=1, inst="wall", nets=("W", "V")),
           footprint("R9", 70, 75, w=2, h=1, inst="late", nets=("Q", "V")),
           footprint("U1", 50, 50, w=2, h=1, inst="decoy", nets=("K", "L"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("mcu"), at=Location(25, 25))
    b.place(Part("decoy"), at=Location(50, 50))
    for k in ("r1", "r2", "r3", "c1"):
        b.place(Part(k))
    return b


def test_a_lock_entry_names_its_anchor_by_instance():
    _, entries = _accepted()
    assert {e.anchor[0] for e in entries if e.anchor} <= {"mcu", "r1", "r2", "r3", "c1"}


def test_a_lock_holds_after_the_board_is_renumbered():
    variant, entries = _accepted()
    plan = _renumbered_lock_board().resolve(lock=entries)
    held = [s for s in plan.steps if s.item in FOCUS and "held by lock" in (s.note or "")]
    assert len(held) == len(FOCUS), [(s.item, s.note) for s in plan.steps if s.item in FOCUS]
    assert _where(plan) == _where(variant)


def test_a_lock_written_with_refdes_still_holds():
    """A lock written by 0.43-0.46: refdes anchors and the refdes digest."""
    b0 = __import__("tests.test_lock", fromlist=["_board"])._board()
    variant, entries = _accepted()
    intents = {i.key: i for i in b0._placements()}
    ref_of = {fp.inst: fp.ref for fp in b0.geometry.footprints}
    old = [dataclasses.replace(e, anchor=(ref_of[e.anchor[0]], e.anchor[1]) if e.anchor else None,
                               declaration=lock.declaration_digest(b0, intents[e.key], legacy=True)) for e in entries]
    plan = __import__("tests.test_lock", fromlist=["_board"])._board().resolve(lock=old)
    assert _where(plan) == _where(variant)


def test_adopted_routes_resolve_after_the_board_is_renumbered():
    placed, routed = _routed()
    (e,) = routes.entries_from(placed, routed, ["X"])
    assert set(e.parts) == {"u1", "r1"}                         # instances, not refdes
    parts = [footprint("U9", 10, 10, w=4, h=1, inst="u1", nets=("A", "X")),
             footprint("R7", 20, 16, w=2, h=1, inst="r1", nets=("X", "B")),
             footprint("U1", 30, 30, w=4, h=1, inst="other", nets=("K", "L"))]
    b = Board(board_geometry(parts, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"), at=Location(20, 16))
    b.place(Part("other"), at=Location(30, 30))
    got = routes.resolve(e, b.resolve().occupancy, 0.001)
    assert not isinstance(got, str), got
    ends = sorted((round(p.x, 6), round(p.y, 6)) for t in got[0] for p in (t.start, t.end))
    assert ends == sorted([(11.4, 10.0), (15.0, 10.0), (15.0, 10.0), (19.4, 16.0)])


def test_adopted_routes_written_with_refdes_still_resolve():
    placed, routed = _routed()
    (e,) = routes.entries_from(placed, routed, ["X"])
    ref_of = {"u1": "U1", "r1": "R1"}

    def point(p):
        k = "pad" if "pad" in p else "anchor"
        return {**p, k: [ref_of[p[k][0]], p[k][1]]}
    old = dataclasses.replace(e, parts={ref_of[k]: v for k, v in e.parts.items()},
                              tracks=tuple({**t, "a": point(t["a"]), "b": point(t["b"])} for t in e.tracks),
                              vias=tuple({**v, "at": point(v["at"])} for v in e.vias))
    from tests.test_routes import _occupancy
    assert not isinstance(routes.resolve(old, _occupancy(), 0.001), Refusal)


def test_a_cells_digest_does_not_follow_the_order_its_members_are_read_in():
    """A re-stamped fragment lists its footprints in another order: the
    lock's digest of the cell must not change with it."""
    from placemat.values import Cell
    def board(order):
        fps = [footprint("C1", 10, 10, w=2, h=1, inst="m.c1", nets=("A", "B"), cell="m"),
               footprint("R1", 14, 10, w=2, h=1, inst="m.r1", nets=("B", "C"), cell="m"),
               footprint("U1", 12, 14, w=4, h=2, inst="m.u1", nets=("A", "C"), cell="m")]
        b = Board(board_geometry([fps[i] for i in order], cells=["m"], width=40, height=40), edge_margin=0.5)
        b.place(Cell("m"))
        return b
    digests = set()
    for order in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
        b = board(order)
        (intent,) = [i for i in b._placements() if i.key == "m"]
        digests.add(lock.declaration_digest(b, intent))
    assert len(digests) == 1


def test_a_lock_written_by_0_48_with_its_members_as_read_still_holds():
    from placemat.values import Cell
    fps = [footprint("C1", 10, 10, w=2, h=1, inst="m.c1", nets=("A", "B"), cell="m"),
           footprint("R1", 14, 10, w=2, h=1, inst="m.r1", nets=("B", "C"), cell="m")]
    b = Board(board_geometry(fps[::-1], cells=["m"], width=40, height=40), edge_margin=0.5)
    b.place(Cell("m"))
    (intent,) = [i for i in b._placements() if i.key == "m"]
    plan = b.resolve()
    (e,) = lock.entries(b, plan, ["m"])
    old = dataclasses.replace(e, declaration=lock.declaration_digest(b, intent, ordered=False))
    assert old.declaration != e.declaration
    b2 = Board(board_geometry(fps[::-1], cells=["m"], width=40, height=40), edge_margin=0.5)
    b2.place(Cell("m"))
    assert "held by lock" in b2.resolve(lock=[old]).step("m").note
