"""MCU_RP2350B: the RP2350B node-MCU cell: the QFN-80, its flash, crystal,
1V1 LDO island, USB series pair, power LED and nineteen decoupling caps.
Silent rails: every cap is plane-fed by a via in both pads and the
serve track to its pin is the only top copper it owns. Two relief-via
columns under the package, one each side of the exposed pad on one
lattice, take the pins a cap axis boxes in; every other pin ends at
its pad for the board to fan out. The west face fan is drawn: thirteen
straight lanes and four relief dives, mirror-symmetric about the DVDD
pin's axis; the east face mirrors it. The flash lies north with the
QSPI descents on one lane lattice and the north caps standing in
columns beside the descents, not across them. The crystal block is a
diamond on the crystal's own 45 south of the package, slid so gpio24
leaves through the gap between its caps; the SWD and RUN trio and
gpio25 to 27 dive to the south relief rows. The USB pair drops into
the annulus, changes layer and runs east parallel at the pair gap to
the terminators north of the LDO island.

The geometry is the hand round's, on the 0.4 mm pin pitch and its
0.5657 diagonal, kept because it is the fold of several hand passes:
every number here is one of that lattice's, named with its reason.
"""
from placemat import board, Centre, CopperLayer, Edge, Location, Net, PadRef, Part, X, Y
from placemat.geometry import Transform

MCU, FLASH, Y1, LDO, LED = Part("mcu"), Part("flash"), Part("y1"), Part("u_ldo1v1"), Part("d_pwr")
F, B = CopperLayer.F, CopperLayer.B
GND, V3V3, V1V1 = Net("gnd"), Net("v3v3"), Net("V1V1")
ORIGIN = Location(14.0, 13.6)   # the package's origin: a fragment's coordinates are its own
PAD = 4.910                     # the QFN's pad-centre offset from the die centre, all four faces
PITCH = 0.400                   # the pin pitch: the fan's lane pitch
D45 = PITCH * 2 ** 0.5          # the along-45 step that keeps lanes one pitch apart
RELIEF_X = 2.350                # the relief-via columns, mirrored: the exposed pad's edge plus a via's room
RELIEF_DY = 0.800               # the relief lattice pitch, both columns
RELIEF_RUN = 0.600              # a dive's last leg runs along its via's own row: a 45 aimed at a via passes its neighbour too close
RELIEF_TURN = -4.400            # a west dive may not turn onto its 45 west of this: the diagonal neighbour pad's inner corner
XTAL_DY = 0.300                 # the crystal block's slide south: opens the cap gate gpio24 leaves through
C24_STEP = 0.100                # the pin-24 cap's step west and south off the block, squaring that gate's jamb
LDO_DX = -0.650                 # the 1V1 island pulled toward the chip
USB_TERM_X = 10.740             # the USB terminators' column, north of the LDO island where the back-face pair resurfaces
USB_TERM_Y = (-3.350, -4.550)   # their two rows: 0.64 mm pads cannot sit on the 0.8 lattice
FLASH_DX, FLASH_DY = 0.100, -0.300
FL_NEAR = -6.890 + FLASH_DY     # the flash's near pad row, facing the package
GND_DROP_Y = -4.000             # VREG_PGND and VREG_FB's drops: the annulus's deepest legal row
USB_ROW = -3.400                # the pair's back-face row: P on the relief lattice row
USB_GAP = 0.450                 # the pair gap: the house clearance target between the two tracks
USB_N_VIA_DY = 0.900            # N's via sits half a pitch past a gap: the length-match knob
QSPI_INV0 = -7.000              # x + y of SD0's 45: the near-row lattice anchor
WRAP_DY = 0.100                 # the far-row wrap's slide south into its slack
FAR_OUT0 = 10.800 - WRAP_DY     # x - y of SD2's outbound 45
FAR_ROW0 = -11.000 + WRAP_DY    # SD2's straight run
FAR_IN0 = -11.700 + WRAP_DY     # x + y of SD2's inbound 45
SE_SERVE_INV = 1.450            # IOVDD41's serve 45: x - y, the SE fan's lattice anchor
NE_SERVE_INV = 2.800            # ADC_AVDD59's serve 45: x + y
ANNULUS = -4.200                # the pins' first turn inside the ring
W = board.netclass(V3V3).track_width


def P(inst):
    return Part(inst)


def at(x, y):
    """A point in the package's frame."""
    return (X(MCU, x), Y(MCU, y))


def place(inst, dx, dy, rot, why):
    board.place(P(inst), at=Location(X(MCU, dx), Y(MCU, dy)), rotation=rot, why=why)


def path(net, pts, layer=F):
    board.track(Net(net), [at(x, y) for x, y in pts], layer=layer, chamfer=0.0)


# ---------------------------------------------------------------- placement, in the package's frame
board.place(MCU, at=ORIGIN, rotation=0.0, why="the QFN-80: the anchor")
place("flash", 0.2 + FLASH_DX, -8.4 + FLASH_DY, 180, "the flash north, its near row facing the package's QSPI pins")
place("r_usb_dm", USB_TERM_X, USB_TERM_Y[0], 0, "the USB series pair north of the LDO island, where the back-face pair resurfaces")
place("r_usb_dp", USB_TERM_X, USB_TERM_Y[1], 0, "the other terminator on the row above")
place("c_iovdd7", -2.95, -7.2, 135, "IOVDD 76's cap on the north-west diagonal, its pad on the pin's 45")
place("c_vreg_vin_avdd", 4.55, -7.445, 90, "the 4.7 uF standing in its own column, dual-serving VREG_AVDD 61 and VREG_VIN 64")
place("c_qspi_iovdd", 2.05, -7.03, 90, "the QSPI_IOVDD 69 cap standing in the column east of the flash, clear of the serve corridors")
place("c_flash_vcc", 2.05, -9.1, 90, "the flash's VCC cap above it in the same column")
place("c_usb_otp_vdd", 3.15, -7.075, 90, "USB_OTP_VDD 68's cap in the next column")
place("c_iovdd6", 5.9, -5.05, 90, "IOVDD 60's cap flanking the north-east fan corridor")
place("c_adc_avdd", 6.95, -5.05, 90, "ADC_AVDD 59's cap beside it")
place("c_iovdd0", -6.45, -2.2, 180, "IOVDD 5's cap point-blank on the pin's axis, served pad inboard")
place("c_dvdd0", -6.45, -0.2, 180, "DVDD 10's cap on its axis: the west face's mirror line")
place("c_iovdd1", -6.45, 1.8, 180, "IOVDD 15's cap on its axis")
place("c_iovdd4", 6.439411, 5.339411, -45, "IOVDD 41's cap on the south-east fan's own 45, its pad on the serve diagonal")
place("c_iovdd5", 6.55, 0.55, 0, "IOVDD 50's cap: the mid-face pair flanking the pins at 0.2, stepped to 0.55 so each serve is one 45")
place("c_dvdd2", 6.55, -0.55, 0, "DVDD 51's cap, its mirror")
place("y1", -0.25, 9.7 + XTAL_DY, -45, "the crystal on its own 45: XIN on the north-west corner, XOUT south-east, each load cap on its net's diagonal")
place("c_xtal_xin", -2.9, 8.25 + XTAL_DY, -135, "XIN's load cap on the north-west diagonal")
place("c_xtal_xout", 1.960589, 8.610589 + XTAL_DY, -45, "XOUT's load cap on the south-east diagonal")
place("r_xtal_damp", 0.610624, 7.260624 + XTAL_DY, 135, "the damping resistor on the XOUT descent into pin 31")
place("c_iovdd3", -1.35, 6.5 + XTAL_DY, -135, "IOVDD 29's cap mirrored about the crystal lane, served pad to its pin, ground outboard")
place("c_dvdd1", 1.35, 6.5 + XTAL_DY, -45, "DVDD 32's cap, its mirror")
place("c_iovdd2", -3.160589 - C24_STEP, 6.760589 + C24_STEP, -135, "IOVDD 24's cap stepped off the block: the jamb of the gate gpio24 leaves through")
place("c_ldo_out", 8.85 + LDO_DX, 0.25, -90, "the LDO's output cap first at the chip")
place("u_ldo1v1", 11.35 + LDO_DX, -1.18, 90, "the 1V1 LDO, output face west")
place("c_ldo_in", 14.34 + LDO_DX, -2.13, 0, "the LDO's input cap")
place("r_led_pwr", 6.425, -6.6, 180, "the power LED's resistor standing in the north-east pocket")
place("d_pwr", 6.425, -8.74, 270, "the LED above it on one axis, cathode north to its ground drop")
place("c_v1v1_bulk", 10.975 + LDO_DX, 1.4, 0, "the 1V1 bulk cap with its pad on the LDO output pad's axis")

# ---------------------------------------------------------------- the west face: three point-blank caps, six dives, the rest end at their pads
W_RELIEF = [("gpio7", -2.6, -2.6), ("gpio8", -1.8, -1.8), ("gpio11", -0.6, -1.0),
            ("gpio12", 0.2, -0.2), ("gpio15", 1.4, 0.6), ("gpio16", 2.2, 1.4)]   # (net, pin row, via row): the pins a cap axis boxes in
for net, y_pin, y_via in W_RELIEF:
    d = abs(y_via - y_pin)
    x_t = max(-RELIEF_X - RELIEF_RUN - d, RELIEF_TURN)
    path(net, [(-PAD, y_pin), (x_t, y_pin), (x_t + d, y_via), (-RELIEF_X, y_via)])
    board.via(Net(net), at(-RELIEF_X, y_via), why="the west relief column")
for inst, net, y in [("c_iovdd0", "v3v3", -2.2), ("c_dvdd0", "V1V1", -0.2), ("c_iovdd1", "v3v3", 1.8)]:
    board.track(Net(net), [PadRef(P(inst), net), at(-PAD, y)], layer=F, chamfer=0.0, why="one straight serve, pad to pin")

# ---------------------------------------------------------------- the east face: two 45 fans on the caps' own diagonals, four dives
for inst, net, y_pin in [("c_iovdd5", "v3v3", 0.2), ("c_dvdd2", "V1V1", -0.2)]:
    pad = PadRef(P(inst), net)
    board.track(Net(net), [pad, (X(pad, -0.35), Y(pad)), (X(pad, -0.7), Y(MCU, y_pin)), at(PAD, y_pin)], layer=F, chamfer=0.0,
                why="the mid-face cap: one 45 onto the pin's axis, then in")
c41 = PadRef(P("c_iovdd4"), "v3v3")
board.track(Net("v3v3"), [at(PAD, 3.8), at(SE_SERVE_INV + 3.8, 3.8), (X(c41), Y(c41, 0.0)), c41], layer=F, chamfer=0.0,
            why="IOVDD 41 out of the pin onto the serve diagonal and up the cap's own column")
board.track(Net("v3v3"), [PadRef(P("c_adc_avdd"), "v3v3"), at(6.95, NE_SERVE_INV - 6.95), at(NE_SERVE_INV + 3.4, -3.4), at(PAD, -3.4)],
            layer=F, chamfer=0.0, why="ADC_AVDD 59: the cap pad, straight, one 45, the pin's axis")
board.track(Net("v3v3"), [PadRef(P("c_iovdd6"), "v3v3"), at(5.9, -4.2), at(5.5, -3.8), at(PAD, -3.8)], layer=F, chamfer=0.0,
            why="IOVDD 60 likewise")
E_RELIEF = [("gpio42_adc2", -1.0, -1.0), ("gpio41_adc1", -0.6, -0.2), ("gpio40_adc0", 0.6, 0.6), ("gpio39", 1.0, 1.4)]
for net, y_pin, y_via in E_RELIEF:
    d = abs(y_via - y_pin)
    path(net, [(PAD, y_pin), (RELIEF_X + RELIEF_RUN + d, y_pin), (RELIEF_X + RELIEF_RUN, y_via), (RELIEF_X, y_via)])
    board.via(Net(net), at(RELIEF_X, y_via), why="the east relief column")

# ---------------------------------------------------------------- the north face: QSPI, the supply chain, the USB pair
def flash_pad(n):
    """A flash pad in the package's frame: the flash's origin offset plus the pad's turned offset."""
    p, o = board.pad(FLASH, n).location, board.part(FLASH).location
    dx, dy = Transform.rotate(180.0).apply((p.x - o.x, p.y - o.y))
    return 0.2 + FLASH_DX + dx, -8.4 + FLASH_DY + dy


for k, (net, xp, pad) in enumerate([("QSPI_SD0", -0.6, 5), ("QSPI_SCLK", -0.2, 6), ("QSPI_SD3", 0.2, 7)]):
    xc, _ = flash_pad(pad)
    yt = QSPI_INV0 + k * D45 - xp
    path(net, [(xp, -PAD), (xp, yt), (xc, yt - (xc - xp)), (xc, FL_NEAR)])
for k, (net, pad, xc) in enumerate([("QSPI_SD2", 3, -1.0), ("QSPI_SD1", 2, -1.4), ("QSPI_SS", 1, -1.8)]):
    xp, yp = flash_pad(pad)
    y1 = xp - (FAR_OUT0 + k * D45)
    row = FAR_ROW0 - k * PITCH
    yc = (FAR_IN0 - k * D45) - xc
    turn = xc + (yc - row)
    path(net, [(xp, yp), (xp, y1), (xp - (y1 - row), row), (turn, row), (xc, yc), (xc, -PAD)])
fl8 = PadRef(FLASH, 8)
board.track(Net("v3v3"), [fl8, (X(fl8), Y(MCU, -7.62)), PadRef(P("c_flash_vcc"), "v3v3")], layer=F, chamfer=0.0, why="the flash's own cap")
board.track(Net("v3v3"), [PadRef(P("c_qspi_iovdd"), "v3v3"), at(1.55, -6.55), at(0.6, -5.6), at(0.6, -PAD)], layer=F, chamfer=0.0,
            why="QSPI_IOVDD 69 from its cap, a lane, the pin's axis")
board.track(Net("v3v3"), [PadRef(P("c_usb_otp_vdd"), "v3v3"), at(2.255, -5.7), at(1.2575, -5.7), at(1.0, -5.4425), at(1.0, -PAD)], layer=F, chamfer=0.0,
            why="USB_OTP_VDD 68 likewise")
board.track(Net("v3v3"), [PadRef(P("c_vreg_vin_avdd"), "v3v3"), at(4.55, -6.05), at(4.1, -5.6), at(3.8, -5.3), at(3.8, -PAD)], layer=F, chamfer=0.0,
            why="the 4.7 uF's trunk to VREG_AVDD 61")
board.track(Net("v3v3"), [at(4.1, -5.6), at(2.7575, -5.6), at(2.6, -5.4425), at(2.6, -PAD)], layer=F, chamfer=0.0,
            why="VREG_VIN 64 branching west off that trunk: a T on its own net")
board.track(Net("v3v3"), [PadRef(P("c_iovdd7"), "v3v3"), at(-2.2, -6.4), at(-2.2, -PAD)], layer=F, chamfer=0.0, why="IOVDD 76's cap down its pin's axis")
path("gnd", [(3.4, -PAD), (3.4, GND_DROP_Y)])
path("gnd", [(2.2, -PAD), (2.2, -4.4), (2.6, GND_DROP_Y)])
board.via(GND, at(3.4, GND_DROP_Y), why="VREG_PGND 62: a plain ground with no room to reach the exposed pad past the USB legs")
board.via(GND, at(2.6, GND_DROP_Y), why="VREG_FB 65 likewise, one lattice row apart")
pdp = PadRef(P("r_usb_dp"), "USB_MCU_P")
pdm = PadRef(P("r_usb_dm"), "USB_MCU_N")
pdp_dx = Transform.rotate(0.0).apply((board.pad(P("r_usb_dp"), "USB_MCU_P").location.x - board.part(P("r_usb_dp")).location.x, 0.0))[0]
PDP_INV = (USB_TERM_X + pdp_dx) + USB_TERM_Y[1]              # x + y of the P terminator's chip-side pad: where P's inbound 45 lands
for net, x_pin, x_via, y_via, y_row, rpad, inv in [("USB_MCU_P", 1.4, 1.2, USB_ROW, USB_ROW, pdp, PDP_INV),
                                                   ("USB_MCU_N", 1.8, 2.0, USB_ROW + USB_N_VIA_DY, USB_ROW + USB_GAP, pdm,
                                                    PDP_INV + USB_GAP * 2 ** 0.5)]:
    path(net, [(x_pin, -PAD), (x_pin, ANNULUS), (x_via, -4.0), (x_via, y_via)])
    board.via(Net(net), at(x_via, y_via), why="the pair drops into the annulus and changes layer")
    ry = USB_TERM_Y[1] if net == "USB_MCU_P" else USB_TERM_Y[0]
    board.track(Net(net), [at(x_via, y_via), at(x_via + abs(y_row - y_via), y_row), at(inv - y_row, y_row), at(inv - ry, ry), rpad],
                layer=B, chamfer=0.0, why="east on the back face, parallel at the pair gap, one 45 up into the terminator's pad")
    board.via(Net(net), rpad, why="the pair surfaces in the terminator's own pad")
path("gnd", [(0.2 + FLASH_DX, -8.4 + FLASH_DY), (0.2 + FLASH_DX, -7.7 + FLASH_DY)])
board.via(GND, at(0.2 + FLASH_DX, -7.7 + FLASH_DY), why="the flash's exposed pad drops to the plane in the band under it")

# ---------------------------------------------------------------- the south face: six dives, the supply serves, the crystal diamond
for net, x_pin, y_via in [("SWCLK", 1.0, 2.2), ("SWDIO", 1.4, 3.0), ("RUN", 1.8, 3.8),
                          ("gpio27", -1.0, 2.2), ("gpio26", -1.4, 3.0), ("gpio25", -1.8, 3.8)]:
    s = 1.0 if x_pin > 0 else -1.0
    x_app = s * (RELIEF_X - RELIEF_RUN)
    d = max(abs(x_app - x_pin), 0.2)
    path(net, [(x_pin, PAD), (x_pin, y_via + d), (x_pin + s * d, y_via), (s * RELIEF_X, y_via)])
    board.via(Net(net), at(s * RELIEF_X, y_via), why="the south relief rows: the pins either side of the oscillator escape inward")
for inst, net, x_pin in [("c_iovdd2", "v3v3", -2.6), ("c_iovdd3", "v3v3", -0.6), ("c_dvdd1", "V1V1", 0.6)]:
    pad = PadRef(P(inst), net)
    board.track(Net(net), [at(x_pin, PAD), (X(MCU, x_pin), Y(pad, -(0.0))), pad], layer=F, chamfer=0.0,
                why="down the pin's axis, then one 45 into the cap's pad on its diagonal")


def xseg(net, table):
    """The crystal diamond's own frame: every vertex not on a package pad rides XTAL_DY south with the block."""
    for x1, y1, x2, y2 in table:
        pts = [(x1, y1 + (XTAL_DY if abs(y1 - PAD) > 1e-9 else 0.0)), (x2, y2 + (XTAL_DY if abs(y2 - PAD) > 1e-9 else 0.0))]
        path(net, pts)


xseg("OSC_XIN", [(-1.628858, 9.523223, -1.628858, 8.84232), (-1.628858, 8.84232, -2.560589, 7.910589),
                 (-2.560589, 7.910589, -1.754254, 7.910589), (-1.754254, 7.910589, -0.2, 6.356335), (-0.2, 6.356335, -0.2, PAD)])
xseg("OSC_Y_XOUT", [(1.128858, 9.876777, 1.621178, 9.384457), (1.621178, 9.384457, 1.621178, 8.271178), (1.621178, 8.271178, 0.971248, 7.621248)])
xseg("OSC_XOUT", [(0.2, PAD, 0.2, 6.85), (0.2, 6.85, 0.25, 6.9)])

# ---------------------------------------------------------------- the 1V1 island and the LED
ldo_out, ldo_in, ldo_en = PadRef(LDO, 5), PadRef(LDO, 3), PadRef(LDO, 1)
board.track(V1V1, [ldo_out, PadRef(P("c_ldo_out"), "V1V1")], layer=F, chamfer=0.0, why="OUT straight into its 1 uF on the pad axis")
board.track(V1V1, [ldo_out, PadRef(P("c_v1v1_bulk"), "V1V1")], layer=F, chamfer=0.0, why="and into the bulk cap on the same axis")
ci = PadRef(P("c_ldo_in"), "v3v3")
board.track(V3V3, [ci, ldo_in], layer=F, chamfer=0.0, why="the input cap into VIN")
board.track(V3V3, [ci, (X(ci), Y(ldo_en, -0.4)), (X(ci, -0.4), Y(ldo_en)), ldo_en], layer=F, chamfer=0.0, why="and up to EN, tied")
la, lr = PadRef(LED, "LED_PWR_NODE"), PadRef(P("r_led_pwr"), "LED_PWR_NODE")
board.track(Net("LED_PWR_NODE"), [la, (X(la), Y(lr, -0.9)), (X(lr), Y(lr, -0.9 + 0.0)), lr], layer=F, chamfer=0.0,
            why="the LED's anode down its axis, one 45 onto the resistor's column, in")

# ---------------------------------------------------------------- the plane hand-off: every cap on both pads, every ground pad
CAPS = ["c_adc_avdd", "c_dvdd0", "c_dvdd1", "c_dvdd2", "c_flash_vcc", "c_iovdd0", "c_iovdd1", "c_iovdd2", "c_iovdd3", "c_iovdd4",
        "c_iovdd5", "c_iovdd6", "c_iovdd7", "c_ldo_in", "c_ldo_out", "c_qspi_iovdd", "c_usb_otp_vdd", "c_v1v1_bulk", "c_vreg_vin_avdd"]
for inst in CAPS:
    for n in (1, 2):
        board.via(Net(board.pad(P(inst), n).net), PadRef(P(inst), n), why="a silent rail: the rail arrives by via, ground leaves by via")
board.via(GND, PadRef(MCU, 81), why="the exposed pad's centre")
for dx, dy in [(-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0)]:
    board.via(GND, at(dx, dy), why="the exposed pad's field")
board.via(GND, PadRef(Y1, 2))
board.via(GND, PadRef(Y1, 4))
board.via(GND, PadRef(LED, GND))
board.via(GND, PadRef(P("c_xtal_xin"), GND))
board.via(GND, PadRef(P("c_xtal_xout"), GND))
board.via(GND, PadRef(LDO, 2))
board.via(V3V3, PadRef(P("r_led_pwr"), V3V3))

board.faces(handoff=Edge.WEST, why="the gpio fans leave west and east; the USB pair and the flash sit north, the debug trio south")
