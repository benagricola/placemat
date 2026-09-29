"""check keep-out names the two pieces of copper that set its distance: a
pad by its part and number, a track or via by its net and ends, and says
when both are pads of one part - a distance its footprint sets, not
something placement can change. Pure: synthetic boards."""
import pytest

from placemat.checks import keep_out
from tests.fixtures import board_geometry, footprint, track


def test_keep_out_judges_layout_and_names_a_nearer_pair_its_footprint_sets():
    """U1 is both the switcher (aggressor on SW) and the sensor (Pm.Sensitive
    FB): its own FB pad sits 1.8 mm from its own SW pad, closer than L1's SW
    pad (5.0 mm). The footprint sets that distance and no placement changes
    it, so the verdict judges L1's pad and names both pairs."""
    u = footprint("U1", 14, 13, nets=("FB", "SW"), fields={"Pm.Aggressor": "true", "Pm.Sensitive": "FB"})
    l = footprint("L1", 20, 13, nets=("SW", "VOUT"), fields={"Pm.Aggressor": "true"})
    (v,) = keep_out(board_geometry([u, l]), limit_mm=2.0)
    assert v.value == pytest.approx(5.0) and v.ok
    assert "L1 pad 1 (SW)" in v.note and "U1 pad 1 (FB)" in v.note
    assert "U1's own pads are 1.80 mm apart" in v.note and "its footprint sets" in v.note, v.note


def test_keep_out_names_a_track_when_it_is_the_nearest_copper():
    """A track drawn between U1 and L1's SW pads runs closer to R1's FB pad
    than either raw pad does: the verdict names the track, by net and ends,
    not a pad."""
    u = footprint("U1", 10, 10, nets=("VIN", "SW"), fields={"Pm.Aggressor": "true"})
    l = footprint("L1", 20, 10, nets=("SW", "VOUT"), fields={"Pm.Aggressor": "true"})
    r = footprint("R1", 15, 12, nets=("VOUT", "FB"), fields={"Pm.Sensitive": "fb"})
    sw = track("SW", 11.4, 10, 18.6, 10, w=0.3)
    (v,) = keep_out(board_geometry([u, l, r], copper=[sw]), limit_mm=2.0)
    assert v.value == pytest.approx(1.35) and v.ok is False
    assert "track SW (11.40, 10.00)-(18.60, 10.00)" in v.note
    assert "R1 pad 2 (FB)" in v.note
    assert "both pads of" not in v.note
