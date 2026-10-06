"""The two reported layout problems on the real board they were found on (fixtures/fairing/termination_row: the board as
written by a run, before its route): the display's reset line from the connector pinched between two termination
resistors, and three display lines whose pins on the MCU stand in the reverse of the order their terminations do."""
from pathlib import Path

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

BOARD = Path(__file__).resolve().parent.parent / "fixtures" / "fairing" / "termination_row" / "layout.kicad_pcb"
QUIET = frozenset(["GND", "V3V3", "MCU_EN", "BOOT_STRAP", "UART_TX", "UART_RX", "LED_STATUS", "LED_USB_K", "LED_BIKE"])
_read = {}


@pytest.fixture
def occ():
    if not _read:
        from placemat.kicad.read import read_board
        _read["g"] = read_board(str(BOARD))
    from placemat.occupancy import Occupancy
    o = Occupancy(_read["g"], edge_margin=0.0)
    o.quiet_nets = QUIET                    # the board's planes and free nets, as its script declares them
    return o


def test_the_reset_line_from_the_connector_is_pinched_between_two_terminations(occ):
    from placemat.approach import pinched
    from placemat.escapes import Escapes
    found = pinched(occ, Escapes(occ, mirror=False, depth=occ.settings.score_escape_depth))
    (f,) = [f for f in found if f["pad"] == ["U5", "4"]]
    assert f["net"] == "DISP_RST" and f["toward"] == ["U16", "21"] and f["layer"] == "F.Cu"
    assert sorted((n["ref"], n["net"]) for n in f["neighbours"]) == [("R6", "DISP_MOSI_P"), ("R7", "DISP_SCK_P")]
    assert f["gap_mm"] < 0.381 <= f["need_mm"] + 1e-9


def test_the_display_lines_reversed_between_the_mcu_and_their_terminations_are_a_notice(occ):
    from placemat.pin_order import reversed_groups
    (f,) = [f for f in reversed_groups(occ, studied=frozenset(["U16"])) if f["refs"] == ["U16", "U5"]]
    assert f["nets"][0] == ["DISP_SCK", "DISP_MOSI", "DISP_DC"] and f["pins"] == ["22", "23", "24"]
    assert [r for r, _ in f["far"]] == ["R5", "R6", "R7"]
    assert f["crossings"] == 6 and f["crossings_mirrored"] == 3
    assert f["rules"][0] == {"ref": "U16", "pool": True, "group": "display"}
