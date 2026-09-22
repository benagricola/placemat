"""SwdHeader: a 1x4 2.54 mm SWD debug header (GND, SWCLK, SWDIO, 3V3) with
knockout pin labels. It lives outside the MCU cell so a board decides
whether to expose SWD at all, and where.

Access is vertical, not an edge: a male header mates top-down, so what it
needs is plug volume above it, not a board edge. The labels sit north of
the row, one per pin over its own pad and the title above them, so the
plug can be oriented before it goes on and the cell still reads with a
plug seated. South is the MCU's side: the two debug signals end at their
pads and the board draws each track from there. GND and 3V3 are through
holes, so they are their own plane landings and the cell drops no via.
"""
from placemat import board, CopperLayer, Edge, Location, Net, PadRef, Part

J = Part("j_swd")
GND, SWCLK, SWDIO, V3V3 = Net("gnd"), Net("swclk"), Net("swdio"), Net("v3v3")

ORIGIN = Location(148.5, 105.0)  # the header's origin: a fragment's coordinates are its own
PIN_SIZE = 0.80                  # the smallest text KiCad's text_height rule allows: four words at the 2.54 pitch
TITLE_SIZE = 0.85
PIN_BAND = PIN_SIZE * 1.6        # a knockout label's box height: the title stands past the pin labels

board.place(J, at=ORIGIN, rotation=0.0, why="pin 1 (the keyed pad, GND) west, pins ascending east; signals leave south")

board.label([PadRef(J, GND), PadRef(J, SWCLK), PadRef(J, SWDIO), PadRef(J, V3V3)], ["GND", "CLK", "IO", "3V3"],
            side=Edge.NORTH, size=PIN_SIZE, knockout=True, line=J, why="each pin named over its own pad, clear of the header's outline, read with the plug off")
board.label(J, "SWD", side=Edge.NORTH, gap=PIN_BAND, size=TITLE_SIZE, knockout=True,
            why="the title past the pin labels, so CLK and IO cannot be read as some other two-wire bus")

board.faces(handoff=Edge.SOUTH, why="the debug signals leave toward the MCU; the plug comes from above")
