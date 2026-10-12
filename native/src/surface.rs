//! Exact surface escape search: the Python rectangular-cell walk followed by
//! every octilinear lattice rooted on the pad/own-copper anchors. This is a
//! geometry kernel, not a replacement for escape eligibility or validity.
use crate::geometry::{point_in_polygon, point_segment_distance, point_segment_within, segments_intersect};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashSet;

type Point = (f64, f64);
type Bounds = (f64, f64, f64, f64);
/// polygon, exact box, layer bits, track-end anchors, clearance adjustment
pub(crate) type Shape = (Vec<Point>, Bounds, u32, Vec<Point>, f64);
pub(crate) type Lane = (Vec<(Point, Point)>, u32, Bounds);
pub(crate) type Spot = (Point, f64, Bounds);
pub(crate) type Foe = (Shape, f64, f64, bool);
pub(crate) type Path = (
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

/// number, layers, box, optional copper outlines, eligible, track reach,
/// via radius, via drill radius, clearance. Eligibility is original intent, supplied
/// by the prepared snapshot rather than weakened by candidate geometry.
pub(crate) type PadRecord = (
    String,
    u32,
    Bounds,
    Option<Vec<Vec<Point>>>,
    bool,
    f64,
    f64,
    f64,
    f64,
);

struct Pad {
    number: String,
    layers: u32,
    box_: Bounds,
    polys: Option<Vec<Vec<Point>>>,
    eligible: bool,
    track_reach: f64,
    via_radius: f64,
    drill_radius: f64,
    clearance: f64,
}
impl Pad {
    fn from_record(record: PadRecord) -> Self {
        let (
            number,
            layers,
            box_,
            polys,
            eligible,
            track_reach,
            via_radius,
            drill_radius,
            clearance,
        ) = record;
        Self {
            number,
            layers,
            box_,
            polys,
            eligible,
            track_reach,
            via_radius,
            drill_radius,
            clearance,
        }
    }
}

fn centre(box_: Bounds) -> Point {
    ((box_.0 + box_.2) / 2.0, (box_.1 + box_.3) / 2.0)
}
fn union(boxes: impl Iterator<Item = Bounds>) -> Bounds {
    boxes.fold(
        (
            f64::INFINITY,
            f64::INFINITY,
            f64::NEG_INFINITY,
            f64::NEG_INFINITY,
        ),
        |a, b| (a.0.min(b.0), a.1.min(b.1), a.2.max(b.2), a.3.max(b.3)),
    )
}
fn corners(b: Bounds) -> [Point; 4] {
    [(b.0, b.1), (b.2, b.1), (b.2, b.3), (b.0, b.3)]
}
fn ray_exit(b: Bounds, u: Point) -> f64 {
    let x = if u.0.abs() > 1e-12 {
        (b.2 - b.0) / 2.0 / u.0.abs()
    } else {
        f64::INFINITY
    };
    let y = if u.1.abs() > 1e-12 {
        (b.3 - b.1) / 2.0 / u.1.abs()
    } else {
        f64::INFINITY
    };
    x.min(y)
}
fn to_edge(p: Point, u: Point, b: Bounds) -> f64 {
    let mut t = f64::INFINITY;
    for (v, k, lo, hi) in [(p.0, u.0, b.0, b.2), (p.1, u.1, b.1, b.3)] {
        if k > 1e-12 {
            t = t.min((hi - v) / k);
        } else if k < -1e-12 {
            t = t.min((lo - v) / k);
        }
    }
    t.max(0.0)
}
fn copper_exit(c: Point, u: Point, polys: &[Vec<Point>]) -> f64 {
    let mut t = f64::INFINITY;
    for poly in polys.iter().filter(|p| point_in_polygon(c, p)) {
        for i in 0..poly.len() {
            let (a, b) = (poly[i], poly[(i + 1) % poly.len()]);
            let (ex, ey) = (b.0 - a.0, b.1 - a.1);
            let den = u.0 * ey - u.1 * ex;
            if den.abs() < 1e-15 {
                continue;
            }
            let tt = ((a.0 - c.0) * ey - (a.1 - c.1) * ex) / den;
            let ss = ((a.0 - c.0) * u.1 - (a.1 - c.1) * u.0) / den;
            if tt > 0.0 && (-1e-12..=1.0 + 1e-12).contains(&ss) {
                t = t.min(tt);
            }
        }
    }
    if t == f64::INFINITY {
        0.0
    } else {
        t
    }
}

/// A dog-leg's turn, in compass steps: 45 and 90 degrees either way (Python `_DOG_LEGS`).
const DOG_LEGS: [i64; 4] = [1, -1, 2, -2];

/// Exact pad-lane generation twin. Rotation coefficients are computed once
/// with Python's math functions when preparing turns. Local centres and the
/// returned row normal use the same clean9 applications as _pin_normal.
#[pyfunction]
pub fn surface_lanes(
    py: Python<'_>,
    records: Vec<PadRecord>,
    rotation: f64,
    turn: Point,
    reach: f64,
    minimum: usize,
) -> PyResult<(Vec<(String, Lane, Point)>, Vec<(String, Spot)>)> {
    py.check_signals()?;
    let mut pads: Vec<_> = records.into_iter().map(Pad::from_record).collect();
    if !rotation.is_finite()
        || !valid_point(turn)
        || turn.0.abs() > 1.0
        || turn.1.abs() > 1.0
        || (crate::exact::hypot(turn.0, turn.1) - 1.0).abs() > 1e-9
        || !reach.is_finite()
        || reach < 0.0
        || reach > 1e9
        || pads.len() > 100_000
    {
        return Err(PyValueError::new_err("surface lane snapshot invalid"));
    }
    let mut numbers = HashSet::new();
    for pad in &pads {
        if !numbers.insert(&pad.number)
            || !valid_bounds(pad.box_)
            || pad.layers == 0
            || [
                pad.track_reach,
                pad.via_radius,
                pad.drill_radius,
                pad.clearance,
            ]
            .iter()
            .any(|v| !v.is_finite() || *v < 0.0 || *v > 1e9)
            || pad.polys.as_ref().is_some_and(|polys| {
                polys.iter().any(|poly| {
                    !validate_shape(&(poly.clone(), pad.box_, pad.layers, Vec::new(), 0.0))
                }) || (!polys.is_empty()
                    && union(polys.iter().flatten().map(|p| (p.0, p.1, p.0, p.1))) != pad.box_)
            })
        {
            return Err(PyValueError::new_err("surface lane pad invalid"));
        }
    }
    if pads.len() < minimum || pads.is_empty() {
        return Ok((Vec::new(), Vec::new()));
    }
    pads.sort_by(|a, b| a.number.cmp(&b.number));
    let (cos, sin) = turn;
    let local = |p: Point| {
        (
            crate::exact::clean9(cos * p.0 - sin * p.1),
            crate::exact::clean9(sin * p.0 + cos * p.1),
        )
    };
    let field = union(pads.iter().map(|p| {
        let c = local(centre(p.box_));
        (c.0, c.1, c.0, c.1)
    }));
    let body = centre(union(pads.iter().map(|p| p.box_)));
    let compass = [
        (1.0, 0.0),
        (0.707106781187, 0.707106781187),
        (0.0, 1.0),
        (-0.707106781187, 0.707106781187),
        (-1.0, 0.0),
        (-0.707106781187, -0.707106781187),
        (0.0, -1.0),
        (0.707106781187, -0.707106781187),
    ];
    let mut lanes = Vec::new();
    let mut spots = Vec::new();
    for (index, pad) in pads.iter().enumerate() {
        if index % 32 == 0 {
            py.check_signals()?;
        }
        if !pad.eligible {
            continue;
        }
        let c = centre(pad.box_);
        let at = local(c);
        let fc = centre(field);
        let (hw, hh) = ((field.2 - field.0) / 2.0, (field.3 - field.1) / 2.0);
        let mut rx = if hw > 1e-6 {
            (at.0 - fc.0).abs() / hw
        } else {
            0.0
        };
        let mut ry = if hh > 1e-6 {
            (at.1 - fc.1).abs() / hh
        } else {
            0.0
        };
        let mut fallback = false;
        if (rx - ry).abs() < 1e-6 {
            let (mut w, mut h) = (pad.box_.2 - pad.box_.0, pad.box_.3 - pad.box_.1);
            if rotation.rem_euclid(180.0) == 90.0 {
                std::mem::swap(&mut w, &mut h);
            }
            if (w - h).abs() < 1e-6 {
                fallback = true;
            } else if w > h {
                rx = 1.0;
                ry = 0.0;
            } else {
                rx = 0.0;
                ry = 1.0;
            }
        }
        let d = if fallback {
            let u = (c.0 - body.0, c.1 - body.1);
            let n = crate::exact::hypot(u.0, u.1);
            if n > 1e-9 {
                (u.0 / n, u.1 / n)
            } else {
                (1.0, 0.0)
            }
        } else {
            let n = if rx > ry {
                (if at.0 >= fc.0 { 1.0 } else { -1.0 }, 0.0)
            } else {
                (0.0, if at.1 >= fc.1 { 1.0 } else { -1.0 })
            };
            let u = (
                crate::exact::clean9(cos * n.0 + sin * n.1),
                crate::exact::clean9(-sin * n.0 + cos * n.1),
            );
            let size = crate::exact::hypot(u.0, u.1);
            (u.0 / size, u.1 / size)
        };
        let d = (crate::exact::clean9(d.0), crate::exact::clean9(d.1));
        let blind = pad
            .polys
            .as_ref()
            .is_some_and(|polys| !polys.iter().any(|p| point_in_polygon(c, p)));
        let exit = |u| {
            pad.polys
                .as_ref()
                .map_or_else(|| ray_exit(pad.box_, u), |p| copper_exit(c, u, p))
        };
        let h = exit(d);
        let start = (c.0 + d.0 * h, c.1 + d.1 * h);
        let mut first = 0.0;
        let mut out = 0.0;
        if pads.len() > 2 {
            let others: Vec<_> = pads
                .iter()
                .filter(|p| p.number != pad.number)
                .map(|p| p.box_)
                .collect();
            first = corners(union(others.iter().copied()))
                .iter()
                .map(|q| (q.0 - start.0) * d.0 + (q.1 - start.1) * d.1)
                .fold(0.0, f64::max);
            out = first;
            let e = (start.0 + d.0 * first, start.1 + d.1 * first);
            let mut more: f64 = 0.0;
            for q in others.iter().flat_map(|b| corners(*b)) {
                let along = (q.0 - e.0) * d.0 + (q.1 - e.1) * d.1;
                let side = ((q.0 - e.0) * d.1 - (q.1 - e.1) * d.0).abs();
                more = more.max(pad.track_reach * 2.0f64.sqrt() - side + along);
            }
            first += more;
        }
        let win = (
            pad.box_.0 - reach,
            pad.box_.1 - reach,
            pad.box_.2 + reach,
            pad.box_.3 + reach,
        );
        let length = first.min(to_edge(start, d, win));
        let end = (start.0 + d.0 * length, start.1 + d.1 * length);
        if !blind {
            for (k, u) in compass.iter().copied().enumerate() {
                let a = if pads.len() > 2 {
                    end
                } else {
                    let e = exit(u);
                    (c.0 + u.0 * e, c.1 + u.1 * e)
                };
                let length = to_edge(a, u, win);
                let f = (a.0 + u.0 * length, a.1 + u.1 * length);
                let first_leg = if pads.len() > 2 { (start, end) } else { (a, a) };
                let mut ways = vec![(vec![first_leg, (a, f)], u)];
                // Its dog-legs (Python `_DOG_LEGS`): halfway along, a turn of 45 or 90 degrees either way, then on to
                // the window's edge.
                if length > 1e-9 {
                    let half_way = length / 2.0;
                    let m = (a.0 + u.0 * half_way, a.1 + u.1 * half_way);
                    for turn in DOG_LEGS {
                        let v = compass[(k as i64 + turn).rem_euclid(8) as usize];
                        let run = to_edge(m, v, win);
                        ways.push((vec![first_leg, (a, m), (m, (m.0 + v.0 * run, m.1 + v.1 * run))], v));
                    }
                }
                for (legs, direction) in ways {
                    let box_ = union(
                        legs.iter()
                            .flat_map(|(a, b)| [a, b])
                            .map(|p| (p.0, p.1, p.0, p.1)),
                    );
                    lanes.push((pad.number.clone(), (legs, pad.layers, box_), direction));
                }
            }
        }
        let mut directions = vec![d];
        if pads.len() <= 2 {
            directions.extend([(-d.1, d.0), (d.1, -d.0)]);
            if pads.len() == 1 {
                directions.push((-d.0, -d.1));
            }
        }
        let mut at: Vec<_> = directions
            .iter()
            .map(|u| {
                let half = u.0.abs() * (pad.box_.2 - pad.box_.0) / 2.0
                    + u.1.abs() * (pad.box_.3 - pad.box_.1) / 2.0;
                (
                    c.0 + u.0 * (half + pad.via_radius),
                    c.1 + u.1 * (half + pad.via_radius),
                )
            })
            .collect();
        if first > 0.0 {
            let t = first.max(out + pad.via_radius + pad.clearance);
            at.push((start.0 + d.0 * t, start.1 + d.1 * t));
        }
        for p in at {
            if blind
                && !pad.polys.as_ref().unwrap().iter().any(|poly| {
                    point_distance(p, poly) <= pad.via_radius + 1e-9
                        && poly
                            .iter()
                            .map(|q| crate::exact::hypot(q.0 - p.0, q.1 - p.1))
                            .fold(0.0, f64::max)
                            >= pad.drill_radius - 1e-9
                })
            {
                continue;
            }
            spots.push((
                pad.number.clone(),
                (
                    p,
                    pad.via_radius,
                    (
                        p.0 - pad.via_radius,
                        p.1 - pad.via_radius,
                        p.0 + pad.via_radius,
                        p.1 + pad.via_radius,
                    ),
                ),
            ));
        }
    }
    if lanes.iter().any(|(_, lane, _)| {
        !valid_bounds(lane.2)
            || lane
                .0
                .iter()
                .any(|(a, b)| !valid_point(*a) || !valid_point(*b))
    }) || spots
        .iter()
        .any(|(_, spot)| !valid_point(spot.0) || !valid_bounds(spot.2))
    {
        return Err(PyValueError::new_err(
            "generated surface lanes exceed coordinate bounds",
        ));
    }
    Ok((lanes, spots))
}

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
/// surface/via/away/walled; 4 means a quiet pad has a way out and no finding;
/// 5 a walled suspect the exact search was not asked of (`exact` false).
/// Python `_verdict`'s twin: the lanes and via spots grade the pad (an open
/// lane toward the target, else a free via spot, else an open lane any way);
/// the exact search (via_exit=false) runs only on a suspect, any way.
#[pyfunction]
#[pyo3(signature = (lanes, spots, foes, bans, aim, centre, quiet, path, exact=true))]
#[allow(clippy::too_many_arguments)]
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
    exact: bool,
) -> PyResult<u8> {
    py.check_signals()?;
    let grid = judge_inputs(&lanes, &spots, &foes, &bans, aim, centre, &path)?;
    let open = open_lanes(&lanes, &foes);
    let (start, walls, layers, window, track, via, _, path_bans, cell, epsilon, via_exit) = path;
    if !quiet {
        let d = aim
            .ok_or_else(|| PyValueError::new_err("signal surface escape lacks target direction"))?;
        if open_toward(open.iter().map(|l| l.0.last().unwrap().1), centre, d, cell) {
            return Ok(0);
        }
    }
    grade(quiet, spot_free(&spots, &foes, &bans), !open.is_empty(), exact, || {
        Ok(path_search(
            py, &start, &walls, layers, window, grid, track, via, None, &path_bans, cell, epsilon, via_exit, None,
        )?
        .toward)
    })
}

/// A pad's grade once no open lane goes toward its target: a free via spot, else an open lane any way, else a walled
/// suspect, which `search` (whether the exact search gets out any way) decides when `exact`, else 5.
fn grade(quiet: bool, spot: bool, open: bool, exact: bool, search: impl FnOnce() -> PyResult<bool>) -> PyResult<u8> {
    if spot || open {
        return Ok(if quiet { 4 } else if spot { 1 } else { 2 });
    }
    if !exact {
        return Ok(5);
    }
    Ok(if search()? { if quiet { 4 } else { 2 } } else { 3 })
}

/// A signal pad's escape facts that do not depend on where its target is: the ends of its open lanes, whether a via
/// spot is free, and, for a walled suspect (no open lane, no free spot), whether the exact search reaches its window's
/// edge. `way` turns them and a target direction into the verdict `surface_judge` gives for the same inputs.
pub(crate) struct SurfaceFacts {
    centre: Point,
    cell: f64,
    open_ends: Vec<Point>,
    spot_free: bool,
    gets_out: bool,
}

impl SurfaceFacts {
    /// `surface_judge`'s verdict for a signal pad aiming along `d`.
    pub(crate) fn way(&self, d: Point, exact: bool) -> u8 {
        if open_toward(self.open_ends.iter().copied(), self.centre, d, self.cell) {
            return 0;
        }
        grade(false, self.spot_free, !self.open_ends.is_empty(), exact, || Ok(self.gets_out)).unwrap_or(3)
    }
}

/// The facts `SurfaceFacts::way` judges a signal pad by, from `surface_judge`'s inputs less the aim. The exact search
/// runs only for a walled suspect.
pub(crate) fn surface_facts(
    py: Python<'_>,
    lanes: Vec<Lane>,
    spots: Vec<Spot>,
    foes: Vec<Foe>,
    bans: Vec<Shape>,
    centre: Point,
    path: Path,
) -> PyResult<SurfaceFacts> {
    py.check_signals()?;
    let grid = judge_inputs(&lanes, &spots, &foes, &bans, None, centre, &path)?;
    let open_ends: Vec<Point> = open_lanes(&lanes, &foes).iter().map(|l| l.0.last().unwrap().1).collect();
    let free = spot_free(&spots, &foes, &bans);
    let (start, walls, layers, window, track, via, _, path_bans, cell, epsilon, via_exit) = path;
    let gets_out = if free || !open_ends.is_empty() {
        false
    } else {
        path_search(
            py, &start, &walls, layers, window, grid, track, via, None, &path_bans, cell, epsilon, via_exit, None,
        )?
        .toward
    };
    Ok(SurfaceFacts { centre, cell, open_ends, spot_free: free, gets_out })
}

#[allow(clippy::too_many_arguments)]
fn judge_inputs(
    lanes: &[Lane],
    spots: &[Spot],
    foes: &[Foe],
    bans: &[Shape],
    aim: Option<Point>,
    centre: Point,
    path: &Path,
) -> PyResult<(i64, i64)> {
    let grid = validate_search(
        &path.0, &path.1, path.2, path.3, path.4, path.5, aim, &path.7, path.8, path.9,
    )?;
    if path.10 {
        return Err(PyValueError::new_err(
            "invalid surface escape classification snapshot",
        ));
    }
    check_lanes(lanes, spots, foes, bans, aim, centre)?;
    Ok(grid)
}

/// `judge_inputs`'s checks of the lanes, spots, foes and bans, without the path.
fn check_lanes(
    lanes: &[Lane],
    spots: &[Spot],
    foes: &[Foe],
    bans: &[Shape],
    aim: Option<Point>,
    centre: Point,
) -> PyResult<()> {
    if !valid_point(centre)
        || aim.is_some_and(|p| !valid_point(p))
        || !foes
            .iter()
            .all(|f| validate_shape(&f.0) && f.1.is_finite() && f.1 >= 0.0 && f.2.is_finite())
        || !bans.iter().all(validate_shape)
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
    Ok(())
}

/// `surface_judge`'s grade from the lanes and spots, the exact search (`search`: whether it gets out any way) asked
/// only of a walled suspect when `exact`. It stops at the first lane that decides.
#[allow(clippy::too_many_arguments)]
pub(crate) fn judge_lanes(
    lanes: &[Lane],
    spots: &[Spot],
    foes: &[Foe],
    bans: &[Shape],
    aim: Option<Point>,
    centre: Point,
    quiet: bool,
    cell: f64,
    exact: bool,
    search: impl FnOnce() -> PyResult<bool>,
) -> PyResult<u8> {
    check_lanes(lanes, spots, foes, bans, aim, centre)?;
    if !quiet {
        let d = aim
            .ok_or_else(|| PyValueError::new_err("signal surface escape lacks target direction"))?;
        if lanes.iter().any(|l| open_toward(std::iter::once(l.0.last().unwrap().1), centre, d, cell) && lane_open(l, foes)) {
            return Ok(0);
        }
    }
    grade(quiet, spot_free(spots, foes, bans), lanes.iter().any(|l| lane_open(l, foes)), exact, search)
}

/// Whether no foe comes within its reach of the lane. A leg whose own box is that far from the foe's box is passed
/// without the exact distance.
fn lane_open(l: &Lane, foes: &[Foe]) -> bool {
    !foes.iter().any(|f| {
        (f.3 || f.0 .2 & l.1 != 0)
            && box_gap(f.0 .1, l.2) < f.1
            && l.0.iter().any(|&(a, b)| {
                box_gap(f.0 .1, (a.0.min(b.0), a.1.min(b.1), a.0.max(b.0), a.1.max(b.1))) < f.1
                    && segment_distance(a, b, &f.0 .0) < f.1
            })
    })
}

/// Whether the exact search of `path` (no via exits) reaches its window's edge any way.
pub(crate) fn search_any(py: Python<'_>, path: Path) -> PyResult<bool> {
    let (start, walls, layers, window, track, via, _, path_bans, cell, epsilon, via_exit) = path;
    if via_exit {
        return Err(PyValueError::new_err("invalid surface escape classification snapshot"));
    }
    let grid = validate_search(&start, &walls, layers, window, track, via, None, &path_bans, cell, epsilon)?;
    Ok(path_search(py, &start, &walls, layers, window, grid, track, via, None, &path_bans, cell, epsilon, false, None)?
        .toward)
}

/// The lanes no foe comes within its reach of.
fn open_lanes<'a>(lanes: &'a [Lane], foes: &[Foe]) -> Vec<&'a Lane> {
    lanes.iter().filter(|l| lane_open(l, foes)).collect()
}

/// Whether an open lane ends more than one cell toward `d` from the pad's centre (any open lane, when `d` has no
/// length).
fn open_toward(mut ends: impl Iterator<Item = Point>, centre: Point, d: Point, cell: f64) -> bool {
    let n = crate::exact::hypot(d.0, d.1);
    ends.any(|end| n < 1e-12 || ((end.0 - centre.0) * d.0 + (end.1 - centre.1) * d.1) / n > cell)
}

/// Whether some via spot is clear of every foe and every via ban.
fn spot_free(spots: &[Spot], foes: &[Foe], bans: &[Shape]) -> bool {
    spots.iter().any(|s| {
        !foes
            .iter()
            .any(|f| box_gap(f.0 .1, s.2) < f.2 && point_distance(s.0, &f.0 .0) < s.1 + f.2)
            && !bans.iter().any(|b| {
                b.1 .0 <= s.2 .2
                    && s.2 .0 <= b.1 .2
                    && b.1 .1 <= s.2 .3
                    && s.2 .1 <= b.1 .3
                    && point_distance(s.0, &b.0) < s.1
            })
    })
}

/// Whether `p` lies within `radius` (less `epsilon`, plus the shape's own adjustment) of one shape: the test every
/// search cell makes.
fn shape_near((poly, b, _, _, delta): &Shape, p: Point, radius: f64, epsilon: f64) -> bool {
    let r = (radius + delta - epsilon).max(0.0);
    if b.0 - r >= p.0 || p.0 >= b.2 + r || b.1 - r >= p.1 || p.1 >= b.3 + r {
        return false;
    }
    point_in_polygon(p, poly)
        || (0..poly.len()).any(|i| point_segment_within(p, poly[i], poly[(i + 1) % poly.len()], r))
}

/// The shapes a search tests, bucketed by area so a cell tests only the shapes whose grown box can reach it. A shape
/// is listed in every bucket its grown box (`shape_near`'s box test) covers, clamped to the grid, and a point reads
/// the bucket its own coordinates fall in, clamped the same way. A point inside a grown box therefore always finds
/// that shape listed, so `near` answers exactly what the plain scan over every shape answers.
struct ShapeIndex<'a> {
    shapes: Vec<&'a Shape>,
    radius: f64,
    epsilon: f64,
    origin: Point,
    size: f64,
    nx: i64,
    ny: i64,
    buckets: Vec<Vec<u32>>,
}

impl<'a> ShapeIndex<'a> {
    fn new(shapes: Vec<&'a Shape>, radius: f64, epsilon: f64, window: Bounds, cell: f64) -> Self {
        let span = (window.2 - window.0).max(window.3 - window.1);
        let size = (cell * 8.0).max(span / 64.0).max(1e-6);
        let nx = (((window.2 - window.0) / size).floor() as i64 + 1).clamp(1, 256);
        let ny = (((window.3 - window.1) / size).floor() as i64 + 1).clamp(1, 256);
        let mut index = Self {
            shapes,
            radius,
            epsilon,
            origin: (window.0, window.1),
            size,
            nx,
            ny,
            buckets: vec![Vec::new(); (nx * ny) as usize],
        };
        for (k, (_, b, _, _, delta)) in index.shapes.iter().enumerate() {
            let r = (radius + delta - epsilon).max(0.0);
            let (i0, j0) = index.bucket((b.0 - r, b.1 - r));
            let (i1, j1) = index.bucket((b.2 + r, b.3 + r));
            for i in i0..=i1 {
                for j in j0..=j1 {
                    index.buckets[(i * ny + j) as usize].push(k as u32);
                }
            }
        }
        index
    }

    fn bucket(&self, p: Point) -> (i64, i64) {
        let i = ((p.0 - self.origin.0) / self.size).floor();
        let j = ((p.1 - self.origin.1) / self.size).floor();
        (
            (i.clamp(0.0, (self.nx - 1) as f64)) as i64,
            (j.clamp(0.0, (self.ny - 1) as f64)) as i64,
        )
    }

    fn near(&self, p: Point) -> bool {
        let (i, j) = self.bucket(p);
        self.buckets[(i * self.ny + j) as usize]
            .iter()
            .any(|&k| shape_near(self.shapes[k as usize], p, self.radius, self.epsilon))
    }
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
                && contains(window, (s.1 .0, s.1 .1))
                && contains(window, (s.1 .2, s.1 .3))
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

/// Python path_out(exact=False), retained for handoffs' initial box check.
/// That check admits a box path before trying the exact polygons; replacing
/// it with only the exact search would change existing handoff validity.
#[pyfunction]
pub fn surface_box_path_out(
    py: Python<'_>,
    start: Vec<Shape>,
    foes: Vec<Shape>,
    holes: Vec<Shape>,
    layers: u32,
    window: Bounds,
    track: f64,
    via: f64,
    toward: Option<Point>,
    bans: Vec<Shape>,
    cell: f64,
) -> PyResult<bool> {
    let (nx, ny) = validate_search(
        &start, &foes, layers, window, track, via, toward, &bans, cell, 0.0,
    )?;
    if !holes.iter().all(validate_shape) {
        return Err(PyValueError::new_err("invalid boxed escape hole geometry"));
    }
    py.check_signals()?;
    let cw = (window.2 - window.0) / nx as f64;
    let ch = (window.3 - window.1) / ny as f64;
    let pad = union(start.iter().map(|s| s.1));
    let pad_centre = centre(pad);
    let centre = |i: i64, j: i64| {
        (
            window.0 + (i as f64 + 0.5) * cw,
            window.1 + (j as f64 + 0.5) * ch,
        )
    };
    let inside = |b: Bounds, p: Point| b.0 < p.0 && p.0 < b.2 && b.1 < p.1 && p.1 < b.3;
    let inflate = |b: Bounds, r: f64| (b.0 - r, b.1 - r, b.2 + r, b.3 + r);
    let mut walls: Vec<_> = foes
        .iter()
        .filter(|s| s.2 & layers != 0)
        .map(|s| inflate(s.1, track))
        .collect();
    let mut vias: Vec<_> = foes.iter().map(|s| inflate(s.1, via)).collect();
    for hole in &holes {
        if track + hole.4 < 0.0 || via + hole.4 < 0.0 {
            return Err(PyValueError::new_err("invalid boxed escape hole clearance"));
        }
        walls.push(inflate(hole.1, track + hole.4));
        vias.push(inflate(hole.1, via + hole.4));
    }
    for ban in &bans {
        if via + ban.4 < 0.0 {
            return Err(PyValueError::new_err("invalid boxed escape ban clearance"));
        }
        vias.push(inflate(ban.1, via + ban.4));
    }
    let slot = |i: i64, j: i64| (i * ny + j) as usize;
    let mut blocked = vec![false; (nx * ny) as usize];
    for b in walls {
        let indices = [
            (b.0 - window.0) / cw,
            (b.2 - window.0) / cw,
            (b.1 - window.1) / ch,
            (b.3 - window.1) / ch,
        ];
        if indices
            .iter()
            .any(|v| !v.is_finite() || v.abs() > i64::MAX as f64 / 2.0)
        {
            return Err(PyValueError::new_err("boxed escape cell index invalid"));
        }
        // int() truncates toward zero; do not replace these with floor.
        let (i0, i1) = ((indices[0] as i64).max(0), (indices[1] as i64).min(nx - 1));
        let (j0, j1) = ((indices[2] as i64).max(0), (indices[3] as i64).min(ny - 1));
        for i in i0..=i1 {
            py.check_signals()?;
            for j in j0..=j1 {
                if inside(b, centre(i, j)) {
                    blocked[slot(i, j)] = true;
                }
            }
        }
    }
    let mut seen = vec![false; (nx * ny) as usize];
    let mut todo = Vec::new();
    for i in 0..nx {
        py.check_signals()?;
        for j in 0..ny {
            if inside(pad, centre(i, j)) {
                seen[slot(i, j)] = true;
                todo.push((i, j));
            }
        }
    }
    let mut visits = 0;
    while let Some((i, j)) = todo.pop() {
        visits += 1;
        if visits % 1024 == 0 {
            py.check_signals()?;
        }
        let at = centre(i, j);
        if (i == 0 || i == nx - 1 || j == 0 || j == ny - 1)
            && toward
                .is_none_or(|d| d.0 * (at.0 - pad_centre.0) + d.1 * (at.1 - pad_centre.1) > 0.0)
        {
            return Ok(true);
        }
        if !inside(pad, at) && !vias.iter().any(|&b| inside(b, at)) {
            return Ok(true);
        }
        for (a, b) in [(i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)] {
            if a >= 0 && a < nx && b >= 0 && b < ny && !seen[slot(a, b)] && !blocked[slot(a, b)] {
                seen[slot(a, b)] = true;
                todo.push((a, b));
            }
        }
    }
    Ok(false)
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
    Ok(path_search(
        py, &start, &foes, layers, window, (nx, ny), track, via, toward, &bans, cell, epsilon, via_exit, None,
    )?
    .toward)
}

/// The four grid steps in the order a depth-first walk should take them to reach a way out facing `toward` soonest:
/// pushed in this order, the most aligned is taken first. Without a direction, the walk's own order. The order only
/// changes which way out is found first, never whether one is.
fn steps4(toward: Option<Point>) -> [(i64, i64); 4] {
    let mut steps = [(1i64, 0i64), (-1, 0), (0, 1), (0, -1)];
    if let Some(d) = toward {
        steps.sort_by(|a, b| {
            (a.0 as f64 * d.0 + a.1 as f64 * d.1).total_cmp(&(b.0 as f64 * d.0 + b.1 as f64 * d.1))
        });
    }
    steps
}

/// The eight lattice steps, ordered as `steps4` orders the four.
fn steps8(toward: Option<Point>) -> [(i64, i64); 8] {
    let mut steps = [(-1i64, -1i64), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)];
    if let Some(d) = toward {
        steps.sort_by(|a, b| {
            (a.0 as f64 * d.0 + a.1 as f64 * d.1).total_cmp(&(b.0 as f64 * d.0 + b.1 as f64 * d.1))
        });
    }
    steps
}

/// What one exhaustive search found: a way out facing `toward` (any way out when there is no direction, or a via
/// spot when vias exit).
struct Found {
    toward: bool,
}

/// The exact surface search: the rectangular-cell walk from the start shapes, then the octilinear lattice rooted on
/// each anchor. It stops at the first way out facing `toward`.
#[allow(clippy::too_many_arguments)]
fn path_search(
    py: Python<'_>,
    start: &[Shape],
    foes: &[Shape],
    layers: u32,
    window: Bounds,
    (nx, ny): (i64, i64),
    track: f64,
    via: f64,
    toward: Option<Point>,
    bans: &[Shape],
    cell: f64,
    epsilon: f64,
    via_exit: bool,
    mut exits: Option<&mut Vec<Point>>,
) -> PyResult<Found> {
    py.check_signals()?;
    let (order4, order8) = (steps4(toward), steps8(toward));
    let width = window.2 - window.0;
    let height = window.3 - window.1;
    let (cw, ch) = (width / nx as f64, height / ny as f64);
    let centre = |i: i64, j: i64| {
        (
            window.0 + (i as f64 + 0.5) * cw,
            window.1 + (j as f64 + 0.5) * ch,
        )
    };
    let walls = ShapeIndex::new(
        foes.iter().filter(|s| s.2 & layers != 0).collect(),
        track,
        epsilon,
        window,
        cell,
    );
    let via_walls = via_exit.then(|| {
        (
            ShapeIndex::new(foes.iter().collect(), via, epsilon, window, cell),
            ShapeIndex::new(bans.iter().collect(), via, epsilon, window, cell),
        )
    });
    let via_free = |p: Point| {
        via_walls
            .as_ref()
            .is_some_and(|(foes, bans)| !on_start(start, p) && !foes.near(p) && !bans.near(p))
    };
    let top = start.iter().fold(
        (
            f64::INFINITY,
            f64::INFINITY,
            f64::NEG_INFINITY,
            f64::NEG_INFINITY,
        ),
        |b, s| {
            (
                b.0.min(s.1 .0),
                b.1.min(s.1 .1),
                b.2.max(s.1 .2),
                b.3.max(s.1 .3),
            )
        },
    );
    let mid = ((top.0 + top.2) / 2.0, (top.1 + top.3) / 2.0);
    let found = Found { toward: true };
    // Per cell: bit 1 seen, bit 2 wall judged, bit 4 blocked.
    let slot = |i: i64, j: i64| (i * ny + j) as usize;
    let mut state = vec![0u8; (nx * ny) as usize];
    let mut todo = Vec::new();
    for i in
        (((top.0 - window.0) / cw) as i64).max(0)..((((top.2 - window.0) / cw) as i64) + 1).min(nx)
    {
        for j in (((top.1 - window.1) / ch) as i64).max(0)
            ..((((top.3 - window.1) / ch) as i64) + 1).min(ny)
        {
            if on_start(start, centre(i, j)) {
                todo.push((i, j));
                state[slot(i, j)] |= 1;
            }
        }
    }
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
        if i == 0 || i == nx - 1 || j == 0 || j == ny - 1 {
            if let Some(exits) = exits.as_mut() {
                exits.push(p);
            } else if facing(p, mid, toward) {
                return Ok(found);
            }
        }
        if via_free(p) {
            return Ok(found);
        }
        for k in order4.map(|(di, dj)| (i + di, j + dj)) {
            if 0 <= k.0 && k.0 < nx && 0 <= k.1 && k.1 < ny {
                let at = &mut state[slot(k.0, k.1)];
                if *at & 1 != 0 {
                    continue;
                }
                if *at & 2 == 0 {
                    *at |= if walls.near(centre(k.0, k.1)) { 6 } else { 2 };
                }
                if *at & 4 == 0 {
                    *at |= 1;
                    todo.push(k);
                }
            }
        }
    }
    let mut anchors = Vec::new();
    for s in start {
        let points = if s.3.is_empty() {
            vec![((s.1 .0 + s.1 .2) / 2.0, (s.1 .1 + s.1 .3) / 2.0)]
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
        // The lattice points inside the window, with two steps' margin for rounding: a point outside it is never
        // queued, so leaving it out of the seen grid changes nothing.
        let i0 = ((window.0 - anchor.0) / cell).floor() as i64 - 2;
        let i1 = ((window.2 - anchor.0) / cell).ceil() as i64 + 2;
        let j0 = ((window.1 - anchor.1) / cell).floor() as i64 - 2;
        let j1 = ((window.3 - anchor.1) / cell).ceil() as i64 + 2;
        let (w, h) = (i1 - i0 + 1, j1 - j0 + 1);
        let mut seen = vec![false; (w * h) as usize];
        let lattice = |i: i64, j: i64| ((i - i0) * h + (j - j0)) as usize;
        seen[lattice(0, 0)] = true;
        let mut todo = vec![(0i64, 0i64)];
        while let Some((i, j)) = todo.pop() {
            visits += 1;
            if visits % 1024 == 0 {
                py.detach(std::thread::yield_now);
                py.check_signals()?;
            }
            let p = (anchor.0 + i as f64 * cell, anchor.1 + j as f64 * cell);
            if p.0 - window.0 <= cell
                || window.2 - p.0 <= cell
                || p.1 - window.1 <= cell
                || window.3 - p.1 <= cell
            {
                if let Some(exits) = exits.as_mut() {
                    exits.push(p);
                } else if facing(p, mid, toward) {
                    return Ok(found);
                }
            }
            if via_free(p) {
                return Ok(found);
            }
            for (di, dj) in order8 {
                {
                    let k = (i + di, j + dj);
                    if (di == 0 && dj == 0) || k.0 < i0 || k.0 > i1 || k.1 < j0 || k.1 > j1 {
                        continue;
                    }
                    let at = &mut seen[lattice(k.0, k.1)];
                    if !*at {
                        *at = true;
                        let q = (anchor.0 + k.0 as f64 * cell, anchor.1 + k.1 as f64 * cell);
                        if window.0 <= q.0
                            && q.0 <= window.2
                            && window.1 <= q.1
                            && q.1 <= window.3
                            && !walls.near(q)
                        {
                            todo.push(k);
                        }
                    }
                }
            }
        }
    }
    Ok(Found { toward: false })
}

/// The cells (and lattice points) of one pad's exact surface search that a track can reach on the lifted board: what
/// `path_search` reaches with the rest of the board's shapes alone. A candidate only adds shapes, and an added shape
/// only blocks, so the candidate's search reaches exactly the points reachable through these sets whose cells the
/// candidate's own shapes leave clear. `found` walks that, testing only the candidate's shapes.
pub(crate) struct LiftedSearch {
    window: Bounds,
    nx: i64,
    ny: i64,
    cw: f64,
    ch: f64,
    mid: Point,
    cell: f64,
    track: f64,
    epsilon: f64,
    layers: u32,
    seeds: Vec<(i64, i64)>,
    reach: Vec<u64>,
    lattices: Vec<Lattice>,
}

struct Lattice {
    anchor: Point,
    i0: i64,
    i1: i64,
    j0: i64,
    j1: i64,
    reach: Vec<u64>,
}

impl Lattice {
    fn slot(&self, i: i64, j: i64) -> Option<usize> {
        (self.i0 <= i && i <= self.i1 && self.j0 <= j && j <= self.j1)
            .then(|| ((i - self.i0) * (self.j1 - self.j0 + 1) + (j - self.j0)) as usize)
    }
}

fn bit(v: &[u64], i: usize) -> bool {
    v[i / 64] >> (i % 64) & 1 != 0
}

fn set(v: &mut [u64], i: usize) {
    v[i / 64] |= 1 << (i % 64);
}

/// The candidate's shapes one pad's search tests: `shape_near` over each, behind a box that holds them all grown by
/// their reach.
pub(crate) struct Added<'a> {
    shapes: Vec<&'a Shape>,
    radius: f64,
    epsilon: f64,
    hull: Bounds,
}

impl<'a> Added<'a> {
    fn new(shapes: Vec<&'a Shape>, radius: f64, epsilon: f64) -> Self {
        let hull = union(shapes.iter().map(|(_, b, _, _, delta)| {
            let r = (radius + delta - epsilon).max(0.0);
            (b.0 - r, b.1 - r, b.2 + r, b.3 + r)
        }));
        Self { shapes, radius, epsilon, hull }
    }

    fn near(&self, p: Point) -> bool {
        !(p.0 < self.hull.0 || p.0 > self.hull.2 || p.1 < self.hull.1 || p.1 > self.hull.3)
            && self.shapes.iter().any(|s| shape_near(s, p, self.radius, self.epsilon))
    }
}

/// The lifted search of a signal or quiet pad from `surface_judge`'s path with the rest of the board's shapes only.
pub(crate) fn lift_search(py: Python<'_>, path: &Path) -> PyResult<LiftedSearch> {
    let (start, foes, layers, window, track, via, _, bans, cell, epsilon, via_exit) = path;
    let (nx, ny) = validate_search(start, foes, *layers, *window, *track, *via, None, bans, *cell, *epsilon)?;
    if *via_exit {
        return Err(PyValueError::new_err("a lifted surface search takes no via exits"));
    }
    let (window, cell, track, epsilon, layers) = (*window, *cell, *track, *epsilon, *layers);
    let (cw, ch) = ((window.2 - window.0) / nx as f64, (window.3 - window.1) / ny as f64);
    let centre = |i: i64, j: i64| (window.0 + (i as f64 + 0.5) * cw, window.1 + (j as f64 + 0.5) * ch);
    let walls = ShapeIndex::new(foes.iter().filter(|s| s.2 & layers != 0).collect(), track, epsilon, window, cell);
    let top = union(start.iter().map(|s| s.1));
    let mid = ((top.0 + top.2) / 2.0, (top.1 + top.3) / 2.0);
    let slot = |i: i64, j: i64| (i * ny + j) as usize;
    let mut reach = vec![0u64; ((nx * ny) as usize).div_ceil(64)];
    let mut judged = vec![0u8; (nx * ny) as usize];
    let mut seeds = Vec::new();
    for i in (((top.0 - window.0) / cw) as i64).max(0)..((((top.2 - window.0) / cw) as i64) + 1).min(nx) {
        for j in (((top.1 - window.1) / ch) as i64).max(0)..((((top.3 - window.1) / ch) as i64) + 1).min(ny) {
            if on_start(start, centre(i, j)) {
                seeds.push((i, j));
                set(&mut reach, slot(i, j));
            }
        }
    }
    let mut todo = seeds.clone();
    let mut visits = 0usize;
    while let Some((i, j)) = todo.pop() {
        visits += 1;
        if visits % 1024 == 0 {
            py.check_signals()?;
        }
        for k in [(i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)] {
            if 0 <= k.0 && k.0 < nx && 0 <= k.1 && k.1 < ny {
                let s = slot(k.0, k.1);
                if bit(&reach, s) {
                    continue;
                }
                if judged[s] == 0 {
                    judged[s] = if walls.near(centre(k.0, k.1)) { 2 } else { 1 };
                }
                if judged[s] == 1 {
                    set(&mut reach, s);
                    todo.push(k);
                }
            }
        }
    }
    let mut anchors = Vec::new();
    for s in start.iter() {
        let points = if s.3.is_empty() { vec![((s.1 .0 + s.1 .2) / 2.0, (s.1 .1 + s.1 .3) / 2.0)] } else { s.3.clone() };
        for p in points {
            if !anchors.contains(&p) {
                anchors.push(p);
            }
        }
    }
    let mut lattices = Vec::new();
    for anchor in anchors {
        let mut lattice = Lattice {
            anchor,
            i0: ((window.0 - anchor.0) / cell).floor() as i64 - 2,
            i1: ((window.2 - anchor.0) / cell).ceil() as i64 + 2,
            j0: ((window.1 - anchor.1) / cell).floor() as i64 - 2,
            j1: ((window.3 - anchor.1) / cell).ceil() as i64 + 2,
            reach: Vec::new(),
        };
        let size = ((lattice.i1 - lattice.i0 + 1) * (lattice.j1 - lattice.j0 + 1)) as usize;
        lattice.reach = vec![0u64; size.div_ceil(64)];
        let mut seen = vec![false; size];
        let origin = lattice.slot(0, 0).unwrap();
        seen[origin] = true;
        set(&mut lattice.reach, origin);
        let mut todo = vec![(0i64, 0i64)];
        while let Some((i, j)) = todo.pop() {
            visits += 1;
            if visits % 1024 == 0 {
                py.check_signals()?;
            }
            for di in -1..=1 {
                for dj in -1..=1 {
                    let k = (i + di, j + dj);
                    let Some(s) = lattice.slot(k.0, k.1).filter(|_| di != 0 || dj != 0) else { continue };
                    if !seen[s] {
                        seen[s] = true;
                        let q = (anchor.0 + k.0 as f64 * cell, anchor.1 + k.1 as f64 * cell);
                        if window.0 <= q.0 && q.0 <= window.2 && window.1 <= q.1 && q.1 <= window.3 && !walls.near(q) {
                            set(&mut lattice.reach, s);
                            todo.push(k);
                        }
                    }
                }
            }
        }
        lattices.push(lattice);
    }
    Ok(LiftedSearch { window, nx, ny, cw, ch, mid, cell, track, epsilon, layers, seeds, reach, lattices })
}

impl LiftedSearch {
    /// `path_search`'s answer (without via exits) on the lifted board with `added` shapes on it too.
    fn found(&self, py: Python<'_>, added: &[Shape], toward: Option<Point>) -> PyResult<Found> {
        let (order4, order8) = (steps4(toward), steps8(toward));
        let walls = Added::new(added.iter().filter(|s| s.2 & self.layers != 0).collect(), self.track, self.epsilon);
        let found = Found { toward: true };
        let (nx, ny, window, cw, ch) = (self.nx, self.ny, self.window, self.cw, self.ch);
        let centre = |i: i64, j: i64| (window.0 + (i as f64 + 0.5) * cw, window.1 + (j as f64 + 0.5) * ch);
        let slot = |i: i64, j: i64| (i * ny + j) as usize;
        let mut seen = vec![0u64; self.reach.len()];
        for &(i, j) in &self.seeds {
            set(&mut seen, slot(i, j));
        }
        let mut todo = self.seeds.clone();
        let mut visits = 0usize;
        while let Some((i, j)) = todo.pop() {
            visits += 1;
            if visits % 1024 == 0 {
                py.check_signals()?;
            }
            if i == 0 || i == nx - 1 || j == 0 || j == ny - 1 {
                if facing(centre(i, j), self.mid, toward) {
                    return Ok(found);
                }
            }
            for k in order4.map(|(di, dj)| (i + di, j + dj)) {
                if 0 <= k.0 && k.0 < nx && 0 <= k.1 && k.1 < ny {
                    let s = slot(k.0, k.1);
                    if bit(&self.reach, s) && !bit(&seen, s) && !walls.near(centre(k.0, k.1)) {
                        set(&mut seen, s);
                        todo.push(k);
                    }
                }
            }
        }
        for lattice in &self.lattices {
            let anchor = lattice.anchor;
            let mut seen = vec![0u64; lattice.reach.len()];
            set(&mut seen, lattice.slot(0, 0).unwrap());
            let mut todo = vec![(0i64, 0i64)];
            while let Some((i, j)) = todo.pop() {
                visits += 1;
                if visits % 1024 == 0 {
                    py.check_signals()?;
                }
                let p = (anchor.0 + i as f64 * self.cell, anchor.1 + j as f64 * self.cell);
                if p.0 - window.0 <= self.cell
                    || window.2 - p.0 <= self.cell
                    || p.1 - window.1 <= self.cell
                    || window.3 - p.1 <= self.cell
                {
                    if facing(p, self.mid, toward) {
                        return Ok(found);
                    }
                }
                for (di, dj) in order8 {
                    {
                        let k = (i + di, j + dj);
                        let Some(s) = lattice.slot(k.0, k.1).filter(|_| di != 0 || dj != 0) else { continue };
                        if !bit(&seen, s) {
                            set(&mut seen, s);
                            let q = (anchor.0 + k.0 as f64 * self.cell, anchor.1 + k.1 as f64 * self.cell);
                            if bit(&lattice.reach, s) && !walls.near(q) {
                                todo.push(k);
                            }
                        }
                    }
                }
            }
        }
        Ok(Found { toward: false })
    }
}

/// One pad's judgement inputs on the lifted board: its lanes, spots, the rest of the board's foes and bans, which
/// lanes those leave open, which spots they leave free, and its exact search's path, whose lifted search is made the
/// first time a walled suspect asks it. `judge` adds a candidate's shapes.
pub(crate) struct LiftedPad {
    lanes: Vec<Lane>,
    spots: Vec<Spot>,
    open: Vec<usize>,
    free: Vec<usize>,
    centre: Point,
    cell: f64,
    path: Path,
    search: std::sync::OnceLock<LiftedSearch>,
}

pub(crate) fn lift_pad(
    py: Python<'_>,
    lanes: Vec<Lane>,
    spots: Vec<Spot>,
    foes: Vec<Foe>,
    bans: Vec<Shape>,
    centre: Point,
    path: Path,
) -> PyResult<LiftedPad> {
    py.check_signals()?;
    judge_inputs(&lanes, &spots, &foes, &bans, None, centre, &path)?;
    let open = (0..lanes.len())
        .filter(|&i| open_lanes(std::slice::from_ref(&lanes[i]), &foes).len() == 1)
        .collect();
    let free = (0..spots.len())
        .filter(|&i| spot_free(std::slice::from_ref(&spots[i]), &foes, &bans))
        .collect();
    let cell = path.8;
    Ok(LiftedPad { lanes, spots, open, free, centre, cell, path, search: std::sync::OnceLock::new() })
}

impl LiftedPad {
    /// `surface_judge`'s verdict with the candidate's foes and bans added to the lifted board's; `walls` gives the
    /// candidate's path shapes, asked only when a walled suspect is searched (`exact`).
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn judge(
        &self,
        py: Python<'_>,
        foes: &[Foe],
        bans: &[Shape],
        aim: Option<Point>,
        quiet: bool,
        exact: bool,
        walls: impl FnOnce() -> Vec<Shape>,
    ) -> PyResult<u8> {
        py.check_signals()?;
        if aim.is_some_and(|p| !valid_point(p))
            || !foes.iter().all(|f| validate_shape(&f.0) && f.1.is_finite() && f.1 >= 0.0 && f.2.is_finite())
            || !bans.iter().all(validate_shape)
        {
            return Err(PyValueError::new_err("invalid surface escape classification snapshot"));
        }
        let open = || self.open.iter().map(|&i| &self.lanes[i]).filter(|l| lane_open(l, foes));
        if !quiet {
            let d = aim.ok_or_else(|| PyValueError::new_err("signal surface escape lacks target direction"))?;
            if self.open.iter().map(|&i| &self.lanes[i])
                .any(|l| open_toward(std::iter::once(l.0.last().unwrap().1), self.centre, d, self.cell) && lane_open(l, foes)) {
                return Ok(0);
            }
        }
        let spot = self
            .free
            .iter()
            .any(|&i| spot_free(std::slice::from_ref(&self.spots[i]), foes, bans));
        grade(quiet, spot, open().next().is_some(), exact, || {
            let walls = walls();
            if !walls.iter().all(validate_shape) {
                return Err(PyValueError::new_err("invalid surface escape classification snapshot"));
            }
            if self.search.get().is_none() {
                let lifted = lift_search(py, &self.path)?;
                let _ = self.search.set(lifted);
            }
            Ok(self.search.get().unwrap().found(py, &walls, None)?.toward)
        })
    }
}
