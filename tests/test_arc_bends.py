"""bend=Bend.ARC / Bend.ARC_FREE: every corner of a track is a circular arc tangent to
both legs (docs/superpowers/specs/2026-10-02-arc-bends-design.md). Pure: synthetic boards."""
import math
import re
from dataclasses import replace

import pytest

from placemat import geometry as _geometry
from placemat.copper import Track, arc_circle, arc_tracks, round_corners
from placemat.geometry import point_in_polygon
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Bend, CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint, pad

F = CopperLayer.F
W = 0.3
R = 3 * W                                   # the default radius: 3 widths


def L(x, y):
    return Location(x, y)


def _line_dist(p, a, b):
    from placemat.geometry import point_segment_distance
    return point_segment_distance(p, a, b)


# ---------------------------------------------------------------- the arc of a corner

def test_a_right_angle_corner_is_an_arc_tangent_to_both_legs():
    pieces, misfits = round_corners([L(0, 0), L(10, 0), L(10, 10)], R)
    assert misfits == []
    (a0, m0, b0), (a1, m1, b1), (a2, m2, b2) = pieces
    assert m0 is None and m2 is None and m1 is not None
    assert (a0.x, a0.y, b0.x, b0.y) == pytest.approx((0, 0, 10 - R, 0))
    assert (a1.x, a1.y, b1.x, b1.y) == pytest.approx((10 - R, 0, 10, R))
    assert (a2.x, a2.y, b2.x, b2.y) == pytest.approx((10, R, 10, 10))
    s = R * (1 - math.sqrt(0.5))
    assert (m1.x, m1.y) == pytest.approx((10 - s, s), abs=1e-6)         # on the bisector, R from the centre


def test_the_arc_the_three_points_make_is_the_circle_and_its_length_runs_along_it():
    cx, cy, r, a0, sweep = arc_circle(L(10 - R, 0), L(10 - R * (1 - math.sqrt(0.5)), R * (1 - math.sqrt(0.5))),
                                      L(10, R))
    assert (cx, cy, r) == pytest.approx((10 - R, R, R), abs=1e-6)
    assert abs(sweep) == pytest.approx(math.pi / 2, abs=1e-6)
    arc = Track("A", F, W, L(10 - R, 0), L(10, R), mid=L(10 - R * (1 - math.sqrt(0.5)), R * (1 - math.sqrt(0.5))))
    assert arc.length == pytest.approx(R * math.pi / 2, abs=1e-5)


def test_a_straight_track_has_no_mid_and_its_length_is_its_chord():
    t = Track("A", F, W, L(0, 0), L(3, 4))
    assert t.mid is None and t.length == pytest.approx(5.0)


def test_a_45_corner_takes_r_tan_of_half_the_turn_from_each_leg():
    pieces, misfits = round_corners([L(0, 0), L(10, 0), L(15, 5)], R)
    assert misfits == []
    t = R * math.tan(math.radians(22.5))
    assert (pieces[0][2].x, pieces[0][2].y) == pytest.approx((10 - t, 0), abs=1e-6)
    arc = pieces[1]
    assert arc[1] is not None
    cx, cy, r, _, sweep = arc_circle(*arc)
    assert r == pytest.approx(R, abs=1e-5) and abs(sweep) == pytest.approx(math.radians(45), abs=1e-5)
    assert cx == pytest.approx(arc[0].x, abs=1e-5)                       # tangent: the radius to the start is square to the leg


def test_the_turn_either_way_is_an_arc_of_the_same_radius():
    for pts in ([L(0, 0), L(10, 0), L(10, 10)], [L(0, 0), L(10, 0), L(10, -10)],
                [L(10, 10), L(10, 0), L(0, 0)], [L(0, 0), L(0, 10), L(-10, 10)]):
        pieces, misfits = round_corners(pts, R)
        assert misfits == []
        arcs = [p for p in pieces if p[1] is not None]
        assert len(arcs) == 1
        c = arc_circle(*arcs[0])
        assert c[2] == pytest.approx(R, abs=1e-5) and abs(c[4]) == pytest.approx(math.pi / 2, abs=1e-5)


def test_points_in_a_line_are_not_corners():
    pieces, misfits = round_corners([L(0, 0), L(5, 0), L(10, 0)], R)
    assert misfits == [] and all(p[1] is None for p in pieces)
    assert sum(p[0].distance(p[2]) for p in pieces) == pytest.approx(10.0)


def test_a_leg_too_short_for_the_two_arcs_at_its_ends_is_a_misfit_though_each_fits_alone():
    pts = [L(0, 0), L(10, 0), L(10, 1.5), L(20, 1.5)]                  # two right angles, 1.5 mm between
    pieces, misfits = round_corners(pts, R)
    assert len(misfits) == 1
    m = misfits[0]
    assert "(10.00, 0.00)" in str(m) and "(10.00, 1.50)" in str(m) and "1.50 mm" in str(m)
    # each corner alone fits
    assert round_corners(pts[:3], R)[1] == [] and round_corners(pts[1:], R)[1] == []


def test_a_first_leg_shorter_than_the_arc_takes_is_a_misfit():
    _, misfits = round_corners([L(0, 0), L(0.5, 0), L(0.5, 10)], R)
    assert len(misfits) == 1 and "0.50 mm" in str(misfits[0])


def test_a_leg_exactly_the_two_tangent_lengths_fits_with_no_straight_between():
    pts = [L(0, 0), L(10, 0), L(10, 2 * R), L(20, 2 * R)]
    pieces, misfits = round_corners(pts, R)
    assert misfits == []
    assert [p[1] is not None for p in pieces] == [False, True, True, False]


def test_arc_tracks_are_tracks_that_join_end_to_end():
    ops, misfits = arc_tracks("A", F, W, [L(0, 0), L(10, 0), L(10, 10)], R)
    assert misfits == []
    assert all(isinstance(t, Track) for t in ops) and [t.mid is not None for t in ops] == [False, True, False]
    for a, b in zip(ops, ops[1:]):
        assert (a.end.x, a.end.y) == (b.start.x, b.start.y)               # the same nanometre: one track to KiCad


# ---------------------------------------------------------------- the polygon

def _on_arc_distance(p, t):
    cx, cy, r, a0, sweep = arc_circle(t.start, t.mid, t.end)
    ang = math.atan2(p[1] - cy, p[0] - cx)
    rel = (ang - a0) % (2 * math.pi) if sweep > 0 else -((a0 - ang) % (2 * math.pi))
    inside = (0 <= rel <= sweep) if sweep > 0 else (sweep <= rel <= 0)
    if inside:
        return abs(math.hypot(p[0] - cx, p[1] - cy) - r)
    return min(math.dist(p, (t.start.x, t.start.y)), math.dist(p, (t.end.x, t.end.y)))


def test_the_polygon_holds_the_copper_and_stands_no_further_out_than_the_arc_error():
    arc = Track("A", F, W, L(10 - R, 0), L(10, R), mid=L(10 - R * (1 - math.sqrt(0.5)), R * (1 - math.sqrt(0.5))))
    poly = arc.polygon
    err = Settings().geometry_arc_error_nm / 1e6
    cap_slack = W / 2 * (1 / math.cos(math.pi / (2 * Settings().geometry_cap_steps)) - 1)
    for p in poly:
        past = _on_arc_distance(p, arc) - W / 2
        assert -1e-9 <= past <= max(err, cap_slack) + 1e-9, (p, past)
    cx, cy, r, a0, sweep = arc_circle(arc.start, arc.mid, arc.end)
    for k in range(0, 41):                                                # the true copper's edges lie in the polygon
        a = a0 + sweep * k / 40
        for rr in (r - W / 2, r, r + W / 2):
            q = (cx + rr * math.cos(a), cy + rr * math.sin(a))
            if k in (0, 40) and rr != r:
                continue
            assert point_in_polygon(q, poly) or min(_line_dist(q, poly[i], poly[(i + 1) % len(poly)])
                                                    for i in range(len(poly))) < 1e-7, (k, rr)


def test_the_polygon_of_an_arc_is_not_the_chords_polygon():
    mid = L(10 - R * (1 - math.sqrt(0.5)), R * (1 - math.sqrt(0.5)))
    arc = Track("A", F, W, L(10 - R, 0), L(10, R), mid=mid)
    chord = Track("A", F, W, L(10 - R, 0), L(10, R))
    assert arc.polygon != chord.polygon and arc.box.right > chord.box.right - 1e-9


# ---------------------------------------------------------------- the board

def _scene(extra=(), clearance=0.2, **settings):
    u1 = footprint("U1", 10, 10, nets=("A", "A"))                           # pad 1 at (8.6, 10)
    g = board_geometry([u1] + list(extra), width=60, height=60, clearance=clearance, extra_nets=("B",))
    b = Board(g, edge_margin=0.5, keep_going=True, settings=Settings(**settings))
    b.place(Part("u1"), at=L(10, 10))
    for fp in extra:
        b.place(Part(fp.inst), at=fp.location)
    return b


def _pad_at(ref, x, y, net="B", size=0.2):
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face
    p = pad(ref, ref.lower(), "1", net, x, y, size, size)
    body = Box(x - size / 2, y - size / 2, x + size / 2, y + size / 2)
    return Footprint(ref, ref.lower(), None, ref, L(x, y), 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,))


def _tracks(plan):
    return [op for op in plan.copper if isinstance(op, Track)]


def _corner_track(b, **kw):
    kw.setdefault("bend", Bend.ARC)
    return b.track(Net("A"), [PadRef(Part("u1"), 1), (20.0, 10.0), (20.0, 20.0)], layer=F, width=W, **kw)


def test_a_track_with_arc_corners_is_straight_arc_straight():
    b = _scene()
    _corner_track(b)
    plan = b.resolve()
    ts = _tracks(plan)
    assert [t.mid is not None for t in ts] == [False, True, False]
    assert ts[0].start == L(8.6, 10.0) and ts[2].end == L(20.0, 20.0)
    assert ts[1].length == pytest.approx(R * math.pi / 2, abs=1e-5)
    assert not [f for f in plan.findings if f.kind == "copper"]


def test_two_corners_are_two_arcs():
    b = _scene()
    b.track(Net("A"), [PadRef(Part("u1"), 1), (20.0, 10.0), (20.0, 20.0), (30.0, 20.0)], layer=F, width=W,
            bend=Bend.ARC)
    ts = _tracks(b.resolve())
    assert [t.mid is not None for t in ts] == [False, True, False, True, False]


def test_the_radius_is_the_setting_times_the_width_and_radius_overrides_it():
    for kw, settings, want in (({}, {}, 3 * W), ({}, {"copper_arc_radius_track_widths": 6.0}, 6 * W),
                               ({"radius": 2.0}, {}, 2.0)):
        b = _scene(**settings)
        _corner_track(b, **kw)
        (arc,) = [t for t in _tracks(b.resolve()) if t.mid is not None]
        assert arc_circle(arc.start, arc.mid, arc.end)[2] == pytest.approx(want, abs=1e-5)


def test_the_width_in_the_rule_is_the_tracks_own():
    b = _scene()
    b.track(Net("A"), [PadRef(Part("u1"), 1), (20.0, 10.0), (20.0, 20.0)], layer=F, width=0.5, bend=Bend.ARC)
    (arc,) = [t for t in _tracks(b.resolve()) if t.mid is not None]
    assert arc_circle(arc.start, arc.mid, arc.end)[2] == pytest.approx(3 * 0.5, abs=1e-5)       # the default widths times its own width


def test_a_radius_not_above_half_the_width_is_refused_when_declared():
    with pytest.raises(ValueError, match="radius"):
        _corner_track(_scene(), radius=W / 2)


def test_chamfer_bridge_and_a_radius_without_an_arc_are_refused():
    b = _scene()
    with pytest.raises(TypeError, match="chamfer"):
        _corner_track(b, chamfer=0.5)
    with pytest.raises(TypeError, match="bridge"):
        _corner_track(b, bridge=True)
    with pytest.raises(TypeError, match="radius"):
        b.track(Net("A"), [PadRef(Part("u1"), 1), (20.0, 10.0)], layer=F, width=W, radius=1.0)


def test_a_corner_the_arc_does_not_fit_is_a_finding_and_the_track_is_not_drawn():
    b = _scene()
    b.track(Net("A"), [PadRef(Part("u1"), 1), (9.5, 10.0), (9.5, 20.0)], layer=F, width=W, bend=Bend.ARC, radius=1.2)
    plan = b.resolve()
    assert _tracks(plan) == []
    hits = [str(f) for f in plan.findings if f.kind == "copper" and "arc" in str(f)]
    assert len(hits) == 1
    assert "(9.50, 10.00)" in hits[0] and "90 degrees" in hits[0] and "1.20 mm" in hits[0] and "0.90 mm" in hits[0]
    assert "not drawn" in hits[0] and "radius=" in hits[0]


def test_a_smaller_radius_fits_where_the_default_does_not():
    b = _scene()
    b.track(Net("A"), [PadRef(Part("u1"), 1), (9.5, 10.0), (9.5, 20.0)], layer=F, width=W, bend=Bend.ARC,
            radius=0.6)
    plan = b.resolve()
    assert [t.mid is not None for t in _tracks(plan)] == [False, True, False]


def test_arc_free_runs_each_leg_at_its_own_angle_with_arcs_at_the_corners():
    b = _scene()
    b.track(Net("A"), [PadRef(Part("u1"), 1), (18.0, 14.0), (28.0, 11.0)], layer=F, width=W, bend=Bend.ARC_FREE)
    ts = _tracks(b.resolve())
    assert [t.mid is not None for t in ts] == [False, True, False]
    first, last = ts[0], ts[2]
    ang = lambda t: math.degrees(math.atan2(t.end.y - t.start.y, t.end.x - t.start.x))
    assert ang(first) == pytest.approx(math.degrees(math.atan2(4.0, 9.4)), abs=1e-4)
    assert ang(last) == pytest.approx(math.degrees(math.atan2(-3.0, 10.0)), abs=1e-4)


def test_arc_plans_the_legs_octilinear_as_a_plain_track_does():
    b = _scene()
    b.track(Net("A"), [PadRef(Part("u1"), 1), L(28.6, 20.0)], layer=F, width=W, bend=Bend.ARC)
    ts = _tracks(b.resolve())
    straights = [t for t in ts if t.mid is None]
    for t in straights:
        dx, dy = abs(t.end.x - t.start.x), abs(t.end.y - t.start.y)
        assert dx < 1e-6 or dy < 1e-6 or abs(dx - dy) < 1e-6
    assert len([t for t in ts if t.mid is not None]) == 1                 # the one 45 between a diagonal and a straight


# ---------------------------------------------------------------- clearance at the arc's true distance
# the track runs east along y=10 to the corner v=(20, 10) and south; its arc (R=1.2) is centred at (18.8, 11.2)

V = (20.0, 10.0)
C = (18.8, 11.2)


def _gap_to_arc(pad_pts, arc):
    """The least distance from a pad's four corners and edges to the arc's copper edge (analytic)."""
    best = 1e9
    n = len(pad_pts)
    for i in range(n):
        a, c = pad_pts[i], pad_pts[(i + 1) % n]
        for k in range(0, 201):
            q = (a[0] + (c[0] - a[0]) * k / 200, a[1] + (c[1] - a[1]) * k / 200)
            best = min(best, _on_arc_distance(q, arc) - W / 2)
    return best


def _conflicts(plan, net="B"):
    return [str(f) for f in plan.findings if f.kind == "copper" and " is " in str(f) and "mm from %s copper" % net in str(f)]


def _gap_of(text):
    return float(re.search(r" is (\d+\.\d+) mm from", text).group(1))


def test_a_pad_on_the_outside_of_the_corner_clears_the_chamfer_but_not_the_arc():
    near = _pad_at("R1", V[0], V[1])                                  # centred on the corner: the arc hugs it, the chamfer cuts it away
    plain = _scene([near], clearance=0.3)
    _corner_track(plain, bend=None)
    assert _conflicts(plain.resolve()) == []                          # the 1.0 mm chamfer's 45 stands 0.4 mm off it

    b = _scene([near], clearance=0.3)
    _corner_track(b, radius=1.2)                                       # the 1.2 mm arc hugs the pad
    plan = b.resolve()
    hits = _conflicts(plan)
    assert len(hits) == 1 and hits[0].startswith("copper A: arc track A (18.80, 10.00)-(20.00, 11.20) is ") and "the arc of its corner" in hits[0] and "a smaller radius= there keeps clear" in hits[0]
    arc = next(t for t in _tracks(plan) if t.mid is not None)
    corners = [(V[0] - 0.1, V[1] - 0.1), (V[0] + 0.1, V[1] - 0.1), (V[0] + 0.1, V[1] + 0.1), (V[0] - 0.1, V[1] + 0.1)]
    assert _gap_of(hits[0]) == pytest.approx(_gap_to_arc(corners, arc), abs=0.006)


def test_a_pad_inside_the_turn_clears_the_arc_but_not_the_chamfer():
    q = 0.6                                                           # from the arc's centre toward the corner
    s = math.sqrt(0.5)
    near = _pad_at("R1", C[0] + q * s, C[1] - q * s)
    plain = _scene([near])
    _corner_track(plain, bend=None)
    assert len(_conflicts(plain.resolve())) >= 1
    b = _scene([near])
    _corner_track(b)
    assert _conflicts(b.resolve()) == []


def test_the_gap_reported_is_the_arcs_true_distance_not_its_chords():
    near = _pad_at("R1", V[0], V[1])
    b = _scene([near], clearance=0.3)
    _corner_track(b)
    plan = b.resolve()
    arc = next(t for t in _tracks(plan) if t.mid is not None)
    chord_gap = min(_line_dist(p, (arc.start.x, arc.start.y), (arc.end.x, arc.end.y))
                    for p in [(V[0] - 0.1, V[1] + 0.1)]) - W / 2
    assert _gap_of(_conflicts(plan)[0]) < chord_gap - 0.1             # the chord is a long way further from the corner


# ---------------------------------------------------------------- native and Python judge it alike

@pytest.mark.skipif(_geometry._native is None, reason="no native module")
def test_native_and_python_judge_the_arc_against_a_pad_alike(monkeypatch):
    results = []
    for native in (_geometry._native, None):
        monkeypatch.setattr(_geometry, "_native", native)
        out = []
        for dx in (-0.05, 0.0, 0.05, 0.4):
            near = _pad_at("R1", V[0] + dx, V[1] + dx)
            b = _scene([near], clearance=0.3)
            _corner_track(b)
            plan = b.resolve()
            out.append(sorted(str(f) for f in plan.findings if f.kind == "copper"))
        results.append(out)
    assert results[0] == results[1] and any(results[0])


@pytest.mark.skipif(_geometry._native is None, reason="no native module")
def test_native_and_python_give_the_same_gap_for_an_arc_polygon(monkeypatch):
    arc = Track("A", F, W, L(10 - R, 0), L(10, R), mid=L(10 - R * (1 - math.sqrt(0.5)), R * (1 - math.sqrt(0.5))))
    other = ((9.9, -0.1), (10.1, -0.1), (10.1, 0.1), (9.9, 0.1))
    got = []
    for native in (_geometry._native, None):
        monkeypatch.setattr(_geometry, "_native", native)
        got.append(_geometry.poly_distance(arc.polygon, other))
    assert got[0] == pytest.approx(got[1], abs=1e-9)


# ---------------------------------------------------------------- crossings

def test_an_arc_track_crossing_another_nets_track_is_a_finding_not_a_bridge():
    b = _scene()
    _corner_track(b)
    b.track(Net("B"), [L(19.0, 8.0), L(19.0, 14.0)], layer=F, width=W, bend=None, chamfer=0)
    plan = b.resolve()
    assert any("cross" in str(f) for f in plan.findings if f.kind == "copper")


# ---------------------------------------------------------------- what already existed is unchanged

def test_a_straight_track_and_its_shape_digest_as_before():
    from placemat import reuse
    from placemat.layout import _shape_of
    t = Track("A", F, W, L(0, 0), L(3, 4))
    assert "mid" not in reuse.canonical(t)
    assert "arc" not in reuse.canonical(_shape_of(t))
    arc = Track("A", F, W, L(10 - R, 0), L(10, R), mid=L(9.6, 0.4))
    assert "mid" in reuse.canonical(arc) and _shape_of(arc).arc == (9.6, 0.4)


def test_the_preview_draws_an_arc_as_an_svg_arc_of_its_radius():
    import xml.etree.ElementTree as ET
    from placemat.preview import draw
    b = _scene()
    _corner_track(b, radius=1.2)
    root = ET.fromstring(draw(b.resolve()))
    paths = [e for e in root.iter() if (e.get("class") or "") == "track" and e.tag.endswith("path")]
    assert len(paths) == 1
    d = paths[0].get("d")
    assert " A 1.2 1.2 0 0 1 " in d                       # radius 1.2, the short way round, clockwise on the page
    assert len([e for e in root.iter() if (e.get("class") or "") == "track" and e.tag.endswith("line")]) == 2
