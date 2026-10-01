"""A script names its board by sitting beside the .zen that declares it."""
import json
from pathlib import Path

import pytest

from placemat.project import BoardSource, fab_min_findings, find_board, fab_profile


def test_the_zen_beside_the_script_declares_the_board(tmp_path):
    (tmp_path / "widget.zen").write_text(
        'X = Module("parts/X.zen")\nBoard(\n    name = "Widget",\n    layout_path = "layout/Widget",\n    layers = 2,\n)\n')
    (tmp_path / "Widget_layout.py").write_text("")
    src = find_board(tmp_path / "Widget_layout.py")
    assert src == BoardSource(name="Widget", zen=tmp_path / "widget.zen", layout_dir=tmp_path / "layout/Widget",
                              board_dir=tmp_path)


def test_a_directory_without_a_board_zen_is_an_error(tmp_path):
    (tmp_path / "not_a_board.zen").write_text("X = Module('x')\n")
    (tmp_path / "s.py").write_text("")
    with pytest.raises(FileNotFoundError):
        find_board(tmp_path / "s.py")


def test_the_fab_profile_is_found_walking_up_and_has_defaults(tmp_path):
    board = tmp_path / "boards" / "w"
    board.mkdir(parents=True)
    (tmp_path / "fab-profile.json").write_text('{"via": {"default_drill_mm": 0.25, "default_size_mm": 0.5}}')
    fab = fab_profile(board)
    assert fab.via_drill == 0.25 and fab.via_size == 0.5
    assert fab.courtyard_excess == 0.10                     # default when the file does not say
    assert fab_profile(Path("/")).via_drill == 0.3          # no file at all: defaults


def test_a_module_fragment_declares_its_layout_with_layout(tmp_path):
    """A module's .zen carries Layout(name=, path=) instead of Board(); its
    fragment is generated and scripted the same way."""
    (tmp_path / "Hub.zen").write_text('conn = Module("x")\nLayout(name = "Hub", path = "layout")\n')
    (tmp_path / "Hub_layout.py").write_text("")
    src = find_board(tmp_path / "Hub_layout.py")
    assert src.name == "Hub" and src.layout_dir == tmp_path / "layout" and src.zen == tmp_path / "Hub.zen"


def test_a_directory_with_several_boards_picks_the_one_the_script_is_named_for(tmp_path):
    """rover/ holds the board and an encoder fragment; Rover_layout.py
    means the board called Rover, not the first .zen in the listing."""
    (tmp_path / "encoder.zen").write_text('Layout(name = "RoverEncoder", path = "layout/RoverEncoder")\n')
    (tmp_path / "rover.zen").write_text('Board(name = "Rover", layout_path = "layout/Rover")\n')
    (tmp_path / "Rover_layout.py").write_text("")
    (tmp_path / "RoverEncoder_layout.py").write_text("")
    assert find_board(tmp_path / "Rover_layout.py").name == "Rover"
    assert find_board(tmp_path / "RoverEncoder_layout.py").name == "RoverEncoder"
    (tmp_path / "other_layout.py").write_text("")
    with pytest.raises(FileNotFoundError):
        find_board(tmp_path / "other_layout.py")            # two boards, neither named by the script


def test_a_zen_may_declare_a_layout_per_variant_and_the_script_picks_by_name(tmp_path):
    (tmp_path / "KeyPad.zen").write_text(
        'style = config("style", str, default = "top")\n'
        'if style == "top":\n    Layout(name = "KeyPad", path = "layout")\n'
        'else:\n    Layout(name = "KeyPadSide", path = "layout_side")\n')
    side = tmp_path / "KeyPadSide_layout.py"
    side.write_text("# placemat generate: --config style=side\nfrom placemat import board\n")
    top = tmp_path / "KeyPad_layout.py"
    top.write_text("from placemat import board\n")
    s = find_board(side)
    assert s.name == "KeyPadSide" and s.layout_dir == tmp_path / "layout_side"
    assert s.generate_args == ("--config", "style=side")
    t = find_board(top)
    assert t.name == "KeyPad" and t.generate_args == ()


def test_a_board_declared_as_a_project_is_found(tmp_path):
    """Layout() is the stdlib's shim over Project(schematic=False), so a
    board that wants a generated schematic declares Project() itself."""
    (tmp_path / "gauge.zen").write_text('X = Module("x")\nProject(name = "Gauge", path = "layout/Gauge", schematic = True)\n')
    (tmp_path / "Gauge_layout.py").write_text("")
    src = find_board(tmp_path / "Gauge_layout.py")
    assert src.name == "Gauge" and src.layout_dir == tmp_path / "layout/Gauge"


def test_a_declaration_with_layout_turned_off_is_not_a_board(tmp_path):
    """A sub-circuit beside the board declares Project(..., layout = False):
    it has no layout of its own, so it is not a candidate."""
    (tmp_path / "Sub.zen").write_text('Project(name = "Sub circuit", path = "kicad", schematic = True, layout = False)\n')
    (tmp_path / "Other.zen").write_text('Project(name="Other", layout=False)\n')
    (tmp_path / "Main.zen").write_text('Board(name = "Main", layout_path = "layout")\n')
    assert find_board(tmp_path / "anything_layout.py").name == "Main"
    assert find_board(tmp_path).name == "Main"


def test_layout_turned_off_everywhere_says_so(tmp_path):
    (tmp_path / "Sub.zen").write_text('Project(name = "Sub", layout = False)\n')
    with pytest.raises(FileNotFoundError, match="layout = False"):
        find_board(tmp_path / "s.py")


# ------------------------------------------------------- via tiers and min

def test_via_tiers_read_the_new_string_form(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps(
        {"via": {"micro": "no", "blind": "if-needed", "buried": "no"}}))
    fab = fab_profile(tmp_path)
    assert fab.tier("micro") == "no" and fab.tier("blind") == "if-needed" and fab.tier("buried") == "no"
    assert fab.via_types == frozenset()          # no type is "yes"


def test_via_tiers_read_the_057_allow_booleans(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {"allow_blind": True, "allow_micro": False}}))
    fab = fab_profile(tmp_path)
    assert fab.tier("blind") == "yes" and fab.tier("micro") == "no" and fab.tier("buried") == "no"


def test_a_type_the_file_does_not_name_is_no(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {}}))
    fab = fab_profile(tmp_path)
    assert fab.tier("micro") == "no" and fab.tier("blind") == "no" and fab.tier("buried") == "no"


def test_min_is_read_and_defaults_to_empty(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps(
        {"min": {"track_mm": 0.09, "clearance_mm": 0.09, "drill_mm": 0.15, "annular_mm": 0.075, "via_size_mm": 0.25}}))
    fab = fab_profile(tmp_path)
    assert fab.min == {"track_mm": 0.09, "clearance_mm": 0.09, "drill_mm": 0.15, "annular_mm": 0.075, "via_size_mm": 0.25}
    assert fab_profile(Path("/")).min == {}


def test_new_style_profile_with_no_new_keys_digests_as_before(tmp_path):
    (tmp_path / "fab-profile.json").write_text(json.dumps({"via": {"micro": "no"}}))
    fab = fab_profile(tmp_path)
    old = fab_profile(Path("/"))
    assert fab.json() == old.json()        # a profile with no "yes" via and no min digests exactly as the default


# --------------------------------------------------------------- fab min findings

def test_a_net_class_below_the_fabs_minimum_is_a_fab_finding():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile
    fab = FabProfile(min={"track_mm": 0.12, "clearance_mm": 0.09, "drill_mm": 0.15,
                          "annular_mm": 0.075, "via_size_mm": 0.25})
    classes = {"A": NetClass("Default", 0.10, 0.2, 0.6, 0.3), "B": NetClass("Default", 0.10, 0.2, 0.6, 0.3)}
    findings = fab_min_findings(classes, fab)
    assert len(findings) == 1 and findings[0].kind == "fab"
    assert "track width" in findings[0] and "0.1" in findings[0] and "0.12" in findings[0]


def test_a_net_class_at_or_above_the_minimum_gets_no_finding():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile
    fab = FabProfile(min={"track_mm": 0.09})
    classes = {"A": NetClass("Default", 0.09, 0.2, 0.6, 0.3)}
    assert fab_min_findings(classes, fab) == []


def test_no_min_section_gives_no_findings():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile
    classes = {"A": NetClass("Default", 0.01, 0.01, 0.01, 0.01)}
    assert fab_min_findings(classes, FabProfile()) == []


def test_each_class_is_checked_once_not_per_net():
    from placemat.board_geometry import NetClass
    from placemat.project import FabProfile
    fab = FabProfile(min={"track_mm": 0.5})
    classes = {"A": NetClass("Thin", 0.1, 0.2, 0.6, 0.3), "B": NetClass("Thin", 0.1, 0.2, 0.6, 0.3)}
    assert len(fab_min_findings(classes, fab)) == 1
