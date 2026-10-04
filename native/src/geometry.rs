//! Pure geometry predicates, ported from `src/placemat/geometry.py`.
//!
//! These mirror the Python "plain" (non-grid) code paths expression-for-
//! expression so IEEE-754 double arithmetic lands on the same bit pattern
//! Python would produce, and so the same boundary cases (an edge exactly on
//! a threshold, two points exactly coincident) fall the same way. Python's
//! `_Prepared` grid cache (for polygons with 24+ vertices, reused across many
//! calls against the same big polygon) is NOT ported here: the plain test
//! below returns the identical boolean answer for any polygon size, only
//! slower for a many-vertex polygon tested repeatedly, so Python keeps that
//! cache and calls into this module only for the plain path. See
//! docs/superpowers/specs/2026-09-24-native-core-design.md.

pub type Point = (f64, f64);
pub type Polygon = [Point];

fn cross(o: Point, a: Point, b: Point) -> f64 {
    (a.0 - o.0) * (b.1 - o.1) - (a.1 - o.1) * (b.0 - o.0)
}

pub fn point_in_polygon(p: Point, poly: &Polygon) -> bool {
    let (x, y) = p;
    let mut inside = false;
    let n = poly.len();
    for i in 0..n {
        let (x1, y1) = poly[i];
        let (x2, y2) = poly[(i + 1) % n];
        if (y1 > y) != (y2 > y) {
            let xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1);
            if x < xin {
                inside = !inside;
            }
        }
    }
    inside
}

pub fn segments_intersect(p1: Point, p2: Point, q1: Point, q2: Point) -> bool {
    let d1 = cross(q1, q2, p1);
    let d2 = cross(q1, q2, p2);
    let d3 = cross(p1, p2, q1);
    let d4 = cross(p1, p2, q2);
    ((d1 > 0.0) != (d2 > 0.0))
        && ((d3 > 0.0) != (d4 > 0.0))
        && d1 != 0.0
        && d2 != 0.0
        && d3 != 0.0
        && d4 != 0.0
}

fn edges(poly: &Polygon) -> impl Iterator<Item = (Point, Point)> + '_ {
    let n = poly.len();
    (0..n).map(move |i| (poly[i], poly[(i + 1) % n]))
}

pub fn point_segment_distance(p: Point, a: Point, b: Point) -> f64 {
    point_segment_distance_below(p, a, b, f64::INFINITY)
}

/// `point_segment_distance` (CPython's `math.hypot`, bit for bit), or something larger than `best` when
/// the distance is clearly past it: the libm hypot, within a unit or two in the last place of the exact
/// one, rules out most pairs of a `min` over many without the exact hypot's cost.
#[inline]
pub(crate) fn point_segment_distance_below(p: Point, a: Point, b: Point, best: f64) -> f64 {
    let (ax, ay) = a;
    let (bx, by) = b;
    let (px, py) = p;
    let (dx, dy) = (bx - ax, by - ay);
    let (ex, ey) = if dx == 0.0 && dy == 0.0 {
        (px - ax, py - ay)
    } else {
        let t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy);
        let t = t.max(0.0).min(1.0);
        (px - (ax + t * dx), py - (ay + t * dy))
    };
    // 1e-14 relative is many units in the last place (2.2e-16): a pair this far over cannot be the minimum. The
    // square root of the sum of squares is within a few units of the exact distance (a sum that underflows or
    // overflows is the exact hypot's, or is far past `best`).
    if (ex * ex + ey * ey).sqrt() > best * (1.0 + 1e-14) {
        return f64::INFINITY;
    }
    crate::exact::hypot(ex, ey)
}

fn within(p: Point, x0: f64, y0: f64, x1: f64, y1: f64) -> bool {
    x0 <= p.0 && p.0 <= x1 && y0 <= p.1 && p.1 <= y1
}

fn bounds(poly: &Polygon) -> (f64, f64, f64, f64) {
    let xs = poly.iter().map(|p| p.0);
    let ys = poly.iter().map(|p| p.1);
    let x0 = xs.clone().fold(f64::INFINITY, f64::min);
    let x1 = xs.fold(f64::NEG_INFINITY, f64::max);
    let y0 = ys.clone().fold(f64::INFINITY, f64::min);
    let y1 = ys.fold(f64::NEG_INFINITY, f64::max);
    (x0, y0, x1, y1)
}

fn edge_meets(p1: Point, p2: Point, x0: f64, y0: f64, x1: f64, y1: f64) -> bool {
    p1.0.min(p2.0) <= x1 && p1.0.max(p2.0) >= x0 && p1.1.min(p2.1) <= y1 && p1.1.max(p2.1) >= y0
}

fn strictly_inside(p: Point, poly: &Polygon) -> bool {
    point_in_polygon(p, poly) && edges(poly).all(|(q1, q2)| point_segment_distance(p, q1, q2) > 1e-9)
}

const NUDGE: f64 = 1e-7; // off a boundary, well past strictness (1e-9) and well inside the 1e-6 coordinate grid

/// Whether the interiors meet beside one polygon's edges, ported from
/// `geometry._along_shared_boundary`. With no edge crossing another and no
/// vertex strictly inside the other polygon, the interiors can still share
/// area when the boundaries coincide - the same rectangle, or one slid
/// along a side. Each edge is split where the other polygon's vertices lie
/// on it, so each piece is wholly inside, outside or on the other's
/// boundary; a point just off a piece's midpoint, on either side, inside
/// both polygons is shared interior.
fn along_shared_boundary(edges: &[(Point, Point)], others: &[Point], in_a: impl Fn(Point) -> bool, in_b: impl Fn(Point) -> bool) -> bool {
    for &(p1, p2) in edges {
        let (dx, dy) = (p2.0 - p1.0, p2.1 - p1.1);
        let n2 = dx * dx + dy * dy;
        if n2 == 0.0 {
            continue;
        }
        let on: Vec<f64> = others
            .iter()
            .filter(|&&q| point_segment_distance(q, p1, p2) <= 1e-9)
            .map(|&q| (((q.0 - p1.0) * dx + (q.1 - p1.1) * dy) / n2).clamp(0.0, 1.0))
            .collect();
        if on.is_empty() {
            continue; // no vertex of the other on this edge: the other pass or the vertex tests decide
        }
        let mut ts = vec![0.0, 1.0];
        ts.extend(on);
        ts.sort_by(|a, b| a.partial_cmp(b).unwrap());
        ts.dedup();
        let n = n2.sqrt();
        let (nx, ny) = (-dy / n * NUDGE, dx / n * NUDGE);
        for w in ts.windows(2) {
            let (t0, t1) = (w[0], w[1]);
            let (mx, my) = (p1.0 + dx * (t0 + t1) / 2.0, p1.1 + dy * (t0 + t1) / 2.0);
            for &s in &[1.0, -1.0] {
                let probe = (mx + s * nx, my + s * ny);
                if in_a(probe) && in_b(probe) {
                    return true;
                }
            }
        }
    }
    false
}

/// `geometry._rect_of`: whether the polygon is an axis-aligned rectangle
/// with area - a courtyard, a pad and a body box usually are.
fn rect_of(poly: &Polygon) -> bool {
    if poly.len() != 4 {
        return false;
    }
    let ((x0, y0), (x1, y1), (x2, y2), (x3, y3)) = (poly[0], poly[1], poly[2], poly[3]);
    if x0 == x1 && y1 == y2 && x2 == x3 && y3 == y0 {
        return x0 != x2 && y0 != y1;
    }
    if y0 == y1 && x1 == x2 && y2 == y3 && x3 == x0 {
        return y0 != y2 && x0 != x1;
    }
    false
}

/// `geometry.polys_overlap`'s "plain" (non-grid) branch: true when the two
/// polygons share interior. Behaviourally identical to the grid branch for
/// any polygon size (the grid is a cache, not a different answer), so this
/// is correct for every call; Python still prefers its cached grid path for
/// a polygon tested repeatedly (a reservation, a keepout).
///
/// Ported `_rect_of` too (placemat commit "two rectangles overlap by their
/// boxes"), not just at the Python dispatch layer: `shapes::conflict` calls
/// this function directly, Rust to Rust, never through
/// `geometry.polys_overlap`'s own Python-side shortcut - a courtyard pair
/// (overwhelmingly rectangles) is the near-obstacle search's dominant case,
/// so skipping this here would mean the hot path never got the shortcut at
/// all.
pub fn polys_overlap(a: &Polygon, b: &Polygon) -> bool {
    let (ax0, ay0, ax1, ay1) = bounds(a);
    let (bx0, by0, bx1, by1) = bounds(b);
    if ax0 >= bx1 || bx0 >= ax1 || ay0 >= by1 || by0 >= ay1 {
        return false;
    }
    if rect_of(a) && rect_of(b) {
        return true; // two rectangles are their boxes, and the boxes share interior
    }
    // strictly inside, as every other vertex is judged (geometry.polys_overlap)
    if (within(a[0], bx0, by0, bx1, by1) && strictly_inside(a[0], b))
        || (within(b[0], ax0, ay0, ax1, ay1) && strictly_inside(b[0], a))
    {
        return true;
    }
    let ea: Vec<(Point, Point)> = edges(a).filter(|&(p1, p2)| edge_meets(p1, p2, bx0, by0, bx1, by1)).collect();
    let eb: Vec<(Point, Point)> = edges(b).filter(|&(q1, q2)| edge_meets(q1, q2, ax0, ay0, ax1, ay1)).collect();
    for &(p1, p2) in &ea {
        for &(q1, q2) in &eb {
            if segments_intersect(p1, p2, q1, q2) {
                return true;
            }
        }
    }
    if a[1..].iter().any(|&p| within(p, bx0, by0, bx1, by1) && strictly_inside(p, b))
        || b[1..].iter().any(|&q| within(q, ax0, ay0, ax1, ay1) && strictly_inside(q, a))
    {
        return true;
    }
    let in_a = |p: Point| strictly_inside(p, a);
    let in_b = |p: Point| strictly_inside(p, b);
    let va: Vec<Point> = a.iter().copied().filter(|&p| within(p, bx0, by0, bx1, by1)).collect();
    let vb: Vec<Point> = b.iter().copied().filter(|&q| within(q, ax0, ay0, ax1, ay1)).collect();
    along_shared_boundary(&ea, &vb, in_a, in_b) || along_shared_boundary(&eb, &va, in_a, in_b)
}

/// A polygon of many points, indexed once so that a small one tested against it (a courtyard against a rule area)
/// looks only at the edges near it: `overlaps` is `polys_overlap(poly, other)` and gives its answer bit for bit.
/// Each step of `polys_overlap` that walks every edge or vertex of the big polygon (its bounds, the edges and
/// vertices in the other's box, a point's containment and its distance to every edge) is done over the part the
/// step can reach: a crossing count is a parity, so only the edges whose y range reaches the point's bin are
/// counted, and an edge further than 2 nanometres from a point (in either axis) is further than the 1 nanometre
/// strictness asks, so only the edges near it are measured.
pub struct Prepared {
    poly: Vec<Point>,
    bounds: (f64, f64, f64, f64),
    rect: bool,
    /// per edge, its box (left, top, right, bottom)
    boxes: Vec<(f64, f64, f64, f64)>,
    n: usize,
    cell: (f64, f64),
    /// the edges (their indexes, ascending) whose boxes reach each cell of an n x n grid over the bounds
    cells: Vec<Vec<u32>>,
    /// the edges whose y range reaches each of n bins over the bounds
    rows: Vec<Vec<u32>>,
}

#[inline]
fn bin(v: f64, v0: f64, size: f64, n: usize) -> usize {
    (((v - v0) / size).floor().max(0.0) as usize).min(n - 1)
}

/// Most entries an index may hold.
const MAX_INDEXED: usize = 2_000_000;

impl Prepared {
    pub fn new(poly: &Polygon) -> Option<Prepared> {
        let m = poly.len();
        if m < 3 {
            return None;
        }
        let b = bounds(poly);
        let n = ((m as f64).sqrt().ceil() as usize).clamp(1, 64);
        let (w, h) = ((b.2 - b.0) / n as f64, (b.3 - b.1) / n as f64);
        if !(w > 0.0 && h > 0.0 && w.is_finite() && h.is_finite()) {
            return None;
        }
        let boxes: Vec<(f64, f64, f64, f64)> =
            edges(poly).map(|(p, q)| (p.0.min(q.0), p.1.min(q.1), p.0.max(q.0), p.1.max(q.1))).collect();
        let mut cells = vec![Vec::new(); n * n];
        let mut rows = vec![Vec::new(); n];
        let mut entries = 0usize;
        for (i, e) in boxes.iter().enumerate() {
            for cy in bin(e.1, b.1, h, n)..=bin(e.3, b.1, h, n) {
                rows[cy].push(i as u32);
                for cx in bin(e.0, b.0, w, n)..=bin(e.2, b.0, w, n) {
                    cells[cy * n + cx].push(i as u32);
                    entries += 1;
                }
            }
            if entries > MAX_INDEXED {
                return None;
            }
        }
        Some(Prepared { poly: poly.to_vec(), bounds: b, rect: rect_of(poly), boxes, n, cell: (w, h), cells, rows })
    }

    /// The edges whose boxes meet the closed box, ascending.
    fn edges_meeting(&self, x0: f64, y0: f64, x1: f64, y1: f64, out: &mut Vec<usize>) {
        out.clear();
        let (b, n) = (self.bounds, self.n);
        for cy in bin(y0, b.1, self.cell.1, n)..=bin(y1, b.1, self.cell.1, n) {
            for cx in bin(x0, b.0, self.cell.0, n)..=bin(x1, b.0, self.cell.0, n) {
                for &i in &self.cells[cy * n + cx] {
                    let e = &self.boxes[i as usize];
                    if e.0 <= x1 && e.2 >= x0 && e.1 <= y1 && e.3 >= y0 {
                        out.push(i as usize);
                    }
                }
            }
        }
        out.sort_unstable();
        out.dedup();
    }

    /// `point_in_polygon`: the parity of the crossings, counted over the edges that can cross.
    fn contains(&self, p: Point) -> bool {
        let (x, y) = p;
        let mut inside = false;
        for &i in &self.rows[bin(y, self.bounds.1, self.cell.1, self.n)] {
            let (x1, y1) = self.poly[i as usize];
            let (x2, y2) = self.poly[(i as usize + 1) % self.poly.len()];
            if (y1 > y) != (y2 > y) {
                let xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1);
                if x < xin {
                    inside = !inside;
                }
            }
        }
        inside
    }

    /// `strictly_inside(p, poly)`.
    fn strictly_inside(&self, p: Point) -> bool {
        if !self.contains(p) {
            return false;
        }
        let mut near = Vec::new();
        self.edges_meeting(p.0 - 2e-9, p.1 - 2e-9, p.0 + 2e-9, p.1 + 2e-9, &mut near);
        near.iter().all(|&i| point_segment_distance(p, self.poly[i], self.poly[(i + 1) % self.poly.len()]) > 1e-9)
    }

    /// `polys_overlap(poly, b)`.
    pub fn overlaps(&self, b: &Polygon) -> bool {
        let a = &self.poly;
        let (ax0, ay0, ax1, ay1) = self.bounds;
        let (bx0, by0, bx1, by1) = bounds(b);
        if ax0 >= bx1 || bx0 >= ax1 || ay0 >= by1 || by0 >= ay1 {
            return false;
        }
        if self.rect && rect_of(b) {
            return true;
        }
        if (within(a[0], bx0, by0, bx1, by1) && strictly_inside(a[0], b))
            || (within(b[0], ax0, ay0, ax1, ay1) && self.strictly_inside(b[0]))
        {
            return true;
        }
        let mut meeting = Vec::new();
        self.edges_meeting(bx0, by0, bx1, by1, &mut meeting);
        let m = a.len();
        let ea: Vec<(Point, Point)> = meeting.iter().map(|&i| (a[i], a[(i + 1) % m])).collect();
        let eb: Vec<(Point, Point)> = edges(b).filter(|&(q1, q2)| edge_meets(q1, q2, ax0, ay0, ax1, ay1)).collect();
        for &(p1, p2) in &ea {
            for &(q1, q2) in &eb {
                if segments_intersect(p1, p2, q1, q2) {
                    return true;
                }
            }
        }
        // the vertices of a in b's box are ends of edges that meet it
        let mut ends: Vec<usize> = meeting.iter().flat_map(|&i| [i, (i + 1) % m]).collect();
        ends.sort_unstable();
        ends.dedup();
        let ia: Vec<usize> = ends.into_iter().filter(|&v| within(a[v], bx0, by0, bx1, by1)).collect();
        if ia.iter().any(|&v| v >= 1 && strictly_inside(a[v], b))
            || b[1..].iter().any(|&q| within(q, ax0, ay0, ax1, ay1) && self.strictly_inside(q))
        {
            return true;
        }
        let in_a = |p: Point| self.strictly_inside(p);
        let in_b = |p: Point| strictly_inside(p, b);
        let va: Vec<Point> = ia.iter().map(|&v| a[v]).collect();
        let vb: Vec<Point> = b.iter().copied().filter(|&q| within(q, ax0, ay0, ax1, ay1)).collect();
        along_shared_boundary(&ea, &vb, in_a, in_b) || along_shared_boundary(&eb, &va, in_a, in_b)
    }
}

/// `geometry.poly_distance`: shortest gap between two polygons, 0 when they
/// overlap or touch.
pub fn poly_distance(a: &Polygon, b: &Polygon) -> f64 {
    if polys_overlap(a, b) {
        return 0.0;
    }
    let mut best = f64::INFINITY;
    for &p in a {
        for (q1, q2) in edges(b) {
            best = best.min(point_segment_distance_below(p, q1, q2, best));
        }
    }
    for &p in b {
        for (q1, q2) in edges(a) {
            best = best.min(point_segment_distance_below(p, q1, q2, best));
        }
    }
    best
}

/// `poly_distance(a, b) < limit`, answered without the whole minimum (a polygon pair that overlaps is 0 apart): a pair of vertex and edge whose
/// boxes lie further than `limit` apart cannot be the one, and the first pair under `limit` ends it.
/// The same answer as the comparison, since a minimum is under `limit` just when one of its terms is;
/// the boxes are held off by a micrometre more than `limit` so no rounding can flip a pair.
pub fn poly_distance_below(a: &Polygon, b: &Polygon, limit: f64) -> bool {
    if limit <= 0.0 {
        return false;               // no distance is negative, and the overlap answers 0
    }
    let reach = limit + 1e-6;
    let near = |p: Point, (x0, y0, x1, y1): (f64, f64, f64, f64)| -> bool {
        p.0 >= x0 - reach && p.0 <= x1 + reach && p.1 >= y0 - reach && p.1 <= y1 + reach
    };
    let (ba, bb) = (bounds(a), bounds(b));
    let against = |pts: &Polygon, poly: &Polygon, pb: (f64, f64, f64, f64)| -> bool {
        for &p in pts {
            if !near(p, pb) {
                continue;
            }
            for (q1, q2) in edges(poly) {
                if p.0 < q1.0.min(q2.0) - reach || p.0 > q1.0.max(q2.0) + reach || p.1 < q1.1.min(q2.1) - reach
                    || p.1 > q1.1.max(q2.1) + reach
                {
                    continue;
                }
                if point_segment_distance_below(p, q1, q2, limit) < limit {
                    return true;
                }
            }
        }
        false
    };
    // the vertices and edges first: where polygons meet, some pair is almost always under the limit, and the overlap
    // test (which allocates) is then not needed; it still decides the polygons that cross with no vertex near
    against(a, b, bb) || against(b, a, ba) || polys_overlap(a, b)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn poly_distance_below_is_the_comparison_with_poly_distance() {
        let mut state = 41u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let ngon = |cx: f64, cy: f64, r: f64, n: usize, rot: f64| -> Vec<Point> {
            (0..n).map(|i| {
                let t = rot + i as f64 * std::f64::consts::TAU / n as f64;
                (cx + r * t.cos(), cy + r * t.sin())
            }).collect()
        };
        let (mut under, mut over) = (0, 0);
        for _ in 0..4000 {
            let a = ngon(next() * 4.0, next() * 4.0, 0.1 + next() * 0.6, 3 + (next() * 20.0) as usize, next());
            let b = ngon(next() * 4.0, next() * 4.0, 0.1 + next() * 0.9, 3 + (next() * 20.0) as usize, next());
            let d = poly_distance(&a, &b);
            for limit in [0.0, 1e-9, 0.2 - 1e-9, 0.5, d, d + 1e-12, d - 1e-12, d * 1.0000001, 3.0] {
                let want = d < limit;
                assert_eq!(poly_distance_below(&a, &b, limit), want, "d {d} limit {limit}");
                if want { under += 1 } else { over += 1 }
            }
        }
        assert!(under > 3000 && over > 3000, "{under} {over}");
    }

    #[test]
    fn a_prepared_polygon_overlaps_as_polys_overlap_does() {
        let mut state = 7u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        // coordinates on a 0.25 grid, a good share of the time, so that vertices and edges meet
        let mut snap = |v: f64, on: bool| if on { (v * 4.0).round() / 4.0 } else { v };
        let (mut hits, mut misses, mut ties) = (0, 0, 0);
        for round in 0..400 {
            let on = round % 2 == 0;
            let n = 24 + (next() * 200.0) as usize;
            let (cx, cy, r) = (next() * 10.0, next() * 10.0, 3.0 + next() * 6.0);
            let big: Vec<Point> = (0..n).map(|i| {
                let t = std::f64::consts::TAU * i as f64 / n as f64;
                let rr = r * (0.5 + 0.5 * next());
                (snap(cx + rr * t.cos(), on), snap(cy + rr * t.sin(), on))
            }).collect();
            // a rectilinear one, for coincident edges
            let rectilinear: Vec<Point> = {
                let mut v = Vec::new();
                for k in 0..n / 4 {
                    let (x, y) = (k as f64 * 0.25, ((k * 7) % 5) as f64 * 0.25);
                    v.push((x, y));
                    v.push((x + 0.25, y));
                }
                v.push((n as f64 / 16.0, -3.0));
                v.push((0.0, -3.0));
                v
            };
            for poly in [big, rectilinear] {
                let Some(prep) = Prepared::new(&poly) else { continue };
                let bb = bounds(&poly);
                for _ in 0..60 {
                    let (x, y) = (snap(bb.0 + next() * (bb.2 - bb.0 + 2.0) - 1.0, on), snap(bb.1 + next() * (bb.3 - bb.1 + 2.0) - 1.0, on));
                    let (w, h) = (snap(0.1 + next() * 2.5, on).max(0.25), snap(0.1 + next() * 2.5, on).max(0.25));
                    let small: Vec<Point> = match (next() * 3.0) as usize {
                        0 => vec![(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                        1 => vec![(x, y), (x + w, y + h * 0.3), (x + w * 0.5, y + h)],
                        _ => (0..8).map(|i| { let t = std::f64::consts::TAU * i as f64 / 8.0; (snap(x + w * t.cos(), on), snap(y + h * t.sin(), on)) }).collect(),
                    };
                    let want = polys_overlap(&poly, &small);
                    assert_eq!(prep.overlaps(&small), want, "round {round} small {small:?}");
                    if want { hits += 1 } else { misses += 1 }
                    ties += (on && want) as usize;
                }
            }
        }
        assert!(hits > 2000 && misses > 2000 && ties > 500, "{hits} {misses} {ties}");
    }

    #[test]
    fn disjoint_boxes_do_not_overlap() {
        let a = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)];
        let b = [(2.0, 0.0), (3.0, 0.0), (3.0, 1.0), (2.0, 1.0)];
        assert!(!polys_overlap(&a, &b));
        assert_eq!(poly_distance(&a, &b), 1.0);
    }

    #[test]
    fn touching_boxes_do_not_overlap_but_are_zero_apart() {
        let a = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)];
        let b = [(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)];
        assert!(!polys_overlap(&a, &b));
        assert_eq!(poly_distance(&a, &b), 0.0);
    }

    #[test]
    fn overlapping_boxes_overlap() {
        let a = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)];
        let b = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)];
        assert!(polys_overlap(&a, &b));
        assert_eq!(poly_distance(&a, &b), 0.0);
    }

    #[test]
    fn contained_polygon_overlaps_even_when_first_vertex_touches_the_boundary() {
        // A 16-gon inside a box with its first vertex exactly on the box's
        // top edge: the case polys_overlap's docstring calls out, where a
        // first-vertex-only containment test would read this as clear.
        let box_ = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)];
        let mut via = Vec::new();
        for i in 0..16 {
            let a = 2.0 * std::f64::consts::PI * (i as f64) / 16.0;
            via.push((0.3 * a.cos(), 0.3 * a.sin() - 1.0)); // vertex 0 = (0.3, -1.0): on box_'s top edge
        }
        assert!(polys_overlap(&box_, &via));
        assert_eq!(poly_distance(&box_, &via), 0.0);
    }

    #[test]
    fn the_same_rectangle_twice_overlaps() {
        // Every vertex of each lies on the other's boundary and no edge
        // crosses another: the case _along_shared_boundary exists for
        // (placemat commit e2614d8 - two coinciding courtyards).
        let a = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)];
        let b = a;
        assert!(polys_overlap(&a, &b));
        assert_eq!(poly_distance(&a, &b), 0.0);
    }

    #[test]
    fn rect_of_needs_the_actual_vertex_order_not_just_a_rectangular_box() {
        // A 4-vertex L-shape's bounding box is a rectangle, but the polygon
        // itself is not one - rect_of must say so, or the shortcut would
        // treat "boxes share interior" as "polygons share interior" for a
        // shape that isn't actually its own box.
        let ell = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0)]; // not a rectangle: only 4 points, wrong order for one
        assert!(!rect_of(&ell));
        let rect = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)];
        assert!(rect_of(&rect));
        // reversed winding is still a rectangle
        let reversed = [(0.0, 0.0), (0.0, 2.0), (2.0, 2.0), (2.0, 0.0)];
        assert!(rect_of(&reversed));
        // a degenerate (zero-area) box is not a rectangle for this purpose
        let flat = [(0.0, 0.0), (2.0, 0.0), (2.0, 0.0), (0.0, 0.0)];
        assert!(!rect_of(&flat));
    }

    #[test]
    fn a_diamond_slid_along_its_own_edge_overlaps_its_copy() {
        // Two congruent diamonds (non-axis-aligned, so _rect_of never
        // applies to them even in Python), one slid along a shared edge
        // line: their interiors overlap in a parallelogram, with no edge
        // crossing and no vertex of either strictly inside the other -
        // only the coinciding-boundary probe finds it.
        let a = [(0.0, -2.0), (2.0, 0.0), (0.0, 2.0), (-2.0, 0.0)];
        let b = [(1.0, -1.0), (3.0, 1.0), (1.0, 3.0), (-1.0, 1.0)]; // a shifted by (1, 1)
        assert!(polys_overlap(&a, &b));
        assert_eq!(poly_distance(&a, &b), 0.0);
    }
}
