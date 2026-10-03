"""A small board built end to end by the builder, each action as data, the script byte for byte (tests/builder_golden/board_*.txt), checked
after every action: the text parses, the `ast` outside the inserted nodes is what it was, the script resolves with the expected status per
part, and no coordinate is written. The same sequence then goes through the applied log: undone step by step each earlier text comes
back and the first undo removes the file, redo makes each again, and an edit made outside the builder makes an undo refuse."""
import ast
import json

import pytest

from placemat import builder_intents as bi, suggestions as sg
from tests.builder_support import GOLDEN, Session, coordinates_in, golden
from tests.fixtures import footprint

PARTS = [footprint("J1", 10, 10, w=4, h=4, inst="j1", nets=("OUT", "GND")), footprint("U1", 10, 30, w=6, h=2, inst="u1", nets=("VIN", "OUT")),
         footprint("C1", 30, 30, inst="c1", nets=("VIN", "GND")), footprint("C2", 30, 40, inst="c2", nets=("VIN", "GND")),
         footprint("R1", 40, 10, inst="r1", nets=("S1", "GND")), footprint("R2", 40, 20, inst="r2", nets=("S2", "GND")),
         footprint("R3", 40, 30, inst="r3", nets=("S3", "GND")), footprint("D1", 50, 10, inst="d1", nets=("S1", "S2"))]

# (subjects, target, intent, params): the actions of the sequence, as the page sends them
ACTIONS = [
    (["j1"], {"kind": "edge", "edge": "NORTH"}, "on_edge_mid", {}),
    (["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside", {"gap": 0.5, "gap_note": "the connector's shell is tall"}),
    (["c1"], {"kind": "pad", "key": "u1", "pad": "VIN"}, "close_to_pad", {}),
    (["r1", "r2", "r3"], {"kind": "edge", "edge": "EAST"}, "row_mid", {}),
]


def run(tmp_path):
    s = Session(tmp_path, parts=PARTS)
    texts, statuses = [], []
    for subjects, target, intent, params in ACTIONS:
        before = s.text
        s.act(subjects, target, intent, **params)
        ast.parse(s.text)
        assert coordinates_in(s.text) == []
        texts.append(s.text)
        statuses.append({k: r["status"] for k, r in s.ctx.rows.items()})
        assert before != s.text
    return s, texts, statuses


def test_the_board_is_built_byte_for_byte_and_each_part_has_its_status(tmp_path):
    s, texts, statuses = run(tmp_path)
    for i, t in enumerate(texts):
        assert t == golden("board_step%d.txt" % (i + 1)), "step %d" % (i + 1)
    assert statuses[0] == {"j1": "decided", "u1": "unplaced", "c1": "unplaced", "c2": "unplaced", "r1": "unplaced", "r2": "unplaced", "r3": "unplaced", "d1": "unplaced"}
    assert statuses[-1] == {"j1": "decided", "u1": "decided", "c1": "searched", "c2": "unplaced", "r1": "decided", "r2": "decided", "r3": "decided", "d1": "unplaced"}
    sug = bi.search_rest(s.ctx)
    s.apply(list(sug["suggestion"].edits))
    assert s.text == golden("board_final.txt")
    assert {k: r["status"] for k, r in s.ctx.rows.items()} == {"j1": "decided", "u1": "decided", "c1": "searched", "c2": "searched", "r1": "decided",
                                                              "r2": "decided", "r3": "decided", "d1": "searched"}


def test_the_ast_outside_each_inserted_node_is_unchanged_by_every_action(tmp_path):
    s = Session(tmp_path, parts=PARTS)
    for subjects, target, intent, params in ACTIONS:
        before = ast.parse(s.text)
        s.act(subjects, target, intent, **params)
        after = ast.parse(s.text)
        # every statement the script had is still there as it was, in order (the import line only widens)
        kept = [ast.dump(n) for n in before.body if not isinstance(n, ast.ImportFrom)]
        now = [ast.dump(n) for n in after.body if not isinstance(n, ast.ImportFrom)]
        it = iter(now)
        assert all(any(k == n for n in it) for k in kept), (intent, kept)
        old_names = [a.name for n in before.body if isinstance(n, ast.ImportFrom) for a in n.names]
        new_names = [a.name for n in after.body if isinstance(n, ast.ImportFrom) for a in n.names]
        assert set(old_names) <= set(new_names) and new_names[0] == "board"


def test_undo_takes_each_step_back_the_first_removes_the_file_and_redo_makes_them_again(tmp_path):
    s = Session(tmp_path, parts=PARTS)
    script, log = s.path.resolve(), tmp_path / "applied.jsonl"
    first = script.read_text()
    script.unlink()                                  # the first write makes the file
    sg.apply_edits([sg.Edit("create_file", None, {"text": first}, None, {}, str(script))], {str(script): ""}, root=tmp_path, log=log,
                   label="Make the layout script", source="builder")
    seen = [first]
    for subjects, target, intent, params in ACTIONS:
        o = s.offer(subjects, target, intent, **params)
        sg.apply_edits(o.edits, s.ctx.digests, root=tmp_path, log=log, label=o.text, source="builder")
        s.text = script.read_text()
        s.resolve()
        seen.append(s.text)
    assert seen[-1] == golden("board_step4.txt")
    for want in reversed(seen[:-1]):
        sg.undo_last(log, root=tmp_path)
        assert script.read_text() == want
    sg.undo_last(log, root=tmp_path)                 # past the first write: no layout
    assert not script.exists()
    for want in seen:
        sg.redo_last(log, root=tmp_path)
        assert script.read_text() == want
    script.write_text(seen[-1] + "# a hand edit\n")
    with pytest.raises(sg.UndoRefused):
        sg.undo_last(log, root=tmp_path)
    assert script.read_text() == seen[-1] + "# a hand edit\n"
    entries = [json.loads(l) for l in log.read_text().splitlines()]
    assert {e["source"] for e in entries} == {"builder"} and entries[0]["files"][0]["before"] is None


def test_every_golden_script_holds_no_coordinate():
    names = sorted(p.name for p in GOLDEN.glob("*.txt"))
    assert len(names) >= 15
    for n in names:
        assert coordinates_in(golden(n)) == [], n
