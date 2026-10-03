"""The case table, the source and api.md agree; nothing a suggestion writes is a coordinate."""
import ast
import inspect
import re
from pathlib import Path

import placemat
from placemat import suggestions as sg
from placemat.layout import Board
from placemat.settings import Settings

SRC = Path(__file__).resolve().parents[1] / "src" / "placemat"
API = Path(__file__).resolve().parents[1] / "skills" / "placemat" / "references" / "api.md"


def raised_cases() -> set:
    """Every case id the source raises: `case="..."` on a Finding, or the case argument of `self._finding(kind, case, ...)`."""
    found = set()
    for path in SRC.glob("*.py"):
        text = path.read_text()
        found |= set(re.findall(r'case="([a-z_]+(?:\.[a-z_]+)?)"', text))
        found |= set(re.findall(r'_finding\(\s*"[a-z_]+",\s*"([a-z_]+(?:\.[a-z_]+)?)"', text))
        found |= set(re.findall(r'_label_finding\(\s*"([a-z_]+\.[a-z_]+)"', text))
    return found - {"unplaced.search"} | {"unplaced.search"}


def test_every_case_raised_in_the_source_has_a_builder_and_every_builder_is_raised():
    raised = raised_cases()
    assert raised, "the scan found no case"
    assert raised == set(sg.CASES), {"raised, no builder": raised - set(sg.CASES), "builder, never raised": set(sg.CASES) - raised}


def test_every_case_is_in_the_api_table_and_the_table_names_no_other():
    text = API.read_text()
    section = text.split("### Suggestions", 1)[1].split("\n## ", 1)[0]
    rows = [l for l in section.splitlines() if l.startswith("| `")]
    named = {c for l in rows for c in re.findall(r"`([a-z_]+(?:\.[a-z_]+)?)`", l.split("|")[1])}
    assert named == set(sg.CASES), {"in api.md only": named - set(sg.CASES), "built, not in api.md": set(sg.CASES) - named}


def test_a_finding_s_case_is_its_kind_and_a_case_of_that_kind():
    from placemat.findings import KINDS
    for case in sg.CASES:
        assert case.split(".")[0] in KINDS, case


def _strings(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def test_no_builder_writes_a_coordinate_a_figure_or_a_plane():
    """An edit writes relations, keywords and settings: not a Location, a Centre, a coordinate pair, `reach=` with a
    number, `board.figure`, or `board.plane`."""
    tree = ast.parse((SRC / "suggestions.py").read_text())
    banned = {"Location", "Centre", "Pin", "Figure", "board.figure", "board.plane", "Polar", "Mid"}
    used = {s for s in _strings(tree)} & banned
    assert not used, used
    for node in ast.walk(tree):         # `reach=` is a keyword a suggestion never sets (a distance standing in for a fact)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_set" and len(node.args) > 2:
            assert not (isinstance(node.args[2], ast.Constant) and node.args[2].value == "reach")


SEARCH = {"item": "c4", "kind": "part", "face": "front", "priority": "", "step": 0.2, "radius": 3.0, "dominant": "reservation",
          "turns": 1, "free_sides": {"c1": ["NORTH", "EAST"]}, "drawn": True, "envelope": "physical", "via": True,
          "via_move": 0.5, "via_leave": 1.0, "reservations": [{"keepout": "ant"}, {"label": "label j1 IN"}],
          "links": [{"own": "1", "partner": "u1", "pad": "2"}]}
LINK = {"a": {"key": "c1", "pad": "1"}, "b": {"key": "u1", "pad": "2"}, "link": "C1.1>U1.2", "achieved": 5.1, "limit": 4.0,
        "weight": 1, "a_searched": True, "free_sides": ["NORTH", "EAST"]}
LABEL = {"key": "label j1 IN", "side": "NORTH", "sides": ["SOUTH", "EAST"], "size": 1.0}
TRACK = {"key": "track SIG", "net": "SIG", "word": "track", "layer": "F", "waypoints": 2, "chamfer_hit": True, "chamfer": 0.3,
         "arc_hit": True, "radius": 0.5, "cause": "arc"}
ESCAPE = {"part": "u1", "pin": "3", "side": "NORTH", "reach": 5.0}
FACTS = {
    "unplaced.search": SEARCH, "unplaced.pocket": SEARCH, "unplaced.slide": dict(SEARCH, edge="NORTH"),
    "unplaced.block": dict(SEARCH, gap_reach=2.0), "unplaced.bearing": dict(SEARCH, bearing_step=5.0), "unplaced.rides": SEARCH,
    "fixed.part": SEARCH, "fixed.cutout": {}, "fixed.keepout": {},
    "link_over": LINK, "label.sits_on": LABEL, "label.no_spot": LABEL, "label.not_drawn": LABEL,
    "copper.keepout": {"net": "SIG", "keepout": "ant", "word": "track", "layer": "F", "layer_word": "front",
                       "excluded": "tracks", "excludes": ["parts", "tracks"], "keepout_layers": ["F", "B"]},
    "copper.cross": {"yielder": "track SIG", "yielder_net": "SIG", "other_net": "GND", "other_bridge": True},
    "copper.meets": TRACK, "copper.not_drawn": TRACK, "copper.corner": TRACK, "copper.note": TRACK,
    "escape_walled": ESCAPE, "escape_closed": ESCAPE, "escape_crossed": ESCAPE, "escape_lane": ESCAPE, "pair_crossed": {},
    "setup.undeclared": {"item": "c9", "anchor": "c1"}, "setup.lane_unused": ESCAPE, "setup.accept": {"key": "keep-out SIG"},
    "vias.dropped": {"item": "c4", "via_move": 0.5, "via_leave": 1.0},
}


def test_every_case_has_facts_in_this_table():
    assert set(FACTS) == set(sg.CASES)


def test_every_keyword_a_builder_sets_is_a_parameter_of_the_board_method_it_edits_and_every_enum_exists():
    settings = Settings()
    seen = 0
    for case, builder in sg.CASES.items():
        for pick in builder(dict(FACTS[case], case=case), settings) or ():
            e = pick.edit
            if e.op in ("set_kwarg", "edit_list", "remove_kwarg") and e.target is not None:
                method = getattr(Board, e.target.kind)
                params = inspect.signature(method).parameters
                name = e.args.get("name") or e.args.get("arg")
                assert name in params, (case, e.target.kind, name)
                seen += 1
            for enum in _enums(e.value):
                first, *rest = enum.split(".")
                obj = getattr(placemat, first)
                for r in rest:
                    obj = getattr(obj, r)
            if e.op == "toml_set":
                key = "%s_%s" % (e.args["section"], e.args["key"])
                assert key in Settings.keys(), (case, key)
    assert seen > 20


def _enums(value):
    if isinstance(value, dict):
        if "enum" in value:
            yield value["enum"]
        for v in value.values():
            yield from _enums(v)
    elif isinstance(value, list):
        for v in value:
            yield from _enums(v)


def test_a_number_a_builder_writes_into_a_call_is_a_named_constant():
    """A set_kwarg value is a form, an enum, an item, a string, a bool, a list of angles or a constant: a bare number
    never stands alone as a keyword's value."""
    for case, builder in sg.CASES.items():
        for pick in builder(dict(FACTS[case], case=case), Settings()) or ():
            e = pick.edit
            if e.op != "set_kwarg":
                continue
            assert isinstance(e.value, (bool, dict)), (case, pick.text)
            assert not (isinstance(e.value, dict) and "num" in e.value), (case, pick.text)


def test_the_suggestions_per_lever_setting_caps_a_lever():
    from dataclasses import replace
    one = replace(Settings(), studio_suggestions_per_lever=1)
    many = sg.suggest("unplaced.search", dict(SEARCH, free_sides={"c1": ["NORTH", "EAST", "SOUTH", "WEST"]}), Settings())
    capped = sg.suggest("unplaced.search", dict(SEARCH, free_sides={"c1": ["NORTH", "EAST", "SOUTH", "WEST"]}), one)
    assert len([s for s in many if s.lever == "beside"]) == 3
    assert len([s for s in capped if s.lever == "beside"]) == 1
    assert [s.rank for s in many] == list(range(1, len(many) + 1))
