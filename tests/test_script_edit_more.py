"""script_edit: lists, statements, settings, constants and undo."""
import ast

import pytest

from placemat import script_edit as se
from placemat.suggestions import Edit, Target
from tests.test_script_edit import FACE, HEAD, edit, line_of, run


# ------------------------------------------------------------------ nesting and encoding
def test_a_call_inside_a_function_keeps_its_indentation_when_a_keyword_is_added_or_removed():
    text = HEAD + ('def build():\n    board.place(\n        Part("c4"),\n        at=Edge.NORTH,  # n\n        face=Face.FRONT,\n    )\n'
                   '\n\nbuild()\n')
    added = run("set_kwarg", text, "board.place", args={"name": "priority"}, value={"enum": "Priority.HIGH"})
    assert added == text.replace("        face=Face.FRONT,\n", "        face=Face.FRONT,\n        priority=Priority.HIGH,\n")
    removed = run("remove_kwarg", text, "board.place", args={"name": "face"})
    assert removed == text.replace("        face=Face.FRONT,\n", "")


def test_non_ascii_text_and_crlf_line_ends_are_kept():
    text = (HEAD + 'board.place(Part("c4"), why="a café")  # µF\nboard.place(Part("c5"))\n').replace("\n", "\r\n")
    out = run("set_kwarg", text, '"c4"', args={"name": "face"}, value=FACE)
    assert out == text.replace('why="a café")', 'why="a café", face=Face.EITHER)')


# ------------------------------------------------------------------ edit_list
LISTED = HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",  # first\n    "B",\n])\n'


def lst(op_args, value, text=LISTED, **kw):
    return run("edit_list", text, "board.keepout", kind="keepout", key="ant", args=dict({"arg": "allow"}, **op_args),
               value=value, **kw)


def test_edit_list_adds_an_element_at_the_end_keeping_the_layout():
    out = lst({"action": "add"}, {"str": "C"})
    assert out == HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",  # first\n    "B",\n    "C",\n])\n'


def test_edit_list_adds_to_a_list_without_a_trailing_comma_and_to_one_on_a_line():
    text = HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",\n    "B"\n])\n'
    assert lst({"action": "add"}, {"str": "C"}, text) == HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",\n    "B",\n    "C"\n])\n'
    text = HEAD + 'board.keepout(shape, "ant", allow=("A", "B"))\n'
    assert lst({"action": "add"}, {"str": "C"}, text) == HEAD + 'board.keepout(shape, "ant", allow=("A", "B", "C"))\n'
    text = HEAD + 'board.keepout(shape, "ant", allow=[])\n'
    assert lst({"action": "add"}, {"str": "C"}, text) == HEAD + 'board.keepout(shape, "ant", allow=["C"])\n'


def test_edit_list_adds_before_and_after_an_element():
    assert lst({"action": "add", "before": {"str": "B"}}, {"str": "X"}) == \
        HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",  # first\n    "X",\n    "B",\n])\n'
    assert lst({"action": "add", "after": {"str": "A"}}, {"str": "X"}) == \
        HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",  # first\n    "X",\n    "B",\n])\n'
    assert lst({"action": "add", "before": {"str": "A"}}, {"str": "X"}) == \
        HEAD + 'board.keepout(shape, "ant", allow=[\n    "X",\n    "A",  # first\n    "B",\n])\n'


def test_edit_list_removes_an_element_and_its_comment_moves_up():
    text = HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",\n    "B",  # second\n    "C",\n])\n'
    assert lst({"action": "remove"}, {"str": "B"}, text) == HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",  # second\n    "C",\n])\n'
    assert lst({"action": "remove"}, {"str": "C"}, text) == HEAD + 'board.keepout(shape, "ant", allow=[\n    "A",\n    "B",  # second\n])\n'
    assert lst({"action": "remove"}, {"str": "A"}, text) == HEAD + 'board.keepout(shape, "ant", allow=[\n    "B",  # second\n    "C",\n])\n'


def test_edit_list_removes_the_last_element_to_an_empty_list():
    text = HEAD + 'board.keepout(shape, "ant", allow=["A"])\n'
    assert lst({"action": "remove"}, {"str": "A"}, text) == HEAD + 'board.keepout(shape, "ant", allow=[])\n'


def test_edit_list_moves_an_element_with_its_comment():
    out = lst({"action": "move", "after": {"str": "B"}}, {"str": "A"})
    assert out == HEAD + 'board.keepout(shape, "ant", allow=[\n    "B",\n    "A",  # first\n])\n'
    text = HEAD + 'board.keepout(shape, "ant", allow=["A", "B", "C"])\n'
    assert lst({"action": "move", "before": {"str": "A"}}, {"str": "C"}, text) == \
        HEAD + 'board.keepout(shape, "ant", allow=["C", "A", "B"])\n'


def test_edit_list_refuses_what_it_cannot_do():
    with pytest.raises(se.EditRefused, match="already in the list"):
        lst({"action": "add"}, {"str": "A"})
    with pytest.raises(se.EditRefused, match="not in the list"):
        lst({"action": "remove"}, {"str": "Z"})
    text = HEAD + 'NETS = ["A"]\nboard.keepout(shape, "ant", allow=NETS)\n'
    with pytest.raises(se.EditRefused, match="brackets"):
        lst({"action": "add"}, {"str": "C"}, text)
    text = HEAD + 'board.keepout(shape, "ant")\n'
    with pytest.raises(se.EditRefused, match="no allow"):
        lst({"action": "add"}, {"str": "C"}, text)


def test_edit_list_swaps_the_members_of_a_row():
    text = HEAD + 'board.row(\n    [Part("r7"), Part("r8")],\n)\n'
    out = run("edit_list", text, "board.row", kind="row", key="r7",
              args={"arg": 0, "action": "move", "after": {"form": "Part", "args": [{"str": "r8"}]}},
              value={"form": "Part", "args": [{"str": "r7"}]})
    assert out == HEAD + 'board.row(\n    [Part("r8"), Part("r7")],\n)\n'


# ------------------------------------------------------------------ insert_statement, remove_statement
def test_insert_statement_adds_a_call_after_the_targets_statement_at_its_indent():
    text = HEAD + 'board.place(Part("c4"))  # c4\n\nboard.place(Part("c5"))\n'
    value = {"form": "board.link", "args": [{"item": "C4"}, {"item": "C5"}],
             "kwargs": {"weight": {"enum": "LinkWeight.SHORT"}}}
    refs = {"C4": Target("place", "c4", "script.py", line_of(text, '"c4"')),
            "C5": Target("place", "c5", "script.py", line_of(text, '"c5"'))}
    out = run("insert_statement", text, '"c4"', value=value, refs=refs)
    assert out == HEAD + ('board.place(Part("c4"))  # c4\nboard.link(Part("c4"), Part("c5"), weight=LinkWeight.SHORT)\n'
                          '\nboard.place(Part("c5"))\n')


def test_insert_statement_inside_a_function():
    text = HEAD + 'def build():\n    board.place(Part("c4"))\n    board.place(Part("c5"))\n\n\nbuild()\n'
    value = {"form": "board.place", "args": [{"form": "Part", "args": [{"str": "c9"}]}]}
    out = run("insert_statement", text, '"c4"', value=value)
    assert out == HEAD + ('def build():\n    board.place(Part("c4"))\n    board.place(Part("c9"))\n'
                          '    board.place(Part("c5"))\n\n\nbuild()\n')


def test_remove_statement_keeps_the_comments_above_it_for_the_next_statement():
    text = HEAD + 'board.place(Part("c3"))\n\n# --- section ---\nboard.accept(a, b)  # not needed\nboard.place(Part("c5"))\n'
    out = run("remove_statement", text, "board.accept", kind="accept", key="a")
    assert out == HEAD + 'board.place(Part("c3"))\n\n# --- section ---\nboard.place(Part("c5"))\n'


def test_remove_the_last_statement_of_a_block_keeps_its_comments():
    text = HEAD + 'def build():\n    board.place(Part("c3"))\n    # about the accept\n    board.accept(a, b)\n\n\nbuild()\n'
    out = run("remove_statement", text, "board.accept", kind="accept", key="a")
    assert "# about the accept" in out and "board.accept" not in out
    ast.parse(out)


def test_remove_statement_refuses_a_call_that_is_not_a_statement_of_its_own():
    text = HEAD + 'x = board.accept(a, b)\n'
    with pytest.raises(se.EditRefused, match="statement of its own"):
        run("remove_statement", text, "board.accept", kind="accept", key="a")


# ------------------------------------------------------------------ toml_set
TOML = '''# placemat
[place]
envelope = "physical"

[scripts."m/a_layout.py".place]
bearing_step = 10.0  # a step
radius = 3.0

[scripts."m/b_layout.py".place]
bearing_step = 15.0

[cleanup]
enabled = false
'''
TABLE = ["scripts", "m/a_layout.py", "place"]


def toml(text, key, value, table=TABLE, comment=""):
    return se.apply(Edit("toml_set", None, {"table": table, "key": key, "comment": comment}, value,
                         file="placemat.toml"), text)


def test_toml_set_changes_the_one_line_and_keeps_its_comment():
    assert toml(TOML, "bearing_step", 2.5) == TOML.replace("bearing_step = 10.0  # a step", "bearing_step = 2.5  # a step")


def test_toml_set_adds_a_key_at_the_end_of_the_table_with_a_comment_where_the_file_has_comments():
    out = toml(TOML, "step", 0.1, comment="from a finding")
    assert out == TOML.replace("radius = 3.0\n", "radius = 3.0\nstep = 0.1  # from a finding\n")


def test_toml_set_adds_a_table_at_the_end():
    out = toml(TOML, "via_move", 1.0, table=["scripts", "m/c_layout.py", "place"])
    assert out == TOML + '\n[scripts."m/c_layout.py".place]\nvia_move = 1.0\n'


def test_toml_set_leaves_another_scripts_table_alone():
    assert "bearing_step = 15.0" in toml(TOML, "bearing_step", 2.5)


def test_toml_set_in_an_empty_or_unterminated_file():
    assert toml("", "step", 1) == '[scripts."m/a_layout.py".place]\nstep = 1\n'
    assert toml('[place]\nstep = 1', "radius", 2.0, table=["place"]) == '[place]\nstep = 1\nradius = 2.0\n'


def test_toml_set_writes_booleans_and_strings():
    assert toml("[place]\n", "envelope", "union", table=["place"]) == '[place]\nenvelope = "union"\n'
    assert toml("[solve]\n", "enabled", True, table=["solve"]) == '[solve]\nenabled = true\n'


# ------------------------------------------------------------------ set_constant
def const(value=5.1, name="C4_LINK_LIMIT_MM", comment="Measured by a run's finding: link_over, 5.10 mm.", **kw):
    return {"const": dict({"name": name, "value": value, "comment": comment}, **kw)}


LINK = {"kind": "link", "key": "a>b", "args": {"name": "limit_mm"}}


def test_a_measured_number_is_a_named_constant_with_a_comment_made_after_the_imports():
    text = HEAD + 'board.link(a, b, limit_mm=4.0)\n'
    out = run("set_kwarg", text, "board.link", value=const(), **LINK)
    assert out == HEAD + ("# Measured by a run's finding: link_over, 5.10 mm.\nC4_LINK_LIMIT_MM = 5.1\n\n"
                          "board.link(a, b, limit_mm=C4_LINK_LIMIT_MM)\n")
    assert "limit_mm=5.1" not in out


def test_a_constant_goes_at_the_end_of_the_scripts_constants_block():
    text = HEAD + 'GAP = 0.3      # silk gap\nVIA = 0.45\n\nboard.link(a, b, limit_mm=4.0)\n'
    out = run("set_kwarg", text, "board.link", value=const(), **LINK)
    assert out == HEAD + ('GAP = 0.3      # silk gap\nVIA = 0.45\n# Measured by a run\'s finding: link_over, 5.10 mm.\n'
                          'C4_LINK_LIMIT_MM = 5.1\n\nboard.link(a, b, limit_mm=C4_LINK_LIMIT_MM)\n')


def test_a_name_already_bound_gets_a_counter_and_nothing_is_overwritten():
    text = HEAD + 'C4_LINK_LIMIT_MM = 9.0\n\nboard.link(a, b, limit_mm=4.0)\n'
    out = run("set_kwarg", text, "board.link", value=const(), **LINK)
    assert "C4_LINK_LIMIT_MM = 9.0\n" in out and "C4_LINK_LIMIT_MM_2 = 5.1\n" in out
    assert out.endswith("limit_mm=C4_LINK_LIMIT_MM_2)\n")


def test_a_name_bound_in_an_imported_module_is_not_reused(tmp_path):
    (tmp_path / "shared.py").write_text("C4_LINK_LIMIT_MM = 1.0\n")
    cell = tmp_path / "cell.py"
    cell.write_text(HEAD + 'from shared import *\n\nboard.link(a, b, limit_mm=4.0)\n')
    e = Edit("set_kwarg", Target("link", "a>b", str(cell), 5), {"name": "limit_mm"}, const())
    out = se.apply_all(e)
    assert "C4_LINK_LIMIT_MM_2" in out[str(cell)][1]


def test_a_board_wide_value_goes_to_the_shared_module_and_the_call_imports_it():
    files = {"cell.py": HEAD + 'from shared import frame\n\nboard.link(a, b, limit_mm=4.0)\n',
             "shared.py": "from placemat import board\n\n\ndef frame():\n    pass\n"}
    e = Edit("set_kwarg", Target("link", "a>b", "cell.py", 5), {"name": "limit_mm"}, const(file="shared.py"))
    out = se.apply_all(e, files.__getitem__)
    assert set(out) == {"cell.py", "shared.py"}
    assert out["cell.py"][1] == HEAD + 'from shared import frame, C4_LINK_LIMIT_MM\n\nboard.link(a, b, limit_mm=C4_LINK_LIMIT_MM)\n'
    assert out["shared.py"][1].count("C4_LINK_LIMIT_MM = 5.1") == 1
    assert out["shared.py"][1].index("C4_LINK_LIMIT_MM") < out["shared.py"][1].index("def frame")


def test_a_call_gets_an_import_line_where_it_has_none_from_the_shared_module():
    files = {"cell.py": HEAD + 'board.link(a, b, limit_mm=4.0)\n', "shared.py": "X = 1\n"}
    e = Edit("set_kwarg", Target("link", "a>b", "cell.py", 3), {"name": "limit_mm"}, const(file="shared.py"))
    out = se.apply_all(e, files.__getitem__)
    assert out["cell.py"][1] == HEAD.rstrip("\n") + '\nfrom shared import C4_LINK_LIMIT_MM\n\nboard.link(a, b, limit_mm=C4_LINK_LIMIT_MM)\n'


def test_set_constant_changes_an_existing_constant_and_says_why_above_it():
    text = HEAD + 'GAP = 0.3  # silk gap\nboard.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH, gap=GAP))\n'
    e = Edit("set_constant", None, {"name": "GAP", "existing": True, "comment": "Raised: 0.5 mm clears it."}, 0.5,
             file="script.py")
    out = se.apply(e, text)
    assert out == HEAD + ('# Raised: 0.5 mm clears it.\nGAP = 0.5  # silk gap\n'
                          'board.place(Part("c4"), at=Beside(Part("c1"), Edge.NORTH, gap=GAP))\n')


def test_a_derived_value_is_written_inline_from_existing_names_and_adds_no_constant():
    text = HEAD + 'PAD_DIAMETER_MM = 0.8\nboard.track(net, pts, layer=L)\n'
    out = run("set_kwarg", text, "board.track", kind="track", key="net", args={"name": "radius"},
              value={"div": [{"name": "PAD_DIAMETER_MM"}, {"num": 2}]})
    assert out.endswith("board.track(net, pts, layer=L, radius=PAD_DIAMETER_MM / 2)\n")
    assert out.count("\n") == text.count("\n")
    with pytest.raises(se.EditRefused, match="does not bind|not a name"):
        run("set_kwarg", text, "board.track", kind="track", key="net", args={"name": "radius"},
            value={"div": [{"name": "OTHER"}, {"num": 2}]})


def test_a_constant_comes_after_a_docstring_and_the_imports():
    text = '"""A cell."""\nfrom __future__ import annotations\nfrom placemat import board\n\nboard.link(a, b, limit_mm=4.0)\n'
    out = run("set_kwarg", text, "board.link", value=const(), **LINK)
    assert out.startswith('"""A cell."""\nfrom __future__ import annotations\nfrom placemat import board\n\n# Measured')


# ------------------------------------------------------------------ undo
def test_undo_is_the_exact_inverse_and_refuses_when_the_text_moved_on():
    text = HEAD + 'board.place(Part("c4"))\n'
    after = run("set_kwarg", text, "board.place", args={"name": "face"}, value=FACE)
    assert se.undo(text, after, after) == text
    with pytest.raises(se.EditRefused, match="changed"):
        se.undo(text, after, after + "# edited by hand\n")
