"""`placemat nets`: one row per net with at least two pads - pad count and
parts, span (the minimum spanning tree over pad centres), routed length,
detour, vias, layers, pour. Pure: synthetic boards; a couple of tests read
the committed Breakout to check the numbers against a hand-computed MST and
pcbnew's own track lengths and via counts."""
import pytest

from placemat import nets
from placemat.board_geometry import CopperItem, Footprint
from placemat.geometry import circle_polygon
from placemat.values import Box, CopperLayer, Face, Location
from tests.conftest import needs_breakout, needs_kicad
from tests.fixtures import board_geometry, pad, track

F, B, IN1 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1


def _single(ref, x, y, net, inst=None):
    """A one-pad part, its pad centred on (x, y): the minimal shape span_of
    an MST needs to measure between parts."""
    p = pad(ref, inst or ref.lower(), 1, net, x, y, 0.5, 0.5)
    body = Box(x - 1.0, y - 1.0, x + 1.0, y + 1.0)
    return Footprint(ref, inst or ref.lower(), None, ref, Location(x, y), 0.0, Face.FRONT, body, body, body, (p,))


def _via(net, x, y, size=0.6, drill=0.3):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, frozenset([F, B]), (ring,), Box.of_points(ring), None, 0.0, drill, ((x, y),))


def _rows(fps, copper=(), inst=False, planes=frozenset()):
    g = board_geometry(fps, copper=copper, width=100, height=100)
    return {r["net"]: r for r in nets.nets_rows(g, planes, inst=inst)}


def test_a_net_with_one_pad_is_left_out():
    g = board_geometry([_single("U1", 0.0, 0.0, "A")], width=50, height=50)
    assert nets.nets_rows(g) == []


def test_pad_count_and_parts_by_ref_or_instance():
    fps = [_single("U1", 0.0, 0.0, "A", inst="board.u1"), _single("U2", 10.0, 0.0, "A", inst="board.u2")]
    by_ref = _rows(fps)["A"]
    assert by_ref["pads"] == 2 and by_ref["parts"] == ["U1", "U2"]
    by_inst = _rows(fps, inst=True)["A"]
    assert by_inst["parts"] == ["board.u1", "board.u2"]


def test_a_part_with_two_pads_on_one_net_counts_both_pads_once_as_a_part():
    p1 = pad("U1", "u1", 1, "A", 0.0, 0.0, 0.5, 0.5)
    p2 = pad("U1", "u1", 2, "A", 1.0, 0.0, 0.5, 0.5)
    body = Box(-1.0, -1.0, 2.0, 1.0)
    fp = Footprint("U1", "u1", None, "U1", Location(0.5, 0.0), 0.0, Face.FRONT, body, body, body, (p1, p2))
    other = _single("U2", 10.0, 0.0, "A")
    row = _rows([fp, other])["A"]
    assert row["pads"] == 3 and row["parts"] == ["U1", "U2"]


def test_the_span_is_the_minimum_spanning_tree_not_the_longest_pair():
    """A 3-4-5 triangle: the tree is the two short legs (7), never the 5 mm
    hypotenuse some pairing could pick instead."""
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 3.0, 0.0, "A"), _single("U3", 3.0, 4.0, "A")]
    assert _rows(fps)["A"]["span"] == pytest.approx(7.0)


def test_routed_length_sums_the_tracks_own_lengths_not_their_chords():
    """A track's `length_mm` is what read.py takes from pcbnew's GetLength():
    an arc's real path, not the straight line between its ends. The nets
    table must add that up, not recompute a chord."""
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 10.0, 0.0, "A")]
    copper = (track("A", 0.0, 0.0, 5.0, 0.0, length=6.0), track("A", 5.0, 0.0, 10.0, 0.0, length=7.5))
    row = _rows(fps, copper)["A"]
    assert row["routed"] == pytest.approx(13.5)


def test_detour_is_routed_over_span():
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 10.0, 0.0, "A")]
    copper = (track("A", 0.0, 0.0, 10.0, 0.0, length=13.0),)
    row = _rows(fps, copper)["A"]
    assert row["span"] == pytest.approx(10.0)
    assert row["detour"] == pytest.approx(1.3)


def test_detour_is_a_dash_when_the_net_carries_no_track():
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 10.0, 0.0, "A")]
    row = _rows(fps)["A"]
    assert row["routed"] == 0.0 and row["detour"] is None
    assert "-" in [l for l in nets.nets_lines([row]) if "A" in l][0]


def test_vias_count_and_layers_come_from_the_tracks_only():
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 10.0, 0.0, "A")]
    copper = (track("A", 0.0, 0.0, 10.0, 0.0, layer=IN1), _via("A", 5.0, 0.0))
    row = _rows(fps, copper)["A"]
    assert row["vias"] == 1
    assert row["layers"] == ["In1.Cu"]


def test_layers_are_in_stackup_order_not_alphabetical():
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 10.0, 0.0, "A")]
    copper = (track("A", 0.0, 0.0, 5.0, 0.0, layer=B), track("A", 5.0, 0.0, 10.0, 0.0, layer=F))
    assert _rows(fps, copper)["A"]["layers"] == ["F.Cu", "B.Cu"]


def test_a_pour_net_is_flagged_from_the_planes_given():
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 10.0, 0.0, "A")]
    assert _rows(fps, planes={"A"})["A"]["pour"] is True
    assert _rows(fps)["A"]["pour"] is False


def test_rows_sort_by_span_largest_first_by_default():
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 1.0, 0.0, "A"),
          _single("U3", 0.0, 0.0, "B"), _single("U4", 20.0, 0.0, "B")]
    rows = nets.sort_rows(_rows(fps).values(), "span")
    assert [r["net"] for r in rows] == ["B", "A"]


def test_sort_takes_any_column_name():
    fps = [_single("U1", 0.0, 0.0, "A"), _single("U2", 1.0, 0.0, "A"), _single("U3", 2.0, 0.0, "A"),
          _single("U4", 0.0, 0.0, "B"), _single("U5", 1.0, 0.0, "B")]
    rows = nets.sort_rows(_rows(fps).values(), "pads")
    assert [r["net"] for r in rows] == ["A", "B"]


def test_an_unknown_sort_column_is_refused():
    with pytest.raises(ValueError):
        nets.sort_rows([], "bogus")


def test_no_nets_says_so():
    assert nets.nets_lines([]) == ["no net on this board joins two or more pads"]


def test_the_docs_describe_the_nets_command_and_the_parts_warning():
    from pathlib import Path
    api = Path("skills/placemat/references/api.md").read_text()
    assert "placemat nets" in api and "--sort" in api and "--inst" in api
    assert "no order number" in api and "parts.order_fields" in api


@needs_kicad
@needs_breakout
def test_nets_on_the_breakout_match_a_hand_computed_mst_and_pcbnew_s_own_counts(breakout_pcb):
    """PERMIT_A and CAN_S1_P, independently computed straight off pcbnew (a
    fresh Prim's MST over GetPosition(), GetLength() summed over the net's
    tracks, GetNetname() vias counted): the nets table must match, allowing
    for the pad centre placemat measures (the outline's box) differing very
    slightly from pcbnew's own pad anchor."""
    from placemat.kicad.read import read_board
    from placemat.kicad.route import plane_nets_of
    g = read_board(breakout_pcb)
    rows = {r["net"]: r for r in nets.nets_rows(g, plane_nets_of(breakout_pcb))}
    permit = rows["PERMIT_A"]
    assert permit["pads"] == 5 and permit["parts"] == ["U4", "U5", "U6", "U7", "U8"]
    assert permit["span"] == pytest.approx(145.432197, abs=0.05)
    assert permit["routed"] == pytest.approx(255.527415, abs=0.05)
    assert permit["vias"] == 0 and permit["layers"] == ["B.Cu"]
    can = rows["CAN_S1_P"]
    assert can["pads"] == 4 and can["parts"] == ["H3", "H5", "U2", "U3"]
    assert can["span"] == pytest.approx(34.234038, abs=0.05)
    assert can["routed"] == pytest.approx(45.210103, abs=0.05)
    assert rows["GND"]["pour"] is True
    assert permit["pour"] is False


@needs_kicad
@needs_breakout
def test_the_nets_command_filters_sorts_and_gives_json(breakout_pcb, capsys):
    from placemat.cli import main
    assert main(["nets", str(breakout_pcb), "--net", "GND", "--format", "json"]) == 0
    import json
    doc = json.loads(capsys.readouterr().out)
    assert [r["net"] for r in doc["nets"]] == ["GND"]
    assert doc["nets"][0]["pour"] is True

    assert main(["nets", str(breakout_pcb), "--sort", "pads"]) == 0
    out = capsys.readouterr().out
    assert "GND" in out and "PERMIT_A" in out


def test_sorting_by_name_reads_a_to_z():
    """Numbers sort largest first; a name reads as a list does, A to Z."""
    from placemat.nets import sort_rows
    rows = [{"net": n, "pads": 2, "parts": [], "span": 1.0, "routed": 0.0, "detour": None, "vias": 0,
             "layers": [], "pour": False} for n in ("B", "C", "A")]
    assert [r["net"] for r in sort_rows(rows, "net")] == ["A", "B", "C"]


def test_a_pin_drawn_as_several_lands_counts_once():
    """A pin drawn as two lands (a split thermal land) is one pad of its
    net, at the centre of the box round its lands."""
    import dataclasses
    from placemat import nets
    from tests.fixtures import board_geometry, footprint, pad
    u = footprint("U1", 10, 10, inst="u1", nets=("A", "B"))
    u = dataclasses.replace(u, pads=(pad("U1", "u1", 1, "A", 9.0, 10.0), pad("U1", "u1", 1, "A", 11.0, 10.0),
                                     pad("U1", "u1", 2, "B", 14.0, 10.0)))
    r = footprint("R1", 30, 10, inst="r1", nets=("A", "C"))
    (row,) = [x for x in nets.nets_rows(board_geometry([u, r], width=60, height=60)) if x["net"] == "A"]
    assert row["pads"] == 2
    assert row["span"] == pytest.approx(abs(r.pads[0].location.x - 10.0) + 0.0, abs=0.01)
