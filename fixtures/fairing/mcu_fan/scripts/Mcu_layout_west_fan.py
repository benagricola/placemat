"""Mcu: the ESP32-S3 and everything that has to sit at its pins.

A fragment, stamped onto the core as the cell `logic`. The chip (the
S3FH4R2, or the S3R8 with its external quad flash, as Mcu.zen's `chip`
chooses), the 40 MHz crystal and its loads, the RF chip-side match, the RF
supply filter, the decoupling, the straps and the reset RC are laid out here
once, so the oscillator loop, the bypasses and on the S3R8 the memory bus
keep their lengths wherever the core puts the cell. The BLE antenna and its matching positions
are not here: they are Ble.zen, on the south arm, at the far end of RF_50.

WHICH SIDE IS WHICH. The chip is turned so its LNA_IN side (pins 1-14) faces
south, +y in this frame, toward the antenna on the core's south arm; the core
places the cell unturned. That puts the SPI pins (29-35) on the north side,
where the S3R8's flash stands, and the crystal pins (53-54) on the west, where
the crystal stands.

Every pin number below is the ESP32-S3 datasheet's (Table 2-1), and each is
also in docs/decisions/schematics/core-netlist.xml.

DECLARED BY INTENT. The chip is the fragment's own datum, `Location(0, 0)`;
its rotation is read off its pin 1 pad, not typed (a turn, never a
position). The arrangement is Ben's hand layout of 2026-09-27, said as
relations: the pins whose tracks leave straight out of the row - LNA_IN,
VDD3P3 twice and CHIP_PU south, XTAL_N west - are escapes
(`board.escape`), and the parts round them stand beside those risers, a
clearance off a pin's end (`Past`), or level with the pad they serve. The
match's series inductor is searched under its LNA_IN link, riding its two
shunts, into the corner the RF bypass and VDDA's 1 uF leave. RF_50's way
out south is an escape of the inductor's own pad, with the reset capacitor
and the RF filter's inductor standing either side of it. A net that lands
on several of the chip's pads (V3V3 at pins 20, 46, 55 and 56) is linked by
the pin NUMBER it bypasses, never by net name alone. The frame is
`board.size(fit=True)`, its content checked against the room the core
actually has for this cell before the fit is taken
(`docs/decisions/layout/mcu-module-routing-2026-09-27.md`).

THE PINS' WAYS OUT (Ben's hand layout of 2026-10-02). Every pin with a net
leaves on an escape: the west row's GPIO fan out at 45 degrees to the
north-west, either side of VDD3P3_CPU's bypass; the south row's GPIO0-3
and LD1-SDA fan out to the south-east, with GNSS_PPS, BL_PWM and SCL
straight down between them; the east and north rows' GPIO leave straight
out. The straps, the console's series resistor and the status light's
resistor are drawn to their pins along those lanes; the other lanes end as
stubs where the core's router takes them.
"""
from placemat import board, Along, Beside, Bend, Corner, CopperLayer, Edge, Facing, LinkWeight, Location, Net, PadRef, Part, Past

from fragment_frame import frame_planes

# --- limits, as in Core_layout.py --------------------------------------------
DECOUPLING_LIMIT = 2.0   # a bypass beyond this is a bulk capacitor, not a bypass
RF_CHAIN_LIMIT = 1.5     # 2.4 GHz match: every extra millimetre is loss and phase
XTAL_LIMIT = 2.5         # load capacitors inside the oscillator's own loop
FLASH_BUS_LIMIT = 5.0    # the quad bus runs at 80 MHz; the flash stands at its pins
STRAP_LIMIT = 6.0        # a strap or pull-up across the fanout band from its pin
FANOUT_BAND = 2.0        # mm round the chip's pads: a bypass's depth, and room for GPIO tracks and vias past it

# --- the chip's pins ----------------------------------------------------------
LNA_IN_PIN = 1
VDD3P3_PINS = (2, 3)         # the RF supply, behind l_rf_supply
CHIP_PU_PIN = 4
VDD3P3_RTC_PIN = 20
VDD_SPI_PIN = 29
VDD3P3_CPU_PIN = 46
VDDA_PINS = (55, 56)
CPU_BYPASS_ROW_PIN = 45      # VDD3P3_CPU's bypass stands with its V3V3 pad level with this pin, the fans either side of it
NC_EAST_PIN = 39             # among GPIO33-37 (pins 38-42), unconnected in this design: the reservoir's GND end

# The room the core has for the cell between the two input tabs, which are
# through-hole and claim both faces (15.9 mm), less the board's own spacing
# (docs/decisions/layout/mcu-module-routing-2026-09-27.md). The fit frame is
# checked against it below; nothing here types a floorplan from it.
CELL_WIDTH = 15.4
SERIES_ROW = 2.4         # mm between the chip's body and the flash's: the 0 ohm links' row
FLASH_ROTATION = 90      # the WSON's pad rows east and west, its body across the chip's north side
VIA, VIA_DRILL = 0.45, 0.20       # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
EP_VIA_PITCH = 1.0       # the S3R8 footprint's 3 x 3 ground vias in its exposed pad, at this pitch
FILLET = 0.15            # the ground/supply zones' corner radius (layout conventions, electronics/CLAUDE.md)
RF_SUPPLY_WIDTH = 0.508  # 20 mil RF supply trunk, Espressif layout guidance
SUPPLY_ENTRANCE_WIDTH = 0.635  # 25 mil main supply path, Espressif layout guidance
CLEAR = board.netclass(Net("V3V3")).clearance
TRACK = board.netclass(Net("V3V3")).track_width
LANE = TRACK + 2.0 * CLEAR       # a fanout lane: one track and its clearance either side


def has_net(name):
    """Whether the generated board carries this net."""
    try:
        board.net(Net(name))
        return True
    except KeyError:
        return False


# The S3R8 build carries the external flash's bus; the S3FH4R2's flash and
# PSRAM are in the package, and its SPI pins are unconnected.
EXTERNAL_FLASH = has_net("FLASH_CS")

# The fragment's own supply nets are the core's planes. They seed nothing here
# either, so nothing is pulled to the middle of every ground pad.
board.free_net(Net("GND"))
board.free_net(Net("V3V3"))

# The 50 ohm class keeps 0.2 mm (its coplanar gap); the match's 0201 parts
# hold their own lands closer, 0.18 mm. The two pairs of nets they separate
# take the lands' gap, which is a footprint-land fact, not a placement.
def land_gap(part, a, b):
    """The copper gap between two of a part's own pads, which its land
    pattern sets."""
    p, q = board.pad(Part(part), a).box, board.pad(Part(part), b).box
    return max(q.left - p.right, p.left - q.right, q.top - p.bottom, p.top - q.bottom)


RF_LAND_GAP = min(land_gap("c_rf_50", "RF_50", "GND"), land_gap("l_rf_match", "RF_CHIP", "RF_50"))
board.rule(clearance=RF_LAND_GAP, between=("RF_50", "GND"), why="the 0201 RF_50 shunt's own lands")
board.rule(clearance=RF_LAND_GAP, between=("RF_CHIP", "RF_50"), why="the 0201 match inductor's own lands")

# --- the chip -----------------------------------------------------------------
# The fragment's own datum: everything else is said relative to it or to
# another part already placed from it. The chip turns so its LNA_IN side
# (pins 1-14) faces south (+y); the two chips' footprints start their pin
# rows on different sides, so the turn is read off which side pin 1 stands
# on (a turn, not a position).
_pin1 = board.pad(Part("mcu"), LNA_IN_PIN).box.center
_body = board.part(Part("mcu")).courtyard_box.center
_dx, _dy = _pin1.x - _body.x, _pin1.y - _body.y
if abs(_dy) >= abs(_dx):
    MCU_ROTATION = 0 if _dy > 0 else 180     # pin 1's row is south or north
else:
    MCU_ROTATION = 90 if _dx < 0 else 270    # pin 1's row is west or east
board.place(Part("mcu"), at=Location(0, 0), rotation=MCU_ROTATION, why="the fragment's own datum")

# The chip's only ground is its exposed pad. The S3R8's footprint carries a
# grid of ground vias in it; the S3FH4R2's carries none, so the pad is filled
# here at the S3R8's pitch (Espressif: at least nine ground vias).
EP_PIN = 57
if not EXTERNAL_FLASH:
    board.vias(Net("GND"), PadRef(Part("mcu"), EP_PIN), pitch=EP_VIA_PITCH, size=VIA, drill=VIA_DRILL)

# --- the fanout band round the chip ------------------------------------------
# The chip's GPIO leave on the east, south and west sides, so a band round
# those pad rows is kept for their tracks and vias: only the bypasses and what
# is linked short to a pin stand in it, and the straps, pull-ups and other
# resistors land just outside it, across from the pin each serves. On the S3R8
# the north side is the memory bus, whose escape is the flash's series links;
# on the S3FH4R2 it carries two GPIO (SPICLK_P/N) and keeps a band too.
FANOUT_SIDES = [Edge.EAST, Edge.SOUTH, Edge.WEST] + ([] if EXTERNAL_FLASH else [Edge.NORTH])
board.fanout(Part("mcu"), depth=FANOUT_BAND, sides=FANOUT_SIDES, why="the GPIO escape")

# --- the pins' ways out (Ben's hand layout, 2026-10-02) ------------------------
# The east and north rows' GPIO leave straight out. The west row's GPIO
# (pins 43-52, either side of VDD3P3_CPU's bypass) fan out north-west at 45
# degrees and the south row's south-east; the module's own routes run on from
# their lanes into their parts, the rest end as stubs.
# VBUS_DISCH and USB_WET turn north-west over VDD3P3_CPU's bypass, the pin
# nearer the row's north end first (Ben, 2026-10-02: the pins nearest a row's
# end turn out first).
# One escape over the west row: pins 43-45 over VDD3P3_CPU's bypass and 47 and 49 under it (48 and 50-52 keep to their
# own routes), the lower lanes starting past the bypass that stands beside the chip.
esc_west = board.escape(Part("mcu"), ["LED_STATUS_DRIVE", "VBUS_DISCH", "USB_WET", "PD_IRQ", "UART_TX_CHIP"], turn=Corner.NW,
                        why="pins 43-45, 47 and 49 out north-west, over and under VDD3P3_CPU's bypass")
# The south row's GPIO0-SCL fan out south-east, the pins nearer the row's
# east end turning first, each 45 a lane long. GPIO0's and GPIO3's routes run
# on along their 45s and drop straight into their straps; the others end as
# stubs (Ben's hand layout, 2026-10-02).
esc_south_fan = board.escape(Part("mcu"), ["BOOT_STRAP", "GNSS_TX", "GNSS_RX", "STRAP_JTAG", "GNSS_PPS", "BL_PWM", "LD1",
                                           "LD2", "SDA", "SCL"], turn=Corner.SE, run=LANE,
                             why="pins 5-14 fan out south-east, to GPIO0's and GPIO3's straps and past them")
esc_east = board.escape(Part("mcu"), ["RING_INT", "INA_ALERT", "DISP_CS", "DISP_RST", "DISP_SCK", "DISP_MOSI", "DISP_DC",
                                      "DISP_TE", "EXCITE", "USB_D_N", "USB_D_P", "IMU_INT1"],
                        why="the east row's GPIO straight out")
esc_north = board.escape(Part("mcu"), ["VBUS_EN", "SCL_PWR"], why="pins 36-37 straight out past the reservoir")

# --- the oscillator's loop and VDDA ------------------------------------------
# Espressif's own ESP32-S3 layout (hardware design guidelines, PCB layout,
# "Crystal", accessed 2026-09-27) is ported: the crystal stands clear of the
# clock pins, the series component on XTAL_P sits at the chip, the loads sit
# on the crystal's two sides at the ends of the clock traces with their
# grounds by the crystal's, and the clock traces take no vias. VDDA's
# bypasses stand at pins 55-56 under the series component, as in that
# figure (Ben's hand layout, 2026-09-27).
#
# XTAL_N leaves pin 53 west on its own riser, over the series inductor,
# steps 45 degrees up past the crystal's north-east pad, runs west a
# clearance above the crystal and turns down into its north-west pad: over
# the crystal, never under it. The riser is an escape, so the inductor
# stands clear of it.
esc_xtal = board.escape(Part("mcu"), [53], why="XTAL_N out of the west row, over the series inductor")
board.link(PadRef(Part("l_xtal"), "XTAL_P"), PadRef(Part("mcu"), "XTAL_P"),
           weight=LinkWeight.SHORT, limit_mm=XTAL_LIMIT, why="XTAL_P's series part at the chip")
board.place(Part("l_xtal"), at=Beside(esc_xtal, Edge.SOUTH, align=("XTAL_P", Past([PadRef(Part("mcu"), 54)], Edge.WEST))),
            rotation=180, why="XTAL_P's series part a clearance off pin 54's end, under XTAL_N's riser")
board.place(Part("xtal"), at=Beside(Part("l_xtal"), Edge.WEST, align=(2, PadRef(Part("mcu"), VDDA_PINS[0]))),
            rotation=90, why="the crystal west of its series part, its north pads level with VDDA's first pin, a pin "
                             "below XTAL_P so the straps over it leave the UART pins' fan room (Ben, 2026-10-02)")
board.link(PadRef(Part("xtal"), "XTAL_N"), PadRef(Part("mcu"), "XTAL_N"), weight=LinkWeight.SHORT,
           why="the crystal on its clock pins, inside their fanout band as Espressif places it; "
               "placed by its series inductor, so no limit of its own")
# The loads on the crystal's own two sides: XTAL_1's under it, XTAL_N's over
# it, a lane above the crystal so XTAL_N's run passes between them.
board.place(Part("c_xtal1"), at=Beside(Part("xtal"), Edge.SOUTH, align=PadRef(Part("xtal"), "XTAL_1")),
            rotation=180, why="XTAL_1's load on the crystal's south side, XTAL_1 pads in one column")
# XTAL_N's load stands against the crystal's north silk (Ben, 2026-10-02):
# XTAL_N's run passes between the two parts' pads, which the silk already
# holds more than a lane apart.
board.place(Part("c_xtal2"), at=Beside(Part("xtal"), Edge.NORTH, align=PadRef(Part("xtal"), "XTAL_N")),
            rotation=0, why="XTAL_N's load on the crystal's north side, XTAL_N's run between their pads")

# VDDA's bypasses under the series inductor, their V3V3 pads in one column a
# clearance off pin 54's end, as the inductor's XTAL_P pad is.
board.link(PadRef(Part("c_vdda_10n"), "V3V3"), PadRef(Part("mcu"), VDDA_PINS[1]),
           weight=LinkWeight.SHORT, limit_mm=DECOUPLING_LIMIT, why="VDDA's bypass by its pins")
board.place(Part("c_vdda_10n"), at=Beside(Part("l_xtal"), Edge.SOUTH, align=("V3V3", Past([PadRef(Part("mcu"), 54)], Edge.WEST))),
            rotation=180, why="VDDA's 10 nF under the series inductor, V3V3 pad at pins 55-56")
board.place(Part("c_vdda_1u"), at=Beside(Part("c_vdda_10n"), Edge.SOUTH, align=PadRef(Part("c_vdda_10n"), "V3V3")),
            rotation=180, why="VDDA's 1 uF under its 10 nF, V3V3 pads in one column")
board.link(PadRef(Part("c_vdda_1u"), "V3V3"), PadRef(Part("mcu"), VDDA_PINS[1]),
           weight=LinkWeight.SHORT, limit_mm=DECOUPLING_LIMIT, why="VDDA's 1 uF by its pins")

# --- the south-west corner: RF match, RF supply bypass and reset --------------
# Under pins 1-4 the south row carries LNA_IN, VDD3P3 twice and CHIP_PU.
# LNA_IN and CHIP_PU leave straight south on their own risers (an escape, so
# nothing stands on them). From the east: CHIP_PU runs down its lane to the
# reset pull-up; c_rf_post takes VDD3P3 from pins 2 and 3 into its pad under
# one pour, a clearance west of that lane, and drops it to the filter on an
# inner layer; the RF match's series inductor stands west of c_rf_post under
# LNA_IN, its two shunts west of its two pads (Espressif: a CLC at the pin,
# 0201 parts).
esc_south = board.escape(Part("mcu"), [LNA_IN_PIN, CHIP_PU_PIN],
                         why="LNA_IN and CHIP_PU straight south to their parts")
board.link(PadRef(Part("c_rf_post"), "VDD_RF"), PadRef(Part("mcu"), VDD3P3_PINS[1]), weight=LinkWeight.SHORT,
           limit_mm=DECOUPLING_LIMIT, why="VDD3P3's bypass at pins 2-3, inside their fanout band")
board.place(Part("c_rf_post"), at=Beside(Part("mcu"), Edge.SOUTH,
                                         align=("VDD_RF", Past([PadRef(Part("mcu"), CHIP_PU_PIN)], Edge.WEST))),
            rotation=270, why="VDD3P3's bypass upright under pins 2-3, a clearance west of CHIP_PU's lane")
board.link(PadRef(Part("l_rf_match"), "RF_CHIP"), PadRef(Part("mcu"), LNA_IN_PIN),
           weight=LinkWeight.SHORT, limit_mm=RF_CHAIN_LIMIT, why="the match sits on the chip's own LNA_IN pad")
board.place(Part("l_rf_match"), rotation=270,
            why="the match's series inductor under LNA_IN, searched into the corner west of the RF bypass and "
                "under VDDA's 1 uF, RF_50 south toward the antenna")
board.place(Part("c_rf_chip"), at=Beside(Part("l_rf_match"), Edge.WEST, align=PadRef(Part("l_rf_match"), "RF_CHIP")),
            rotation=180, why="the chip-side shunt west of the series inductor's LNA_IN pad")
board.place(Part("c_rf_50"), at=Beside(Part("l_rf_match"), Edge.WEST, align=PadRef(Part("l_rf_match"), "RF_50")),
            rotation=180, why="the antenna-side shunt west of the series inductor's RF_50 pad")

# RF_50 leaves the series inductor straight south toward the core's antenna,
# and nothing stands on that way out: the reset capacitor east of it and the
# RF supply filter west of it each stand off it. It runs past the filter's
# row, which stands upright under the antenna-side shunt, so on the core it
# can turn west round the row toward the antenna (Ben, 2026-10-02): the
# shunt's half and an upright part's length.
RF_WAY_OUT = (board.part(Part("c_rf_50")).courtyard_box.height / 2.0
              + board.part(Part("l_rf_supply")).courtyard_box.width)
esc_rf = board.escape(Part("l_rf_match"), ["RF_50"], depth=RF_WAY_OUT,
                      why="RF_50's way out south past the RF supply filter, toward the core's antenna")

# The reset capacitor east of RF_50's way out, level with its end; the
# pull-up east of it, MCU_EN pads in one row, CHIP_PU's lane running down to
# them.
board.link(PadRef(Part("r_en"), "MCU_EN"), PadRef(Part("mcu"), CHIP_PU_PIN), weight=LinkWeight.SHORT,
           limit_mm=STRAP_LIMIT, why="the reset pull-up under CHIP_PU's own lane")
board.place(Part("c_en"), at=Beside(esc_rf, Edge.EAST, align=Along.END),
            rotation=270, why="the reset capacitor east of RF_50's way out, level with its end")
board.place(Part("r_en"), at=Beside(Part("c_en"), Edge.EAST, align=PadRef(Part("c_en"), "MCU_EN")),
            rotation=90, why="the reset pull-up east of its capacitor, MCU_EN pads in one row")
board.link(PadRef(Part("c_en"), "MCU_EN"), PadRef(Part("mcu"), CHIP_PU_PIN), weight=LinkWeight.SHORT,
           limit_mm=STRAP_LIMIT, why="the reset capacitor beside CHIP_PU's own lane")
# GPIO0's pull-up east of the reset pull-up, GPIO3's a lane and a track
# further (GNSS_TX and GNSS_RX fan out over the gap).
board.link(PadRef(Part("r_boot"), "BOOT_STRAP"), PadRef(Part("mcu"), 5), weight=LinkWeight.SHORT,
           limit_mm=STRAP_LIMIT, why="GPIO0's pull-up at its pin")
board.place(Part("r_boot"), at=Beside(Part("r_en"), Edge.EAST, align=("BOOT_STRAP", PadRef(Part("r_en"), "MCU_EN"))),
            rotation=90, why="GPIO0's pull-up east of the reset pull-up, pads in one row")
board.link(PadRef(Part("r_strap3"), "STRAP_JTAG"), PadRef(Part("mcu"), 8), weight=LinkWeight.SHORT,
           limit_mm=STRAP_LIMIT, why="GPIO3's strap at its pin")
board.place(Part("r_strap3"), at=Beside(Part("r_boot"), Edge.EAST, gap=LANE + TRACK,
                                        align=("STRAP_JTAG", PadRef(Part("r_boot"), "BOOT_STRAP"))),
            rotation=90, why="GPIO3's strap a lane and a track east of GPIO0's: pins 6-7's stubs end over the gap, and "
                             "GPIO3's lane lands on it from the south-east (Ben, 2026-10-02)")

# --- the RF supply filter and the shared reservoir ---------------------------
# The filter stands in one row under the antenna-side shunt, west of RF_50's
# way out: the inductor, its 100 nF and its 1 uF, each upright with its V3V3
# pad south, one fill joining the three (Ben, 2026-10-02). RF_50 passes the
# row on its south. The reservoir shared with the RF supply reaches it
# through the plane pair
# (docs/decisions/schematics/mcu-rf-supply-reservoir-2026-09-27.md).
board.place(Part("l_rf_supply"), at=Beside(Part("c_rf_50"), Edge.SOUTH, align=Along.END),
            rotation=Facing(PadRef(Part("l_rf_supply"), "V3V3"), Edge.SOUTH),
            why="the RF filter's inductor upright under the antenna-side shunt, west of RF_50's way out")
board.place(Part("c_rf_pre_100n"), at=Beside(Part("l_rf_supply"), Edge.WEST, align=("V3V3", PadRef(Part("l_rf_supply"), "V3V3"))),
            rotation=Facing(PadRef(Part("c_rf_pre_100n"), "V3V3"), Edge.SOUTH),
            why="the filter's 100 nF upright west of the inductor, V3V3 level with its V3V3 pad")
board.place(Part("c_rf_pre_1u"), at=Beside(Part("c_rf_pre_100n"), Edge.WEST, align=("V3V3", PadRef(Part("c_rf_pre_100n"), "V3V3"))),
            rotation=Facing(PadRef(Part("c_rf_pre_1u"), "V3V3"), Edge.SOUTH),
            why="the filter's 1 uF upright west of the 100 nF, V3V3 pads in one row")
# The shared reservoir lies along GPIO33-37 (pins 38-42), which this design
# leaves unconnected, so it blocks no pin's escape and keeps the south-west
# corner clear for RF_50's way to the antenna (Ben, 2026-10-02). Lying flat
# it stands no further north than VDD_SPI's bypasses; its GND end over pin 39
# keeps it clear of pin 37's exit, V3V3 toward VDD3P3_CPU's corner.
board.link(PadRef(Part("c_mcu_bulk"), "V3V3"), PadRef(Part("mcu"), VDD3P3_CPU_PIN), weight=LinkWeight.SHORT,
           why="the reservoir by VDD3P3_CPU's corner of the chip")
board.place(Part("c_mcu_bulk"), at=Beside(Part("mcu"), Edge.NORTH, align=("GND", PadRef(Part("mcu"), NC_EAST_PIN))),
            rotation=Facing(PadRef(Part("c_mcu_bulk"), "V3V3"), Edge.WEST),
            why="the shared reservoir lying along the unconnected pins 38-42, V3V3 toward VDD3P3_CPU's corner")

# --- the west edge past the crystal: GPIO45-46 straps ------------------------
# The two straps stack up from XTAL_N's load, as near their pins' row as the
# crystal lets them; their pins' lanes run into them from the south-east.
board.link(PadRef(Part("r_strap46"), "STRAP_DOWNLOAD"), PadRef(Part("mcu"), 52), weight=LinkWeight.SHORT,
           limit_mm=STRAP_LIMIT, why="GPIO46's strap at its pin")
board.place(Part("r_strap46"), at=Beside(Part("c_xtal2"), Edge.NORTH, align=Along.START), rotation=180,
            why="GPIO46's strap just over the crystal's north load")
board.link(PadRef(Part("r_strap45"), "STRAP_VSPI"), PadRef(Part("mcu"), 51), weight=LinkWeight.SHORT,
           limit_mm=STRAP_LIMIT, why="GPIO45's strap at its pin")
board.place(Part("r_strap45"), at=Beside(Part("r_strap46"), Edge.NORTH, align=Along.START), rotation=180,
            why="GPIO45's strap a silk gap over GPIO46's")

# --- the console and the status light ----------------------------------------
board.link(PadRef(Part("r_uart_tx"), "UART_TX_CHIP"), PadRef(Part("mcu"), "UART_TX_CHIP"),
           weight=LinkWeight.PREFER, why="the console's series resistor at the chip")
board.place(Part("r_uart_tx"), at=Beside(Part("r_strap45"), Edge.NORTH, align=Along.START, gap=LANE),
            rotation=Facing(PadRef(Part("r_uart_tx"), "UART_TX_CHIP"), Edge.EAST),
            why="the console's series resistor in line with the straps, a lane over them for UART_RX's way out (Ben, 2026-10-02)")
board.link(PadRef(Part("r_led_status"), "LED_STATUS_DRIVE"), PadRef(Part("mcu"), "LED_STATUS_DRIVE"),
           weight=LinkWeight.PREFER, why="the status light's resistor at the chip")
board.place(Part("r_led_status"), at=Beside(Part("c_mcu_bulk"), Edge.WEST, align=Along.MID),
            rotation=Facing(PadRef(Part("r_led_status"), "LED_STATUS_DRIVE"), Edge.SOUTH),
            why="the status light's resistor west of the reservoir, over the chip's north-west corner: LED_STATUS_DRIVE "
                "fans up to it from pin 43 clear of VDD3P3_CPU's bypass (Ben, 2026-10-02)")

# --- the bypasses on the other three sides -----------------------------------
# Each stands a fanout lane off its pin (the tracks of the pins beside it pass
# between), VDD_SPI's two across the north row at pin 29. V3V3 lands on four
# pads, so each bypass is linked to its OWN pin by number.
board.link(PadRef(Part("c_vspi_1u"), "VDD_SPI"), PadRef(Part("mcu"), VDD_SPI_PIN), weight=LinkWeight.SHORT,
           limit_mm=DECOUPLING_LIMIT, why="VDD_SPI's bypass at its pin")
board.link(PadRef(Part("c_vspi_100n"), "VDD_SPI"), PadRef(Part("mcu"), VDD_SPI_PIN), weight=LinkWeight.SHORT,
           limit_mm=DECOUPLING_LIMIT, why="VDD_SPI's 100 nF at its pin")
board.link(PadRef(Part("c_cpu"), 1), PadRef(Part("mcu"), VDD3P3_CPU_PIN), weight=LinkWeight.SHORT,
           limit_mm=DECOUPLING_LIMIT, why="VDD3P3_CPU's bypass at its own pin, not V3V3's first pad")
board.link(PadRef(Part("c_rtc"), 1), PadRef(Part("mcu"), VDD3P3_RTC_PIN), weight=LinkWeight.SHORT,
           limit_mm=DECOUPLING_LIMIT, why="VDD3P3_RTC's bypass at its own pin, not V3V3's first pad")
if not EXTERNAL_FLASH:
    board.place(Part("c_rtc"), at=Beside(esc_east, Edge.EAST, align=(1, PadRef(Part("mcu"), VDD3P3_RTC_PIN))),
                rotation=Facing(PadRef(Part("c_rtc"), 1), Edge.WEST),
                why="VDD3P3_RTC's bypass lying on pin 20's row past the east row's stubs")
    board.place(Part("c_cpu"), at=Beside(Part("mcu"), Edge.WEST, gap=LANE, align=(1, PadRef(Part("mcu"), CPU_BYPASS_ROW_PIN))),
                rotation=135, why="VDD3P3_CPU's bypass a fanout lane west of pin 46, turned out of the corner, its V3V3 "
                                  "pad level with pin 45 so pins 47-52 fan out under it (Ben, 2026-10-02)")
    board.place(Part("c_vspi_1u"), at=Beside(Part("mcu"), Edge.NORTH, align=PadRef(Part("mcu"), VDD_SPI_PIN)),
                rotation=0, why="VDD_SPI's 1 uF over pin 29")
    board.place(Part("c_vspi_100n"), at=Beside(Part("c_vspi_1u"), Edge.WEST, align=PadRef(Part("c_vspi_1u"), "VDD_SPI")),
                rotation=180, why="VDD_SPI's 100 nF west of the 1 uF, VDD_SPI pads facing")
else:
    board.place(Part("c_rtc"), rotation=90, why="VDD3P3_RTC's bypass")
    board.place(Part("c_cpu"), rotation=90, why="VDD3P3_CPU's bypass")
    board.place(Part("c_vspi_100n"), rotation=0, why="VDD_SPI's 100 nF")
    board.place(Part("c_vspi_1u"), at=Beside(Part("c_vspi_100n"), Edge.WEST, align=PadRef(Part("c_vspi_100n"), "VDD_SPI")),
                rotation=180, why="VDD_SPI's 1 uF beside the 100 nF, VDD_SPI pads facing")

# --- the flash and its bus ----------------------------------------------------
# The S3R8 only. The flash stands north of the chip, across the row of 0 ohm
# links Espressif's schematic checklist recommends; its own bypass and the
# three pull-ups sit at its pins.
if EXTERNAL_FLASH:
    flash = board.block(Part("flash"), satellites=[
        (Part("c_flash"), "VDD_SPI"),
        (Part("r_flash_cs"), "FLASH_CS"),
        (Part("r_flash_wp_up"), "FLASH_WP"),
        (Part("r_flash_hd_up"), "FLASH_HD"),
    ])
    board.link(PadRef(Part("flash"), "FLASH_CS"), PadRef(Part("mcu"), "FLASH_CS"),
               weight=LinkWeight.SHORT, limit_mm=FLASH_BUS_LIMIT,
               why="the quad bus runs at the chip's flash clock; keep it short")
    board.place(flash, at=Beside(Part("mcu"), Edge.NORTH, align=Along.MID, gap=SERIES_ROW), rotation=FLASH_ROTATION,
                why="the flash across the row of 0 ohm links")
    board.link(PadRef(Part("r_flash_clk"), "FLASH_CLK_CHIP"), PadRef(Part("mcu"), "FLASH_CLK_CHIP"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="the clock's series link at the chip")
    board.link(PadRef(Part("r_flash_clk"), "FLASH_CLK"), PadRef(Part("flash"), "FLASH_CLK"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="the clock's series link at the flash")
    board.place(Part("r_flash_clk"))
    board.link(PadRef(Part("r_flash_d"), "FLASH_D_CHIP"), PadRef(Part("mcu"), "FLASH_D_CHIP"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO0's series link at the chip")
    board.link(PadRef(Part("r_flash_d"), "FLASH_D"), PadRef(Part("flash"), "FLASH_D"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO0's series link at the flash")
    board.place(Part("r_flash_d"))
    board.link(PadRef(Part("r_flash_q"), "FLASH_Q_CHIP"), PadRef(Part("mcu"), "FLASH_Q_CHIP"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO1's series link at the chip")
    board.link(PadRef(Part("r_flash_q"), "FLASH_Q"), PadRef(Part("flash"), "FLASH_Q"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO1's series link at the flash")
    board.place(Part("r_flash_q"))
    board.link(PadRef(Part("r_flash_wp"), "FLASH_WP_CHIP"), PadRef(Part("mcu"), "FLASH_WP_CHIP"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO2's series link at the chip")
    board.link(PadRef(Part("r_flash_wp"), "FLASH_WP"), PadRef(Part("flash"), "FLASH_WP"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO2's series link at the flash")
    board.place(Part("r_flash_wp"))
    board.link(PadRef(Part("r_flash_hd"), "FLASH_HD_CHIP"), PadRef(Part("mcu"), "FLASH_HD_CHIP"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO3's series link at the chip")
    board.link(PadRef(Part("r_flash_hd"), "FLASH_HD"), PadRef(Part("flash"), "FLASH_HD"),
               weight=LinkWeight.PREFER, limit_mm=FLASH_BUS_LIMIT, why="IO3's series link at the flash")
    board.place(Part("r_flash_hd"))

# The room the core has for the cell is checked, not typed: `board.width`
# is refused on a fit board (it is not resolved until board.size() below
# runs), so the content's own width is measured directly from every placed
# part's real, drawn box - the same box `board.size(fit=True)` itself packs
# to - and checked against CELL_WIDTH before the fit is taken. A fit frame
# wider than the tabs leave would not show until the core's own run, which
# this module cannot run (electronics/CLAUDE.md).
_boxes = [board.part(p).courtyard_box for p in board.parts()]
_content_width = max(b.right for b in _boxes) - min(b.left for b in _boxes)
assert _content_width <= CELL_WIDTH, \
    f"the cell's content is {_content_width:.2f} mm wide; only {CELL_WIDTH} mm fits between the input tabs"
board.size(fit=True)

# Routing evidence: ../../../../docs/decisions/layout/mcu-module-routing-2026-09-27.md
# Ground and 3V3 planes as the core has them (In1/In4, In3), and a ground
# zone on the component face round the clock and RF traces (Espressif), all
# bounded to the frame's keep-in so the stamped cell brings no copper past its
# parts.
frame_planes(FILLET)

# --- copper -----------------------------------------------------------------
# Every point is a pad, a lane of one of the escapes above, or a clearance
# asked of the tool (Past). Plane drops are vias in the pads (filled and
# capped).
F = CopperLayer.F


def pin_track(net, pin, part, pad=1, width=None):
    board.track(Net(net), [PadRef(Part("mcu"), pin), PadRef(Part(part), pad)], layer=F, width=width)


# The bypasses at their pins.
pin_track("V3V3", VDD3P3_CPU_PIN, "c_cpu")
pin_track("V3V3", VDD3P3_RTC_PIN, "c_rtc")
# VDDA: pins 55 and 56 joined along the row, then west into the 10 nF's pad,
# which drops to the 3V3 plane; the 1 uF's V3V3 pad stands under it in one
# column, and one pour joins the two.
board.track(Net("V3V3"), [PadRef(Part("mcu"), VDDA_PINS[0]), PadRef(Part("mcu"), VDDA_PINS[1])], layer=F)
board.track(Net("V3V3"), [PadRef(Part("mcu"), VDDA_PINS[1]), PadRef(Part("c_vdda_10n"), "V3V3")], layer=F)
board.pour(Net("V3V3"), [PadRef(Part("c_vdda_10n"), "V3V3"), PadRef(Part("c_vdda_1u"), "V3V3")],
           layer=F, swallow_pads=True)
# VDD_SPI: pin 29's stem into its capacitor's pad, and the two capacitors'
# facing VDD_SPI pads joined by one pour.
if EXTERNAL_FLASH:
    pin_track("VDD_SPI", VDD_SPI_PIN, "c_vspi_100n", pad="VDD_SPI")
else:
    pin_track("VDD_SPI", VDD_SPI_PIN, "c_vspi_1u", pad="VDD_SPI")
board.pour(Net("VDD_SPI"), [PadRef(Part("c_vspi_1u"), "VDD_SPI"), PadRef(Part("c_vspi_100n"), "VDD_SPI")],
           layer=F, swallow_pads=True)

# The RF chip-side match: LNA_IN down its riser to the series inductor, its
# two shunts, and RF_50's way out south.
board.track(Net("RF_CHIP"), [esc_south[LNA_IN_PIN], PadRef(Part("l_rf_match"), "RF_CHIP")], layer=F)
board.track(Net("RF_CHIP"), [PadRef(Part("c_rf_chip"), "RF_CHIP"), PadRef(Part("l_rf_match"), "RF_CHIP")], layer=F)
board.track(Net("RF_50"), [PadRef(Part("l_rf_match"), "RF_50"), PadRef(Part("c_rf_50"), "RF_50")], layer=F)
board.track(Net("RF_50"), [esc_rf["RF_50"]], layer=F)

# The RF supply: pins 2 and 3 under one pour, down into c_rf_post's pad; it and
# the filter's output drop to an In2 trunk between them.
_post = PadRef(Part("c_rf_post"), "VDD_RF")
board.pour(Net("VDD_RF"), [PadRef(Part("mcu"), VDD3P3_PINS[0]), PadRef(Part("mcu"), VDD3P3_PINS[1])], layer=F, swallow_pads=True)
board.track(Net("VDD_RF"), [PadRef(Part("mcu"), VDD3P3_PINS[1]), _post], layer=F)
board.via(Net("VDD_RF"), _post, size=VIA, drill=VIA_DRILL)
board.via(Net("VDD_RF"), PadRef(Part("l_rf_supply"), "VDD_RF"), size=VIA, drill=VIA_DRILL)
board.track(Net("VDD_RF"), [_post, PadRef(Part("l_rf_supply"), "VDD_RF")], layer=CopperLayer.IN2, width=RF_SUPPLY_WIDTH)
# The filter's input: the three V3V3 pads of its row, one fill.
board.pour(Net("V3V3"), [PadRef(Part("c_rf_pre_1u"), "V3V3"), PadRef(Part("c_rf_pre_100n"), "V3V3"),
                         PadRef(Part("l_rf_supply"), "V3V3")], layer=F, swallow_pads=True)
# The reservoir's GND pad and the filter's 100 nF GND pad: joined by the
# component face's ground zone.

# The oscillator loop. XTAL_N: out of pin 53 on its riser over the series
# inductor, a 45 up past the crystal's north-east pad, west a clearance over
# the crystal's north pads, and down into its north-west pad; its load's
# pad above joins the run. XTAL_P straight into the series inductor. XTAL_1:
# from the inductor, a clearance west of VDDA's 10 nF ground pad, into the
# crystal's south-east pad and on to its load.
_xn, _x1 = PadRef(Part("xtal"), "XTAL_N"), PadRef(Part("xtal"), "XTAL_1")
_xtal_ne = PadRef(Part("xtal"), 2)
board.track(Net("XTAL_N"), [esc_xtal[53], Past([_xtal_ne], Corner.NE),
                            Past([_xtal_ne, _xn], Edge.NORTH, across=_xn), _xn], layer=F)
board.track(Net("XTAL_N"), [PadRef(Part("c_xtal2"), "XTAL_N"), _xn], layer=F)
board.track(Net("XTAL_P"), [PadRef(Part("mcu"), "XTAL_P"), PadRef(Part("l_xtal"), "XTAL_P")], layer=F)
board.track(Net("XTAL_1"), [PadRef(Part("l_xtal"), "XTAL_1"), Past([PadRef(Part("c_vdda_10n"), "GND")], Edge.WEST), _x1],
            layer=F)
board.track(Net("XTAL_1"), [_x1, PadRef(Part("c_xtal1"), "XTAL_1")], layer=F)

# Reset: CHIP_PU down its riser to the pull-up; the capacitor's MCU_EN pad
# stands beside the pull-up's, and one pour joins them.
board.track(Net("MCU_EN"), [esc_south[CHIP_PU_PIN], PadRef(Part("r_en"), "MCU_EN")], layer=F, bend=Bend.END)
board.pour(Net("MCU_EN"), [PadRef(Part("r_en"), "MCU_EN"), PadRef(Part("c_en"), "MCU_EN")],
           layer=F, swallow_pads=True)

# The pins' ways out: stubs where the core's router takes them. The pins
# the module joins inside it are routed round them.
board.track(Net("VBUS_DISCH"), [esc_west["VBUS_DISCH"]], layer=F)
board.track(Net("USB_WET"), [esc_west["USB_WET"]], layer=F)
board.track(Net("PD_IRQ"), [esc_west["PD_IRQ"]], layer=F)
board.track(Net("GNSS_TX"), [esc_south_fan["GNSS_TX"]], layer=F)
board.track(Net("GNSS_RX"), [esc_south_fan["GNSS_RX"]], layer=F)
board.track(Net("GNSS_PPS"), [esc_south_fan["GNSS_PPS"]], layer=F)
board.track(Net("BL_PWM"), [esc_south_fan["BL_PWM"]], layer=F)
board.track(Net("SCL"), [esc_south_fan["SCL"]], layer=F)
board.track(Net("LD1"), [esc_south_fan["LD1"]], layer=F)
board.track(Net("LD2"), [esc_south_fan["LD2"]], layer=F)
board.track(Net("SDA"), [esc_south_fan["SDA"]], layer=F)
board.track(Net("STRAP_DOWNLOAD"), [PadRef(Part("mcu"), 52),
                                    Past([PadRef(Part("l_xtal"), "XTAL_1")], Edge.WEST, across=PadRef(Part("mcu"), 52)),
                                    PadRef(Part("r_strap46"), "STRAP_DOWNLOAD")], layer=F, bend=Bend.START)
board.track(Net("STRAP_VSPI"), [PadRef(Part("mcu"), 51), PadRef(Part("r_strap45"), "STRAP_VSPI")], layer=F)
board.track(Net("UART_TX_CHIP"), [esc_west["UART_TX_CHIP"], PadRef(Part("r_uart_tx"), "UART_TX_CHIP")], layer=F)
board.track(Net("LED_STATUS_DRIVE"), [esc_west["LED_STATUS_DRIVE"], PadRef(Part("r_led_status"), "LED_STATUS_DRIVE")], layer=F)
board.track(Net("BOOT_STRAP"), [esc_south_fan["BOOT_STRAP"], PadRef(Part("r_boot"), "BOOT_STRAP")], layer=F, bend=Bend.START)
board.track(Net("STRAP_JTAG"), [esc_south_fan["STRAP_JTAG"], PadRef(Part("r_strap3"), "STRAP_JTAG")], layer=F, bend=Bend.START)
for net in ("RING_INT", "INA_ALERT", "DISP_CS", "DISP_RST", "DISP_SCK", "DISP_MOSI", "DISP_DC", "DISP_TE", "EXCITE",
            "USB_D_N", "USB_D_P", "IMU_INT1"):
    board.track(Net(net), [esc_east[net]], layer=F)
board.track(Net("VBUS_EN"), [esc_north["VBUS_EN"]], layer=F)
board.track(Net("SCL_PWR"), [esc_north["SCL_PWR"]], layer=F)

# Plane drops in the pads: bypasses and pull-ups to V3V3 on In3, their
# grounds to GND on In1/In4. VDD3P3_CPU's bypass grounds through the
# component face's zone, between the west row's two fans; the crystal's
# ground pads drop in their pads (Ben, 2026-10-02).
for part in ("c_cpu", "c_rtc", "c_vdda_1u", "c_vdda_10n", "c_rf_pre_100n", "c_rf_pre_1u", "l_rf_supply", "c_mcu_bulk",
             "r_boot", "r_en", "r_strap3"):
    board.via(Net("V3V3"), PadRef(Part(part), "V3V3"), size=VIA, drill=VIA_DRILL)
for part in ("c_rtc", "c_vdda_1u", "c_vdda_10n", "c_rf_pre_100n", "c_rf_pre_1u", "c_mcu_bulk",
             "c_rf_post", "c_vspi_100n", "c_vspi_1u", "c_en", "c_xtal1", "c_xtal2", "r_strap45", "r_strap46"):
    board.via(Net("GND"), PadRef(Part(part), "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), PadRef(Part("xtal"), 2), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), PadRef(Part("xtal"), 4), size=VIA, drill=VIA_DRILL)
