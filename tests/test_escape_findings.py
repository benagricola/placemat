"""A resolve reports escapes it left crossed, closed or walled off, as
findings of their own kinds, confirmed by the path search."""
import dataclasses

from placemat.board_geometry import Footprint
from placemat.findings import Finding
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, Face, Location, Part
from tests.fixtures import board_geometry, pad
from tests.test_cleanup_swaps import two_pad, west_row
from tests.test_escapes import _ring


def _fixed(fps, keep_going=False, **settings):
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False, **settings)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg, keep_going=keep_going)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b.resolve()


def test_escapes_that_cross_at_a_pin_row_are_a_finding_naming_the_pins_and_the_parts():
    fps = [west_row("U2", "mcu", 30, 30, {3: "VDD_RF", 4: "MCU_EN"}),
           two_pad("C2", "c_en", 26.1, 29.5, ("GND", "MCU_EN")),
           two_pad("L2", "l_rf", 26.1, 30.75, ("VRF_IN", "VDD_RF"))]
    plan = _fixed(fps)
    crossed = [f for f in plan.findings if f.kind == "escape_crossed"]
    assert crossed == ["U2 pins 3/4: L2 VDD_RF crosses C2 MCU_EN"]


def _walled_in(gap):
    """U9's IN pad at (30, 30), and R9 - another part - a ring of RING pads
    `gap` mm round it; T1 is what IN joins."""
    from tests.fixtures import footprint
    ring = _ring("R9", "r9", 30, 30, "DROP", "RING", gap)
    ring = Footprint("R9", "r9", None, "R9", ring.location, 0.0, Face.FRONT, ring.body_box, ring.courtyard_box,
                     ring.phys_box, ring.pads[1:])                          # the ring alone
    centre = Footprint("U9", "u9", None, "U9", Location(30, 30), 0.0, Face.FRONT, Box(29.7, 29.7, 30.3, 30.3),
                       Box(29.7, 29.7, 30.3, 30.3), Box(29.7, 29.7, 30.3, 30.3), (pad("U9", "u9", 1, "IN", 30, 30, 0.5, 0.5),))
    return [centre, ring, footprint("T1", 50, 50, inst="t1", nets=("IN", "Z"))]


def test_a_pad_the_path_search_finds_walled_in_is_a_finding_naming_what_walls_it():
    plan = _fixed(_walled_in(0.1), keep_going=True)          # 0.1 mm is under the clearance: a finding too
    walled = [f for f in plan.findings if f.kind == "escape_walled"]
    assert walled == ["U9 pin 1 (IN): walled off by R9"]


def test_a_pad_whose_corridors_are_closed_but_a_track_still_gets_out_is_no_finding():
    plan = _fixed(_walled_in(1.0), keep_going=True)
    assert not [f for f in plan.findings if f.kind.startswith("escape_")]


def test_the_findings_keep_their_kind_through_reuse():
    fps = [west_row("U2", "mcu", 30, 30, {3: "VDD_RF", 4: "MCU_EN"}),
           two_pad("C2", "c_en", 26.1, 29.5, ("GND", "MCU_EN")),
           two_pad("L2", "l_rf", 26.1, 30.75, ("VRF_IN", "VDD_RF"))]
    first = _fixed(fps)
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    again = b.resolve(reuse=first.reuse)
    assert [(f.kind, str(f)) for f in again.findings] == [(f.kind, str(f)) for f in first.findings]
