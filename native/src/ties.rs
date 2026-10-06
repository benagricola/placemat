//! KiCad's net-tie exclusion, ported from `src/placemat/occupancy.py`'s
//! `_net_tie_exclusion` and `_hole_tie_exclusion`, and the shape collisions
//! it needs from `src/placemat/kicad_collide.py`.
//!
//! KiCad 10.0 lets copper of two nets meet at a net tie in two ways:
//!
//! - DRC_ENGINE::EvalRules ("Handle Footprint net ties", drc_engine.cpp)
//!   gives a net tie's copper drawing no clearance to a connected item of a
//!   net of a pad of its group it overlaps (FOOTPRINT::BuildNetTieCache);
//! - DRC_ENGINE::IsNetTieExclusion (drc_engine.cpp:2526) lets a collision
//!   through where its position - the one `SHAPE::Collide` gives the
//!   clearance provider (drc_test_provider_copper_clearance.cpp:283, 352,
//!   850) - lies within the DRC epsilon of a net-tie pad of the colliding
//!   item's net, on the layer tested.
//!
//! Python's rules are the reference: each function here names the one it
//! ports, and does what it does in the same order and with the same
//! rounding, so a candidate is let through here exactly where `_conflict`
//! lets it through. Only the shapes a net tie can excuse carry a `TieInfo`
//! (`Occupancy._native_ties`): the copper of a net tie's footprint, and
//! copper of a net a net tie's pads carry.

use crate::geometry::{point_in_polygon, point_segment_distance, Point};
use crate::shapes::{Kind, Shape};
use std::collections::HashSet;
use std::sync::Arc;

type P = (i64, i64);

/// A `kicad_collide` shape, in nm: a SHAPE_CIRCLE (x, y, r), a SHAPE_SEGMENT (ax, ay, bx, by, width), a
/// square-cornered SHAPE_RECT (its top-left corner, size and the quarter turns of the pad it is read from), a
/// SHAPE_SIMPLE.
#[derive(Clone, Debug, PartialEq)]
pub enum K {
    C(i64, i64, i64),
    S(i64, i64, i64, i64, i64),
    R(i64, i64, i64, i64, i64),
    P(Vec<P>),
}

/// A pad of a net tie's footprint as read: its outlines (mm) and effective shape (nm, `PadGeom.kshapes`), and its
/// layers as read and mirrored (`Occupancy._mirror_layers`).
pub struct ReadPad {
    pub outlines: Vec<Vec<Point>>,
    pub kshapes: Vec<K>,
    pub layers: u32,
    pub mirrored: u32,
}

/// Outlines as read (mm), each with the effective shape read with it (nm).
pub type Reads = Vec<(Vec<Point>, Vec<K>)>;

/// What `_tie_pads` and `_net_tie_cache` read off a net tie's footprint.
pub struct TieFootprint {
    /// Its pads in a net-tie group, in pad order, each with its net.
    pub tie_pads: Vec<(String, ReadPad)>,
    /// The pads `_net_tie_cache` collides with a drawing, each with the nets of its group's members.
    pub cache_pads: Vec<(ReadPad, Vec<String>)>,
    /// Every net of `cache_pads`.
    pub cache_nets: HashSet<String>,
}

/// One shape as the net-tie exclusion sees it (Python's view of the shape a check judges: a candidate's shape
/// moved by `legal`, which keeps no track ends nor via circle, or an obstacle as it stands).
pub struct TieInfo {
    pub has_fp: bool,      // geometry.has_footprint(owner)
    pub fp_graphic: bool,  // Occupancy._is_footprint_graphic
    pub fp_copper: bool,   // Occupancy._is_footprint_copper
    pub tie_graphic: bool, // Occupancy._is_tie_graphic
    pub circle: Option<(f64, f64, f64)>, // a via's circle (no track ends), mm
    pub ends: Option<(Point, Point)>,    // a track's two ends, mm
    /// `Occupancy._read_of`'s outlines in the order it tries them, each with the effective shape read with it:
    /// shared by every shape of the footprint that reads them.
    pub reads: Option<Arc<Reads>>,
    /// The owner's footprint, when it is a net tie.
    pub fp: Option<Arc<TieFootprint>>,
}

const ECOORD_MAX: i64 = i64::MAX;
const INT_MAX: i64 = i32::MAX as i64;

// ------------------------------------------------------------------ integer helpers (kicad_collide)

/// KiCad's rescale(): a * b / c, rounded half away from zero.
fn rescale(a: i64, b: i64, c: i64) -> i64 {
    let q = a as i128 * b as i128;
    let c128 = c as i128;
    let r = (q.abs() + c128.abs() / 2) / c128.abs();
    (if (q >= 0) == (c > 0) { r } else { -r }) as i64
}

/// KiROUND: half away from zero.
fn kiround(v: f64) -> i64 {
    if v >= 0.0 { (v + 0.5) as i64 } else { -((-v + 0.5) as i64) }
}

/// VECTOR2I / 2: halves round away from zero.
fn half(v: i64) -> i64 {
    if v < 0 { -((1 - v) / 2) } else { (v + 1) / 2 }
}

/// `(int) sqrt( v )`: the double square root, truncated.
fn sqrt_int(v: i64) -> i64 {
    (v as f64).sqrt() as i64
}

fn sq(p: P, q: P) -> i64 {
    (p.0 - q.0) * (p.0 - q.0) + (p.1 - q.1) * (p.1 - q.1)
}

/// Python's `round()` of a float to an int: half to even.
fn round_even(v: f64) -> i64 {
    v.round_ties_even() as i64
}

/// `kicad_collide.to_nm`.
pub fn to_nm(mm: f64) -> i64 {
    round_even(mm * 1e6)
}

// ------------------------------------------------------------------ SEG

type Seg = (P, P);

/// SEG::NearestPoint( VECTOR2I ).
fn nearest_to_point(seg: Seg, p: P) -> P {
    let ((ax, ay), (bx, by)) = seg;
    let (dx, dy) = (bx - ax, by - ay);
    let l2 = dx * dx + dy * dy;
    if l2 == 0 {
        return (ax, ay);
    }
    let t = dx * (p.0 - ax) + dy * (p.1 - ay);
    if t < 0 {
        return (ax, ay);
    }
    if t > l2 {
        return (bx, by);
    }
    (ax + rescale(t, dx, l2), ay + rescale(t, dy, l2))
}

/// SEG::SquaredDistance( VECTOR2I ).
fn sq_distance_point(seg: Seg, p: P) -> i64 {
    let ((ax, ay), (bx, by)) = seg;
    let (abx, aby) = (bx - ax, by - ay);
    let (apx, apy) = (p.0 - ax, p.1 - ay);
    let e = apx * abx + apy * aby;
    if e <= 0 {
        return apx * apx + apy * apy;
    }
    let f = abx * abx + aby * aby;
    if e >= f {
        let (bpx, bpy) = (p.0 - bx, p.1 - by);
        return bpx * bpx + bpy * bpy;
    }
    let g = ((apx * apx + apy * apy) as f64) - (e as f64 * e as f64) / (f as f64);
    if g < 0.0 || g > ECOORD_MAX as f64 {
        return 0;
    }
    kiround(g)
}

/// SEG::Intersect( SEG ): the point two segments share, or None; for collinear ones the middle of their overlap.
fn intersect(s1: Seg, s2: Seg) -> Option<P> {
    let ((ax, ay), (bx, by)) = s1;
    let ((cx, cy), (ex, ey)) = s2;
    if ax.max(bx) < cx.min(ex) || cx.max(ex) < ax.min(bx) || ay.max(by) < cy.min(ey) || cy.max(ey) < ay.min(by) {
        return None;
    }
    let (d1x, d1y) = (bx - ax, by - ay);
    let (d2x, d2y) = (ex - cx, ey - cy);
    let (ox, oy) = (cx - ax, cy - ay);
    let det = d2x * d1y - d2y * d1x;
    if det == 0 {
        if d1x * oy - d1y * ox != 0 {
            return None;
        }
        let use_x = d1x.abs() >= d1y.abs();
        let (s1a, s1b, s2a, s2b, o1a, o1b) = if use_x { (ax, bx, cx, ex, ay, by) } else { (ay, by, cy, ey, ax, bx) };
        let (lo, hi) = (s1a.min(s1b).max(s2a.min(s2b)), s1a.max(s1b).min(s2a.max(s2b)));
        if hi < lo {
            return None;
        }
        let proj = ((lo + hi) as f64 / 2.0) as i64; // C++ integer division truncates toward zero
        let other = if s1b != s1a { o1a + rescale(proj - s1a, o1b - o1a, s1b - s1a) } else { o1a };
        return Some(if use_x { (proj, other) } else { (other, proj) });
    }
    let p2 = d2x * oy - d2y * ox;
    let p1 = d1x * oy - d1y * ox;
    if det > 0 {
        if p1 < 0 || p1 > det || p2 < 0 || p2 > det {
            return None;
        }
    } else if p1 > 0 || p1 < det || p2 > 0 || p2 < det {
        return None;
    }
    Some((cx + rescale(p1, d2x, det), cy + rescale(p1, d2y, det)))
}

/// SEG::SquaredDistance( SEG ).
fn sq_distance(s1: Seg, s2: Seg) -> i64 {
    if s1.0 == s1.1 {
        return sq_distance_point(s2, s1.0);
    }
    if s2.0 == s2.1 {
        return sq_distance_point(s1, s2.0);
    }
    if intersect(s1, s2).is_some() {
        return 0;
    }
    sq(nearest_to_point(s2, s1.0), s1.0)
        .min(sq(nearest_to_point(s2, s1.1), s1.1))
        .min(sq(nearest_to_point(s1, s2.0), s2.0))
        .min(sq(nearest_to_point(s1, s2.1), s2.1))
}

/// SEG::NearestPoint( SEG ): the point of `s1` nearest `s2`.
fn nearest_point(s1: Seg, s2: Seg) -> P {
    if let Some(hit) = intersect(s1, s2) {
        return hit;
    }
    let outs = [s1.0, s1.1, nearest_to_point(s1, s2.0), nearest_to_point(s1, s2.1)];
    let dists = [sq(nearest_to_point(s2, s1.0), s1.0), sq(nearest_to_point(s2, s1.1), s1.1),
                 sq(outs[2], s2.0), sq(outs[3], s2.1)];
    let mut i = 0;
    for k in 1..4 {
        if dists[k] < dists[i] {
            i = k;
        }
    }
    outs[i]
}

/// SEG::Collide( SEG, clearance, &actual ): (actual, collides).
fn seg_collide(s1: Seg, s2: Seg, clearance: i64) -> (i64, bool) {
    if clearance < 0 {
        return (0, false);
    }
    if s1.0 == s1.1 {
        let d = sq_distance_point(s2, s1.0).isqrt();
        return (d, d == 0 || d < clearance);
    }
    if s2.0 == s2.1 {
        let d = sq_distance_point(s1, s2.0).isqrt();
        return (d, d == 0 || d < clearance);
    }
    if intersect(s1, s2).is_some() {
        return (0, true);
    }
    let clearance_sq = clearance * clearance;
    let mut best = ECOORD_MAX;
    for d in [sq_distance_point(s1, s2.0), sq_distance_point(s1, s2.1), sq_distance_point(s2, s1.0),
              sq_distance_point(s2, s1.1)] {
        if d == 0 {
            return (0, true);
        }
        best = best.min(d);
    }
    (best.isqrt(), best < clearance_sq)
}

// ------------------------------------------------------------------ SHAPE_LINE_CHAIN_BASE

/// SHAPE_LINE_CHAIN_BASE::PointInside at an accuracy of 0: the crossing rule, so a point on a right-hand edge is
/// outside.
fn point_inside(p: P, pts: &[P]) -> bool {
    let n = pts.len();
    let mut inside = false;
    if n < 3 {
        return false;
    }
    for i in 0..n {
        let (p1, p2) = (pts[i], pts[(i + 1) % n]);
        let dy = p2.1 - p1.1;
        if dy == 0 {
            continue;
        }
        let d = rescale(p2.0 - p1.0, p.1 - p1.1, dy);
        if ((p1.1 >= p.1) != (p2.1 >= p.1)) && (p.0 - p1.0 < d) {
            inside = !inside;
        }
    }
    inside
}

fn edges(pts: &[P]) -> impl Iterator<Item = Seg> + '_ {
    let n = pts.len();
    (0..n).map(move |i| (pts[i], pts[(i + 1) % n]))
}

/// SHAPE_LINE_CHAIN::Collide( SEG ) of a closed chain: (actual, location) or None.
fn chain_collide_seg(pts: &[P], seg: Seg, clearance: i64) -> Option<(i64, P)> {
    if point_inside(seg.0, pts) {
        return Some((0, seg.0));
    }
    let mut closest = ECOORD_MAX;
    let clearance_sq = clearance * clearance;
    let mut nearest = (0, 0);
    for s in edges(pts) {
        let d = sq_distance(s, seg);
        if d < closest {
            nearest = nearest_point(s, seg);
            closest = d;
            if closest == 0 {
                break;
            }
        }
    }
    if closest == 0 || closest < clearance_sq {
        return Some((sqrt_int(closest), nearest));
    }
    None
}

/// Collide( SHAPE_LINE_CHAIN_BASE, SHAPE_LINE_CHAIN_BASE ) of two closed chains, A first.
fn chain_collide_chain(a: &[P], b: &[P], clearance: i64) -> Option<(i64, P)> {
    let mut closest = INT_MAX;
    let mut nearest = (0, 0);
    if point_inside(a[0], b) {
        closest = 0;
        nearest = a[0];
    } else if point_inside(b[0], a) {
        closest = 0;
        nearest = b[0];
    } else {
        let mut a_segs: Vec<Seg> = edges(a).collect();
        let mut b_segs: Vec<Seg> = edges(b).collect();
        a_segs.sort_by_key(|s| s.0);
        b_segs.sort_by_key(|s| s.0);
        for &sa in &a_segs {
            for &sb in &b_segs {
                let (d, hit) = seg_collide(sa, sb, clearance);
                if hit {
                    if d < closest {
                        nearest = nearest_point(sa, sb);
                        closest = d;
                    }
                    if closest == 0 {
                        break;
                    }
                }
            }
        }
    }
    if closest == 0 || closest < clearance {
        return Some((closest, nearest));
    }
    None
}

// ------------------------------------------------------------------ one shape against a segment

/// SHAPE_CIRCLE::Collide( SEG ).
fn circle_collide_seg(c: (i64, i64, i64), seg: Seg, clearance: i64) -> Option<(i64, P)> {
    let (cx, cy, r) = c;
    let pn = nearest_to_point(seg, (cx, cy));
    let dist_sq = sq(pn, (cx, cy));
    if dist_sq == 0 || dist_sq < (clearance + r) * (clearance + r) {
        let mut at = pn;
        if dist_sq == 0 {
            if let Some(&first) = circle_intersect(c, seg).first() {
                at = first;
            }
        }
        return Some(((sqrt_int(dist_sq) - r).max(0), at));
    }
    None
}

/// VECTOR2I::Resize.
fn resize(v: P, length: i64) -> P {
    let (x, y) = v;
    if x == 0 && y == 0 {
        return (0, 0);
    }
    let (nx, ny);
    if x.abs() == y.abs() {
        nx = length.abs() as f64 * 0.5f64.sqrt();
        ny = nx;
    } else {
        let l_sq = x * x + y * y;
        let n_sq = length * length;
        nx = (rescale(n_sq, x * x, l_sq) as f64).sqrt();
        ny = (rescale(n_sq, y * y, l_sq) as f64).sqrt();
    }
    (if x < 0 { -kiround(nx) } else { kiround(nx) }, if y < 0 { -kiround(ny) } else { kiround(ny) })
}

/// VECTOR2<int64>::EuclideanNorm.
fn euclid_norm(x: i64, y: i64) -> i64 {
    if x.abs() == y.abs() {
        return kiround(x.abs() as f64 * 2.0f64.sqrt());
    }
    if x == 0 {
        return y.abs();
    }
    if y == 0 {
        return x.abs();
    }
    kiround(crate::exact::hypot(x as f64, y as f64))
}

/// CIRCLE::Intersect( SEG ): the line's crossings of the circle that lie on the segment.
fn circle_intersect(c: (i64, i64, i64), seg: Seg) -> Vec<P> {
    let (cx, cy, r) = c;
    let ((ax, ay), (bx, by)) = seg;
    let (dx, dy) = (bx - ax, by - ay);
    let l2 = dx * dx + dy * dy;
    let m = if l2 == 0 {
        (ax, ay)
    } else {
        let t = dx * (cx - ax) + dy * (cy - ay);
        (ax + rescale(t, dx, l2), ay + rescale(t, dy, l2))
    };
    let om = euclid_norm(m.0 - cx, m.1 - cy);
    let prec = 1; // SHAPE::MIN_PRECISION_IU
    if om > r + prec {
        return Vec::new();
    }
    let pts = if r - prec <= om && om <= r + prec {
        vec![m]
    } else {
        let to1 = resize((dx, dy), ((r * r - om * om) as f64).sqrt() as i64);
        vec![(to1.0 + m.0, to1.1 + m.1), (-to1.0 + m.0, -to1.1 + m.1)]
    };
    pts.into_iter().filter(|&p| sq_distance_point(seg, p) <= 3).collect() // SEG::Contains
}

/// SHAPE_SEGMENT::Collide( SEG ).
fn segment_collide_seg(s: (i64, i64, i64, i64, i64), seg: Seg, clearance: i64) -> Option<(i64, P)> {
    let (ax, ay, bx, by, w) = s;
    let me = ((ax, ay), (bx, by));
    let min_dist = (w + 1) / 2 + clearance;
    let (dist_sq, loc) = if seg.0 == seg.1 {
        (sq_distance_point(me, seg.0), nearest_to_point(me, seg.0))
    } else {
        (sq_distance(me, seg), nearest_point(me, seg))
    };
    if dist_sq == 0 || dist_sq < min_dist * min_dist {
        return Some(((sqrt_int(dist_sq) - (w + 1) / 2).max(0), loc));
    }
    None
}

/// SHAPE_RECT::Collide( SEG ), square-cornered.
fn rect_collide_seg(r: (i64, i64, i64, i64), seg: Seg, clearance: i64) -> Option<(i64, P)> {
    let (x, y, w, h) = r;
    for end in [seg.0, seg.1] {
        if x <= end.0 && end.0 <= x + w && y <= end.1 && end.1 <= y + h {
            return Some((0, end));
        }
    }
    let corners = [(x, y), (x, y + h), (x + w, y + h), (x + w, y), (x, y)];
    let mut closest = ECOORD_MAX;
    let mut nearest = (0, 0);
    for i in 0..4 {
        let side = (corners[i], corners[i + 1]);
        let d = sq_distance(side, seg);
        if d < closest {
            nearest = nearest_point(side, seg);
            closest = d;
        } else if d == closest {
            let near = nearest_point(side, seg);
            if sq(near, seg.0) < sq(nearest, seg.0) {
                nearest = near;
            }
        }
    }
    if closest == 0 || closest < clearance * clearance {
        return Some((sqrt_int(closest), nearest));
    }
    None
}

// ------------------------------------------------------------------ pairs of single shapes (shape_collisions.cpp)

fn circle_circle(a: (i64, i64, i64), b: (i64, i64, i64), clearance: i64) -> Option<(i64, P)> {
    let (ax, ay, ar) = a;
    let (bx, by, br) = b;
    let min_dist = clearance + ar + br;
    let dist_sq = (bx - ax) * (bx - ax) + (by - ay) * (by - ay);
    if dist_sq == 0 || dist_sq < min_dist * min_dist {
        return Some(((sqrt_int(dist_sq) - ar - br).max(0), (half(ax + bx), half(ay + by))));
    }
    None
}

fn rect_circle(rect: (i64, i64, i64, i64), circle: (i64, i64, i64), clearance: i64) -> Option<(i64, P)> {
    let (x, y, w, h) = rect;
    let (cx, cy, r) = circle;
    let min_dist_sq = (clearance + r) * (clearance + r);
    let vts = [(x, y), (x, y + h), (x + w, y + h), (x + w, y), (x, y)];
    let inside = x <= cx && cx <= x + w && y <= cy && cy <= y + h;
    let mut nearest_sq = ECOORD_MAX;
    let mut nearest = (0, 0);
    for i in 0..4 {
        let pn = nearest_to_point((vts[i], vts[i + 1]), (cx, cy));
        let d = sq(pn, (cx, cy));
        if d < nearest_sq {
            nearest = pn;
            nearest_sq = d;
            if nearest_sq == 0 {
                break;
            }
        }
    }
    if inside || nearest_sq == 0 || nearest_sq < min_dist_sq {
        return Some(((sqrt_int(nearest_sq) - r).max(0), nearest));
    }
    None
}

fn circle_chain(circle: (i64, i64, i64), pts: &[P], clearance: i64) -> Option<(i64, P)> {
    let (cx, cy, _) = circle;
    let mut closest = INT_MAX;
    let mut nearest = (0, 0);
    if point_inside((cx, cy), pts) {
        nearest = (cx, cy);
        closest = 0;
    } else {
        for s in edges(pts) {
            if let Some((d, pn)) = circle_collide_seg(circle, s, clearance) {
                if d < closest {
                    nearest = pn;
                    closest = d;
                }
                if closest == 0 {
                    break;
                }
            }
        }
    }
    if closest == 0 || closest < clearance {
        return Some((closest, nearest));
    }
    None
}

fn seg_of(s: (i64, i64, i64, i64, i64)) -> Seg {
    ((s.0, s.1), (s.2, s.3))
}

fn circle_segment(circle: (i64, i64, i64), s: (i64, i64, i64, i64, i64), clearance: i64) -> Option<(i64, P)> {
    let w = s.4;
    let (d, at) = circle_collide_seg(circle, seg_of(s), clearance + w / 2)?;
    Some(((d - w / 2).max(0), at))
}

fn segment_segment(a: (i64, i64, i64, i64, i64), b: (i64, i64, i64, i64, i64), clearance: i64) -> Option<(i64, P)> {
    let (d, at) = segment_collide_seg(a, seg_of(b), clearance + b.4 / 2)?;
    Some(((d - b.4 / 2).max(0), at))
}

fn rect_segment(rect: (i64, i64, i64, i64), s: (i64, i64, i64, i64, i64), clearance: i64) -> Option<(i64, P)> {
    let w = s.4;
    let (d, at) = rect_collide_seg(rect, seg_of(s), clearance + w / 2)?;
    Some(((d - w / 2).max(0), at))
}

fn chain_segment(pts: &[P], s: (i64, i64, i64, i64, i64), clearance: i64) -> Option<(i64, P)> {
    let w = s.4;
    let (d, at) = chain_collide_seg(pts, seg_of(s), clearance + w / 2)?;
    Some(((d - w / 2).max(0), at))
}

fn rect_chain(rect: (i64, i64, i64, i64), pts: &[P], clearance: i64) -> Option<(i64, P)> {
    let (x, y, w, h) = rect;
    let mut closest = INT_MAX;
    let mut nearest = (0, 0);
    let centre = (x + w / 2, y + h / 2);
    if point_inside(centre, pts) {
        nearest = centre;
        closest = 0;
    } else {
        for s in edges(pts) {
            if let Some((d, pn)) = rect_collide_seg(rect, s, clearance) {
                if d < closest {
                    nearest = pn;
                    closest = d;
                }
                if closest == 0 {
                    break;
                }
            }
        }
    }
    if closest == 0 || closest < clearance {
        return Some((closest, nearest));
    }
    None
}

fn outline(rect: (i64, i64, i64, i64)) -> [P; 4] {
    let (x, y, w, h) = rect;
    [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
}

/// collideSingleShapes(): (actual, location) of two single shapes, or None.
fn collide_single(a: &K, b: &K, clearance: i64) -> Option<(i64, P)> {
    match (a, b) {
        (K::C(ax, ay, ar), K::C(bx, by, br)) => circle_circle((*ax, *ay, *ar), (*bx, *by, *br), clearance),
        (K::C(x, y, r), K::R(rx, ry, rw, rh, _)) | (K::R(rx, ry, rw, rh, _), K::C(x, y, r)) =>
            rect_circle((*rx, *ry, *rw, *rh), (*x, *y, *r), clearance),
        (K::C(x, y, r), K::P(pts)) | (K::P(pts), K::C(x, y, r)) => circle_chain((*x, *y, *r), pts, clearance),
        (K::C(x, y, r), K::S(ax, ay, bx, by, w)) | (K::S(ax, ay, bx, by, w), K::C(x, y, r)) =>
            circle_segment((*x, *y, *r), (*ax, *ay, *bx, *by, *w), clearance),
        (K::R(x, y, w, h, _), K::R(x2, y2, w2, h2, _)) =>
            chain_collide_chain(&outline((*x, *y, *w, *h)), &outline((*x2, *y2, *w2, *h2)), clearance),
        (K::R(x, y, w, h, _), K::P(pts)) | (K::P(pts), K::R(x, y, w, h, _)) =>
            rect_chain((*x, *y, *w, *h), pts, clearance),
        (K::R(x, y, w, h, _), K::S(ax, ay, bx, by, sw)) | (K::S(ax, ay, bx, by, sw), K::R(x, y, w, h, _)) =>
            rect_segment((*x, *y, *w, *h), (*ax, *ay, *bx, *by, *sw), clearance),
        (K::P(a), K::P(b)) => chain_collide_chain(a, b, clearance),
        (K::P(pts), K::S(ax, ay, bx, by, w)) | (K::S(ax, ay, bx, by, w), K::P(pts)) =>
            chain_segment(pts, (*ax, *ay, *bx, *by, *w), clearance),
        (K::S(a0, a1, a2, a3, a4), K::S(b0, b1, b2, b3, b4)) =>
            segment_segment((*a0, *a1, *a2, *a3, *a4), (*b0, *b1, *b2, *b3, *b4), clearance),
    }
}

/// SHAPE::Collide( SHAPE, clearance, &actual, &location ) of two SHAPE_COMPOUNDs (`kicad_collide.collide`):
/// (actual, location) or None. Of the sub-shape pairs that collide, the one of least `actual` gives the
/// location (the first of equals), and a pair at 0 ends the search.
pub fn collide(a: &[K], b: &[K], clearance: i64) -> Option<(i64, P)> {
    let mut colliding = false;
    let mut actual = INT_MAX;
    let mut location = (0, 0);
    for ea in a {
        for eb in b {
            if let Some((d, at)) = collide_single(ea, eb, clearance) {
                colliding = true;
                if d < actual {
                    actual = d;
                    location = at;
                }
                if actual > 0 {
                    continue;
                }
                return Some((actual, location));
            }
        }
    }
    if colliding { Some((actual, location)) } else { None }
}

/// SHAPE::Collide( VECTOR2I, clearance ) of an effective shape (`kicad_collide.collide_point`).
pub fn collide_point(shape: &[K], p: P, clearance: i64) -> bool {
    let seg = (p, p);
    shape.iter().any(|s| match s {
        K::C(x, y, r) => circle_collide_seg((*x, *y, *r), seg, clearance).is_some(),
        K::S(a, b, c, d, w) => segment_collide_seg((*a, *b, *c, *d, *w), seg, clearance).is_some(),
        K::R(x, y, w, h, _) => rect_collide_seg((*x, *y, *w, *h), seg, clearance).is_some(),
        K::P(pts) => chain_collide_seg(pts, seg, clearance).is_some(),
    })
}

// ------------------------------------------------------------------ a read shape where a part stands

/// (a, b, c, d, tx, ty), mm: a rigid move.
type Affine = (f64, f64, f64, f64, f64, f64);

/// `occupancy._affine_between`: the rigid move that carries `r`, an outline as read, onto `poly`, vertex for
/// vertex; None when `poly` is not that outline moved.
fn affine_between(r: &[Point], poly: &[Point]) -> Option<Affine> {
    let n = r.len();
    if n != poly.len() || n < 3 {
        return None;
    }
    let i = 0;
    let far = |k: usize| {
        let (u, v) = (r[k].0 - r[i].0, r[k].1 - r[i].1);
        u * u + v * v
    };
    let mut j = 0;
    for k in 1..n {
        if far(k) > far(j) {
            j = k;
        }
    }
    let (dx, dy) = (r[j].0 - r[i].0, r[j].1 - r[i].1);
    let across = |m: usize| (dx * (r[m].1 - r[i].1) - dy * (r[m].0 - r[i].0)).abs();
    let mut k = 0;
    for m in 1..n {
        if across(m) > across(k) {
            k = m;
        }
    }
    let det = dx * (r[k].1 - r[i].1) - dy * (r[k].0 - r[i].0);
    if det.abs() < 1e-12 {
        return None;
    }
    let (ex, ey) = (r[k].0 - r[i].0, r[k].1 - r[i].1);
    let solve = |vi: f64, vj: f64, vk: f64| {
        let (fj, fk) = (vj - vi, vk - vi);
        ((fj * ey - fk * dy) / det, (dx * fk - ex * fj) / det)
    };
    let (a, b) = solve(poly[i].0, poly[j].0, poly[k].0);
    let (c, d) = solve(poly[i].1, poly[j].1, poly[k].1);
    let tx = poly[i].0 - a * r[i].0 - b * r[i].1;
    let ty = poly[i].1 - c * r[i].0 - d * r[i].1;
    if ((a * d - b * c).abs() - 1.0).abs() > 1e-6 {
        return None;
    }
    for (&(x, y), &(u, v)) in r.iter().zip(poly) {
        if (a * x + b * y + tx - u).abs() > 1e-5 || (c * x + d * y + ty - v).abs() > 1e-5 {
            return None;
        }
    }
    Some((a, b, c, d, tx, ty))
}

/// `Occupancy._read_of`: the move that carries the first outline it was read with that fits onto `poly`, and the
/// effective shape read with it.
fn read_of<'a>(info: &'a TieInfo, poly: &[Point]) -> Option<(Affine, &'a [K])> {
    info.reads.as_deref()?.iter().find_map(|(r, shapes)| affine_between(r, poly).map(|m| (m, shapes.as_slice())))
}

/// `occupancy._move_shapes`: effective shapes (nm) under a move (mm).
fn move_shapes(shapes: &[K], m: Affine) -> Vec<K> {
    let (a, b, c, d, tx, ty) = m;
    let (tx, ty) = (tx * 1e6, ty * 1e6);
    let at = |x: i64, y: i64| -> P {
        let (x, y) = (x as f64, y as f64);
        (round_even(a * x + b * y + tx), round_even(c * x + d * y + ty))
    };
    shapes
        .iter()
        .map(|sh| match sh {
            K::C(x, y, r) => {
                let p = at(*x, *y);
                K::C(p.0, p.1, *r)
            }
            K::S(ax, ay, bx, by, w) => {
                let (p, q) = (at(*ax, *ay), at(*bx, *by));
                K::S(p.0, p.1, q.0, q.1, *w)
            }
            K::P(pts) => K::P(pts.iter().map(|&(x, y)| at(x, y)).collect()),
            K::R(x, y, w, h, q) => {
                // PAD::buildEffectiveShape lists a rectangle's corners bottom-left first, counter-clockwise, and
                // turns the list by the pad's orientation: a quarter turn starts it a corner on
                let corners = [(*x, *y + *h), (*x + *w, *y + *h), (*x + *w, *y), (*x, *y)];
                let pts: Vec<P> = (0..4).map(|i| {
                    let c = corners[((q + i) as i64).rem_euclid(4) as usize];
                    at(c.0, c.1)
                }).collect();
                let mut xs: Vec<i64> = pts.iter().map(|p| p.0).collect();
                let mut ys: Vec<i64> = pts.iter().map(|p| p.1).collect();
                xs.sort_unstable();
                xs.dedup();
                ys.sort_unstable();
                ys.dedup();
                if xs.len() == 2 && ys.len() == 2 {
                    K::R(xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0], *q)
                } else {
                    K::P(pts)
                }
            }
        })
        .collect()
}

fn nm_poly(poly: &[Point]) -> K {
    K::P(poly.iter().map(|&(x, y)| (to_nm(x), to_nm(y))).collect())
}

/// `Occupancy._pad_standing`: (layers, outlines, effective shape) of a read pad moved by `m`.
fn pad_standing(pad: &ReadPad, m: Affine) -> (u32, Vec<Vec<Point>>, Vec<K>) {
    let (a, b, c, d, tx, ty) = m;
    let polys: Vec<Vec<Point>> = pad.outlines.iter()
        .map(|o| o.iter().map(|&(x, y)| (a * x + b * y + tx, c * x + d * y + ty)).collect())
        .collect();
    let shape = if pad.kshapes.is_empty() {
        polys.iter().map(|p| nm_poly(p)).collect()
    } else {
        move_shapes(&pad.kshapes, m)
    };
    let layers = if a * d - b * c < 0.0 { pad.mirrored } else { pad.layers };
    (layers, polys, shape)
}

/// `Occupancy._kicad_prims`: a footprint's pad or copper drawing standing as `poly`, as the SHAPE_COMPOUND
/// KiCad's DRC collides.
fn kicad_prims(info: &TieInfo, poly: &[Point]) -> Vec<K> {
    match read_of(info, poly) {
        Some((m, shapes)) if !shapes.is_empty() => move_shapes(shapes, m),
        _ => vec![nm_poly(poly)],
    }
}

/// `Occupancy._tie_pads`: (outlines, effective shape) of each net-tie pad of `other`'s footprint of `net`, on a
/// layer of `layers` and `other`'s, where the part stands as `other` does; an item of `owner` asks it.
fn tie_pads(net: &str, owner: &str, layers: u32, other: &Shape) -> Vec<(Vec<Vec<Point>>, Vec<K>)> {
    let mut out = Vec::new();
    if net.is_empty() || owner == other.owner {
        return out;
    }
    let Some(info) = other.tie.as_deref() else { return out };
    let Some(fp) = info.fp.as_deref() else { return out };
    if !info.has_fp || !fp.tie_pads.iter().any(|(n, _)| n == net) {
        return out;
    }
    let Some((m, _)) = read_of(info, &other.poly) else { return out };
    for (n, pad) in &fp.tie_pads {
        if n != net {
            continue;
        }
        let (on, polys, shape) = pad_standing(pad, m);
        if on & layers & other.layers != 0 {
            out.push((polys, shape));
        }
    }
    out
}

/// The tolerances the exclusion is judged with: KiCad's DRC epsilon, mm and nm (`Occupancy._tie_eps`,
/// `_eps_nm`).
#[derive(Clone, Copy)]
pub struct TieEps {
    pub mm: f64,
    pub nm: i64,
}

/// `Occupancy._at_tie_pad`.
fn at_tie_pad(at: P, item: &Shape, other: &Shape, eps: TieEps) -> bool {
    tie_pads(&item.net, &item.owner, item.layers, other).iter().any(|(_, shape)| collide_point(shape, at, eps.nm))
}

/// Whether `net` is among the nets `Occupancy._net_tie_cache` gives `graphic`.
fn net_tie_cache_has(graphic: &Shape, net: &str) -> bool {
    let Some(info) = graphic.tie.as_deref() else { return false };
    let Some(fp) = info.fp.as_deref() else { return false };
    if !fp.cache_nets.contains(net) {
        return false;
    }
    let Some((m, _)) = read_of(info, &graphic.poly) else { return false };
    let drawn = kicad_prims(info, &graphic.poly);
    fp.cache_pads.iter().any(|(pad, nets)| {
        nets.iter().any(|n| n == net) && collide(&pad_standing(pad, m).2, &drawn, 0).is_some()
    })
}

/// `Occupancy._kicad_pair`: the two shapes as KiCad's DRC collides them, or None when either is not one it ports.
fn kicad_pair(s: &Shape, o: &Shape) -> Option<(Vec<K>, Vec<K>)> {
    let one = |sh: &Shape| -> Option<Vec<K>> {
        let info = sh.tie.as_deref()?;
        if info.fp_copper {
            Some(kicad_prims(info, &sh.poly))
        } else {
            info.circle.map(|(x, y, r)| vec![K::C(to_nm(x), to_nm(y), to_nm(r))])
        }
    };
    Some((one(s)?, one(o)?))
}

/// `Occupancy._kicad_exclusion`: IsNetTieExclusion at the position KiCad's DRC gives the collision, whichever
/// of the two it tests first.
fn kicad_exclusion(s: &Shape, o: &Shape, cs: &[K], co: &[K], clearance: f64, eps: TieEps) -> bool {
    let clr = (to_nm(clearance) - eps.nm).max(0); // sub_e()
    let pad = |sh: &Shape| matches!(sh.kind, Kind::Pad | Kind::Through) && sh.tie.as_deref().is_some_and(|t| t.has_fp);
    let padded = pad(s) && pad(o);
    for ((a, ca), (b, cb)) in [((s, cs), (o, co)), ((o, co), (s, cs))] {
        let Some((_, at)) = collide(ca, cb, clr) else { return false };
        if !(at_tie_pad(at, a, b, eps) || (!padded && at_tie_pad(at, b, a, eps))) {
            return false;
        }
    }
    true
}

/// `occupancy._kicad_segment_location`: where KiCad's DRC places a track's collision with a closed polygon.
fn segment_location(ends: (Point, Point), poly: &[Point]) -> Point {
    let nm = |p: Point| (round_even(p.0 * 1e6), round_even(p.1 * 1e6));
    let (a, b) = (nm(ends.0), nm(ends.1));
    let pts: Vec<P> = poly.iter().map(|&p| nm(p)).collect();
    let mut at = a;
    if !point_inside(a, &pts) {
        let mut best: Option<i64> = None;
        for edge in edges(&pts) {
            let d2 = sq_distance(edge, (a, b));
            if best.is_none_or(|b| d2 < b) {
                at = nearest_point(edge, (a, b));
                best = Some(d2);
                if d2 == 0 {
                    break;
                }
            }
        }
    }
    (at.0 as f64 / 1e6, at.1 as f64 / 1e6)
}

fn point_poly_distance(p: Point, poly: &[Point]) -> f64 {
    let n = poly.len();
    (0..n).map(|i| point_segment_distance(p, poly[i], poly[(i + 1) % n])).fold(f64::INFINITY, f64::min)
}

fn in_pads(at: Point, pads: &[(Vec<Vec<Point>>, Vec<K>)], eps: TieEps) -> bool {
    pads.iter().any(|(polys, _)| polys.iter().any(|poly| point_in_polygon(at, poly) || point_poly_distance(at, poly) <= eps.mm))
}

/// `Occupancy._net_tie_exclusion` for two pieces of copper that meet within `clearance` (mm, the one the pair is
/// judged by): whether KiCad's DRC lets them, because one is a net tie's.
pub fn net_tie_exclusion(s: &Shape, o: &Shape, clearance: f64, eps: TieEps) -> bool {
    if s.tie.is_none() && o.tie.is_none() {
        return false;
    }
    for (graphic, other) in [(s, o), (o, s)] {
        if !other.net.is_empty()
            && graphic.tie.as_deref().is_some_and(|t| t.tie_graphic)
            && !other.tie.as_deref().is_some_and(|t| t.fp_graphic)
            && net_tie_cache_has(graphic, &other.net)
        {
            return true;
        }
    }
    if let Some((cs, co)) = kicad_pair(s, o) {
        return kicad_exclusion(s, o, &cs, &co, clearance, eps);
    }
    for (item, other) in [(s, o), (o, s)] {
        let Some(ends) = item.tie.as_deref().and_then(|t| t.ends) else { continue };
        let pads = tie_pads(&item.net, &item.owner, item.layers, other);
        if !pads.is_empty() && in_pads(segment_location(ends, &other.poly), &pads, eps) {
            return true;
        }
    }
    false
}

/// `Occupancy._hole_tie_exclusion`: a hole's net is not tested against a net tie's copper drawing where the
/// hole's centre lies inside a pad of the tie's groups of that net.
pub fn hole_tie_exclusion(hole: &Shape, metal: &Shape, eps: TieEps) -> bool {
    if hole.net.is_empty() || !metal.tie.as_deref().is_some_and(|t| t.fp_graphic) {
        return false;
    }
    let at = ((hole.bbox.0 + hole.bbox.2) / 2.0, (hole.bbox.1 + hole.bbox.3) / 2.0);
    let layers = if hole.layers != 0 { metal.layers & hole.layers } else { metal.layers };
    in_pads(at, &tie_pads(&hole.net, &hole.owner, layers, metal), eps)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rescale_rounds_half_away_from_zero() {
        assert_eq!(rescale(3, 1, 2), 2);
        assert_eq!(rescale(-3, 1, 2), -2);
        assert_eq!(rescale(1_000_000_000_000, 1_000_000_000, 3_000_000_000), 333_333_333_333);
    }

    #[test]
    fn two_circles_collide_at_the_middle_of_their_centres() {
        let hit = collide(&[K::C(0, 0, 100)], &[K::C(150, 0, 100)], 0).unwrap();
        assert_eq!(hit, (0, (75, 0)));
        assert!(collide(&[K::C(0, 0, 100)], &[K::C(300, 0, 100)], 50).is_none());
        assert_eq!(collide(&[K::C(0, 0, 100)], &[K::C(300, 0, 100)], 150).unwrap().0, 100);
    }

    #[test]
    fn a_point_on_a_right_hand_edge_is_outside() {
        let sq = [(0, 0), (10, 0), (10, 10), (0, 10)];
        assert!(point_inside((5, 5), &sq));
        assert!(!point_inside((10, 5), &sq));
    }

    #[test]
    fn a_moved_rectangle_stays_a_rectangle_on_a_quarter_turn() {
        let m = (0.0, -1.0, 1.0, 0.0, 1.0, 2.0);
        let moved = move_shapes(&[K::R(0, 0, 100, 50, 0)], m);
        assert_eq!(moved, vec![K::R(1_000_000 - 50, 2_000_000, 50, 100, 0)]);
    }

    #[test]
    fn the_move_between_an_outline_and_itself_turned_is_found() {
        let r = vec![(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)];
        let turned: Vec<Point> = r.iter().map(|&(x, y)| (-y + 5.0, x + 3.0)).collect();
        let (a, b, c, d, tx, ty) = affine_between(&r, &turned).unwrap();
        assert!((a - 0.0).abs() < 1e-12 && (b + 1.0).abs() < 1e-12 && (c - 1.0).abs() < 1e-12 && d.abs() < 1e-12);
        assert!((tx - 5.0).abs() < 1e-12 && (ty - 3.0).abs() < 1e-12);
        assert!(affine_between(&r, &[(0.0, 0.0), (3.0, 0.0), (3.0, 1.0), (0.0, 1.0)]).is_none());
    }
}
