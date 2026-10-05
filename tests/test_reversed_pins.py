"""Two parts joined by three or more lines whose pins stand in reverse order along their facing edges, so their straight
airwires cross where the mirrored order would not: a `pins.reversed` notice, raised once on the finished board."""
import dataclasses

from placemat.board_geometry import Footprint
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, Face, Location, Part
from tests.fixtures import board_geometry, pad

YS = (28.0, 28.5, 29.0, 29.5, 30.0, 30.5)       # the pins' y, north to south


def column(ref, inst, x, nets, fields=None):
    """A part with a column of pads at x, pin 1 northmost, one per entry of `nets`."""
    pads = tuple(pad(ref, inst, k + 1, n, x, y, 0.8, 0.3) for k, (y, n) in enumerate(zip(YS, nets)))
    body = Box(x - 0.6, YS[0] - 0.4, x + 0.6, YS[-1] + 0.4)
    return Footprint(ref, inst, None, ref, Location(x, 29.25), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads,
                     fields=dict(fields or {}))


def resolve(fps, pin_study=True, **settings):
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True,
              settings=dataclasses.replace(Settings(), cleanup_enabled=False, **settings))
    b.pin_study = pin_study
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b.resolve()


def reversed_(plan) -> list:
    return [f for f in plan.findings if f.cause is C.PINS_REVERSED]


BUS = ["", "D0", "D1", "D2", "D3", ""]


def test_a_bus_whose_order_is_reversed_between_two_parts_is_a_notice_with_the_crossings_a_mirror_removes():
    """The reported case: four lines from U1's east column to J1's west column, D0 northmost on U1 and southmost on J1,
    so each straight airwire crosses the other three."""
    (f,) = reversed_(resolve([column("U1", "mcu", 30.0, BUS), column("J1", "conn", 40.0, BUS[::-1])]))
    assert f.severity == "notice" and f.kind == "pins"
    assert f.facts["refs"] == ["J1", "U1"]
    assert f.facts["nets"] == [["D3", "D2", "D1", "D0"], ["D0", "D1", "D2", "D3"]]
    assert f.facts["pins"] == ["2", "3", "4", "5"] and f.facts["far"] == [["U1", "2"], ["U1", "3"], ["U1", "4"], ["U1", "5"]]
    assert f.facts["crossings"] == 6 and f.facts["crossings_mirrored"] == 0
    assert f.facts["mirror"] == "J1" and f.facts["mirror_also"] == "U1"
    assert f.facts["rules"] == [{"ref": "J1", "pool": False, "group": ""}, {"ref": "U1", "pool": False, "group": ""}]
    assert f == ("J1 and U1: D3, D2, D1, D0 stand in that order along J1 (pins 2, 3, 4, 5) and the other way round where "
                 "their airwires from J1 land (U1 pins 2, 3, 4, 5), so the straight airwires between J1 and U1 cross 6 "
                 "times; mirrored on J1 or on U1 they would cross 0 times; neither part has a Pm.PinPool holding those "
                 "pins, so the pin map study does not reorder them")


def test_a_bus_in_the_same_order_at_both_ends_is_no_finding():
    assert reversed_(resolve([column("U1", "mcu", 30.0, BUS), column("J1", "conn", 40.0, BUS)])) == []


def test_two_lines_reversed_are_under_the_group_size():
    two = ["", "D0", "D1", "", "", ""]
    assert reversed_(resolve([column("U1", "mcu", 30.0, two), column("J1", "conn", 40.0, ["", "D1", "D0", "", "", ""])])) == []


def test_lines_through_series_terminations_count_as_one_line_each():
    """U1's lines reach J1 through a column of termination resistors: the order is reversed between U1 and the
    resistors, where their airwires from U1 land, and the crossings are counted on both legs of each line."""
    from tests.test_cleanup_swaps import two_pad
    mcu = ["", "D0", "D1", "D2", "D3", ""]
    fps = [column("U1", "mcu", 30.0, mcu), column("J1", "conn", 40.0, ["", "P0", "P1", "P2", "P3", ""])]
    for k, y in enumerate(YS[1:5]):                     # R1 (northmost) joins D3 to P0, ... R4 joins D0 to P3
        fps.append(two_pad("R%d" % (k + 1), "r%d" % (k + 1), 35.0, y, ("D%d" % (3 - k), "P%d" % k)))
    (f,) = reversed_(resolve(fps))
    assert f.facts["nets"] == [["D0", "D1", "D2", "D3"], ["D3", "D2", "D1", "D0"]]
    assert f.facts["far"] == [["R1", "1"], ["R2", "1"], ["R3", "1"], ["R4", "1"]]
    assert "where their airwires from U1 land (R1 pin 1, R2 pin 1, R3 pin 1, R4 pin 1), so" in f
    assert f.facts["crossings"] == 6 and f.facts["crossings_mirrored"] == 0
    assert f.facts["mirror"] == "U1" and f.facts["mirror_also"] == ""     # the side where mirroring removes them


def test_a_pool_and_a_group_holding_the_pins_are_said_and_the_mirror_is_on_that_part():
    """With the pin map study off, the notice stands, mirrored on the part whose Pm.PinGroup holds the pins."""
    fields = {"Pm.PinPool": "1-6", "Pm.PinGroup": "bus:2-5"}
    (f,) = reversed_(resolve([column("U1", "mcu", 30.0, BUS, fields), column("J1", "conn", 40.0, BUS[::-1])],
                             pin_study=False))
    assert f.facts["mirror"] == "U1" and f.facts["refs"] == ["U1", "J1"] and f.facts["mirror_also"] == ""
    assert f.facts["rules"][0] == {"ref": "U1", "pool": True, "group": "bus"}
    assert f.endswith("mirrored on U1 they would cross 0 times; U1's Pm.PinGroup bus holds those pins, so the pin map "
                      "study may reorder them")


def test_where_the_pin_map_study_gives_a_map_for_the_part_its_advice_stands_alone():
    fields = {"Pm.PinPool": "1-6"}
    plan = resolve([column("U1", "mcu", 30.0, BUS, fields), column("J1", "conn", 40.0, BUS[::-1])],
                   pins_budget_steps=10 ** 6, pins_guard_ms=0.0)
    assert [f.cause for f in plan.findings if f.kind == "pins"] == [C.PINS_REMAP]
