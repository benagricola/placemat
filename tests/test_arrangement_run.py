"""The module run with alternatives, on a real module of the fixtures (KiCad): each arrangement resolved, proven by DRC and the
checks on its own scratch board, recorded in run.json and written into the fragment as notes."""
import json

import pytest

from tests.conftest import needs_kicad
from tests import real_modules

pytestmark = needs_kicad

# c_vcc turned puts its GND pad on the PP5V_SENSE run (refused: copper.meets); r_rt a little further south keeps its nets
ALTERNATIVES = '''
board.alternative(Part("c_vcc"), "turned", rotation=LYING)
board.alternative(Part("r_rt"), "apart", at=Beside(Part("buck"), Edge.SOUTH, gap=0.6, align=("RT_5V", pin(RT_PIN))))
'''


def with_alternatives(text: str) -> str:
    marker = "frame_planes(FILLET, supply=None)"
    return text.replace(marker, ALTERNATIVES + marker, 1)


def test_a_module_with_alternatives_records_each_arrangement_and_writes_the_offered_ones_as_notes(tmp_path):
    result, drc, pcb = real_modules.run(tmp_path, "usb5v", edit=with_alternatives)
    rec = json.loads((result.run_dir / "run.json").read_text())
    ids = [a["id"] for a in rec["arrangements"]]
    assert ids == ["default", "r_rt.apart", "c_vcc.turned", "c_vcc.turned+r_rt.apart"]
    assert rec["arrangements"][0]["offered"] is True and rec["arrangements"][0]["dir"] == "arrangements/default"
    assert (result.run_dir / "arrangements" / "default" / "layout.kicad_pcb").exists()
    errors = lambda report: sorted(v["type"] for v in report.get("violations", []) if v.get("severity") == "error")
    for a in rec["arrangements"][1:]:
        d = result.run_dir / a["dir"]
        assert (d / "layout.kicad_pcb").exists() and (d / "reuse.json").exists()
        if a["offered"]:                # no real DRC bucket; the errors a fragment's DRC expects are the default's
            assert a["metrics"]["drc"] == 0 and errors(json.loads((d / "drc.json").read_text())) == errors(drc)
        else:
            assert a["refused"] and all("form" in r for r in a["refused"])
    offered = [a["id"] for a in rec["arrangements"][1:] if a["offered"]]
    assert offered == ["r_rt.apart"], "adjust ALTERNATIVES to two members whose other place passes this module's own DRC"
    import pcbnew
    from placemat.arrangement_note import ARRANGEMENT_PREFIX, read_notes
    board = pcbnew.LoadBoard(str(pcb))
    texts = [d.GetText() for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(ARRANGEMENT_PREFIX)]
    docs, problems = read_notes(texts)
    assert problems == [] and sorted(d["id"] for d in docs) == sorted(offered)
    print("note characters:", sorted(len(t) for t in texts))             # the size Phase 1 measures
    assert max(len(t) for t in texts) < 20000
    run_copy = pcbnew.LoadBoard(str(result.run_dir / "layout.kicad_pcb"))      # the run's copy is the fragment, notes and all
    assert sorted(d.GetText() for d in run_copy.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)
                  and d.GetText().startswith(ARRANGEMENT_PREFIX)) == sorted(texts)


def test_the_written_fragment_is_the_defaults_and_equal_to_a_run_with_no_alternatives(tmp_path):
    plain_result, _, plain_pcb = real_modules.run(tmp_path / "a", "usb5v")
    alt_result, _, alt_pcb = real_modules.run(tmp_path / "b", "usb5v", edit=with_alternatives)
    import pcbnew

    def live(path):
        board = pcbnew.LoadBoard(str(path))
        return sorted((f.GetReference(), f.GetPosition().x, f.GetPosition().y, f.GetOrientationDegrees()) for f in board.GetFootprints()), \
            sorted((t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y) for t in board.GetTracks())
    assert live(plain_pcb) == live(alt_pcb)


def test_a_module_with_no_alternatives_writes_no_arrangement_record_or_directory(tmp_path):
    result, _, _ = real_modules.run(tmp_path, "usb5v")
    rec = json.loads((result.run_dir / "run.json").read_text())
    assert "arrangements" not in rec and not (result.run_dir / "arrangements").exists()


def test_a_refused_alternative_is_recorded_with_its_refusals_and_raises_arrangement_refused(tmp_path):
    bad = '\nboard.alternative(Part("c_vcc"), "wild", at=Beside(Part("buck"), Edge.EAST))\n'      # where the coil stands
    result, _, pcb = real_modules.run(tmp_path, "usb5v", edit=lambda t: t.replace("frame_planes(FILLET, supply=None)", bad + "frame_planes(FILLET, supply=None)", 1))
    rec = json.loads((result.run_dir / "run.json").read_text())
    wild = next(a for a in rec["arrangements"] if a["id"] == "c_vcc.wild")
    assert wild["offered"] is False and {"form": "unplaced", "item": "c_vcc"} in wild["refused"]
    assert any(f["cause"] == "arrangement.refused" and f["facts"]["id"] == "c_vcc.wild" for f in rec["finding_details"])
    assert rec["arrangements"][0]["offered"] is True                    # the default is written either way


def test_a_stopped_run_resumes_each_arrangement_from_its_own_record(tmp_path, monkeypatch):
    from placemat import arrangement_run, stop
    real = arrangement_run.resolve_spec

    def stop_on_the_last(prepared, spec, **kw):
        if spec.id == prepared.specs[-1].id:
            raise stop.Stopped(15)                      # the run is stopped while it lays out the last arrangement
        return real(prepared, spec, **kw)
    monkeypatch.setattr(arrangement_run, "resolve_spec", stop_on_the_last)
    with pytest.raises(stop.Stopped):
        real_modules.run(tmp_path, "usb5v", edit=with_alternatives, reuse=True)
    monkeypatch.setattr(arrangement_run, "resolve_spec", real)
    runs = tmp_path / "board" / "modules" / "usb5v" / ".placemat" / "runs"
    (stopped,) = [p for p in runs.iterdir() if (p / "arrangements").is_dir()]
    assert (stopped / "arrangements" / "r_rt.apart" / "reuse.json").exists()
    again, _, _ = real_modules.run(tmp_path, "usb5v", edit=with_alternatives, reuse=True, fresh_folder=False)
    done = json.loads((again.run_dir / "arrangements" / "r_rt.apart" / "reuse.json").read_text())
    assert done["reused"] == len(done["steps"]) > 0          # the arrangement the stopped run finished is replayed, not laid again


def test_write_notes_replaces_the_fragments_texts_and_leaves_a_board_with_none_alone(tmp_path):
    import pcbnew
    from placemat.kicad.arrange import write_notes
    from placemat.arrangement_note import ARRANGEMENT_PREFIX
    pcb = tmp_path / "layout.kicad_pcb"
    board = pcbnew.CreateEmptyBoard()
    board.Save(str(pcb))
    before = pcb.read_bytes()
    assert write_notes(pcb, []) == [] and pcb.read_bytes() == before
    write_notes(pcb, [ARRANGEMENT_PREFIX + "a", ARRANGEMENT_PREFIX + "b"])
    write_notes(pcb, [ARRANGEMENT_PREFIX + "c"])
    texts = [d.GetText() for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert texts == [ARRANGEMENT_PREFIX + "c"]


def test_notes_stand_below_the_fragment_and_its_other_notes(tmp_path):
    import pcbnew
    from placemat.kicad.arrange import write_notes
    from placemat.kicad.write import write_faces, nm
    from placemat.arrangement_note import ARRANGEMENT_PREFIX
    from placemat.values import Edge
    pcb = tmp_path / "layout.kicad_pcb"
    board = pcbnew.CreateEmptyBoard()
    line = pcbnew.PCB_SHAPE(board)
    line.SetShape(pcbnew.SHAPE_T_SEGMENT)
    line.SetStart(pcbnew.VECTOR2I(nm(0), nm(0)))
    line.SetEnd(pcbnew.VECTOR2I(nm(10), nm(5)))
    line.SetLayer(pcbnew.Edge_Cuts)
    board.Add(line)
    board.Save(str(pcb))
    write_faces(pcb, {"outward": Edge.NORTH})
    write_notes(pcb, [ARRANGEMENT_PREFIX + "a", ARRANGEMENT_PREFIX + "b"])
    write_faces(pcb, {"outward": Edge.SOUTH})                   # written again, it stands where it stood: the notes are not in its box
    at = {d.GetText(): (pcbnew.ToMM(d.GetPosition().x), pcbnew.ToMM(d.GetPosition().y))
          for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)}
    faces = next(v for k, v in at.items() if k.startswith("placemat faces "))
    assert faces[1] == pytest.approx(5.0 + 1.0, abs=0.2)
    assert at[ARRANGEMENT_PREFIX + "a"][1] > faces[1] and at[ARRANGEMENT_PREFIX + "b"][1] > at[ARRANGEMENT_PREFIX + "a"][1]
