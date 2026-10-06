"""kicad.remap: a variant's pin remap made on its written board before the explore routes it. The pads the map names
take their new nets; an escape laid from one follows it, and copper that runs on to another pad of its old net is
deleted for the router to lay again; a part the remap's pose turns is turned about its pivot
and the copper laid from its pads is deleted; a flipped pose is not made."""
import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad


def _board(path):
    """U1 at (10, 10) with pads 1-4 on nets A-D, 1 mm apart down x = 12; a track of net A from pad 1 out east, on
    through a via to a second track; a track of net B from pad 2; R1 on net A (the far end of the track)."""
    import pcbnew
    mm = pcbnew.FromMM
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)
    info = {}
    for n in ("A", "B", "C", "D"):
        info[n] = pcbnew.NETINFO_ITEM(board, n)
        board.Add(info[n])
    rect = getattr(pcbnew, "PAD_SHAPE_RECT", None) or pcbnew.PAD_SHAPE_RECTANGLE

    def part(ref, x, y, pads):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        board.Add(fp)
        fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        for number, px, py, net in pads:
            pad = pcbnew.PAD(fp)
            pad.SetNumber(number)
            pad.SetShape(rect)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            pad.SetSize(pcbnew.VECTOR2I(mm(0.6), mm(0.6)))
            pad.SetLayerSet(pad.SMDMask())
            pad.SetNet(info[net])
            fp.Add(pad)
            pad.SetPosition(pcbnew.VECTOR2I(mm(px), mm(py)))
    part("U1", 10, 10, [(str(k + 1), 12, 8.5 + k, n) for k, n in enumerate("ABCD")])
    part("R1", 20, 8.5, [("1", 20, 8.5, "A")])

    def track(net, a, b):
        t = pcbnew.PCB_TRACK(board)
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(info[net])
        t.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
        t.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
        t.SetWidth(mm(0.2))
        board.Add(t)
    track("A", (12, 8.5), (15, 8.5))
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(mm(15), mm(8.5)))
    via.SetNet(info["A"])
    via.SetWidth(mm(0.6))
    via.SetDrill(mm(0.3))
    board.Add(via)
    track("A", (15, 8.5), (20, 8.5))
    track("B", (12, 9.5), (15, 9.5))
    board.Save(str(path))


SWAP = {"refs": ["U1"], "present": 1.0, "best": 0.0,
        "map": [{"ref": "U1", "net": "A", "from": {"pin": "1", "name": ""}, "to": {"pin": "2", "name": ""}},
                {"ref": "U1", "net": "B", "from": {"pin": "2", "name": ""}, "to": {"pin": "1", "name": ""}}],
        "turns": [{"ref": "U1", "turn_deg": 0.0, "rotation_deg": 0.0, "face": "front", "flip": False}]}


def _read(path):
    import pcbnew
    board = pcbnew.LoadBoard(str(path))
    u1 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "U1")
    pads = {p.GetNumber(): p.GetNetname() for p in u1.Pads()}
    tracks = sorted((round(pcbnew.ToMM(t.GetStart().x), 3), round(pcbnew.ToMM(t.GetStart().y), 3), t.GetNetname(),
                     isinstance(t, pcbnew.PCB_VIA)) for t in board.GetTracks())
    return board, u1, pads, tracks


def test_the_swapped_pads_take_their_new_nets_an_escape_follows_and_a_connection_goes(tmp_path):
    from placemat.kicad.remap import apply_remap
    pcb = tmp_path / "layout.kicad_pcb"
    _board(pcb)
    got = apply_remap(pcb, [SWAP])
    _, _, pads, tracks = _read(pcb)
    assert pads == {"1": "B", "2": "A", "3": "C", "4": "D"}
    # pad 1's track runs through its via on to R1's pad, which keeps A: deleted; pad 2's escape takes A
    assert tracks == [(12.0, 9.5, "A", False)]
    assert got == {"pads": 2, "tracks": 1, "deleted": 3, "turned": [], "not_turned": []}


def test_a_pad_a_net_leaves_for_an_unused_pin_has_no_net_and_its_copper_goes(tmp_path):
    from placemat.kicad.remap import apply_remap
    pcb = tmp_path / "layout.kicad_pcb"
    _board(pcb)
    move = dict(SWAP, map=[{"ref": "U1", "net": "B", "from": {"pin": "2", "name": ""}, "to": {"pin": "4", "name": ""}},
                           {"ref": "U1", "net": "D", "from": {"pin": "4", "name": ""}, "to": {"pin": "3", "name": ""}},
                           {"ref": "U1", "net": "C", "from": {"pin": "3", "name": ""}, "to": {"pin": "2", "name": ""}}])
    apply_remap(pcb, [move])
    _, _, pads, tracks = _read(pcb)
    assert pads == {"1": "A", "2": "C", "3": "D", "4": "B"}
    assert (12.0, 9.5, "C", False) in tracks


def test_a_turned_part_is_turned_about_its_pivot_and_the_copper_laid_from_its_pads_is_deleted(tmp_path):
    import pcbnew
    from placemat.kicad.remap import apply_remap
    pcb = tmp_path / "layout.kicad_pcb"
    _board(pcb)
    turned = dict(SWAP, turns=[{"ref": "U1", "turn_deg": 90.0, "rotation_deg": 90.0, "face": "front", "flip": False,
                                "pivot": [10.0, 10.0]}])
    got = apply_remap(pcb, [turned])
    _, u1, pads, tracks = _read(pcb)
    assert pads["1"] == "B" and pads["2"] == "A"
    assert u1.GetOrientationDegrees() == pytest.approx(90.0)
    p1 = next(p for p in u1.Pads() if p.GetNumber() == "1").GetPosition()
    assert (round(pcbnew.ToMM(p1.x), 3), round(pcbnew.ToMM(p1.y), 3)) == (8.5, 8.0)     # (12, 8.5) a quarter turn about (10, 10)
    assert tracks == [] and got["deleted"] == 4 and got["turned"] == ["U1"]


def test_a_flipped_pose_is_not_made_and_is_named(tmp_path):
    from placemat.kicad.remap import apply_remap
    pcb = tmp_path / "layout.kicad_pcb"
    _board(pcb)
    flipped = dict(SWAP, turns=[{"ref": "U1", "turn_deg": 0.0, "rotation_deg": 180.0, "face": "back", "flip": True,
                                 "pivot": [10.0, 10.0]}])
    got = apply_remap(pcb, [flipped])
    _, u1, pads, _ = _read(pcb)
    assert pads["1"] == "B" and u1.GetOrientationDegrees() == pytest.approx(0.0) and not u1.IsFlipped()
    assert got["not_turned"] == ["U1"] and got["turned"] == []
