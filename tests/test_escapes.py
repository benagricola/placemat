"""Escape room: every placed pad keeps short corridors out of it, a track
plus its clearance wide. Copper of another net on the pad's layer closes a
corridor; a part's body does not, since a track can run under it. Closing a
pad's last corridor toward what it connects to costs `score.escape_closed`;
closing its last corridor of any kind walls it off and costs
`score.escape_walled`."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Box, Face, Location, Near, Part
from tests.fixtures import board_geometry, footprint, pad

BLIND = dict(score_crossing=0.0, score_escape_closed=0.0, score_escape_walled=0.0, score_escape_crossed=0.0)


def _row_part(ref, inst, cx, cy, nets, pitch=1.0, n=5):
    """Five pads in one row along x at y=cy, each 0.4 wide and 1.2 tall; the body
    north of the row, so each pad's corridor runs south."""
    pads = tuple(pad(ref, inst, k + 1, nets[k], cx + (k - (n - 1) / 2) * pitch, cy, 0.4, 1.2) for k in range(n))
    body = Box(cx - n * pitch / 2, cy - 3.0, cx + n * pitch / 2, cy + 0.6)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def _board(**settings):
    # U1's row at y=30, pins 1-5 at x 28-32 on nets A-E. Pin 3 (C) joins TA to the south.
    # C1 (pads 1x1 at x -+0.4) joins pins 2 (B) and 4 (D): wire alone pulls it right
    # across pin 3's corridor.
    fps = [_row_part("U1", "u1", 30, 30, ("A", "B", "C", "D", "E")),
           footprint("C1", 5, 5, w=2.0, h=1.0, inst="c1", nets=("B", "D")),
           footprint("TA", 30, 45, inst="ta", nets=("C", "Q"))]
    cfg = dataclasses.replace(Settings(), **settings)
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg)


def _placed(b, extra=()):
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("ta"), at=Location(30, 45))
    for inst, at in extra:
        b.place(Part(inst), at=at)
    return b.resolve()


def test_a_row_pad_has_one_corridor_along_its_rows_normal_and_a_two_pad_part_three():
    from placemat.escapes import corridors
    occ = _placed(_board()).occupancy
    row = [c for c in corridors(occ, "U1") if c.number == "3" and not c.via]
    assert len(row) == 1 and row[0].direction == pytest.approx((0.0, 1.0))      # south, away from the body
    two = [c for c in corridors(occ, "TA") if not c.via]
    assert len([c for c in two if c.number == "1"]) == 3
    assert not [c for c in two if c.number == "2"]          # Q goes nowhere else: an unconnected pin keeps no escape
    spots = [c for c in corridors(occ, "U1") if c.number == "3" and c.via]
    assert len(spots) == 1                                  # and each way out has a via spot where it starts


def test_foreign_copper_across_a_pads_only_corridor_walls_it_off_and_beside_it_costs_nothing():
    from placemat.escapes import Escapes
    occ = _placed(_board()).occupancy
    esc = Escapes(occ)
    c1 = occ.geometry.footprint("C1")
    assert esc.closed(c1, Placement(Location(30.0, 31.5), 0.0, Face.FRONT)) == (0, 0, 1)
    # south of the corridor, its airwires to pins 2 and 4 pass either side of pin 3's
    assert esc.closed(c1, Placement(Location(30.0, 36.0), 0.0, Face.FRONT)) == (0, 0, 0)


def test_closing_only_the_corridor_toward_the_target_is_closed_not_walled():
    """TA's C pad (28.1-29.1 x 44.5-45.5) joins U1 pin 3 to the north. W's pads close
    its north corridor and all three via spots but leave its west and south
    corridors open: the pad can still be left, but not toward what it joins."""
    from placemat.escapes import Escapes
    # W is read 20 mm east and 35 mm north of where the candidate puts it
    w_pads = tuple(pad("W", "w", k + 1, "Z", (x0 + x1) / 2 + 20, (y0 + y1) / 2 - 35, x1 - x0, y1 - y0)
                   for k, (x0, y0, x1, y1) in enumerate([
                       (27.0, 43.3, 30.0, 44.4),                            # across the north corridor and spot
                       (27.3, 44.5, 28.0, 44.62), (27.3, 45.38, 28.0, 45.5),  # either side of the west corridor
                       (28.1, 45.55, 28.25, 46.2), (28.95, 45.55, 29.1, 46.2)]))  # either side of the south one
    body = Box(47.0, 8.3, 50.0, 11.2)
    wall = Footprint("W", "w", None, "W", Location(48.5, 9.7), 0.0, Face.FRONT, body, body, body, w_pads)
    fps = [_row_part("U1", "u1", 30, 30, ("A", "B", "C", "D", "E")),
           footprint("TA", 30, 45, inst="ta", nets=("C", "Q")), wall]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("ta"), at=Location(30, 45))
    occ = b.resolve().occupancy
    assert Escapes(occ).closed(wall, Placement(Location(28.5, 44.7), 0.0, Face.FRONT)) == (0, 1, 0)


def test_a_via_spot_beside_the_pad_keeps_its_escape_open_whatever_else_is_closed():
    from placemat.escapes import Escapes
    occ = _placed(_board()).occupancy
    c1 = occ.geometry.footprint("C1")
    # C1's B pad across TA's north corridor only: its via spots west and south stay clear
    assert Escapes(occ).closed(c1, Placement(Location(29.0, 43.8), 0.0, Face.FRONT)) == (0, 0, 0)


def test_same_net_copper_and_the_pads_own_part_never_close_a_corridor():
    from placemat.escapes import Escapes
    b = Board(board_geometry([_row_part("U1", "u1", 30, 30, ("A", "B", "X", "D", "E")),
                              footprint("C1", 5, 5, inst="c1", nets=("X", "X2")),         # pads at x -+1.4
                              footprint("T1", 30, 45, inst="t1", nets=("X", "Q"))],
                             width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(30, 30))
    b.place(Part("t1"), at=Location(30, 45))
    occ = b.resolve().occupancy
    c1 = occ.geometry.footprint("C1")
    # C1's X pad right over pin 3 (X too); its X2 pad at x 32.8, touching pin 5's corridor at most
    assert Escapes(occ).closed(c1, Placement(Location(31.4, 31.5), 0.0, Face.FRONT)) == (0, 0, 0)


def test_the_search_keeps_a_part_off_a_pads_only_corridor():
    from placemat.escapes import Escapes
    blind = _placed(_board(**BLIND), extra=[("c1", Near(Location(30.0, 31.6), radius=4.0))])
    assert not Escapes(blind.occupancy).open_toward("U1", "3")          # wire alone walls pin 3 off
    kept = _placed(_board(), extra=[("c1", Near(Location(30.0, 31.6), radius=4.0))])
    assert Escapes(kept.occupancy).open_toward("U1", "3")


def _ring(ref, inst, cx, cy, net_in, net_ring, gap, size=1.0):
    """A 0.5 mm pad of `net_in` at the centre, boxed in by eight `size` mm pads of
    another net `gap` mm clear of it on every side."""
    pads = [pad(ref, inst, 1, net_in, cx, cy, 0.5, 0.5)]
    k = 2
    r = 0.25 + gap + size / 2
    for x in (-r, 0.0, r):
        for y in (-r, 0.0, r):
            if x or y:
                pads.append(pad(ref, inst, k, net_ring, cx + x, cy + y, size, size))
                k += 1
    body = Box(cx - 3, cy - 3, cx + 3, cy + 3)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1), body, tuple(pads))


def _ringed(gap, size=1.0):
    fps = [_ring("U9", "u9", 30, 30, "IN", "RING", gap, size), footprint("T1", 50, 50, inst="t1", nets=("IN", "Z"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)       # track 0.2, clearance 0.2, via 0.6
    b.place(Part("u9"), at=Location(30, 30))
    b.place(Part("t1"), at=Location(50, 50))
    return b.resolve().occupancy


def test_a_pad_boxed_in_tighter_than_a_track_or_a_via_has_no_way_out():
    from placemat.escapes import path_out
    assert path_out(_ringed(0.1), "U9", "1", depth=2.0) is False


def test_a_gap_a_track_fits_through_is_a_way_out():
    from placemat.escapes import path_out
    # ring pads 1.75 apart, 1 mm wide: 0.75 mm between them, a track and its clearances need 0.6
    assert path_out(_ringed(1.0), "U9", "1", depth=2.0) is True


def test_room_for_a_via_beside_the_pad_is_a_way_out():
    from placemat.escapes import path_out
    # 1.2 mm ring pads 0.45 mm apart: no track between them; but 0.8 mm clear round the
    # pad fits a 0.6 mm via 0.2 mm from the ring, to take the route to another layer
    assert path_out(_ringed(0.8, size=1.2), "U9", "1", depth=2.0) is True
