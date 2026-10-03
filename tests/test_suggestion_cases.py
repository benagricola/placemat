"""The case table, the source and api.md agree; nothing a suggestion writes is a coordinate."""
import ast
import inspect
import re
from pathlib import Path

import placemat
from placemat.findings import FindingCause, FindingCause as C
from placemat import suggestions as sg
from placemat.layout import Board
from placemat.settings import Settings

SRC = Path(__file__).resolve().parents[1] / "src" / "placemat"
API = Path(__file__).resolve().parents[1] / "skills" / "placemat" / "references" / "api.md"


def test_every_builder_is_of_a_cause_a_finding_can_have():
    assert set(sg.CASES) <= set(FindingCause)
    assert all(isinstance(c, FindingCause) for c in sg.CASES)


def test_every_cause_a_finding_is_made_with_in_the_source_is_a_FindingCause_member():
    """`Finding(...)`, `_finding(...)` and `ctx.note(...)` take a `C.X` or `FindingCause.X`, never a string."""
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("Finding", "_finding", "note") and node.args and path.name not in ("findings.py", "finding_text.py"):
                first = node.args[0]
                if isinstance(first, ast.Constant) or isinstance(first, ast.JoinedStr):
                    raise AssertionError("%s:%d makes a finding from %r" % (path.name, node.lineno, getattr(first, "value", "text")))


def test_every_case_is_in_the_api_table_and_the_table_names_no_other():
    text = API.read_text()
    section = text.split("### Suggestions", 1)[1].split("\n## ", 1)[0]
    rows = [l for l in section.splitlines() if l.startswith("| `")]
    named = {c for l in rows for c in re.findall(r"`([a-z_]+(?:\.[a-z_]+)?)`", l.split("|")[1])}
    assert named == set(sg.CASES), {"in api.md only": named - set(sg.CASES), "built, not in api.md": set(sg.CASES) - named}


def test_a_cause_carries_its_kind():
    for cause in FindingCause:
        assert cause.value.split(".")[0] == cause.kind.value, cause


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


SEARCH = {"item": "c4", "kind": "part", "face": "front", "priority": "", "step": 0.2, "dominant": "reservation",
          "turns": 1, "free_sides": {"c1": ["NORTH", "EAST"]}, "drawn": True, "envelope": "physical", "via": True,
          "reservations": [{"keepout": "ant"}, {"label": "label j1 IN", "item": "j1"}],
          "links": [{"own": "1", "partner": "u1", "pad": "2"}]}
LINK = {"a": {"key": "c1", "pad": "1"}, "b": {"key": "u1", "pad": "2"}, "link": "C1.1>U1.2", "achieved_mm": 5.1,
        "limit_mm": 4.0, "weight": 1, "a_searched": True, "free_sides": ["NORTH", "EAST"]}
LABEL = {"key": "label j1 IN", "item": "j1", "side": "NORTH", "sides": ["SOUTH", "EAST"], "size": 1.0}
TRACK = {"key": "track SIG", "net": "SIG", "word": "track", "layer": "F", "waypoints": 2, "chamfer_hit": True, "chamfer_mm": 0.3,
         "arc_hit": True, "radius_mm": 0.5, "variant": "arc",
         "misfit": {"code": "arc_leg", "leg": [[0, 0], [1, 0]], "length_mm": 1.0,
                    "arcs": [{"radius_mm": 0.5, "at": [0, 0], "turn_deg": "90", "takes_mm": 0.5},
                             {"radius_mm": 0.5, "at": [1, 0], "turn_deg": "90", "takes_mm": 0.5}]}}
ESCAPE = {"part": "u1", "pin": "3", "side": "NORTH", "reach": 5.0}
FACTS = {
    C.UNPLACED_SEARCH: SEARCH, C.UNPLACED_POCKET: SEARCH, C.UNPLACED_SLIDE: dict(SEARCH, edge="NORTH"),
    C.UNPLACED_BLOCK: SEARCH, C.UNPLACED_BEARING: SEARCH, C.UNPLACED_RIDES: SEARCH,
    C.FIXED_PART: dict(SEARCH, row={"first": "c1", "index": 1}, centre={"intent": True},
                       block={"anchor": "u1", "satellites": ["c1"]}, why={"code": "block_no_spot", "sat": "c1"}),
    C.FIXED_CUTOUT: {"name": "slot", "outline_kind": "rect", "why": {"code": "cutout_web", "gap_mm": 0.9, "web_mm": 1.0}},
    C.SETUP_FRAME_REACH: {"item": "c1", "from_mm": 1.0, "to_mm": 42.1, "axis": "width", "frame_from_mm": 0.0, "frame_to_mm": 30.0},
    C.SETUP_WEB: {"cutout": "slot", "gap_mm": 0.9, "web_mm": 1.0, "outline_kind": "rect"}, C.FIXED_KEEPOUT: {},
    C.FIXED_ROOM: {"item": "c1", "copper": "track SIG", "net": "SIG", "side": "north", "reach_mm": 2.0},
    C.FIXED_ROOM_UNSETTLED: {"copper": "track SIG", "moved_mm": 0.2, "passes": 4},
    C.LINK_OVER: LINK, C.LABEL_SITS_ON: LABEL, C.LABEL_NO_SPOT: LABEL, C.LABEL_NOT_DRAWN: LABEL,
    C.COPPER_KEEPOUT: {"net": "SIG", "keepout": "ant", "word": "track", "layer": "F", "layer_word": "front",
                       "excluded": "tracks", "excludes": ["parts", "tracks"], "keepout_layers": ["F", "B"]},
    C.COPPER_STITCH: {}, C.COPPER_CROSS: {"yielder": "track SIG", "yielder_net": "SIG", "other_net": "GND", "other_bridge": True},
    C.COPPER_MEETS: TRACK, C.COPPER_NOT_DRAWN: TRACK, C.COPPER_CORNER: TRACK, C.COPPER_NOTE: dict(TRACK, variant="waypoint"),
    C.ESCAPE_WALLED: ESCAPE, C.ESCAPE_CLOSED: ESCAPE, C.ESCAPE_CROSSED: ESCAPE, C.ESCAPE_LANE: ESCAPE, C.PAIR_CROSSED: {},
    C.SETUP_CENTRE_COORDINATES: {"item": "c9", "relation": {"item": "c1", "side": "NORTH"}}, C.SETUP_CENTRE_FLAG_DEFAULT: {"item": "c9"},
    C.SETUP_UNDECLARED: {"item": "c9", "anchor": "c1"}, C.SETUP_LANE_UNUSED: ESCAPE, C.SETUP_ACCEPT: {"key": "keep-out SIG"},
    C.VIAS_DROPPED: {"item": "c4"},
}


def test_every_case_has_facts_in_this_table():
    assert set(FACTS) == set(sg.CASES)


def test_every_keyword_a_builder_sets_is_a_parameter_of_the_board_method_it_edits_and_every_enum_exists():
    settings = Settings()
    seen = 0
    for case, builder in sg.CASES.items():
        for pick in builder(FACTS[case], settings) or ():
            e = pick.edits[0]
            if e.op in ("set_kwarg", "edit_list", "remove_kwarg") and e.target is not None and e.args.get("into"):
                assert e.args["name"] in {"coordinates", "gap", "across", "at"}, (case, e.args)       # a keyword of an inner call
                seen += 1
            elif e.op in ("set_kwarg", "edit_list", "remove_kwarg") and e.target is not None:
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
        for pick in builder(FACTS[case], Settings()) or ():
            e = pick.edits[0]
            if e.op != "set_kwarg":
                continue
            assert isinstance(e.value, (bool, dict)), (case, pick.text)
            assert not (isinstance(e.value, dict) and "num" in e.value), (case, pick.text)


def test_the_suggestions_per_lever_setting_caps_a_lever():
    from dataclasses import replace
    one = replace(Settings(), studio_suggestions_per_lever=1)
    many = sg.suggest(C.UNPLACED_SEARCH, dict(SEARCH, free_sides={"c1": ["NORTH", "EAST", "SOUTH", "WEST"]}), Settings())
    capped = sg.suggest(C.UNPLACED_SEARCH, dict(SEARCH, free_sides={"c1": ["NORTH", "EAST", "SOUTH", "WEST"]}), one)
    assert len([s for s in many if s.lever == "beside"]) == 3
    assert len([s for s in capped if s.lever == "beside"]) == 1
    assert [s.rank for s in many] == list(range(1, len(many) + 1))
