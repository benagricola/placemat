"""The builder's facts: the state of each row, the gate, the batch of edits to the three homes (one apply, one undo), the
root-versus-board rule for fab-profile.json, the confirmation and the read-back."""
import json

import pytest

from placemat import builder_facts as bf, facts, suggestions as sg, zen_edit as ze
from placemat.builder import BuilderRefused

LAYERS = {"F.Cu": {"role": "signal", "copper_mm": None}, "B.Cu": {"role": "signal", "copper_mm": None}}


def record(**kw):
    base = dict(layers=LAYERS, pairs={}, via_types={"micro": "no", "blind": "no", "buried": "no"}, fab_min={}, rise_c=10.0,
                plane_mismatches=(), via_named=())
    base.update(kw)
    return bf.facts_record(facts.FactsDocument(**base))


def model(rec=None, confirmed="", acks=None, doc=None, **kw):
    return bf.facts_model(rec or record(), zen={"file": "d.zen"}, fab={}, rise=kw.get("rise", {"set": False}), confirmed_digest=confirmed,
                          confirmed_doc=doc, acks=acks)


def states(m):
    return {r["id"]: r["state"] for r in m["rows"]}


def decided():
    return record(layers={"F.Cu": {"role": "signal", "copper_mm": 0.035}, "B.Cu": {"role": "signal", "copper_mm": 0.035}},
                  pairs={"USB": ["USB_N", "USB_P"]}, via_types={"micro": "no", "blind": "if-needed", "buried": "no"},
                  fab_min={"track_mm": 0.09}, via_named=("micro", "blind", "buried"))


def test_a_board_with_nothing_declared_has_every_row_undecided_and_the_gate_shut():
    m = model()
    assert states(m) == {"layer:F.Cu": "undecided", "layer:B.Cu": "undecided", "pairs": "undecided", "via:micro": "undecided",
                         "via:blind": "undecided", "via:buried": "undecided", "min": "undecided", "rise": "undecided"}
    assert m["counts"]["undecided"] == 8 and m["gate"]["open"] is False and "layer:F.Cu" in m["gate"]["holds"]
    assert [r["reason"] for r in m["reasons"]][0] == "no_record"
    assert bf.can_confirm(m) and "F.Cu is undecided" in bf.can_confirm(m)[0]


def test_accepting_no_pairs_is_a_decision_and_a_default_left_unwritten_is_not():
    assert states(model(acks={"no_pairs": True}))["pairs"] == "decided"
    assert states(model())["pairs"] == "undecided"
    assert states(model(decided()))["pairs"] == "decided"


def test_a_plane_mismatch_flags_a_row_until_it_is_acknowledged():
    rec = decided()
    rec = dict(rec, plane_mismatches=["B.Cu is power (ground) but carries no plane()"])
    m = model(rec, rise={"set": True})
    assert states(m)["layer:B.Cu"] == "flagged" and m["counts"]["flagged"] == 1
    assert any("no plane()" in x for x in bf.can_confirm(m))
    m2 = model(rec, acks={"plane:B.Cu": True}, rise={"set": True})
    assert states(m2)["layer:B.Cu"] == "decided" and bf.can_confirm(m2) == []


def test_everything_decided_can_be_confirmed_and_the_confirmed_digest_opens_the_gate():
    rec = decided()
    m = model(rec, rise={"set": True})
    assert bf.can_confirm(m) == [] and m["gate"]["open"] is False
    ok = model(rec, confirmed=rec["digest"], rise={"set": True})
    assert ok["gate"]["open"] is True and ok["confirmed"] is True and ok["gate"]["holds"] == []


def test_a_fact_changed_after_confirmation_shows_which_one_and_closes_the_gate():
    rec = decided()
    later = dict(rec, via_types={"micro": "no", "blind": "yes", "buried": "no"})
    later["digest"] = facts.FactsDocument(later["layers"], later["pairs"], later["via_types"], later["fab_min"], later["rise_c"]).digest()
    m = model(later, confirmed=rec["digest"], doc=rec, rise={"set": True})
    assert states(m)["via:blind"] == "changed" and states(m)["via:micro"] == "decided"
    assert m["gate"]["open"] is False and m["changed_known"] is True
    unknown = model(later, confirmed=rec["digest"], rise={"set": True})
    assert unknown["counts"]["changed"] == 1 and "changed" in unknown["gate"]["holds"] and unknown["changed_known"] is False


def test_the_reasons_are_the_commands_own():
    rec = record(via_named=("micro",))
    m = model(rec, confirmed="abc")
    assert {"reason": "no_via_tier", "kinds": ["blind", "buried"]}.items() <= m["reasons"][0].items()
    assert [r["reason"] for r in m["reasons"]] == ["no_via_tier", "no_min_section", "changed"]
    assert all(r["text"] for r in m["reasons"])


def test_pair_candidates_come_from_the_routers_naming_rule():
    got = bf.pair_candidates(["USB_P", "USB_N", "CLK+", "CLK-", "GND", "VCC", "DATA_P", "SDA"])
    assert [(c["positive"], c["negative"]) for c in got] == [("CLK+", "CLK-"), ("USB_P", "USB_N")]
    assert {c["base"] for c in got} == {"CLK", "USB"}


def test_a_thickness_that_is_a_standard_weight_is_shown_as_that_weight():
    assert bf.weight_row({"kind": "copper", "role": "signal", "thickness_um": 35})["oz"] == 1.0
    assert bf.weight_row({"kind": "copper", "role": "signal", "oz": 0.5})["thickness_mm"] == 0.0175
    assert "oz" not in bf.weight_row({"kind": "copper", "role": "signal", "thickness_um": 40})
    assert bf.weight_row({"kind": "dielectric", "thickness_mm": 0.2})["thickness_mm"] == 0.2


# ------------------------------------------------------------------ files
ZEN = 'Board(\n    name = "Demo",\n    layers = 2,\n)\n'
PROFILE = '{\n  "via": {"micro": "no"},\n  "courtyard": {"excess_mm": 0.1}\n}\n'


def project(tmp_path, zen=ZEN, toml=None, profile_at_root=None, profile_beside=None):
    root = tmp_path / "proj"
    board = root / "boards" / "demo"
    board.mkdir(parents=True)
    (board / "demo.zen").write_text(zen)
    if toml is not None:
        (root / "placemat.toml").write_text(toml)
    if profile_at_root is not None:
        (root / "fab-profile.json").write_text(profile_at_root)
    if profile_beside is not None:
        (board / "fab-profile.json").write_text(profile_beside)
    return root, board


def apply(plan, root, tmp_path):
    return sg.apply_edits(plan["edits"], plan["digests"], root=root, log=tmp_path / "applied.jsonl", label=plan["label"], source="builder")


REQUEST = {"stackup": {"copper_layers": 2, "rows": [{"kind": "copper", "role": "signal", "oz": 1}, {"kind": "dielectric", "thickness_mm": 1.5, "form": "core"},
                                                    {"kind": "copper", "role": "signal", "oz": 1}]},
           "pairs": {"classes": [{"name": "USB", "diff_pair_width": 0.2, "diff_pair_gap": 0.15, "nets": ["USB_P", "USB_N"]}]},
           "via": {"micro": "no", "blind": "no", "buried": "no", "default_drill_mm": 0.3, "default_size_mm": 0.6},
           "min": {"track_mm": 0.09, "clearance_mm": 0.09}, "rise_c": 20}


def test_a_batch_writes_the_three_homes_in_one_apply_and_one_undo_restores_them(tmp_path):
    root, board = project(tmp_path, toml="[check]\nrise_c = 10\n")
    plan = bf.facts_edits(REQUEST, zen_file=str(board / "demo.zen"), board_name="Demo", board_dir=board, root=root)
    assert len(plan["edits"]) == 4 or len(plan["edits"]) == 5
    done = apply(plan, root, tmp_path)
    zen = (board / "demo.zen").read_text()
    assert ze.read_stackup(zen, "Demo")[0]["oz"] == 1.0 and ze.read_netclasses(zen, "Demo")[0]["name"] == "USB"
    prof = json.loads((root / "fab-profile.json").read_text())
    assert prof["via"]["blind"] == "no" and prof["min"] == {"track_mm": 0.09, "clearance_mm": 0.09}
    assert "rise_c = 20.0" in (root / "placemat.toml").read_text()
    assert set(done.files) == {str(board / "demo.zen"), str(root / "fab-profile.json"), str(root / "placemat.toml")}
    sg.undo_last(tmp_path / "applied.jsonl", root=root)
    assert (board / "demo.zen").read_text() == ZEN and not (root / "fab-profile.json").exists()
    assert (root / "placemat.toml").read_text() == "[check]\nrise_c = 10\n"


def test_a_batch_against_a_stale_file_writes_nothing(tmp_path):
    root, board = project(tmp_path)
    plan = bf.facts_edits({"pairs": REQUEST["pairs"]}, zen_file=str(board / "demo.zen"), board_name="Demo", board_dir=board, root=root)
    (board / "demo.zen").write_text(ZEN + "# edited\n")
    with pytest.raises(sg.StaleSuggestion):
        apply(plan, root, tmp_path)
    assert (board / "demo.zen").read_text() == ZEN + "# edited\n"


def test_with_no_profile_the_values_go_to_the_project_root(tmp_path):
    root, board = project(tmp_path)
    plan = bf.fab_plan(board, root, [(["via", "micro"], "no")])
    assert plan["mode"] == "create_root" and plan["file"] == str(root / "fab-profile.json") and "default" in plan["says"]
    assert json.loads(plan["text"]) == {"via": {"micro": "no"}}


def test_a_root_profile_is_left_alone_and_a_changed_value_gets_a_full_copy_beside_the_board(tmp_path):
    root, board = project(tmp_path, profile_at_root=PROFILE)
    plan = bf.fab_plan(board, root, [(["via", "blind"], "if-needed")])
    assert plan["mode"] == "copy_beside" and plan["file"] == str(board / "fab-profile.json") and plan["from"] == str(root / "fab-profile.json")
    assert json.loads(plan["text"]) == {"via": {"micro": "no", "blind": "if-needed"}, "courtyard": {"excess_mm": 0.1}}
    assert "its own fab-profile.json" in plan["says"]
    same = bf.fab_plan(board, root, [(["via", "micro"], "no")])
    assert same["mode"] == "none"
    out = bf.facts_edits({"via": {"blind": "if-needed"}}, zen_file=str(board / "demo.zen"), board_name="Demo", board_dir=board, root=root)
    apply(out, root, tmp_path)
    assert (root / "fab-profile.json").read_text() == PROFILE and json.loads((board / "fab-profile.json").read_text())["via"]["blind"] == "if-needed"


def test_a_profile_beside_the_board_is_edited_in_place_and_when_root_is_the_board_there_is_one_file(tmp_path):
    root, board = project(tmp_path, profile_at_root=PROFILE, profile_beside=PROFILE)
    plan = bf.fab_plan(board, root, [(["via", "blind"], "no")])
    assert plan["mode"] == "edit" and plan["file"] == str(board / "fab-profile.json")
    one = tmp_path / "one"
    one.mkdir()
    (one / "fab-profile.json").write_text(PROFILE)
    assert bf.fab_plan(one, one, [(["via", "blind"], "no")])["mode"] == "edit"


def test_the_rise_goes_to_the_nearest_placemat_toml_and_a_new_one_only_where_none_exists(tmp_path):
    root, board = project(tmp_path, toml="[solve]\nenabled = false\n")
    assert bf.toml_file(board) == root / "placemat.toml"
    root2, board2 = project(tmp_path / "b")
    assert bf.toml_file(board2) == board2 / "placemat.toml"
    plan = bf.facts_edits({"rise_c": 15}, zen_file=str(board2 / "demo.zen"), board_name="Demo", board_dir=board2, root=root2)
    apply(plan, root2, tmp_path)
    assert (board2 / "placemat.toml").read_text().startswith("[check]\n")
    assert 'rise_c = 15.0' in (board2 / "placemat.toml").read_text()


def test_the_confirmation_writes_what_the_command_writes(tmp_path):
    root, board = project(tmp_path, toml="[check]\nrise_c = 10\n")
    script = board / "Demo_layout.py"
    script.write_text('"""x"""\n')
    plan = bf.confirm_edit(script, "abc123", board)
    assert plan["key"] == "boards/demo/Demo_layout.py"
    apply(plan, root, tmp_path)
    assert (root / "placemat.toml").read_text() == facts.confirmed_text("[check]\nrise_c = 10\n", "abc123", key=plan["key"])
    sg.undo_last(tmp_path / "applied.jsonl", root=root)
    assert (root / "placemat.toml").read_text() == "[check]\nrise_c = 10\n"


def test_the_confirmation_makes_the_toml_where_there_is_none_and_undo_removes_it(tmp_path):
    root, board = project(tmp_path)
    script = board / "Demo_layout.py"
    script.write_text('"""x"""\n')
    plan = bf.confirm_edit(script, "abc123", board)
    apply(plan, root, tmp_path)
    assert (board / "placemat.toml").read_text().startswith("[facts.boards]")
    sg.undo_last(tmp_path / "applied.jsonl", root=root)
    assert not (board / "placemat.toml").exists()


def test_a_request_with_nothing_to_write_or_a_wrong_value_is_refused(tmp_path):
    root, board = project(tmp_path)
    kw = dict(zen_file=str(board / "demo.zen"), board_name="Demo", board_dir=board, root=root)
    with pytest.raises(BuilderRefused, match="nothing to write"):
        bf.facts_edits({}, **kw)
    with pytest.raises(BuilderRefused, match="yes, no or if-needed"):
        bf.facts_edits({"via": {"micro": "maybe"}}, **kw)
    with pytest.raises(BuilderRefused, match="not a fab minimum"):
        bf.facts_edits({"min": {"width_mm": 1}}, **kw)
    with pytest.raises(BuilderRefused, match="rise"):
        bf.facts_edits({"rise_c": 0}, **kw)
    with pytest.raises(BuilderRefused, match="positive"):
        bf.facts_edits({"min": {"track_mm": -1}}, **kw)


def test_the_readback_reports_what_the_generator_ignored():
    asked = {"stackup": REQUEST["stackup"], "pairs": REQUEST["pairs"], "via": {"blind": "if-needed"}, "min": {"track_mm": 0.09}, "rise_c": 20}
    got = record(layers={"F.Cu": {"role": "signal", "copper_mm": 0.035}, "B.Cu": {"role": "signal", "copper_mm": 0.035}},
                 pairs={"USB": ["USB_N", "USB_P"]}, via_types={"micro": "no", "blind": "if-needed", "buried": "no"}, fab_min={"track_mm": 0.09},
                 rise_c=20.0)
    assert bf.readback(asked, got) == []
    bad = dict(got, layers={"F.Cu": {"role": "power", "copper_mm": 0.0175}, "B.Cu": {"role": "signal", "copper_mm": 0.035}}, pairs={}, rise_c=10.0)
    names = [(r["fact"], r["name"]) for r in bf.readback(asked, bad)]
    assert names == [("layer", "F.Cu"), ("layer", "F.Cu"), ("pairs", "pair classes"), ("rise", "rise_c")]
    ground = {"stackup": {"rows": [{"kind": "copper", "role": "ground", "oz": 1}]}}
    assert bf.readback(ground, dict(got, layers={"In1.Cu": {"role": "power", "copper_mm": 0.035}})) == []


def test_a_stackup_the_zen_does_not_declare_is_the_generators_default_and_stays_undecided():
    rec = decided()
    m = bf.facts_model(rec, zen={"file": "d.zen", "stackup": "none"}, fab={}, rise={"set": True}, confirmed_digest="")
    assert states(m)["layer:F.Cu"] == "undecided" and m["rows"][0]["default"] is True
    m2 = bf.facts_model(rec, zen={"file": "d.zen", "stackup": "elsewhere"}, fab={}, rise={"set": True}, confirmed_digest="")
    assert states(m2)["layer:F.Cu"] == "decided"
