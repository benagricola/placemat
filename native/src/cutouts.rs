//! `cutouts.loop_gap`: the shortest distance between two closed loops, 0.0 when they touch or cross, ported
//! expression for expression (`point_segment`, `_side` and `crosses` as `placemat/cutouts.py` writes them) so
//! the same bits come out.

use crate::exact::hypot;

type Point = (f64, f64);

/// `cutouts.point_segment`: the distance from (px, py) to the segment (x1, y1)-(x2, y2).
fn point_segment(px: f64, py: f64, x1: f64, y1: f64, x2: f64, y2: f64) -> f64 {
    let (dx, dy) = (x2 - x1, y2 - y1);
    let n = dx * dx + dy * dy;
    let t = if n < 1e-18 {
        0.0
    } else {
        let q = ((px - x1) * dx + (py - y1) * dy) / n;
        let m = if q < 1.0 { q } else { 1.0 };      // Python's min(1.0, q)
        if m > 0.0 { m } else { 0.0 }               // and max(0.0, m)
    };
    hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

fn side(ax: f64, ay: f64, bx: f64, by: f64, px: f64, py: f64) -> f64 {
    (bx - ax) * (py - ay) - (by - ay) * (px - ax)
}

/// `cutouts.crosses`: whether the segments (a, b) and (c, d) cross properly.
#[allow(clippy::too_many_arguments)]
fn crosses(ax: f64, ay: f64, bx: f64, by: f64, cx: f64, cy: f64, dx: f64, dy: f64) -> bool {
    let (d1, d2) = (side(cx, cy, dx, dy, ax, ay), side(cx, cy, dx, dy, bx, by));
    let (d3, d4) = (side(ax, ay, bx, by, cx, cy), side(ax, ay, bx, by, dx, dy));
    ((d1 > 0.0) != (d2 > 0.0)) && ((d3 > 0.0) != (d4 > 0.0))
}

/// `cutouts.loop_gap(a, b)`.
pub fn loop_gap(a: &[Point], b: &[Point]) -> f64 {
    let mut best = f64::INFINITY;
    let (n, m) = (a.len(), b.len());
    for i in 0..n {
        let ((ax, ay), (bx, by)) = (a[i], a[(i + 1) % n]);
        for j in 0..m {
            let ((cx, cy), (dx, dy)) = (b[j], b[(j + 1) % m]);
            if crosses(ax, ay, bx, by, cx, cy, dx, dy) {
                return 0.0;
            }
            // Python's min(best, p, q): the first of equals, the same value either way
            let p = point_segment(ax, ay, cx, cy, dx, dy);
            if p < best {
                best = p;
            }
            let q = point_segment(cx, cy, ax, ay, bx, by);
            if q < best {
                best = q;
            }
        }
    }
    if best == f64::INFINITY { 0.0 } else { best }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn two_squares_a_gap_apart() {
        let a = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)];
        let b = [(3.0, 0.0), (4.0, 0.0), (4.0, 1.0), (3.0, 1.0)];
        assert_eq!(loop_gap(&a, &b), 2.0);
        let c = [(0.5, 0.5), (2.0, 0.5), (2.0, 2.0), (0.5, 2.0)];
        assert_eq!(loop_gap(&a, &c), 0.0);          // they cross
        assert_eq!(loop_gap(&[], &b), 0.0);
    }
}
