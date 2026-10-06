import json

import pytest

from fixtures.reference import fetch, prepare

pcbnew = pytest.importorskip("pcbnew")

BOARD = fetch.Board(name="tiny", repo="github:o/r", commit="0" * 40, files={}, board="tiny.kicad_pcb", licence="MIT",
                    tests=("a",), islands=(), fixed=(), human_track_mm=None, kicad5=False)


def _two_layer_board(path, rename=False):
    mm = pcbnew.FromMM
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    if rename:
        board.SetLayerName(pcbnew.F_Cu, "Top")
        board.SetLayerName(pcbnew.B_Cu, "Bottom")
    net = pcbnew.NETINFO_ITEM(board, "SIG")
    gnd = pcbnew.NETINFO_ITEM(board, "GND")
    board.Add(net)
    board.Add(gnd)
    for i, x in enumerate((10, 20)):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference("R%d" % (i + 1))
        fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(10)))
        pad = pcbnew.PAD(fp)
        pad.SetNumber("1")
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pad.SMDMask())
        pad.SetSize(pcbnew.VECTOR2I(mm(1), mm(1)))
        pad.SetPosition(pcbnew.VECTOR2I(mm(x), mm(10)))
        pad.SetNet(net)
        fp.Add(pad)
        board.Add(fp)
    track = pcbnew.PCB_TRACK(board)
    track.SetStart(pcbnew.VECTOR2I(mm(10), mm(10)))
    track.SetEnd(pcbnew.VECTOR2I(mm(20), mm(10)))
    track.SetWidth(mm(0.25))
    track.SetLayer(pcbnew.F_Cu)
    track.SetNet(net)
    board.Add(track)
    zone = pcbnew.ZONE(board)
    zone.SetLayer(pcbnew.B_Cu)
    zone.SetNet(gnd)
    outline = pcbnew.VECTOR_VECTOR2I([pcbnew.VECTOR2I(mm(x), mm(y)) for x, y in ((5, 5), (25, 5), (25, 15), (5, 15))])
    zone.AddPolygon(outline)
    board.Add(zone)
    pcbnew.SaveBoard(str(path), board)
    (path.with_suffix(".kicad_pro")).write_text("{}")


def _loaded(path):
    return pcbnew.LoadBoard(str(path))


@pytest.mark.parametrize("rename", [False, True])
def test_prepare_strips_tracks_keeps_zone_and_layers_count(tmp_path, rename):
    src, work = tmp_path / "src", tmp_path / "work"
    src.mkdir()
    _two_layer_board(src / "tiny.kicad_pcb", rename)
    prepared = prepare.prepare(BOARD, src, work)
    assert len(_loaded(prepared.test).GetTracks()) == 0
    assert len(_loaded(prepared.test).Zones()) == 1
    assert len(_loaded(prepared.ref).GetTracks()) == 1
    assert prepared.layers == 2
    assert prepared.human.vias == 0 and prepared.human.track_mm == pytest.approx(10.0, abs=0.01)
    if rename:
        assert _loaded(prepared.test).GetLayerName(pcbnew.F_Cu) == "Top"


def test_violations_keeps_errors_and_leaves_out_silk_courtyard_and_library_types(tmp_path):
    item = lambda d, x, y: {"description": d, "pos": {"x": x, "y": y}}
    report = {"violations": [
        {"type": "clearance", "severity": "error", "items": [item("Track [A] on F.Cu", 1.5, 2.5), item("Pad 1 [B] of R1", 3, 4)]},
        {"type": "silk_overlap", "severity": "error", "items": [item("Text", 0, 0)]},
        {"type": "courtyards_overlap", "severity": "error", "items": []},
        {"type": "lib_footprint_issues", "severity": "error", "items": []},
        {"type": "track_dangling", "severity": "warning", "items": []},
    ]}
    path = tmp_path / "d.json"
    path.write_text(json.dumps(report))
    assert prepare.violations(path) == [prepare.Violation("clearance", ("A", "B"), (1.5, 2.5))]
