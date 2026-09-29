"""measure --copper: the segments a board carries per net, each end named by
what it lands on, a leg off 0/45/90 flagged. Pure: synthetic boards."""
from placemat.describe import copper_lines, copper_segments
from tests.fixtures import board_geometry, footprint, track


def _geom():
    u1 = footprint("U1", 10, 10, inst="u1", nets=("A", "B"))          # pad 1 at (8.6, 10)
    legs = [track("A", 8.6, 10.0, 5.0, 10.0), track("A", 5.0, 10.0, 3.0, 8.845299), track("B", 11.4, 10.0, 14.0, 10.0)]
    return board_geometry([u1], copper=legs, width=30, height=30)


def test_each_segment_names_what_its_ends_land_on():
    segs = copper_segments(_geom(), ["A"])
    assert [(s["start_on"], s["end_on"]) for s in segs] == [("U1.1", "track"), ("track", "-")]
    assert segs[0]["angle"] == 0 and segs[0]["octilinear"]
    assert not segs[1]["octilinear"] and abs(segs[1]["angle"] - 150.0) < 0.01     # up and west: 150 from east


def test_the_lines_flag_a_leg_off_the_octilinear_angles():
    text = "\n".join(copper_lines(_geom(), ["A"]))
    assert "A  F.Cu  0.30" in text and "U1.1" in text
    assert "150.0 deg  off 0/45/90" in text, text
    assert "B " not in text


def test_every_net_when_none_is_named():
    assert {s["net"] for s in copper_segments(_geom(), [])} == {"A", "B"}
