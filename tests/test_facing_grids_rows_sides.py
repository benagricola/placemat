"""Facing on a part with no pad rows (a grid), in a row, by a bare pad key and
toward a pad; SideOf, the side where a pad lands, in Beside; row(over=). Pure:
synthetic boards."""
import pytest

from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.values import Beside, Box, Edge, Face, Facing, Location, PadRef, Part, SideOf
from tests.fixtures import board_geometry, footprint, pad

_DIRECTION = {Edge.NORTH: (0, -1), Edge.SOUTH: (0, 1), Edge.EAST: (1, 0), Edge.WEST: (-1, 0)}


def _part(ref, pads, ox, oy):
    """A part at origin (ox, oy); `pads` are (number, net, dx, dy, w, h) off the origin."""
    built = [pad(ref, ref.lower(), n, net, ox + dx, oy + dy, w, h) for n, net, dx, dy, w, h in pads]
    body = Box.union([p.box for p in built]).inflate(0.2)
    return Footprint(ref, ref.lower(), None, ref, Location(ox, oy), 0.0, Face.FRONT, body, body.inflate(0.1), body,
                     tuple(built))


def _grid(ref="G", n=2, pitch=1.0):
    """An n x n grid of square pads on nets A1.. (row letter, column number), at (30, 30)."""
    pads = []
    for r in range(n):
        for c in range(n):
            pads.append((r * n + c + 1, "%s%d" % (chr(65 + r), c + 1),
                         (c - (n - 1) / 2.0) * pitch, (r - (n - 1) / 2.0) * pitch, 0.4, 0.4))
    return _part(ref, pads, 30.0, 30.0)


def _board(parts):
    return Board(board_geometry(parts, width=80, height=80), edge_margin=1.0, keep_going=True)


def _centre_of(plan, ref, numbers):
    shapes = [s for s in plan.occupancy.items[ref].shapes if s.kind == "pad" and s.label in {str(n) for n in numbers}]
    return Box.union([s.box for s in shapes]).center


def _side(plan, ref, numbers, body=None):
    """The board side the named pads lie on, measured off the placed part."""
    c = plan.occupancy.items[ref].body.center if body is None else body
    p = _centre_of(plan, ref, numbers)
    dx, dy = p.x - c.x, p.y - c.y
    if abs(dx) > abs(dy):
        return Edge.EAST if dx > 0 else Edge.WEST
    return Edge.SOUTH if dy > 0 else Edge.NORTH


# ------------------------------------------------------------------ a grid

@pytest.mark.parametrize("edge", list(Edge))
@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK])
def test_facing_a_grid_column_turns_it_to_the_side(edge, face):
    b = _board([_grid()])
    # east column of the grid (A2, B2): the outermost pads toward east
    b.place(Part("g"), at=Location(30, 30), face=face,
            rotation=Facing([PadRef(Part("g"), "B2"), PadRef(Part("g"), "A2")], edge))
    plan = b.resolve()
    assert _side(plan, "G", [4, 2]) == edge


def test_facing_a_grid_row_of_three_by_three_uses_its_outer_row():
    b = _board([_grid(n=3)])
    b.place(Part("g"), at=Location(30, 30), rotation=Facing([PadRef(Part("g"), "A1"), PadRef(Part("g"), "A2"),
                                                              PadRef(Part("g"), "A3")], Edge.EAST))
    assert _side(b.resolve(), "G", [1, 2, 3]) == Edge.EAST


def test_facing_one_corner_ball_is_refused_as_a_diagonal():
    b = _board([_grid()])
    with pytest.raises(ValueError, match=r"pad 4.*diagonal"):
        b.place(Part("g"), at=Location(30, 30), rotation=Facing(PadRef(Part("g"), "B2"), Edge.SOUTH))


def test_facing_the_centre_ball_of_a_grid_is_refused_as_having_no_direction():
    b = _board([_grid(n=3)])
    with pytest.raises(ValueError, match=r"pad 5.*centre"):
        b.place(Part("g"), at=Location(30, 30), rotation=Facing(PadRef(Part("g"), "B2"), Edge.SOUTH))


def test_facing_two_opposite_corners_is_refused_as_having_no_direction():
    b = _board([_grid()])
    with pytest.raises(ValueError, match="centre"):
        b.place(Part("g"), at=Location(30, 30),
                rotation=Facing([PadRef(Part("g"), "A1"), PadRef(Part("g"), "B2")], Edge.SOUTH))


# ------------------------------------------------------------------ bare keys and rows

def _caps(n=2):
    return [footprint("C%d" % k, 0, 0, w=2, h=1, inst="c%d" % k, nets=("S%d" % k, "GND")) for k in range(1, n + 1)]


def _fets(n=4):
    out = []
    for k in range(1, n + 1):
        ref = "Q%d" % k
        out.append(_part(ref, [(1, "G%d" % k, -1.0, 0.95, 0.6, 0.6), (2, "S%d" % k, 1.0, 0.95, 0.6, 0.6),
                               (3, "D%d" % k, 0.0, -0.95, 0.6, 0.6)], 5.0 * k, 5.0))
    return out


def test_a_row_of_two_parts_with_pad_1_west():
    b = _board(_caps())
    b.row([Part("c1"), Part("c2")], Edge.NORTH, rotation=Facing(1, Edge.WEST))
    plan = b.resolve()
    for ref in ("C1", "C2"):
        assert _side(plan, ref, [1]) == Edge.WEST


def test_a_row_of_two_parts_with_pad_1_east_on_an_east_edge():
    b = _board(_caps())
    b.row([Part("c1"), Part("c2")], Edge.EAST, rotation=Facing(1, Edge.EAST))
    plan = b.resolve()
    for ref in ("C1", "C2"):
        assert _side(plan, ref, [1]) == Edge.EAST


def test_a_row_of_four_with_a_named_pad_south():
    b = _board(_fets())
    b.row([Part("q%d" % k) for k in range(1, 5)], Edge.NORTH, rotation=Facing(3, Edge.SOUTH))
    plan = b.resolve()
    for k in range(1, 5):
        assert _side(plan, "Q%d" % k, [3]) == Edge.SOUTH


def test_a_row_takes_a_pad_by_net_name_for_each_member():
    caps = [footprint("C%d" % k, 0, 0, w=2, h=1, inst="c%d" % k, nets=("SUPPLY", "GND")) for k in (1, 2)]
    b = _board(caps)
    b.row([Part("c1"), Part("c2")], Edge.NORTH, rotation=Facing("SUPPLY", Edge.EAST))
    plan = b.resolve()
    for ref in ("C1", "C2"):
        assert _side(plan, ref, [1]) == Edge.EAST


def test_a_row_takes_one_rotation_per_member_a_facing_or_a_number():
    b = _board(_caps())
    b.row([Part("c1"), Part("c2")], Edge.NORTH, rotation=[Facing(1, Edge.WEST), 180])
    plan = b.resolve()
    assert _side(plan, "C1", [1]) == Edge.WEST
    assert _side(plan, "C2", [1]) == Edge.EAST


def test_a_facing_of_another_parts_pad_in_a_row_is_refused():
    b = _board(_caps())
    with pytest.raises(TypeError, match="own pads"):
        b.row([Part("c1"), Part("c2")], Edge.NORTH, rotation=Facing(PadRef(Part("c1"), 1), Edge.WEST))


def test_a_facing_does_not_mix_keys_and_padrefs():
    with pytest.raises(TypeError):
        Facing([1, PadRef(Part("c1"), 2)], Edge.WEST)


def test_a_bare_key_facing_works_in_place():
    b = _board(_caps(1))
    b.place(Part("c1"), at=Location(30, 30), rotation=Facing(1, Edge.NORTH))
    assert _side(b.resolve(), "C1", [1]) == Edge.NORTH


def test_toward_in_a_row_is_refused():
    b = _board(_caps() + [footprint("U", 40, 40, w=6, h=2, inst="u", nets=("A", "VCC"))])
    with pytest.raises(ValueError, match="toward"):
        b.row([Part("c1"), Part("c2")], Edge.NORTH, rotation=Facing(1, toward=PadRef(Part("u"), "VCC")))


# ------------------------------------------------------------------ SideOf, toward and over

_TURNS = [(0.0, Face.FRONT), (90.0, Face.FRONT), (180.0, Face.FRONT), (270.0, Face.FRONT),
          (0.0, Face.BACK), (90.0, Face.BACK), (180.0, Face.BACK), (270.0, Face.BACK)]


def _chip():
    return footprint("U", 40, 40, w=6, h=2, inst="u", nets=("SDA", "VCC"))     # pad 1 west, pad 2 east


@pytest.mark.parametrize("rot, face", _TURNS)
def test_a_part_beside_another_stands_on_the_side_where_a_named_pad_lands(rot, face):
    b = _board([_chip(), footprint("R", 0, 0, w=2, h=1, inst="r", nets=("X", "Y"))])
    b.place(Part("u"), at=Location(40, 40), rotation=rot, face=face)
    b.place(Part("r"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))), rotation=0)
    plan = b.resolve()
    want = _side(plan, "U", [2])
    ub, rb = plan.box("u"), plan.box("r")
    got = {Edge.EAST: rb.center.x > ub.right, Edge.WEST: rb.center.x < ub.left,
           Edge.SOUTH: rb.center.y > ub.bottom, Edge.NORTH: rb.center.y < ub.top}
    assert got[want], (want, ub, rb)
    assert sum(got.values()) == 1


def test_sideof_waits_for_its_part_when_declared_first():
    b = _board([_chip(), footprint("R", 0, 0, w=2, h=1, inst="r", nets=("X", "Y"))])
    b.place(Part("r"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))), rotation=0)
    b.place(Part("u"), at=Location(40, 40), rotation=180)
    plan = b.resolve()
    assert plan.box("r").center.x < plan.box("u").left


def test_sideof_with_a_lane_or_point_align_is_refused():
    from placemat.values import X
    b = _board([_chip(), footprint("R", 0, 0, w=2, h=1, inst="r", nets=("X", "Y"))])
    with pytest.raises(TypeError, match="SideOf"):
        b.place(Part("r"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC")),
                                     align=(1, X(PadRef(Part("u"), 1)))))


def test_a_beside_side_is_an_edge_or_a_sideof():
    with pytest.raises(TypeError):
        Beside(Part("u"), "east")


@pytest.mark.parametrize("rot, face", _TURNS)
def test_a_pad_faces_a_target_pad_on_whichever_side_it_lands(rot, face):
    cap = footprint("C", 0, 0, w=2, h=1, inst="c", nets=("SUPPLY", "GND"))
    b = _board([_chip(), cap])
    b.place(Part("u"), at=Location(40, 40), rotation=rot, face=face)
    b.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))),
            rotation=Facing(PadRef(Part("c"), "SUPPLY"), toward=PadRef(Part("u"), "VCC")))
    plan = b.resolve()
    target = _centre_of(plan, "U", [2])
    d_supply = _dist(_centre_of(plan, "C", [1]), target)
    d_gnd = _dist(_centre_of(plan, "C", [2]), target)
    assert d_supply < d_gnd


def _dist(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def test_toward_waits_for_the_target_part_when_declared_first():
    cap = footprint("C", 0, 0, w=2, h=1, inst="c", nets=("SUPPLY", "GND"))
    b = _board([_chip(), cap])
    b.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))),
            rotation=Facing(PadRef(Part("c"), "SUPPLY"), toward=PadRef(Part("u"), "VCC")))
    b.place(Part("u"), at=Location(40, 40), rotation=180)
    plan = b.resolve()
    assert _dist(_centre_of(plan, "C", [1]), _centre_of(plan, "U", [2])) < \
        _dist(_centre_of(plan, "C", [2]), _centre_of(plan, "U", [2]))


def test_facing_takes_an_edge_or_toward_not_both_or_neither():
    with pytest.raises(TypeError):
        Facing(1, Edge.WEST, toward=PadRef(Part("u"), 1))
    with pytest.raises(TypeError):
        Facing(1)


def _pullups():
    return [footprint("R%s" % n, 0, 0, w=2, h=1, inst="r_%s" % n.lower(), nets=(n, "VCC")) for n in ("SDA", "SCL")]


def _bus_chip():
    return footprint("U", 40, 40, w=6, h=2, inst="u", nets=("SDA", "SCL"))     # SDA pad 1 west, SCL pad 2 east


@pytest.mark.parametrize("rot, face", _TURNS)
def test_a_row_is_ordered_by_where_the_pads_it_serves_land(rot, face):
    b = _board([_bus_chip()] + _pullups())
    b.place(Part("u"), at=Location(40, 40), rotation=rot, face=face)
    edge = Edge.NORTH if rot in (0.0, 180.0) else Edge.EAST
    b.row([Part("r_scl"), Part("r_sda")], edge, of=Part("u"),
          over=[PadRef(Part("u"), "SCL"), PadRef(Part("u"), "SDA")], rotation=0)
    plan = b.resolve()
    axis = (lambda p: p.x) if edge is Edge.NORTH else (lambda p: p.y)
    sda, scl = axis(_centre_of(plan, "U", [1])), axis(_centre_of(plan, "U", [2]))
    r_sda, r_scl = axis(plan.box("r_sda").center), axis(plan.box("r_scl").center)
    assert (r_sda < r_scl) == (sda < scl)


def test_a_row_over_pads_keeps_the_order_given_when_it_already_matches():
    b = _board([_bus_chip()] + _pullups())
    b.place(Part("u"), at=Location(40, 40), rotation=0)
    b.row([Part("r_sda"), Part("r_scl")], Edge.NORTH, of=Part("u"),
          over=[PadRef(Part("u"), "SDA"), PadRef(Part("u"), "SCL")], rotation=0)
    plan = b.resolve()
    assert plan.box("r_sda").center.x < plan.box("r_scl").center.x


def test_a_row_over_pads_at_one_coordinate_is_refused_naming_the_members():
    b = _board([_bus_chip()] + _pullups())
    b.place(Part("u"), at=Location(40, 40), rotation=90)
    b.row([Part("r_sda"), Part("r_scl")], Edge.NORTH, of=Part("u"),
          over=[PadRef(Part("u"), "SDA"), PadRef(Part("u"), "SCL")], rotation=0)
    with pytest.raises(ValueError, match=r"r_sda.*r_scl"):
        b.resolve()


def test_a_row_over_a_different_count_of_pads_is_refused():
    b = _board([_bus_chip()] + _pullups())
    with pytest.raises(ValueError, match="over"):
        b.row([Part("r_sda"), Part("r_scl")], Edge.NORTH, of=Part("u"), over=[PadRef(Part("u"), "SDA")])


def test_a_row_over_pads_waits_for_their_part_when_declared_first():
    b = _board([_bus_chip()] + _pullups())
    b.row([Part("r_scl"), Part("r_sda")], Edge.NORTH, of=Part("u"),
          over=[PadRef(Part("u"), "SCL"), PadRef(Part("u"), "SDA")], rotation=0)
    b.place(Part("u"), at=Location(40, 40), rotation=180)
    plan = b.resolve()
    assert plan.box("r_scl").center.x < plan.box("r_sda").center.x


def test_a_row_over_pads_on_the_board_edge_with_a_start():
    chip = _bus_chip()
    b = _board([chip] + _pullups())
    b.place(Part("u"), at=Location(40, 40), rotation=180)
    b.row([Part("r_sda"), Part("r_scl")], Edge.NORTH, start=10.0,
          over=[PadRef(Part("u"), "SDA"), PadRef(Part("u"), "SCL")], rotation=0)
    plan = b.resolve()
    assert plan.box("r_scl").center.x < plan.box("r_sda").center.x      # SCL lies west once u is turned 180

