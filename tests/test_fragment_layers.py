"""A module's keepout on layers its own two-layer board does not have. The
declaration travels in the zone name, the one thing that survives KiCad's save
and pcb's stamp. Pure: no KiCad."""
from placemat.board_geometry import (RuleArea, layer_marker, resolve_marker, split_marker,
                                     stackup_order)
from placemat.values import CopperLayer

F, B, IN1, IN2 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1, CopperLayer.IN2
TWO, FOUR = (F, B), (F, IN1, IN2, B)


def test_every_copper_layer_is_marked_as_such():
    assert layer_marker(None, TWO) == " [*.Cu]"


def test_explicit_layers_the_board_lacks_are_listed_in_stackup_order():
    assert layer_marker((B, IN2, F, IN1), TWO) == " [F.Cu,In1.Cu,In2.Cu,B.Cu]"


def test_explicit_layers_the_board_has_need_no_marker():
    assert layer_marker((F, B), TWO) == ""
    assert layer_marker((IN2,), FOUR) == ""


def test_a_stamped_name_splits_into_base_and_declaration():
    """pcb layout appends `_1` after the marker."""
    assert split_marker("keepout clearance [*.Cu]_1") == ("keepout clearance", "*")
    assert split_marker("keepout clearance_c [In2.Cu]_1") == ("keepout clearance_c", (IN2,))
    assert split_marker("keepout vent") == ("keepout vent", None)


def test_an_unmarked_name_keeps_its_digits():
    """Without a marker there is no telling pcb's `_1` from a name that ends
    in a number: `keepout rail_1_26` is a real keepout, not `rail_1` stamped."""
    assert split_marker("keepout rail_1_26") == ("keepout rail_1_26", None)
    assert split_marker("keepout clearance_1") == ("keepout clearance_1", None)


def test_a_declaration_resolves_against_the_board_it_is_on():
    assert resolve_marker("*", FOUR) == (frozenset(FOUR), ())
    assert resolve_marker((IN2,), FOUR) == (frozenset((IN2,)), ())
    assert resolve_marker((IN2,), TWO) == (frozenset(), (IN2,))


def test_stackup_order_runs_front_inner_back():
    assert sorted((B, IN2, F, IN1), key=stackup_order) == [F, IN1, IN2, B]


def test_a_rule_area_names_its_base_and_what_it_could_not_honour():
    ra = RuleArea("keepout clearance_c [In2.Cu]_1", "rf", ((0, 0), (1, 0), (1, 1)),
                  frozenset(), frozenset(["fill"]), missing=(IN2,))
    assert ra.base == "keepout clearance_c" and ra.missing == (IN2,)


import dataclasses

import pytest

from placemat.layout import Board
from placemat.values import Location
from tests.fixtures import board_geometry


def _shape():
    from placemat.cutouts import Circle
    return Circle(4.0)


def _geom(copper, rule_areas=()):
    g = board_geometry([], width=40, height=40)
    return dataclasses.replace(g, layers=tuple(copper), rule_areas=tuple(rule_areas))


def test_the_clash_check_sees_a_stamped_marked_name_as_the_same_keepout():
    stamped = RuleArea("keepout clearance [*.Cu]_1", "rf", ((0, 0), (4, 0), (4, 4)),
                       frozenset(TWO), frozenset(["fill"]))
    b = Board(_geom(FOUR, [stamped]), edge_margin=0.0)
    with pytest.raises(ValueError):
        b.keepout(_shape(), "clearance", at=Location(20, 20), why="clearance")


def test_a_keepout_on_a_layer_the_board_lacks_is_a_finding():
    b = Board(_geom(TWO), edge_margin=0.0)
    b.keepout(_shape(), "clearance_c", at=Location(20, 20), layers=(IN2,), why="Detail C")
    plan = b.resolve()
    said = [f for f in plan.findings if "clearance_c" in f]
    assert said and "In2.Cu" in said[0] and "recorded in its name" in said[0]


def test_a_stamped_keepout_the_parent_cannot_honour_is_a_finding():
    stamped = RuleArea("keepout shield [In5.Cu]_1", "rf", ((0, 0), (4, 0), (4, 4)),
                       frozenset(), frozenset(["fill"]), missing=(CopperLayer.IN5,))
    plan = Board(_geom(FOUR, [stamped]), edge_margin=0.0).resolve()
    said = [f for f in plan.findings if "shield" in f]
    assert said and "In5.Cu" in said[0] and "rf" in said[0]


def test_the_docs_describe_the_marker():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "[*.Cu]" in api
    assert "## To 0.17" in Path("skills/placemat/references/migration.md").read_text()
