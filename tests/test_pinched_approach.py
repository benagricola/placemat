"""A pad whose only approach toward what it joins passes between two other nets' pads standing closer than a track and
two clearances: an `escape.pinched` warning, raised once on the finished board."""
import dataclasses
from pathlib import Path

import pytest

from placemat.board_geometry import Footprint, NetClass
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, Face, Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, pad

XS = (29.0, 29.5, 30.0, 30.5, 31.0)         # the contacts' and the pins' x, 0.5 mm apart


def row_part(ref, inst, cx, y, nets, size=(0.3, 0.8)):
    """A part with a row of pads along x at `y`, 0.5 mm apart round `cx`, one per entry of `nets` (pad 1 westmost)."""
    xs = [cx - 1.0 + 0.5 * k for k in range(5)]
    pads = tuple(pad(ref, inst, k + 1, n, x, y, *size) for k, (x, n) in enumerate(zip(xs, nets)))
    body = Box(xs[0] - 0.3, y - 0.6, xs[-1] + 0.3, y + 0.6)
    return Footprint(ref, inst, None, ref, Location(cx, y), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def o201(ref, inst, cx, cy, nets):
    """An 0201 standing along y: 0.3 mm pads 0.5 mm apart, pad 1 north."""
    pads = (pad(ref, inst, 1, nets[0], cx, cy - 0.25, 0.3, 0.3), pad(ref, inst, 2, nets[1], cx, cy + 0.25, 0.3, 0.3))
    body = Box(cx - 0.15, cy - 0.4, cx + 0.15, cy + 0.4)
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.05), body, pads)


def termination_row(centres=(29.1, 29.7, 30.3, 30.9), east=False):
    """J1's contacts on y = 30, U1's pins on y = 12, RST on the middle one of each; a termination 0201 per other line
    on y = 24 between them, 0.6 mm apart: RST's airwire runs north up x = 30 between R2 and R3, whose pads are 0.3 mm
    apart. The terminations' lines go on to the contacts beside RST, or with `east` to U2, east of the row."""
    lines = [k for k, x in enumerate(XS) if x != 30.0][:len(centres)] if len(centres) == 4 else [1, 3]
    pins, contacts, rs = [""] * 5, [""] * 5, []
    for i, (k, cx) in enumerate(zip(lines, centres)):
        pins[k], contacts[k] = "S%d" % (i + 1), "S%d_P" % (i + 1)
        rs.append(o201("R%d" % (i + 1), "r%d" % (i + 1), cx, 24.0, (pins[k], contacts[k])))
    pins[2] = contacts[2] = "RST"
    if east:
        far = row_part("U2", "far", 40.0, 26.0, [c for c in contacts if c != "RST"] + [""])
        contacts = ["", "", "RST", "", ""]
    parts = [row_part("U1", "mcu", 30.0, 12.0, pins), row_part("J1", "conn", 30.0, 30.0, contacts)] + rs
    return parts + [far] if east else parts


def resolve(fps, **settings):
    g = board_geometry(fps, width=60, height=60)
    g = dataclasses.replace(g, netclasses={n: NetClass("Default", 0.127, 0.127, 0.45, 0.2) for n in g.nets},
                            default_clearance=0.127)
    b = Board(g, edge_margin=1.0, keep_going=True,
              settings=dataclasses.replace(Settings(), cleanup_enabled=False, **settings))
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b.resolve()


def pinched(plan) -> list:
    return [f for f in plan.findings if f.cause is C.ESCAPE_PINCHED]


def test_a_contact_whose_line_must_pass_between_two_terminations_closer_than_a_track_and_two_clearances_is_a_warning():
    """The reported case: four 0201s at 0.6 mm straddle the connector contact, their pads 0.3 mm apart, and a 0.127 mm
    track at 0.127 mm clearance needs 0.381 mm. The row is wider than any way round within the detour."""
    (f,) = pinched(resolve(termination_row()))
    assert f.severity == "warning"
    assert f.facts["net"] == "RST" and f.facts["pad"] == ["J1", "3"] and f.facts["toward"] == ["U1", "3"]
    assert f.facts["layer"] == "F.Cu"
    assert f.facts["neighbours"] == [{"kind": "pad", "ref": "R2", "cell": "", "pin": "2", "net": "S2_P", "lane": ""},
                                     {"kind": "pad", "ref": "R3", "cell": "", "pin": "2", "net": "S3_P", "lane": ""}]
    assert f.facts["gap_mm"] == pytest.approx(0.3) and f.facts["need_mm"] == pytest.approx(0.381)
    assert f.facts["at"] == pytest.approx([30.0, 24.25])
    assert f == ("J1 pin 3 (RST): its approach toward U1 pin 3 on F.Cu passes between R2 pin 2 (S2_P) and R3 pin 2 "
                 "(S3_P), 0.300 mm apart, under the 0.381 mm a 0.127 mm track and two clearances need; within 2.00 mm of "
                 "the airwire every other way is closed by copper or crosses another net's airwire")


def test_a_pinch_with_a_way_round_within_the_detour_is_no_finding():
    """Two terminations only, their lines going east to U2 rather than to the contacts beside RST: the gap between them
    is as narrow, and a track goes round the west one within the detour."""
    assert pinched(resolve(termination_row(centres=(29.7, 30.3), east=True))) == []


def test_the_lines_of_two_terminations_to_the_contacts_beside_it_close_the_way_round():
    """The same two terminations with their lines to the contacts either side of RST: going round either crosses one
    of them, so the gap between the two is the only approach."""
    (f,) = pinched(resolve(termination_row(centres=(29.7, 30.3))))
    assert f.facts["pad"] == ["J1", "3"] and f.facts["gap_mm"] == pytest.approx(0.3)


def test_the_detour_is_a_setting():
    """The row of four with its lines going east: the way round its west end is 1.24 mm off the airwire, inside the
    default detour and outside one of 1 mm."""
    assert pinched(resolve(termination_row(east=True))) == []
    (f,) = pinched(resolve(termination_row(east=True), place_approach_detour=1.0))
    assert f.facts["detour_mm"] == 1.0


def test_a_pinch_past_the_reach_is_not_looked_for():
    """The row is 6 mm from the contact and 12 mm from the pin: within neither end's reach, nothing is raised."""
    assert pinched(resolve(termination_row(), place_approach_reach=5.0)) == []


def test_a_gap_a_track_fits_is_no_pinch():
    """The same row 0.7 mm apart: 0.4 mm between pads, over the 0.381 mm needed."""
    assert pinched(resolve(termination_row(centres=(28.9, 29.6, 30.4, 31.1)))) == []


def test_a_dense_field_whose_gaps_a_track_fits_raises_nothing():
    """Three rows of six 0201s 0.7 mm apart (0.4 mm between pads) across five lines from U1 to J1: dense, and every gap
    takes the track."""
    fps = [row_part("U1", "mcu", 30.0, 12.0, ["A", "B", "C", "D", "E"]), row_part("J1", "conn", 30.0, 30.0, ["A", "B", "C", "D", "E"])]
    for r, y in enumerate((18.0, 21.0, 24.0)):
        for k in range(6):
            name = "R%d%d" % (r, k)
            fps.append(o201(name, name.lower(), 28.25 + 0.7 * k, y, ("N%d%d" % (r, k), "M%d%d" % (r, k))))
    fps.append(row_part("U2", "far", 45.0, 40.0, ["N%d%d" % (r, k) for r in range(3) for k in range(2)][:5]))
    plan = resolve(fps)
    assert pinched(plan) == []


ROUTED = Path(__file__).resolve().parent.parent / "fixtures" / "fairing" / "routed" / "layout.kicad_pcb"


@needs_kicad
def test_a_dense_board_that_routed_has_no_pinched_approach():
    """A whole board after its route, read with its pads only (no copper, so every connection is an airwire again):
    the router found every way it took, so no approach is pinched."""
    from placemat.approach import pinched as pinches
    from placemat.escapes import Escapes
    from placemat.kicad.read import read_board
    from placemat.occupancy import Occupancy
    routed = read_board(str(ROUTED))
    g = dataclasses.replace(routed, copper=tuple(c for c in routed.copper if c.kind == "pad"))
    occ = Occupancy(g, edge_margin=0.0)
    assert len(occ.ratsnest().edges()) > 500
    assert pinches(occ, Escapes(occ, mirror=False, depth=occ.settings.score_escape_depth)) == []
