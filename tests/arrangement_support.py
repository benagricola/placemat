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


def stamp_fragment(board, fragment_pcb, cell, offset):
    """Stamp the module fragment at `fragment_pcb` into `board` (a pcbnew BOARD) as group `cell`, the way `pcb layout` does
    (pcb-layout kicad_adapter.py `_apply_fragment_routing`): each track, via, zone and drawing (its notes among them) duplicated from
    the fragment's board with `BOARD_ITEM.Duplicate`, put on the cell's net `<cell>.<net>`, moved by `offset` (mm) and added to the
    group, a zone's priority raised by one (FRAGMENT_ZONE_PRIORITY_BIAS). pcb makes the footprints from their libraries and stands
    them where the fragment has them, each with a reference of the board's; here each is duplicated from the fragment, numbered
    on when the board has its reference already, its pads put on the cell's nets and its Path `<cell>.<path>`. Returns the group."""
    import pcbnew
    frag = pcbnew.LoadBoard(str(fragment_pcb))
    group = pcbnew.PCB_GROUP(board)
    group.SetName(cell)
    board.Add(group)
    nets = {}

    def net_of(src):
        name = src.GetNetname()
        if not name:
            return None
        full = "%s.%s" % (cell, name)
        if full not in nets:
            info = board.FindNet(full)
            if info is None:
                info = pcbnew.NETINFO_ITEM(board, full)
                board.Add(info)
            nets[full] = info
        return nets[full]

    shift = pcbnew.VECTOR2I(pcbnew.FromMM(offset[0]), pcbnew.FromMM(offset[1]))

    def dup(src, connected=True):
        item = pcbnew.BOARD_ITEM.Duplicate(src)
        if connected:
            info = net_of(src)
            if info is not None:
                item.SetNet(info)
        board.Add(item)
        item.Move(shift)
        group.AddItem(item)
        return item

    refs = {fp.GetReference() for fp in board.GetFootprints()}

    def fresh(ref):                     # a board's references are its own: a second stamp's parts are numbered on
        if ref not in refs:
            return ref
        letters = ref.rstrip("0123456789")
        n = 1
        while "%s%d" % (letters, n) in refs:
            n += 1
        return "%s%d" % (letters, n)

    for src in frag.GetFootprints():
        fp = pcbnew.Cast_to_FOOTPRINT(pcbnew.BOARD_ITEM.Duplicate(src))
        fp.SetReference(fresh(fp.GetReference()))
        refs.add(fp.GetReference())
        for pad, was in zip(fp.Pads(), src.Pads()):
            info = net_of(was)
            if info is not None:
                pad.SetNet(info)
        board.Add(fp)
        fp.Move(shift)
        try:
            path = fp.GetFieldText("Path")
        except KeyError:
            path = ""
        if path:
            fp.SetField("Path", "%s.%s" % (cell, path))
        else:
            fp.SetReference("%s.%s" % (cell, fp.GetReference()))
        group.AddItem(fp)
    for src in frag.GetTracks():
        dup(src)
    for src in frag.Zones():
        zone = dup(src)
        zone.SetAssignedPriority(src.GetAssignedPriority() + 1)
    for src in frag.GetDrawings():
        dup(src, connected=False)
    return group


def stamp_fragment_as_cells(fragment_pcb, out_pcb, cells):
    """A board of the module fragment at `fragment_pcb` stamped once for each `{cell: offset}` (`stamp_fragment`), saved at `out_pcb`.
    The board starts as the fragment's own with its items deleted, so it keeps the fragment's layers and setup; the project and rules
    files are copied beside it."""
    import pathlib
    import shutil
    import pcbnew
    fragment_pcb, out_pcb = pathlib.Path(fragment_pcb), pathlib.Path(out_pcb)
    board = pcbnew.LoadBoard(str(fragment_pcb))
    for item in list(board.GetFootprints()) + list(board.GetTracks()) + list(board.Zones()) + list(board.GetDrawings()):
        board.Delete(item)
    for cell, offset in cells.items():
        stamp_fragment(board, fragment_pcb, cell, offset)
    board.Save(str(out_pcb))
    for ext in (".kicad_pro", ".kicad_dru"):
        if fragment_pcb.with_suffix(ext).exists():
            shutil.copy(fragment_pcb.with_suffix(ext), out_pcb.with_suffix(ext))
    return out_pcb


def stamp_fragment_as_cell(fragment_pcb, out_pcb, cell, offset):
    """What `pcb layout` does with a module fragment: its parts, copper, rule areas and notes become one group `cell` on a board, the
    instance paths and nets prefixed by the cell's name, the group moved by `offset`. The project and rules files are copied beside it."""
    return stamp_fragment_as_cells(fragment_pcb, out_pcb, {cell: offset})


def synthetic_notes_for(pcb) -> dict:
    """Write a note into every cell of the board at `pcb` that has two or more members: the arrangement `turn` leaves every member where it
    is and turns the smallest one half way round about its own origin (the stamped frame is taken as the fragment's, offset 0). Returns
    {cell: "turn"} for the cells that got one."""
    import pcbnew
    from placemat.kicad.read import read_board
    geometry = read_board(pcb)
    board = pcbnew.LoadBoard(str(pcb))
    groups = {g.GetName(): g for g in board.Groups()}
    done = {}
    for name, cell in sorted(geometry.cells.items()):
        prefix = name + "."
        members = [fp for fp in cell.members if fp.inst.startswith(prefix)]
        if len(cell.members) < 2 or len(members) != len(cell.members) or name not in groups:
            continue
        smallest = min(members, key=lambda fp: (fp.body_box.area, fp.inst))
        rows = []
        for fp in members:
            # the place as the note's json holds it (4 places): the note's digest is taken from the place it is given and read
            # back from the json's, which round to 3 places apart for a coordinate such as 33.680469 (33.68 against 33.681)
            was = N.pose_from_json(N.pose_json(Placement(fp.location, fp.rotation, fp.face)))
            now = Placement(was.location, (was.rotation + 180.0) % 360.0, was.face) if fp is smallest else was
            rows.append((fp.inst[len(prefix):], now, was))
        doc = N.document("turn", {"turn": "half"}, rows, [], [], order=1)
        for text in N.encode(doc, 4000):
            t = pcbnew.PCB_TEXT(board)
            t.SetText(text)
            t.SetLayer(pcbnew.Cmts_User)
            board.Add(t)
            groups[name].AddItem(t)
        done[name] = "turn"
    board.Save(str(pcb))
    return done
