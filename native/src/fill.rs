//! `NativeFill`: the Rust port of `checks.py`'s `_Fill` - rasterising a
//! zone fill polygon and, per copper item asked about, the copper's own
//! polygons, both on the fill's grid; the exact two-pass Euclidean
//! distance transform of each (Felzenszwalb and Huttenlocher); `touching`
//! and the breadth-first `reach` over the fill's cells. The neck point and
//! the "one step or less" sentence stay in Python (`checks.py` `_Fill.width`),
//! which calls `touching`/`reach` here the same number of times, in the
//! same order, as the pure-Python version - see
//! docs/superpowers/specs/2026-09-30-performance-zone-width-give-way-sweep-design.md
//! section 1.

use std::collections::{HashMap, HashSet, VecDeque};

pub type Point = (f64, f64);
pub type Bounds = (f64, f64, f64, f64); // left, top, right, bottom

fn bounds_of(polys: &[Vec<Point>]) -> Bounds {
    let mut x0 = f64::INFINITY;
    let mut y0 = f64::INFINITY;
    let mut x1 = f64::NEG_INFINITY;
    let mut y1 = f64::NEG_INFINITY;
    for poly in polys {
        for &(x, y) in poly {
            if x < x0 {
                x0 = x;
            }
            if x > x1 {
                x1 = x;
            }
            if y < y0 {
                y0 = y;
            }
            if y > y1 {
                y1 = y;
            }
        }
    }
    (x0, y0, x1, y1)
}

/// `checks._raster`: 1 for each cell of the grid whose centre lies inside
/// any of `polys` (even-odd within each). A slit to a hole - two
/// coincident edges - is crossed twice at one x, so it leaves no gap.
pub fn raster(polys: &[Vec<Point>], x0: f64, y0: f64, nx: usize, ny: usize, s: f64) -> Vec<bool> {
    let mut inside = vec![false; nx * ny];
    for poly in polys {
        let mut rows: HashMap<i64, Vec<f64>> = HashMap::new();
        let n = poly.len();
        for k in 0..n {
            let (ax, ay) = poly[k];
            let (bx, by) = poly[(k + 1) % n];
            if ay == by {
                continue;
            }
            let (lo, hi) = if ay < by { (ay, by) } else { (by, ay) };
            let r_lo = (((lo - y0) / s - 0.5).ceil()).max(0.0) as i64;
            let r_hi_f = ((hi - y0) / s - 0.5).ceil();
            let r_hi = (r_hi_f as i64).min(ny as i64);
            let mut r = r_lo;
            while r < r_hi {
                let y = y0 + (r as f64 + 0.5) * s;
                let x = ax + (y - ay) * (bx - ax) / (by - ay);
                rows.entry(r).or_default().push(x);
                r += 1;
            }
        }
        for (r, mut xs) in rows {
            xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
            let base = (r as usize) * nx;
            let mut it = xs.chunks_exact(2);
            for pair in &mut it {
                let (a, b) = (pair[0], pair[1]);
                let c0 = (((a - x0) / s - 0.5).ceil()).max(0.0) as i64;
                let c1_f = ((b - x0) / s - 0.5).ceil();
                let c1 = (c1_f as i64).clamp(0, nx as i64);
                if c1 > c0 {
                    for c in (c0 as usize)..(c1 as usize) {
                        inside[base + c] = true;
                    }
                }
            }
        }
    }
    inside
}

/// `checks._edt_line`: the squared distance transform of one line of
/// samples (Felzenszwalb and Huttenlocher's lower envelope of parabolas):
/// d[q] = min over p of (q - p)^2 + f[p].
pub fn edt_line(f: &[f64]) -> Vec<f64> {
    let n = f.len();
    let finite: Vec<i64> = (0..n as i64).filter(|&q| f[q as usize].is_finite()).collect();
    if finite.is_empty() {
        return vec![f64::INFINITY; n];
    }
    let mut v: Vec<i64> = vec![finite[0]];
    let mut z: Vec<f64> = vec![f64::NEG_INFINITY, f64::INFINITY];
    for &q in &finite[1..] {
        let mut cut;
        loop {
            let p = *v.last().unwrap();
            cut = ((f[q as usize] + (q * q) as f64) - (f[p as usize] + (p * p) as f64)) / (2.0 * (q - p) as f64);
            if cut > z[z.len() - 2] {
                break;
            }
            v.pop();
            z.pop();
        }
        v.push(q);
        let last = z.len() - 1;
        z[last] = cut;
        z.push(f64::INFINITY);
    }
    let mut d = vec![0.0; n];
    let mut k = 0usize;
    for q in 0..n as i64 {
        while z[k + 1] < q as f64 {
            k += 1;
        }
        let p = v[k];
        let dq = (q - p) as f64;
        d[q as usize] = dq * dq + f[p as usize];
    }
    d
}

/// `checks._distance_transform`: the squared-distance-in-cells transform
/// of a 0/1 raster (`inside` true = in), column-wise then row-wise. Not
/// inverted here - the caller (`Fill::touching`) inverts the copper
/// raster before calling this, since the copper cells must be the
/// transform's distance-0 seeds, the opposite of what `Fill::new` wants
/// for the fill's own `sq` (seeded from OUTSIDE the fill).
pub fn distance_transform(inside: &[bool], nx: usize, ny: usize) -> Vec<f64> {
    let mut cols = vec![0.0; nx * ny];
    for q in 0..nx {
        let col: Vec<f64> = (0..ny).map(|r| if inside[r * nx + q] { f64::INFINITY } else { 0.0 }).collect();
        let d = edt_line(&col);
        for r in 0..ny {
            cols[r * nx + q] = d[r];
        }
    }
    let mut sq = vec![0.0; nx * ny];
    for r in 0..ny {
        let d = edt_line(&cols[r * nx..(r + 1) * nx]);
        sq[r * nx..(r + 1) * nx].copy_from_slice(&d);
    }
    sq
}

/// One zone fill polygon rasterised at `s`, plus, per copper item asked
/// about (`touching`), its own raster and distance transform on the same
/// grid - see the module doc.
pub struct Fill {
    pub x0: f64,
    pub y0: f64,
    pub s: f64,
    pub nx: usize,
    pub ny: usize,
    pub inside: Vec<bool>,
    pub sq: Vec<f64>,
    pub deep: Vec<usize>,   // the fill's cells, deepest first
    pub depths: Vec<f64>,   // -sq[c], parallel to `deep`
    pub levels: Vec<f64>,   // sorted distinct sq values among `deep`
    copper: HashMap<usize, (Vec<f64>, Bounds)>, // polys_id -> (copper_sq at this fill's cells, copper's own bounds)
}

impl Fill {
    pub fn new(poly: &[Point], step: f64) -> Self {
        let (bx0, by0, bx1, by1) = bounds_of(&[poly.to_vec()]);
        let width = bx1 - bx0;
        let height = by1 - by0;
        let x0 = bx0 - step;
        let y0 = by0 - step;
        let nx = (width / step).ceil() as usize + 2;
        let ny = (height / step).ceil() as usize + 2;
        let inside = raster(&[poly.to_vec()], x0, y0, nx, ny, step);
        let sq = distance_transform(&inside, nx, ny);
        let mut deep: Vec<usize> = (0..nx * ny).filter(|&c| inside[c]).collect();
        deep.sort_by(|&a, &b| sq[b].partial_cmp(&sq[a]).unwrap()); // deepest (highest sq) first
        let depths: Vec<f64> = deep.iter().map(|&c| -sq[c]).collect();
        let mut levels: Vec<f64> = deep.iter().map(|&c| sq[c]).collect();
        levels.sort_by(|a, b| a.partial_cmp(b).unwrap());
        levels.dedup();
        Fill { x0, y0, s: step, nx, ny, inside, sq, deep, depths, levels, copper: HashMap::new() }
    }

    pub fn centre(&self, c: usize) -> Point {
        let (r, q) = (c / self.nx, c % self.nx);
        (self.x0 + (q as f64 + 0.5) * self.s, self.y0 + (r as f64 + 0.5) * self.s)
    }

    pub fn radius(&self, tau: f64) -> f64 {
        self.s * (tau.sqrt() - 0.5)
    }

    /// `bisect.bisect_right(self.depths, -tau)`: `depths` is sorted
    /// ascending (least negative - i.e. shallowest - last), so this is the
    /// count of cells at least `tau` deep, the prefix of `deep`.
    fn deep_count(&self, tau: f64) -> usize {
        self.depths.partition_point(|&d| d <= -tau)
    }

    /// `checks._Fill.touching`: the fill's cells at least `tau` from its
    /// edge whose disc of that radius reaches `polys`, within half a step.
    /// `polys` is given (and its raster/transform built and cached under
    /// `polys_id`) only on the first call for that id; later calls pass
    /// `None` and reuse the cached transform - `checks.py`'s own
    /// `_Fill._copper_distance` caches the same way, by `id(polys)`.
    pub fn touching(&mut self, polys_id: usize, polys: Option<&[Vec<Point>]>, tau: f64) -> Vec<usize> {
        if !self.copper.contains_key(&polys_id) {
            let polys = polys.expect("Fill::touching: polys_id not cached yet and no polys given to build it");
            self.copper.insert(polys_id, self.build_copper_distance(polys));
        }
        let (copper_sq, cbox) = self.copper.get(&polys_id).unwrap();
        let s = self.s;
        let far = self.radius(tau) + s / 2.0;
        let nx_i = self.nx as i64;
        let ny_i = self.ny as i64;
        let q0 = (((cbox.0 - far - self.x0) / s).floor().max(0.0)) as i64;
        let r0 = (((cbox.1 - far - self.y0) / s).floor().max(0.0)) as i64;
        let q1 = ((((cbox.2 + far - self.x0) / s).ceil()) as i64 + 1).min(nx_i).max(0);
        let r1 = ((((cbox.3 + far - self.y0) / s).ceil()) as i64 + 1).min(ny_i).max(0);
        let (nx, ny) = (self.nx, self.ny);
        let window = if q1 > q0 && r1 > r0 { ((q1 - q0) * (r1 - r0)) as usize } else { 0 };
        let deep_n = self.deep_count(tau);
        let cells: Vec<usize> = if deep_n < window {
            self.deep[..deep_n]
                .iter()
                .copied()
                .filter(|&c| {
                    let q = (c % nx) as i64;
                    let r = (c / nx) as i64;
                    q0 <= q && q < q1 && r0 <= r && r < r1
                })
                .collect()
        } else {
            let (q0, q1, r0, r1) = (q0.max(0) as usize, q1.max(0) as usize, r0.max(0) as usize, r1.max(0) as usize);
            let mut v = Vec::new();
            if q1 > q0 && r1 > r0 {
                for r in r0..r1.min(ny) {
                    for q in q0..q1.min(nx) {
                        let c = r * nx + q;
                        if self.inside[c] && self.sq[c] >= tau {
                            v.push(c);
                        }
                    }
                }
            }
            v
        };
        let limit = (far / s).powi(2);
        cells.into_iter().filter(|&c| copper_sq[c] <= limit + 1e-9).collect()
    }

    /// The squared-distance-in-cells transform of `polys`, read back at
    /// this fill's own cells, and `polys`'s own bounds - see
    /// `checks._Fill._copper_distance`'s doc for why the grid is grown,
    /// cell-aligned, past the fill's own wherever `polys` reaches further.
    fn build_copper_distance(&self, polys: &[Vec<Point>]) -> (Vec<f64>, Bounds) {
        let (s, x0, y0, nx, ny) = (self.s, self.x0, self.y0, self.nx, self.ny);
        let cbox = bounds_of(polys);
        let dq = (((x0 - (cbox.0 - s)) / s - 1e-9).ceil().max(0.0)) as usize;
        let dr = (((y0 - (cbox.1 - s)) / s - 1e-9).ceil().max(0.0)) as usize;
        let gx0 = x0 - dq as f64 * s;
        let gy0 = y0 - dr as f64 * s;
        let extra_c = ((((cbox.2 + s) - (x0 + nx as f64 * s)) / s - 1e-9).ceil().max(0.0)) as usize;
        let extra_r = ((((cbox.3 + s) - (y0 + ny as f64 * s)) / s - 1e-9).ceil().max(0.0)) as usize;
        let gnx = nx + dq + extra_c;
        let gny = ny + dr + extra_r;
        let sq = if dq == 0 && dr == 0 && extra_c == 0 && extra_r == 0 {
            let inside = raster(polys, x0, y0, nx, ny, s);
            let inverted: Vec<bool> = inside.iter().map(|&b| !b).collect();
            distance_transform(&inverted, nx, ny)
        } else {
            let inside = raster(polys, gx0, gy0, gnx, gny, s);
            let inverted: Vec<bool> = inside.iter().map(|&b| !b).collect();
            let grid = distance_transform(&inverted, gnx, gny);
            let mut out = vec![0.0; nx * ny];
            for r in 0..ny {
                for q in 0..nx {
                    out[r * nx + q] = grid[(r + dr) * gnx + (q + dq)];
                }
            }
            out
        };
        (sq, cbox)
    }

    /// `checks._Fill._reach`: a path of fill cells from `start` to `goal`,
    /// 8-connected, every cell on it in either set or at least `tau`
    /// (squared cells) from the fill's edge - breadth first, so it stops
    /// as soon as it arrives.
    /// (the goal cell reached, or None; the parent map; the cells in the
    /// order `parent` gained them - `start`'s own order, then discovery
    /// order). The order matters: `checks.py` `width()`'s "no path at
    /// all" branch does `min(seen, key=...)`, which on a tie between
    /// equally-near cells picks the FIRST one `seen` iterates - a Python
    /// dict's insertion order, exactly what `Fill::new`'s caller (the
    /// `NativeReach` pyclass, lib.rs) must reproduce rather than
    /// answering from a hash-ordered map.
    pub fn reach(&self, start: &[usize], goal: &[usize], tau: f64) -> (Option<usize>, HashMap<usize, Option<usize>>, Vec<usize>) {
        let goal_set: HashSet<usize> = goal.iter().copied().collect();
        let mut parent: HashMap<usize, Option<usize>> = HashMap::new();
        let mut order: Vec<usize> = Vec::new();
        for &c in start {
            if parent.insert(c, None).is_none() {
                order.push(c);
            }
        }
        let mut todo: VecDeque<usize> = start.iter().copied().collect();
        let (nx, ny) = (self.nx, self.ny);
        while let Some(c) = todo.pop_front() {
            if goal_set.contains(&c) {
                return (Some(c), parent, order);
            }
            let (r, q) = (c / nx, c % nx);
            let r_lo = r.saturating_sub(1);
            let r_hi = (r + 1).min(ny.saturating_sub(1));
            let q_lo = q.saturating_sub(1);
            let q_hi = (q + 1).min(nx.saturating_sub(1));
            for rr in r_lo..=r_hi {
                for qq in q_lo..=q_hi {
                    let n = rr * nx + qq;
                    if parent.contains_key(&n) || !self.inside[n] {
                        continue;
                    }
                    if self.sq[n] >= tau || goal_set.contains(&n) {
                        parent.insert(n, Some(c));
                        order.push(n);
                        todo.push_back(n);
                    }
                }
            }
        }
        (None, parent, order)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(cx: f64, cy: f64, w: f64, h: f64) -> Vec<Point> {
        vec![(cx - w / 2.0, cy - h / 2.0), (cx + w / 2.0, cy - h / 2.0), (cx + w / 2.0, cy + h / 2.0), (cx - w / 2.0, cy + h / 2.0)]
    }

    #[test]
    fn raster_marks_cell_centres_inside_a_rectangle() {
        // a 2x2 mm square at the origin, step 1: cells at (-1..0, -1..0),
        // (0..1, -1..0), (-1..0, 0..1), (0..1, 0..1) are inside (centres
        // at +/-0.5), the ring round them is not.
        let poly = rect(0.0, 0.0, 2.0, 2.0);
        let nx = 4;
        let ny = 4;
        let x0 = -2.0;
        let y0 = -2.0;
        let inside = raster(&[poly], x0, y0, nx, ny, 1.0);
        let count = inside.iter().filter(|&&b| b).count();
        assert_eq!(count, 4);
        // centre cell (q=2, r=2 -> centre (0.5, 0.5)) is inside
        assert!(inside[2 * nx + 2]);
        // corner cell (q=0, r=0 -> centre (-1.5,-1.5)) is not
        assert!(!inside[0]);
    }

    #[test]
    fn distance_transform_peaks_at_the_centre_of_a_filled_square() {
        let poly = rect(0.0, 0.0, 4.0, 4.0);
        let x0 = -3.0;
        let y0 = -3.0;
        let nx = 6;
        let ny = 6;
        let inside = raster(&[poly], x0, y0, nx, ny, 1.0);
        let sq = distance_transform(&inside, nx, ny);
        let centre_c = 3 * nx + 3; // near the middle
        let corner_inside_c = nx + 1;
        assert!(sq[centre_c] >= sq[corner_inside_c]);
    }

    #[test]
    fn fill_new_finds_the_deepest_cell_at_the_middle() {
        // A square, not a wide rectangle: a rectangle's deepest cells form
        // a ridge along its centre line (many tied-deepest cells, broken
        // by cell order, not position) - a square's single centre cell is
        // the only one at the maximum, an unambiguous check.
        let poly = rect(0.0, 0.0, 4.0, 4.0);
        let f = Fill::new(&poly, 0.5);
        let deepest = f.deep[0];
        let (cx, cy) = f.centre(deepest);
        assert!(cx.abs() < 0.5, "deepest cell near the middle in x: {cx}");
        assert!(cy.abs() < 0.5, "deepest cell near the middle in y: {cy}");
    }

    #[test]
    fn touching_finds_copper_directly_overlapping_the_fill() {
        let lane = rect(0.0, 0.0, 10.0, 1.0);
        let mut f = Fill::new(&lane, 0.25);
        let copper = vec![rect(-5.0, 0.0, 1.0, 1.0)]; // at the fill's own left edge
        let cells = f.touching(1, Some(&copper), 1.0);
        assert!(!cells.is_empty());
        for &c in &cells {
            let (cx, _) = f.centre(c);
            assert!(cx < -3.0, "touching cell at x={cx} should be near the left edge");
        }
    }

    #[test]
    fn touching_does_not_find_copper_far_away() {
        let lane = rect(0.0, 0.0, 20.0, 1.0);
        let mut f = Fill::new(&lane, 0.25);
        let far_copper = vec![rect(9.5, 0.0, 1.0, 1.0)]; // near the right edge
        let cells = f.touching(1, Some(&far_copper), 1.0); // shallow tau: far is small
        for &c in &cells {
            let (cx, _) = f.centre(c);
            assert!(cx > 5.0, "a shallow-tau touching cell should be near the copper, got x={cx}");
        }
    }

    #[test]
    fn touching_reads_the_real_distance_not_zero_everywhere() {
        // Regression: the copper raster must be inverted before the
        // transform (copper cells are the seeds), or every non-copper
        // cell reads as distance 0 from any copper however far away.
        let lane = rect(10.0, 0.0, 20.0, 1.2); // x 0..20
        let mut f = Fill::new(&lane, 0.05);
        let far_right = vec![rect(19.5, 0.0, 1.0, 1.0)];
        f.touching(1, Some(&far_right), 1.0);
        let (copper_sq, _) = &f.copper[&1];
        let nearest_left = (0..f.nx * f.ny)
            .filter(|&c| f.inside[c])
            .min_by(|&a, &b| f.centre(a).0.partial_cmp(&f.centre(b).0).unwrap())
            .unwrap();
        assert!(copper_sq[nearest_left] > 100.0, "a cell far from copper must not read as distance ~0");
    }

    #[test]
    fn reach_finds_a_path_across_a_uniform_grid() {
        let poly = rect(0.0, 0.0, 6.0, 6.0);
        let f = Fill::new(&poly, 1.0);
        let start: Vec<usize> = (0..f.nx * f.ny).filter(|&c| f.inside[c]).take(1).collect();
        let goal: Vec<usize> = (0..f.nx * f.ny).filter(|&c| f.inside[c]).rev().take(1).collect();
        let (hit, parent, order) = f.reach(&start, &goal, 0.0);
        assert!(hit.is_some());
        assert!(parent.contains_key(&hit.unwrap()));
        assert!(order.contains(&hit.unwrap()));
        assert_eq!(order.len(), parent.len());
    }

    #[test]
    fn reach_returns_none_when_goal_is_unreachable() {
        let poly = rect(0.0, 0.0, 4.0, 4.0);
        let f = Fill::new(&poly, 1.0);
        let start: Vec<usize> = vec![f.deep[0]];
        let goal: Vec<usize> = vec![99999]; // not a real cell, never reached
        let (hit, _, _) = f.reach(&start, &goal, 0.0);
        assert!(hit.is_none());
    }

    #[test]
    fn reach_order_starts_with_the_start_cells_then_discovery_order() {
        let poly = rect(0.0, 0.0, 6.0, 6.0);
        let f = Fill::new(&poly, 1.0);
        let start: Vec<usize> = (0..f.nx * f.ny).filter(|&c| f.inside[c]).take(2).collect();
        let (_, parent, order) = f.reach(&start, &[], 0.0);
        assert_eq!(&order[..2], &start[..]);
        assert_eq!(order.len(), parent.len());
        // every key appears exactly once in `order`
        let mut sorted_order = order.clone();
        sorted_order.sort_unstable();
        sorted_order.dedup();
        assert_eq!(sorted_order.len(), order.len());
    }
}
