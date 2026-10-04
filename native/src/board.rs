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
use crate::geometry::{polys_overlap, Prepared};

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

/// The segments of loops binned by y, for `loops_around`: bin `k` holds every segment whose y range
/// reaches the bin, so a ray at y need only look at its bin.
struct YBins {
    y0: f64,
    h: f64,
    bins: Vec<Vec<u32>>,
}

/// The segments of loops binned over their boxes in a grid, for `too_near`.
struct Grid {
    x0: f64,
    y0: f64,
    w: f64,
    h: f64,
    nx: usize,
    ny: usize,
    cells: Vec<Vec<u32>>,
}

/// Most bin entries an index may hold: past it a loop set is scanned whole, as it was.
const MAX_ENTRIES: usize = 4_000_000;

#[inline]
fn bin_of(v: f64, v0: f64, size: f64, n: usize) -> usize {
    (((v - v0) / size).floor().max(0.0) as usize).min(n - 1)
}

impl YBins {
    fn new(segs: &[Seg]) -> Option<YBins> {
        if segs.is_empty() {
            return None;
        }
        let y0 = segs.iter().fold(f64::INFINITY, |m, s| m.min(s.lo_y));
        let y1 = segs.iter().fold(f64::NEG_INFINITY, |m, s| m.max(s.hi_y));
        let n = segs.len().clamp(1, 4096);
        let h = (y1 - y0) / n as f64;
        if !(h > 0.0 && h.is_finite()) {
            return None;
        }
        let mut bins = vec![Vec::new(); n];
        let mut entries = 0usize;
        for (i, s) in segs.iter().enumerate() {
            for k in bin_of(s.lo_y, y0, h, n)..=bin_of(s.hi_y, y0, h, n) {
                bins[k].push(i as u32);
                entries += 1;
            }
            if entries > MAX_ENTRIES {
                return None;
            }
        }
        Some(YBins { y0, h, bins })
    }
}

impl Grid {
    fn new(segs: &[Seg]) -> Option<Grid> {
        if segs.is_empty() {
            return None;
        }
        let x0 = segs.iter().fold(f64::INFINITY, |m, s| m.min(s.lo_x));
        let x1 = segs.iter().fold(f64::NEG_INFINITY, |m, s| m.max(s.hi_x));
        let y0 = segs.iter().fold(f64::INFINITY, |m, s| m.min(s.lo_y));
        let y1 = segs.iter().fold(f64::NEG_INFINITY, |m, s| m.max(s.hi_y));
        let n = ((segs.len() as f64).sqrt().ceil() as usize).clamp(1, 256);
        let (w, h) = ((x1 - x0) / n as f64, (y1 - y0) / n as f64);
        if !(w > 0.0 && h > 0.0 && w.is_finite() && h.is_finite()) {
            return None;
        }
        let mut cells = vec![Vec::new(); n * n];
        let mut entries = 0usize;
        for (i, s) in segs.iter().enumerate() {
            for cy in bin_of(s.lo_y, y0, h, n)..=bin_of(s.hi_y, y0, h, n) {
                for cx in bin_of(s.lo_x, x0, w, n)..=bin_of(s.hi_x, x0, w, n) {
                    cells[cy * n + cx].push(i as u32);
                    entries += 1;
                }
            }
            if entries > MAX_ENTRIES {
                return None;
            }
        }
        Some(Grid { x0, y0, w, h, nx: n, ny: n, cells })
    }
}

/// Loops as `Where` takes them, their segments in declared order.
pub struct Loops {
    segs: Vec<Seg>,
    count: usize,
    ybins: Option<YBins>,
    grid: Option<Grid>,
}

/// Which loops enclose a point: the first (the board's, for an outline), and any of the rest.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Around {
    pub first: bool,
    pub others: bool,
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
        let (ybins, grid) = (YBins::new(&segs), Grid::new(&segs));
        Loops { segs, count: loops.len(), ybins, grid }
    }

    /// One crossing of the ray from (x, y), as `Where.loops_around` counts them.
    #[inline]
    fn crosses_ray(s: &Seg, x: f64, y: f64) -> bool {
        (s.y1 > y) != (s.y2 > y) && x < s.x1 + (y - s.y1) / (s.y2 - s.y1) * (s.x2 - s.x1)
    }

    /// `Where.loops_around`: which loops enclose the point, as a bitset. A parity does not depend on the
    /// order its crossings are counted in, so only the segments whose y range reaches the point's bin are
    /// looked at; the rest cannot cross the ray.
    pub fn around(&self, x: f64, y: f64) -> Around {
        if self.count <= 64 {
            let mut odd = 0u64;
            let mut flip = |i: usize| {
                let s = &self.segs[i];
                if Self::crosses_ray(s, x, y) {
                    odd ^= 1u64 << s.n;
                }
            };
            match &self.ybins {
                Some(yb) => {
                    for &i in &yb.bins[bin_of(y, yb.y0, yb.h, yb.bins.len())] {
                        flip(i as usize);
                    }
                }
                None => (0..self.segs.len()).for_each(&mut flip),
            }
            return Around { first: odd & 1 != 0, others: odd >> 1 != 0 };
        }
        let odd = self.loops_around_scan(x, y);
        Around { first: odd.first().copied().unwrap_or(false), others: odd.iter().skip(1).any(|&o| o) }
    }

    /// `Where.loops_around`, every segment in turn.
    fn loops_around_scan(&self, x: f64, y: f64) -> Vec<bool> {
        let mut odd = vec![false; self.count];
        for s in &self.segs {
            if Self::crosses_ray(s, x, y) {
                odd[s.n] = !odd[s.n];
            }
        }
        odd
    }

    /// The loop of the first segment, in declared order, within `margin` of the box as `why_not` finds
    /// it. The loops come in order, so that is the lowest loop with a segment that near: only the segments
    /// whose boxes touch the box grown by `margin` (the grid's cells under it) are tested.
    fn too_near(&self, b: &B, margin: f64) -> Option<usize> {
        let (left, top) = (b.l - margin, b.t - margin);
        let (right, bottom) = (b.r + margin, b.b + margin);
        let near = |s: &Seg| -> bool {
            !(s.hi_x < left || s.lo_x > right || s.hi_y < top || s.lo_y > bottom)
                && segment_box(s.x1, s.y1, s.x2, s.y2, b) < margin - NM
        };
        match &self.grid {
            Some(g) => {
                let mut least: Option<usize> = None;
                for cy in bin_of(top, g.y0, g.h, g.ny)..=bin_of(bottom, g.y0, g.h, g.ny) {
                    for cx in bin_of(left, g.x0, g.w, g.nx)..=bin_of(right, g.x0, g.w, g.nx) {
                        for &i in &g.cells[cy * g.nx + cx] {
                            let s = &self.segs[i as usize];
                            if least.is_none_or(|l| s.n < l) && near(s) {
                                if s.n == 0 {
                                    return Some(0);
                                }
                                least = Some(s.n);
                            }
                        }
                    }
                }
                least
            }
            None => self.too_near_scan(b, margin),
        }
    }

    /// `too_near`, every segment in turn.
    fn too_near_scan(&self, b: &B, margin: f64) -> Option<usize> {
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
/// `occupancy.FLAT_EDGE_MARGIN`: how far inside the edge a courtyard or body is held.
pub const FLAT_EDGE_MARGIN: f64 = 2e-5;
pub const COPPER_EDGE: u8 = 16;  // added to a code that refuses an item's copper, judged at the keep-in
pub const PAST_MARGIN: u8 = 7;   // "body box %s crosses the board edge margin (%.2f mm)"

/// `Cutouts.why_not`.
fn cutouts_why_not(c: &Loops, b: &B, margin: f64) -> Option<u8> {
    if c.count == 0 {
        return None;
    }
    let cx = (b.l + b.r) / 2.0;
    let cy = (b.t + b.b) / 2.0;
    let around = c.around(cx, cy);
    if around.first || around.others {
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
        self.why_not_at(b, self.margin?)
    }

    /// As `why_not`, for a box judged against the edge itself (`FLAT_EDGE_MARGIN`,
    /// no more than the keep-in): a courtyard or body. A board with no edge
    /// check allows it.
    pub fn why_not_flat(&self, b: &B) -> Option<u8> {
        let margin = self.margin?;
        self.why_not_at(b, pmin(margin, FLAT_EDGE_MARGIN))
    }

    /// `values.Disc.why_not`, `outline.Outline.why_not` and `Cutouts.why_not`
    /// as `Occupancy._edge_why` asks them, at `margin`.
    fn why_not_at(&self, b: &B, margin: f64) -> Option<u8> {
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
                let around = loops.around((b.l + b.r) / 2.0, (b.t + b.b) / 2.0);
                if !around.first {
                    return Some(OUTSIDE);
                }
                if around.others {
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
    /// Whether the polygon lies clear of `b` and of a `slack` all round it: every cell the grown box
    /// touches, edges included, has no edge of the polygon in it and its corner outside. The polygon then
    /// shares no interior with anything inside `b`, whatever an overlap test's tolerances.
    pub fn clear_of(&self, b: &B, slack: f64) -> bool {
        let g = B { l: b.l - slack, t: b.t - slack, r: b.r + slack, b: b.b + slack };
        let c = self.cell;
        let i0 = 0i64.max(((g.l - self.x0) / c).floor() as i64);
        let i1 = self.nx.min(((g.r - self.x0) / c).ceil() as i64);
        let j0 = 0i64.max(((g.t - self.y0) / c).floor() as i64);
        let j1 = self.ny.min(((g.b - self.y0) / c).ceil() as i64);
        for j in j0..j1 {
            let row = &self.state[j as usize];
            for i in i0..i1 {
                if row[i as usize] != 0 {
                    return false;
                }
            }
        }
        true
    }

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
    /// A KiCad rule area: judged by each part's courtyard polygon, not its body box.
    pub courtyard: bool,
    /// The polygon indexed, when it has many points: the overlap test then looks only at the edges near a box.
    pub prepared: Option<Prepared>,
}

impl Reservation {
    pub fn new(poly: Vec<Point>, raster: Option<Raster>, courtyard: bool) -> Reservation {
        let bbox = B::of_points(&poly);
        let prepared = if poly.len() >= 24 { Prepared::new(&poly) } else { None };
        Reservation { poly, bbox, raster, courtyard, prepared }
    }

    /// `polys_overlap(poly, other)`.
    pub fn polygon_overlaps(&self, other: &[Point]) -> bool {
        match &self.prepared {
            Some(p) => p.overlaps(other),
            None => polys_overlap(&self.poly, other),
        }
    }

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
        self.polygon_overlaps(&body.polygon())
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
    fn a_courtyard_is_held_to_the_edge_itself_and_copper_to_the_margin() {
        let sq = vec![(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)];
        let k = Keepin { margin: Some(0.5), shape: Shape::Outline { loops: Loops::new(&[sq]) } };
        let near = B { l: 0.2, t: 2.0, r: 1.0, b: 3.0 };
        assert_eq!(k.why_not_flat(&near), None);
        assert_eq!(k.why_not(&near), Some(PAST_BOARD));
        assert_eq!(k.why_not_flat(&B { l: -0.1, t: 2.0, r: 1.0, b: 3.0 }), Some(PAST_BOARD));
        let none = Keepin { margin: None, shape: Shape::Rect { board: B { l: 0.0, t: 0.0, r: 1.0, b: 1.0 }, cutouts: Loops::new(&[]) } };
        assert_eq!(none.why_not_flat(&B { l: 5.0, t: 5.0, r: 6.0, b: 6.0 }), None);
    }

    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> f64 {
            self.0 ^= self.0 << 13;
            self.0 ^= self.0 >> 7;
            self.0 ^= self.0 << 17;
            (self.0 >> 11) as f64 / (1u64 << 53) as f64
        }
        fn between(&mut self, a: f64, b: f64) -> f64 {
            a + (b - a) * self.next()
        }
        fn below(&mut self, n: usize) -> usize {
            ((self.next() * n as f64) as usize).min(n - 1)
        }
        /// A value on a 0.25 grid half the time, so that ties with vertices and cell edges happen.
        fn coord(&mut self, a: f64, b: f64) -> f64 {
            let v = self.between(a, b);
            if self.below(2) == 0 { (v * 4.0).round() / 4.0 } else { v }
        }
    }

    fn random_loops(g: &mut Rng, with_cutouts: usize) -> Vec<Vec<Point>> {
        let mut loops = Vec::new();
        // the board: a rounded, notched shape of many segments
        let n = 3 + g.below(300);
        let board: Vec<Point> = (0..n).map(|i| {
            let a = std::f64::consts::TAU * i as f64 / n as f64;
            let r = 20.0 + if g.below(8) == 0 { g.between(-5.0, 0.0) } else { 0.0 };
            (g.coord(0.0, 0.0) + 30.0 + r * a.cos(), 25.0 + r * a.sin())
        }).collect();
        loops.push(board);
        for _ in 0..with_cutouts {
            let (cx, cy) = (g.between(15.0, 45.0), g.between(15.0, 35.0));
            let k = 3 + g.below(12);
            loops.push((0..k).map(|i| {
                let a = std::f64::consts::TAU * i as f64 / k as f64;
                (g.coord(cx, cx) + g.between(1.0, 3.0) * a.cos(), cy + g.between(1.0, 3.0) * a.sin())
            }).collect());
        }
        loops
    }

    #[test]
    fn the_indexed_edge_tests_give_the_scans_answers() {
        let mut g = Rng(0x2545F4914F6CDD1D);
        let mut inside = 0usize;
        let mut near = 0usize;
        let mut total = 0usize;
        for round in 0..60 {
            let cutouts = match round % 4 { 0 => 0, 1 => 3, 2 => 70, _ => 1 };    // 70: past what a bitmask holds
            let loops = Loops::new(&random_loops(&mut g, cutouts));
            for _ in 0..400 {
                let (x, y) = (g.coord(0.0, 60.0), g.coord(0.0, 50.0));
                let want = loops.loops_around_scan(x, y);
                let got = loops.around(x, y);
                assert_eq!(got.first, want[0], "round {round} first at ({x}, {y})");
                assert_eq!(got.others, want.iter().skip(1).any(|&o| o), "round {round} others at ({x}, {y})");
                let (w, h) = (g.between(0.1, 6.0), g.between(0.1, 6.0));
                let b = B { l: x, t: y, r: x + w, b: y + h };
                let margin = [0.0, 2e-5, 0.3, 1.0, 4.0][g.below(5)];
                let (a, c) = (loops.too_near(&b, margin), loops.too_near_scan(&b, margin));
                assert_eq!(a, c, "round {round} box {b:?} margin {margin}");
                total += 1;
                inside += want[0] as usize;
                near += c.is_some() as usize;
            }
        }
        assert!(inside > total / 5 && inside < total * 4 / 5, "{inside} of {total} inside");
        assert!(near > total / 10 && near < total * 9 / 10, "{near} of {total} near");
    }

    #[test]
    fn a_rect_board_insets_by_its_margin() {
        let k = Keepin { margin: Some(1.0), shape: Shape::Rect { board: B { l: 0.0, t: 0.0, r: 10.0, b: 10.0 }, cutouts: Loops::new(&[]) } };
        assert_eq!(k.why_not(&B { l: 1.0, t: 1.0, r: 9.0, b: 9.0 }), None);
        assert_eq!(k.why_not(&B { l: 0.9, t: 1.0, r: 9.0, b: 9.0 }), Some(PAST_MARGIN));
    }
}
