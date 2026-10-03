"""The builder's page script: the selection logic that needs no page runs in node; the script is plain ASCII (served and read as UTF-8 or not,
it shows the same); its part and card have the Unplace action."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import placemat

JS = Path(placemat.__file__).with_name("studio_builder.js")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

ROWS = [{"key": "esd", "ref": "ESD", "status": "decided"}, {"key": "sink", "ref": "SINK", "status": "unplaced"},
        {"key": "src", "ref": "SRC", "status": "unplaced"}, {"key": "tcpc", "ref": "TCPC", "status": "searched"}]


def click(tmp_path, subj, chip, key, multi=False):
    text = JS.read_text()
    pure = text[:text.index("// ---- end of the part that needs no page")]
    f = tmp_path / "pure.js"
    f.write_text(pure + "\nconsole.log(JSON.stringify(BuilderPure.rowClick(%s, %s, %s, %s, %s)));\n" % (
        json.dumps(ROWS), json.dumps(subj), json.dumps(chip), json.dumps(key), json.dumps(multi)))
    done = subprocess.run(["node", str(f)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@needs_node
def test_a_placed_part_still_selected_is_the_target_when_another_item_is_ticked_and_part_is_chosen(tmp_path):
    # esd was just placed and stays selected; sink is ticked; Part is chosen; esd is clicked: it becomes the target and sink the subject
    ticked = click(tmp_path, ["esd"], "edge", "sink", multi=True)
    assert ticked["subj"] == ["sink"]                                   # a tick replaces the placed selection with the unplaced item
    got = click(tmp_path, ["sink", "esd"], "part", "esd")               # the reported state: both selected, Part chosen
    assert got == {"subj": ["sink"], "target": "esd", "say": ""}


@needs_node
def test_a_part_click_picks_a_placed_or_searched_target_and_refuses_an_unplaced_one_with_a_sentence(tmp_path):
    assert click(tmp_path, ["sink"], "part", "tcpc") == {"subj": ["sink"], "target": "tcpc", "say": ""}
    assert click(tmp_path, ["sink"], "pad", "esd")["target"] == "esd"
    got = click(tmp_path, ["sink"], "part", "src")
    assert got["target"] is None and got["subj"] == ["sink"] and "not placed yet" in got["say"]


@needs_node
def test_a_click_with_the_edge_chosen_selects_and_a_second_click_deselects(tmp_path):
    assert click(tmp_path, [], "edge", "sink") == {"subj": ["sink"], "target": None, "say": ""}
    assert click(tmp_path, ["sink"], "edge", "sink")["subj"] == []
    assert click(tmp_path, ["sink"], "edge", "src", multi=True)["subj"] == ["sink", "src"]


@needs_node
def test_the_only_selected_part_is_not_its_own_target(tmp_path):
    got = click(tmp_path, ["esd"], "part", "esd")
    assert got["target"] is None and got["subj"] == []


def test_the_script_is_plain_ascii_so_no_charset_can_garble_it():
    bad = [(n + 1, l) for n, l in enumerate(JS.read_text().splitlines()) if re.search(r"[^\x00-\x7f]", l)]
    assert bad == []


def test_a_placed_item_can_be_unplaced_from_the_list_the_card_and_the_edit_panel():
    text = JS.read_text()
    assert text.count("data-unplace") >= 2 and 'id="bld-cardun"' in text and 'id="bt-remove"' in text and "async function unplace" in text


def test_no_label_the_builder_shows_has_a_bracketed_explanation():
    literals = re.findall(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)\"""", JS.read_text())
    shown = []
    for a, b in literals:
        t = re.sub(r"<[^>]*>", " ", a or b)
        if re.search(r"\s\([A-Za-z][^()]*\)", t) and not re.search(r"[=;{}]", t) and " " in t:
            shown.append(t.strip())
    assert shown == []
