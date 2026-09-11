#!/usr/bin/env python3
"""THE SHAPE OF A PLACEMENT SCRIPT. Not a board - a scaffold to copy.

This file defines the format. A new placement script starts as a copy of it,
and an existing script that does not match it is migrated to it (SKILL step 0)
before anything else is done to that script. When the format changes, it
changes HERE first, and the scripts follow.

A SCRIPT DECLARES; THE LIBRARY SCHEDULES. The script contributes CONFIG and
stage BODIES. It does not decide when anything runs: a body runs when its stage
runs, not where it is written. That is what stops the file being the scheduler -
the order statements happen to appear in decides nothing - not which candidate
gets scarce room, not what board state a validation is asked about.

THE RUNNER OWNS THE ENVIRONMENT. It resolves the board and the project,
prepares the interpreter, reads the config below, builds the two and runs the
stages:

    placemat run <board>                     (and `placemat round` calls it)

So this file carries NO path arithmetic, no sys.path insert, no bytecode
switch, no board-path-off-argv, and it constructs neither. `context()` names the
two the runner builds; the raw board is `board.pcb` and the stamped cells `board.cells`.

Three rules give the file its shape, and everything below is one of them:

  CONFIG is what comes from OUTSIDE the circuit.  Board size, mounting,
  reserved bands, the nets that matter, which cell faces which way. These are a
  person's to decide because nothing in the schematic implies them - an
  enclosure, a motor's hole pitch, a fab rule, where a hand has to reach. Every
  value carries the SOURCE that fixes it, because a number whose origin is
  unrecorded cannot be changed by anyone but its author, and is usually not
  changed at all. It stays module-level: neither object exists until the frame
  and the plane nets are known.

  THE LINK WEIGHTS ARE THE EXCEPTION, and they are the model's to decide. What
  a millimetre costs on a connection is an ELECTRICAL fact, readable from the
  topology and the datasheets: which node is high-impedance, which loop
  switches fast, which cap is bypass and which is bulk, which end of a filter
  faces the load. So an agent laying a board out assigns them itself, for every
  link the circuit gives an answer for, rather than waiting to be told. Record
  the REASON on each one and the LIMIT wherever the circuit implies a length -
  a weight with no reason cannot be argued with, and being argued with is the
  point: the owner overrides the ones they disagree with, and can only do that
  if they can see what the number was for.

  What a person decides is CONSTRAINTS, not positions. Position is derived: a
  cell settles by search on real geometry, a block searches off its anchor's
  own pads, a loose part is seeded on its own nets. So a coordinate in a script
  is one of exactly two things and its comment says which - a MECHANICAL FACT
  no search may overrule (a hole pitch, a case window, the edge a plug enters
  at), or a HINT, a starting guess the search is free to leave and usually
  does. Writing a coordinate for every part is not the job and does not
  survive: the next part that moves invalidates the arithmetic behind it, and
  a file of numbers nothing chose is a file nobody can safely change. Give the
  machinery the constraint and let it find the position.

  MECHANISM is stage BODIES, in library calls.  The stages are fixed and in
  dependency order - frame, anchors, cells, loose, copper, drops, repair, silk,
  report - because each reads what the one before it left. A hand-rolled helper
  in a body is a bug: it does not get the library's later fixes, and it makes
  this board differ from its siblings for no reason a reader can see.

  WITHIN a stage, the order bodies run in must not matter. That is a testable
  claim, and it is tested: the shuffle gate permutes registration and requires
  the same board. A stage whose bodies do not commute is a stage boundary in
  the wrong place - the answer is another stage, not a convention about where
  to write things.

The board's own docstring replaces this one and says: what the board is, its
face law (which face carries what, and why), and how to regenerate it.
"""
from placemat import stage, context

layout, board = context()   # layout is the artwork; board is the board


# =============================================================================
# CONFIG - what a person decides. Every value names its source.
# =============================================================================

# THE STACKUP, FIRST (SKILL round step 2). How many copper layers, what each
# is FOR, and which nets a plane already carries - placement, via cost and
# corridor budget all differ between a two-layer board and one with planes, and
# a net on a plane is not routed at all.
LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu")   # source: the board's intent doc
PLANE_NETS = {"GND", "3V3"}                     # carried by a plane: never routed, never priced as adjacency

# THE FRAME. State both dimensions even when they are equal - a height that
# comes from a default is a height nobody chose. Three sources are legitimate
# and the comment says which one applies: locked to a mechanical part, computed
# from the floorplan (set below, in the frame section, and say so here), or
# chosen outright.
BOARD_W, BOARD_H = 56.4, 56.4     # source: <what fixes this - a case, a motor face, a host board>
CHAMFER = 2.0                     # source: <fab minimum / enclosure corner radius>
MOUNT_INSET = 3.8                 # source: <the mounting pattern this bolts to, e.g. a motor's hole pitch>

# NETS THE SCRIPT NAMES. A layout script references nets by string and the
# schematic can rename one; nothing then errors, it just quietly does nothing.
# Every net name the script depends on goes here and through require_nets().
NETS_USED = PLANE_NETS | {"<rail>", "<signal>"}

# BANDS SPOKEN FOR by copper that is not drawn yet, each with its reason and
# the nets it carries (a rail's own bulk cap belongs ON the bar that feeds it).
# no_vias extends the claim to holes, so a stripped plane via is not re-dropped
# into a lane.
#
# ONLY the claims whose position is known INDEPENDENTLY of any placement go
# here, because this list is read in the frame stage, before anything is placed.
# A claim whose position depends on where something landed - a connector's
# mating volume, a lane off a cell's frontier - is reserved in the body that
# places that thing, right after the call that fixes it.
RESERVED = (
    # (x0, y0, x1, y1, layer, why, allow_nets, no_vias)
    (0.0, 0.0, 0.0, 0.0, "F.Cu", "<the copper that will land here>", ("<net>",), True),
)

# CLEARANCE WAIVERS, scoped to one cell, with the reason. A waiver without a
# reason is a silenced check.
WAIVERS = (
    # (cell, mm, why)
    ("<cell>", 0.20, "<why the board's class cannot be met inside this cell>"),
)

# WHICH WAY EACH CELL SHOULD FACE, as {cell: a net whose copper marks its
# front}. A stamped cell in the right place, the right way up and facing the
# wrong way is the easiest error to miss; the report prints this every pass.
CELL_FACING = {"<cell>": "<net>"}

# =============================================================================
# MECHANISM - stage bodies, in library calls.
# Below this line, prefer a library call to any local code. If the call you
# want does not exist, see SKILL "Script discipline": search the library by
# CONCEPT first, then propose the addition - do not write a private copy.
# `layout` and `board` are the names context() gave the runner's objects.
# =============================================================================


@stage("frame")
def _frame():
    """Outline, mounting, and any keepout volume no netlist carries (a mating
    volume, an antenna window, a creepage gap). First, because everything else
    is placed against it."""
    layout.both_faces = True                            # parts on both faces: render the bottom too
    board.require_nets(NETS_USED)                     # a schematic rename fails HERE, naming the net
    for x0, y0, x1, y1, layer, why, allow, no_vias in RESERVED:
        board.reserve(x0, y0, x1, y1, layer=layer, why=why, allow=allow, no_vias=no_vias)
    for cell, mm, why in WAIVERS:
        board.cell_clearance(cell, mm, why=why)       # written to the sibling .kicad_dru on save
    board.outline_chamfered(CHAMFER)
    for inst, (x, y) in {"mh1": (MOUNT_INSET, MOUNT_INSET)}.items():
        board.fix(inst, x, y)
    board.rule_area(0.0, 0.0, 0.0, 0.0, name="<what this volume is for>")
    board.note_rect(0.0, 0.0, 0.0, 0.0)               # ...and record WHY it is empty


@stage("anchors")
def _anchors():
    """Whatever the layout does not get to choose. Connectors first (tactic 7):
    the enclosure and the field wiring fix their edge and orientation, and
    everything else packs around them. A sensor whose position IS its function
    belongs here too - an encoder over the shaft centre, a current sensor in the
    bus path - and so does anything on a mating pattern."""
    board.place("<connector inst>", 0.0, 0.0, 0)
    board.edge_align("<connector inst>", "N")
    # the mating volume is reserved HERE, not in CONFIG: its position is not
    # known until the connector has one
    _box = board.box_of("<connector inst>")
    board.reserve(_box[0], _box[1], _box[2], _box[3], layer="F.Cu",
               why="<what mates here, and the room it needs>", no_vias=True)


@stage("cells")
def _cells():
    """Every stamped fragment. Hand the whole stage over at once: the order is
    an allocation of area, adjacency and standoff, so it is DERIVED from the
    requests rather than being the order the calls are written in."""
    board.settle_all([
        dict(inst="<cell>", x=0.0, y=0.0, rot=0, radius=9.0),
        dict(inst="<cell needing standoff>", x=0.0, y=0.0, apart_from=("<the aggressor>",)),
    ])


@stage("loose")
def _loose():
    """Individual parts, likewise handed over as a stage. Each is seeded on its
    OWN nets, never on a typed coordinate: a hint is a guess at where there is
    room and carries nothing about where the part's net is."""
    board.place_free_all([
        dict(inst="<inst>", x=0.0, y=0.0),
    ])
    board.retry_fallbacks()
    board.purge()                                     # the doomed copper goes; the drops are settled at save


@stage("copper")
def _copper():
    """Pours and planes for power, thin traces for signals. After placement,
    because most of it is anchored on where the parts actually landed."""
    board.plane("GND", layers=("In1.Cu",))
    board.pour("<rail>", [(0.0, 0.0, 0.0, 0.0)], layer="F.Cu")
    layout.poly("<rail>", board.band_with_notches("<rail>", 0.0, 0.0, 0.0, 0.0))


@stage("repair")
def _repair():
    """Re-run the legality tests against copper that did not exist when the
    parts were placed, and move only what actually broke. Report what moved: a
    silent repair is indistinguishable from a decision."""
    board.resettle_free()


@stage("silk")
def _silk():
    """Refdes to the fab layer on a dense board (assembly reads the CPL); the
    silk is then free for the markings a person needs at the bench. A ROW of
    labels is aligned, never centred, and anything landing on something else is
    moved off it once both are down."""
    layout.refs_to_fab()
    board.label_at_part("<inst>", "<TEXT>", 0.0)
    _t = board.label("<TEXT>", 0.0, 0.0, rot=90, align="bottom")
    board.clear_of(_t, (0.0, 0.0, 0.0, 0.0), gap=0.4, side="W")
    board.silk_line(0.0, 0.0, 0.0, 0.0)               # a boundary a person has to see
    board.mockup("MOCK1", "<path to .wrl>", 0.0, 0.0)  # what plugs in, for the iso render


@stage("report")
def _report():
    """What the next pass is judged against: where every cell landed and which
    way it faces. The SAVE is the runner's, not this file's."""
    board.stamp_report(CELL_FACING)
