import pytest

from placemat import arrangement_note as N
from placemat.copper import Track, Via, Zone
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board, PlacedKeepout
from placemat.values import Cell, CopperLayer, Drops, Face, Location, Net
from tests.arrangement_support import EAST_TRACK, east_doc, kicad_cell_board
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def staged(tmp_path, cells=(("mod", (30.0, 10.0)),), doc=None):
    texts = N.encode(doc or east_doc(), 4000)
    return kicad_cell_board(tmp_path / "layout.kicad_pcb", cells, notes={c: texts for c, _ in cells})


def written(pcb, plan, cell):
    """Each member of `cell` as the board holds it, against where the search's committed geometry put it. A back part's turn is
    compared by its pads: placemat counts a flipped part's rotation from its generated pose, KiCad's orientation adds the flip's
    half turn (kicad/write.py _place_footprint)."""
    after = read_board(pcb)
    out = []
    for fp in after.cell(cell).members:
        got = plan.occupancy.items[fp.ref]
        pads = sorted((p.number, round(p.box.center.x, 3), round(p.box.center.y, 3)) for p in fp.pads)
        judged = sorted((s.label, round(s.box.center.x, 3), round(s.box.center.y, 3)) for s in got.shapes if s.kind == "pad")
        out.append((fp.inst, fp.location, got.reference.location, pads, judged, fp.face, got.reference.face))
    return out


def assert_as_judged(rows):
    for inst, at, want, pads, judged, face, wface in rows:
        assert abs(at.x - want.x) < 1e-3 and abs(at.y - want.y) < 1e-3, inst
        assert pads == judged and face == wface, inst


def place(pcb, plane=None, **kw):
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    if plane is not None:
        b.plane(Net(plane), layers=(CopperLayer.B,))
    for cell, args in kw.items():
        b.place(Cell(cell), **args)
    return b


@pytest.mark.parametrize("rotation, face", [(0, Face.FRONT), (90, Face.FRONT), (0, Face.BACK), (270, Face.BACK)])
def test_an_arranged_cell_turned_or_flipped_is_written_where_the_search_judged_it(tmp_path, rotation, face):
    """Review focus 3."""
    pcb = staged(tmp_path)
    b = place(pcb, mod=dict(at=Location(40.0, 30.0), rotation=rotation, face=face, arrangements="c_in.east"))
    plan = b.resolve()
    apply_plan(pcb, plan)
    assert_as_judged(written(pcb, plan, "mod"))


def test_the_group_is_intact_after_the_arrangement_deletes_its_copper(tmp_path):
    """The saved board, loaded again, holds the cell's group whole: its items are wrapped and answer for their place. It reloads
    from disk, so it does not show the in-process breakage CLAUDE.md warns of, which small boards do not reproduce anyway."""
    import pcbnew
    pcb = staged(tmp_path)
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    group = next(g for g in board.Groups() if g.GetName() == "mod")
    items = list(group.GetItems())
    assert items and not any(type(i).__name__ == "SwigPyObject" for i in items)
    assert [i.GetPosition() for i in items if isinstance(i, pcbnew.FOOTPRINT)]
    assert [i.GetStart() for i in board.GetTracks()]


def test_the_arrangements_copper_replaces_the_stamped_copper_and_the_note_is_dropped(tmp_path):
    import pcbnew
    pcb = staged(tmp_path)
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    assert [t.GetNetname() for t in board.GetTracks()] == ["mod.VIN"]
    assert not [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(N.ARRANGEMENT_PREFIX)]


def test_two_stamps_of_one_module_choose_and_are_written_independently(tmp_path):
    """Review focus 1: cell A in c_in.east, cell B in the default; nets map per cell."""
    pcb = staged(tmp_path, (("mod_a", (30.0, 10.0)), ("mod_b", (30.0, 40.0))))
    b = place(pcb, mod_a=dict(at=Location(20.0, 15.0), arrangements="c_in.east"),
              mod_b=dict(at=Location(60.0, 45.0), arrangements="default"))
    plan = b.resolve()
    assert plan.placement("mod_a").arrangement == "c_in.east" and plan.placement("mod_b").arrangement == ""
    apply_plan(pcb, plan)
    assert_as_judged(written(pcb, plan, "mod_a") + written(pcb, plan, "mod_b"))
    import pcbnew
    nets = sorted(t.GetNetname() for t in pcbnew.LoadBoard(str(pcb)).GetTracks())
    assert nets == ["mod_a.VIN", "mod_b.GND"]                  # A's copper is its arrangement's, in A's nets; B keeps the copper it was stamped with


def test_a_cell_placed_in_its_default_drops_its_notes_and_keeps_its_copper(tmp_path):
    import pcbnew
    pcb = staged(tmp_path)
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="default")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    assert not [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(N.ARRANGEMENT_PREFIX)]
    assert [t.GetNetname() for t in board.GetTracks()] == ["mod.GND"]                 # the stamped copper, which kicad_cell_board draws


def test_a_board_with_no_arranged_cell_is_written_as_before(tmp_path):
    pcb = staged(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    other = kicad_cell_board(plain / "layout.kicad_pcb", (("mod", (30.0, 10.0)),))
    for p in (pcb, other):
        apply_plan(p, place(p, mod=dict(at=Location(40.0, 30.0))).resolve())
    import pcbnew
    live = lambda p: sorted((f.GetReference(), f.GetPosition().x, f.GetPosition().y) for f in pcbnew.LoadBoard(str(p)).GetFootprints())
    assert live(pcb) == live(other)


# In the fragment's frame c_in.east stands c_in at (11.0, 3.0) turned half way round: its GND pad (pad 2) is at (10.1, 3.0). The default's
# GND pad of c_in is at (1.9, 3.0), and nothing of u1 is at x 10.1: a field there is found only against the arranged pad.
FIELD = [Via("GND", Location(9.85, 3.0), 0.15, 0.3), Via("GND", Location(10.35, 3.0), 0.15, 0.3)]


def test_a_moved_members_field_is_thinned_against_its_arranged_pad(tmp_path):
    """Pre-flight 15: drops= applies to the arranged copper, so a field in a member the arrangement moved is thinned."""
    import pcbnew
    pcb = staged(tmp_path, doc=east_doc(ops=FIELD))
    plan = place(pcb, plane="mod.GND", mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east", drops=Drops.HALF)).resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    assert len(plan.thinned["mod"]) == 1                                    # a field of two keeps one
    gone = plan.thinned["mod"][0]
    assert abs(gone[1] - 13.0) < 1e-6 and min(abs(gone[0] - 39.85), abs(gone[0] - 40.35)) < 1e-6     # in the generated board's frame
    held = [s for s in plan.occupancy.copper if s.owner == "mod" and s.kind == "through"]
    assert len(held) == 1
    note = next(n for n in plan.steps[[s.item for s in plan.steps].index("mod")].notes if n.get("kind") == "drops")
    assert note["fields"] == [{"ref": "mod.c_in", "pad": "2", "kept": 1, "of": 2}]      # the arranged field, not the default's
    apply_plan(pcb, plan)
    vias = [t for t in pcbnew.LoadBoard(str(pcb)).GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    assert len(vias) == 1


def test_an_arranged_cell_with_no_drops_keeps_its_whole_field(tmp_path):
    import pcbnew
    pcb = staged(tmp_path, doc=east_doc(ops=FIELD))
    plan = place(pcb, plane="mod.GND", mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    assert "mod" not in plan.thinned
    apply_plan(pcb, plan)
    assert len([t for t in pcbnew.LoadBoard(str(pcb)).GetTracks() if isinstance(t, pcbnew.PCB_VIA)]) == 2


def _stamp_zone_and_rule_area(pcb):
    """Give cell `mod` a stamped copper zone and rule area of its own, in its group, as a fragment's stamp brings them."""
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    group = next(g for g in board.Groups() if g.GetName() == "mod")
    for rule in (False, True):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(rule)
        if rule:
            z.SetLayerSet(pcbnew.LSET.AllCuMask(2))
            z.SetDoNotAllowTracks(True)
            z.SetZoneName("keepout old [*.Cu]_1")
        else:
            z.SetLayer(pcbnew.F_Cu)
            z.SetNetCode(board.FindNet("mod.GND").GetNetCode())
        o = z.Outline()
        o.NewOutline()
        for x, y in ((30.0, 8.0), (33.0, 8.0), (33.0, 9.0), (30.0, 9.0)):
            o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
        board.Add(z)
        group.AddItem(z)
    board.Save(str(pcb))


def test_the_arrangements_zone_and_rule_area_replace_the_stamped_ones_once(tmp_path):
    """Task 2.1: an arranged zone has no owner; the writer deletes the group's zones and draws the arrangement's, so the board holds it
    once. The note's keepout is written by the code that writes a stamped default's (write.rule_area)."""
    import pcbnew
    zone = Zone("GND", CopperLayer.F, ((9.0, 0.0), (12.0, 0.0), (12.0, 1.0), (9.0, 1.0)))
    guard = PlacedKeepout("guard", ((9.0, 5.0), (12.0, 5.0), (12.0, 6.0), (9.0, 6.0)), Location(0.0, 0.0), 0.0, ("tracks", "vias"),
                          None, frozenset(), frozenset(), "", None, frozenset(), frozenset())
    pcb = staged(tmp_path, doc=east_doc(ops=[zone], keepouts=[guard]))
    _stamp_zone_and_rule_area(pcb)
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    group = next(g for g in board.Groups() if g.GetName() == "mod")
    in_group = {it.m_Uuid.AsString() for it in group.GetItems()}
    copper = [z for z in board.Zones() if not z.GetIsRuleArea()]
    rules = [z for z in board.Zones() if z.GetIsRuleArea()]
    assert [z.GetNetname() for z in copper] == ["mod.GND"]
    assert [z.GetZoneName() for z in rules] == ["keepout guard [*.Cu]_1"]                   # pcb's suffix, as a stamped default has it
    assert all(z.m_Uuid.AsString() in in_group for z in copper + rules)
    assert copper[0].IsFilled() and copper[0].CalculateFilledArea() > 0         # drawn unfilled, filled once the cell is moved
    r = rules[0]
    assert r.GetDoNotAllowTracks() and r.GetDoNotAllowVias() and not r.GetDoNotAllowFootprints()
    assert r.GetLayerSet().CuStack().size() == 2
    # moved with the cell: the zone's box is as wide as the note's, about where the cell went
    bb = copper[0].GetBoundingBox()
    assert abs(pcbnew.ToMM(bb.GetWidth()) - 3.0) < 0.01 and abs(pcbnew.ToMM(bb.GetHeight()) - 1.0) < 0.01


def test_an_arranged_keepout_that_lets_a_net_through_is_written_with_its_rule(tmp_path):
    """The arrangement's rule area carries its allow= nets as the fragment's zone did, and the board's .kicad_dru holds its rule over
    the board's net names, as for a stamped default's."""
    import pcbnew
    lane = PlacedKeepout("lane", ((9.0, 5.0), (12.0, 5.0), (12.0, 6.0), (9.0, 6.0)), Location(0.0, 0.0), 0.0, ("tracks",), None,
                         frozenset({"VIN"}), frozenset(), "", None, frozenset(), frozenset())
    pcb = staged(tmp_path, doc=east_doc(keepouts=[lane]))
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    apply_plan(pcb, plan)
    rules = [z for z in pcbnew.LoadBoard(str(pcb)).Zones() if z.GetIsRuleArea()]
    assert [z.GetZoneName() for z in rules] == ["keepout lane [*.Cu] {allow VIN | tracks}_1"]
    assert not rules[0].GetDoNotAllowTracks()
    dru = (tmp_path / "layout.kicad_dru").read_text()
    assert "intersectsArea('keepout lane [*.Cu] {allow VIN | tracks}_1')" in dru and "A.NetName != 'mod.VIN'" in dru


LANE = PlacedKeepout("lane", ((9.0, 5.0), (12.0, 5.0), (12.0, 6.0), (9.0, 6.0)), Location(0.0, 0.0), 0.0, ("tracks",), None,
                     frozenset({"VIN"}), frozenset(), "", None, frozenset(), frozenset())
LANE_ZONE = "keepout lane [*.Cu] {allow VIN | tracks}"


def _stamp_keepout(pcb, cell, origin, drawing=True):
    """Give `cell` the stamped default of LANE as pcb stamps it: the rule area (named with pcb's `_1`) a little west of the
    arrangement's, and, with `drawing`, the keepout drawing the fragment drew for it (outline and label on User.Comments)."""
    import pcbnew
    mm = pcbnew.FromMM
    board = pcbnew.LoadBoard(str(pcb))
    group = next(g for g in board.Groups() if g.GetName() == cell)
    ox, oy = origin
    pts = [(ox + x, oy + y) for x, y in ((5.0, 5.0), (8.0, 5.0), (8.0, 6.0), (5.0, 6.0))]
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    z.SetLayerSet(pcbnew.LSET.AllCuMask(2))
    z.SetDoNotAllowVias(True)
    z.SetZoneName(LANE_ZONE + "_1")
    o = z.Outline()
    o.NewOutline()
    for x, y in pts:
        o.Append(mm(x), mm(y))
    board.Add(z)
    group.AddItem(z)
    if drawing:
        sh = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
        sh.SetLayer(pcbnew.Cmts_User)
        ps = pcbnew.SHAPE_POLY_SET()
        ps.NewOutline()
        for x, y in pts:
            ps.Append(mm(x), mm(y))
        sh.SetPolyShape(ps)
        board.Add(sh)
        group.AddItem(sh)
        t = pcbnew.PCB_TEXT(board)
        t.SetText("lane")
        t.SetLayer(pcbnew.Cmts_User)
        t.SetPosition(pcbnew.VECTOR2I(mm(ox + 6.5), mm(oy + 5.5)))
        board.Add(t)
        group.AddItem(t)
    board.Save(str(pcb))


def test_an_arranged_keepouts_drawing_replaces_the_stamped_ones(tmp_path):
    """The fragment drew its admitting keepout as an outline and a label; arranged, the cell's drawing is the arrangement's keepout's,
    once, where its rule area is."""
    import pcbnew
    pcb = staged(tmp_path, doc=east_doc(keepouts=[LANE]))
    _stamp_keepout(pcb, "mod", (30.0, 10.0))
    plan = place(pcb, mod=dict(at=Location(40.0, 30.0), arrangements="c_in.east")).resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    (area,) = [z for z in board.Zones() if z.GetIsRuleArea()]
    outlines = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE) and d.GetLayer() == pcbnew.Cmts_User]
    labels = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText() == "lane"]
    assert len(outlines) == 1 and len(labels) == 1
    ab, ob = area.GetBoundingBox(), outlines[0].GetPolyShape().BBox()
    near = lambda a, b: abs(pcbnew.ToMM(a - b)) < 0.01
    assert near(ab.GetLeft(), ob.GetLeft()) and near(ab.GetRight(), ob.GetRight()) and near(ab.GetTop(), ob.GetTop()) \
        and near(ab.GetBottom(), ob.GetBottom())                            # the outline is the arranged area's, not the default's
    c = ab.GetCenter()
    assert near(labels[0].GetPosition().x, c.x) and near(labels[0].GetPosition().y, c.y)
    group = next(g for g in board.Groups() if g.GetName() == "mod")
    mine = {it.m_Uuid.AsString() for it in group.GetItems()}
    assert outlines[0].m_Uuid.AsString() in mine and labels[0].m_Uuid.AsString() in mine


def test_two_arranged_stamps_name_their_areas_apart_and_each_rule_names_its_own(tmp_path):
    """pcb stamps a module's keepout as `<name>_1` in every cell; two arranged stamps must not share a name, or each cell's
    AllowRule (`intersectsArea`) would cover the other's area too. KiCad's DRC passes A's VIN in A's lane."""
    import json
    import subprocess
    import pcbnew
    pcb = staged(tmp_path, (("mod_a", (30.0, 10.0)), ("mod_b", (30.0, 40.0))), doc=east_doc(keepouts=[LANE]))
    _stamp_keepout(pcb, "mod_a", (30.0, 10.0), drawing=False)
    _stamp_keepout(pcb, "mod_b", (30.0, 40.0), drawing=False)
    b = place(pcb, mod_a=dict(at=Location(20.0, 15.0), arrangements="c_in.east"),
              mod_b=dict(at=Location(60.0, 45.0), arrangements="c_in.east"))
    plan = b.resolve()
    apply_plan(pcb, plan)
    board = pcbnew.LoadBoard(str(pcb))
    by_cell = {g.GetName(): [it for it in g.GetItems() if isinstance(it, pcbnew.ZONE) and it.GetIsRuleArea()] for g in board.Groups()}
    (za,), (zb,) = by_cell["mod_a"], by_cell["mod_b"]
    assert za.GetZoneName() != zb.GetZoneName() and {za.GetZoneName(), zb.GetZoneName()} <= {LANE_ZONE + "_1", LANE_ZONE + "_2"}
    dru = (tmp_path / "layout.kicad_dru").read_text()
    rules = [r for r in dru.split("(rule ")[1:] if "intersectsArea" in r]
    assert len(rules) == 2
    for z, net in ((za, "mod_a.VIN"), (zb, "mod_b.VIN")):
        (rule,) = [r for r in rules if "A.NetName != '%s'" % net in r]
        assert "intersectsArea('%s')" % z.GetZoneName() in rule and rule.count("intersectsArea") == 1
    # a track of A's VIN across A's lane: allowed there, and B's rule does not reach it
    c = za.GetBoundingBox().GetCenter()
    t = pcbnew.PCB_TRACK(board)
    t.SetLayer(pcbnew.F_Cu)
    t.SetWidth(pcbnew.FromMM(0.2))
    t.SetStart(pcbnew.VECTOR2I(c.x - pcbnew.FromMM(1.0), c.y))
    t.SetEnd(pcbnew.VECTOR2I(c.x + pcbnew.FromMM(1.0), c.y))
    t.SetNet(board.FindNet("mod_a.VIN"))
    board.Add(t)
    board.Save(str(pcb))
    (tmp_path / "layout.kicad_pro").write_text("{}")
    out = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)], capture_output=True, timeout=120)
    flagged = [v for v in json.loads(out.read_text())["violations"] if v["type"] == "items_not_allowed"]
    assert flagged == []
