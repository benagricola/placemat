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
