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
            for u in compass {
                let a = if pads.len() > 2 {
                    end
                } else {
                    let e = exit(u);
                    (c.0 + u.0 * e, c.1 + u.1 * e)
                };
                let length = to_edge(a, u, win);
                let f = (a.0 + u.0 * length, a.1 + u.1 * length);
                let legs = if pads.len() > 2 {
                    vec![(start, end), (a, f)]
                } else {
                    vec![(a, a), (a, f)]
                };
                let box_ = union(
                    legs.iter()
                        .flat_map(|(a, b)| [a, b])
                        .map(|p| (p.0, p.1, p.0, p.1)),
                );
                lanes.push((pad.number.clone(), (legs, pad.layers, box_), u));
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
                (f.3 || f.0 .2 & l.1 != 0)
                    && box_gap(f.0 .1, l.2) < f.1
                    && l.0
                        .iter()
                        .any(|&(a, b)| segment_distance(a, b, &f.0 .0) < f.1)
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
            .any(|f| box_gap(f.0 .1, s.2) < f.2 && point_distance(s.0, &f.0 .0) < s.1 + f.2)
            && !bans.iter().any(|b| {
                b.1 .0 <= s.2 .2
                    && s.2 .0 <= b.1 .2
                    && b.1 .1 <= s.2 .3
                    && s.2 .1 <= b.1 .3
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
                b.0.min(s.1 .0),
                b.1.min(s.1 .1),
                b.2.max(s.1 .2),
                b.3.max(s.1 .3),
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
