"""Debug: the bench panel, stamped onto the core as one cell inside the seal.

What a person with the case open touches or reads, in one place and one
reading order: the two buttons and the three lights along the top, the six
programming pads under them. The lights' resistors are in the sheets that
drive them, so only a limited current runs to the panel. The core places the
panel as one cell. Its names are the cell's own, so they turn and flip with
it: vertical names, the buttons' above them and knocked out, the pads' below
them (Ben, 2026-09-30).

  row A  BOOT  RESET  then the bike, USB and status lights (unnamed for now)
  row B  3V3  GND  TX  RX  IO0  EN       the pads a programming clip lands on, in the
                                        order of the usual six-pin ESP32 header

The rows pack as tight as their parts' envelopes allow, the pads just under
the buttons, and BOOT and EN run to their pads on the component face in the
lane between the lights and the pads (Ben's hand layout, 2026-09-30).

Evidence: docs/decisions/layout/debug-module-routing-2026-09-26.md.
"""
from placemat import board, Along, Beside, CopperLayer, Corner, Edge, Location, Net, PadRef, Part, Past

from fragment_frame import frame_planes

LIGHT_ROTATION = 90      # a 0603 light stood on end, 1.7 mm across the row
BUTTON_ROTATION = 270    # the switches a quarter turn anticlockwise from the north row's default 180 (Ben, 2026-09-29)
VIA, VIA_DRILL = 0.45, 0.20   # the core's via; a 0.2 mm drill is inside JLCPCB's via-in-pad range
FILLET = 0.15                 # the ground zone's corner radius
SILK_SPACING = 0.2       # between any two pieces of silk (Ben, 2026-09-23): the rows pack at it
LABEL_SIZE = 0.8         # the panel's names: small, but legible without a loupe
LABEL_TURN = 90          # the names read up the page, one over each item, so the rows keep their tight pitch

BUTTONS = [Part("sw_boot"), Part("sw_reset")]
LIGHTS = [Part("led_bike"), Part("led_usb"), Part("led_status")]
PADS = [Part("tp_3v3"), Part("tp_gnd"), Part("tp_txd0"), Part("tp_rxd0"),
        Part("tp_boot"), Part("tp_reset")]

# The frame fits the rows and their names, so the rows run off the BOOT
# switch rather than the frame's edge: the reset switch and the lights in a
# line east of it on its centre line, the pads under it from its west end.
board.rect(fit=True, draw=False)
board.place(Part("sw_boot"), at=Location(0, 0), rotation=BUTTON_ROTATION, why="the panel's datum: the top row's west end")
board.place(Part("sw_reset"), at=Beside(Part("sw_boot"), Edge.EAST), rotation=BUTTON_ROTATION, why="the second button")
board.place(Part("led_bike"), at=Beside(Part("sw_reset"), Edge.EAST, gap=SILK_SPACING), rotation=LIGHT_ROTATION,
            why="the lights after the buttons")
board.place(Part("led_usb"), at=Beside(Part("led_bike"), Edge.EAST, gap=SILK_SPACING), rotation=LIGHT_ROTATION,
            why="the lights in a line")
board.place(Part("led_status"), at=Beside(Part("led_usb"), Edge.EAST, gap=SILK_SPACING), rotation=LIGHT_ROTATION,
            why="the lights in a line")
board.row(PADS, Edge.SOUTH, of=Part("sw_boot"), gap=SILK_SPACING, align=Along.START)

# The names: the buttons' above them, knocked out, and the pads' below them
# (Ben, 2026-09-30). The lights carry no names yet. Stamped with the cell,
# each keeps parts off its box on the cell's face.
board.label(BUTTONS, ["BOOT", "RESET"], side=Edge.NORTH, gap=SILK_SPACING, knockout=True, size=LABEL_SIZE,
            rotation=LABEL_TURN)
board.label(PADS, ["3V3", "GND", "TX", "RX", "IO0", "EN"], side=Edge.SOUTH, gap=SILK_SPACING, size=LABEL_SIZE,
            rotation=LABEL_TURN)
frame_planes(FILLET)

# Internal connections only; the six programming signals and LED drives
# retain their existing pads as handoffs to the core. Every drop is a via in
# its pad, filled and capped, so a probe lands on a flat pad.
# Each switch joins its programming pad on the component face (Ben's hand
# layout, 2026-09-30). BOOT leaves under its switch's signal pad, takes a 45
# past the reset switch's signal pad's south-west corner, under that switch's
# body between its pads, and runs east in a lane a clearance over the pad
# row. EN leaves under its own, takes a 45 past the bike light's south-west
# corner and runs east in a lane a clearance under the lights.
_boot_sw, _en_sw = PadRef(Part("sw_boot"), "BOOT_STRAP"), PadRef(Part("sw_reset"), "MCU_EN")
_boot, _en = PadRef(Part("tp_boot"), "BOOT_STRAP"), PadRef(Part("tp_reset"), "MCU_EN")
_pad_row = [PadRef(p, 1) for p in PADS]
_lights = [PadRef(p, n) for p in LIGHTS for n in (1, 2)]
board.track(Net("BOOT_STRAP"), [_boot_sw, Past([_boot_sw], Edge.SOUTH), Past([_en_sw], Corner.SW),
                                Past(_pad_row, Edge.NORTH, across=_boot), _boot], layer=CopperLayer.F)
board.track(Net("MCU_EN"), [_en_sw, Past([_en_sw], Edge.SOUTH), Past([PadRef(Part("led_bike"), "GND")], Corner.SW),
                            Past(_lights, Edge.SOUTH, across=_en), _en], layer=CopperLayer.F)
# The 3V3 pad and the USB light's anode reach the 3V3 plane; the ground pad,
# the switches' grounds and the lights' reach the ground planes.
board.via(Net("V3V3"), PadRef(Part("tp_3v3"), "V3V3"), size=VIA, drill=VIA_DRILL)
board.via(Net("V3V3"), PadRef(Part("led_usb"), "V3V3"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), PadRef(Part("tp_gnd"), "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), PadRef(Part("sw_boot"), "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), PadRef(Part("sw_reset"), "GND"), size=VIA, drill=VIA_DRILL)
# The BOOT and EN runs part the component face's ground from the lights, so
# the bike and status lights' cathodes drop to the planes (the USB light is
# switched at its cathode, its anode on 3V3).
board.via(Net("GND"), PadRef(Part("led_bike"), "GND"), size=VIA, drill=VIA_DRILL)
board.via(Net("GND"), PadRef(Part("led_status"), "GND"), size=VIA, drill=VIA_DRILL)
