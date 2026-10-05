import dataclasses

import pytest

from placemat.layout import Board, CriticalUnplaced
from placemat.settings import Settings
from placemat.values import Cell, Location, Part
from tests.arrangement_support import east_doc, stamped_geometry, with_arrangement


def board(settings=None, g=None):
    return Board(g or with_arrangement(), edge_margin=0.0, keep_going=True, settings=settings or Settings())


def test_one_id_lays_that_arrangement_and_default_holds_the_modules_own_layout():
    b = board(g=with_arrangement(doc=east_doc(ops=[])))     # no copper: the placement centres the cell's box, plan.box its members'
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.east")
    plan = b.resolve()
    p = plan.placement("mod")
    assert p.arrangement == "c_in.east"
    assert plan.occupancy.items["C1"].reference.rotation == 180.0 and abs(plan.box("mod").center.x - 40.0) < 1e-3
    held = board()
    held.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="default")
    plan2 = held.resolve()
    assert plan2.placement("mod").arrangement == "" and plan2.occupancy.items["C1"].reference.rotation == 0.0


def test_a_part_cannot_take_arrangements():
    b = board()
    with pytest.raises(TypeError):
        b.place(Part("R9"), at=Location(5, 5), arrangements="x")


def test_an_id_the_cell_does_not_offer_leaves_it_unplaced_with_the_ids_offered():
    b = board()
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.west")
    plan = b.resolve()
    assert plan.step("mod").placement is None
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.facts == {"item": "mod", "asked": ["c_in.west"], "offered": ["default", "c_in.east"]}


def test_missing_stops_the_run_with_required():
    b = Board(with_arrangement(), edge_margin=0.0)
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.west", required=True)
    with pytest.raises(CriticalUnplaced):
        b.resolve()


def test_the_switch_off_offers_the_default_only():
    off = dataclasses.replace(Settings(), place_arrangements=False)
    b = board(off)
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.east")
    plan = b.resolve()
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.facts["offered"] == ["default"]
    ok = board(off)
    ok.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="default")
    assert ok.resolve().placement("mod").arrangement == ""


def test_a_cell_declared_without_arrangements_places_as_it_did():
    plain = Board(stamped_geometry(), edge_margin=0.0, keep_going=True)
    plain.place(Cell("mod"), at=Location(40.0, 30.0))
    with_note = board()
    with_note.place(Cell("mod"), at=Location(40.0, 30.0))
    assert plain.resolve().placement("mod") == with_note.resolve().placement("mod")      # nothing pulls it: the default


def test_a_missing_arrangement_is_critical_on_the_unplaced_step_and_a_warning_from_the_lock():
    b = board()
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.west")
    plan = b.resolve()
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.severity == "critical"
    lock = b._arrangement_missing("mod", ["c_in.west"], ["default", "c_in.east"], source="lock")
    assert lock.severity == "warning" and lock.facts["source"] == "lock"


def test_the_unplaced_step_says_what_was_asked_and_what_is_offered():
    from placemat import step_text
    b = board()
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements=["c_in.west", "default"])
    step = b.resolve().step("mod")
    text = step_text.unplaced_text(step.unplaced)
    assert "c_in.west" in text and "c_in.east" in text


def test_the_run_record_carries_an_arrangement_only_when_not_the_default():
    from placemat.runner import placements_record
    b = board()
    b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements="c_in.east")
    b.place(Part("R9"), at=Location(5, 5))
    rec = placements_record(b.resolve())
    assert rec["mod"]["arrangement"] == "c_in.east" and "arrangement" not in rec["r9"]


def test_offered_reads_the_base_cell_and_is_empty_for_an_arranged_one():
    b = board()
    base = b.geometry.cells["mod"]
    assert b._offered(base) == ("c_in.east",)
    assert b._offered(base.arranged("c_in.east")) == ()


def riding(arrangements):
    """`mod` rides r9, which is searched: the cell is laid with r9, never settled on its own."""
    from placemat.values import Beside, Edge, Near
    b = board()
    b.place(Part("r9"), at=Near(Location(20.0, 30.0)))
    b.place(Cell("mod"), at=Beside(Part("r9"), Edge.EAST), arrangements=arrangements)
    plan = b.resolve()
    assert [r.key for r in b._ride_groups["r9"]] == ["mod"]
    return plan


def test_a_riding_cell_pinned_to_an_offered_id_stands_in_it():
    plan = riding("c_in.east")
    assert plan.placement("mod").arrangement == "c_in.east"
    assert plan.occupancy.items["C1"].reference.rotation == 180.0
    assert not [f for f in plan.findings if f.cause == "arrangement.missing"]


def test_a_riding_cell_pinned_to_an_id_not_offered_is_unplaced_with_the_finding():
    plan = riding("c_in.west")
    assert plan.step("mod").placement is None and plan.placement("r9") is not None
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.facts == {"item": "mod", "asked": ["c_in.west"], "offered": ["default", "c_in.east"]} and f.severity == "critical"


@pytest.mark.parametrize("value", [(), [], "x"])
def test_any_arrangements_on_a_part_is_refused(value):
    with pytest.raises(TypeError, match="arrangements="):
        board().place(Part("R9"), at=Location(5, 5), arrangements=value)


def test_arrangements_that_is_not_text_or_a_sequence_is_refused_by_name():
    with pytest.raises(TypeError, match="mod: arrangements="):
        board().place(Cell("mod"), at=Location(40.0, 30.0), arrangements=5)


@pytest.mark.parametrize("value", ["", ["c_in.east", ""]])
def test_an_empty_id_is_refused(value):
    with pytest.raises(TypeError, match="mod: arrangements="):
        board().place(Cell("mod"), at=Location(40.0, 30.0), arrangements=value)


def test_repeated_ids_are_kept_once_in_their_order():
    b = board()
    i = b.place(Cell("mod"), at=Location(40.0, 30.0), arrangements=["c_in.east", "default", "c_in.east"])
    assert i.arrangements == ("c_in.east", "default")
    one = board()
    one.place(Cell("mod"), at=Location(40.0, 30.0), arrangements=("c_in.east", "c_in.east"))
    assert one.resolve().placement("mod").arrangement == "c_in.east"


def test_a_required_riding_cell_pinned_to_an_id_not_offered_stops_the_run():
    from placemat.values import Beside, Edge, Near
    b = Board(with_arrangement(), edge_margin=0.0)
    b.place(Part("r9"), at=Near(Location(20.0, 30.0)))
    b.place(Cell("mod"), at=Beside(Part("r9"), Edge.EAST), arrangements="c_in.west", required=True)
    with pytest.raises(CriticalUnplaced):
        b.resolve()


def test_a_part_riding_a_cell_left_unplaced_for_its_arrangement_is_unplaced_as_a_rider():
    from placemat.values import Beside, Edge, Near
    b = board(g=with_arrangement(stamped_geometry(partner=(60.0, 50.0))))
    b.place(Part("r9"), at=Near(Location(20.0, 30.0)))
    b.place(Cell("mod"), at=Beside(Part("r9"), Edge.EAST), arrangements="c_in.west")
    b.place(Part("r8"), at=Beside(Cell("mod"), Edge.SOUTH))
    plan = b.resolve()
    assert [r.key for r in b._ride_groups["r9"]] == ["mod", "r8"]
    assert plan.placement("r9") is not None and plan.step("mod").placement is None
    step = plan.step("r8")
    assert step.placement is None and step.unplaced == ({"form": "rides", "rider_of": "mod"},)
    (f,) = [f for f in plan.findings if f.cause == "unplaced.rides"]
    assert f.facts == {"item": "r8", "variant": "rode", "rider_of": "mod"}
    keys = [s.item for s in plan.steps]
    assert keys.index("mod") < keys.index("r8")


def test_a_riding_cell_left_unplaced_for_its_arrangement_steps_in_its_ride_order():
    from placemat.values import Beside, Edge, Near
    b = board(g=with_arrangement(stamped_geometry(partner=(60.0, 50.0))))
    b.place(Part("r9"), at=Near(Location(20.0, 30.0)))
    b.place(Part("r8"), at=Beside(Part("r9"), Edge.NORTH))
    b.place(Cell("mod"), at=Beside(Part("r8"), Edge.EAST), arrangements="c_in.west")
    plan = b.resolve()
    assert [r.key for r in b._ride_groups["r9"]] == ["r8", "mod"]
    keys = [s.item for s in plan.steps]
    assert plan.placement("r8") is not None and keys.index("r8") < keys.index("mod")


@pytest.mark.parametrize("rotation", [0, 90])
def test_a_pin_by_a_members_origin_lands_the_arranged_member_on_the_point(rotation):
    from placemat.values import Pin
    b = board(g=with_arrangement(doc=east_doc(ops=[])))
    b.place(Cell("mod"), at=Pin(Part("mod.c_in"), 60.0, 30.0), rotation=rotation, arrangements="c_in.east")
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    at = plan.occupancy.items["C1"].reference
    assert (at.location.x, at.location.y) == pytest.approx((60.0, 30.0), abs=1e-6)
    assert at.rotation == pytest.approx((180.0 + rotation) % 360.0)


@pytest.mark.parametrize("rotation", [0, 90])
def test_a_pin_by_a_members_pad_with_a_local_offset_turns_the_offset_with_the_arranged_member(rotation):
    """PadRef.local is in the member's own frame: c_in.east turns c_in half way round, so the offset turns with it."""
    from placemat.values import PadRef, Pin
    b = board(g=with_arrangement(doc=east_doc(ops=[])))
    b.place(Cell("mod"), at=Pin(PadRef(Part("mod.c_in"), 1).local(1.0, 0.0), 60.0, 30.0), rotation=rotation,
            arrangements="c_in.east")
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    pad = plan.occupancy.pad_location("C1", "1")
    member = plan.occupancy.items["C1"].reference.rotation          # the member's own turn: 180 plus the cell's
    from placemat.lock import _turn
    vx, vy = _turn(1.0, 0.0, member)
    assert (pad.x + vx, pad.y + vy) == pytest.approx((60.0, 30.0), abs=1e-6)


def test_a_stale_note_is_a_finding_only_with_the_switch_on():
    g = with_arrangement()
    stale = dataclasses.replace(g.cells["mod"], arrangement_problems=({"reason": "version", "ids": ["c_in.west"]},))
    g = dataclasses.replace(g, cells={**g.cells, "mod": stale})
    for on, want in ((True, 1), (False, 0)):
        b = board(dataclasses.replace(Settings(), place_arrangements=on), g=g)
        b.place(Cell("mod"), at=Location(40.0, 30.0))
        assert len([f for f in b.resolve().findings if f.cause == "arrangement.stale"]) == want, on
