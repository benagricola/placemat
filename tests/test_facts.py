"""The facts document placemat facts prints, and its digest: what
placemat facts --confirm records in placemat.toml's [facts] confirmed."""
import dataclasses

import pytest

from placemat.board_geometry import NetClass
from placemat.facts import facts_of, render, unconfirmed_line, unconfirmed_reasons, write_confirmed
from placemat.project import FabProfile
from placemat.values import CopperLayer
from tests.fixtures import board_geometry, footprint

F, B, IN1 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1


def _geometry():
    g = board_geometry([footprint("U1", 10, 10, inst="u1")], width=30, height=30)
    return dataclasses.replace(g, layers=(F, IN1, B), layer_types={F: "signal", IN1: "power", B: "signal"},
                               copper_mm={F: 0.035, IN1: 0.0152, B: 0.035},
                               netclasses={**g.netclasses,
                                          "CLK_P": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1),
                                          "CLK_N": NetClass("Fast", 0.2, 0.15, 0.45, 0.2, 0.1, 0.1)})


def test_layers_carry_role_and_weight():
    doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
    assert doc.layers["F.Cu"] == {"role": "signal", "copper_mm": 0.035}
    assert doc.layers["In1.Cu"] == {"role": "power", "copper_mm": 0.0152}


def test_pair_classes_and_their_nets():
    doc = facts_of(_geometry(), FabProfile(), rise_c=10.0)
    assert doc.pairs == {"Fast": ["CLK_N", "CLK_P"]}


def test_via_types_by_tier():
    fab = FabProfile(via_tiers={"buried": "yes", "blind": "if-needed"})
    doc = facts_of(_geometry(), fab, rise_c=10.0)
    assert doc.via_types == {"micro": "no", "blind": "if-needed", "buried": "yes"}


def test_the_digest_is_stable_for_the_same_facts():
    doc1 = facts_of(_geometry(), FabProfile(), rise_c=10.0)
    doc2 = facts_of(_geometry(), FabProfile(), rise_c=10.0)
    assert doc1.digest() == doc2.digest()


def test_the_digest_changes_when_a_copper_weight_changes():
    doc1 = facts_of(_geometry(), FabProfile(), rise_c=10.0)
    changed = dataclasses.replace(_geometry(), copper_mm={F: 0.070, IN1: 0.0152, B: 0.035})
    doc2 = facts_of(changed, FabProfile(), rise_c=10.0)
    assert doc1.digest() != doc2.digest()


def test_a_board_never_confirmed_is_unconfirmed():
    doc = facts_of(_geometry(), FabProfile(via_tiers={"blind": "yes"}, min={"track_mm": 0.09}), rise_c=10.0)
    assert unconfirmed_reasons(doc, "") == ["no confirmation record yet"]


def test_a_matching_digest_with_via_and_min_set_is_confirmed():
    doc = facts_of(_geometry(), FabProfile(via_tiers={"blind": "yes"}, min={"track_mm": 0.09}), rise_c=10.0)
    assert unconfirmed_reasons(doc, doc.digest()) == []


def test_a_changed_digest_is_unconfirmed():
    doc = facts_of(_geometry(), FabProfile(via_tiers={"blind": "yes"}, min={"track_mm": 0.09}), rise_c=10.0)
    assert unconfirmed_reasons(doc, "not" + doc.digest()) == ["the facts have changed since they were last confirmed"]


def test_no_via_tiers_at_all_is_unconfirmed_even_with_a_matching_digest():
    doc = facts_of(_geometry(), FabProfile(min={"track_mm": 0.09}), rise_c=10.0)
    reasons = unconfirmed_reasons(doc, doc.digest())
    assert "fab-profile.json has no via section" in reasons


def test_no_min_at_all_is_unconfirmed_even_with_a_matching_digest():
    doc = facts_of(_geometry(), FabProfile(via_tiers={"blind": "yes"}), rise_c=10.0)
    reasons = unconfirmed_reasons(doc, doc.digest())
    assert "fab-profile.json has no min section" in reasons


def test_a_signal_layer_carrying_a_plane_is_flagged():
    doc = facts_of(_geometry(), FabProfile(), rise_c=10.0, plane_layers=frozenset({F}))
    assert any("F.Cu" in m and "signal" in m for m in doc.plane_mismatches)


def test_a_power_layer_with_no_plane_is_flagged():
    doc = facts_of(_geometry(), FabProfile(), rise_c=10.0, plane_layers=frozenset())
    assert any("In1.Cu" in m for m in doc.plane_mismatches)


def test_render_lists_every_fact_and_says_unconfirmed():
    doc = facts_of(_geometry(), FabProfile(via_tiers={"blind": "yes"}, min={"track_mm": 0.09}), rise_c=10.0)
    lines = render(doc, unconfirmed_reasons(doc, ""))
    assert any(l.startswith("layer      F.Cu") for l in lines)
    assert any(l.startswith("pair class Fast") for l in lines)
    assert any(l.startswith("via        micro") for l in lines)
    assert lines[-1] == "unconfirmed: no confirmation record yet"


def test_render_says_confirmed_when_the_digest_matches():
    doc = facts_of(_geometry(), FabProfile(via_tiers={"blind": "yes"}, min={"track_mm": 0.09}), rise_c=10.0)
    lines = render(doc, unconfirmed_reasons(doc, doc.digest()))
    assert lines[-1] == "confirmed"


def test_the_unconfirmed_line_names_the_command():
    assert unconfirmed_line(["no confirmation record yet"]) == "facts: unconfirmed - placemat facts"


def test_write_confirmed_adds_a_facts_section(tmp_path):
    p = tmp_path / "placemat.toml"
    p.write_text("[place]\nstep = 0.1\n")
    write_confirmed(p, "abc123")
    text = p.read_text()
    assert "[facts]" in text and 'confirmed = "abc123"' in text
    assert "[place]" in text and "step = 0.1" in text


def test_write_confirmed_replaces_an_existing_value(tmp_path):
    p = tmp_path / "placemat.toml"
    p.write_text('[facts]\nconfirmed = "old"\n')
    write_confirmed(p, "new")
    text = p.read_text()
    assert text.count("[facts]") == 1 and 'confirmed = "new"' in text and "old" not in text


def test_write_confirmed_creates_the_file_when_it_does_not_exist(tmp_path):
    p = tmp_path / "placemat.toml"
    write_confirmed(p, "abc123")
    assert 'confirmed = "abc123"' in p.read_text()
