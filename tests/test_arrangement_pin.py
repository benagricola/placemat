import dataclasses

import pytest

from placemat.layout import Board, CriticalUnplaced
from placemat.settings import Settings
from placemat.values import Cell, Location, Part
from tests.arrangement_support import stamped_geometry, with_arrangement


def board(settings=None, g=None):
    return Board(g or with_arrangement(), edge_margin=0.0, keep_going=True, settings=settings or Settings())


def test_one_id_lays_that_arrangement_and_default_holds_the_modules_own_layout():
    b = board()
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
