//! Exact surface escape search: the Python rectangular-cell walk followed by
//! every octilinear lattice rooted on the pad/own-copper anchors. This is a
//! geometry kernel, not a replacement for escape eligibility or validity.
use crate::geometry::{point_in_polygon, point_segment_distance, segments_intersect};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};

type Point = (f64, f64);
type Bounds = (f64, f64, f64, f64);
/// polygon, exact box, layer bits, track-end anchors, clearance adjustment
type Shape = (Vec<Point>, Bounds, u32, Vec<Point>, f64);
type Lane = (Vec<(Point, Point)>, u32, Bounds);
type Spot = (Point, f64, Bounds);
type Foe = (Shape, f64, f64, bool);
type Path = (
    Vec<Shape>,
    Vec<Shape>,
    u32,
    Bounds,
    f64,
    f64,
    Option<Point>,
    Vec<Shape>,
    f64,
    f64,
    bool,
);

fn box_gap(a: Bounds, b: Bounds) -> f64 {
    crate::exact::hypot(
        (a.0 - b.2).max(b.0 - a.2).max(0.0),
        (a.1 - b.3).max(b.1 - a.3).max(0.0),
    )
}

fn point_distance(p: Point, poly: &[Point]) -> f64 {
    if point_in_polygon(p, poly) {
        return 0.0;
    }
    (0..poly.len())
        .map(|i| point_segment_distance(p, poly[i], poly[(i + 1) % poly.len()]))
        .fold(f64::INFINITY, f64::min)
}

fn segment_distance(a: Point, b: Point, poly: &[Point]) -> f64 {
    if point_in_polygon(a, poly) {
        return 0.0;
    }
    let mut best = f64::INFINITY;
    for i in 0..poly.len() {
        let (p, q) = (poly[i], poly[(i + 1) % poly.len()]);
        if segments_intersect(a, b, p, q) {
            return 0.0;
        }
        best = best
            .min(point_segment_distance(p, a, b))
            .min(point_segment_distance(a, p, q))
            .min(point_segment_distance(b, p, q));
    }
    best
}

/// Classification only: eligibility, current nearest-target identity and
/// original intent are supplied by the snapshot builder. 0/1/2/3 are
/// surface/via/away/walled; 4 means a quiet pad has a way out and no finding.
/// The classifier requires via_exit=false, just as Python `_verdict`: a via
/// is judged by its spots after the toward surface search, never counted as
/// a free surface route. The standalone path kernel supports both modes.
#[pyfunction]
pub fn surface_judge(
    py: Python<'_>,
    lanes: Vec<Lane>,
    spots: Vec<Spot>,
    foes: Vec<Foe>,
    bans: Vec<Shape>,
    aim: Option<Point>,
    centre: Point,
    quiet: bool,
    path: Path,
) -> PyResult<u8> {
    py.check_signals()?;
    validate_search(
        &path.0, &path.1, path.2, path.3, path.4, path.5, aim, &path.7, path.8, path.9,
    )?;
    if !valid_point(centre)
        || aim.is_some_and(|p| !valid_point(p))
        || !foes
            .iter()
            .all(|f| validate_shape(&f.0) && f.1.is_finite() && f.1 >= 0.0 && f.2.is_finite())
        || !bans.iter().all(validate_shape)
        || path.10
        || !lanes.iter().all(|l| {
            valid_bounds(l.2)
                && l.1 != 0
                && !l.0.is_empty()
                && l.0.iter().all(|&(a, b)| {
                    valid_point(a) && valid_point(b) && contains(l.2, a) && contains(l.2, b)
                })
        })
        || !spots.iter().all(|s| {
            valid_bounds(s.2)
                && valid_point(s.0)
                && contains(s.2, s.0)
                && s.1.is_finite()
                && s.1 >= 0.0
        })
    {
        return Err(PyValueError::new_err(
            "invalid surface escape classification snapshot",
        ));
    }
    let open: Vec<_> = lanes
        .iter()
        .filter(|l| {
            !foes.iter().any(|f| {
                (f.3 || f.0.2 & l.1 != 0)
                    && box_gap(f.0.1, l.2) < f.1
                    && l.0
                        .iter()
                        .any(|&(a, b)| segment_distance(a, b, &f.0.0) < f.1)
            })
        })
        .collect();
    let (start, walls, layers, window, track, via, _, path_bans, cell, epsilon, via_exit) = path;
    if !quiet {
        let d = aim
            .ok_or_else(|| PyValueError::new_err("signal surface escape lacks target direction"))?;
        let n = crate::exact::hypot(d.0, d.1);
        if open.iter().any(|l| {
            n < 1e-12 || {
                let end = l.0.last().unwrap().1;
                ((end.0 - centre.0) * d.0 + (end.1 - centre.1) * d.1) / n > cell
            }
        }) {
            return Ok(0);
        }
        let toward = if d.0.abs() + d.1.abs() < 1e-12 {
            None
        } else {
            Some(d)
        };
        if surface_path_out(
            py,
            start.clone(),
            walls.clone(),
            layers,
            window,
            track,
            via,
            toward,
            path_bans.clone(),
            cell,
            epsilon,
            via_exit,
        )? {
            return Ok(0);
        }
    }
    if spots.iter().any(|s| {
        !foes
            .iter()
            .any(|f| box_gap(f.0.1, s.2) < f.2 && point_distance(s.0, &f.0.0) < s.1 + f.2)
            && !bans.iter().any(|b| {
                b.1.0 <= s.2.2
                    && s.2.0 <= b.1.2
                    && b.1.1 <= s.2.3
                    && s.2.1 <= b.1.3
                    && point_distance(s.0, &b.0) < s.1
            })
    }) {
        return Ok(if quiet { 4 } else { 1 });
    }
    if !open.is_empty()
        || surface_path_out(
            py, start, walls, layers, window, track, via, None, path_bans, cell, epsilon, via_exit,
        )?
    {
        return Ok(if quiet { 4 } else { 2 });
    }
    Ok(3)
}

fn near(shapes: &[Shape], p: Point, radius: f64, epsilon: f64) -> bool {
    shapes.iter().any(|(poly, b, _, _, delta)| {
        let r = (radius + delta - epsilon).max(0.0);
        if b.0 - r >= p.0 || p.0 >= b.2 + r || b.1 - r >= p.1 || p.1 >= b.3 + r {
            return false;
        }
        point_in_polygon(p, poly)
            || (0..poly.len())
                .any(|i| point_segment_distance(p, poly[i], poly[(i + 1) % poly.len()]) < r)
    })
}

fn on_start(shapes: &[Shape], p: Point) -> bool {
    shapes.iter().any(|(poly, b, _, _, _)| {
        b.0 <= p.0 && p.0 <= b.2 && b.1 <= p.1 && p.1 <= b.3 && point_in_polygon(p, poly)
    })
}

fn facing(p: Point, centre: Point, toward: Option<Point>) -> bool {
    toward.is_none_or(|d| d.0 * (p.0 - centre.0) + d.1 * (p.1 - centre.1) > 0.0)
}

fn valid_point(p: Point) -> bool {
    p.0.is_finite() && p.1.is_finite() && p.0.abs() <= 1e9 && p.1.abs() <= 1e9
}

fn valid_bounds(b: Bounds) -> bool {
    valid_point((b.0, b.1)) && valid_point((b.2, b.3)) && b.0 <= b.2 && b.1 <= b.3
}

fn contains(b: Bounds, p: Point) -> bool {
    b.0 <= p.0 && p.0 <= b.2 && b.1 <= p.1 && p.1 <= b.3
}

fn validate_shape(s: &Shape) -> bool {
    let (poly, b, _, anchors, delta) = s;
    poly.len() >= 3
        && poly.iter().all(|&p| valid_point(p))
        && anchors.iter().all(|&p| valid_point(p))
        && delta.is_finite()
        && valid_bounds(*b)
        && poly.iter().all(|&p| contains(*b, p))
        && anchors.iter().all(|&p| contains(*b, p))
        && poly.iter().find(|&&p| p != poly[0]).is_some_and(|&q| {
            poly.iter().any(|&p| {
                (q.0 - poly[0].0) * (p.1 - poly[0].1) - (q.1 - poly[0].1) * (p.0 - poly[0].0) != 0.0
            })
        })
}

fn validate_search(
    start: &[Shape],
    foes: &[Shape],
    layers: u32,
    window: Bounds,
    track: f64,
    via: f64,
    toward: Option<Point>,
    bans: &[Shape],
    cell: f64,
    epsilon: f64,
) -> PyResult<(i64, i64)> {
    if start.is_empty()
        || layers == 0
        || !start.iter().chain(foes).chain(bans).all(validate_shape)
        || !valid_bounds(window)
        || window.2 <= window.0
        || window.3 <= window.1
        || ![track, via, epsilon]
            .iter()
            .all(|x| x.is_finite() && *x >= 0.0 && *x <= 1e9)
        || !cell.is_finite()
        || cell <= 0.0
        || cell > 1e9
        || toward.is_some_and(|p| !valid_point(p))
        || !start.iter().all(|s| {
            s.2 != 0
                && s.2 & layers != 0
                && contains(window, (s.1.0, s.1.1))
                && contains(window, (s.1.2, s.1.3))
        })
    {
        return Err(PyValueError::new_err(
            "invalid surface escape geometry or search parameters",
        ));
    }
    let nx = ((window.2 - window.0) / cell).ceil().max(1.0);
    let ny = ((window.3 - window.1) / cell).ceil().max(1.0);
    if nx > 1_000_000.0 || ny > 1_000_000.0 || nx * ny > 1_000_000.0 {
        return Err(PyValueError::new_err(
            "surface escape search exceeds one million cells",
        ));
    }
    Ok((nx as i64, ny as i64))
}

#[pyfunction]
#[pyo3(signature = (start, foes, layers, window, track, via, toward, bans, cell, epsilon, via_exit=false))]
pub fn surface_path_out(
    py: Python<'_>,
    start: Vec<Shape>,
    foes: Vec<Shape>,
    layers: u32,
    window: Bounds,
    track: f64,
    via: f64,
    toward: Option<Point>,
    bans: Vec<Shape>,
    cell: f64,
    epsilon: f64,
    via_exit: bool,
) -> PyResult<bool> {
    let (nx, ny) = validate_search(
        &start, &foes, layers, window, track, via, toward, &bans, cell, epsilon,
    )?;
    py.check_signals()?;
    let width = window.2 - window.0;
    let height = window.3 - window.1;
    let (cw, ch) = (width / nx as f64, height / ny as f64);
    let centre = |i: i64, j: i64| {
        (
            window.0 + (i as f64 + 0.5) * cw,
            window.1 + (j as f64 + 0.5) * ch,
        )
    };
    let walls: Vec<Shape> = foes.iter().filter(|s| s.2 & layers != 0).cloned().collect();
    let top = start.iter().fold(
        (
            f64::INFINITY,
            f64::INFINITY,
            f64::NEG_INFINITY,
            f64::NEG_INFINITY,
        ),
        |b, s| {
            (
                b.0.min(s.1.0),
                b.1.min(s.1.1),
                b.2.max(s.1.2),
                b.3.max(s.1.3),
            )
        },
    );
    let mid = ((top.0 + top.2) / 2.0, (top.1 + top.3) / 2.0);
    let mut todo = Vec::new();
    for i in
        (((top.0 - window.0) / cw) as i64).max(0)..((((top.2 - window.0) / cw) as i64) + 1).min(nx)
    {
        for j in (((top.1 - window.1) / ch) as i64).max(0)
            ..((((top.3 - window.1) / ch) as i64) + 1).min(ny)
        {
            if on_start(&start, centre(i, j)) {
                todo.push((i, j));
            }
        }
    }
    let mut seen: HashSet<_> = todo.iter().copied().collect();
    let mut memo = HashMap::new();
    let mut visits = 0usize;
    while let Some((i, j)) = todo.pop() {
        visits += 1;
        if visits % 1024 == 0 {
            // Let the existing command watchdog request its stop, then obey
            // Python's stop/SIGINT handler without returning a partial verdict.
            py.detach(std::thread::yield_now);
            py.check_signals()?;
        }
        let p = centre(i, j);
        if (i == 0 || i == nx - 1 || j == 0 || j == ny - 1) && facing(p, mid, toward) {
            return Ok(true);
        }
        if via_exit
            && !on_start(&start, p)
            && !near(&foes, p, via, epsilon)
            && !near(&bans, p, via, epsilon)
        {
            return Ok(true);
        }
        for k in [(i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)] {
            if 0 <= k.0
                && k.0 < nx
                && 0 <= k.1
                && k.1 < ny
                && !seen.contains(&k)
                && !*memo
                    .entry(k)
                    .or_insert_with(|| near(&walls, centre(k.0, k.1), track, epsilon))
            {
                seen.insert(k);
                todo.push(k);
            }
        }
    }
    let mut anchors = Vec::new();
    for s in &start {
        let points = if s.3.is_empty() {
            vec![((s.1.0 + s.1.2) / 2.0, (s.1.1 + s.1.3) / 2.0)]
        } else {
            s.3.clone()
        };
        for p in points {
            if !anchors.contains(&p) {
                anchors.push(p);
            }
        }
    }
    for anchor in anchors {
        let mut seen = HashSet::from([(0i64, 0i64)]);
        let mut todo = vec![(0i64, 0i64)];
        while let Some((i, j)) = todo.pop() {
            visits += 1;
            if visits % 1024 == 0 {
                py.detach(std::thread::yield_now);
                py.check_signals()?;
            }
            let p = (anchor.0 + i as f64 * cell, anchor.1 + j as f64 * cell);
            if (p.0 - window.0 <= cell
                || window.2 - p.0 <= cell
                || p.1 - window.1 <= cell
                || window.3 - p.1 <= cell)
                && facing(p, mid, toward)
            {
                return Ok(true);
            }
            if via_exit
                && !on_start(&start, p)
                && !near(&foes, p, via, epsilon)
                && !near(&bans, p, via, epsilon)
            {
                return Ok(true);
            }
            for di in -1..=1 {
                for dj in -1..=1 {
                    let k = (i + di, j + dj);
                    if (di != 0 || dj != 0) && seen.insert(k) {
                        let q = (anchor.0 + k.0 as f64 * cell, anchor.1 + k.1 as f64 * cell);
                        if window.0 <= q.0
                            && q.0 <= window.2
                            && window.1 <= q.1
                            && q.1 <= window.3
                            && !near(&walls, q, track, epsilon)
                        {
                            todo.push(k);
                        }
                    }
                }
            }
        }
    }
    Ok(false)
}
