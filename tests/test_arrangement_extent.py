from placemat import arrangement_run as run
from placemat.values import Beside, Box, Edge, Location, Near, Part
from tests.arrangement_support import module


def test_the_members_that_set_the_outline_are_listed_with_how_far_they_stand_past_the_next():
    boxes = {"a": Box(0.0, 0.0, 10.0, 4.0), "b": Box(2.0, 1.0, 6.0, 3.0), "c": Box(7.0, -1.8, 9.0, 3.0)}
    assert run.extent_from_boxes(boxes) == [
        {"item": "a", "sides": ["east", "south", "west"], "protrudes_mm": 2.0},      # west: a at 0, the next edge at 2
        {"item": "c", "sides": ["north"], "protrudes_mm": 1.8}]                       # north: c at -1.8, the next edge at 0


def test_a_lone_member_reaches_every_side_and_protrudes_nothing():
    (g,) = run.extent_from_boxes({"a": Box(0.0, 0.0, 2.0, 1.0)})
    assert g["sides"] == ["north", "east", "south", "west"] and g["protrudes_mm"] == 0.0


def test_a_module_that_declares_alternatives_notes_each_extent_member_with_none():
    b = module()
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    extent = [{"item": "c_in", "sides": ["west"], "protrudes_mm": 0.4}, {"item": "r_pull", "sides": ["east"], "protrudes_mm": 0.1}]
    found = run.extent_findings(b, extent, 2.0)
    assert [f.facts["item"] for f in found] == ["r_pull"] and found[0].severity == "notice"
    assert found[0].facts == {"item": "r_pull", "sides": ["east"], "protrudes_mm": 0.1, "alternatives": True}


def test_a_module_that_declares_none_notes_only_what_protrudes_past_the_setting():
    b = module()
    extent = [{"item": "c_in", "sides": ["west"], "protrudes_mm": 2.5}, {"item": "r_pull", "sides": ["east"], "protrudes_mm": 1.9}]
    found = run.extent_findings(b, extent, 2.0)
    assert [f.facts["item"] for f in found] == ["c_in"] and found[0].facts["alternatives"] is False


def test_the_extent_of_a_resolved_plan_names_instances():
    plan = module().resolve()
    got = run.extent_of(plan)
    assert {g["item"] for g in got} <= {"u1", "c_in", "r_pull"} and got and all(g["sides"] for g in got)
