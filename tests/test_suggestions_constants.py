"""Numbers a suggestion writes are named constants: where they go, the variants where the call already reads one, and
the settings table edits."""
from pathlib import Path

from placemat import script_edit as se, suggestions as sg
from tests.suggest_support import IMPORTS, apply_and_resolve, resolve, suggestions_of

NAMED = '''LIMIT = 4.0      # a bypass beyond this is a bulk capacitor
board.place(Part("u1"), at=Location(30, 30))
board.place(Part("c1"), at=Near(Location(45, 45), radius=0.5))
board.link(PadRef(Part("c1"), 1), PadRef(Part("u1"), 2), limit_mm=LIMIT)
board.place(Part("c4"), at=Location(10, 50))
board.place(Part("r1"), at=Location(10, 10))
board.place(Part("j1"), at=Location(50, 10))
'''


def raise_limit(plan):
    return [s for f in plan.findings if f.cause == "link_over" for s in f.suggestions if s.lever == "limit"]


def test_a_call_that_already_reads_a_constant_gets_both_variants(tmp_path):
    board, plan, path = resolve(tmp_path, NAMED)
    change, own = raise_limit(plan)
    assert change.text.endswith(", by changing LIMIT (every use of it changes)")
    assert own.text.endswith(", with a constant of its own")
    assert change.edit.op == "set_constant" and own.edit.op == "set_kwarg"
    shown = sg.apply_suggestion(suggestions_of(plan), change.id, dry_run=True).files[str(path)]
    import re
    assert re.search(r"\nLIMIT = \d+\.\d+ +#", shown.after) and "limit_mm=LIMIT)" in shown.after
    assert "# Measured by a run's finding (link_over)" in shown.after
    assert "# a bypass beyond this is a bulk capacitor" in shown.after           # the old comment stays
    shown = sg.apply_suggestion(suggestions_of(plan), own.id, dry_run=True).files[str(path)]
    assert "LIMIT = 4.0" in shown.after and "limit_mm=C1_LINK_LIMIT_MM)" in shown.after and re.search(r"\nC1_LINK_LIMIT_MM = \d+\.\d+\n", shown.after)


def test_either_variant_clears_the_finding(tmp_path):
    for n in (0, 1):
        sub = tmp_path / str(n)
        sub.mkdir()
        board, plan, path = resolve(sub, NAMED)
        s = raise_limit(plan)[n]
        board2, plan2 = apply_and_resolve(sub, plan, s.id, path)
        assert not [f for f in plan2.findings if f.kind == "link_over"]


def test_a_cells_constant_goes_to_the_file_of_the_call_and_a_boards_to_the_shared_module(tmp_path):
    (tmp_path / "shared.py").write_text("from placemat import board\n\nGAP = 1\n")
    (tmp_path / "placemat.toml").write_text("")
    cell = tmp_path / "cell_layout.py"
    cell.write_text("from placemat import board, Part\nfrom shared import GAP\n\nboard.place(Part('a'))\n")
    other = tmp_path / "other_layout.py"
    other.write_text("from placemat import board, Part\nfrom shared import GAP\n\nboard.place(Part('b'))\n")
    assert se.shared_module(cell) == str(tmp_path / "shared.py")

    class Fake:
        script_file = str(cell)
    binder = sg._Binder(Fake())
    assert binder.constants_file("board", str(cell)) == str(tmp_path / "shared.py")
    assert binder.constants_file("cell", str(cell)) == str(cell)
    assert binder.constants_file("board", str(tmp_path / "helper.py")) == str(tmp_path / "helper.py")


def test_with_no_module_shared_by_another_script_a_boards_constant_goes_to_the_boards_script(tmp_path):
    (tmp_path / "shared.py").write_text("GAP = 1\n")
    cell = tmp_path / "cell_layout.py"
    cell.write_text("from placemat import board, Part\nfrom shared import GAP\n\nboard.place(Part('a'))\n")
    assert se.shared_module(cell) is None            # only this script imports it

    class Fake:
        script_file = str(cell)
    assert sg._Binder(Fake()).constants_file("board", str(cell)) == str(cell)


def test_a_module_imported_by_the_most_scripts_is_the_shared_one(tmp_path):
    for name in ("one", "two"):
        (tmp_path / (name + ".py")).write_text("X = 1\n")
    main = tmp_path / "main_layout.py"
    main.write_text("from placemat import board\nimport one\nimport two\n")
    for n in range(3):
        (tmp_path / ("s%d_layout.py" % n)).write_text("from placemat import board\nimport two\n")
    assert se.shared_module(main) == str(tmp_path / "two.py")


def test_a_settings_suggestion_writes_the_scripts_own_table_and_nothing_else(tmp_path):
    original = '[place]\nenvelope = "courtyard"  # as the board is drawn\n\n[cleanup]\nenabled = false\n'
    (tmp_path / "placemat.toml").write_text(original)
    script = ('board.place(Part("u1"), at=Location(30, 30))\nboard.place(Part("j1"), at=Location(30, 30), rotations=[0, 90])\n'
              'board.place(Part("c1"), at=Location(50, 50))\n')
    board, plan, path = resolve(tmp_path, script)
    (f,) = [f for f in plan.findings if f.cause == "unplaced.bearing"]
    shown = sg.apply_suggestion(suggestions_of(plan), f.suggestions[0].id, dry_run=True)
    toml = str(tmp_path / "placemat.toml")
    after = shown.files[toml].after
    assert after.startswith(original)                                  # the rest of the file byte for byte
    assert after[len(original):].startswith('\n[scripts."layout.py".place]\nbearing_step = 2.5  # A run\'s finding')
    assert f.suggestions[0].digests[toml] == se.digest(original)
    sg.apply_suggestion(suggestions_of(plan), f.suggestions[0].id, root=tmp_path, log=tmp_path / "applied.jsonl")
    from placemat.settings import load
    assert load(tmp_path, script=path).place_bearing_step == 2.5


def test_a_settings_suggestion_is_refused_as_stale_when_the_toml_changed(tmp_path):
    (tmp_path / "placemat.toml").write_text('[place]\nenvelope = "courtyard"\n')
    script = ('board.place(Part("u1"), at=Location(30, 30))\nboard.place(Part("j1"), at=Location(30, 30), rotations=[0, 90])\n'
              'board.place(Part("c1"), at=Location(50, 50))\n')
    board, plan, path = resolve(tmp_path, script)
    (f,) = [f for f in plan.findings if f.cause == "unplaced.bearing"]
    (tmp_path / "placemat.toml").write_text('[place]\nenvelope = "union"\n')
    try:
        sg.apply_suggestion(suggestions_of(plan), f.suggestions[0].id, dry_run=True)
    except sg.StaleSuggestion as e:
        assert e.files == [str(tmp_path / "placemat.toml")]
    else:
        raise AssertionError("a changed placemat.toml was not refused")


def test_no_check_that_the_edit_would_change_more_than_the_target_passes_when_it_does():
    before = IMPORTS + '\nboard.place(Part("c4"))\nboard.place(Part("c5"))\n'
    after = before.replace('Part("c5")', 'Part("c6")').replace('Part("c4")', 'Part("c4"), face=Face.EITHER')
    import pytest
    with pytest.raises(se.EditRefused, match="more than the target"):
        se._check_call_edit(before, after, 5, "Attribute(value=Name(id='board', ctx=Load()), attr='place', ctx=Load())")
