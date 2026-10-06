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


def test_violations_read_the_same_whichever_order_the_items_are_listed(tmp_path):
    a = {"description": "Track [A] on F.Cu", "pos": {"x": 1.5, "y": 2.5}}
    b = {"description": "Pad 1 [B] of R1", "pos": {"x": 3, "y": 4}}
    paths = []
    for name, items in (("one", [a, b]), ("two", [b, a])):
        paths.append(tmp_path / (name + ".json"))
        paths[-1].write_text(json.dumps({"violations": [{"type": "clearance", "severity": "error", "items": items}]}))
    assert prepare.violations(paths[0]) == prepare.violations(paths[1]) == [prepare.Violation("clearance", ("A", "B"), (1.5, 2.5))]


KICAD5_BOARD = """(kicad_pcb (version 20171130) (host pcbnew 5.1.10)
  (general (thickness 1.6))
  (page A4)
  (layers (0 F.Cu signal) (31 B.Cu signal) (44 Edge.Cuts user))
  (setup (last_trace_width 0.25) (trace_clearance 0.2) (zone_clearance 0.508) (zone_45_only no) (trace_min 0.2)
    (via_size 0.8) (via_drill 0.4) (via_min_size 0.4) (via_min_drill 0.3) (uvia_size 0.3) (uvia_drill 0.1)
    (uvias_allowed no) (uvia_min_size 0.2) (uvia_min_drill 0.1) (edge_width 0.05) (segment_width 0.2) (pcb_text_width 0.3)
    (pcb_text_size 1.5 1.5) (mod_edge_width 0.12) (mod_text_size 1 1) (mod_text_width 0.15) (pad_size 1.524 1.524)
    (pad_drill 0.762) (pad_to_mask_clearance 0.051))
  (net 0 "")
  (net 1 SIG)
  (net_class Default "This is the default net class."
    (clearance 0.2) (trace_width 0.25) (via_dia 0.8) (via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1))
  (net_class save ""
    (clearance 0.2) (trace_width 0.5) (via_dia 0.8) (via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1)
    (add_net SIG))
  (segment (start 10 10) (end 20 10) (width 0.25) (layer F.Cu) (net 1))
)
"""


def test_a_kicad5_board_is_upgraded_and_its_kicad_pro_holds_its_net_classes(tmp_path):
    src, work = tmp_path / "src", tmp_path / "work"
    src.mkdir()
    (src / "tiny.kicad_pcb").write_text(KICAD5_BOARD)
    (src / "tiny.kicad_pro").write_text("{}")   # a project file in the source must not replace the one the upgrade writes
    board = fetch.Board(**{**BOARD.__dict__, "kicad5": True})
    prepared = prepare.prepare(board, src, work)
    project = json.loads((work / "ref.kicad_pro").read_text())
    assert [c["name"] for c in project["net_settings"]["classes"]] == ["Default", "save"]
    assert len(_loaded(prepared.ref).GetTracks()) == 1 and len(_loaded(prepared.test).GetTracks()) == 0
