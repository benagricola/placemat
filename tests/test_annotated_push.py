"""Pushes from part annotations: a part carrying Pm.Emits and a part carrying
Pm.Limit of one kind hold each other apart through board.push's machinery."""
import pytest

from placemat.layout import Board
from placemat.values import Cell, Face, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint

EMITS = "magnetic:3.2mT@13.5mm^3"
LIMIT = "magnetic:0.3mT"
RADIUS = 13.5 * (3.2 / 0.3) ** (1.0 / 3.0)      # ~29.7 mm


def _board(fps, width=60, height=60, **kw):
    return Board(board_geometry(fps, width=width, height=height), edge_margin=1.0, keep_going=True, **kw)


def _m1(x=10, y=10, **fields):
    return footprint("M1", x, y, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS, **fields})


def _u2(x=30, y=30, **fields):
    return footprint("U2", x, y, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT, **fields})


def _findings_of(plan, name):
    return [f for f in plan.findings if name in f]


def test_a_unit_mismatch_is_refused_when_the_run_starts_naming_both_parts():
    m1 = footprint("M1", 10, 10, inst="m1", fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 30, 30, inst="u2", fields={"Pm.Limit": "magnetic:500uT"})
    b = _board([m1, u2])
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(30, 30))
    with pytest.raises(ValueError) as e:
        b.resolve()
    assert "M1" in str(e.value) and "U2" in str(e.value)


def test_a_firm_sensitive_part_inside_the_hard_limit_is_refused_by_the_source():
    b = _board([_m1(), _u2(14, 10)])
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(14, 10))
    plan = b.resolve()
    found = _findings_of(plan, "u2")
    assert any("push from M1" in f and ("%.3g" % RADIUS) in f for f in found), found


def _landing_fps(annotated):
    m1 = footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND"),
                   fields={"Pm.Emits": "magnetic:3.2mT@2mm^3"} if annotated else None)
    u2 = footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"),
                   fields={"Pm.Limit": LIMIT} if annotated else None)
    j1 = footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))
    return [m1, u2, j1]


def _landing(annotated, pushed=True):
    b = _board(_landing_fps(annotated))
    b.place(Part("m1"), at=Location(10, 30))
    b.place(Part("j1"), at=Location(55, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    b.place(Part("u2"), radius=25.0, step=1.0)
    if pushed and not annotated:
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3)
    return b.resolve()


def test_an_annotated_pair_lands_where_the_equivalent_board_push_lands():
    by_hand, annotated = _landing(False), _landing(True)
    assert annotated.step("u2").placement == by_hand.step("u2").placement
    d = annotated.box("u2").center.distance(Location(10, 30))
    assert 3.2 * (2.0 / d) ** 3 <= 0.3 + 1e-6
    assert d > _landing(False, pushed=False).box("u2").center.distance(Location(10, 30))


def test_a_source_and_a_limit_of_different_kinds_do_not_pair():
    m1 = _m1()
    m1.fields["Pm.Emits"] = "heat:15C@5mm^1"
    b = _board([m1, _u2(14, 10)])
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(14, 10))
    plan = b.resolve()
    assert not _findings_of(plan, "u2")
    assert not plan.pushes


def test_members_of_one_cell_do_not_pair():
    fps = [footprint("M1", 10, 10, w=2, h=2, inst="sensor.m1", nets=("A", "GND"), cell="sensor",
                     fields={"Pm.Emits": EMITS}),
           footprint("U2", 14, 10, w=2, h=2, inst="sensor.u2", nets=("SIG", "GND"), cell="sensor",
                     fields={"Pm.Limit": LIMIT})]
    b = Board(board_geometry(fps, cells=["sensor"], width=60, height=60), edge_margin=1.0)
    b.place(Cell("sensor"), at=Location(12, 10))
    plan = b.resolve()
    assert not plan.pushes
    assert plan.step("sensor").placement is not None
