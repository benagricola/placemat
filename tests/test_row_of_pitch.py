"""board.row(items, edge, of=Part(...), centre=PadRef(...), pitch=...): a row
along a part's side whose middle lies on a pad's centre line, its items'
centres `pitch` apart. Pure: synthetic boards."""
import pytest

from placemat.layout import Board
from placemat.values import Along, Edge, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def make_board(**kw):
    fps = [footprint("U1", 20, 20, w=6, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 0, 0, w=2, h=1, inst="r1", nets=("A", "GND")),
           footprint("R2", 0, 0, w=2, h=1, inst="r2", nets=("B", "GND")),
           footprint("C1", 40, 40, w=2, h=1, inst="c1", nets=("A", "GND"))]
    return Board(board_geometry(fps, width=80, height=80), edge_margin=1.0, **kw)


def test_a_pitched_pair_is_centred_on_a_pad_of_the_part():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), centre=PadRef(Part("u1"), 2), pitch=2.7,
          rotation=0)
    plan = b.resolve()
    r1, r2, u1 = plan.box("r1"), plan.box("r2"), plan.box("u1")
    assert r2.center.x - r1.center.x == pytest.approx(2.7)
    assert (r1.center.x + r2.center.x) / 2 == pytest.approx(22.4)       # pad 2's centre: 20 + 3 - 0.6
    assert (u1.top - 0.1) - (r1.bottom + 0.1) == pytest.approx(0.0)      # the envelope gap off u1 (courtyards touching)
    assert r1.center.y == pytest.approx(r2.center.y)


def test_a_pitch_below_the_envelope_gap_is_refused_naming_both_items():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    with pytest.raises(ValueError, match=r"r1.*r2.*2\.2"):
        b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), centre=PadRef(Part("u1"), 2), pitch=2.0,
              rotation=0)


def test_a_pitch_of_exactly_the_envelope_gap_is_accepted():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), pitch=2.2, rotation=0)
    plan = b.resolve()
    assert plan.box("r2").center.x - plan.box("r1").center.x == pytest.approx(2.2)


def test_pitch_with_gap_is_refused():
    b = make_board()
    with pytest.raises(ValueError, match="pitch.*gap"):
        b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), pitch=2.7, gap=0.5)


def test_centre_with_align_is_refused():
    b = make_board()
    with pytest.raises(ValueError, match="centre.*align"):
        b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), centre=PadRef(Part("u1"), 2),
              align=Along.MID)


def test_centre_with_of_takes_a_pad():
    b = make_board()
    with pytest.raises(TypeError, match="PadRef"):
        b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), centre=Location(10, 10))


def test_pitch_needs_of():
    b = make_board()
    with pytest.raises(ValueError, match="pitch.*of="):
        b.row([Part("r1"), Part("r2")], Edge.NORTH, pitch=2.7)


def test_centre_on_a_third_parts_pad():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), centre=PadRef(Part("c1"), 1), pitch=2.7,
          rotation=0)
    b.place(Part("c1"), at=Location(30, 40))                            # declared after: the row waits for it
    plan = b.resolve()
    r1, r2 = plan.box("r1"), plan.box("r2")
    assert (r1.center.x + r2.center.x) / 2 == pytest.approx(29.6)       # c1's pad 1: 30 - 1 + 0.6
    assert [s.item for s in plan.steps].index("c1") < [s.item for s in plan.steps].index("r1")


def test_centre_without_pitch_puts_the_rows_middle_on_the_pad():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), centre=PadRef(Part("u1"), 1), rotation=0)
    plan = b.resolve()
    r1, r2 = plan.box("r1"), plan.box("r2")
    assert (r1.left - 0.1 + r2.right + 0.1) / 2 == pytest.approx(17.6)  # pad 1's centre: 20 - 3 + 0.6
    assert r2.left - r1.right == pytest.approx(0.2)                      # courtyards touching


def test_without_pitch_or_centre_the_row_is_unchanged():
    b = make_board()
    b.place(Part("u1"), at=Location(20, 20))
    row = b.row([Part("r1"), Part("r2")], Edge.NORTH, of=Part("u1"), rotation=0)
    assert "pitch" not in vars(row)                   # a Row's digest names its attributes: none new
    assert row.anchor == ("of", (Part("u1"), Along.START))


PAIR = ("r1", "r2")        # two pins at a mechanical pitch, north of a driver, centred on one of its pins
PITCH = 2.7


def _hand_placed():
    """The hand arithmetic a script wrote before pitch= and centre=: the
    pin's x, each item's body centre half the pitch either side of it, and
    each item's envelope the envelope gap (courtyards touching) north of
    the driver's."""
    b = make_board()
    b.place(Part("u1"), at=Location(20.0, 20.0), rotation=0)
    u1_env = b.envelope(Part("u1"), rotation=0)
    pin_x = 20.0 + 3.0 - 0.6                                  # the driver's pad 2, read off its footprint
    for name, side in zip(PAIR, (-1, 1)):
        env, body = b.envelope(Part(name), rotation=0), b.extent(Part(name), rotation=0)
        x = pin_x + side * PITCH / 2.0 - body.center.x
        y = 20.0 + u1_env.top - 0.0 - env.bottom
        b.place(Part(name), at=Location(x, y), rotation=0)
    return b.resolve()


def _intent_placed():
    b = make_board()
    b.place(Part("u1"), at=Location(20.0, 20.0), rotation=0)
    b.row([Part(n) for n in PAIR], Edge.NORTH, of=Part("u1"), centre=PadRef(Part("u1"), 2), pitch=PITCH,
          rotation=0)
    return b.resolve()


def test_the_pitched_pair_matches_the_hand_computed_one_within_0_01mm():
    hand, intent = _hand_placed(), _intent_placed()
    for name in PAIR:
        a, b = hand.box(name), intent.box(name)
        assert (a.left, a.top, a.right, a.bottom) == pytest.approx((b.left, b.top, b.right, b.bottom), abs=0.01)
