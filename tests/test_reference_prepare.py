import json

import pytest

from fixtures.reference import fetch, prepare
from tests.conftest import needs_router

pcbnew = pytest.importorskip("pcbnew")

BOARD = fetch.Board(name="tiny", repo="github:o/r", commit="0" * 40, files={}, board="tiny.kicad_pcb", licence="MIT",
                    tests=("a",), phases=(), fixed=(), human_track_mm=None, kicad5=False)


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


@needs_router
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


@needs_router
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


@needs_router
def test_a_board_whose_file_leaves_ids_out_is_prepared_with_the_same_ids_every_time(tmp_path):
    """The source's pads and track carry no uuid (an older format leaves them out). The stripped board gets ids from
    a generator seeded by the file, so two preparations write the same board, and their baseline DRC names the same
    items. The board's own id is not in its file, so kicad-cli makes a new one each time: an item "PCB" is left out."""
    import re
    src = tmp_path / "src"
    src.mkdir()
    _two_layer_board(src / "tiny.kicad_pcb")
    board = src / "tiny.kicad_pcb"
    board.write_text(re.sub(r'^\s*\(uuid "[^"]*"\)\n', "", board.read_text(), flags=re.M)
                     .replace("(at 20 10)", "(at 10.6 10)"))   # R2's pad over R1's: a violation naming both pads
    runs = [prepare.prepare(BOARD, src, tmp_path / ("work%d" % i)) for i in (1, 2)]
    texts = [r.test.read_text() for r in runs]
    assert "(uuid" in texts[0] and texts[0] == texts[1]
    ids = [[[i.get("uuid") for i in v["items"] if i.get("description") != "PCB"] for v in json.loads((r.test.parent / prepare.BASELINE).read_text())["violations"]]
           for r in runs]
    assert ids[0] and ids[0] == ids[1]


def test_regenerated_reference_uses_pinned_import_and_reports_failures(tmp_path, monkeypatch):
    import pathlib
    import subprocess
    calls = []
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'tiny.kicad_pro').write_text('{}')

    def run(command, **kwargs):
        calls.append((command, kwargs.get('cwd')))
        out = tmp_path / 'work' / prepare.REGENERATED
        if command[1] == 'import':
            (out / 'layout').mkdir(parents=True)
        else:
            (out / 'layout' / 'tiny.kicad_pcb').write_text('generated')
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(prepare.subprocess, 'run', run)
    result = prepare.regenerate(BOARD, src, tmp_path / 'work')
    assert result.read_text() == 'generated'
    assert calls == [(['pcb', 'import', str(src / 'tiny.kicad_pro'), str(tmp_path / 'work' / 'regenerated')], None),
                     (['pcb', 'layout', '--no-open', '-S', 'errors', 'tiny.zen'], tmp_path / 'work' / 'regenerated')]
    diagnostics = 'full error context\n' * 100 + 'bad project'
    monkeypatch.setattr(prepare.subprocess, 'run', lambda command, **kw: subprocess.CompletedProcess(command, 1, 'full stdout', diagnostics))
    with pytest.raises(RuntimeError, match='(?s)pcb import failed .*bad project'):
        prepare.regenerate(BOARD, src, tmp_path / 'work')
    assert (tmp_path / 'work' / 'regenerated-import.stderr.log').read_text() == diagnostics
    assert (tmp_path / 'work' / 'regenerated-import.stdout.log').read_text() == 'full stdout'
    assert json.loads((tmp_path / 'work' / 'regenerated-import.command.json').read_text()) == {
        'argv': calls[0][0], 'cwd': None}
    monkeypatch.setattr(prepare.subprocess, 'run', lambda command, **kw: subprocess.CompletedProcess(command, 0, '', ''))
    with pytest.raises(RuntimeError, match='pcb layout wrote no'):
        prepare.regenerate(BOARD, src, tmp_path / 'work')


def test_regeneration_timeout_keeps_partial_command_output(tmp_path, monkeypatch):
    import subprocess
    command = ['pcb', 'layout', 'tiny.zen']
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(command, 900, output=b'partial stdout', stderr=b'partial stderr')
    monkeypatch.setattr(prepare.subprocess, 'run', timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        prepare._generation_step(command, tmp_path, tmp_path, 'regenerated-layout', 'pcb layout')
    assert (tmp_path / 'regenerated-layout.stdout.log').read_text() == 'partial stdout'
    assert (tmp_path / 'regenerated-layout.stderr.log').read_text() == 'partial stderr'


def test_prepare_regenerated_reference_preserves_generated_rules(tmp_path, monkeypatch):
    made = tmp_path / 'generated' / 'tiny.kicad_pcb'
    made.parent.mkdir()
    made.write_text('generated board')
    made.with_suffix('.kicad_pro').write_text('{"generated_rules": true}')
    monkeypatch.setattr(prepare, 'regenerate', lambda *args: made)
    monkeypatch.setattr(prepare, 'strip', lambda src, dst: dst.write_text(src.read_text()))
    monkeypatch.setattr(prepare, '_upgrade', lambda pcb: None)
    monkeypatch.setattr(prepare, 'measure', lambda pcb: (2, prepare.HumanCopper(1, 2.0)))
    monkeypatch.setattr(prepare, 'run_drc', lambda pcb, out, refill_zones: out.write_text('{"violations": []}'))
    got = prepare.prepare(BOARD, tmp_path / 'missing-source', tmp_path / 'work', regenerated=True)
    assert got.ref.read_text() == 'generated board'
    assert json.loads(got.test.with_suffix('.kicad_pro').read_text()) == {"generated_rules": True}



def test_legacy_regeneration_imports_an_existing_upgraded_project_and_copies_sheets(tmp_path, monkeypatch):
    import dataclasses
    import pathlib
    import subprocess
    src = tmp_path / "cache"
    source = src / "nested" / "tiny.kicad_pcb"
    source.parent.mkdir(parents=True)
    source.write_text("legacy board")
    source.with_suffix(".pro").write_text("legacy rules")
    source.with_suffix(".sch").write_text("legacy root schematic")
    child = source.parent / "sheets" / "child.sch"
    child.parent.mkdir()
    child.write_text("child schematic")
    board = dataclasses.replace(BOARD, board="nested/tiny.kicad_pcb", kicad5=True)
    calls = []

    def upgrade(copied):
        assert copied != source and copied.read_text() == "legacy board"
        assert copied.with_suffix(".pro").read_text() == "legacy rules"
        assert (copied.parent / "sheets" / "child.sch").is_file()
        copied.with_suffix(".kicad_pro").write_text('{"upgraded": true}')

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "kicad-cli":
            assert pathlib.Path(command[-1]).is_file()
        elif command[1] == "import":
            project = pathlib.Path(command[2])
            assert project.is_file() and json.loads(project.read_text())["upgraded"]
            assert project.parent != source.parent
            (pathlib.Path(command[3]) / "layout").mkdir(parents=True)
        else:
            (pathlib.Path(kwargs["cwd"]) / "layout" / "tiny.kicad_pcb").write_text("generated")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(prepare, "_upgrade", upgrade)
    monkeypatch.setattr(prepare.subprocess, "run", run)
    assert prepare.regenerate(board, src, tmp_path / "work").is_file()
    assert len([c for c in calls if c[0] == "kicad-cli"]) == 2
    assert source.read_text() == "legacy board" and not source.with_suffix(".kicad_pro").exists()


def test_legacy_regeneration_passes_the_real_kicad_upgrade_project_to_import(tmp_path, monkeypatch):
    import dataclasses
    import pathlib
    import subprocess
    src = tmp_path / 'cache'
    src.mkdir()
    original = src / 'tiny.kicad_pcb'
    original.write_text(KICAD5_BOARD)
    original.with_suffix('.pro').write_text('[pcbnew]\n')
    imported = []

    def run(command, **kwargs):
        if command[1] == 'import':
            project = pathlib.Path(command[2])
            assert project.is_file()
            classes = json.loads(project.read_text())['net_settings']['classes']
            assert {c['name'] for c in classes} == {'Default', 'save'}
            imported.append(project)
            (pathlib.Path(command[3]) / 'layout').mkdir(parents=True)
        else:
            (pathlib.Path(kwargs['cwd']) / 'layout' / 'tiny.kicad_pcb').write_text('generated')
        return subprocess.CompletedProcess(command, 0, '', '')

    monkeypatch.setattr(prepare.subprocess, 'run', run)
    prepare.regenerate(dataclasses.replace(BOARD, kicad5=True), src, tmp_path / 'work')
    assert len(imported) == 1 and not original.with_suffix('.kicad_pro').exists()
