//! The reservation pass of `sweep`: the first reservation, in `reservations`
//! order, that refuses a candidate, and the part it refuses.
//!
//! `reference` is the pass as it was first written, a test against every
//! reservation in turn. `ReservationPass` answers the same, faster: it sets
//! aside, once per sweep, the reservations whose box lies clear of every
//! place the sweep's candidates can put the item, and tests the rest in the
//! same order with the same expressions, without building a polygon for a
//! courtyard that is clear of the reservation's box.

use crate::board::{Reservation, B};
use crate::exact::clean9;
use crate::geometry::polys_overlap;

type Point = (f64, f64);

/// How far past a sweep's candidates a reservation must lie to be set aside:
/// a candidate's boxes are rounded to nine places after they are shifted.
const REACH_SLACK: f64 = 1e-6;

/// The bounds of an unshifted polygon, as `B::of_points`; None for a polygon with no points.
pub fn poly_box(poly: &[Point]) -> Option<B> {
    if poly.is_empty() { None } else { Some(B::of_points(poly)) }
}

/// A box moved by (x, y), not rounded: the box of the polygon moved by (x, y) is exactly this, since
/// adding a number to each coordinate keeps their order.
#[inline]
fn moved(b: &B, x: f64, y: f64) -> B {
    B { l: b.l + x, t: b.t + y, r: b.r + x, b: b.b + y }
}

/// The smallest box holding both.
pub fn hull(a: &B, b: &B) -> B {
    B { l: a.l.min(b.l), t: a.t.min(b.t), r: a.r.max(b.r), b: a.b.max(b.b) }
}

/// One turn's yards as the pass takes them: each part's courtyard polygon, or None, and its box.
pub struct TurnYards {
    pub polys: Vec<Option<Vec<Point>>>,
    pub boxes: Vec<Option<B>>,
}

impl TurnYards {
    pub fn new(polys: &[Option<Vec<Point>>]) -> TurnYards {
        TurnYards {
            polys: polys.to_vec(),
            boxes: polys.iter().map(|p| p.as_deref().and_then(poly_box)).collect(),
        }
    }
}

/// The pass as first written: every reservation in `reservations` order, each allocating what it needs.
/// `members` are the shifted boxes of a cell's parts (none for an item with no parts); `judged` and `yards`
/// as `sweep` takes them.
#[allow(clippy::too_many_arguments)]
pub fn reference(
    res: &[Reservation],
    reservations: &[usize],
    judged: Option<&Vec<Vec<usize>>>,
    yards: &[Vec<Option<Vec<Point>>>],
    turn: usize,
    body: &B,
    members: &[B],
    x: f64,
    y: f64,
) -> Option<(usize, usize)> {
    reservations.iter().enumerate().find_map(|(pos, ri)| {
        let r = &res[*ri];
        if r.courtyard {
            let ys: &[Option<Vec<Point>>] = yards.get(turn).map(|v| v.as_slice()).unwrap_or(&[]);
            let yard_hit = |k: usize| -> bool {
                match ys.get(k) {
                    Some(Some(poly)) => {
                        let moved: Vec<Point> = poly.iter().map(|p| (p.0 + x, p.1 + y)).collect();
                        r.bbox.overlaps(&B::of_points(&moved)) && polys_overlap(&r.poly, &moved)
                    }
                    _ => false,
                }
            };
            if members.is_empty() {
                return if yard_hit(0) { Some((*ri, 0usize)) } else { None };
            }
            let idx: Vec<usize> = match judged {
                Some(j) => j[pos].clone(),
                None => (0..members.len()).collect(),
            };
            return idx
                .into_iter()
                .find(|&k| k < members.len() && if k < ys.len() { yard_hit(k) } else { r.overlaps(&members[k]) })
                .map(|k| (*ri, k + 1));
        }
        if !r.overlaps(body) {
            return None;
        }
        if members.is_empty() {
            return Some((*ri, 0usize));
        }
        let hit = match judged {
            Some(j) => j[pos].iter().copied().find(|&k| k < members.len() && r.overlaps(&members[k])),
            None => (0..members.len()).find(|&k| r.overlaps(&members[k])),
        };
        hit.map(|k| (*ri, k + 1))
    })
}

/// The live reservations' boxes binned in a grid: the cell a point falls in holds every reservation whose box
/// reaches it (as their indexes into `live`, in order).
struct ResGrid {
    x0: f64,
    y0: f64,
    w: f64,
    h: f64,
    n: usize,
    cells: Vec<Vec<u32>>,
}

/// Most entries a grid may hold: past it the live reservations are all asked of, as before.
const MAX_ENTRIES: usize = 2_000_000;

#[inline]
fn bin_of(v: f64, v0: f64, size: f64, n: usize) -> usize {
    (((v - v0) / size).floor().max(0.0) as usize).min(n - 1)
}

impl ResGrid {
    fn new(res: &[Reservation], live: &[(usize, usize)]) -> Option<ResGrid> {
        if live.len() < 8 {
            return None;
        }
        let boxes = || live.iter().map(|&(_, ri)| &res[ri].bbox);
        let x0 = boxes().fold(f64::INFINITY, |m, b| m.min(b.l));
        let x1 = boxes().fold(f64::NEG_INFINITY, |m, b| m.max(b.r));
        let y0 = boxes().fold(f64::INFINITY, |m, b| m.min(b.t));
        let y1 = boxes().fold(f64::NEG_INFINITY, |m, b| m.max(b.b));
        let n = ((live.len() as f64).sqrt().ceil() as usize * 2).clamp(1, 64);
        let (w, h) = ((x1 - x0) / n as f64, (y1 - y0) / n as f64);
        if !(w > 0.0 && h > 0.0 && w.is_finite() && h.is_finite()) {
            return None;
        }
        let mut cells = vec![Vec::new(); n * n];
        let mut entries = 0usize;
        for (k, &(_, ri)) in live.iter().enumerate() {
            let b = &res[ri].bbox;
            for cy in bin_of(b.t, y0, h, n)..=bin_of(b.b, y0, h, n) {
                for cx in bin_of(b.l, x0, w, n)..=bin_of(b.r, x0, w, n) {
                    cells[cy * n + cx].push(k as u32);
                    entries += 1;
                }
            }
            if entries > MAX_ENTRIES {
                return None;
            }
        }
        Some(ResGrid { x0, y0, w, h, n, cells })
    }
}

pub struct ReservationPass<'a> {
    res: &'a [Reservation],
    judged: Option<&'a Vec<Vec<usize>>>,
    yards: &'a [TurnYards],
    /// per turn, a box holding the item's body, parts and courtyards at the origin
    hulls: &'a [B],
    /// (position in `reservations`, index in the board's reservations), in `reservations` order: the ones that
    /// can reach a candidate of this sweep.
    live: Vec<(usize, usize)>,
    /// `live`, binned: a candidate asks only the reservations whose boxes reach the cells under its hull
    grid: Option<ResGrid>,
    /// the indexes into `live` found for a candidate, and the stamps that keep one from being found twice
    found: Vec<u32>,
    stamp: Vec<u32>,
    tick: u32,
    scratch: Vec<Point>,
}

impl<'a> ReservationPass<'a> {
    /// `reach`: a box that holds every box and courtyard of every candidate this pass will be asked of
    /// (None: no limit).
    pub fn new(
        res: &'a [Reservation],
        reservations: &[usize],
        judged: Option<&'a Vec<Vec<usize>>>,
        yards: &'a [TurnYards],
        hulls: &'a [B],
        reach: Option<B>,
    ) -> ReservationPass<'a> {
        let live: Vec<(usize, usize)> = reservations
            .iter()
            .enumerate()
            .filter(|(_, ri)| match &reach {
                Some(g) => res[**ri].bbox.overlaps(&B { l: g.l - REACH_SLACK, t: g.t - REACH_SLACK, r: g.r + REACH_SLACK, b: g.b + REACH_SLACK }),
                None => true,
            })
            .map(|(pos, ri)| (pos, *ri))
            .collect();
        let grid = ResGrid::new(res, &live);
        let stamp = vec![0; live.len()];
        ReservationPass { res, judged, yards, hulls, live, grid, found: Vec::new(), stamp, tick: 0, scratch: Vec::new() }
    }

    /// As `reference`, over the reservations that can reach. `parts` are the unshifted boxes of a cell's
    /// parts, each shifted (and rounded as a candidate's boxes are) only when a reservation asks for it;
    /// `body` is the candidate's shifted body box.
    pub fn hit(&mut self, turn: usize, body: &B, parts: &[B], x: f64, y: f64) -> Option<(usize, usize)> {
        let empty = TurnYards { polys: Vec::new(), boxes: Vec::new() };
        let ys = self.yards.get(turn).unwrap_or(&empty);
        // Everything this candidate puts down lies in `near`: a reservation clear of it refuses nothing.
        let near = match self.hulls.get(turn) {
            Some(h) => B { l: h.l + x - REACH_SLACK, t: h.t + y - REACH_SLACK, r: h.r + x + REACH_SLACK, b: h.b + y + REACH_SLACK },
            None => B { l: f64::NEG_INFINITY, t: f64::NEG_INFINITY, r: f64::INFINITY, b: f64::INFINITY },
        };
        // the live reservations whose boxes reach `near`, in `live` order
        let mut found = std::mem::take(&mut self.found);
        found.clear();
        match &self.grid {
            Some(g) => {
                self.tick = self.tick.wrapping_add(1);
                if self.tick == 0 {
                    self.stamp.iter_mut().for_each(|t| *t = 0);
                    self.tick = 1;
                }
                for cy in bin_of(near.t, g.y0, g.h, g.n)..=bin_of(near.b, g.y0, g.h, g.n) {
                    for cx in bin_of(near.l, g.x0, g.w, g.n)..=bin_of(near.r, g.x0, g.w, g.n) {
                        for &k in &g.cells[cy * g.n + cx] {
                            if self.stamp[k as usize] != self.tick {
                                self.stamp[k as usize] = self.tick;
                                found.push(k);
                            }
                        }
                    }
                }
                found.sort_unstable();
            }
            None => found.extend(0..self.live.len() as u32),
        }
        let out = self.first_hit(&found, &near, ys, body, parts, x, y);
        self.found = found;
        out
    }

    fn first_hit(&mut self, found: &[u32], near: &B, ys: &TurnYards, body: &B, parts: &[B], x: f64, y: f64) -> Option<(usize, usize)> {
        for &k in found {
            let (pos, ri) = self.live[k as usize];
            let r = &self.res[ri];
            if !r.bbox.overlaps(near) {
                continue;
            }
            if r.courtyard {
                let mut yard_hit = |k: usize| -> bool {
                    match (ys.polys.get(k), ys.boxes.get(k)) {
                        (Some(Some(poly)), Some(Some(bb))) => {
                            if !r.bbox.overlaps(&moved(bb, x, y)) {
                                return false;
                            }
                            // a rastered polygon with nothing of it near the courtyard's box shares no interior with it
                            if r.poly.len() >= 24 && r.raster.as_ref().is_some_and(|ra| ra.clear_of(&moved(bb, x, y), REACH_SLACK)) {
                                return false;
                            }
                            self.scratch.clear();
                            self.scratch.extend(poly.iter().map(|p| (p.0 + x, p.1 + y)));
                            r.polygon_overlaps(&self.scratch)
                        }
                        _ => false,
                    }
                };
                if parts.is_empty() {
                    if yard_hit(0) {
                        return Some((ri, 0));
                    }
                    continue;
                }
                let n = ys.polys.len();
                let found = match self.judged {
                    Some(j) => j[pos].iter().copied().find(|&k| k < parts.len() && if k < n { yard_hit(k) } else { r.overlaps(&shifted(&parts[k], x, y)) }),
                    None => (0..parts.len()).find(|&k| if k < n { yard_hit(k) } else { r.overlaps(&shifted(&parts[k], x, y)) }),
                };
                if let Some(k) = found {
                    return Some((ri, k + 1));
                }
                continue;
            }
            if !r.overlaps(body) {
                continue;
            }
            if parts.is_empty() {
                return Some((ri, 0));
            }
            let found = match self.judged {
                Some(j) => j[pos].iter().copied().find(|&k| k < parts.len() && r.overlaps(&shifted(&parts[k], x, y))),
                None => (0..parts.len()).find(|&k| r.overlaps(&shifted(&parts[k], x, y))),
            };
            if let Some(k) = found {
                return Some((ri, k + 1));
            }
        }
        None
    }
}

/// A box shifted by (x, y) and rounded, as a candidate's boxes are.
#[inline]
pub fn shifted(b: &B, x: f64, y: f64) -> B {
    B { l: clean9(b.l + x), t: clean9(b.t + y), r: clean9(b.r + x), b: clean9(b.b + y) }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Raster;

    /// A small deterministic generator, so a failure repeats.
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
    }

    fn blob(g: &mut Rng, cx: f64, cy: f64, r: f64, n: usize) -> Vec<Point> {
        (0..n)
            .map(|i| {
                let a = std::f64::consts::TAU * i as f64 / n as f64;
                let rr = r * g.between(0.6, 1.0);
                (cx + rr * a.cos(), cy + rr * a.sin())
            })
            .collect()
    }

    fn rect(g: &mut Rng, cx: f64, cy: f64, w: f64, h: f64) -> Vec<Point> {
        let _ = g;
        vec![(cx - w, cy - h), (cx + w, cy - h), (cx + w, cy + h), (cx - w, cy + h)]
    }

    fn reservation(g: &mut Rng, courtyard: bool) -> Reservation {
        let (cx, cy) = (g.between(0.0, 60.0), g.between(0.0, 40.0));
        let kind = g.below(3);
        let (a, b) = (g.between(0.5, 6.0), g.between(0.5, 6.0));
        let (n_small, n_big) = (5 + g.below(12), 24 + g.below(30));
        let poly = match kind {
            0 => rect(g, cx, cy, a, b),
            1 => blob(g, cx, cy, a + 1.0, n_small),
            _ => blob(g, cx, cy, b + 2.0, n_big),
        };
        let bbox = B::of_points(&poly);
        let raster = if poly.len() >= 24 { Some(honest_raster(&poly)) } else { None };
        let _ = bbox;
        Reservation::new(poly, raster, courtyard)
    }

    /// `geometry.PolyRaster`'s cells: crossed (2) where an edge's box meets the cell, else inside (1) or outside (0)
    /// by the cell's first corner.
    fn honest_raster(poly: &[Point]) -> Raster {
        let bb = B::of_points(poly);
        let (w, h) = ((bb.r - bb.l).max(1e-6), (bb.b - bb.t).max(1e-6));
        let c = 0.25f64.max((w * h / 40000.0).sqrt());
        let (nx, ny) = (1.max((w / c).ceil() as i64), 1.max((h / c).ceil() as i64));
        let n = poly.len();
        let mut state = Vec::new();
        for j in 0..ny {
            let mut row = Vec::new();
            for i in 0..nx {
                let (a0, b0) = (bb.l + i as f64 * c, bb.t + j as f64 * c);
                let (a1, b1) = (a0 + c, b0 + c);
                let crossed = (0..n).any(|k| {
                    let (p, q) = (poly[k], poly[(k + 1) % n]);
                    p.0.min(q.0) <= a1 && p.0.max(q.0) >= a0 && p.1.min(q.1) <= b1 && p.1.max(q.1) >= b0
                });
                row.push(if crossed { 2 } else if crate::geometry::point_in_polygon((a0, b0), poly) { 1 } else { 0 });
            }
            state.push(row);
        }
        Raster { x0: bb.l, y0: bb.t, cell: c, nx, ny, state }
    }

    fn cell_part(g: &mut Rng) -> (B, Option<Vec<Point>>) {
        let (cx, cy) = (g.between(-4.0, 4.0), g.between(-4.0, 4.0));
        let (w, h) = (g.between(0.3, 2.5), g.between(0.3, 2.5));
        let b = B { l: cx - w, t: cy - h, r: cx + w, b: cy + h };
        let yard = if g.below(4) == 0 { None } else { Some(b.polygon()) };
        (b, yard)
    }

    #[test]
    fn the_pass_gives_the_references_answer_on_random_boards() {
        let mut g = Rng(0x9E3779B97F4A7C15);
        let mut hits = 0usize;
        let mut asked = 0usize;
        for round in 0..300 {
            let n = 1 + g.below(40);
            let mut res: Vec<Reservation> = Vec::new();
            for _ in 0..n { let c = g.below(3) == 0; res.push(reservation(&mut g, c)); }
            let mut list: Vec<usize> = { let mut l = Vec::new(); for i in 0..n { if g.below(5) != 0 { l.push(i); } } l };
            // a different order from the board's, as `reservations` may be
            if round % 3 == 0 { list.reverse(); }
            let parts_n = if round % 4 == 0 { 0 } else { 1 + g.below(6) };
            let mut parts: Vec<(B, Option<Vec<Point>>)> = Vec::new();
            for _ in 0..parts_n { parts.push(cell_part(&mut g)); }
            let yards_one: Vec<Option<Vec<Point>>> = if parts_n == 0 || round % 5 == 0 {
                vec![Some(rect(&mut g, 0.0, 0.0, 1.0, 1.5))]
            } else {
                let mut v: Vec<Option<Vec<Point>>> = parts.iter().map(|p| p.1.clone()).collect();
                if round % 7 == 0 { v.truncate(parts_n / 2); }    // a cell's own copper past its members: no yard
                v
            };
            let judged: Option<Vec<Vec<usize>>> = if parts_n > 0 && round % 2 == 0 {
                let mut j = Vec::new();
                for _ in &list { let mut one = Vec::new(); for k in 0..parts_n { if g.below(4) != 0 { one.push(k); } } j.push(one); }
                Some(j)
            } else {
                None
            };
            let body_o = if parts_n == 0 { B { l: -1.0, t: -1.5, r: 1.0, b: 1.5 } } else {
                let mut b = parts[0].0;
                for p in &parts[1..] { b.l = b.l.min(p.0.l); b.t = b.t.min(p.0.t); b.r = b.r.max(p.0.r); b.b = b.b.max(p.0.b); }
                b
            };
            let yards = vec![yards_one];
            let ty: Vec<TurnYards> = yards.iter().map(|y| TurnYards::new(y)).collect();
            // the points: a region of the board; reach holds every candidate's boxes
            let (px0, py0) = (g.between(0.0, 50.0), g.between(0.0, 30.0));
            let (pw, ph) = (g.between(0.0, 15.0), g.between(0.0, 15.0));
            let mut reach = body_o;
            for p in &parts { reach.l = reach.l.min(p.0.l); reach.t = reach.t.min(p.0.t); reach.r = reach.r.max(p.0.r); reach.b = reach.b.max(p.0.b); }
            for yy in yards[0].iter().flatten() { let yb = B::of_points(yy); reach.l = reach.l.min(yb.l); reach.t = reach.t.min(yb.t); reach.r = reach.r.max(yb.r); reach.b = reach.b.max(yb.b); }
            let reach = B { l: px0 + reach.l, t: py0 + reach.t, r: px0 + pw + reach.r, b: py0 + ph + reach.b };
            let mut hull0 = body_o;
            for p in &parts { hull0 = hull(&hull0, &p.0); }
            for yy in yards[0].iter().flatten() { hull0 = hull(&hull0, &B::of_points(yy)); }
            let hulls = [hull0];
            let mut pass = ReservationPass::new(&res, &list, judged.as_ref(), &ty, &hulls, Some(reach));
            for _ in 0..60 {
                let (x, y) = (px0 + g.between(0.0, pw), py0 + g.between(0.0, ph));
                let sh = |b: &B| B { l: crate::exact::clean9(b.l + x), t: crate::exact::clean9(b.t + y), r: crate::exact::clean9(b.r + x), b: crate::exact::clean9(b.b + y) };
                let members: Vec<B> = parts.iter().map(|p| sh(&p.0)).collect();
                let body = sh(&body_o);
                let want = reference(&res, &list, judged.as_ref(), &yards, 0, &body, &members, x, y);
                let unshifted: Vec<B> = parts.iter().map(|p| p.0).collect();
                let got = pass.hit(0, &body, &unshifted, x, y);
                assert_eq!(got, want, "round {round} at ({x}, {y})");
                asked += 1;
                hits += want.is_some() as usize;
            }
        }
        assert!(hits > 200 && hits < asked - 200, "the generator should refuse some candidates and not others: {hits} of {asked}");
    }
}
