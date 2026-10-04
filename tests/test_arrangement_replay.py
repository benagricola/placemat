import json

import pytest

from placemat import reuse
from placemat.copper import Via
from placemat.layout import Board
from placemat.values import Beside, Cell, CopperLayer, Drops, Edge, Location, Near, Net, Part
from tests.arrangement_support import EAST_TRACK, east_doc, stamped_geometry, with_arrangement
from tests.conftest import needs_kicad
from tests.test_arrangement_search import NEAR
from tests.test_reuse_partial import Died, Dying
from tests.test_reuse_replay import _same


def board(g):
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.reuse_extra = "t"
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    return b


def pads(plan):
    return [plan.occupancy.pad_location(r, n) for r in ("C1", "U1") for n in ("1", "2")]


def test_the_second_run_replays_an_arranged_step():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    first = board(g).resolve()
    record = json.loads(json.dumps(first.reuse))
    assert first.placement("mod").arrangement == "c_in.east"
    second = board(g).resolve(reuse=record)
    assert second.reuse["reused"] == len(second.reuse["steps"]) and second.placement("mod") == first.placement("mod")
    assert pads(second) == pads(first)


# In the fragment's frame c_in.east stands c_in's GND pad (pad 2) at (10.1, 3.0): a field of two vias there, which drops=HALF thins to one
FIELD = [Via("GND", Location(9.85, 3.0), 0.15, 0.3), Via("GND", Location(10.35, 3.0), 0.15, 0.3)]


def riding_board(g, **cell):
    """`mod` rides r8: it is committed inside r8's step, so its commit is in that step's record."""
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.reuse_extra = "t"
    b.plane(Net("mod.GND"), layers=(CopperLayer.B,))
    b.place(Part("r8"), at=Near(Location(60.0, 30.0), radius=4.0, step=0.5))
    b.place(Cell("mod"), at=Beside(Part("r8"), Edge.WEST), **cell)
    return b


def mod_commit(record):
    return next(c for s in record["steps"] for c in s["commits"] if c[0][1] == "mod")


def test_a_cell_committed_inside_a_step_is_recorded_and_replayed_in_its_arrangement():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)), east_doc(ops=FIELD))
    first = riding_board(g, arrangements="c_in.east", drops=Drops.HALF).resolve()
    record = json.loads(json.dumps(first.reuse))
    key, placement = mod_commit(record)
    assert key == ["cell", "mod", "c_in.east"] and placement[-1] == "c_in.east"
    assert first.placement("mod").arrangement == "c_in.east" and len(first.thinned["mod"]) == 1
    second = riding_board(g, arrangements="c_in.east", drops=Drops.HALF).resolve(reuse=record)
    assert second.reuse["reused"] == len(second.reuse["steps"])
    assert pads(second) == pads(first) and dict(second.thinned) == dict(first.thinned)


def test_a_default_commit_is_recorded_as_before_and_an_old_record_reads_as_the_default():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    first = riding_board(g).resolve()
    assert first.placement("mod").arrangement == ""
    key, placement = mod_commit(first.reuse)
    assert list(key) == ["cell", "mod"] and len(placement) == 4
    assert reuse.placement_from_json([1.0, 2.0, 0.0, "front"]).arrangement == ""


def test_the_context_digest_follows_the_cells_arrangements_only_when_it_has_any(monkeypatch):
    plain = stamped_geometry()
    assert reuse.arrangements_digest(plain) == ""
    one, other = with_arrangement(), with_arrangement(doc=east_doc("c_in.east", 1, []))
    assert reuse.arrangements_digest(one) != "" and reuse.arrangements_digest(one) != reuse.arrangements_digest(other)
    arranged = board(with_arrangement(stamped_geometry(partner=(60.0, 30.0))))
    bare = board(stamped_geometry(partner=(60.0, 30.0)))
    assert reuse.context_key(arranged, "t") != reuse.context_key(bare, "t")
    # with the digest empty the arranged board keys as the plain one: an empty digest adds nothing to the context
    monkeypatch.setattr(reuse, "arrangements_digest", lambda g: "")
    assert reuse.context_key(arranged, "t") == reuse.context_key(bare, "t")


def test_a_record_of_another_version_replays_nothing():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    record = json.loads(json.dumps(board(g).resolve().reuse))
    record["version"] = 4
    assert board(g).resolve(reuse=record).reuse["reused"] == 0


def test_a_partial_log_of_another_version_is_not_read(tmp_path):
    path = tmp_path / "reuse.partial.jsonl"
    log = reuse.PartialLog(path)
    board(with_arrangement(stamped_geometry(partner=(60.0, 30.0)))).resolve(partial=log)
    log.close()
    lines = path.read_text().splitlines()
    header = json.loads(lines[0])
    assert header["version"] == 5 and reuse.read_partial(path) is not None
    path.write_text("\n".join([json.dumps(dict(header, version=4))] + lines[1:]) + "\n")
    assert reuse.read_partial(path) is None


def given_way_geometry():
    """c_in.east carries a VIN via that gives way to a GND track on the board (test_arrangement_search's give-way case)."""
    from tests.fixtures import track
    doc = east_doc(ops=[Via("VIN", Location(6.0, 7.0), 0.3, 0.6)])
    return with_arrangement(stamped_geometry(partner=(60.0, 30.0), copper=(track("GND", 36.0, 33.4, 40.5, 33.4, w=0.3),)), doc)


def given_way_board(g):
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.reuse_extra = "t"
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), radius=0.0, rotations=(0,)))
    b.place(Part("r9"), at=Near(Location(20.0, 40.0), **NEAR))
    return b


def _arranged_same(a, b):
    """Two plans whose arranged cell stands the same, with the same arranged copper and the same vias given way."""
    _same(a, b)
    assert b.placement("mod").arrangement == a.placement("mod").arrangement == "c_in.east"
    held = lambda p: sorted((s.kind, s.net, round(s.box.left, 6), round(s.box.top, 6), round(s.box.right, 6), round(s.box.bottom, 6))
                            for s in p.occupancy.copper if s.owner == "mod")
    assert held(a) and held(a) == held(b)
    assert [(w.home, w.kind) for w in a.given_way] == [(w.home, w.kind) for w in b.given_way] == [("mod", "move")]
    assert dict(a.thinned) == dict(b.thinned)


def test_a_replayed_arranged_cell_commits_its_arranged_copper_and_its_carried_via_as_given_way():
    g = given_way_geometry()
    first = given_way_board(g).resolve()
    again = given_way_board(g).resolve(reuse=json.loads(json.dumps(first.reuse)))
    assert again.reuse["reused"] == len(again.reuse["steps"])
    _arranged_same(first, again)


def test_a_stopped_run_resumes_and_replays_the_arranged_cell(tmp_path):
    g = given_way_geometry()
    clean = given_way_board(g).resolve()
    keys = [s["step"]["item"] for s in clean.reuse["steps"]]
    path = tmp_path / "reuse.partial.jsonl"
    log = Dying(path, keys.index("mod") + 1)            # the run stops once the cell's step is logged
    with pytest.raises(Died):
        given_way_board(g).resolve(partial=log)
    log.close()
    partial = reuse.read_partial(path)
    assert [s["step"]["item"] for s in partial["steps"]][-1] == "mod"
    again = given_way_board(g).resolve(reuse=partial)
    assert again.reuse["reused"] == len(partial["steps"]) < len(again.reuse["steps"])
    _arranged_same(clean, again)


def _written(pcb):
    """What a written board holds, as comparable rows: footprints, tracks, vias, zones and drawings."""
    import pcbnew
    b = pcbnew.LoadBoard(str(pcb))
    pt = lambda v: (v.x, v.y)
    return (sorted((f.GetReference(), pt(f.GetPosition()), f.GetOrientationDegrees(), f.GetLayer()) for f in b.GetFootprints()),
            sorted((type(t).__name__, t.GetNetname(), pt(t.GetStart()), pt(t.GetEnd()), t.GetWidth(), t.GetLayer()) for t in b.GetTracks()),
            sorted((z.GetNetname(), z.GetIsRuleArea(), pt(z.GetPosition()), z.GetNumCorners()) for z in b.Zones()),
            sorted((type(d).__name__, d.GetLayer(), pt(d.GetPosition()), d.GetText() if hasattr(d, "GetText") else "") for d in b.GetDrawings()))


@needs_kicad
def test_a_replayed_arranged_cell_is_written_as_the_first_run_wrote_it(tmp_path):
    """The arranged copper, its field as drops= thinned it and the cell's rule areas come back on the board as the first run wrote them."""
    import shutil
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    from tests.arrangement_support import kicad_cell_board
    from placemat import arrangement_note as N
    pcb = kicad_cell_board(tmp_path / "layout.kicad_pcb", notes={"mod": N.encode(east_doc(ops=FIELD + [EAST_TRACK]), 4000)})

    def resolve(**kw):
        b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
        b.rect(width=80, height=60)
        b.reuse_extra = "t"
        b.plane(Net("mod.GND"), layers=(CopperLayer.B,))
        b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), arrangements="c_in.east", drops=Drops.HALF)
        return b.resolve(**kw)
    first = resolve()
    second = resolve(reuse=json.loads(json.dumps(first.reuse)))
    assert second.reuse["reused"] == len(second.reuse["steps"]) and second.placement("mod").arrangement == "c_in.east"
    a, b = tmp_path / "a.kicad_pcb", tmp_path / "b.kicad_pcb"
    shutil.copy(pcb, a)
    shutil.copy(pcb, b)
    apply_plan(a, first)
    apply_plan(b, second)
    written = _written(a)
    assert written == _written(b)
    assert len([t for t in written[1] if t[0] == "PCB_VIA"]) == 1              # the field of two, thinned to one
