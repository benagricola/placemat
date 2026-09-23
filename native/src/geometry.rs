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
    let (ax, ay) = a;
    let (bx, by) = b;
    let (px, py) = p;
    let (dx, dy) = (bx - ax, by - ay);
    if dx == 0.0 && dy == 0.0 {
        return (px - ax).hypot(py - ay);
    }
    let t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy);
    let t = t.max(0.0).min(1.0);
    (px - (ax + t * dx)).hypot(py - (ay + t * dy))
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
    if (within(a[0], bx0, by0, bx1, by1) && point_in_polygon(a[0], b))
        || (within(b[0], ax0, ay0, ax1, ay1) && point_in_polygon(b[0], a))
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

/// `geometry.poly_distance`: shortest gap between two polygons, 0 when they
/// overlap or touch.
pub fn poly_distance(a: &Polygon, b: &Polygon) -> f64 {
    if polys_overlap(a, b) {
        return 0.0;
    }
    let mut best = f64::INFINITY;
    for &p in a {
        for (q1, q2) in edges(b) {
            best = best.min(point_segment_distance(p, q1, q2));
        }
    }
    for &p in b {
        for (q1, q2) in edges(a) {
            best = best.min(point_segment_distance(p, q1, q2));
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;

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
