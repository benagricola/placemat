"""A pair: two nets drawn together at a set gap along one centreline, the
way KiCad's differential tool draws them. Corners are chamfered at 45, each
track leaves its pad at 45 to join its line, and a lead that would cross the
partner on the pair's layer goes over the other face from a via stepped
clear of the partner."""
import math

import pytest

from placemat.copper import Track, Via, pair_ops
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, Part, PadRef
from tests.fixtures import board_geometry, footprint

B = CopperLayer.B
W, GAP = 0.2, 0.35
PITCH = W + GAP


def end(px, py, nx, ny, through=True):
    return (Location(px, py), Location(nx, ny), through, through)


def tracks(ops, net, layer=None):
    return [t for t in ops if isinstance(t, Track) and t.net == net and (layer is None or t.layer is layer)]


def test_the_two_tracks_run_at_the_gap_either_side_of_the_centreline():
    ops = pair_ops("P", "N", B, W, GAP, end(4, -3, 6, -3), [(5, 0), (5, 20)], end(4, 23, 6, 23),
                   via_drill=0.3, via_size=0.6)
    p_run = [t for t in tracks(ops, "P") if t.start.y == 0 and t.end.y == 20][0]
    n_run = [t for t in tracks(ops, "N") if t.start.y == 0 and t.end.y == 20][0]
    assert p_run.start.x == pytest.approx(5 - PITCH / 2) and n_run.start.x == pytest.approx(5 + PITCH / 2)
    assert all(t.width == W for t in tracks(ops, "P") + tracks(ops, "N"))


def test_a_track_leaves_its_pad_at_45_then_runs_straight_to_its_line():
    ops = pair_ops("P", "N", B, W, GAP, end(4, -3, 6, -3), [(5, 0), (5, 20)], end(4, 23, 6, 23),
                   via_drill=0.3, via_size=0.6)
    lead = [t for t in tracks(ops, "P") if t.start == Location(4, -3)][0]
    dx, dy = lead.end.x - lead.start.x, lead.end.y - lead.start.y
    assert abs(abs(dx) - abs(dy)) < 1e-9                  # the first leg is a 45
    assert lead.end.x == pytest.approx(5 - PITCH / 2)      # and it lands on P's line


def test_a_corner_is_chamfered_and_the_offsets_stay_at_the_pitch():
    # P starts north of an eastward run and turns south with it, so it ends on the east: the outer track
    ops = pair_ops("P", "N", B, W, GAP, end(-3, -1, -3, 1), [(0, 0), (10, 0), (10, 10)], end(11, 13, 9, 13),
                   via_drill=0.3, via_size=0.6, chamfer=1.0)
    p, n = tracks(ops, "P"), tracks(ops, "N")
    diag_p = [t for t in p if abs(abs(t.end.x - t.start.x) - abs(t.end.y - t.start.y)) < 1e-9 and t.start.x > 5]
    diag_n = [t for t in n if abs(abs(t.end.x - t.start.x) - abs(t.end.y - t.start.y)) < 1e-9 and t.start.x > 5]
    assert diag_p and diag_n                                # both tracks turn the corner at 45
    lp = diag_p[0].start.distance(diag_p[0].end)
    ln = diag_n[0].start.distance(diag_n[0].end)
    assert abs(lp - ln) == pytest.approx(2 * PITCH * math.tan(math.pi / 8), abs=1e-6)   # inner short, outer long: two 45 turns
    horiz_p = [t for t in p if t.start.y == t.end.y and t.start.x < 5 < t.end.x][0]
    horiz_n = [t for t in n if t.start.y == t.end.y and t.start.x < 5 < t.end.x][0]
    assert abs(horiz_p.start.y - horiz_n.start.y) == pytest.approx(PITCH)


def test_a_lead_that_would_cross_the_partner_goes_over_the_other_face_from_a_stepped_via():
    # pads in line with the run, east of it: the inner track's lead must cross the outer's line
    ops = pair_ops("P", "N", B, W, GAP, end(8, 2, 8, -2), [(5, 0), (5, 20)], end(8, 22, 8, 18),
                   via_drill=0.3, via_size=0.6, via_step=0.4)
    inner = "N" if any(t.start.x < 5 for t in tracks(ops, "N") if t.start.y == 0) else "P"
    outer = "P" if inner == "N" else "N"
    vias = [v for v in ops if isinstance(v, Via) and v.net == inner]
    assert len(vias) == 2                                   # one per end
    other = tracks(ops, inner, B.other_face)
    assert other and all(t.start.y <= 0 or t.start.y >= 18 for t in other)     # the leads only
    inner_x, outer_x = 5 - PITCH / 2, 5 + PITCH / 2                            # the inner line is the west one
    assert all(abs(v.at.x - inner_x) == pytest.approx(0.4) for v in vias)       # stepped away from the partner
    assert all(abs(v.at.x - outer_x) > abs(inner_x - outer_x) for v in vias)


def test_an_smd_pad_on_the_other_face_gets_a_via_at_its_line():
    ops = pair_ops("P", "N", B, W, GAP, end(4, -3, 6, -3), [(5, 0), (5, 20)],
                   (Location(4, 23), Location(6, 23), False, False), via_drill=0.3, via_size=0.6, end_faces=(B.other_face, B.other_face))
    vias = [v for v in ops if isinstance(v, Via)]
    assert {v.net for v in vias} == {"P", "N"}
    assert tracks(ops, "P", B.other_face) and tracks(ops, "N", B.other_face)


def test_a_board_pair_takes_its_geometry_from_the_diff_pair_class():
    fps = [footprint("H1", 10, 10, w=4, h=2, inst="h1", nets=("CAN_P", "CAN_N"), through=True),
           footprint("H2", 10, 40, w=4, h=2, inst="h2", nets=("CAN_P", "CAN_N"), through=True)]
    b = Board(board_geometry(fps, width=50, height=60), edge_margin=1.0)
    b.place(Part("h1"), at=Location(10, 10))
    b.place(Part("h2"), at=Location(10, 40))
    p1, n1 = PadRef(Part("h1"), "CAN_P"), PadRef(Part("h1"), "CAN_N")
    p2, n2 = PadRef(Part("h2"), "CAN_P"), PadRef(Part("h2"), "CAN_N")
    b.pair(Net("CAN_P"), Net("CAN_N"), [(p1, n1), (10, 14), (10, 36), (p2, n2)], layer=B, width=0.2, gap=0.35)
    plan = b.resolve()
    assert tracks(plan.copper, "CAN_P") and tracks(plan.copper, "CAN_N")
    assert plan.step("pair CAN_P/CAN_N").kind == "copper"
