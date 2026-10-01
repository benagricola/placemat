"""A label never costs a searched item its place: the search does not see
labels, and once the item is down the labels it meets give way as they do for
a firm part - or are a finding when they have nowhere to go. Other items'
silk and pads stay obstacles. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.copper import Text
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Along, Edge, Location, Near, Part
from tests.fixtures import board_geometry, footprint

SILK = 0.2


def texts(plan):
    return [op for op in plan.copper if isinstance(op, Text)]


def make_board(room_south=True, surround=False, j1_silk=(), **kw):
    """J1 (x 1..7, y 5..9) on a keep-in of x 1..7: the strip above J1 is 4 mm
    deep and 6 wide, and C1 (2 x 3.5) fits in it only where J1's label (4.4
    wide, centred on J1) is not kept clear. `room_south` leaves the label room
    below J1; `surround` instead walls in its other three sides."""
    size = (4.4 - 0.15) / (5 * 0.914 + 2 / 9)
    wide = surround
    cx = 10 if wide else 4
    fps = [footprint("J1", cx, 7, w=6, h=4, inst="j1", nets=("A", "B"), silk_boxes=j1_silk),
           footprint("C1", cx, 3, w=2, h=3.5, inst="c1", nets=("C", "D"),
                     silk_boxes=((cx - 1, 1.25, cx + 1, 4.75),))]
    if surround:
        fps += [footprint("RW", 4.2, 7, w=4.4, h=4, inst="rw", nets=("E", "F")),
                footprint("RE", 15.8, 7, w=4.4, h=4, inst="re", nets=("G", "H")),
                footprint("RS", 10, 10.2, w=6, h=2, inst="rs", nets=("I", "J"))]
    b = Board(board_geometry(fps, width=20 if wide else 8, height=12 if room_south or surround else 10,
                             silk_clearance=SILK),
              edge_margin=1.0, settings=dataclasses.replace(Settings(), place_envelope="physical"), **kw)
    b.place(Part("j1"), at=Location(cx, 7))
    b.label(Part("j1"), "USB-C", side=Edge.NORTH, align=Along.MID, size=size)
    for ref, at in (("rw", (4.2, 7)), ("re", (15.8, 7)), ("rs", (10, 10.2))) if surround else ():
        b.place(Part(ref), at=Location(*at))
    b.place(Part("c1"), at=Near(Location(cx, 3), radius=3.0), rotations=(0.0,))
    return b


def test_a_searched_part_places_where_a_label_was_kept_clear_and_the_label_moves():
    plan = make_board().resolve()
    assert plan.placement("c1").location == Location(4.0, 3.0)
    (t,) = texts(plan)
    assert t.side is Edge.SOUTH
    assert "moved from north MID to south MID: C1 was there" in plan.step("label j1 USB-C").note
    assert not [f for f in plan.findings if f.kind in ("unplaced", "label")], list(plan.findings)


def test_a_label_with_nowhere_to_go_is_a_finding_and_the_part_still_places():
    plan = make_board(surround=True, keep_going=True).resolve()
    assert plan.placement("c1") is not None
    (t,) = texts(plan)
    assert t.side is Edge.NORTH
    said = [str(f) for f in plan.findings if "label j1 USB-C" in str(f) and "no clear spot" in str(f)]
    assert said and "C1" in said[0], list(plan.findings)
    assert not [f for f in plan.findings if f.kind == "unplaced"], list(plan.findings)


def test_a_searched_part_still_keeps_off_another_items_silk():
    plan = make_board(j1_silk=((1, 3, 7, 5),), keep_going=True).resolve()
    assert plan.placement("c1") is None
    assert [f for f in plan.findings if f.kind == "unplaced" and f.startswith("c1")], list(plan.findings)


def test_a_replayed_run_ends_with_the_label_and_part_where_the_fresh_run_put_them():
    first = make_board().resolve()
    again = make_board().resolve(reuse=first.reuse)
    assert again.reuse["reused"] > 0
    assert texts(again) == texts(first)
    assert again.placements == first.placements
    assert again.step("label j1 USB-C").note == first.step("label j1 USB-C").note
    assert again.findings == first.findings


def test_the_native_sweep_leaves_labels_out_as_the_python_one_does(monkeypatch):
    from placemat import geometry, placer
    if geometry._native is None:
        pytest.skip("no native module")
    runs = {}
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        plan = make_board().resolve()
        runs[on] = (plan.placements, texts(plan), plan.step("label j1 USB-C").note, list(plan.findings))
    assert runs[True] == runs[False]
    assert runs[True][0]["c1"].location == Location(4.0, 3.0)
