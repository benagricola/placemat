# placemat generate: --config switch_style=side
"""McuButtonsSide: the McuButtons cell with the side-actuated switches
(Panasonic EVQP7J01P): BOOT and RUN pressed by a pin through the case
wall, and the status LED. The switch's push plate sits on its local +Y
long side, so each switch is turned 180 to put the plate on the cell's
NORTH face, which is the face a board puts against its edge (declared
below as the cell's outward side). Pressing closes contact 1 (pads 1
and 1', the signal) to contact 2 (pads 2 and 2', the common rail); with
the turn, the rail pads are outboard and the signal pads inboard, so
every signal leaves the cell to the south.

The two switches are one row on the cell's north face, their plates
on one line at the frame's edge, so a board that puts the cell's north
face at its edge gets both plates at the edge, and a case one drill
line for two pins; the LED stands on the same line, centred level with
RUN. The cell has a frame for that row, sized from the row and the
band below it, that is never drawn: the board supplies the outline.
Each control's passive stands under it: the BOOT series resistor under BOOT,
the RUN pull-up and the reset cap under RUN, the LED series resistor
under the LED. The knockout labels sit in their own band south of the
passives, one per control, centred on it.

Nets that leave the cell end at their part, no stubs: boot_cs at R1's
south pad, v3v3 at R3's south pad, status at R2's south pad. The rails the
module owns, gnd and the pull-up's 3V3, take vias to the board's planes;
boot_com is the board's choice of rail and, like the signals, ends at
its part for the board to route. The module pours no ground.

Gate: DRC clean but for the via-in-pad and rail-via dangling reports
the house accepts for a fragment; every net routed or ended at its part.
"""
from placemat import board, Centre, CopperLayer, Edge, Net, PadRef, Part, X, Y
from placemat.geometry import Transform

SW_BOOT, SW_RUN, LED = Part("sw_boot"), Part("sw_run"), Part("d_status")
R_BOOT, R_RUN, C_RESET, R_LED = Part("r_boot"), Part("r_run_pu"), Part("c_reset"), Part("r_led")
BOOT_SW, RUN, LED_A, GND, BOOT_COM = Net("BOOT_SW"), Net("run"), Net("STATUS_LED_A"), Net("gnd"), Net("boot_com")
F = CopperLayer.F
W = board.netclass(RUN).track_width      # the cell's tracks: the class width, nothing asks for more

# ---------------------------------------------------------------- the numbers, each a choice
ROW_GAP = 0.0         # between the controls: courtyards touching; pins through a wall need nothing between them
MARGIN = 0.0          # the frame ends at the row and the labels: the board gives the cell its room
PASSIVE_GAP = 0.0     # a control's courtyard to its passive's: touching
PAIR_DX = 1.2         # the RUN pull-up and the reset cap side by side under RUN: two 0402 courtyards touching
LABEL_GAP = 0.0       # a label's box to the passive above it: touching
LABEL_SIZE = 0.9      # legible through a lid window, two lines of controls tall at most

# ---------------------------------------------------------------- measured from the generated fragment
SW_ROT = 180.0        # the push plate is on the switch's local +Y: turned, it faces the cell's north
LED_ROT = -90.0       # the LED stands on the controls' line, its pads north and south
sw_reach = board.reach(SW_BOOT, rotation=SW_ROT)          # body, pads and silk: what the label band measures from
led_reach = board.reach(LED, rotation=LED_ROT)
sw_claim = board.claim(SW_BOOT, rotation=SW_ROT)          # reach and courtyard: what touching means
led_claim = board.claim(LED, rotation=LED_ROT)
passive_claim = board.claim(R_BOOT, rotation=90.0)
def pad_off(part, key, rotation):
    """A pad's offset from its part's origin once the part is turned: measured at the generated rotation, then turned."""
    p, o = board.pad(part, key).location, board.part(part).location
    return Transform.rotate(rotation).apply((p.x - o.x, p.y - o.y))
SIG_DY = pad_off(SW_BOOT, 1, SW_ROT)[1]                                                # the signal pad row below the switch origin, turned
LED_A_DY = pad_off(LED, LED_A, LED_ROT)[1]                                             # the anode below the LED origin, turned
UNDER = (sw_claim.bottom - SIG_DY) + PASSIVE_GAP + passive_claim.height / 2            # signal pad row to the passive's centre line: courtyards touching
UNDER_LED = (led_claim.bottom - LED_A_DY) + PASSIVE_GAP + passive_claim.height / 2
LABEL_DOWN = (sw_claim.bottom - sw_reach.bottom) + PASSIVE_GAP + passive_claim.height + LABEL_GAP   # a control's reach to the band, past its passive's claim
LABEL_BAND = LABEL_SIZE * 1.6                                  # a knockout label's box height

# ---------------------------------------------------------------- the control row on the north face, and the frame it sets
controls = board.row([SW_BOOT, SW_RUN, LED], Edge.NORTH, gap=ROW_GAP, align="center", line="centre",
                     rotation=[SW_ROT, SW_ROT, LED_ROT],
                     why="both plates and the light on one line at the cell's north face, courtyards touching")
board.size(width=controls.length + 2 * (board.keep_in + MARGIN),
           height=2 * board.keep_in + controls.depth + LABEL_DOWN + LABEL_BAND + MARGIN, draw=False)

# ---------------------------------------------------------------- the passives under their controls
boot_sig, run_sig = PadRef(SW_BOOT, 1), PadRef(SW_RUN, 1)             # the inboard (signal) pads, west one of each pair
board.place(R_BOOT, at=Centre(X(SW_BOOT), Y(boot_sig, UNDER)), rotation=90.0,
            why="BOOT's series resistor centred under BOOT, its switch-side pad up")
board.place(C_RESET, at=Centre(X(SW_RUN, -PAIR_DX / 2), Y(run_sig, UNDER)), rotation=90.0,
            why="the reset cap under RUN, west of centre")
board.place(R_RUN, at=Centre(X(SW_RUN, PAIR_DX / 2), Y(run_sig, UNDER)), rotation=90.0,
            why="RUN's pull-up under RUN, east of centre")
board.place(R_LED, at=Centre(X(PadRef(LED, LED_A)), Y(PadRef(LED, LED_A), UNDER_LED)), rotation=90.0,
            why="the LED's series resistor under the LED, anode side up")

# ---------------------------------------------------------------- copper: each passive up into its switch, balanced about it
# A switch contact is two pads joined inside the part; the copper joins
# them too, and each passive meets that join so the block reads as one
# symmetric figure: BOOT's resistor, centred, runs straight up into the
# join; RUN's cap and pull-up, one each side of centre, each take the
# signal pad on their own side.
board.track(BOOT_SW, [PadRef(SW_BOOT, 1), PadRef(SW_BOOT, "1'")], layer=F, width=W)
board.track(BOOT_COM, [PadRef(SW_BOOT, 2), PadRef(SW_BOOT, "2'")], layer=F, width=W)
board.track(RUN, [PadRef(SW_RUN, 1), PadRef(SW_RUN, "1'")], layer=F, width=W)
board.track(GND, [PadRef(SW_RUN, 2), PadRef(SW_RUN, "2'")], layer=F, width=W)
board.track(BOOT_SW, [PadRef(R_BOOT, BOOT_SW), (X(R_BOOT), Y(boot_sig))], layer=F, width=W,
            why="straight up into the join between BOOT's signal pads")
board.track(RUN, [PadRef(C_RESET, RUN), PadRef(SW_RUN, "1'")], layer=F, width=W, why="the west passive to the west pad (1', turned)")
board.track(RUN, [PadRef(R_RUN, RUN), PadRef(SW_RUN, 1)], layer=F, width=W, why="the east passive to the east pad, its mirror")
board.track(LED_A, [PadRef(R_LED, LED_A), PadRef(LED, LED_A)], layer=F, width=W)

# the rails the module owns take a via to the board's planes: ground, and the pull-up's 3V3.
# boot_com is the board's choice of rail and boot_cs, run and status leave the module: they end at their part.
board.via(GND, PadRef(SW_RUN, 2), why="the board's ground plane picks RUN's common up here")
board.via(GND, PadRef(SW_RUN, "2'"), why="and here: the pair's other pad")
board.via(GND, PadRef(C_RESET, GND), why="the reset cap's ground, via-in-pad")
board.via(GND, PadRef(LED, GND), why="the LED cathode's ground, via-in-pad")
board.via(Net("v3v3"), PadRef(R_RUN, "v3v3"), why="the pull-up's rail from the board's 3V3 plane, via-in-pad")

# ---------------------------------------------------------------- labels: one line south of the passives, one per control
board.label([SW_BOOT, SW_RUN, LED], ["BOOT", "RUN", "MCU"], side=Edge.SOUTH, gap=LABEL_DOWN, size=LABEL_SIZE, knockout=True,
            why="the controls are a row, so their labels are one line: past the deepest control and its passive")

board.faces(outward=Edge.NORTH, handoff=Edge.SOUTH,
            why="the push plates face north; every signal leaves south")
