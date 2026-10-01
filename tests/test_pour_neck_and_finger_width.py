"""board.pour(net, [PadRef(a), PadRef(b)]) draws the neck, as declared (swallow_pads changes nothing for two pads),
between two pads instead of needing a third point, as wide as the narrower
pad across the run unless width= says otherwise; board.finger(...,
width=PadRef(...)) runs as wide as that pad across the run. Pure."""
import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Pour
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Face, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, pad


def _one_pad_part(ref, inst, net, cx, cy, w, h):
    p = pad(ref, inst, 1, net, cx, cy, w, h)
    body = Box(cx - w / 2 - 0.5, cy - h / 2 - 0.5, cx + w / 2 + 0.5, cy + h / 2 + 0.5)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _board():
    pa = _one_pad_part("PA", "pa", "V48", 20.0, 20.0, 2.0, 2.0)
    pb = _one_pad_part("PB", "pb", "V48", 26.0, 20.0, 1.0, 1.0)
    return Board(board_geometry([pa, pb], width=60, height=60), edge_margin=1.0)


def _points(plan):
    (p,) = [o for o in plan.copper if isinstance(o, Pour)]
    return p


def test_a_pour_between_two_pads_needs_no_third_point():
    b = _board()
    b.pour(Net("V48"), [PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], layer=CopperLayer.F)
    plan = b.resolve()
    p = _points(plan)
    xs = sorted({round(x, 6) for x, _ in p.points})
    ys = sorted({round(y, 6) for _, y in p.points})
    assert xs == [20.0, 26.0]
    # as wide as the narrower pad (PB, 1.0 mm across the horizontal run), centred on the line
    assert ys == [19.5, 20.5]


def test_a_pour_necks_width_may_be_given_explicitly():
    b = _board()
    b.pour(Net("V48"), [PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], layer=CopperLayer.F, swallow_pads=True,
          width=4.0)
    plan = b.resolve()
    p = _points(plan)
    ys = sorted({round(y, 6) for _, y in p.points})
    assert ys == [18.0, 22.0]


def test_a_pour_of_two_non_pad_points_still_needs_a_third():
    b = _board()
    with pytest.raises(ValueError, match="3 or more points"):
        b.pour(Net("V48"), [Location(0, 0), Location(5, 5)], layer=CopperLayer.F)


def test_a_two_pad_pour_with_swallow_pads_and_width_is_the_neck_as_declared():
    """Nothing is fitted, nothing cut; foreign copper in it is a finding."""
    b = _board()
    b.pour(Net("V48"), [PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], layer=CopperLayer.F, swallow_pads=True, width=1.0)
    p = _points(b.resolve())
    assert not p.fitted
    assert p.points == ((20.0, 20.5), (26.0, 20.5), (26.0, 19.5), (20.0, 19.5))


def test_a_two_pad_pour_with_swallow_pads_and_no_width_is_fitted():
    b = _board()
    b.pour(Net("V48"), [PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], layer=CopperLayer.F, swallow_pads=True)
    p = _points(b.resolve())
    assert p.fitted
    assert Box.of_points(p.points).left == 19.0 and Box.of_points(p.points).right == 26.5


def test_a_swallowing_pour_naming_another_nets_pad_and_plain_points_is_refused():
    """A fitted pour is given by its pads: a plain point is refused, and so is a corner that is not a pad."""
    pa = _one_pad_part("PA", "pa", "V48", 20.0, 20.0, 2.0, 2.0)
    foreign = _one_pad_part("PF", "pf", "GND", 26.0, 20.0, 1.0, 1.0)
    b = Board(board_geometry([pa, foreign], width=60, height=60), edge_margin=1.0)
    with pytest.raises(ValueError, match="every point is a pad"):
        b.pour(Net("V48"), [PadRef(Part("pa"), 1), Location(25.0, 15.0), PadRef(Part("pf"), 1), Location(15.0, 25.0)],
               layer=CopperLayer.F, swallow_pads=True)


def test_a_declared_pours_corner_may_name_another_nets_pad():
    """A corner given as a PadRef shapes the pour close to another part's pad; the pour is drawn as declared."""
    pa = _one_pad_part("PA", "pa", "V48", 20.0, 20.0, 2.0, 2.0)
    foreign = _one_pad_part("PF", "pf", "GND", 26.0, 20.0, 1.0, 1.0)
    b = Board(board_geometry([pa, foreign], width=60, height=60), edge_margin=1.0)
    b.pour(Net("V48"), [PadRef(Part("pa"), 1), Location(25.0, 15.0), PadRef(Part("pf"), 1), Location(15.0, 25.0)],
           layer=CopperLayer.F)
    p = _points(b.resolve())
    assert not p.fitted and p.points == ((20.0, 20.0), (25.0, 15.0), (26.0, 20.0), (15.0, 25.0))


def test_a_finger_may_run_as_wide_as_a_named_pad():
    pw = _one_pad_part("PW", "pw", "V48", 20.0, 20.0, 1.0, 3.0)
    b = Board(board_geometry([pw], width=60, height=60), edge_margin=1.0)
    b.finger(Net("V48"), layer=CopperLayer.F, from_=Location(10.0, 20.0), to=Location(30.0, 20.0),
             width=PadRef(Part("pw"), 1))
    plan = b.resolve()
    p = _points(plan)
    ys = sorted({round(y, 6) for _, y in p.points})
    assert ys == [18.5, 21.5]                    # 3 mm across, centred on the pad's own y


def test_a_fingers_width_is_a_number_or_a_pad_not_anything_else():
    b = _board()
    with pytest.raises(TypeError):
        b.finger(Net("V48"), layer=CopperLayer.F, from_=Location(0, 0), to=Location(10, 0), width="wide")
