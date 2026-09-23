"""The cleanup pass on its own: moves and swaps that lower wire and link cost."""
from placemat.cleanup import cleanup
from placemat.layout import Link
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint


def _occ(fps, at, width=60, height=30):
    g = board_geometry(fps, width=width, height=height)
    occ = Occupancy(g, 0.5, board_box=g.outline_box)
    for fp in fps:
        occ.commit(fp, Placement(Location(*at[fp.inst]), 0.0, Face.FRONT))
    return g, occ


def _pins(g, placed_refs, quiet=()):
    pins = {}
    for fp in g.footprints:
        if fp.ref in placed_refs:
            for p in fp.pads:
                if p.net and p.net not in quiet:
                    pins.setdefault(p.net, []).append((fp.ref, p.number))
    return {n: v for n, v in pins.items() if len(v) > 1}


def test_a_part_left_far_from_its_connections_moves_toward_them():
    """b1's only connection is to a1, 26 mm west: between two parts it would sit
    anywhere along the line at the same wire length."""
    fps = [footprint("A1", 10, 15, inst="a1", nets=("N1", "N2")),
           footprint("B1", 14, 15, inst="b1", nets=("N2", "N9")),
           footprint("C1", 50, 15, inst="c1", nets=("N3", "N4"))]
    g, occ = _occ(fps, {"a1": (10, 15), "b1": (40, 15), "c1": (50, 15)})
    r = cleanup(occ, {"b1": fps[1]}, _pins(g, {"A1", "B1", "C1"}), [], None, 3, 3.0, 0.25)
    frm, to, c0, c1 = r.moves["b1"]
    assert c1 < c0 and to.location.x < frm.location.x
    assert occ.legal(fps[1], to) is None


def test_two_identical_parts_whose_connections_cross_swap():
    fps = [footprint("J1", 5, 5, inst="j1", nets=("P", "GND")), footprint("J2", 5, 25, inst="j2", nets=("Q", "GND")),
           footprint("R1", 30, 25, inst="r1", nets=("P", "X")), footprint("R2", 30, 5, inst="r2", nets=("Q", "Y"))]
    g, occ = _occ(fps, {"j1": (5, 5), "j2": (5, 25), "r1": (30, 25), "r2": (30, 5)})
    r = cleanup(occ, {"r1": fps[2], "r2": fps[3]}, _pins(g, {"J1", "J2", "R1", "R2"}, quiet={"GND"}), [], None, 3, 0.5, 0.25)
    assert r.swaps == [("r1", "r2")]


def test_a_move_stops_where_a_limited_link_would_pass_its_limit():
    """b1's wire pulls it west toward a1; a FREE link with a 3 mm limit ties
    its pad 2 to d1. It moves, but no further than the limit allows."""
    fps = [footprint("A1", 10, 15, inst="a1", nets=("N1", "N2")),
           footprint("B1", 30, 15, inst="b1", nets=("N2", "N3")),
           footprint("D1", 32, 17.5, inst="d1", nets=("N5", "N6"))]
    g, occ = _occ(fps, {"a1": (10, 15), "b1": (30, 15), "d1": (32, 17.5)})
    link = Link(("B1", "2"), ("D1", "1"), 0, 3.0, "keep b1 by d1", None, None)
    r = cleanup(occ, {"b1": fps[1]}, _pins(g, {"A1", "B1", "D1"}), [link], None, 3, 3.0, 0.25)
    assert "b1" in r.moves
    to = r.moves["b1"][1]
    assert to.location.x < 30
    pads = occ.candidate_pad_locations(fps[1], to)
    assert pads[("B1", "2")].distance(occ.pad_location("D1", "1")) <= 3.0 + 1e-9


def test_the_pass_is_the_same_twice():
    def run():
        fps = [footprint("A%d" % k, 5 + 6 * k, 15, inst="a%d" % k, nets=("N%d" % k, "N%d" % (k + 1))) for k in range(6)]
        at = {"a%d" % k: (5 + 9 * ((k * 7) % 6), 15) for k in range(6)}
        g, occ = _occ(fps, at)
        r = cleanup(occ, {fp.inst: fp for fp in fps}, _pins(g, {fp.ref for fp in fps}), [], None, 3, 3.0, 0.25)
        return sorted((k, v[1]) for k, v in r.moves.items()), r.swaps
    assert run() == run()


def _wrong_way():
    """R1's pad 1 (A) is west and pad 2 (B) east, but A's other pad is east
    of it and B's west: turned 180 both nets are 2.8 mm shorter."""
    fps = [footprint("J1", 10, 15, inst="west", nets=("X", "B")),
           footprint("J2", 30, 15, inst="east", nets=("A", "Y")),
           footprint("R1", 20, 15, inst="r", nets=("A", "B"))]
    g, occ = _occ(fps, {"west": (10, 15), "east": (30, 15), "r": (20, 15)})
    return fps, _pins(g, {"J1", "J2", "R1"}), occ


def test_a_part_the_wrong_way_round_is_turned_when_it_may_turn():
    fps, pins, occ = _wrong_way()
    r = cleanup(occ, {"r": fps[2]}, pins, [], None, 2, 0.5, 0.25, turns={"r": (0, 90, 180, 270)})
    frm, to, c0, c1 = r.moves["r"]
    assert to.rotation == 180 and c1 < c0
    assert occ.legal(fps[2], to) is None


def test_a_part_with_one_rotation_is_only_shifted():
    fps, pins, occ = _wrong_way()
    cleanup(occ, {"r": fps[2]}, pins, [], None, 2, 0.5, 0.25)
    assert occ.items["R1"].reference.rotation == 0
