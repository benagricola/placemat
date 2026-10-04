"""Synthetic modules for the arrangement tests: a regulator-like part with a bypass west of it and a pull-up east. Pure: no KiCad
until `kicad_cell_board`."""
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Beside, Edge, Location, Part
from tests.fixtures import board_geometry, footprint


def parts():
    return [footprint("U1", 20, 15, w=6, h=4, nets=("VIN", "OUT"), inst="u1"),
            footprint("C1", 8, 15, w=3, h=1.6, nets=("VIN", "GND"), inst="c_in"),
            footprint("R1", 33, 25, w=3, h=1.6, nets=("OUT", "GND"), inst="r_pull"),
            footprint("R2", 45, 8, w=3, h=1.6, nets=("OUT", "GND"), inst="r_free")]


def module(settings=None) -> Board:
    """u1 on its place, c_in west of it and r_pull east: the module as its script says it (r_free is not placed)."""
    b = Board(board_geometry(parts(), width=60, height=40), edge_margin=1.0, settings=settings or Settings())
    b.place(Part("u1"), at=Location(20, 15), why="the regulator")
    b.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST), why="bypass at VIN")
    b.place(Part("r_pull"), at=Beside(Part("u1"), Edge.EAST), why="pull-up at OUT")
    return b


import dataclasses

from placemat import arrangement_note as N
from placemat.arranged_geometry import attach
from placemat.copper import Track
from placemat.placement import Placement
from placemat.values import CopperLayer, Face


def stamped_geometry(offset=(30.0, 10.0), partner=None, obstacle=None, copper=()):
    """A board holding cell `mod` stamped from a fragment whose c_in stood at (1.0, 3.0) and u1 at (6.0, 3.0), moved by `offset`, and
    a loose part. The fragment's nets are `VIN`, `GND` and `OUT`; the board names them `mod.VIN` and so on. `partner=(x, y)` adds a
    part `r8` on the cell's VIN net there (the pull a search follows); `obstacle=(x, y, w, h)` adds a part `obst` that fills that box."""
    ox, oy = offset
    fps = [footprint("C1", 1.0 + ox, 3.0 + oy, w=3, h=1.6, nets=("mod.VIN", "mod.GND"), cell="mod", inst="mod.c_in"),
           footprint("U1", 6.0 + ox, 3.0 + oy, w=6, h=4, nets=("mod.VIN", "mod.OUT"), cell="mod", inst="mod.u1"),
           footprint("R9", 5, 5, nets=("mod.OUT", "GND"))]
    if partner is not None:
        fps.append(footprint("R8", partner[0], partner[1], w=3, h=1.6, nets=("mod.VIN", "GND"), inst="r8"))
    if obstacle is not None:
        x, y, w, h = obstacle
        fps.append(footprint("R7", x, y, w=w, h=h, nets=("GND", "GND"), inst="obst"))
    return board_geometry(fps, cells=["mod"], copper=copper, extra_nets=("mod.GND", "GND"), width=80, height=60)


DEFAULT_C_IN = Placement(Location(1.0, 3.0), 0.0, Face.FRONT)
DEFAULT_U1 = Placement(Location(6.0, 3.0), 0.0, Face.FRONT)
OBSTACLE = (43.0, 32.5, 2.0, 1.0)         # filled in the default's u1 and free in c_in.east, for a firm cell with its box centre on (40, 30)


# c_in turned half way round at (11.0, 3.0) has its VIN pad (pad 1) at (11.9, 3.0): the track runs east from it
EAST_TRACK = Track("VIN", CopperLayer.F, 0.3, Location(11.9, 3.0), Location(13.0, 3.0))


def east_doc(ident="c_in.east", order=1, ops=None, keepouts=()):
    """The note of an arrangement that turns c_in half way round and stands it east of u1 (fragment frame)."""
    east = Placement(Location(11.0, 3.0), 180.0, Face.FRONT)
    ops = [EAST_TRACK] if ops is None else ops
    return N.document(ident, {"c_in": "east"}, [("c_in", east, DEFAULT_C_IN), ("u1", DEFAULT_U1, DEFAULT_U1)], ops,
                      list(keepouts), order=order)


def still_doc(ops=(), keepouts=(), ident="still"):
    """The note of an arrangement that moves no member: its geometry is the default's, with the module's copper `ops`."""
    return N.document(ident, {}, [("c_in", DEFAULT_C_IN, DEFAULT_C_IN), ("u1", DEFAULT_U1, DEFAULT_U1)], list(ops), list(keepouts),
                      order=1)


def with_arrangement(g=None, doc=None):
    """`stamped_geometry` whose cell `mod` carries the note `doc` read as the reader reads it."""
    g = g or stamped_geometry()
    texts = N.encode(doc or east_doc(), 4000)
    cell = attach(g.cells["mod"], texts, frozenset(g.nets), g.layers)
    return dataclasses.replace(g, cells={**g.cells, "mod": cell})


def kicad_cell_board(path, cells=(("mod", (30.0, 10.0)),), notes=None):
    """A 2-layer board of stamped cells (pcbnew, no libraries): each a group of c_in and u1 at the module's places (1.0, 3.0) and (6.0, 3.0) moved
    by the cell's offset. A footprint has no Path field, so its instance is its reference, `<cell>.c_in`."""
    import pcbnew
    mm = pcbnew.FromMM
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)
    names = ["GND"] + ["%s.%s" % (c, n) for c, _ in cells for n in ("VIN", "GND", "OUT")]
    info = {}
    for n in names:
        info[n] = pcbnew.NETINFO_ITEM(board, n)
        board.Add(info[n])
    rect = getattr(pcbnew, "PAD_SHAPE_RECT", None) or pcbnew.PAD_SHAPE_RECTANGLE
    for cell, (ox, oy) in cells:
        group = pcbnew.PCB_GROUP(board)
        group.SetName(cell)
        board.Add(group)
        for inst, x, y, n1, n2 in (("c_in", 1.0, 3.0, "VIN", "GND"), ("u1", 6.0, 3.0, "VIN", "OUT")):
            fp = pcbnew.FOOTPRINT(board)
            fp.SetReference("%s.%s" % (cell, inst))
            board.Add(fp)
            fp.SetPosition(pcbnew.VECTOR2I(mm(x + ox), mm(y + oy)))
            for number, dx, net in (("1", -0.9, n1), ("2", 0.9, n2)):
                pad = pcbnew.PAD(fp)
                pad.SetNumber(number)
                pad.SetShape(rect)
                pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
                pad.SetSize(pcbnew.VECTOR2I(mm(1.0), mm(1.0)))
                pad.SetLayerSet(pad.SMDMask())
                pad.SetNet(info["%s.%s" % (cell, net)])
                fp.Add(pad)
                pad.SetPosition(pcbnew.VECTOR2I(mm(x + ox + dx), mm(y + oy)))
            group.AddItem(fp)
        track = pcbnew.PCB_TRACK(board)                     # the cell's own stamped copper
        track.SetLayer(pcbnew.F_Cu)
        track.SetNet(info["%s.GND" % cell])
        track.SetWidth(mm(0.3))
        track.SetStart(pcbnew.VECTOR2I(mm(ox), mm(oy + 4.0)))
        track.SetEnd(pcbnew.VECTOR2I(mm(ox + 2.0), mm(oy + 4.0)))
        board.Add(track)
        group.AddItem(track)
        for text in (notes or {}).get(cell, ()):
            t = pcbnew.PCB_TEXT(board)
            t.SetText(text)
            t.SetLayer(pcbnew.Cmts_User)
            t.SetPosition(pcbnew.VECTOR2I(mm(ox), mm(oy + 20)))
            board.Add(t)
            group.AddItem(t)
    board.Save(str(path))
    return path
