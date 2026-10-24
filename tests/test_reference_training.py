"""A human-routed board becomes a training record: its placed board has no tracks, vias or copper zones, and the
record holds the human's route as the outcome (tools/reference_training.py)."""
import importlib.util
from pathlib import Path

from tests.conftest import needs_kicad

ROOT = Path(__file__).resolve().parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location("reference_training", ROOT / "tools/reference_training.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _routed_board(tmp_path, tracks=True):
    import pcbnew
    mm, vec = pcbnew.FromMM, lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    board = pcbnew.CreateEmptyBoard()
    nets = {n: pcbnew.NETINFO_ITEM(board, n) for n in ("A", "B")}
    for n in nets.values():
        board.Add(n)
    for a, c in (((0, 0), (20, 0)), ((20, 0), (20, 20)), ((20, 20), (0, 20)), ((0, 20), (0, 0))):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        s.SetStart(vec(*a))
        s.SetEnd(vec(*c))
        board.Add(s)
    for ref, net, x, y in (("R1", "A", 4, 5), ("R2", "A", 16, 5), ("R3", "B", 4, 15), ("R4", "B", 16, 15)):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(vec(x, y))
        p = pcbnew.PAD(fp)
        p.SetNumber("1")
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(pcbnew.VECTOR2I(mm(1), mm(1)))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(pcbnew.PAD.SMDMask())
        p.SetPosition(vec(x, y))
        p.SetNet(nets[net])
        fp.Add(p)
        board.Add(fp)
    if tracks:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(vec(4, 5))
        t.SetEnd(vec(10, 5))
        t.SetWidth(mm(0.25))
        t.SetLayer(pcbnew.F_Cu)
        t.SetNet(nets["A"])
        board.Add(t)
        t2 = pcbnew.PCB_TRACK(board)
        t2.SetStart(vec(10, 5))
        t2.SetEnd(vec(16, 5))
        t2.SetWidth(mm(0.25))
        t2.SetLayer(pcbnew.F_Cu)
        t2.SetNet(nets["A"])
        board.Add(t2)
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(vec(10, 5))
        v.SetDrill(mm(0.3))
        v.SetWidth(mm(0.6))
        v.SetNet(nets["A"])
        board.Add(v)
    pcb = tmp_path / "human.kicad_pcb"
    board.Save(str(pcb))
    return pcb


@needs_kicad
def test_the_placed_board_has_no_tracks_vias_or_copper_zones(tmp_path):
    import pcbnew
    tool = _tool()
    tool.make_record(_routed_board(tmp_path), tmp_path / "out", "human", "kicad-demo:human", 0.25)
    placed = pcbnew.LoadBoard(str(tmp_path / "out/route/placed.kicad_pcb"))
    assert len(list(placed.GetTracks())) == 0
    assert [z for z in placed.Zones() if not z.GetIsRuleArea()] == []
    assert len(list(placed.GetFootprints())) == 4


@needs_kicad
def test_the_record_holds_the_humans_route(tmp_path):
    from placemat.kicad.training import read_raster
    tool = _tool()
    row = tool.make_record(_routed_board(tmp_path), tmp_path / "out", "human", "kicad-demo:human", 0.25)
    record, _ = read_raster(tmp_path / "out/route/training.json")
    assert record["source"] == "human" and record["board"] == "human" and record["origin"] == "kicad-demo:human"
    a, b = record["nets"]["A"], record["nets"]["B"]
    assert a["open_before"] == 1 and a["open_after"] == 0 and a["vias"] == 1 and a["track_mm"] > 11
    assert b["open_before"] == 1 and b["open_after"] == 1
    assert record["closure"] == 0.5 and row["closure"] == 0.5 and row["open_before"] == 2


@needs_kicad
def test_a_board_with_no_tracks_is_skipped(tmp_path):
    import pytest
    tool = _tool()
    with pytest.raises(tool.Skip, match="not routed"):
        tool.make_record(_routed_board(tmp_path, tracks=False), tmp_path / "out", "bare", "x", 0.25)


@needs_kicad
def test_the_collector_finds_the_record(tmp_path):
    spec = importlib.util.spec_from_file_location("training_collect", ROOT / "tools/training_collect.py")
    collect = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collect)
    _tool().make_record(_routed_board(tmp_path), tmp_path / "out/human", "human", "x", 0.25)
    assert len(collect.collect(tmp_path / "data", [tmp_path / "out"])) == 1
