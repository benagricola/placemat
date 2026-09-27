"""A 3D model path that does not resolve from the project's folder is
re-anchored to the nearest folder above it that holds the same tail."""
from placemat import models


def _tree(tmp_path):
    (tmp_path / "parts" / "p").mkdir(parents=True)
    (tmp_path / "parts" / "p" / "f.step").write_text("")
    project = tmp_path / "boards" / "core" / "modules" / "m" / "layout"
    project.mkdir(parents=True)
    return project


def test_a_path_one_level_short_is_re_anchored(tmp_path):
    project = _tree(tmp_path)
    text, found = models.reanchor("${KIPRJMOD}/../../../parts/p/f.step", project)
    assert text == "${KIPRJMOD}/../../../../../parts/p/f.step" and found


def test_a_path_that_resolves_is_left(tmp_path):
    project = _tree(tmp_path)
    assert models.reanchor("${KIPRJMOD}/../../../../../parts/p/f.step", project) == (None, True)
    assert models.reanchor("../../../../../parts/p/f.step", project) == (None, True)


def test_a_relative_path_is_re_anchored_as_kiprjmod(tmp_path):
    project = _tree(tmp_path)
    assert models.reanchor("../parts/p/f.step", project) == ("${KIPRJMOD}/../../../../../parts/p/f.step", True)


def test_other_variables_and_absolute_paths_are_left(tmp_path):
    project = _tree(tmp_path)
    assert models.reanchor("${KICAD9_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0402.step", project) == (None, True)
    assert models.reanchor("/nowhere/parts/p/f.step", project) == (None, True)


def test_a_tail_found_nowhere_is_left_and_said(tmp_path):
    project = _tree(tmp_path)
    assert models.reanchor("${KIPRJMOD}/../parts/q/g.step", project) == (None, False)


def test_the_search_stops_at_the_workspace(tmp_path):
    project = _tree(tmp_path)
    (tmp_path / "boards" / "pcb.toml").write_text("[workspace]\n")
    stop = models.workspace_root(project)
    assert stop == tmp_path / "boards"
    assert models.reanchor("${KIPRJMOD}/../parts/p/f.step", project, stop) == (None, False)   # parts/ is above it


def test_a_tail_in_the_project_folder_itself(tmp_path):
    project = _tree(tmp_path)
    (project / "parts" / "p").mkdir(parents=True)
    (project / "parts" / "p" / "f.step").write_text("")
    assert models.reanchor("${KIPRJMOD}/../../parts/p/f.step", project) == ("${KIPRJMOD}/parts/p/f.step", True)


def test_backslashes_are_separators(tmp_path):
    project = _tree(tmp_path)
    assert models.reanchor("${KIPRJMOD}\\..\\..\\..\\parts\\p\\f.step", project) == \
        ("${KIPRJMOD}/../../../../../parts/p/f.step", True)


def test_the_run_line_says_what_was_done_and_nothing_when_nothing_was():
    assert models.models_line({"reanchored": 0, "missing": []}) == ""
    assert models.models_line({"reanchored": 2, "missing": ["a.step"]}) == "2 re-anchored, 1 not found (a.step)"


def test_embedded_models_and_forms_kicad_finds_elsewhere_are_left_as_found(tmp_path):
    project = _tree(tmp_path)
    for text in ("kicad-embed://USB_C.step", ":MYLIB:r.step", "Resistor_SMD.3dshapes/R_0402.wrl"):
        assert models.reanchor(text, project) == (None, True), text


def test_the_parenthesised_variable_is_the_same_variable(tmp_path):
    project = _tree(tmp_path)
    assert models.reanchor("$(KIPRJMOD)/../parts/p/f.step", project) == \
        ("${KIPRJMOD}/../../../../../parts/p/f.step", True)


def test_only_the_leading_parent_steps_are_dropped(tmp_path):
    project = _tree(tmp_path)
    (tmp_path / "lib" / "parts" / "p").mkdir(parents=True)
    (tmp_path / "lib" / "parts" / "p" / "f.step").write_text("")
    # lib/../parts/p/f.step is parts/p/f.step, not lib/parts/p/f.step
    assert models.reanchor("${KIPRJMOD}/../lib/../parts/p/f.step", project) == \
        ("${KIPRJMOD}/../../../../../parts/p/f.step", True)


def test_a_bare_file_name_is_not_searched_for(tmp_path):
    project = _tree(tmp_path)
    (tmp_path / "f.step").write_text("")
    assert models.reanchor("${KIPRJMOD}/../f.step", project) == (None, False)
