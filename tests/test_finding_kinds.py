"""A finding says what kind of thing went wrong, so a run can be scored by
kind: a part left unplaced, a link over its limit, a fixed item that is not
legal where it was put, copper that breaks a rule, a label on a part, an
escape crossed, closed or walled off, or something about the setup that is
the same every run."""
import pytest

from placemat.findings import KINDS, FindingCause as C
from tests.finding_samples import finding
from placemat.layout import Board
from placemat.values import Edge, LinkWeight, Location, Near, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board(**kw):
    fps = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("VIN", "OUT")),
           footprint("C1", 40, 40, inst="c1", nets=("VIN", "GND")),
           footprint("R1", 40, 45, inst="r1", nets=("OUT", "GND")),
           footprint("J1", 45, 10, w=4, h=4, inst="j1", nets=("OUT", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, **kw)


def kinds(plan):
    return {f.kind for f in plan.findings}


def test_a_finding_is_its_text_and_carries_its_kind():
    f = finding(C.LINK_OVER)
    assert f == "link A.1 to B.2 is 3.00 mm, over its 2.00 mm limit" and f.kind == "link_over"
    assert f.startswith("link") and "over its" in f
    assert set(KINDS) == {"unplaced", "link_over", "fixed", "copper", "label", "escape_crossed", "pair_crossed",
                          "escape_closed", "escape_walled", "escape_lane", "setup", "route", "vias", "fab", "facts",
                          "needs", "split", "time", "arrangement", "keep_out"}


def test_a_plan_takes_only_findings_that_say_their_cause():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    plan = b.resolve()
    with pytest.raises(TypeError):
        plan.findings.append("a bare sentence")
    plan.findings.append(finding(C.SETUP_UNDECLARED))


def test_a_link_over_its_limit():
    b = _board()
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("c1"), at=Location(40, 40))
    b.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=LinkWeight.SHORT, limit_mm=2.0)
    plan = b.resolve()
    assert [f.kind for f in plan.findings if "over its" in f] == ["link_over"]


def test_an_undeclared_part_is_setup():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    plan = b.resolve()
    assert {f.kind for f in plan.findings if "no declaration places it" in f} == {"setup"}


def test_a_part_with_no_room_is_unplaced():
    b = _board(keep_going=True)
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("j1"), at=Near(Location(30, 30), radius=0.5))      # nowhere legal within half a millimetre
    b.place(Part("c1"), at=Location(50, 50))
    b.place(Part("r1"), at=Location(50, 20))
    plan = b.resolve()
    assert [f.kind for f in plan.findings if f.startswith("j1")] == ["unplaced"]


def test_a_fixed_part_that_collides_is_fixed_when_the_run_carries_on():
    b = _board(keep_going=True)
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("c1"), at=Location(30, 30))
    b.place(Part("r1"), at=Location(50, 50))
    b.place(Part("j1"), at=Location(50, 20))
    plan = b.resolve()
    assert "fixed" in kinds(plan)


def test_a_label_on_a_part_is_label():
    b = _board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("c1"), at=Location(20, 17.2))                    # where a north label on u1 lands
    b.label(Part("u1"), "IN", side=Edge.NORTH, gap=0.3, reserve=False)
    b.place(Part("r1"), at=Location(50, 50))
    b.place(Part("j1"), at=Location(50, 20))
    plan = b.resolve()
    assert [f.kind for f in plan.findings if "sits on" in f] == ["label"]


def test_a_replayed_run_keeps_its_findings_kinds(tmp_path):
    from placemat import reuse as _reuse
    f = finding(C.LINK_OVER)
    g = _reuse.finding_from_json(_reuse.finding_to_json(f))
    assert g.kind == "link_over" and g.cause is C.LINK_OVER and g == f
