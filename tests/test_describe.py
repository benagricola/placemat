"""What a part and a pad look like when placemat says them out loud. Pure:
no KiCad, so the formatting is pinned by tests that run anywhere."""
import dataclasses

import pytest

from placemat import describe
from placemat.values import CopperLayer
from tests.fixtures import board_geometry, footprint, track


def _geom():
    fps = [footprint("U1", 10.0, 10.0, w=4.0, h=2.0, inst="mcu.u", nets=("A", "GND"), cell="mcu"),
           footprint("R1", 30.0, 30.0, w=2.0, h=1.0, inst="r1", nets=("GND", "C"))]
    return board_geometry(fps, cells=["mcu"], width=60, height=60)


def test_a_part_carries_its_identity_position_and_three_boxes():
    g = _geom()
    f = describe.part_facts(g.footprint("U1"), g)
    assert f["instance"] == "mcu.u" and f["ref"] == "U1" and f["cell"] == "mcu"
    assert f["face"] == "front" and f["rotation"] == 0.0
    assert f["origin"] == [10.0, 10.0]
    for name in ("body", "courtyard", "physical"):
        assert name in f and len(f[name]) == 2, name
    assert f["body"] == [4.0, 2.0]


def test_a_pad_reports_the_box_round_its_copper_not_its_anchor():
    g = _geom()
    fp = g.footprint("U1")
    p = fp.pads[0]
    f = describe.pad_facts(fp, p, g)
    assert f["number"] == p.number and f["net"] == p.net
    assert f["size"] == [pytest.approx(p.box.width), pytest.approx(p.box.height)]
    assert f["at"] == [pytest.approx(p.box.center.x), pytest.approx(p.box.center.y)]


def test_a_pad_on_one_face_says_which():
    g = _geom()
    fp = g.footprint("U1")
    assert describe.pad_facts(fp, fp.pads[0], g)["attribute"] == "smd front"


def test_a_part_block_names_all_three_boxes():
    g = _geom()
    text = "\n".join(describe.part_lines(g.footprint("U1"), g))
    for word in ("body", "courtyard", "physical", "U1", "mcu.u", "front"):
        assert word in text, word


def test_pads_are_only_printed_when_asked_for():
    g = _geom()
    assert not any("pad" in l for l in describe.part_lines(g.footprint("U1"), g))
    assert any("pad" in l for l in describe.part_lines(g.footprint("U1"), g, pads=True))


def test_copper_touching_a_pad_is_counted_by_kind():
    """The question is "is anything wired to this pad", not "what is at this
    coordinate" - that one belongs to the occupancy surface."""
    fps = [footprint("U1", 10.0, 10.0, w=4.0, h=2.0, inst="u1", nets=("A", "GND"))]
    g = board_geometry(fps, copper=(track("A", 8.4, 10.0, 20.0, 10.0),), width=60, height=60)
    assert describe.copper_on(g.footprint("U1"), g) == {"track": 1, "via": 0}


def test_copper_on_another_net_is_not_counted():
    fps = [footprint("U1", 10.0, 10.0, w=4.0, h=2.0, inst="u1", nets=("A", "GND"))]
    g = board_geometry(fps, copper=(track("ELSEWHERE", 8.4, 10.0, 20.0, 10.0),),
                       width=60, height=60, extra_nets=("ELSEWHERE",))
    assert describe.copper_on(g.footprint("U1"), g) == {"track": 0, "via": 0}


def test_the_listing_carries_cell_area_and_pin_count():
    g = _geom()
    rows = {r["instance"]: r for r in describe.parts_rows(g)}
    assert rows["mcu.u"]["cell"] == "mcu"
    assert rows["r1"]["cell"] is None
    assert rows["mcu.u"]["mm2"] == pytest.approx(g.footprint("U1").courtyard_box.area, abs=0.01)
    assert rows["mcu.u"]["pins"] == 2


def test_the_listing_s_pin_count_is_the_rank_s_pin_count():
    """Two counts of the same thing would drift. The listing exists partly to
    explain the placement order, so it must not disagree with it."""
    from placemat.ranking import pin_count
    g = _geom()
    for row in describe.parts_rows(g):
        assert row["pins"] == pin_count(g.footprint(row["ref"]))


def test_a_part_with_no_cell_prints_a_dash_rather_than_a_blank():
    g = _geom()
    line = [l for l in describe.parts_lines(g) if "r1" in l][0]
    assert " - " in line


def test_a_board_with_no_footprints_says_so():
    g = board_geometry([], width=20, height=20)
    assert describe.parts_lines(g) == ["no footprints on this board"]


def test_the_nearest_edge_is_none_when_the_board_has_no_polygon():
    """A synthetic geometry has no board_polygon, and the formatter must not
    invent one."""
    g = _geom()
    assert describe.nearest_edge(((1.0, 1.0), (2.0, 1.0), (2.0, 2.0)), g) is None
    assert "nearest board edge" not in "\n".join(describe.part_lines(g.footprint("U1"), g))


def test_the_nearest_edge_is_measured_when_there_is_one():
    g = dataclasses.replace(_geom(),
                            board_polygon=(((0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)),))
    f = describe.part_facts(g.footprint("U1"), g)
    assert f["nearest_edge_courtyard"] == pytest.approx(7.9, abs=0.2)


def test_a_hole_counts_as_a_board_edge():
    """A cutout's edge is a board edge: a part near one is near the edge."""
    g = dataclasses.replace(_geom(),
                            board_polygon=(((0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)),
                                           ((13.0, 8.0), (16.0, 8.0), (16.0, 12.0), (13.0, 12.0))))
    f = describe.part_facts(g.footprint("U1"), g)
    assert f["nearest_edge_courtyard"] == pytest.approx(0.9, abs=0.05)    # the hole, not the rim


def test_the_docs_tell_an_agent_to_measure_rather_than_grep():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "placemat parts" in api and "--pads" in api
    skill = Path("skills/placemat/SKILL.md").read_text()
    assert "placemat parts" in skill and "kicad_mod" in skill
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.10" in mig


def test_the_docs_tell_an_agent_to_index_a_datasheet_rather_than_grep_it():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "placemat datasheet" in api and "--show" in api
    skill = Path("skills/placemat/SKILL.md").read_text()
    assert "placemat datasheet" in skill
    mig = Path("skills/placemat/references/migration.md").read_text()
    assert "0.12" in mig and "0.11" in mig


def test_the_pad_table_lines_up_whatever_the_stackup():
    """A four-layer board names four layers on every through pad, which is
    wider than the column the layer names used to be poured into, so the
    coordinates after it walked. Each block is laid out to its own widest
    entry instead of to a constant."""
    g = _geom()
    fp = g.footprint("U1")
    wide = dataclasses.replace(fp.pads[0], through=True, drill_mm=0.8, layers=frozenset(
        [CopperLayer.F, CopperLayer.B, CopperLayer.IN1, CopperLayer.IN2]))
    fp = dataclasses.replace(fp, pads=(wide, fp.pads[1]))
    pads = [l for l in describe.part_lines(fp, g, pads=True) if l.strip().startswith("pad ")]
    assert len(pads) == 2
    assert len({l.index(" at (") for l in pads}) == 1, pads
