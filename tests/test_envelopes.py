"""[place] envelope: what a part claims against another. Pure."""
import dataclasses

import pytest

from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings, SettingsError
from placemat.values import Box, Face, Location, Part
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


def _board(fps, envelope, **kw):
    return Board(board_geometry(fps, width=60, height=40, silk_clearance=SILK, **kw), edge_margin=0.5,
                 settings=dataclasses.replace(Settings(), place_envelope=envelope))


def test_in_physical_the_rank_measures_what_the_part_draws():
    """A small courtyard round a large drawn body: the courtyard understates
    the part, and in physical the rank goes by the body."""
    fps = [footprint("P1", 10, 10, w=2, h=1, inst="p1", nets=("A", "B"), fab=(5, 6, 15, 14)),
           footprint("P2", 40, 20, w=4, h=3, inst="p2", nets=("C", "D"))]
    def first(envelope):
        b = _board(fps, envelope)
        b.place(Part("p1"))
        b.place(Part("p2"))
        steps = [s for s in b.resolve().steps if s.item in ("p1", "p2")]
        return min(steps, key=lambda s: s.rank).item
    assert first("courtyard") == "p2"
    assert first("physical") == "p1"


def test_in_physical_a_rows_claim_is_the_reach_alone():
    fp = footprint("P1", 10, 10, w=4, h=2, inst="p1", excess=0.5, silk_boxes=[(8.2, 9.2, 11.8, 9.3)])
    court = _board([fp], "courtyard").claim(Part("p1"))
    phys = _board([fp], "physical").claim(Part("p1"))
    assert court.width == pytest.approx(5.0)            # the courtyard, 0.5 each side of the 4 mm body
    assert phys.width == pytest.approx(4.0)             # the body and silk it draws
    assert _board([fp], "union").claim(Part("p1")).width == pytest.approx(5.0)


def test_a_cells_envelope_holds_its_members_silk_and_bodies():
    fps = [footprint("R1", 10, 10, inst="r1", cell="c", silk_boxes=[(7, 8, 13, 8.1)]),
           footprint("R2", 10, 14, inst="r2", cell="c", fab=(8, 13, 12, 15))]
    g, occ = _occ(fps, "physical")
    g = board_geometry(fps, cells=("c",), width=60, height=40, silk_clearance=SILK)
    occ = Occupancy(g, 0.5, settings=dataclasses.replace(Settings(), place_envelope="physical"))
    kinds = {s.kind for s in occ._geometry(g.cells["c"]).shapes}
    assert {"silk", "body"} <= kinds


def test_in_physical_a_pocket_is_not_where_a_placed_body_stands():
    from placemat.placer import pockets
    fps = [footprint("A1", 30, 20, w=2, h=1, inst="a1", fab=(10, 5, 50, 35))]     # a small courtyard, a large body
    g, occ = _occ(fps, "physical")
    a = g.footprint("a1")
    occ.commit(a, Placement(a.location, a.rotation, a.face))
    for p in pockets(occ, 5.0, 5.0, Face.FRONT):
        assert not p.box.overlaps(Box(10, 5, 50, 35)), p.box


def test_in_physical_a_blocks_members_keep_the_same_gaps_from_each_other():
    """A satellite laid at its pin is another part: its silk may not reach the
    anchor's silk or pads, as between any two parts. Both are pending, as in a
    resolve, so only the block's own check can see one against the other."""
    from placemat.placer import BlockSpec, layout_block
    anchor = footprint("U1", 20, 20, w=6, h=3, inst="u1", nets=("VIN", "VOUT"),
                       silk_boxes=[(16.0, 19.35, 16.9, 19.45)], mask_grow=0.0)        # a silk stub west of pad 1
    sat = footprint("C1", 40, 20, w=2, h=1, inst="c1", nets=("VIN", "GND"),
                    silk_boxes=[(39.6, 19.35, 40.0, 19.45)], mask_grow=0.0)            # in the stub's row
    g, occ = _occ([anchor, sat], "physical")
    occ.pending |= {"U1", "C1"}
    spec = BlockSpec(g.footprint("u1"), ((g.footprint("c1"), "VIN"),), gap=None)
    members, why = layout_block(occ, spec, Placement(Location(20, 20), 0.0, Face.FRONT))
    assert members is not None, why
    occ.commit(g.footprint("u1"), members["u1"])
    assert occ.legal(g.footprint("c1"), members["c1"]) is None
