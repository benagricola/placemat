"""The plan as JSON, from the model preview.py draws."""
import json
import xml.etree.ElementTree as ET

from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.preview import draw
from placemat.preview_json import declared_sites, finding_targets, item_json, plan_json
from placemat.values import Centre, CopperLayer, Cutout, Face, LinkWeight, Location, Net, PadRef, Part
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


def test_the_page_gets_a_keepouts_terms_a_links_kind_a_vias_layers_and_the_boards_copper_layers():
    b, plan = _plan()
    doc = plan_json(plan, declared_sites(b))
    k = doc["keepouts"][0]
    assert k["why"] == "a clearance" and k["layers"] is None and "tracks" in k["excludes"] and k["allow"] == []
    assert [l["kind"] for l in doc["links"]] == ["SHORT", "DEFAULT"] and [l["weight"] for l in doc["links"]] == [8, 1]
    via = [c for c in doc["copper"] if c["t"] == "via"][0]
    assert via["layers"] == []                          # a through via spans every layer
    assert doc["layers"][0] == "F.Cu" and doc["layers"][-1] == "B.Cu"


def test_a_keepouts_step_places_no_part_so_it_has_no_shapes_to_draw():
    b, plan = _plan()
    doc = plan_json(plan, declared_sites(b))
    drawn = [i["key"] for i in doc["items"] if any(m["shapes"] for m in i["members"])]
    assert "clear" not in drawn and set(drawn) == {"j1", "k1", "u1", "r1"}
    assert any(s["kind"] == "keepout" for s in doc["steps"])


def test_silk_text_carries_its_justification_rotation_and_mirroring():
    from placemat.copper import Text
    b, plan = _plan()
    plan.copper.append(Text("TOP", Location(5, 5), Face.BACK, 0.8, 0.12, 90.0, "left", "bottom", mirrored=True))
    t = [c for c in plan_json(plan, declared_sites(b))["copper"] if c["t"] == "text"][-1]
    assert (t["rotation"], t["hjust"], t["vjust"], t["mirrored"], t["thickness"], t["face"]) == (90.0, "left", "bottom", True, 0.12, "back")


def test_a_finding_names_the_parts_and_pads_its_sentence_mentions():
    refs = {"U1", "U10", "R1", "J1"}
    assert finding_targets("link R1.1 to U10.14 is 5.75 mm, over its 2.00 mm limit", refs) == (["R1", "U10"], [["R1", "1"], ["U10", "14"]])
    assert finding_targets("U1 pins 4/5: J1 SCL crosses U10 ALS_INT", refs) == (["U1", "J1", "U10"], [["U1", "4"], ["U1", "5"]])
    assert finding_targets("U1 pin 15 (RAIL): closed toward J1 by R1, U1", refs) == (["U1", "J1", "R1"], [["U1", "15"]])
    assert finding_targets("a cell XU1 and U11 and SU1", refs) == ([], [])             # only whole refs


def test_the_plan_gives_each_finding_its_refs_and_pads():
    b, plan = _plan()
    doc = plan_json(plan, declared_sites(b))
    assert all(isinstance(f["refs"], list) and isinstance(f["pads"], list) for f in doc["findings"])


def test_a_copper_step_says_which_of_the_documents_copper_it_laid_and_a_cutout_step_which_loop_it_cut():
    b = _board()
    b.size(width=60.0, height=20.0, holes=[Cutout(Circle(1.0), "vent", at=Centre(40.0, 4.0), why="air")])
    plan = b.resolve()
    doc = plan_json(plan, declared_sites(b))
    steps = {s["item"]: s for s in doc["steps"]}
    laid = [i for s in doc["steps"] if s["kind"] == "copper" for i in s["copper"]]
    assert laid and all(0 <= i < len(doc["copper"]) for i in laid) and len(laid) == len(set(laid))
    kinds = {doc["copper"][i]["t"] for i in laid}
    assert "track" in kinds and "via" in kinds
    cut = next(s for s in doc["steps"] if s["kind"] == "cutout")
    assert cut["loop"] is not None and len(doc["board"]["loops"][cut["loop"]]) > 4
    assert all(s["loop"] is None for s in doc["steps"] if s["kind"] != "cutout")


def test_a_footprints_own_copper_graphics_are_in_its_shapes_with_their_layer():
    import dataclasses
    from placemat.values import CopperLayer
    fps = [footprint("K1", 13, 10, w=6, h=6, inst="k1", nets=("A", "B"))]
    fps[0] = dataclasses.replace(fps[0], copper=((CopperLayer.F, ((12.0, 9.0), (14.0, 9.0), (14.0, 9.2), (12.0, 9.2))),
                                                 (CopperLayer.B, ((12.0, 11.0), (14.0, 11.0), (14.0, 11.2), (12.0, 11.2)))))
    b = Board(board_geometry(fps, width=30, height=20), edge_margin=0.5, keep_going=True)
    b.place(Part("k1"), at=Location(13, 10))
    plan = b.resolve()
    doc = plan_json(plan, declared_sites(b))
    shapes = [s for it in doc["items"] for m in it["members"] for s in m["shapes"] if s["kind"] == "copper"]
    assert sorted(s["layers"][0] for s in shapes) == ["B.Cu", "F.Cu"]
    assert all(s["faces"] and len(s["poly"]) == 4 for s in shapes)


def test_copper_and_cutout_steps_are_told_to_on_step_as_they_settle_with_what_they_draw():
    from placemat.preview_json import step_extras
    b = _board()
    b.size(width=60.0, height=20.0, holes=[Cutout(Circle(1.0), "vent", at=Centre(40.0, 4.0), why="air")])
    seen = []
    b.resolve(on_step=lambda p, s: seen.append((s.kind, s.item, step_extras(p, s))))
    kinds = [k for k, _, _ in seen]
    assert "cutout" in kinds and "copper" in kinds
    cu = [e for k, _, e in seen if k == "copper" and e["ops"]]
    assert cu and {op["t"] for e in cu for op in e["ops"]} >= {"track", "via"}
    cut = next(e for k, _, e in seen if k == "cutout")
    assert cut["cutout"] and len(cut["cutout"]) > 4


def test_the_engine_tells_on_begin_the_queue_each_item_it_starts_and_what_a_long_step_is_doing():
    b = _board()
    seen = []
    plan = b.resolve(on_begin=lambda p, info: seen.append(("begin", info)), on_step=lambda p, s: seen.append(("step", s.item)))
    assert seen[0][1]["kind"] == "total" and seen[0][1]["items"] >= 5 and seen[0][1]["searched"] >= 1
    begins = [i for k, i in seen if k == "begin" and i["kind"] == "begin"]
    searched = [i for i in begins if i["what"] == "searched"]
    assert searched and all(i["rank"] and i["of"] >= i["rank"] for i in searched)
    assert {"decided", "copper"} <= {i["what"] for i in begins}
    phases = [i["text"] for k, i in seen if k == "begin" and i["kind"] == "phase"]
    assert any(x.startswith("scanning") for x in phases) and any(x.startswith("seeding") for x in phases)
    hint = next(i for k, i in seen if k == "begin" and i.get("hint"))
    assert len(hint["hint"]) == 2
    order = [(k, i["item"] if k == "begin" else i) for k, i in seen if k == "step" or (k == "begin" and i["kind"] == "begin")]
    for n, (k, item) in enumerate(order):
        if k == "step" and item in {b_["item"] for b_ in begins if b_["what"] in ("searched", "decided")}:
            assert ("begin", item) in order[:n]                         # a placement is announced before it settles
    plain = _board().resolve()
    assert [s.item for s in plain.steps] == [s.item for s in plan.steps]
    assert [(s.item, s.placement) for s in plain.steps] == [(s.item, s.placement) for s in plan.steps]
