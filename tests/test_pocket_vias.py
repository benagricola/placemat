"""A through via in a pocket's raster is judged as the collision rule judges it
for the item being fitted: a courtyard may sit over a via, a pad may not."""
import dataclasses

from placemat.board_geometry import CopperItem
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placer import pockets
from placemat.values import Box, CopperLayer, Face, Location, Part
from tests.fixtures import board_geometry, footprint, rect


def _via(x, y, net="GND"):
    outline = rect(x, y, 0.6, 0.6)
    return CopperItem("via", net, frozenset([CopperLayer.F, CopperLayer.B]), (outline,), Box.of_points(outline),
                      owner="other")


def _field(step=1.0):
    """A 20 x 20 board whose every free cell holds a via on a grid, so no cell is clear of one."""
    return [_via(x + 0.5, y + 0.5) for x in range(0, 20, 1) for y in range(0, 20, 1)]


def _padless(ref, w, h, **kw):
    fp = footprint(ref, 100, 100, w=w, h=h, excess=0.0, **kw)
    return dataclasses.replace(fp, pads=())


def test_a_padless_part_is_placed_over_a_field_of_vias():
    fps = [_padless("D1", 8, 8, inst="d1")]
    b = Board(board_geometry(fps, copper=_field(), width=20, height=20), edge_margin=0.0)
    b.place(Part("d1"))
    plan = b.resolve()
    assert plan.placement("d1") is not None, plan.step("d1").note
    assert not any("pocket" in f for f in plan.findings)


def test_a_part_with_pads_is_kept_off_the_vias():
    fps = [footprint("R1", 100, 100, w=8, h=8, inst="r1", nets=("P", "Q"), excess=0.0)]
    b = Board(board_geometry(fps, copper=_field(), width=20, height=20), edge_margin=0.0, keep_going=True)
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.placement("r1") is None
    assert any("no pocket fits" in f for f in plan.findings)


def _fp(g, ref):
    return next(fp for fp in g.footprints if fp.ref == ref)


def test_the_raster_blocks_a_via_only_for_an_item_with_something_it_may_not_overlap():
    g = board_geometry([_padless("D1", 4, 4, inst="d1"), footprint("R1", 100, 100, inst="r1")],
                       copper=[_via(10, 10)], width=20, height=20)
    occ = Occupancy(g, edge_margin=0.0, board_box=g.outline_box)
    assert not occ.vias_matter(_fp(g, "D1"))
    assert occ.vias_matter(_fp(g, "R1"))
    assert pockets(occ, 20.0, 20.0, Face.FRONT, item=_fp(g, "D1"), limit=1)
    assert not pockets(occ, 20.0, 20.0, Face.FRONT, item=_fp(g, "R1"), limit=1)
    assert not pockets(occ, 20.0, 20.0, Face.FRONT, limit=1)          # no item named: a via blocks


def test_a_house_rule_that_vias_block_courtyards_blocks_a_padless_part_too():
    g = board_geometry([_padless("D1", 4, 4, inst="d1")], copper=[_via(10, 10)], width=20, height=20)
    occ = Occupancy(g, edge_margin=0.0, board_box=g.outline_box, vias_block_courtyards=True)
    assert occ.vias_matter(_fp(g, "D1"))


def test_a_drawn_envelope_ignores_a_via_for_a_padless_body_and_silk_but_not_for_a_pad():
    from placemat.settings import Settings
    fps = [dataclasses.replace(footprint("D1", 100, 100, w=4, h=4, inst="d1", excess=0.0, fab=(98, 98, 102, 102),
                                         silk_boxes=((97.5, 97.5, 102.5, 102.5),)), pads=()),
           footprint("R1", 100, 100, w=4, h=4, inst="r1", excess=0.0, fab=(98, 98, 102, 102), mask_grow=0.1)]
    g = board_geometry(fps, copper=[_via(10, 10)], width=20, height=20)
    occ = Occupancy(g, edge_margin=0.0, board_box=g.outline_box,
                    settings=dataclasses.replace(Settings(), place_envelope="physical"))
    assert not occ.vias_matter(_fp(g, "D1"))
    assert occ.vias_matter(_fp(g, "R1"))


def test_a_part_with_pads_is_placed_with_its_pads_between_the_vias_when_no_pocket_is_clear_of_them():
    from placemat.occupancy import Occupancy as Occ
    vias = [_via(x * 2.5 + 0.25, y * 2.5 + 0.25) for x in range(8) for y in range(8)]
    fps = [footprint("R1", 100, 100, w=8, h=3, inst="r1", nets=("P", "Q"), excess=0.0)]
    g = board_geometry(fps, copper=vias, width=20, height=20)
    occ = Occ(g, edge_margin=0.0, board_box=g.outline_box)
    assert not pockets(occ, 8.0, 3.0, Face.FRONT, item=fps[0])                       # no rectangle is clear of vias
    assert pockets(occ, 8.0, 3.0, Face.FRONT, item=fps[0], vias=False)
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.placement("r1") is not None, plan.step("r1").note
    assert "pocket" in plan.step("r1").note
