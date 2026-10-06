"""What a saved explore compares of the script: its code, not its text. A comment, a docstring or a blank line changed since
the explore began leaves its variants acceptable (and its checkpoint resumable); a change to the code is refused, naming
the files whose code changed."""
import json

import pytest

from placemat import checkpoint, explore, lock
from placemat.explore import search
from tests import explore_boards as eb

SEEDS = range(0, 8)
CODE = '"""The board."""\nfrom helper import GAP\n\n\ndef place(board):\n    """Where it goes."""\n    return GAP  # the gap\n'
HELPER = "GAP = 1.0\n"


def _searched(tmp_path):
    (tmp_path / "helper.py").write_text(HELPER)
    script = tmp_path / "Board_layout.py"
    script.write_text(CODE)
    report, _ = search(eb.make, script, seconds=60, jobs=2, seeds=SEEDS, checkpoint_dir=tmp_path / "state")
    assert report["best_seed"] != 0
    return script, report


def test_a_comment_docstring_or_blank_line_edit_still_accepts(tmp_path):
    script, report = _searched(tmp_path)
    script.write_text(CODE.replace("# the gap", "# the gap, wider now").replace('"""The board."""', '"""The board, again."""')
                      .replace('"""Where it goes."""', '"""Where it goes, said differently."""') + "\n\n# the end\n")
    said = explore.accept_best(script, tmp_path / "state", seed=report["best_seed"])
    assert "seed %d" % report["best_seed"] in said
    assert {e.key for e in lock.read(lock.path_for(script))} == set(eb.KEYS)


def test_a_code_change_is_refused_naming_the_files_it_was_in(tmp_path):
    script, report = _searched(tmp_path)
    (tmp_path / "helper.py").write_text("GAP = 2.0  # a code change\n")
    with pytest.raises(explore.ScriptChanged) as e:
        explore.accept_best(script, tmp_path / "state", seed=report["best_seed"])
    assert e.value.changed == ["helper.py"] and e.value.added == [] and e.value.removed == []
    assert "helper.py" in str(e.value) and isinstance(e.value, ValueError)
    assert not lock.path_for(script).exists()


def test_the_script_itself_changed_is_named_as_the_script(tmp_path):
    script, report = _searched(tmp_path)
    script.write_text(CODE.replace("return GAP", "return GAP * 2"))
    with pytest.raises(explore.ScriptChanged) as e:
        explore.accept_best(script, tmp_path / "state")
    assert e.value.changed == ["Board_layout.py"]


def test_an_explore_saved_by_a_release_that_digested_the_text_is_accepted_while_the_text_is_the_same(tmp_path):
    script, report = _searched(tmp_path)
    best = tmp_path / "state" / "best.json"
    doc = json.loads(best.read_text())
    from placemat.project import script_fingerprint
    doc["script"] = checkpoint.sha(script_fingerprint(script, with_lock=False))
    doc.pop("script_files", None)
    best.write_text(json.dumps(doc))
    assert "seed" in explore.accept_best(script, tmp_path / "state")


def test_a_saved_explore_resumes_after_a_comment_edit(tmp_path, capsys):
    (tmp_path / "helper.py").write_text(HELPER)
    script = tmp_path / "Board_layout.py"
    script.write_text(CODE)
    search(eb.make, script, seconds=60, jobs=2, seeds=SEEDS, checkpoint_dir=tmp_path / "state", keep_state=True)
    lines = checkpoint.read_lines(tmp_path / "state" / "checkpoint.jsonl")
    assert lines[0]["script_files"]
    script.write_text(CODE + "# a note\n")
    capsys.readouterr()
    search(eb.make, script, seconds=60, jobs=2, seeds=SEEDS, checkpoint_dir=tmp_path / "state", keep_state=True)
    out = capsys.readouterr().out
    assert "resuming a saved explore" in out and "was not continued" not in out
