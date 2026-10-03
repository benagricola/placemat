"""The .zen dialect of the splicing editor (zen_edit.py): a stackup and pair net classes in `Board(config=)`, as minimal splices of
the file's own text, byte for byte."""
import pytest

from placemat import script_edit as se, zen_edit as ze

HEADER = '# A demo board.\nload("@stdlib/board_config.zen", "BoardConfig")\nR = Module("@stdlib/generics/Resistor.zen")\n'
PLAIN = HEADER + '''gnd = io("GND", Net)

Board(
    name = "Demo",
    layout_path = "layout/Demo",
    layers = 4,
)
'''

ROWS = [
    {"kind": "copper", "thickness_mm": 0.035, "role": "signal", "oz": 1},
    {"kind": "dielectric", "thickness_mm": 0.2, "form": "prepreg"},
    {"kind": "copper", "thickness_mm": 0.0175, "role": "power", "oz": 0.5},
    {"kind": "dielectric", "thickness_mm": 1.065, "form": "core"},
    {"kind": "copper", "thickness_mm": 0.0175, "role": "power", "oz": 0.5},
    {"kind": "dielectric", "thickness_mm": 0.2, "form": "prepreg"},
    {"kind": "copper", "thickness_mm": 0.035, "role": "signal", "oz": 1},
]


def test_a_board_with_no_config_gets_its_stackup_in_place_and_the_load_names_it_needs():
    out = ze.stackup_edit(PLAIN, "Demo", ROWS)
    assert out == HEADER.replace('"BoardConfig")', '"BoardConfig", "Stackup", "CopperLayer", "DielectricLayer")') + '''gnd = io("GND", Net)

Board(
    name = "Demo",
    layout_path = "layout/Demo",
    layers = 4,
    config = BoardConfig(stackup = Stackup(layers = [
        CopperLayer(thickness = 0.035, role = "signal"),  # 1 oz
        DielectricLayer(thickness = 0.2, form = "prepreg"),  # chosen in the studio's board builder
        CopperLayer(thickness = 0.0175, role = "power"),  # 0.5 oz
        DielectricLayer(thickness = 1.065, form = "core"),  # chosen in the studio's board builder
        CopperLayer(thickness = 0.0175, role = "power"),  # 0.5 oz
        DielectricLayer(thickness = 0.2, form = "prepreg"),  # chosen in the studio's board builder
        CopperLayer(thickness = 0.035, role = "signal"),  # 1 oz
    ])),
)
'''
    assert ze.read_stackup(out, "Demo")[2] == {"kind": "copper", "thickness_mm": 0.0175, "role": "power", "oz": 0.5}


def test_a_thickness_without_an_oz_says_it_was_chosen_in_the_builder():
    rows = [dict(ROWS[0], oz=None), ROWS[1], dict(ROWS[6], oz=None)]
    out = ze.stackup_edit(PLAIN, "Demo", rows, copper_layers=2)
    assert '    layers = 2,\n' in out
    assert 'CopperLayer(thickness = 0.035, role = "signal"),  # chosen in the studio' in out


def test_an_edit_that_changes_one_layer_leaves_every_other_byte():
    once = ze.stackup_edit(PLAIN, "Demo", ROWS)
    rows = [dict(r) for r in ROWS]
    rows[2].update(thickness_mm=0.035, oz=1)
    out = ze.stackup_edit(once, "Demo", rows)
    assert out == once.replace('CopperLayer(thickness = 0.0175, role = "power"),  # 0.5 oz\n        DielectricLayer(thickness = 1.065',
                               'CopperLayer(thickness = 0.035, role = "power"),  # 1 oz\n        DielectricLayer(thickness = 1.065')
    assert ze.stackup_edit(out, "Demo", rows) == out


def test_a_layer_keeps_its_material_and_its_comment_when_it_is_not_changed():
    text = PLAIN.replace('    layers = 4,\n', '''    layers = 2,
    config = BoardConfig(stackup = Stackup(thickness = 1.6, layers = [
        CopperLayer(thickness = 0.035, role = "signal"),  # outer, mine
        DielectricLayer(thickness = 1.5, material = "FR4", form = "core"),
        CopperLayer(thickness = 0.035, role = "signal"),
    ])),
''')
    rows = [ROWS[0], {"kind": "dielectric", "thickness_mm": 1.4, "form": "core"}, ROWS[6]]
    out = ze.stackup_edit(text, "Demo", rows)
    assert 'CopperLayer(thickness = 0.035, role = "signal"),  # outer, mine' in out
    assert 'DielectricLayer(thickness = 1.4, form = "core", material = "FR4"),  # chosen in the studio' in out
    assert "Stackup(thickness = 1.6, layers" in out


def test_a_different_number_of_layers_rewrites_the_list():
    text = ze.stackup_edit(PLAIN, "Demo", ROWS)
    out = ze.stackup_edit(text, "Demo", [ROWS[0], ROWS[1], ROWS[6]])
    assert out.count("CopperLayer(") == 2 and "1.065" not in out and out.count("\n    ])),") == 1


def test_a_config_that_is_not_a_literal_call_is_refused_naming_it():
    text = PLAIN.replace("    layers = 4,\n", "    layers = 4,\n    config = CONFIG,\n")
    with pytest.raises(se.EditRefused, match="config= is CONFIG, not a literal BoardConfig"):
        ze.stackup_edit(text, "Demo", ROWS)
    text = PLAIN.replace("    layers = 4,\n", "    layers = 4,\n    config = BoardConfig(stackup = STACK),\n")
    with pytest.raises(se.EditRefused, match="stackup= is STACK"):
        ze.stackup_edit(text, "Demo", ROWS)


def test_the_board_must_be_found_once_and_a_file_that_does_not_parse_is_refused():
    with pytest.raises(se.EditRefused, match="no Board"):
        ze.stackup_edit(PLAIN, "Other", ROWS)
    with pytest.raises(se.EditRefused, match="twice|2 times"):
        ze.stackup_edit(PLAIN + 'Board(name = "Demo", layers = 2)\n', "Demo", ROWS)
    with pytest.raises(se.EditRefused, match="does not parse"):
        ze.stackup_edit("Board(name = \n", "Demo", ROWS)
    project = 'Project(name = "Demo")\n'
    with pytest.raises(se.EditRefused, match="Project"):
        ze.stackup_edit(project, "Demo", ROWS)


def test_a_file_that_writes_keywords_without_spaces_gets_them_that_way():
    text = 'Board(name="Demo", layers=2)\n'
    out = ze.stackup_edit(text, "Demo", [ROWS[0], ROWS[6]])
    assert out.startswith('load("@stdlib/board_config.zen", "BoardConfig", "Stackup", "CopperLayer")\n\nBoard(name="Demo", layers=2, config=BoardConfig(stackup=Stackup(layers=[\n')
    assert '    CopperLayer(thickness=0.035, role="signal"),  # 1 oz\n' in out


def test_validation_refuses_a_stackup_that_is_not_one():
    for rows, why in (([], "at least one"), ([{"kind": "copper", "thickness_mm": 0, "role": "signal"}], "positive"),
                      ([{"kind": "copper", "thickness_mm": 0.035, "role": "plane"}], "role"),
                      ([{"kind": "dielectric", "thickness_mm": 0.1, "form": "glue"}], "core or prepreg")):
        with pytest.raises(se.EditRefused, match=why):
            ze.stackup_edit(PLAIN, "Demo", rows)


# ------------------------------------------------------------------ pair classes
CLASSES = [{"name": "USB", "diff_pair_width": 0.2, "diff_pair_gap": 0.15, "nets": ["USB_P", "USB_N"]}]


def test_a_pair_class_is_added_with_its_design_rules_branch():
    out = ze.netclasses_edit(PLAIN, "Demo", CLASSES)
    assert out == HEADER.replace('"BoardConfig")', '"BoardConfig", "DesignRules", "NetClass")') + '''gnd = io("GND", Net)

Board(
    name = "Demo",
    layout_path = "layout/Demo",
    layers = 4,
    config = BoardConfig(design_rules = DesignRules(netclasses = [
        NetClass(
            name = "USB",
            diff_pair_width = 0.2,  # chosen in the studio's board builder
            diff_pair_gap = 0.15,  # chosen in the studio's board builder
            nets = ["USB_P", "USB_N"],
        ),
    ])),
)
'''
    assert ze.read_netclasses(out, "Demo") == CLASSES


EXISTING = HEADER + '''Board(
    name = "Demo",
    layers = 2,
    config = BoardConfig(design_rules = DesignRules(netclasses = [
        NetClass(name = "Power", track_width = 0.5),  # mine
        NetClass(name = "USB", diff_pair_width = 0.18, diff_pair_gap = 0.15, nets = ["USB_P", "USB_N"]),
        NetClass(name = "CAN", diff_pair_width = 0.2, diff_pair_gap = 0.2, nets = ["CAN_H", "CAN_L"]),
    ])),
)
'''


def test_pair_classes_are_set_removed_and_added_and_other_classes_are_left_alone():
    want = [{"name": "USB", "diff_pair_width": 0.2, "diff_pair_gap": 0.15, "nets": ["USB_P", "USB_N"]},
            {"name": "ETH", "diff_pair_width": 0.1, "diff_pair_gap": 0.1, "nets": ["ETH_P", "ETH_N"]}]
    out = ze.netclasses_edit(EXISTING, "Demo", want)
    assert 'NetClass(name = "Power", track_width = 0.5),  # mine' in out
    assert 'NetClass(name = "USB", diff_pair_width = 0.2, diff_pair_gap = 0.15, nets = ["USB_P", "USB_N"]),' in out
    assert "CAN" not in out and '"ETH_P", "ETH_N"' in out
    assert [c["name"] for c in ze.read_netclasses(out, "Demo")] == ["USB", "ETH"]
    assert ze.netclasses_edit(out, "Demo", want) == out


def test_no_pair_classes_removes_them_and_a_pair_needs_exactly_two_nets():
    out = ze.netclasses_edit(EXISTING, "Demo", [])
    assert ze.read_netclasses(out, "Demo") == []
    assert 'NetClass(name = "Power"' in out
    with pytest.raises(se.EditRefused, match="exactly its two nets"):
        ze.netclasses_edit(PLAIN, "Demo", [dict(CLASSES[0], nets=["A"])])
    with pytest.raises(se.EditRefused, match="positive"):
        ze.netclasses_edit(PLAIN, "Demo", [dict(CLASSES[0], diff_pair_gap=0)])


def test_missing_keys_of_a_kept_class_are_added():
    text = EXISTING.replace('NetClass(name = "USB", diff_pair_width = 0.18, diff_pair_gap = 0.15, nets = ["USB_P", "USB_N"])',
                            'NetClass(name = "USB", diff_pair_width = 0.18)')
    out = ze.netclasses_edit(text, "Demo", [{"name": "USB", "diff_pair_width": 0.18, "diff_pair_gap": 0.15, "nets": ["USB_P", "USB_N"]},
                                           {"name": "CAN", "diff_pair_width": 0.2, "diff_pair_gap": 0.2, "nets": ["CAN_H", "CAN_L"]}])
    assert 'NetClass(name = "USB", diff_pair_width = 0.18, diff_pair_gap = 0.15, nets = ["USB_P", "USB_N"]),' in out


def test_the_edit_is_an_op_of_apply_edits(tmp_path):
    from placemat.suggestions import Edit
    p = tmp_path / "demo.zen"
    p.write_text(PLAIN)
    e = Edit("zen_stackup", None, {"board": "Demo", "layers": ROWS, "copper_layers": 4}, None, {}, str(p))
    f = Edit("zen_netclasses", None, {"board": "Demo", "classes": CLASSES}, None, {}, str(p))
    done = se.apply_edits([e, f], lambda path: p.read_text())
    before, after = done[str(p)]
    assert before == PLAIN and ze.read_stackup(after, "Demo") is not None and ze.read_netclasses(after, "Demo") == CLASSES
    assert after.count('load("@stdlib/board_config.zen"') == 1


def test_the_stackup_state_says_how_the_zen_declares_it():
    assert ze.stackup_state(PLAIN, "Demo") == {"state": "none"}
    assert ze.stackup_state(ze.stackup_edit(PLAIN, "Demo", ROWS), "Demo") == {"state": "literal"}
    assert ze.stackup_state(PLAIN.replace("    layers = 4,\n", "    layers = 4,\n    config = CONFIG,\n"), "Demo") == {
        "state": "elsewhere", "why": "config= is CONFIG"}
    assert ze.stackup_state(PLAIN.replace("    layers = 4,\n", "    layers = 4,\n    config = BoardConfig(design_rules = RULES),\n"),
                            "Demo") == {"state": "none"}
    assert ze.stackup_state("Board(name = \n", "Demo")["state"] == "unreadable"
    assert ze.stackup_state(PLAIN, "Other")["state"] == "unreadable"
