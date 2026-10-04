"""A label's spot lies on the board: inside the outline, outside its cutouts,
the board's silk clearance from the edge (KiCad checks silk to the board edge
against the silk clearance rule). A label with no such spot is a finding. Pure:
synthetic boards."""
import dataclasses


from placemat.copper import Text
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Along, Beside, Cell, Edge, Location, Part
from tests.fixtures import board_geometry, footprint

SILK = 0.2


def texts(plan):
    return [op for op in plan.copper if isinstance(op, Text)]


def make_board(height, side=Edge.NORTH, text_width=5.2, other=True, shape=None, at=(27, 28), **kw):
    """Cell conn: a labelled connector J1 (x 28..32, y 29..31) beside a taller
    member P1. Cell other, placed Beside conn's east side, pushes a north label
    off its declared spot."""
    size = (text_width - 0.15) / (5 * 0.914 + 2 / 9)
    fps = [footprint("J1", 30, 30, w=4, h=2, inst="conn.j1", nets=("A", "B"), cell="conn"),
           footprint("P1", 25, 28, w=4, h=6, inst="conn.p1", nets=("C", "D"), cell="conn"),
           footprint("U2", 0, 0, w=3, h=5, inst="other.u2", nets=("E", "F"), cell="other",
                     silk_boxes=((-1.5, -2.5, 1.5, 2.5),))]
    b = Board(board_geometry(fps, cells=["conn", "other"], width=80, height=height, silk_clearance=SILK),
              edge_margin=1.0, settings=dataclasses.replace(Settings(), place_envelope="physical"), **kw)
    if shape is not None:
        shape(b)
    b.place(Cell("conn"), at=Location(*at))
    b.label(Part("conn.j1"), "USB-C", side=side, align=Along.START, knockout=True, size=size)
    if other:
        b.place(Cell("other"), at=Beside(Cell("conn"), Edge.EAST, align=Along.START))
    return b


def inside(t, height, margin=SILK):
    return t.box.top >= margin - 1e-6 and t.box.bottom <= height - margin + 1e-6


def test_a_label_pushed_south_does_not_leave_the_board():
    """Taller board: south is on the board and the label goes there."""
    plan = make_board(40).resolve()
    (t,) = texts(plan)
    assert t.side is Edge.SOUTH and inside(t, 40)


def test_a_label_with_no_spot_on_the_board_is_a_finding():
    plan = make_board(32, keep_going=True).resolve()
    (t,) = texts(plan)
    assert t.side is Edge.NORTH                  # it stays where it was, unmoved
    said = [str(f) for f in plan.findings if "label conn.j1 USB-C" in str(f) and "no clear spot" in str(f)]
    assert said, list(plan.findings)


def test_a_label_declared_off_the_board_moves_to_a_side_on_it():
    """First placement: south of the connector is off a 32 mm board."""
    plan = make_board(32, side=Edge.SOUTH, text_width=3.0, other=False).resolve()
    (t,) = texts(plan)
    assert t.side is not Edge.SOUTH and inside(t, 32)
    assert "moved" in plan.step("label conn.j1 USB-C").note


def test_a_label_declared_off_the_board_with_no_spot_is_a_finding():
    """A text wider than the board fits on no side."""
    plan = make_board(40, side=Edge.SOUTH, text_width=79.9, other=False, keep_going=True).resolve()
    assert [f for f in plan.findings if "label conn.j1 USB-C" in str(f) and "no spot on the board" in str(f)], list(plan.findings)


def test_a_label_keeps_the_silk_clearance_from_the_edge():
    """South spot is on the board but nearer the edge than the silk clearance."""
    plan = make_board(32.05, side=Edge.SOUTH, text_width=3.0, other=False).resolve()
    (t,) = texts(plan)
    assert t.side is not Edge.SOUTH
    assert t.box.top >= SILK - 1e-6 and t.box.bottom <= 32.05 - SILK + 1e-6


def test_a_label_does_not_leave_a_round_board():
    def disc(b):
        b.disc(diameter=36.0)
    """The text overhangs its connector, whose own corner is well inside the rim: its declared spot is
    inside the board's square frame but past the rim."""
    plan = make_board(36, side=Edge.SOUTH, text_width=9.0, other=False, shape=disc, at=(22, 24)).resolve()
    (t,) = texts(plan)
    assert "moved" in plan.step("label conn.j1 USB-C").note
    cx = cy = 18.0
    far = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 for x in (t.box.left, t.box.right) for y in (t.box.top, t.box.bottom))
    assert far <= 18.0 - SILK + 1e-6
