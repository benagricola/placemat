"""RelayDriver: the Darlington low-side driver array (ULN2003A, SOIC-16)
and its COM bypass. The SOIC pinout already pools the pads: the seven
logic inputs are one pin row and the seven open-collector outputs the
other, each channel column-aligned through the IC, so the IC at
rotation 0 gives one routing front per side: inputs south, the MCU's
side, and outputs north, the coils' side.

The COM bypass, the clamp diodes' freewheel return, stands upright
above the COM pin with its COM pad on the pin's own axis, so the serve
is one straight track down that axis; upright, it adds only its short
side to the cell's width. COM and E (ground) take a via in the pad to
the board's planes. Inputs and outputs are bare pads: the board draws
their copper, so every one is expected open in this fragment.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, X, Y

IC, C_COM = Part("ic"), Part("com_dec")
COM, GND = Net("com"), Net("gnd")
F = CopperLayer.F

ORIGIN = Location(150.0, 105.0)   # the IC's origin: a fragment's coordinates are its own, the board stamps it anywhere
CAP_ROT = 90.0                    # upright: its COM pad south, toward the pin, ground north
CAP_GAP = 0.0                     # the cap's courtyard to the IC's: touching

ic_claim = board.claim(IC)
cap_claim = board.claim(C_COM, rotation=CAP_ROT)
com_pin = PadRef(IC, COM)

board.place(IC, at=ORIGIN, rotation=0.0, why="inputs south to the MCU, outputs north to the coils")
board.place(C_COM, at=Centre(X(com_pin), Y(IC, ic_claim.top - CAP_GAP - cap_claim.height / 2)), rotation=CAP_ROT,
            why="the bypass upright above the COM pin, its COM pad on the pin's axis")

board.track(COM, [PadRef(C_COM, COM), com_pin], layer=F, why="one straight serve down the pin's axis")
board.via(COM, PadRef(C_COM, COM), why="the coil supply plane lands in the bypass's pad")
board.via(GND, PadRef(IC, GND), why="the ground plane lands in the E pin")

board.faces(handoff=Edge.SOUTH, why="the inputs face the MCU; the outputs leave north to the coils")
