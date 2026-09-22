"""Slice 1: the BoardGeometry read from the committed Breakout .kicad_pcb answers the
questions the old layout script asked pcbnew directly."""
import pytest

from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def test_station_cell_extents_match_the_measured_module_contract(breakout):
    # Turned onto an edge, a drop's world-Y extent is the module's along-edge
    # width and its world-X extent is the module's depth: the numbers the
    # modules' own layouts measure today. These footprints draw no courtyard,
    # so the body box IS the physical box.
    box = breakout.cell("power_drop0").box
    assert abs(box.height - 28.560) < 0.01
    assert abs(box.width - 40.250) < 0.01
    assert breakout.cell("power_drop0").copper_box is not None   # the cell's own tracks count
    box = breakout.cell("bus_drop0").box
    assert abs(box.height - 27.050) < 0.01
    assert abs(box.width - 19.650) < 0.01


def test_cells_are_indexed_by_group_name(breakout):
    assert sorted(breakout.cells) == sorted(
        ["power_drop%d" % d for d in range(3)] + ["bus_drop%d" % d for d in range(3)])
    conn = breakout.cell("power_drop0").member("conn")
    assert conn.ref.startswith("U") and conn.cell == "power_drop0"
    assert breakout.cell("power_drop0").member("fuse").inst == "power_drop0.fuse"


def test_footprints_are_addressed_by_instance_and_by_reference(breakout):
    cn1 = breakout.footprint("CN1")
    assert cn1.ref == "CN1"
    assert cn1.face.value == "front"
    assert breakout.footprint(cn1.inst) is cn1


def test_pad_lookup_by_number_and_by_net(breakout):
    v48 = breakout.pad("CN1", "V48P")
    gnd = breakout.pad("CN1", "GND")
    assert v48.net == "V48P" and gnd.net == "GND"
    assert v48.location != gnd.location
    by_number = breakout.pad("CN1", int(v48.number))
    assert by_number is v48
    with pytest.raises(TypeError):
        breakout.pad("CN1", "1")          # a numeric string is neither a number nor a net


def test_cell_pad_lookup_finds_the_jumper_pad_on_a_net(breakout):
    p = breakout.cell_pad("bus_drop0", net="CAN_P", ref_prefix="H")
    assert p.net == "CAN_P"
    assert p.owner.startswith("H")
    p5 = breakout.cell_pad("power_drop0", number=5, ref_prefix="U")
    assert p5.number == "5"


def test_copper_and_outline_are_collected(breakout):
    kinds = {c.kind for c in breakout.copper}
    assert {"pad", "track", "poly", "zone"} <= kinds       # this board has no via: nothing changes face
    assert breakout.outline_box.height > breakout.outline_box.width          # a tall panel, whatever its size today


def test_netclass_clearance_is_resolved_from_the_project(breakout):
    assert breakout.clearance("CAN_P", "CAN_N") == pytest.approx(0.2, abs=1e-6)


def test_a_footprint_with_no_courtyard_claims_its_body_not_its_pads(breakout_pcb):
    """`courtyard_box`'s own fallback was unreachable: it appended the pads box
    before testing the union for None, so a footprint that draws no courtyard
    claimed exactly its pads. A five-way terminal block claimed 70 mm2 of the
    334 mm2 it stands on, and the placement rank is worked out from that area.
    `body_box` has always used the physical extent in this case; the two now
    agree."""
    import pcbnew

    from placemat.kicad import read

    board = pcbnew.LoadBoard(str(breakout_pcb))
    bare = [fp for fp in board.GetFootprints()
            if not any(d.GetLayer() in read._COURTYARD_LAYERS for d in fp.GraphicalItems())]
    assert bare, "the breakout has no courtyard-less footprints to check"
    for fp in bare:
        assert read.courtyard_box(fp) == read.phys_box(fp), fp.GetReference()
