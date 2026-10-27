"""tests/impact.py: which slow tests a change reaches, from the recorded map."""
import subprocess

import pytest

from tests import impact

A = "tests/test_a.py::test_one"
B = "tests/test_b.py::test_two"
C = "tests/test_c.py::test_three"
ENTRIES = {
    A: {"funcs": {"src/placemat/escapes.py::path_out", "tests/test_a.py::test_one"},
        "opened": {"fixtures/mod/layout/layout.kicad_pcb"}, "spawns": False},
    B: {"funcs": {"src/placemat/escapes.py::Escapes.closed", "tests/test_b.py::test_two"}, "opened": set(),
        "spawns": False},
    C: {"funcs": {"tests/test_c.py::test_three"}, "opened": set(), "spawns": True},
}


def _select(monkeypatch, changes, local=True, slow=(A, B, C), funcs=("src/placemat/escapes.py::path_out",)):
    monkeypatch.setattr(impact, "changed_paths", lambda ref: changes)
    monkeypatch.setattr(impact, "reaches_only_code", lambda ref, path: local)
    monkeypatch.setattr(impact, "changed_functions", lambda ref, path: set(funcs))
    return impact.selected("v0", set(slow), ENTRIES)


def test_a_changed_function_runs_the_tests_that_ran_it_and_those_that_spawn(monkeypatch):
    assert _select(monkeypatch, [("M", "src/placemat/escapes.py")]) == {A, C}
    assert _select(monkeypatch, [("M", "src/placemat/escapes.py")], funcs=("src/placemat/escapes.py::Escapes.closed",)) == {B, C}


def test_the_map_packs_and_loads_back(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(impact, "MAP", tmp_path / "map.json")
    (tmp_path / "map.json").write_text(json.dumps(impact.pack(ENTRIES)))
    assert impact.load_map() == ENTRIES


def test_a_change_outside_functions_runs_every_slow_test(monkeypatch):
    assert _select(monkeypatch, [("M", "src/placemat/escapes.py")], local=False) is None


def test_a_deleted_module_runs_every_slow_test(monkeypatch):
    assert _select(monkeypatch, [("D", "src/placemat/escapes.py")]) is None


def test_the_native_module_and_the_environment_run_every_slow_test(monkeypatch):
    for path in ("native/src/surface.rs", "uv.lock", "pyproject.toml", "tests/impact.py"):
        assert _select(monkeypatch, [("M", path)]) is None, path


def test_a_module_file_runs_the_tests_that_opened_a_file_of_that_module(monkeypatch):
    assert _select(monkeypatch, [("M", "fixtures/mod/board_rules.zen")]) == {A, C}
    assert _select(monkeypatch, [("M", "fixtures/other/board_rules.zen")]) == {C}


def test_a_test_file_changed_at_module_level_runs_its_own_slow_tests(monkeypatch):
    assert _select(monkeypatch, [("M", "tests/test_b.py")], local=False) == {B, C}


def test_a_document_no_test_read_runs_only_what_always_runs(monkeypatch):
    assert _select(monkeypatch, [("M", "docs/notes.md")]) == {C}


def test_a_slow_test_with_no_entry_runs(monkeypatch):
    new = "tests/test_d.py::test_new"
    assert _select(monkeypatch, [], slow=(A, B, C, new)) == {C, new}


def test_a_path_is_in_its_folders_two_levels_deep_and_more():
    assert impact._folders("fixtures/a/b/c.pcb") == ["fixtures/a", "fixtures/a/b"]
    assert impact._folders("README.md") == [] and impact._folders("docs/x.md") == []


def _repo(tmp_path, monkeypatch, before: str, after: str):
    run = lambda *a: subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    run("init", "-q")
    (tmp_path / "m.py").write_text(before)
    run("add", "m.py")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a")
    (tmp_path / "m.py").write_text(after)
    monkeypatch.setattr(impact, "ROOT", tmp_path)
    return impact.reaches_only_code("HEAD", "m.py")


BASE = 'LIMIT = 1\n\n\ndef f(a=2):\n    return a + LIMIT\n\n\nclass K:\n    y = 3\n'


@pytest.mark.parametrize("old,new", [("return a + LIMIT", "return a - LIMIT"), ("a=2", "a=3"), ("def f(a=2)", "def f(a=2, b=0)")],
                         ids=["body", "default", "signature"])
def test_a_change_to_a_function_is_local(tmp_path, monkeypatch, old, new):
    assert _repo(tmp_path, monkeypatch, BASE, BASE.replace(old, new))


def test_a_statement_moved_unchanged_is_local(tmp_path, monkeypatch):
    assert _repo(tmp_path, monkeypatch, BASE, BASE.replace("LIMIT = 1\n", "") + "\nLIMIT = 1\n")


def test_an_import_of_one_more_name_and_a_dropped_constant_are_local(tmp_path, monkeypatch):
    before = "from os import path\nOLD = 1\n" + BASE
    assert _repo(tmp_path, monkeypatch, before, "from os import path, sep\n" + BASE)


def test_a_new_constant_a_new_function_and_a_comment_are_local(tmp_path, monkeypatch):
    after = BASE.replace("LIMIT = 1\n", "LIMIT = 1\nSTEP = 5     # new\n# a note\n") + \
        "\n\n@staticmethod\ndef g():\n    return STEP\n"
    assert _repo(tmp_path, monkeypatch, BASE, after)


@pytest.mark.parametrize("old,new", [("LIMIT = 1", "LIMIT = 2"), ("y = 3", "y = 4"), ("class K:", "class K(dict):")],
                         ids=["constant", "class-attribute", "base"])
def test_a_changed_constant_class_attribute_or_base_is_not(tmp_path, monkeypatch, old, new):
    assert not _repo(tmp_path, monkeypatch, BASE, BASE.replace(old, new))


def test_a_changed_statement_that_binds_no_name_is_not(tmp_path, monkeypatch):
    before = BASE + "\nprint(LIMIT)\n"
    assert not _repo(tmp_path, monkeypatch, before, before.replace("print(LIMIT)", "print(LIMIT + 1)"))


def test_a_changed_line_names_the_innermost_function_that_holds_it(tmp_path, monkeypatch):
    src = "class K:\n    def m(self):\n        def inner():\n            return 1\n        return inner()\n\n\ndef f():\n    return 2\n"
    _repo(tmp_path, monkeypatch, src, src.replace("return 1", "return 3").replace("return 2", "return 4"))
    assert impact.changed_functions("HEAD", "m.py") == {"m.py::K.m.<locals>.inner", "m.py::f"}


SETTINGS = 'class S:\n    a: float = 1.0\n\n\nPOSITIVE = frozenset(["a", "z"])\nORDER = ("a",)\n'


def test_a_registry_that_gains_only_a_new_setting_is_local(tmp_path, monkeypatch):
    after = SETTINGS.replace("    a: float = 1.0\n", "    a: float = 1.0\n    b: float = 2.0\n") \
        .replace('frozenset(["a", "z"])', 'frozenset(["a", "z", "b"])').replace('("a",)', '("a", "b")')
    assert _repo(tmp_path, monkeypatch, SETTINGS, after)


@pytest.mark.parametrize("new", ['frozenset(["a", "z", "c"])', 'frozenset(["a"])', 'frozenset(["z", "a", "b"])'],
                         ids=["a-name-not-added", "a-name-dropped", "reordered"])
def test_a_registry_changed_otherwise_is_not(tmp_path, monkeypatch, new):
    after = SETTINGS.replace("    a: float = 1.0\n", "    a: float = 1.0\n    b: float = 2.0\n") \
        .replace('frozenset(["a", "z"])', new)
    assert not _repo(tmp_path, monkeypatch, SETTINGS, after)


FORMS = 'FORMS = {"a": lambda r: "x", "b": lambda r: "y"}\n'


def test_a_dict_registry_that_gains_an_entry_is_local(tmp_path, monkeypatch):
    assert _repo(tmp_path, monkeypatch, FORMS, FORMS.replace('"b"', '"c": lambda r: "z", "b"'))


def test_a_dict_registry_with_a_changed_entry_is_not(tmp_path, monkeypatch):
    assert not _repo(tmp_path, monkeypatch, FORMS, FORMS.replace('"y"', '"w"'))
