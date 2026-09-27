"""A via's copper is drawn with every edge on or outside its circle, as a
track's round end is: drawn inside it, a gap to a pad between two vertices
reads up to 2% of the radius longer than it is (a clearance 0.1575 mm in
KiCad passed as 0.16)."""
import math

from placemat.copper import Via
from placemat.geometry import point_segment_distance
from placemat.values import Location


def _inner_reach(poly, c):
    n = len(poly)
    return min(point_segment_distance((c.x, c.y), poly[i], poly[(i + 1) % n]) for i in range(n))


def test_a_vias_polygon_holds_its_whole_circle():
    v = Via("GND", Location(10.0, 10.0), 0.2, 0.45)
    assert _inner_reach(v.polygon, v.at) >= 0.225 - 1e-9


def test_the_via_ring_a_site_is_judged_by_holds_its_whole_circle():
    from placemat.geometry import via_ring
    ring = via_ring(Location(3.0, 4.0), 0.45)
    assert _inner_reach(ring, Location(3.0, 4.0)) >= 0.225 - 1e-9
    assert max(math.dist(p, (3.0, 4.0)) for p in ring) < 0.225 * 1.03       # and not much more
