"""The clear octilinear paths on one layer between two pads, or the
blockers across the narrowest cut when there is none. Pure: synthetic
geometry, no KiCad, except the timing check on the breakout board."""
import dataclasses
import time

from placemat import queries, routes
from placemat.board_geometry import CopperItem
from placemat.values import Box, CopperLayer, Location
from tests.conftest import needs_breakout, needs_kicad
from tests.fixtures import board_geometry, footprint, track

F, B = CopperLayer.F, CopperLayer.B


def _zone(net, x0, y0, x1, y1, layer=F):
    poly = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return CopperItem("zone", net, frozenset([layer]), (poly,), Box(x0, y0, x1, y1))


def _pad(net, x0, y0, x1, y1, layers=(F,)):
    poly = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return CopperItem("pad", net, frozenset(layers), (poly,), Box(x0, y0, x1, y1), owner="U1")


def _geom(copper=(), fps=(), **kw):
    g = board_geometry(list(fps), copper=list(copper), width=50, height=50,
                       extra_nets=("GND", "SIG", "PWR"), clearance=0.2)
    return dataclasses.replace(g, **kw) if kw else g


def _cells(points) -> set:
    """Every 0.1 mm grid node a corridor path's corners cover, so a test can
    check two paths share none: `points` is a `CorridorPath.points`."""
    out = set()
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        steps = max(1, round(max(abs(x1 - x0), abs(y1 - y0)) / queries.GRID_MM))
        for i in range(steps + 1):
            t = i / steps
            out.add((round((x0 + t * (x1 - x0)) / queries.GRID_MM), round((y0 + t * (y1 - y0)) / queries.GRID_MM)))
    return out


def test_a_wall_with_a_gap_lets_the_path_through():
    g = _geom([_zone("GND", 24, 0, 26, 20), _zone("GND", 24, 30, 26, 50)])
    result = queries.corridor(g, Location(5, 25), Location(45, 25), "SIG", 0.3, F)
    assert result.paths and not result.blockers
    assert result.paths[0].points[0] == (5.0, 25.0) and result.paths[0].points[-1] == (45.0, 25.0)


def test_closing_the_gap_leaves_no_path_and_names_the_walls_pieces():
    g = _geom([_zone("GND", 24, 0, 26, 21), _zone("GND", 24, 29, 26, 50), track("GND", 25, 19, 25, 31, w=2.0)])
    result = queries.corridor(g, Location(5, 25), Location(45, 25), "SIG", 0.3, F)
    assert not result.paths
    assert result.blockers
    assert all("GND" in b for b in result.blockers)
    assert any(kind in b for b in result.blockers for kind in ("zone", "track"))


def test_a_foreign_pad_on_another_layer_does_not_block():
    g = _geom([_pad("GND", 24, 24, 26, 26, layers=(B,))])
    result = queries.corridor(g, Location(5, 25), Location(45, 25), "SIG", 0.3, F)
    assert result.paths
    assert result.paths[0].length == 40.0 and result.paths[0].turns == 0


def test_a_through_pad_blocks():
    g = _geom([_pad("GND", 24, 24, 26, 26, layers=(F, B))])
    result = queries.corridor(g, Location(5, 25), Location(45, 25), "SIG", 0.3, F)
    assert result.paths
    assert result.paths[0].length > 40.0        # detoured round it


def test_a_cutout_blocks():
    g = _geom()
    outer = g.outline[0]
    hole = ((23.0, 20.0), (27.0, 20.0), (27.0, 30.0), (23.0, 30.0))
    g = dataclasses.replace(g, board_polygon=(outer, hole))
    result = queries.corridor(g, Location(5, 25), Location(45, 25), "SIG", 0.3, F)
    assert result.paths
    assert result.paths[0].length > 40.0        # detoured round the hole


def test_the_shortest_path_and_up_to_two_disjoint_alternatives():
    g = _geom()
    result = queries.corridor(g, Location(5, 5), Location(45, 45), "SIG", 0.3, F, margin=15.0)
    assert len(result.paths) >= 2
    first, second = _cells(result.paths[0].points), _cells(result.paths[1].points)
    ends = {queries._snap(Location(5, 5)), queries._snap(Location(45, 45))}
    assert not (first - ends) & (second - ends)


def test_ignore_kept_opens_a_route_a_kept_track_closes():
    fp = footprint("J1", 20, 25, w=2.0, h=2.0, nets=("X", "X"))
    g = _geom([track("PWR", 20, 0, 20, 50, w=1.0)], fps=[fp])
    blocked = queries.corridor(g, Location(5, 25), Location(45, 25), "SIG", 0.3, F)
    assert not blocked.paths
    c = fp.pad(1).box.center
    entry = routes.RouteEntry(
        net="PWR",
        tracks=({"layer": "F.Cu", "width": 1.0,
                "a": {"anchor": [fp.inst, "1"], "offset": [20.0 - c.x, 0.0 - c.y]},
                "b": {"anchor": [fp.inst, "1"], "offset": [20.0 - c.x, 50.0 - c.y]}},),
        vias=(),
        parts={fp.inst: {"face": fp.face.value, "pads": {"1": [c.x, c.y]}}})
    filtered = routes.without_kept(g, [entry], tolerance=0.01)
    assert not any(item.kind == "track" and item.net == "PWR" for item in filtered.copper)
    opened = queries.corridor(filtered, Location(5, 25), Location(45, 25), "SIG", 0.3, F)
    assert opened.paths


def test_an_entry_that_no_longer_holds_removes_nothing():
    """A kept entry whose part moved (here: is simply absent) does not draw,
    so there is nothing of its to leave out."""
    g = _geom([track("PWR", 20, 0, 20, 50, w=1.0)])
    entry = routes.RouteEntry(
        net="PWR", tracks=({"layer": "F.Cu", "width": 1.0,
                            "a": {"anchor": ["gone", "1"], "offset": [0.0, 0.0]},
                            "b": {"anchor": ["gone", "1"], "offset": [0.0, 50.0]}},),
        vias=(), parts={"gone": {"face": "front", "pads": {"1": [20.0, 0.0]}}})
    filtered = routes.without_kept(g, [entry], tolerance=0.01)
    assert any(item.kind == "track" and item.net == "PWR" for item in filtered.copper)


@needs_kicad
@needs_breakout
def test_a_corridor_search_on_the_breakout_finishes_well_under_the_target(breakout_pcb):
    """Two pads of the same net, a realistic reach apart (not the board's
    own diagonal): the room a hand-routed net would actually be asked for."""
    from placemat.kicad.read import read_board
    g = read_board(breakout_pcb)
    sig = [(fp, p) for fp in g.footprints for p in fp.pads if p.net and not p.through]
    by_net = {}
    for fp, p in sig:
        by_net.setdefault(p.net, []).append((fp, p))
    net, pads = max(((n, ps) for n, ps in by_net.items() if len(ps) >= 2), key=lambda kv: len(kv[1]))
    centres = [p.box.center for _, p in pads]
    a, b = max(((x, y) for x in centres for y in centres), key=lambda xy: xy[0].distance(xy[1])
              if xy[0].distance(xy[1]) <= 30.0 else -1.0)
    layer = queries._ordered(pads[0][1].layers or g.layers)[0]
    t0 = time.time()
    result = queries.corridor(g, a, b, net, 0.25, layer)
    elapsed = time.time() - t0
    assert elapsed < 5.0, "corridor search took %.2fs" % elapsed
    assert result.paths or result.blockers
