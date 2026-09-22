"""GnssAntenna: the 1575MHz chain from the radiator to a 50 ohm feed.

A fragment, not a board. It exists so that this corner's geometry - the
clearance, the network's distance from the feed node, every pad-to-pad gap - is
settled ONCE and then carried onto whatever board wants it. Change the board's
diameter or move a connector and none of this is re-derived.

THE FRAME'S y = 0 IS THE BOARD EDGE and +y runs INBOARD, so everything is
measured from the edge the reference is drawn against. Stamped onto a board, the
cell is turned so +y points at the board's centre.

IT IS WIDE, NOT TALL. The feed leaves its pad going LEFT (Ben, 2026-09-19), so
the matching network sits BESIDE the clearance rather than under it - which is
how the reference runs it, the 50 ohm line leaving the land sideways and the
components following it. The clearance takes the right of the frame and the
network the left.

WHAT THE BOARD STILL OWES IT, because a cell cannot carry either:
  - a ground plane its GND pads can reach;
  - room. The clearance must not be clipped by the board's edge, so the cell has
    to be placed far enough in that its whole frame is on the board.

NOTHING HERE IS A TYPED ANGLE OR A TYPED GAP. `facing()` reads which end of a
footprint a net lands on and returns the rotation that points it where it is
wanted; the gaps come from the real pads and courtyards. A part swapped in the
.zen cannot leave a stale number behind.
"""
import math

from placemat import (board, Centre, CopperLayer, Location, Net, PadRef, Part,
                      Path, Pin, X, Y)

def _turned(w: float, h: float, rotation: float) -> tuple:
    """A box's two dimensions once the part is turned. Pad and courtyard boxes
    both come off the GENERATED board, which is unrotated, so a quarter turn
    swaps them. Getting this wrong is what spaces a neighbour by a part's LENGTH
    when the part is standing on end."""
    return (h, w) if round(rotation) % 180 == 90 else (w, h)

# --- measuring the parts, so no rotation or gap below is a typed number -----
# Courtyards touching is not enough between two parts in the RF path: the
# courtyard excess is smaller than the copper clearance on some of these
# footprints, so the class clearance goes into the spacing explicitly.
RF_GAP = board.netclass(Net("ANT_FEED")).clearance


def pad_offset(part, key, rotation: float) -> tuple:
    """A pad's offset from its part's centre, once the part is turned.

    KiCad's footprint angle is counter-clockwise in a frame whose y runs DOWN,
    so this is not the textbook rotation - the y row carries the minus sign.
    Taken from pcbnew's own absolute pad positions on a placed board, which is
    the only way to check it: reading the .kicad_pcb back with a hand-written
    transform tests that transform against itself and agrees with whatever it
    already believes.

    Getting the sign wrong mirrors every rotation derived here. That does not
    collide and does not fail - it quietly puts each part's wrong end against
    its neighbour, and the board looks right until someone reads the nets."""
    crt = board.part(part).courtyard_box
    pad = board.pad(part, key).box.center
    dx, dy = pad.x - crt.center.x, pad.y - crt.center.y
    a = math.radians(rotation)
    return (dx * math.cos(a) + dy * math.sin(a),
            -dx * math.sin(a) + dy * math.cos(a))


def facing(part, key, axis: str, side: float, base: float = 0.0) -> float:
    """The rotation - `base` or `base` + 180 - that puts this part's `key` pad on
    `side` of its own body along `axis`.

    Which END of a footprint a net lands on is a property of the part, so a
    rotation typed by hand is a guess that a part swap silently invalidates.
    This reads it off the placed pads instead, which is why nothing below says
    a bare angle: every one of them says which way the pad has to point."""
    for rot in (base, base + 180.0):
        rx, ry = pad_offset(part, key, rot)
        if (rx if axis == "x" else ry) * side > 0:
            return rot % 360.0
    return base % 360.0


def courtyard_half(part, rotation: float, axis: str) -> float:
    """Half the part's COURTYARD along `axis`, once turned. Not `board.extent`,
    which is the BODY box: the run collides on courtyards, and on a small
    passive the courtyard is the larger of the two, so sizing a gap on the body
    leaves a part that fits by the script's arithmetic and overlaps by the
    tool's."""
    crt = board.part(part).courtyard_box
    w, h = _turned(crt.width, crt.height, rotation)
    return (w if axis == "x" else h) / 2.0


def pad_half(part, key, rotation: float, axis: str) -> float:
    """Half the pad's own size along `axis`, once the part is turned."""
    b = board.pad(part, key).box
    w, h = _turned(b.width, b.height, rotation)
    return (w if axis == "x" else h) / 2.0


def pad_to_courtyard(part, key, rotation: float, axis: str, side: float) -> float:
    """Distance from a pad's centre out to the part's courtyard edge on `side`
    (+1 for the increasing direction), along `axis`, once the part is turned.
    The pad is not at the courtyard's centre, so this is not half a courtyard."""
    crt = board.part(part).courtyard_box
    rx, ry = pad_offset(part, key, rotation)
    w, h = _turned(crt.width, crt.height, rotation)
    half = (w if axis == "x" else h) / 2.0
    return half - side * (rx if axis == "x" else ry)


# Two courtyards that merely TOUCH are reported as overlapping, so a gap sized
# to touch exactly loses to rounding. This is the margin that keeps it a touch.
# It is a workaround for the tool rather than anything the board needs - see
# TASKS.md, toolchain.
COURTYARD_TOUCH = 0.01


def gap_between(a, a_key, a_rot, b, b_key, b_rot, axis: str, side: float) -> float:
    """Pad centre to pad centre for two parts set beside each other along
    `axis`, `b` on `side` of `a` (+1 for the increasing direction). Returns the
    distance, unsigned.

    It has to clear BOTH rules at once: the courtyards may not overlap, which is
    what stops a run, and the copper wants RF_GAP between it, which is what the
    netclass asks for. Whichever is larger wins. `side` matters because a pad is
    not in the middle of its part - reading the courtyard from the wrong side is
    what spaces one shunt twice as far out as the other."""
    courtyards = (pad_to_courtyard(a, a_key, a_rot, axis, side)
                  + pad_to_courtyard(b, b_key, b_rot, axis, -side)
                  + COURTYARD_TOUCH)
    copper = (pad_half(a, a_key, a_rot, axis) + RF_GAP
              + pad_half(b, b_key, b_rot, axis))
    return max(courtyards, copper)



def shunt_across(cap, key, rot: float) -> float:
    """How far a shunt's body centre sits from R1's, across the corridor. The
    receiver is placed against the outer edge of this too, so it is its own
    function rather than a line inside the placement."""
    rx = pad_offset(cap, key, rot)[0]
    sep = (pad_half(Part("r_ant_series"), key, SERIES_ROT, "x") + RF_GAP
           + pad_half(cap, key, rot, "x"))
    return max(sep + abs(rx),
               courtyard_half(Part("r_ant_series"), SERIES_ROT, "x")
               + COURTYARD_TOUCH + courtyard_half(cap, rot, "x"))


def shunt_at(cap, key, rot: float, side: float, node_ry: float):
    """A shunt's placement beside R1, its live pad level with the R1 pad it
    shares `key` with and `side` of the corridor (+1 east). The live pad's own
    offset from its body goes into the reach, so the pad lands where it is
    wanted whichever way round the footprint numbers its ends."""
    across = shunt_across(cap, key, rot)
    return Centre(X(Part("r_ant_series"), side * across),
                  Y(Part("r_ant_series"), node_ry - pad_offset(cap, key, rot)[1]))


# --- the antenna's clearance, transcribed from the datasheet -----------------
# Pulse W3011, datasheet p6: "All metallization should be removed from all PWB
# layers on ground clearance area (4,00 x 4,25 mm)", and DETAIL B draws the
# opening in the bottom and inner ground layers as exactly that rectangle.
#
# Measured from the BOARD EDGE, which is y = 0 here: the clearance runs 4.25 in
# from it, and the antenna's pads start 0.40 in and run 1.84 deep, being the 1.6
# body plus the 0.12 the pads stand proud top and bottom. The part is centred on
# its pads, so its middle is at 0.40 + 0.92 = 1.32.
# THE BOARD EDGE IS THE DATUM and every number below is measured from it, the
# way the reference is dimensioned. It cannot sit at the frame's own y = 0:
# placemat holds a part off a frame's edge and `board.keep_in` is read-only, so
# the whole cell sits EDGE_Y in and the datum is that line. A parent placing this
# cell aligns EDGE_Y with the board's rim, not the cell's corner.
EDGE_Y = 0.5
CLEARANCE_W, CLEARANCE_D = 4.00, 4.25
ANT_PAD_INSET = 0.40                # pad edge to board edge
ANT_PAD_DEPTH = 1.84                # 1.6 body + 0.12 proud each side
ANT_PAD_W = 0.80                    # pad width along the antenna's axis
ANT_Y = EDGE_Y + ANT_PAD_INSET + ANT_PAD_DEPTH / 2.0

# THE FEED LEAVES LEFT, so the part is turned to put its feed pad on the left
# end. Said as a requirement rather than an angle: ask for the wrong side and the
# part turns a half circle and the single ground land ends up where the split
# pair belongs.
ANT_ROT = facing(Part("ant"), "ANT_TRACE", "x", -1.0, base=0.0)
ANT_FEED_DX, ANT_FEED_DY = pad_offset(Part("ant"), "ANT_TRACE", ANT_ROT)

# The 50 ohm feed's width, needed here because the corridor it runs down sets
# where the u.FL goes. 0.35mm on F.Cu over the first inner plane, about 0.2mm of
# prepreg away on a 1.6mm four-layer stackup, is close to 50 ohm - the same basis
# as the note in Front.zen. The netclass still reports 0.2, which is a default
# and not a computed impedance; see TASKS.md.
# THE FINGER IS DRAWN WIDER THAN IT IS DECLARED. placemat writes it as a filled
# polygon carrying a stroke of the netclass track width, and KiCad counts a
# stroked fill's outline as copper too - so a finger asked for at w comes out
# w + track_width of actual copper. Declare the difference, not the target.
FEED_COPPER_W = 0.35                # what we want on the board
FEED_W = FEED_COPPER_W - board.netclass(Net("ANT_FEED")).track_width

# --- the matching network, BESIDE the clearance ------------------------------
# The corridor runs LEFT from the feed pad, so "along" it is x and "across" it
# is y. The series element lies along it; the shunts stand across it at its two
# ends, each reaching away from the line to the plane.
SERIES_ROT = facing(Part("r_ant_series"), "ANT_TRACE", "x", +1.0, base=0.0)
SHUNT2_ROT = facing(Part("c_ant_shunt2"), "ANT_TRACE", "y", -1.0, base=90.0)
SHUNT1_ROT = facing(Part("c_ant_shunt1"), "ANT_FEED", "y", -1.0, base=90.0)

# How wide the network is, so the frame can hold it left of the clearance.
NET_SPAN = (courtyard_half(Part("c_ant_shunt2"), SHUNT2_ROT, "x")
            + shunt_across(Part("c_ant_shunt2"), "ANT_TRACE", SHUNT2_ROT)
            + shunt_across(Part("c_ant_shunt1"), "ANT_FEED", SHUNT1_ROT)
            + courtyard_half(Part("c_ant_shunt1"), SHUNT1_ROT, "x"))
FRAME_MARGIN = 0.5                  # left only; y = 0 is the board edge
# Detail C (datasheet p6, "Opening in other layers (no ground/RF)"): 6.51 x
# 5.44, centred on the antenna and measured from the datum like Detail B. It
# stands 1.26 wider than the ground clearance on the antenna's far side, so
# the frame's right margin holds it.
DETAIL_C_W, DETAIL_C_D = 6.51, 5.44
FRAME_MARGIN_RIGHT = (DETAIL_C_W - CLEARANCE_W) / 2.0 + 0.1

# The left margin is the frame's own: the feed finger runs FRAME_MARGIN past
# the leftmost shunt's courtyard to the frame's edge, which a board stamping
# the cell reads as its feed exit.
NET_LEFT = FRAME_MARGIN
FRAME_W = NET_LEFT + NET_SPAN + RF_GAP + CLEARANCE_W + FRAME_MARGIN_RIGHT

CLEARANCE_LEFT = FRAME_W - FRAME_MARGIN_RIGHT - CLEARANCE_W
ANT_AT = Location(CLEARANCE_LEFT + CLEARANCE_W / 2.0, ANT_Y)
board.place(Part("ant"), at=ANT_AT, rotation=ANT_ROT,
            why="the only part whose performance is set by what is not near it")

# THE CLEARANCE DOES NOT TURN WITH THE PART. It is a rectangle symmetric about
# the antenna's axis, so which end feeds cannot mirror it, and tying it to the
# part's rotation would swing the 4.25 that must run inboard the other way.
# A BITE OUT OF ITS RIGHT EDGE, so the plane can reach the single ground land at
# that end. Without it the land sits in the cleared area with nothing to connect
# to - the same defect the Abracon had. The bite clears the pad by the 0.12 the
# datasheet already specifies as the pads' proud edge, which is the only padding
# figure the part gives.
GND_PAD_PAD = 0.12                  # datasheet p7: the pads stand this proud
_gnd_notch_x = (CLEARANCE_W / 2.0 + abs(ANT_FEED_DX)
                - ANT_PAD_W / 2.0 - GND_PAD_PAD)
_gnd_notch_dy = ANT_PAD_DEPTH / 2.0 + GND_PAD_PAD

board.keepout(Path([(0.0, EDGE_Y), (CLEARANCE_W, EDGE_Y),
                    (CLEARANCE_W, ANT_Y - _gnd_notch_dy),
                    (_gnd_notch_x, ANT_Y - _gnd_notch_dy),
                    (_gnd_notch_x, ANT_Y + _gnd_notch_dy),
                    (CLEARANCE_W, ANT_Y + _gnd_notch_dy),
                    (CLEARANCE_W, EDGE_Y + CLEARANCE_D), (0.0, EDGE_Y + CLEARANCE_D)],
                   anchor=(CLEARANCE_W / 2.0, ANT_Y)),
              "antenna", at=Location(ANT_AT.x, ANT_AT.y), rotation=0.0,
              # ALL FOUR LAYERS, NAMED, THOUGH THE FRAGMENT KEEPS TWO. Left unsaid, a
# keepout covers the layers of the board it is written on, and a module's
# `Layout()` takes no layer count, so this fragment is two and KiCad drops the
# inner pair when it saves the rule area. Naming them is still what the
# datasheet says, and it is what a parent reads: the board that stamps this
# restates the shape on its own four and measures 0.00% of metal inside it on
# the three layers that are not the antenna's own pads.
              layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B),
              # GND is allowed to RUN through, which is not the same as letting the plane
# fill: the exclusion is "fill", written as a KiCad rule area, and that still
# stops the zone. What this permits is the explicit finger that takes the split
# pair's ground out to the plane.
              excludes=("fill",),
              allow=(Part("ant"), Net("ANT_TRACE"), Net("GND")),
              why="W3011 p6: no metallisation on any of the four layers inside this shape")

# DETAIL C: the larger opening on every layer that carries neither the ground
# plane nor the feed. This cell owns the feed on F and a ground plane on F and
# B; the board that stamps it puts its ground plane on IN1 and its rail on
# IN2, so IN2 is that layer here. The shape follows the part like Detail B.
board.keepout(Path([(CLEARANCE_W / 2.0 - DETAIL_C_W / 2.0, EDGE_Y),
                    (CLEARANCE_W / 2.0 + DETAIL_C_W / 2.0, EDGE_Y),
                    (CLEARANCE_W / 2.0 + DETAIL_C_W / 2.0, EDGE_Y + DETAIL_C_D),
                    (CLEARANCE_W / 2.0 - DETAIL_C_W / 2.0, EDGE_Y + DETAIL_C_D)],
                   anchor=(CLEARANCE_W / 2.0, ANT_Y)),
              "antenna_c", at=Location(ANT_AT.x, ANT_AT.y), rotation=0.0,
              layers=(CopperLayer.IN2,), excludes=("fill", "tracks", "vias", "pads"),
              # the cell's own feed and the split pair's ground finger lie on F,
              # which this region does not cover; named so the check knows
              allow=(Net("ANT_TRACE"), Net("ANT_FEED"), Net("GND")),
              why="W3011 p6 Detail C: 6.51 x 5.44 open on the layers that are neither ground nor the feed")

# The series element, clear of the keepout by the class clearance - it is a
# copper keep-out, so what a part outside it owes the boundary is the gap it
# owes any other copper.
# Clear of the keepout by the class clearance - and it is the SHUNT that has to
# clear it, not the series element. c_ant_shunt2 stands across the corridor at
# R1's antenna-side pad, so it reaches further toward the clearance than R1's own
# body does; sizing this on R1 walks the shunt into the antenna.
SERIES_X = (CLEARANCE_LEFT - RF_GAP
            - shunt_across(Part("c_ant_shunt2"), "ANT_TRACE", SHUNT2_ROT)
            - courtyard_half(Part("c_ant_shunt2"), SHUNT2_ROT, "x"))
FEED_Y = ANT_AT.y + ANT_FEED_DY     # the line the corridor runs along
board.place(Part("r_ant_series"), rotation=SERIES_ROT,
            at=Location(SERIES_X, FEED_Y),
            why="the series element, on the feed's line just clear of the clearance")


def shunt_beside(cap, key, rot: float, side: float):
    """A shunt standing ACROSS the corridor at one end of the series element,
    its live pad against the R1 pad it shares `key` with. `side` is +1 toward
    the antenna. The live pad's own offset goes into the reach, so it lands
    where it is wanted whichever way round the footprint numbers its ends."""
    across = shunt_across(cap, key, rot)
    return Centre(X(Part("r_ant_series"), side * across),
                  Y(Part("r_ant_series"), -pad_offset(cap, key, rot)[1]))


board.place(Part("c_ant_shunt2"), rotation=SHUNT2_ROT,
            at=shunt_beside(Part("c_ant_shunt2"), "ANT_TRACE", SHUNT2_ROT, +1.0),
            why="antenna-side shunt, live pad against R1's ANT_TRACE, ground away")
board.place(Part("c_ant_shunt1"), rotation=SHUNT1_ROT,
            at=shunt_beside(Part("c_ant_shunt1"), "ANT_FEED", SHUNT1_ROT, -1.0),
            why="feed-side shunt, live pad against R1's ANT_FEED, ground away")

# --- the frame's bottom ------------------------------------------------------
# The network's real bottom is not the series element's: the shunts stand
# ACROSS the corridor and are offset from its line by their own pad, so each
# reaches FEED_Y plus that offset plus its half height.
def net_reach_below(cap, key, rot: float) -> float:
    """How far below the corridor's line a shunt standing across it reaches."""
    return abs(pad_offset(cap, key, rot)[1]) + courtyard_half(cap, rot, "y")


NET_BOTTOM = FEED_Y + max(
    net_reach_below(Part("c_ant_shunt2"), "ANT_TRACE", SHUNT2_ROT),
    net_reach_below(Part("c_ant_shunt1"), "ANT_FEED", SHUNT1_ROT),
    courtyard_half(Part("r_ant_series"), SERIES_ROT, "y"))
# The diagnostic u.FL that used to hang below the network is the board's now
# (Main.zen: it is 2.5 tall and has to stand where the case allows it); the
# frame ends at the network's bottom or the clearance's, whichever is lower.
FRAME_H = max(EDGE_Y + CLEARANCE_D, EDGE_Y + DETAIL_C_D, NET_BOTTOM) + FRAME_MARGIN + COURTYARD_TOUCH
board.size(FRAME_W, FRAME_H, draw=False)

# --- the 50 ohm feed ---------------------------------------------------------
# FINGERS, not tracks. A finger is a rectangular pour of a set width along a
# centreline, which is what a controlled-impedance feed is; a track would come
# out at the netclass width, and the netclass is not set for 50 ohm - it reports
# 0.2mm, which is a default and not a computed impedance. See TASKS.md.
#
# 0.35mm on F.Cu over the first inner plane, about 0.2mm of prepreg away on a
# 1.6mm four-layer stackup, is close to 50 ohm. That is the same basis as the
# note in Front.zen: 0.35 over 0.2, rather than 2.9mm over the full 1.6.

# Two runs, because the series element breaks the line. Each ends on a pad
# rather than a coordinate, so both follow when the network moves.
board.finger(Net("ANT_TRACE"), layer=CopperLayer.F,
             from_=PadRef(Part("ant"), "ANT_TRACE"),
             to=PadRef(Part("r_ant_series"), "ANT_TRACE"), width=FEED_W,
             why="the launch: the antenna's feed pad to the match")
board.finger(Net("ANT_FEED"), layer=CopperLayer.F,
             from_=PadRef(Part("r_ant_series"), "ANT_FEED"),
             to=Location(0.0, FEED_Y), width=FEED_W,
             why="the 50 ohm feed, out of the module's left edge")

# THE SPLIT PAIR'S GROUND NEEDS A TRACE. The land at the far end gets the plane
# by the bite in the keepout above, but this one sits in the middle of the
# cleared area and has no such option - the clearance is there precisely so the
# plane is not. So it runs out to the fill on its own copper, at the feed's width
# so the two sides of the launch are symmetric.
SPLIT_PITCH = 1.19                  # feed contact to its neighbouring ground
_a = math.radians(ANT_ROT)
SPLIT_GND_X = ANT_AT.x + ANT_FEED_DX + SPLIT_PITCH * math.sin(_a)
SPLIT_GND_Y = ANT_AT.y + ANT_FEED_DY + SPLIT_PITCH * math.cos(_a)
board.finger(Net("GND"), layer=CopperLayer.F,
             from_=Location(SPLIT_GND_X, SPLIT_GND_Y),
             to=Location(CLEARANCE_LEFT - FEED_COPPER_W, SPLIT_GND_Y),
             width=FEED_W,
             why="the split pair's ground, out of the clearance to the plane")

# --- the module's own ground -------------------------------------------------
# IT CARRIES ITS OWN PLANE rather than relying on the board's. A chip antenna
# radiates off the ground plane - the plane IS the other half of the radiator -
# so "the board will have ground somewhere near it" is not a specification.
#
# On a board that has its own GND plane there will be two zones on the same net
# overlapping. That is fine and deliberate: KiCad merges same-net zones when it
# fills, so the module's plane joins the board's rather than fighting it.
board.plane(Net("GND"), layers=(CopperLayer.F, CopperLayer.B),
            why="the antenna's other half, carried with it rather than assumed")
