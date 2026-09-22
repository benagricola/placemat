# placemat generate: --config switch_style=top
"""McuButtons: the MCU's human interface, the top-actuated switches
(6 x 6 tactile): BOOT and RUN pressed from above, and the status LED.
Enclosure-driven: the controls set their own board position, so they
live outside the MCU cell. The two switches and the LED are one row on
the cell's north face, their centres on one line parallel to the edge a
board puts them against, so a case gets one drill line for two plungers
and a light pipe. The switches are turned so their common pads are
outboard (north, the ground fence) and the signal pads inboard: every
signal leaves the cell to the south.

The switches stand one passive apart: the reset cap, the RUN pull-up
and the BOOT series resistor stand in one column on the switches'
mid-axis, top to bottom, courtyards touching, so the cell ends at the
switches' own south edge; the LED's series resistor lies under the LED,
inside the switches' height, and the LED stands off RUN by what the
resistor is wider than it. The knockout labels are one line south of
the controls.

Nets that leave the cell end at their part, no stubs: boot_cs at the
BOOT resistor's south pad, status at the LED resistor's east pad, run at
RUN's signal pads. The rails the module owns, gnd and the pull-up's 3V3,
take vias to the board's planes; boot_com is the board's choice of rail
and ends at its switch. The module pours no ground.
"""
from placemat import board, Centre, CopperLayer, Edge, Mid, Net, PadRef, Part, X, Y
from placemat.geometry import Transform

SW_BOOT, SW_RUN, LED = Part("sw_boot"), Part("sw_run"), Part("d_status")
R_BOOT, R_RUN, C_RESET, R_LED = Part("r_boot"), Part("r_run_pu"), Part("c_reset"), Part("r_led")
BOOT_SW, RUN, LED_A, GND, V3V3 = Net("BOOT_SW"), Net("run"), Net("STATUS_LED_A"), Net("gnd"), Net("v3v3")
F = CopperLayer.F
W = board.netclass(RUN).track_width      # the cell's tracks: the class width, nothing asks for more

# ---------------------------------------------------------------- the numbers, each a choice
LABEL_SIZE = 0.9      # legible through a lid window
SW_ROT = 180.0        # the common (ground) pads north, the signal pads south
LED_ROT = 270.0       # the LED upright on the controls' line, cathode north to the ground fence


def pad_off(part, key, rotation):
    """A pad's offset from its part's origin once the part is turned."""
    p, o = board.pad(part, key).location, board.part(part).location
    return Transform.rotate(rotation).apply((p.x - o.x, p.y - o.y))


def upright(part, north_net):
    """The rotation that stands a two-pad part on end with `north_net`'s pad north."""
    return 90.0 if pad_off(part, north_net, 90.0)[1] < 0 else -90.0


def flat(part, east_net):
    """The rotation that lays a two-pad part along the row with `east_net`'s pad east."""
    return 0.0 if pad_off(part, east_net, 0.0)[0] > 0 else 180.0


sw_claim = board.claim(SW_BOOT, rotation=SW_ROT)
led_claim = board.claim(LED, rotation=LED_ROT)
col_h = [board.claim(p, rotation=90.0).height for p in (C_RESET, R_RUN, R_BOOT)]   # the column, top to bottom
COLUMN_GAP = max(board.claim(p, rotation=90.0).width for p in (C_RESET, R_RUN, R_BOOT))   # between the switches: the column's room
r_led_claim = board.claim(R_LED)
LED_STANDOFF = max(0.0, (r_led_claim.width - led_claim.width) / 2)   # the LED off RUN by what its resistor is wider than it

# ---------------------------------------------------------------- the control row on the north face, a frame around it
switches = board.row([SW_BOOT, SW_RUN], Edge.NORTH, gap=COLUMN_GAP, line="centre", rotation=SW_ROT,
                     why="both plungers on one line at the cell's north face, the passive column between them")
light = board.row([LED], Edge.NORTH, gap=LED_STANDOFF, after=switches, rotation=LED_ROT,
                  why="the light on the plungers' line, its resistor's width off RUN")
board.size(width=switches.length + LED_STANDOFF + max(light.length, r_led_claim.width) + 2 * board.keep_in,
           height=2 * board.keep_in + switches.depth + LABEL_SIZE * 1.6, draw=False)

# ---------------------------------------------------------------- the passive column between the switches, the LED's resistor under it
column = X(Mid(SW_BOOT, SW_RUN))
board.place(C_RESET, at=Centre(column, Y(SW_BOOT, sw_claim.top + col_h[0] / 2)), rotation=upright(C_RESET, GND),
            why="the reset cap at the column's top, its ground pad in the fence row")
board.place(R_RUN, at=Centre(column, Y(C_RESET, col_h[0] / 2 + col_h[1] / 2)), rotation=upright(R_RUN, RUN),
            why="the pull-up under the cap, run pad to run pad")
board.place(R_BOOT, at=Centre(column, Y(R_RUN, col_h[1] / 2 + col_h[2] / 2)), rotation=upright(R_BOOT, BOOT_SW),
            why="the BOOT resistor at the column's foot, boot_cs the cell's south extreme")
board.place(R_LED, at=Centre(X(LED), Y(LED, led_claim.height / 2 + r_led_claim.height / 2)), rotation=flat(R_LED, Net("status")),
            why="the LED's resistor under the LED, status east for the board")

# ---------------------------------------------------------------- copper
# a switch contact is two pads joined inside the part; the copper joins them too
board.track(BOOT_SW, [PadRef(SW_BOOT, 2), PadRef(SW_BOOT, 1)], layer=F, width=W)
board.track(RUN, [PadRef(SW_RUN, 2), PadRef(SW_RUN, 1)], layer=F, width=W)
board.track(BOOT_SW, [PadRef(SW_BOOT, 1), PadRef(R_BOOT, BOOT_SW)], layer=F, width=W,
            why="off BOOT's east signal pad into the resistor at the column's foot")
board.track(RUN, [PadRef(C_RESET, RUN), PadRef(R_RUN, RUN)], layer=F, width=W, why="cap to pull-up, straight down the column")
board.track(RUN, [PadRef(R_RUN, RUN), PadRef(SW_RUN, 2)], layer=F, width=W, why="the pull-up to RUN's west signal pad")
board.track(LED_A, [PadRef(R_LED, LED_A), PadRef(LED, LED_A)], layer=F, width=W)

# the rails the module owns take a via to the board's planes: ground, and the pull-up's 3V3;
# BOOT's common is boot_com, the board's choice of rail, so its pads stay bare for the board
board.via(GND, PadRef(SW_RUN, 3), why="RUN's common pads: the ground fence")
board.via(GND, PadRef(SW_RUN, 4))
board.via(GND, PadRef(LED, GND), why="the LED cathode, via-in-pad")
board.via(GND, PadRef(C_RESET, GND), why="the reset cap's ground, via-in-pad")
board.via(V3V3, PadRef(R_RUN, V3V3), why="the pull-up's rail from the board's 3V3 plane, via-in-pad")

# ---------------------------------------------------------------- labels: one line south of the controls
board.label([SW_BOOT, SW_RUN, LED], ["BOOT", "RUN", "MCU"], side=Edge.SOUTH, size=LABEL_SIZE, knockout=True,
            why="the controls are a row, so their labels are one line")

board.faces(outward=Edge.NORTH, handoff=Edge.SOUTH, why="the plungers face north; every signal leaves south")
