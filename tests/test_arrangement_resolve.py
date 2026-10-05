import dataclasses

import pytest

from placemat import Alt, arrangement_run as run
from placemat.settings import Settings
from placemat.values import Beside, CopperLayer, Edge, Location, Net, PadRef, Part
from tests.arrangement_support import module

F = CopperLayer.F


def board():
    b = module()
    b.keep_going = True             # c_in east of u1 meets r_pull there: a collision is a finding, not the end of the resolve
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    return b


def test_the_default_resolves_as_the_script_says_and_an_alternative_lays_its_option_over():
    b = board()
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]
    default = run.resolve_spec(prepared, prepared.specs[0])
    east = run.resolve_spec(prepared, prepared.specs[2])
    collided = lambda plan: [f for f in plan.findings if f.cause == "fixed.part"]
    assert not collided(default) and collided(east)                    # east lands on r_pull: a finding under keep_going
    u1 = default.placement("u1").location.x
    assert default.placement("c_in").location.x < u1 < east.placement("c_in").location.x
    again = run.resolve_spec(prepared, prepared.specs[0])
    assert again.placements == default.placements                      # the board was put back between resolves


def test_the_option_turns_one_member_and_leaves_the_rest():
    b = board()
    prepared = run.begin(b)
    default = run.resolve_spec(prepared, prepared.specs[0])
    turned = run.resolve_spec(prepared, prepared.specs[1])
    assert turned.placement("r_pull").rotation == 180.0 and default.placement("r_pull").rotation == 0.0
    assert turned.placement("c_in") == default.placement("c_in")


def with_tracks():
    """OUT straight from u1 to r_pull in the default; turned, r_pull's OUT pad is on its far side, so a detour north of it."""
    b = board()
    b.track(Net("OUT"), [PadRef(Part("u1"), 2), PadRef(Part("r_pull"), 1)], layer=F, only=("default",))
    b.track(Net("OUT"), [PadRef(Part("u1"), 2), Location(22.4, 13), Location(25.6, 13), PadRef(Part("r_pull"), 1)], layer=F,
            only=("r_pull.turned",))
    b.via(Net("VIN"), PadRef(Part("u1"), 1))                            # no only=: in every arrangement
    return b


def detoured(plan) -> bool:
    return any(abs(p.y - 13) < 1e-6 for op in tracks(plan) for p in (op.start, op.end))


def tracks(plan) -> list:
    return [op for op in plan.copper if hasattr(op, "start")]


def vias(plan) -> list:
    return [op for op in plan.copper if not hasattr(op, "start")]


def test_copper_exists_only_in_the_arrangements_it_names():
    prepared = run.begin(with_tracks())
    default = run.resolve_spec(prepared, prepared.specs[0])
    turned = run.resolve_spec(prepared, prepared.specs[1])
    assert not detoured(default) and len(tracks(default)) == 1
    assert detoured(turned) and len(tracks(turned)) == 5                # the detour's segments, and no straight track
    assert all(op.net == "OUT" for op in tracks(turned))
    east = run.resolve_spec(prepared, prepared.specs[2])
    assert tracks(east) == []                                           # neither track exists in c_in.east
    for spec in prepared.specs:
        assert [op.net for op in vias(run.resolve_spec(prepared, spec))] == ["VIN"], spec.id


def test_a_plain_resolve_lays_the_default_copper():
    plan = with_tracks().resolve()
    assert not detoured(plan) and len(tracks(plan)) == 1 and [op.net for op in vias(plan)] == ["VIN"]


def test_resolving_an_arrangement_leaves_the_board_as_it_was():
    plain = with_tracks().resolve()
    b = with_tracks()
    prepared = run.begin(b)
    run.resolve_spec(prepared, prepared.specs[3])                       # c_in.east+r_pull.turned
    assert b._laid == "default"
    after = b.resolve()
    assert after.placements == plain.placements and after.copper == plain.copper and len(after.copper) == 2


def test_a_resolve_that_raises_leaves_the_board_as_it_was():
    b = with_tracks()
    b.keep_going = False
    prepared = run.begin(b)
    with pytest.raises(Exception, match="collide"):
        run.resolve_spec(prepared, prepared.specs[2])                   # c_in.east lands on r_pull
    assert b._laid == "default" and next(i for i in b._intents if i.key == "c_in").beside.side == Edge.WEST
    assert len(b._copper) == 3


def test_two_arrangements_that_resolve_alike_have_one_signature():
    b = board()
    b.alternative(Part("c_in"), "same", at=Beside(Part("u1"), Edge.WEST))      # the default's own relation
    prepared = run.begin(b)
    plans = {s.id: run.resolve_spec(prepared, s) for s in prepared.specs}
    assert run.signature(plans["c_in.same"]) == run.signature(plans["default"])
    assert run.signature(plans["c_in.east"]) != run.signature(plans["default"])


def test_the_limit_finding_is_on_the_default_plan_and_the_resolve_is_the_default_alone():
    b = module(dataclasses.replace(Settings(), place_arrangements_max=2))
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default"]
    plan = run.resolve_spec(prepared, prepared.specs[0])
    (f,) = [f for f in plan.findings if f.cause == "arrangement.limit"]
    assert f.facts["arrangements"] == 4 and f.facts["max_arrangements"] == 2 and f.severity == "warning"


def untimed(record):
    if isinstance(record, dict):
        return {k: untimed(v) for k, v in record.items() if k != "seconds"}
    if isinstance(record, list):
        return [untimed(v) for v in record]
    return record


def test_a_board_that_declares_no_alternative_resolves_as_before():
    plain = module().resolve()
    prepared = run.begin(module())
    got = run.resolve_spec(prepared, prepared.specs[0])
    assert got.placements == plain.placements and [str(f) for f in got.findings] == [str(f) for f in plain.findings]
    assert untimed(got.reuse) == untimed(plain.reuse) and list(got.steps) == list(plain.steps)
    assert not [f for f in plain.findings if f.cause.startswith("arrangement.")]


def test_an_option_takes_the_declared_intents_slot_and_keeps_its_pushes():
    b = board()
    b.push(Part("c_in"), from_=Part("r_pull"), falloff=2.0, reference=(1.0, 1.0), limit=0.5)
    declared = {i.key: i for i in b._intents}
    c_in = declared["c_in"]
    slot = (c_in.index, c_in.line, c_in.file, c_in.pushes, c_in.needs)
    prepared = run.begin(b)
    b._restore(prepared.saved)
    b.lay_arrangement(prepared.specs[2])                                # c_in.east
    laid = next(i for i in b._intents if i.key == "c_in")
    assert laid is c_in and laid.beside.side == Edge.EAST
    assert (laid.index, laid.line, laid.file, laid.pushes) == slot[:4] and slot[4] <= laid.needs
    assert [i.key for i in b._intents] == [i.key for i in sorted(b._intents, key=lambda i: i.index)]
    b._restore(prepared.saved)
    assert next(i for i in b._intents if i.key == "c_in").beside.side == Edge.WEST


def test_an_unknown_only_id_is_refused_before_the_resolve():
    b = board()
    b.track(Net("OUT"), [PadRef(Part("r_pull"), 1), PadRef(Part("u1"), 2)], layer=F, only=("r_pull.sideways",))
    with pytest.raises(ValueError, match="not an arrangement of this module"):
        b.resolve()
    c = board()
    c.track(Net("OUT"), [PadRef(Part("r_pull"), 1), PadRef(Part("u1"), 2)], layer=F, only=("r_pull.sideways",))
    with pytest.raises(ValueError, match="not an arrangement of this module"):
        run.begin(c)


def test_resolve_others_records_a_failing_arrangement_as_refused_and_goes_on(tmp_path):
    from placemat import reuse
    b = board()
    b.keep_going = False                # c_in east of u1 meets r_pull: the resolve of c_in.east raises
    prepared = run.begin(b)
    default = b.resolve()
    began = []
    got = run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, began.append)
    assert began == ["r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]
    assert [r.spec.id for r in got] == began
    turned, east, both = got
    assert turned.plan is not None and turned.refused == []
    assert reuse.read(tmp_path / "arrangements" / "r_pull.turned" / "reuse.json")["steps"]
    for r in (east, both):
        assert r.plan is None and r.duplicate_of == "" and r.refused
        assert all(x["form"] == "finding" and x["cause"] == "fixed.part" for x in r.refused)
        d = tmp_path / "arrangements" / r.spec.id
        assert not (d / "reuse.partial.jsonl").exists()                 # a finished run leaves no log as if mid-run
        kept = reuse.read(d / "reuse.json")                             # the steps it completed, for the next run to replay
        assert kept["context"] and kept["steps"] and kept["reused"] == 0
    assert b._laid == "default" and b.resolve().placements == default.placements       # the board is the default's again


def test_resolve_others_records_an_unplaced_required_item_as_refused(tmp_path, monkeypatch):
    from placemat.layout import CriticalUnplaced
    b = board()
    prepared = run.begin(b)
    default = b.resolve()
    real = run.resolve_spec

    def unplaced(prepared, spec, **kw):
        if spec.id == "c_in.east":
            raise CriticalUnplaced("c_in", "no place", None)
        return real(prepared, spec, **kw)
    monkeypatch.setattr(run, "resolve_spec", unplaced)
    got = {r.spec.id: r for r in run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)}
    assert got["c_in.east"].refused == [{"form": "unplaced", "item": "c_in"}]
    assert got["r_pull.turned"].plan is not None and got["c_in.east+r_pull.turned"].plan is not None


def test_resolve_others_drops_an_arrangement_that_lays_out_as_an_earlier_one(tmp_path):
    b = board()
    b.alternative(Part("c_in"), "same", at=Beside(Part("u1"), Edge.WEST))      # the default's own relation
    prepared = run.begin(b)
    default = b.resolve()
    got = {r.spec.id: r for r in run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)}
    assert got["c_in.same"].plan is None and got["c_in.same"].duplicate_of == "default"
    assert got["c_in.same+r_pull.turned"].duplicate_of == "r_pull.turned"
    assert (tmp_path / "arrangements" / "c_in.same" / "reuse.json").exists()


def test_read_died_takes_a_finished_record_or_the_steps_of_a_partial_log(tmp_path):
    from placemat import reuse
    b = board()
    prepared = run.begin(b)
    default = b.resolve()
    run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)
    died = run.read_died(tmp_path)
    assert sorted(died) == ["c_in.east", "c_in.east+r_pull.turned", "r_pull.turned"]
    assert died["r_pull.turned"]["steps"] == reuse.read(tmp_path / "arrangements" / "r_pull.turned" / "reuse.json")["steps"]
    assert run.read_previous(tmp_path).keys() == died.keys()
    assert run.read_died(tmp_path / "nothing") == {} and run.read_previous(tmp_path / "nothing") == {}


def test_a_note_the_setting_leaves_no_room_for_refuses_its_arrangement_with_a_finding(tmp_path, monkeypatch):
    from types import SimpleNamespace
    b = board()
    prepared = run.begin(b)
    default = b.resolve()
    got = run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)
    monkeypatch.setattr(run, "prove", lambda *a, **kw: run.Proof(True, [], {"drc": None}))
    src = SimpleNamespace(board_dir=tmp_path, name="m", pcb=tmp_path / "m.kicad_pcb")
    cfg = dataclasses.replace(Settings(), place_arrangement_note_chars=1)
    out = run.finish(prepared, default, got[:1], src=src, cfg=cfg, fab=None, run_dir=tmp_path, default_report=None,
                     board=b, drc=False)
    entry = out.record[1]
    assert entry["id"] == "r_pull.turned" and entry["offered"] is False
    assert entry["refused"] == [{"form": "note_chars", "chars": 1}] and out.texts == []
    f, dead = out.findings
    assert f.cause == "arrangement.refused" and f.facts["id"] == "r_pull.turned" and f.severity == "warning"
    assert "place.arrangement_note_chars" in str(f)
    assert dead.cause == "arrangement.option_dead" and dead.facts["refused"] == ["r_pull.turned"]


def test_the_console_rows_of_the_record():
    from placemat import finding_text
    record = [{"id": "default", "offered": True},
              {"id": "a.b", "offered": True},
              {"id": "a.c", "offered": False, "duplicate_of": "a.b"},
              {"id": "a.d", "offered": False, "refused": [{"form": "unplaced", "item": "c1"}]}]
    rows = run.lines(record)
    assert [r["state"] for r in rows] == ["written", "offered", "duplicate", "refused"]
    assert [finding_text.arrangement_row_text(r) for r in rows] == [
        "default: offered, written", "a.b: offered", "a.c: the same as a.b, dropped", "a.d: not offered: c1 is not placed"]


def test_a_row_anchored_on_a_moved_member_follows_it_whatever_was_resolved_before():
    def with_row():
        b = module()
        b.row([Part("r_free")], Edge.EAST, of=Part("r_pull"))          # its start waits on r_pull's place
        b.alternative(Part("r_pull"), "north", at=Beside(Part("u1"), Edge.NORTH))
        return b
    alone = run.begin(with_row())
    first = run.resolve_spec(alone, alone.specs[1])
    b = with_row()
    prepared = run.begin(b)
    default = b.resolve()
    after = run.resolve_spec(prepared, prepared.specs[1])
    assert after.placement("r_free") == first.placement("r_free") != default.placement("r_free")
    assert after.reuse["context"] == first.reuse["context"]
    assert b.resolve().placement("r_free") == default.placement("r_free")      # the default's rows are put back


def test_resolve_others_records_any_other_error_of_one_arrangement_and_goes_on(tmp_path, monkeypatch):
    b = board()
    prepared = run.begin(b)
    default = b.resolve()
    real = run.resolve_spec

    def raising(prepared, spec, **kw):
        if spec.id == "c_in.east":
            raise ValueError("c_in is placed relative to u9, which is not placed by then")
        return real(prepared, spec, **kw)
    monkeypatch.setattr(run, "resolve_spec", raising)
    got = {r.spec.id: r for r in run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)}
    assert got["c_in.east"].plan is None and got["c_in.east"].refused == [
        {"form": "error", "type": "ValueError", "message": "c_in is placed relative to u9, which is not placed by then"}]
    assert got["r_pull.turned"].plan is not None and got["c_in.east+r_pull.turned"].plan is not None
    assert not (tmp_path / "arrangements" / "c_in.east" / "reuse.partial.jsonl").exists()


def test_a_stop_inside_one_arrangement_still_stops_the_run(tmp_path, monkeypatch):
    from placemat import stop
    b = board()
    prepared = run.begin(b)
    default = b.resolve()
    monkeypatch.setattr(run, "resolve_spec", lambda prepared, spec, **kw: (_ for _ in ()).throw(stop.Stopped(15)))
    with pytest.raises(stop.Stopped):
        run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)


def test_an_escape_that_cannot_be_laid_out_names_the_escape_and_its_part():
    from placemat import finding_text
    from placemat.lanes import EscapeError
    from tests.escape_fixtures import fan_board
    from placemat.values import CopperLayer as L
    b = fan_board(keep_going=True, via_size=0.9, via_drill=0.3)        # no legal spot for pin 10's via at this pitch
    esc = b.escape(Part("mcu"), [9, 10], vias=[9, 10], why="south pins")
    for p in (9, 10):
        b.track(Net("N%d" % p), [esc[p]], layer=L.F, why="its lane")
    with pytest.raises(EscapeError) as e:
        b.resolve()
    (r,) = run._raised_refusals(e.value)
    assert r["form"] == "escape" and r["part"] == "mcu" and r["escape"].startswith("escape ")
    assert finding_text.refusal_record_text(r) == "%s cannot be laid out with mcu as placed" % r["escape"]


def test_an_error_refusal_renders_its_type_and_message():
    from placemat import finding_text
    assert finding_text.refusal_record_text({"form": "error", "type": "ValueError", "message": "a tie"}) == \
        "its resolve or proof raised ValueError: a tie"


def proven(tmp_path, make=None):
    b = (make or board)()
    prepared = run.begin(b)
    default = b.resolve()
    return b, prepared, default, run.resolve_others(prepared, default, tmp_path, {}, {}, (), None, lambda ident: None)


def finish(b, prepared, default, got, tmp_path, cfg=None):
    from types import SimpleNamespace
    src = SimpleNamespace(board_dir=tmp_path, name="m", pcb=tmp_path / "m.kicad_pcb")
    return run.finish(prepared, default, got, src=src, cfg=cfg or Settings(), fab=None, run_dir=tmp_path, default_report=None,
                      board=b, drc=False)


def test_a_proof_that_raises_refuses_its_arrangement_and_the_others_are_written(tmp_path, monkeypatch):
    b, prepared, default, got = proven(tmp_path)

    def prove(prepared, resolved, default_plan, **kw):
        if resolved.spec.id == "c_in.east":
            raise RuntimeError("kicad-cli died")
        return run.Proof(True, [], {"drc": None})
    monkeypatch.setattr(run, "prove", prove)
    out = finish(b, prepared, default, got, tmp_path)
    by = {e["id"]: e for e in out.record}
    assert by["c_in.east"]["offered"] is False
    assert by["c_in.east"]["refused"] == [{"form": "error", "type": "RuntimeError", "message": "kicad-cli died"}]
    assert by["r_pull.turned"]["offered"] is True and by["c_in.east+r_pull.turned"]["offered"] is True
    from placemat.arrangement_note import read_notes
    docs, problems = read_notes(out.texts)
    assert problems == [] and sorted(d["id"] for d in docs) == ["c_in.east+r_pull.turned", "r_pull.turned"]
    assert [f.facts["id"] for f in out.findings if f.cause == "arrangement.refused"] == ["c_in.east"]


def test_a_note_error_outside_the_encode_is_not_read_as_the_setting(tmp_path, monkeypatch):
    from placemat import arrangement_note
    b, prepared, default, got = proven(tmp_path, with_tracks)          # copper the note writes
    monkeypatch.setattr(run, "prove", lambda *a, **kw: run.Proof(True, [], {"drc": None}))

    def no_form(op):
        raise arrangement_note.NoteError("no note form for Thing")
    monkeypatch.setattr(arrangement_note, "op_to_json", no_form)
    with pytest.raises(arrangement_note.NoteError, match="no note form"):
        finish(b, prepared, default, got[:1], tmp_path)
