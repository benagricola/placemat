"""A part's keep-out is judged between copper sharing a copper layer, as KiCad's clearance is. A pair on
different layers is no failure; with no plane between them it is a notice. Pure: synthetic boards."""
import pytest

from placemat.board_geometry import CopperItem
from placemat.checks import keep_out, keep_out_notices
from placemat.values import Box, CopperLayer, Face
from tests.fixtures import board_geometry, footprint, rect

CITE = "datasheet rev B, section 10.2, layout example"
LIMIT = 2.0


def _parts(u_face=Face.FRONT, gap=0.7):
    """L1's SW pad on the front; U1's FB pad `gap` mm below it, on U1's face."""
    q = footprint("Q1", 14, 13, nets=("VIN", "SW"), fields={"Pm.Aggressor": "true"})
    l = footprint("L1", 20, 13, nets=("SW", "VOUT"), fields={"Pm.Aggressor": "true"})
    u = footprint("U1", 20.0, 13.5 + gap + 0.5, nets=("FB", "SW"), face=u_face,
                  fields={"Pm.Sensitive": "FB", "Pm.KeepOut": "%gmm pads=FB away=SW; %s" % (LIMIT, CITE)})
    return [q, l, u]


def _plane(layer=CopperLayer.IN1, net="GND"):
    outline = rect(20, 15, 30, 10)
    return CopperItem("zone", net, frozenset([layer]), (outline,), Box.of_points(outline))


def _via(net, x, y):
    outline = rect(x, y, 0.6, 0.6)
    return CopperItem("via", net, frozenset([CopperLayer.F, CopperLayer.B]), (outline,), Box.of_points(outline),
                      width_mm=0.6, anchors=((x, y),))


def _judge(parts, copper=()):
    geometry = board_geometry(parts, copper=list(copper))
    return keep_out(geometry, LIMIT), keep_out_notices(geometry, LIMIT)


def _sw(verdicts):
    return next(v for v in verdicts if v.subject == "SW")


def test_a_pair_on_one_layer_within_the_limit_fails():
    verdicts, notices = _judge(_parts())
    v = _sw(verdicts)
    assert v.ok is False and v.value == pytest.approx(0.7)
    assert notices == []


def test_a_pair_on_different_layers_with_a_plane_between_passes_and_is_not_reported():
    verdicts, notices = _judge(_parts(Face.BACK), [_plane()])
    assert all(v.ok is not False for v in verdicts)
    assert notices == []


def test_a_pair_on_different_layers_with_no_plane_passes_and_is_a_notice():
    verdicts, notices = _judge(_parts(Face.BACK))
    assert all(v.ok is not False for v in verdicts)
    (n,) = notices
    assert n.kind == "keep-out-cross-layer" and n.net == "SW"
    assert (n.away.kind, n.away.owner, n.pads.kind, n.pads.owner) == ("pad", "L1", "pad", "U1")
    assert n.layers == (CopperLayer.F, CopperLayer.B)
    assert n.distance_mm == pytest.approx(0.7) and n.limit_mm == pytest.approx(LIMIT)


def test_a_plane_not_between_the_layers_does_not_shield():
    verdicts, notices = _judge(_parts(Face.BACK), [_plane(CopperLayer.F)])
    assert len(notices) == 1


def test_a_pair_beyond_the_limit_is_no_notice():
    verdicts, notices = _judge(_parts(Face.BACK, gap=2.5))
    assert notices == []


def test_a_via_spanning_both_layers_within_the_limit_fails():
    # U1 on the back with a plane between; a SW via near its FB pad spans the pad's layer
    verdicts, notices = _judge(_parts(Face.BACK), [_plane(), _via("SW", 18.6, 15.0)])
    v = _sw(verdicts)
    assert v.ok is False and v.value < LIMIT
    assert "via" in v.note


def test_a_notice_is_a_notice_finding_with_its_facts():
    from placemat.checks import keep_out_findings
    from placemat.findings import FindingCause as C
    geometry = board_geometry(_parts(Face.BACK))
    (f,) = keep_out_findings(geometry, LIMIT)
    assert f.cause is C.KEEP_OUT_CROSS_LAYER and f.kind == "keep_out" and f.severity == "notice"
    assert f.facts["net"] == "SW" and f.facts["layers"] == ["F.Cu", "B.Cu"]
    assert f.facts["away"]["owner"] == "L1" and f.facts["pads"]["owner"] == "U1"
    assert f.facts["distance_mm"] == pytest.approx(0.7) and f.facts["limit_mm"] == LIMIT
    assert "L1 pad 1 (SW) on F.Cu" in f and "not a failed check" in f


def test_a_shielded_pair_raises_no_finding():
    from placemat.checks import keep_out_findings
    assert keep_out_findings(board_geometry(_parts(Face.BACK), copper=[_plane()]), LIMIT) == []
