"""The lock file: accepted decisions as anchor-relative entries a run
applies deterministically, drifting or releasing with a note when the
script changes under them."""
import math

from placemat import lock
from placemat.explore import Explore
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint

FOCUS = frozenset({"r1", "r2", "r3", "c1"})


def _board(mcu=(25, 25, 0), extra=(), c1_rotation=None, after=None, cleanup=True, wall_rotation=0):
    fps = [footprint("U1", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B")),
           footprint("R1", 60, 60, w=2, h=1, inst="r1", nets=("A", "X")),
           footprint("R2", 60, 62, w=2, h=1, inst="r2", nets=("B", "Y")),
           footprint("R3", 60, 64, w=2, h=1, inst="r3", nets=("A", "Z")),
           footprint("C1", 60, 66, w=2, h=1, inst="c1", nets=("B", "Q")),
           footprint("W1", 70, 70, w=2, h=1, inst="wall", nets=("W", "V")),
           footprint("R9", 70, 75, w=2, h=1, inst="late", nets=("Q", "V"))]
    import dataclasses
    from placemat.settings import Settings
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0,
              settings=dataclasses.replace(Settings(), cleanup_enabled=cleanup))
    b.place(Part("mcu"), at=Location(mcu[0], mcu[1]), rotation=mcu[2])
    for x, y in extra:
        b.place(Part("wall"), at=Location(x, y), rotation=wall_rotation)
    for k in ("r1", "r2", "r3"):
        b.place(Part(k))
    b.place(Part("c1"), **({"rotation": c1_rotation} if c1_rotation is not None else {}))
    if after:
        b.place(Part("late"))
    return b


def _where(plan, keys=("r1", "r2", "r3", "c1")):
    out = {}
    for s in plan.steps:
        if s.item in keys and s.placement is not None:
            out[s.item] = (round(s.placement.location.x, 4), round(s.placement.location.y, 4), s.placement.rotation)
    return out


def _accepted(seed=9):
    b = _board()
    plan = b.resolve(explore=Explore(seed=seed, focus=FOCUS))
    return plan, lock.entries(b, plan, sorted(FOCUS))


def test_entries_round_trip_through_the_file(tmp_path):
    _, entries = _accepted()
    path = tmp_path / "Board_layout.lock.json"
    lock.write(path, entries)
    assert lock.read(path) == sorted(entries, key=lambda e: e.key)


def test_a_run_with_the_lock_reproduces_the_accepted_placements():
    variant, entries = _accepted()
    assert _where(_board().resolve(lock=entries)) == _where(variant)
    assert all("held by lock" in s.note for s in _board().resolve(lock=entries).steps if s.item in FOCUS)


def test_moving_and_turning_the_anchor_part_carries_a_locked_item_with_it():
    b = _board(cleanup=False)
    variant = b.resolve(explore=Explore(seed=9, focus=FOCUS))
    entries = lock.entries(b, variant, sorted(FOCUS))
    e = next(e for e in entries if e.key == "r1")
    moved = _board(mcu=(22, 28, 90), cleanup=False).resolve(lock=entries)
    g_old, g_new = variant.occupancy, moved.occupancy
    a_old = g_old.pad_location(*e.anchor); a_new = g_new.pad_location(*e.anchor)
    r_old = g_old.items["R1"].reference.location; r_new = g_new.items["R1"].reference.location
    d_old = (r_old.x - a_old.x, r_old.y - a_old.y)
    d_new = (r_new.x - a_new.x, r_new.y - a_new.y)
    assert math.hypot(*d_old) == __import__("pytest").approx(math.hypot(*d_new), abs=1e-6)
    assert "held by lock" in moved.step("r1").note


def test_a_blocked_spot_drifts_and_says_so():
    variant, entries = _accepted()
    at = variant.turns["r1"]["placement"]                  # the locked spot: a part R1's size sits on it
    plan = _board(extra=[(at.location.x, at.location.y)], wall_rotation=at.rotation).resolve(lock=entries)
    assert plan.placement("r1") is not None
    assert "lock: drifted" in plan.step("r1").note


def test_a_changed_declaration_releases_its_entry():
    _, entries = _accepted()
    plan = _board(c1_rotation=90).resolve(lock=entries)
    assert "lock: released" in plan.step("c1").note and "declaration" in plan.step("c1").note
    assert "held by lock" in plan.step("r1").note


def test_an_edit_below_leaves_a_locked_item_where_it_was():
    variant, entries = _accepted()
    assert _where(_board(after=True).resolve(lock=entries)) == _where(variant)


def test_the_lock_is_in_the_reuse_key():
    plain = _board().resolve()
    _, entries = _accepted()
    locked = _board().resolve(reuse=plain.reuse, lock=entries)
    changed = [s.item for s in locked.steps if s.item in FOCUS and s.placement != plain.placement(s.item)]
    assert locked.reuse["first_change"] in FOCUS
    again = _board().resolve(reuse=locked.reuse, lock=entries)
    assert again.reuse["reused"] == len(again.reuse["steps"])


def test_a_locked_block_is_held_with_its_satellites():
    fps = [footprint("U1", 10, 10, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C1", 60, 60, inst="cin", nets=("VIN", "GND")),
           footprint("J1", 5, 5, w=8, h=3, inst="j1", nets=("VIN", "GND"))]

    def make():
        b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
        b.place(Part("j1"), at=Location(10, 50))
        b.place(b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")]))
        return b
    b = make()
    variant = b.resolve(explore=Explore(seed=3, focus=frozenset({"block ldo"})))
    entries = lock.entries(b, variant, ["block ldo"])
    held = make().resolve(lock=entries)
    assert held.placement("block ldo") == variant.placement("block ldo")
    assert held.placement("cin") == variant.placement("cin")
    assert "held by lock" in held.step("block ldo").note
