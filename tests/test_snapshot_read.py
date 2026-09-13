"""Slice 1: a snapshot read from the committed Breakout board answers the
questions the old layout script asked pcbnew directly."""
import pytest

from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def test_station_cell_extents_match_the_measured_module_contract(breakout):
    # The old script asserts these every run: after rotation onto the RIGHT
    # edge, power_drop0's world-Y extent is the module's along-edge width and
    # its world-X extent is the module's depth.
    # These footprints draw no courtyard, so the body box IS the physical box.
    box = breakout.cell("power_drop0").box
    assert abs(box.height - 28.600) < 0.01
    assert abs(box.width - 40.250) < 0.01
    assert breakout.cell("power_drop0").copper_box is not None   # the cell's own tracks count
    box = breakout.cell("bus_drop0").box
    assert abs(box.height - 27.050) < 0.01
    assert abs(box.width - 16.650) < 0.01


def test_cells_are_indexed_by_group_name(breakout):
    assert sorted(breakout.cells) == sorted(
        ["power_drop%d" % d for d in range(6)] + ["bus_drop%d" % d for d in range(6)])
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
    p = breakout.cell_pad("bus_drop0", net="CANH", ref_prefix="H")
    assert p.net == "CANH"
    assert p.owner.startswith("H")
    p5 = breakout.cell_pad("power_drop0", number=5, ref_prefix="U")
    assert p5.number == "5"


def test_copper_and_outline_are_collected(breakout):
    kinds = {c.kind for c in breakout.copper}
    assert {"pad", "track", "via", "poly"} <= kinds
    assert breakout.outline_box.width > 100 and breakout.outline_box.height > 200


def test_netclass_clearance_is_resolved_from_the_project(breakout):
    assert breakout.clearance("CANH", "CANL") == pytest.approx(0.2, abs=1e-6)
