"""[place] envelope: what a part claims against another. Pure."""
import dataclasses

import pytest

from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings, SettingsError
from placemat.values import Face, Location, Part
from tests.fixtures import board_geometry, footprint

SILK = 0.1
SPACING = 0.2


def _occ(fps, envelope):
    g = board_geometry(fps, width=60, height=40, silk_clearance=SILK)
    occ = Occupancy(g, 0.5, settings=dataclasses.replace(Settings(), place_envelope=envelope),
                    component_spacing=SPACING)
    return g, occ


def _why(fps, envelope, first="a1", second="b1"):
    """Commit `first` where it is drawn and ask whether `second` may sit where it is drawn."""
    g, occ = _occ(fps, envelope)
    a, b = g.footprint(first), g.footprint(second)
    occ.commit(a, Placement(a.location, a.rotation, a.face))
    return occ.legal(b, Placement(b.location, b.rotation, b.face))


def _wide_silk(ref, cx, inst):
    """A part whose silk line runs 1 mm past each end of its courtyard."""
    return footprint(ref, cx, 10, inst=inst, silk_boxes=[(cx - 3.0, 8.7, cx + 3.0, 8.8)])


def test_silk_past_the_courtyard_cannot_meet_another_parts_silk_in_physical():
    fps = [_wide_silk("A1", 10, "a1"), _wide_silk("B1", 16, "b1")]      # courtyards 1.8 mm apart, silk touching
    assert _why(fps, "courtyard") is None
    why = _why(fps, "physical")
    assert why is not None and "silk" in why and "needs 0.10" in why
    clear = [_wide_silk("A1", 10, "a1"), _wide_silk("B1", 16.15, "b1")]  # silk 0.15 apart
    assert _why(clear, "physical") is None


def test_silk_by_another_parts_mask_opening_keeps_the_silk_clearance():
    a = footprint("A1", 10, 10, inst="a1", mask_grow=0.05)             # pad 1 opening y 9.45..10.55
    near = footprint("B1", 10, 13, inst="b1", silk_boxes=[(8.0, 10.6, 9.0, 10.62)])      # 0.05 below it
    far = footprint("B1", 10, 13, inst="b1", silk_boxes=[(8.0, 10.66, 9.0, 10.68)])      # 0.11 below it
    why = _why([a, near], "physical")
    assert why is not None and "mask" in why
    assert _why([a, far], "physical") is None


def test_bodies_keep_the_component_spacing_from_each_other_and_from_pads():
    def pair(cx):
        return [footprint("A1", 10, 10, inst="a1", fab=(8, 9, 12, 11)),
                footprint("B1", cx, 10, inst="b1", fab=(cx - 2, 9, cx + 2, 11))]
    assert "body" in (_why(pair(14.1), "physical") or "")             # 0.1 apart
    assert _why(pair(14.2), "physical") is None                        # exactly the spacing
    pad_near = [footprint("A1", 10, 10, inst="a1", fab=(8, 9, 12, 11)),
                footprint("B1", 14.0, 10, inst="b1", silk_boxes=[(15.9, 9, 16, 11)])]      # its pad 0.1 from the body
    why = _why(pad_near, "physical")
    assert why is not None and "body" in why


def test_silk_may_touch_another_body_but_not_sit_inside_it():
    touch = [footprint("A1", 10, 10, inst="a1", fab=(8, 9, 12, 11)),
             footprint("B1", 10, 14, inst="b1", silk_boxes=[(9, 11.0, 11, 11.1)])]
    inside = [footprint("A1", 10, 10, inst="a1", fab=(8, 9, 12, 11)),
              footprint("B1", 10, 14, inst="b1", silk_boxes=[(9, 10.9, 11, 11.1)])]
    assert _why(touch, "physical") is None
    assert "body" in (_why(inside, "physical") or "")


def _resolve(fps, envelope):
    b = Board(board_geometry(fps, width=40, height=30, silk_clearance=SILK), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), place_envelope=envelope))
    b.place(Part("j1"), at=Location(5, 15))
    for fp in fps[1:]:
        b.place(Part(fp.inst))
    return [(s.item, s.placement) for s in b.resolve().steps]


def test_a_footprint_with_only_pads_places_exactly_as_in_courtyard_mode():
    fps = [footprint("J1", 5, 15, w=3, h=2, inst="j1", nets=("A", "GND")),
           footprint("R1", 20, 20, inst="r1", nets=("A", "B")),
           footprint("R2", 25, 20, inst="r2", nets=("B", "C")),
           footprint("R3", 30, 20, inst="r3", nets=("C", "A"))]
    base = _resolve(fps, "courtyard")
    assert _resolve(fps, "physical") == base
    assert _resolve(fps, "union") == base


def test_a_footprint_with_no_physical_layers_claims_its_courtyard_in_physical():
    fps = [footprint("A1", 10, 10, inst="a1"), footprint("B1", 14.1, 10, inst="b1")]   # courtyards overlap by 0.1
    assert "courtyard" in (_why(fps, "physical") or "")


def test_union_refuses_what_either_refuses():
    silk = [_wide_silk("A1", 10, "a1"), _wide_silk("B1", 16, "b1")]
    assert "silk" in (_why(silk, "union") or "")
    court = [footprint("A1", 10, 10, inst="a1", fab=(9, 9.5, 11, 10.5)),
             footprint("B1", 14.1, 10, inst="b1", fab=(13.1, 9.5, 15.1, 10.5))]     # bodies far apart, courtyards overlap
    assert _why(court, "physical") is None
    assert "courtyard" in (_why(court, "union") or "")


def test_an_unknown_envelope_is_a_settings_error(tmp_path):
    from placemat import settings
    (tmp_path / "placemat.toml").write_text('[place]\nenvelope = "silk"\n')
    with pytest.raises(SettingsError, match="courtyard, physical or union"):
        settings.load(tmp_path)
