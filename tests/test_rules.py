"""Design rules the script declares are written as KiCad custom rules beside
the board, where its DRC reads them: a clearance inside one cell, between
two nets, or on one net."""
from placemat.layout import Board
from placemat.rules import Rule, rules_text
from placemat.values import Cell, Net, Part
from tests.fixtures import board_geometry, footprint


def test_a_clearance_declared_within_a_cell_between_nets_or_on_a_net_reads_as_kicad_rules():
    fps = [footprint("U1", 10, 10, cell="tmc", inst="tmc.u", nets=("A", "GND")),
           footprint("R1", 30, 10, nets=("V48", "GND"))]
    b = Board(board_geometry(fps, cells=["tmc"]), edge_margin=1.0)
    b.rule(clearance=0.2, within=Cell("tmc"), why="0.5 mm TQFP pitch cannot meet the class between adjacent pads")
    b.rule(clearance=0.6, between=(Net("V48"), Net("GND")), why="48 V to ground")
    b.rule(clearance=0.4, on=Net("V48"), why="the bus")
    plan = b.resolve()
    assert [r.min_mm for r in plan.rules] == [0.2, 0.6, 0.4]
    text = rules_text(plan.rules)
    assert text.startswith("(version 1)")
    assert "(condition \"A.memberOf('tmc') && B.memberOf('tmc')\")" in text
    assert "(constraint clearance (min 0.2mm))" in text
    assert "(A.NetName == 'V48' && B.NetName == 'GND') || (A.NetName == 'GND' && B.NetName == 'V48')" in text
    assert "(condition \"A.NetName == 'V48'\")" in text
    assert "48 V to ground" in text                          # the why is the rule's name


def test_a_rule_needs_exactly_one_scope_and_a_known_cell_or_net():
    import pytest
    fps = [footprint("R1", 30, 10, nets=("V48", "GND"))]
    b = Board(board_geometry(fps), edge_margin=1.0)
    with pytest.raises(ValueError):
        b.rule(clearance=0.2, why="no scope")
    with pytest.raises(ValueError):
        b.rule(clearance=0.2, on=Net("V48"), between=(Net("V48"), Net("GND")), why="two scopes")
    with pytest.raises(KeyError):
        b.rule(clearance=0.2, on=Net("NOPE"), why="unknown net")
    with pytest.raises(KeyError):
        b.rule(clearance=0.2, within=Cell("nope"), why="unknown cell")
