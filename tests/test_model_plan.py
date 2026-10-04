"""The plan document's 3D fields: per member the model entries resolved with their matrices, the table of distinct models, the stackup; additive,
deterministic, and absent without a model context."""
import json
from dataclasses import replace

import pytest

from placemat import preview_json
from placemat.model_plan import ModelContext
from tests.fixtures import footprint
from tests.suggest_support import resolve

BOARD = '''(kicad_pcb (version 20240108) (general (thickness 1.2))
	(footprint "lib:E"
		(property "Reference" "C1"
		)
		(embedded_files
			(file
				(name "E.step")
				(type model)
				(checksum "ABCD0123")
			)
		)
	)
)
'''
BODY = 'board.place(Part("u1"), at=Location(10, 10))\nboard.place(Part("c1"), at=Location(30, 20))\nboard.place(Part("r1"), at=Location(30, 30), face=Face.BACK)\n'


def _parts(tmp_path):
    step = tmp_path / "lib" / "chip.step"
    step.parent.mkdir()
    step.write_bytes(b"step bytes")
    u1 = footprint("U1", 10, 10, w=6, h=2, inst="u1")
    c1 = replace(footprint("C1", 40, 40, inst="c1"), models=(("kicad-embed://E.step", (0, 0, 0), (0, 0, 0), (1, 1, 1), True, 1.0),))
    r1 = replace(footprint("R1", 40, 50, inst="r1"), models=((str(step), (0, 0, 0.1), (0, 0, 90), (1, 1, 1), True, 1.0),
                                                              ("${KIPRJMOD}/gone.step", (0, 0, 0), (0, 0, 0), (1, 1, 1), True, 1.0),
                                                              (str(step), (0, 0, 0), (0, 0, 0), (1, 1, 1), False, 1.0)))
    return [u1, c1, r1]


@pytest.fixture
def planned(tmp_path):
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(BOARD)
    board, plan, path = resolve(tmp_path, BODY, parts=_parts(tmp_path))
    return plan, ModelContext(pcb), tmp_path


def _items(doc):
    return {i["key"]: i for i in doc["items"]}


def test_each_member_carries_its_models_resolved_with_a_matrix_or_a_reason(planned):
    plan, ctx, tmp = planned
    doc = preview_json.plan_json(plan, {}, None, ctx)
    assert doc["version"] == 3
    ms = {m["ref"]: m for it in doc["items"] for m in it["members"]}
    assert ms["U1"]["models"] == [{"id": "", "state": "none", "name": "", "opacity": 1.0, "why": "no_model", "text": "", "matrix": None}]
    (emb,) = ms["C1"]["models"]
    assert emb["state"] == "ok" and emb["id"] == "e-abcd0123" and len(emb["matrix"]) == 16 and emb["name"] == "E.step"
    ok, gone, hidden = ms["R1"]["models"]
    assert ok["state"] == "ok" and len(ok["id"]) == 32 and len(ok["matrix"]) == 16
    assert gone["state"] == "missing" and gone["matrix"] is None and gone["why"] == "not_found" and gone["text"] == "${KIPRJMOD}/gone.step"
    from placemat import present
    assert present.model_why(gone) == "model not found: ${KIPRJMOD}/gone.step"
    assert hidden["state"] == "hidden" and hidden["matrix"] is None


def test_the_plan_has_the_table_of_distinct_models_and_the_stackup_from_the_board_file(planned):
    plan, ctx, tmp = planned
    doc = preview_json.plan_json(plan, {}, None, ctx)
    assert sorted(v["source"] for v in doc["models"].values()) == ["embedded", "file"] and set(doc["models"]) == {"e-abcd0123", next(k for k in doc["models"] if len(k) == 32)}
    assert doc["stackup"]["thickness"] == 1.2 and set(doc["stackup"]["copper"]) <= {"F.Cu", "B.Cu"}


def test_a_written_boards_footprint_carries_its_models_where_the_file_has_it(tmp_path):
    from placemat import model_place
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(BOARD)
    u1, c1, r1 = _parts(tmp_path)
    ctx = ModelContext(pcb)
    assert ctx.written(u1) == [{"id": "", "state": "none", "name": "", "opacity": 1.0, "why": "no_model", "text": "", "matrix": None}]
    (emb,) = ctx.written(c1)
    assert emb["id"] == "e-abcd0123" and emb["matrix"] == model_place.placement(c1.models[0], location=(40, 40), rotation=c1.rotation, face=c1.face.value, thickness=1.2)
    ok, gone, hidden = ctx.written(r1)
    assert len(ok["id"]) == 32 and ok["matrix"] == model_place.placement(r1.models[0], location=(40, 50), rotation=r1.rotation, face=r1.face.value, thickness=1.2)
    assert gone["matrix"] is None and hidden["matrix"] is None
    assert {j["id"] for j in ctx.new_jobs(set())} == {"e-abcd0123", ok["id"]}


def test_a_board_kept_away_from_its_project_resolves_its_models_from_the_project_folder(tmp_path):
    project, kept = tmp_path / "layout", tmp_path / "runs" / "r1"
    (project / "models").mkdir(parents=True)
    kept.mkdir(parents=True)
    (project / "models" / "m.step").write_bytes(b"step bytes")
    (kept / "x.kicad_pcb").write_text(BOARD)
    fp = replace(footprint("U1", 10, 10, inst="u1"), models=(("${KIPRJMOD}/models/m.step", (0, 0, 0), (0, 0, 0), (1, 1, 1), True, 1.0),))
    assert ModelContext(kept / "x.kicad_pcb").written(fp)[0]["state"] == "missing"
    (got,) = ModelContext(kept / "x.kicad_pcb", project_dir=project).written(fp)
    assert got["state"] == "ok" and got["matrix"] is not None


def test_a_part_the_plan_put_on_the_back_hangs_below_the_board(planned):
    plan, ctx, tmp = planned
    doc = preview_json.plan_json(plan, {}, None, ctx)
    m = next(mm for it in doc["items"] for mm in it["members"] if mm["ref"] == "R1")["models"][0]["matrix"]
    front, back = 1.2 - 0.005, -0.085
    assert m[13] == pytest.approx(back - 0.1)                    # the model's z offset 0.1 mm above the part's own face, which is the back plane now


def test_without_a_context_the_document_has_none_of_it_and_it_is_deterministic(planned):
    plan, ctx, tmp = planned
    plain = preview_json.plan_json(plan, {}, None)
    assert "stackup" not in plain and "models" not in plain and all("models" not in m for it in plain["items"] for m in it["members"])
    a = json.dumps(preview_json.plan_json(plan, {}, None, ctx), sort_keys=True)
    b = json.dumps(preview_json.plan_json(plan, {}, None, ModelContext(ctx.pcb)), sort_keys=True)
    assert a == b


def test_a_streamed_item_carries_the_same_models_and_new_jobs_are_handed_out_once(planned):
    plan, ctx, tmp = planned
    step = next(s for s in plan.steps if s.item == "r1")
    item = preview_json.item_json(plan, step, {}, ctx)
    assert item["members"][0]["models"][0]["state"] == "ok"
    known = set()
    jobs = ctx.new_jobs(known)
    assert [j["kind"] for j in jobs] == ["file"] and jobs[0]["path"].endswith("chip.step") and ctx.new_jobs(known) == []
    preview_json.item_json(plan, next(s for s in plan.steps if s.item == "c1"), {}, ctx)
    again = ctx.new_jobs(known)
    assert [j["kind"] for j in again] == ["embedded"] and again[0]["ref"] == "C1" and again[0]["board"] == ctx.pcb


STACKED = '''(kicad_pcb (version 20240108) (general (thickness 1.6))
	(setup
		(stackup
			(layer "F.SilkS" (type "Top Silk Screen"))
			(layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
			(layer "F.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 1" (type "prepreg") (thickness 0.1 locked) (material "FR4") (epsilon_r 4.5))
			(layer "In1.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 2" (type "core") (thickness 0.64) (material "FR4") addsublayer (thickness 0.6) (material "FR4"))
			(layer "In2.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 3" (type "prepreg") (thickness 0.1))
			(layer "B.Cu" (type "copper") (thickness 0.035))
			(layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))
			(copper_finish "None")
		)
	)
)
'''


def _geometry(*names, copper=None):
    from types import SimpleNamespace
    from placemat.values import CopperLayer
    return SimpleNamespace(layers=frozenset(CopperLayer.of(n) for n in names), copper_mm={CopperLayer.of(k): v for k, v in (copper or {}).items()})


def test_the_stackup_gives_each_copper_layer_its_height_from_the_boards_own_stackup(tmp_path):
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(STACKED)
    got = ModelContext(pcb).stackup(_geometry("F.Cu", "In1.Cu", "In2.Cu", "B.Cu", copper={"F.Cu": 0.035, "In1.Cu": 0.035, "In2.Cu": 0.035, "B.Cu": 0.035}))
    assert got["thickness"] == 1.6 and got["declared"] is True and got["copper"]["In1.Cu"] == 0.035
    # each layer's height is its middle, walked down from the top face through the mask, copper and dielectric (both sublayers of the core)
    assert [l["name"] for l in got["layers"]] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert [l["z"] for l in got["layers"]] == [1.5725, 1.4375, 0.1625, 0.0275]
    assert all(l["thickness"] == 0.035 for l in got["layers"])


def test_a_stackup_that_does_not_add_up_to_the_thickness_is_scaled_to_it(tmp_path):
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(STACKED.replace("(thickness 1.6))", "(thickness 3.2))", 1))
    got = ModelContext(pcb).stackup(_geometry("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"))
    assert got["thickness"] == 3.2 and [l["z"] for l in got["layers"]] == [3.145, 2.875, 0.325, 0.055]


def test_a_board_with_no_stackup_spaces_its_copper_layers_evenly_through_the_thickness(tmp_path):
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(BOARD)
    got = ModelContext(pcb).stackup(_geometry("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"))
    assert got["declared"] is False and got["copper"] == {}
    assert [(l["name"], l["z"], l["thickness"]) for l in got["layers"]] == [("F.Cu", 1.2, None), ("In1.Cu", 0.8, None), ("In2.Cu", 0.4, None), ("B.Cu", 0.0, None)]
    one = ModelContext(pcb).stackup(_geometry("F.Cu"))
    assert [(l["name"], l["z"]) for l in one["layers"]] == [("F.Cu", 1.2)]


def test_a_stackup_that_misses_one_of_the_boards_layers_is_not_used(tmp_path):
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(STACKED)
    got = ModelContext(pcb).stackup(_geometry("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "B.Cu"))
    assert got["declared"] is False and [l["z"] for l in got["layers"]] == [1.6, 1.2, 0.8, 0.4, 0.0]


def test_the_stackup_rows_are_read_in_order_with_their_kind_and_thickness(tmp_path):
    from placemat import model_place
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(STACKED)
    rows = model_place.board_stackup(pcb)
    assert [r[0] for r in rows] == ["F.SilkS", "F.Mask", "F.Cu", "dielectric 1", "In1.Cu", "dielectric 2", "In2.Cu", "dielectric 3", "B.Cu", "B.Mask"]
    assert rows[0] == ("F.SilkS", "Top Silk Screen", 0.0) and rows[3] == ("dielectric 1", "prepreg", 0.1) and rows[5][2] == pytest.approx(1.24)
    assert model_place.board_stackup(tmp_path / "gone.kicad_pcb") == []
    (tmp_path / "plain.kicad_pcb").write_text(BOARD)
    assert model_place.board_stackup(tmp_path / "plain.kicad_pcb") == []
