//! The board's keep-in and its reservations, as `Occupancy.legal()` tests a
//! candidate's body box against them before any obstacle: ported
//! expression for expression from `Occupancy._edge_or_reservation_conflict`
//! and what it calls - `Outline.why_not`, `Disc.why_not` (values.py),
//! `Cutouts.why_not`, `segment_box`, `point_segment`, `crosses`
//! (cutouts.py), `Reservation.overlaps` and `PolyRaster.classify`
//! (occupancy.py, geometry.py) - so every comparison lands the same way.
//!
//! `Where`, the segment index those use in Python, only narrows which
//! segments are looked at: every segment it would offer is visited here in
//! the same declared order, with the same test, so the answer is the same.

use crate::exact::hypot;
use crate::geometry::polys_overlap;

type Point = (f64, f64);

/// A box as `values.Box`: (left, top, right, bottom).
#[derive(Clone, Copy, Debug)]
pub struct B {
    pub l: f64,
    pub t: f64,
    pub r: f64,
    pub b: f64,
}

impl B {
    /// `Box.overlaps(other)` with no gap: strict on every side.
    pub fn overlaps(&self, o: &B) -> bool {
        self.l < o.r + 0.0 && o.l < self.r + 0.0 && self.t < o.b + 0.0 && o.t < self.b + 0.0
    }
    /// `Box.contains(other)`.
    pub fn contains(&self, o: &B) -> bool {
        self.l <= o.l && o.r <= self.r && self.t <= o.t && o.b <= self.b
    }
    pub fn of_points(pts: &[Point]) -> B {
        let mut b = B { l: pts[0].0, t: pts[0].1, r: pts[0].0, b: pts[0].1 };
        for &(x, y) in &pts[1..] {
            if x < b.l { b.l = x; }
            if y < b.t { b.t = y; }
            if x > b.r { b.r = x; }
            if y > b.b { b.b = y; }
        }
        b
    }
    pub fn polygon(&self) -> Vec<Point> {
        vec![(self.l, self.t), (self.r, self.t), (self.r, self.b), (self.l, self.b)]
    }
}

pub const NM: f64 = 1e-5; // cutouts.NM and values._NM: ten KiCad units

/// Python's `min(a, b)`: the first unless the second is smaller.
#[inline]
fn pmin(a: f64, b: f64) -> f64 { if b < a { b } else { a } }
/// Python's `max(a, b)`: the first unless the second is larger.
#[inline]
fn pmax(a: f64, b: f64) -> f64 { if b > a { b } else { a } }

/// `cutouts.point_segment`.
pub fn point_segment(px: f64, py: f64, x1: f64, y1: f64, x2: f64, y2: f64) -> f64 {
    let (dx, dy) = (x2 - x1, y2 - y1);
    let n = dx * dx + dy * dy;
    let t = if n < 1e-18 { 0.0 } else { pmax(0.0, pmin(1.0, ((px - x1) * dx + (py - y1) * dy) / n)) };
    hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

#[inline]
fn side(ax: f64, ay: f64, bx: f64, by: f64, px: f64, py: f64) -> f64 {
    (bx - ax) * (py - ay) - (by - ay) * (px - ax)
}

/// `cutouts.crosses`.
pub fn crosses(ax: f64, ay: f64, bx: f64, by: f64, cx: f64, cy: f64, dx: f64, dy: f64) -> bool {
    let (d1, d2) = (side(cx, cy, dx, dy, ax, ay), side(cx, cy, dx, dy, bx, by));
    let (d3, d4) = (side(ax, ay, bx, by, cx, cy), side(ax, ay, bx, by, dx, dy));
    ((d1 > 0.0) != (d2 > 0.0)) && ((d3 > 0.0) != (d4 > 0.0))
}

/// `cutouts.segment_box`.
pub fn segment_box(x1: f64, y1: f64, x2: f64, y2: f64, b: &B) -> f64 {
    if (b.l <= x1 && x1 <= b.r && b.t <= y1 && y1 <= b.b) || (b.l <= x2 && x2 <= b.r && b.t <= y2 && y2 <= b.b) {
        return 0.0;
    }
    let corners = [(b.l, b.t), (b.r, b.t), (b.r, b.b), (b.l, b.b)];
    let mut d = point_segment(corners[0].0, corners[0].1, x1, y1, x2, y2);
    for &(cx, cy) in &corners[1..] {
        d = pmin(d, point_segment(cx, cy, x1, y1, x2, y2));
    }
    for k in 0..4 {
        let (ax, ay) = corners[k];
        let (bx, by) = corners[(k + 1) % 4];
        // min(d, a, b): each replaces the running value only when smaller
        d = pmin(pmin(d, point_segment(x1, y1, ax, ay, bx, by)), point_segment(x2, y2, ax, ay, bx, by));
        if crosses(x1, y1, x2, y2, ax, ay, bx, by) {
            return 0.0;
        }
    }
    d
}

/// One loop segment, as `Where` keeps it: its ends, its loop, its box.
#[derive(Clone, Copy)]
pub struct Seg {
    x1: f64, y1: f64, x2: f64, y2: f64,
    n: usize,
    lo_x: f64, lo_y: f64, hi_x: f64, hi_y: f64,
}

/// Loops as `Where` takes them, their segments in declared order.
pub struct Loops {
    segs: Vec<Seg>,
    count: usize,
}

impl Loops {
    pub fn new(loops: &[Vec<Point>]) -> Loops {
        let mut segs = Vec::new();
        for (n, lp) in loops.iter().enumerate() {
            let k = lp.len();
            for i in 0..k {
                let (x1, y1) = lp[i];
                let (x2, y2) = lp[(i + 1) % k];
                segs.push(Seg {
                    x1, y1, x2, y2, n,
                    lo_x: pmin(x1, x2), lo_y: pmin(y1, y2), hi_x: pmax(x1, x2), hi_y: pmax(y1, y2),
                });
            }
        }
        Loops { segs, count: loops.len() }
    }

    /// `Where.loops_around`: which loops enclose the point, as a bitset.
    fn loops_around(&self, x: f64, y: f64) -> Vec<bool> {
        let mut odd = vec![false; self.count];
        for s in &self.segs {
            if (s.y1 > y) != (s.y2 > y) && x < s.x1 + (y - s.y1) / (s.y2 - s.y1) * (s.x2 - s.x1) {
                odd[s.n] = !odd[s.n];
            }
        }
        odd
    }

    /// The first segment, in declared order, within `margin` of the box
    /// as `why_not` finds it: its loop index.
    fn too_near(&self, b: &B, margin: f64) -> Option<usize> {
        let (left, top) = (b.l - margin, b.t - margin);
        let (right, bottom) = (b.r + margin, b.b + margin);
        for s in &self.segs {
            if s.hi_x < left || s.lo_x > right || s.hi_y < top || s.lo_y > bottom {
                continue;
            }
            if segment_box(s.x1, s.y1, s.x2, s.y2, b) < margin - NM {
                return Some(s.n);
            }
        }
        None
    }
}

/// Why an edge check refused a body box: the sentence it would say.
pub const OUTSIDE: u8 = 1;       // "outside the board"
pub const IN_CUTOUT: u8 = 2;     // "inside a cutout"
pub const PAST_BOARD: u8 = 3;    // "past the board's keep-in (%.2f mm)"
pub const PAST_CUTOUT: u8 = 4;   // "past the cutout's keep-in (%.2f mm)"
pub const PAST_RIM: u8 = 5;      // "past the rim's keep-in (%.2f mm)"
pub const INTO_BORE: u8 = 6;     // "into the bore's keep-in (%.2f mm)"
pub const PAST_MARGIN: u8 = 7;   // "body box %s crosses the board edge margin (%.2f mm)"

/// `Cutouts.why_not`.
fn cutouts_why_not(c: &Loops, b: &B, margin: f64) -> Option<u8> {
    if c.count == 0 {
        return None;
    }
    let cx = (b.l + b.r) / 2.0;
    let cy = (b.t + b.b) / 2.0;
    if c.loops_around(cx, cy).iter().any(|&o| o) {
        return Some(IN_CUTOUT);
    }
    c.too_near(b, margin).map(|_| PAST_CUTOUT)
}

pub enum Shape {
    /// No shape: the board box, inset by the margin, then its cutouts.
    Rect { board: B, cutouts: Loops },
    /// `values.Disc`: its centre, radius and bore (radius), then its cutouts.
    Disc { cx: f64, cy: f64, radius: f64, bore: f64, cutouts: Loops },
    /// `outline.Outline`: the board's loop first, then each cutout's.
    Outline { loops: Loops },
}

pub struct Keepin {
    pub margin: Option<f64>,
    pub shape: Shape,
}

impl Keepin {
    /// Why the body box may not be there, as `_edge_or_reservation_conflict`
    /// finds it; `None` when the edge allows it.
    pub fn why_not(&self, b: &B) -> Option<u8> {
        let margin = self.margin?;
        match &self.shape {
            Shape::Rect { board, cutouts } => {
                let d = -margin;
                let inner = B { l: board.l - d, t: board.t - d, r: board.r + d, b: board.b + d };
                if !inner.contains(b) {
                    return Some(PAST_MARGIN);
                }
                cutouts_why_not(cutouts, b, margin)
            }
            Shape::Disc { cx, cy, radius, bore, cutouts } => {
                let mut far = hypot(b.l - cx, b.t - cy);
                for (x, y) in [(b.l, b.b), (b.r, b.t), (b.r, b.b)] {
                    far = pmax(far, hypot(x - cx, y - cy));
                }
                if far > radius - margin + NM {
                    return Some(PAST_RIM);
                }
                if *bore != 0.0 {
                    let dx = pmax(pmax(b.l - cx, 0.0), cx - b.r);
                    let dy = pmax(pmax(b.t - cy, 0.0), cy - b.b);
                    if hypot(dx, dy) < bore + margin - NM {
                        return Some(INTO_BORE);
                    }
                }
                cutouts_why_not(cutouts, b, margin)
            }
            Shape::Outline { loops } => {
                let odd = loops.loops_around((b.l + b.r) / 2.0, (b.t + b.b) / 2.0);
                if !odd.first().copied().unwrap_or(false) {
                    return Some(OUTSIDE);
                }
                if odd.iter().skip(1).any(|&o| o) {
                    return Some(IN_CUTOUT);
                }
                loops.too_near(b, margin).map(|n| if n == 0 { PAST_BOARD } else { PAST_CUTOUT })
            }
        }
    }
}

/// `geometry.PolyRaster`, rastered in Python and handed over.
pub struct Raster {
    pub x0: f64,
    pub y0: f64,
    pub cell: f64,
    pub nx: i64,
    pub ny: i64,
    pub state: Vec<Vec<u8>>, // per row: 1 inside, 0 outside, 2 crossed
}

impl Raster {
    /// `PolyRaster.classify`: Some(overlaps) when the cells decide it.
    pub fn classify(&self, b: &B) -> Option<bool> {
        let c = self.cell;
        let i0 = 0i64.max(((b.l - self.x0) / c).floor() as i64);
        let i1 = self.nx.min(((b.r - self.x0) / c).ceil() as i64);
        let j0 = 0i64.max(((b.t - self.y0) / c).floor() as i64);
        let j1 = self.ny.min(((b.b - self.y0) / c).ceil() as i64);
        let mut crossed = false;
        for j in j0..j1 {
            let b0 = self.y0 + j as f64 * c;
            if !(b0 < b.b && b0 + c > b.t) {
                continue;
            }
            let row = &self.state[j as usize];
            for i in i0..i1 {
                let a0 = self.x0 + i as f64 * c;
                if !(a0 < b.r && a0 + c > b.l) {
                    continue;
                }
                match row[i as usize] {
                    1 => return Some(true),
                    2 => crossed = true,
                    _ => {}
                }
            }
        }
        if crossed { None } else { Some(false) }
    }
}

/// `occupancy.Reservation`, as far as `overlaps` reads it.
pub struct Reservation {
    pub poly: Vec<Point>,
    pub bbox: B,
    pub raster: Option<Raster>,
}

impl Reservation {
    /// `Reservation.overlaps(body)`.
    pub fn overlaps(&self, body: &B) -> bool {
        if !self.bbox.overlaps(body) {
            return false;
        }
        if self.poly.len() >= 24 {
            if let Some(r) = &self.raster {
                if let Some(hit) = r.classify(body) {
                    return hit;
                }
            }
        }
        polys_overlap(&self.poly, &body.polygon())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_box_inside_a_square_outline_is_allowed_and_one_outside_is_not() {
        let sq = vec![(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)];
        let k = Keepin { margin: Some(0.5), shape: Shape::Outline { loops: Loops::new(&[sq]) } };
        assert_eq!(k.why_not(&B { l: 2.0, t: 2.0, r: 3.0, b: 3.0 }), None);
        assert_eq!(k.why_not(&B { l: 12.0, t: 2.0, r: 13.0, b: 3.0 }), Some(OUTSIDE));
        assert_eq!(k.why_not(&B { l: 0.2, t: 2.0, r: 1.0, b: 3.0 }), Some(PAST_BOARD));
    }

    #[test]
    fn a_rect_board_insets_by_its_margin() {
        let k = Keepin { margin: Some(1.0), shape: Shape::Rect { board: B { l: 0.0, t: 0.0, r: 10.0, b: 10.0 }, cutouts: Loops::new(&[]) } };
        assert_eq!(k.why_not(&B { l: 1.0, t: 1.0, r: 9.0, b: 9.0 }), None);
        assert_eq!(k.why_not(&B { l: 0.9, t: 1.0, r: 9.0, b: 9.0 }), Some(PAST_MARGIN));
    }
}
