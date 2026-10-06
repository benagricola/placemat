"""The module run with alternatives, on a real module of the fixtures (KiCad): each arrangement resolved, proven by DRC and the
checks on its own scratch board, recorded in run.json and written into the fragment as notes."""
import json
from pathlib import Path

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
    from placemat.settings import Settings
    assert len(texts) > 1 and all(len(t) <= Settings().place_arrangement_note_chars for t in texts)    # split, and rejoined above
    (doc,) = docs
    assert doc["choices"] == {"r_rt": "apart"} and doc["order"] == 1
    r_rt = next(m for m in doc["members"] if m["inst"].endswith("r_rt"))
    assert r_rt["y"] > r_rt["from"][1]                                  # further south than in the default
    assert "arrangements" in rec["timing_s"]
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


def test_with_render_each_proven_arrangement_is_rendered_in_its_folder_and_its_resolve_timed_apart(tmp_path, monkeypatch):
    import time
    from placemat import arrangement_run
    from placemat.kicad import write
    rendered = []

    def render_board(pcb_path, log, both_faces=False, timeout=None, run=None):        # kicad-cli's render is minutes: where it is asked
        rendered.append(Path(pcb_path).parent)
        (Path(pcb_path).parent / "layout.png").write_bytes(b"png")
        return ["layout.png"]
    monkeypatch.setattr(write, "render_board", render_board)
    real = arrangement_run.resolve_spec

    def slow(prepared, spec, **kw):
        time.sleep(2.0)
        return real(prepared, spec, **kw)
    monkeypatch.setattr(arrangement_run, "resolve_spec", slow)
    result, _, _ = real_modules.run(tmp_path / "r", "usb5v", edit=with_alternatives, render=True)
    rec = json.loads((result.run_dir / "run.json").read_text())
    for a in rec["arrangements"][1:]:
        assert (result.run_dir / a["dir"] / "layout.png").exists(), a["id"]
    assert rec["timing_s"]["resolve"] < 6.0 <= rec["timing_s"]["arrangements"]      # three arrangements of 2 s each
    rendered.clear()
    monkeypatch.setattr(arrangement_run, "resolve_spec", real)
    plain, _, _ = real_modules.run(tmp_path / "p", "usb5v", edit=with_alternatives)
    assert rendered == [] and not list((plain.run_dir / "arrangements").glob("*/layout.png"))


MARK = "frame_planes(FILLET, supply=None)"

# ALTERNATIVES with r_rt's move as a unit's option: c_vcc's turn stays an item's option.
GROUPED = '''
from placemat import Alt
board.alternative(Part("c_vcc"), "turned", rotation=LYING)
rt = board.unit("rt", Part("r_rt"), why="RT's resistor may move")
board.alternative(rt, "apart", Alt(Part("r_rt"), at=Beside(Part("buck"), Edge.SOUTH, gap=0.6, align=("RT_5V", pin(RT_PIN)))),
                  why="RT's resistor a little further south")
'''


def with_grouped(text: str) -> str:
    return text.replace(MARK, GROUPED + MARK, 1)


def _member_poses(pcb) -> dict:
    from placemat.kicad.read import read_board
    return {fp.inst: (round(fp.location.x, 4), round(fp.location.y, 4), round(fp.rotation % 360.0, 3), fp.face)
            for fp in read_board(pcb).footprints}


def test_a_units_option_lays_as_the_same_move_made_an_items_option_does(tmp_path):
    """The unit form and the item form of one module agree arrangement by arrangement: the same places, offered and dead."""
    items, _, _ = real_modules.run(tmp_path / "items", "usb5v", edit=with_alternatives)
    grouped, _, _ = real_modules.run(tmp_path / "grouped", "usb5v", edit=with_grouped)
    rec = json.loads((grouped.run_dir / "run.json").read_text())
    assert [a["id"] for a in rec["arrangements"]] == ["default", "rt.apart", "c_vcc.turned", "c_vcc.turned+rt.apart"]
    assert rec["arrangements"][1]["choices"] == {"rt": "apart"}
    reason = {"unit": "rt", "option": "apart", "why": "RT's resistor a little further south", "unit_why": "RT's resistor may move"}
    assert [a.get("why") for a in rec["arrangements"]] == [None, [reason], None, [reason]]
    same = {"default": "default", "rt.apart": "r_rt.apart", "c_vcc.turned": "c_vcc.turned",
            "c_vcc.turned+rt.apart": "c_vcc.turned+r_rt.apart"}
    for mine, theirs in same.items():
        assert _member_poses(grouped.run_dir / "arrangements" / mine / "layout.kicad_pcb") == \
            _member_poses(items.run_dir / "arrangements" / theirs / "layout.kicad_pcb"), mine
    assert [a["id"] for a in rec["arrangements"] if a["offered"]] == ["default", "rt.apart"]
    dead = [f["facts"] for f in rec["finding_details"] if f["cause"] == "arrangement.option_dead"]
    assert [(d["choice"], d["refused"]) for d in dead] == [("c_vcc.turned", ["c_vcc.turned", "c_vcc.turned+rt.apart"])]


def test_an_exclusion_is_not_laid_out_and_the_record_says_why(tmp_path):
    rule = '\nboard.exclude("c_vcc.turned", "rt.apart", why="the turned capacitor and the moved resistor are not wanted together")\n'
    result, _, _ = real_modules.run(tmp_path, "usb5v", edit=lambda t: with_grouped(t).replace(MARK, rule + MARK, 1))
    rec = json.loads((result.run_dir / "run.json").read_text())
    assert [a["id"] for a in rec["arrangements"] if not a.get("excluded")] == ["default", "rt.apart", "c_vcc.turned"]
    (gone,) = [a for a in rec["arrangements"] if a.get("excluded")]
    assert gone.pop("why")[0]["unit"] == "rt"
    assert gone == {"id": "c_vcc.turned+rt.apart", "choices": {"c_vcc": "turned", "rt": "apart"}, "offered": False,
                    "excluded": {"why": "the turned capacitor and the moved resistor are not wanted together",
                                 "by": ["c_vcc.turned", "rt.apart"]}}
    assert not (result.run_dir / "arrangements" / "c_vcc.turned+rt.apart").exists()
    dead = [f["facts"] for f in rec["finding_details"] if f["cause"] == "arrangement.option_dead"]
    assert [(d["choice"], d["refused"]) for d in dead] == [("c_vcc.turned", ["c_vcc.turned"])]   # the excluded one is not counted
