"""The plan as JSON, from the model preview.py draws."""
import json
import xml.etree.ElementTree as ET

from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.preview import draw
from placemat.preview_json import declared_sites, item_json, plan_json
from placemat.values import CopperLayer, Face, LinkWeight, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("K1", 13, 10, w=16, h=17, inst="k1", nets=("K1A", "K1B")),
           footprint("U1", 50, 10, w=6, h=6, inst="u1", nets=("A", "B")),
           footprint("R1", 40, 15, w=2, h=1, inst="r1", nets=("B", "C"), face=Face.BACK),
           footprint("BIG", 30, 30, w=80, h=80, inst="big", nets=("D", "E"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5, keep_going=True)
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("k1"), at=Location(13, 10))
    b.place(Part("u1"))
    b.place(Part("r1"), face=Face.BACK)
    b.place(Part("big"))
    b.keepout(Circle(2.0), "clear", at=Location(30, 3), why="a clearance")
    b.link(PadRef(Part("u1"), 2), PadRef(Part("r1"), 1), weight=LinkWeight.SHORT, limit_mm=50.0)
    b.link(PadRef(Part("u1"), 1), PadRef(Part("j1"), 1), limit_mm=1.0)
    b.track(Net("A"), [PadRef(Part("j1"), 1), (6.0, 18.0)], layer=CopperLayer.F)
    b.via(Net("A"), (6.0, 18.0))
    return b


def _plan():
    b = _board()
    return b, b.resolve()


def _cls(root, name):
    return [e for e in root.iter() if name in (e.get("class") or "").split()]


def test_it_is_plain_json_and_the_same_every_time():
    b, plan = _plan()
    text = json.dumps(plan_json(plan, declared_sites(b)), sort_keys=True)
    b2, plan2 = _plan()
    assert json.dumps(plan_json(plan2, declared_sites(b2)), sort_keys=True) == text
    assert json.loads(text)["version"] == 1


def test_the_shapes_are_those_the_drawing_has():
    b, plan = _plan()
    doc = plan_json(plan, declared_sites(b))
    root = ET.fromstring(draw(plan))
    for face in ("front", "back"):
        g = _cls(root, face)[0]
        shapes = [s for item in doc["items"] for m in item["members"] for s in m["shapes"] if face in s["faces"]]
        assert len([s for s in shapes if s["kind"] in ("pad", "through")]) == len(_cls(g, "pad"))
        assert len([s for s in shapes if s["kind"] == "courtyard"]) == len(_cls(g, "courtyard"))
        assert len([s for s in shapes if s["kind"] == "body"]) == len(_cls(g, "body"))
        assert len([s for s in shapes if s["kind"] == "silk"]) == len(_cls(g, "silk"))
    drawn = [[c for c in e.get("class").split() if c in ("ok", "over", "free")][0] for e in _cls(_cls(root, "front")[0], "link") if e.tag.endswith("line")]
    assert [l["state"] for l in doc["links"]] == drawn
    assert [k["name"] for k in doc["keepouts"]] == ["clear"]
    assert doc["pocketed"] == list(plan.pocketed)
    assert [u["item"] for u in doc["unplaced"]] == ["big"]
    assert doc["findings"] and all("text" in f for f in doc["findings"])


def test_an_item_carries_what_the_page_shows_for_it():
    b, plan = _plan()
    doc = plan_json(plan, declared_sites(b))
    items = {i["key"]: i for i in doc["items"]}
    assert set(items) == {"j1", "k1", "u1", "r1"}
    j1, r1 = items["j1"], items["r1"]
    assert j1["at"] == [3.0, 10.0] and j1["face"] == "front" and j1["freedom"] == "fixed"
    assert r1["face"] == "back"
    assert j1["file"].endswith("test_preview_json.py") and j1["line"] > 0
    assert items["u1"]["line"] == j1["line"] + 2
    assert items["u1"]["note"] and items["u1"]["how"] == "pocket" and items["j1"]["how"] == "decided"
    pads = [s for s in j1["members"][0]["shapes"] if s["kind"] == "pad"]
    assert {p["net"] for p in pads} == {"A", "GND"} and {p["number"] for p in pads} == {"1", "2"}


def test_copper_links_and_the_steps_are_in_it():
    b, plan = _plan()
    doc = plan_json(plan, declared_sites(b))
    kinds = sorted(c["t"] for c in doc["copper"])
    assert "via" in kinds and "track" in kinds
    assert [s["item"] for s in doc["steps"]] == [s.item for s in plan.steps]
    assert doc["counts"]["placed"] == sum(1 for s in plan.steps if s.placement is not None)
    assert doc["congestion"] is None or "worst" in doc["congestion"]
    assert doc["board"]["loops"] and len(doc["board"]["extent"]) == 4


def test_a_streamed_step_is_the_same_item_the_final_plan_has():
    b = _board()
    streamed = {}
    plan = b.resolve(on_step=lambda p, s: streamed.__setitem__(s.item, item_json(p, s, declared_sites(b))))
    final = {i["key"]: i for i in plan_json(plan, declared_sites(b))["items"]}
    for key, item in streamed.items():
        if key in final:
            assert item["at"] == final[key]["at"] and item["members"][0]["shapes"] == final[key]["members"][0]["shapes"]


def test_an_unplaced_step_has_no_shapes():
    b = _board()
    seen = {}
    b.resolve(on_step=lambda p, s: seen.__setitem__(s.item, item_json(p, s, declared_sites(b))))
    assert seen["big"]["placed"] is False and seen["big"]["members"] == [] and seen["big"]["at"] is None
