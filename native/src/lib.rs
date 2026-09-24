//! `placemat_native`: an optional accelerator for placemat's geometry hot
//! path. Imported by `placemat.geometry` when present; every function here
//! has a pure-Python reference implementation that stays the source of
//! truth for behaviour (see docs/superpowers/specs/2026-09-24-native-core-design.md).

mod board;
mod escapes;
mod exact;
mod geometry;
mod pockets;
mod ratsnest;
mod shapes;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;

type Point = (f64, f64);

#[pyfunction]
fn polys_overlap(a: Vec<Point>, b: Vec<Point>) -> bool {
    geometry::polys_overlap(&a, &b)
}

#[pyfunction]
fn poly_distance(a: Vec<Point>, b: Vec<Point>) -> f64 {
    geometry::poly_distance(&a, &b)
}

#[pyfunction]
fn point_segment_distance(p: Point, a: Point, b: Point) -> f64 {
    geometry::point_segment_distance(p, a, b)
}

/// `placer._largest_rectangle`, whole - see native/src/pockets.rs.
#[pyfunction]
#[pyo3(signature = (free, rows, cols, need_r=1, need_c=1))]
fn largest_rectangle(
    free: Vec<Vec<bool>>,
    rows: usize,
    cols: usize,
    need_r: usize,
    need_c: usize,
) -> Option<(usize, usize, usize, usize, usize)> {
    pockets::largest_rectangle(&free, rows, cols, need_r, need_c)
}

/// A `shapes::Shape` as a plain tuple, for tests to build from Python
/// without going through `Occupancy` at all: (kind, faces, layers, net,
/// poly, owner, owner_is_footprint, is_lead, margin). `faces` bit 0 = front,
/// bit 1 = back; `layers` a bitmask (only its zero-ness matters to
/// `conflict`, so any nonzero value works in a test that never mixes it
/// with a real layer set). `owner` is compared directly (the
/// courtyard-vs-lead rule needs "is this the SAME part's own lead"), not
/// just hashed/bucketed. `margin` is Occupancy._margins.get(owner, 0.0) -
/// only meaningful for a courtyard shape, but carried on every shape for a
/// uniform tuple shape.
type PyShape = (String, u8, u32, String, Vec<Point>, String, bool, bool, f64);

fn build_shape(t: &PyShape) -> PyResult<shapes::Shape> {
    let (kind_s, faces, layers, net, poly, owner, owner_is_footprint, is_lead, margin) = t;
    let kind = shapes::Kind::from_str(kind_s)
        .ok_or_else(|| PyValueError::new_err(format!("unknown shape kind {kind_s:?}")))?;
    let bbox = geometry_bounds(poly);
    Ok(shapes::Shape {
        kind,
        faces: *faces,
        layers: *layers,
        net: net.clone(),
        poly: poly.clone(),
        bbox,
        owner: owner.clone(),
        owner_is_footprint: *owner_is_footprint,
        is_lead: *is_lead,
        margin: *margin,
    })
}

fn geometry_bounds(poly: &[Point]) -> (f64, f64, f64, f64) {
    let x0 = poly.iter().map(|p| p.0).fold(f64::INFINITY, f64::min);
    let x1 = poly.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max);
    let y0 = poly.iter().map(|p| p.1).fold(f64::INFINITY, f64::min);
    let y1 = poly.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max);
    (x0, y0, x1, y1)
}

/// `Occupancy._conflict`'s boolean decision (not its reason string), for
/// direct fuzzing against the live Python method - see
/// tests/test_native_conflict.py.
#[pyfunction]
#[pyo3(signature = (s, o, clearance, touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance))]
#[allow(clippy::too_many_arguments)]
fn conflict(
    s: PyShape,
    o: PyShape,
    clearance: Option<f64>,
    touch: f64,
    vias_block_courtyards: bool,
    silk_clearance: f64,
    component_spacing: f64,
    default_clearance: f64,
    net_clearance: HashMap<String, f64>,
) -> PyResult<bool> {
    // gap/drawn_gap are only read by ShapeGrid::first_conflict's gap_for,
    // not by conflict() itself: unused here.
    let cfg = shapes::ConflictConfig {
        touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance, gap: 0.0, drawn_gap: 0.0,
    };
    Ok(shapes::conflict(&build_shape(&s)?, &build_shape(&o)?, clearance, &cfg))
}

/// A scan's obstacle pool, registered once (mirrors `Occupancy.obstacles()`
/// building a `ShapeIndex` once per scan) and queried once per candidate.
/// See `shapes` module doc and
/// docs/superpowers/specs/2026-09-24-native-core-design.md ("Phase 2").
#[pyclass]
struct NativeObstacles {
    grid: shapes::ShapeGrid,
    cfg: shapes::ConflictConfig,
}

#[pymethods]
impl NativeObstacles {
    #[new]
    #[pyo3(signature = (obstacles, touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance, gap, drawn_gap))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        obstacles: Vec<PyShape>,
        touch: f64,
        vias_block_courtyards: bool,
        silk_clearance: f64,
        component_spacing: f64,
        default_clearance: f64,
        net_clearance: HashMap<String, f64>,
        gap: f64,
        drawn_gap: f64,
    ) -> PyResult<Self> {
        let built: Vec<shapes::Shape> = obstacles.iter().map(build_shape).collect::<PyResult<_>>()?;
        let cfg = shapes::ConflictConfig {
            touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance, gap, drawn_gap,
        };
        Ok(NativeObstacles { grid: shapes::ShapeGrid::new(built), cfg })
    }

    /// The first (candidate shape index, obstacle index) pair that
    /// conflicts, or `None`. Python maps the indices back to its own Shape
    /// objects (the candidate list it passed, and the same ordered list it
    /// built this index from) and re-runs its own `_conflict` /
    /// `_drawn_conflict` on that one pair for the reason string - this
    /// function only decides WHICH pair, never formats anything.
    fn first_conflict(&self, candidate_shapes: Vec<PyShape>, clearance: Option<f64>) -> PyResult<Option<(usize, usize)>> {
        let built: Vec<shapes::Shape> = candidate_shapes.iter().map(build_shape).collect::<PyResult<_>>()?;
        Ok(self.grid.first_conflict(&built, clearance, &self.cfg))
    }

    /// As `first_conflict`, but against a `NativeOriginShapes` registered
    /// once for this item's (rotation, face) turn - see that class's doc.
    fn first_conflict_shifted(
        &self,
        origin: &NativeOriginShapes,
        dx: f64,
        dy: f64,
        clearance: Option<f64>,
    ) -> Option<(usize, usize)> {
        self.grid.first_conflict_shifted(&origin.shapes, dx, dy, clearance, &self.cfg)
    }
}

/// A candidate item's own shapes, turned for one (rotation, face) and left
/// at the origin - the native mirror of what
/// `Occupancy._origin_shapes` caches in Python, registered once per turn
/// (not once per `legal()` call) so a candidate at a new (x, y) on the same
/// turn costs two floats crossing the FFI boundary, not a rebuilt polygon
/// per shape. See docs/superpowers/specs/2026-09-24-native-core-design.md
/// ("per-candidate shapes stay native").
#[pyclass]
struct NativeOriginShapes {
    shapes: Vec<shapes::Shape>,
}

#[pymethods]
impl NativeOriginShapes {
    #[new]
    fn new(shapes: Vec<PyShape>) -> PyResult<Self> {
        Ok(NativeOriginShapes { shapes: shapes.iter().map(build_shape).collect::<PyResult<_>>()? })
    }
}

/// `ratsnest.mst`: one net's airwires as index pairs into `anchors`
/// ((x, y, refdes, pad number)), in Kruskal's order (native/src/ratsnest.rs).
#[pyfunction]
fn mst(anchors: Vec<(f64, f64, String, String)>, joined: Vec<(usize, usize)>) -> Vec<(usize, usize)> {
    ratsnest::mst(&anchors, &joined)
}

/// CPython's `math.hypot(a, b)`, bit for bit (native/src/exact.rs).
#[pyfunction]
fn hypot(a: f64, b: f64) -> f64 {
    exact::hypot(a, b)
}

/// `geometry._clean` on each value, for comparing against Python in bulk.
#[pyfunction]
fn clean9_many(values: Vec<f64>) -> Vec<f64> {
    values.into_iter().map(exact::clean9).collect()
}

/// `math.hypot` on each pair, for comparing against Python in bulk.
#[pyfunction]
fn hypot_many(xs: Vec<f64>, ys: Vec<f64>) -> Vec<f64> {
    xs.into_iter().zip(ys).map(|(a, b)| exact::hypot(a, b)).collect()
}

/// The board's keep-in and its reservations, mirrored from an Occupancy
/// (native/src/board.rs): built when the board's shape, cutouts or margin
/// change, and a reservation added as `Occupancy.reserve` adds one.
#[pyclass]
struct NativeBoard {
    keepin: board::Keepin,
    reservations: Vec<board::Reservation>,
}

type PyBox = (f64, f64, f64, f64);

fn bx(t: PyBox) -> board::B {
    board::B { l: t.0, t: t.1, r: t.2, b: t.3 }
}

#[pymethods]
impl NativeBoard {
    /// `kind` is "none" (no edge check), "rect", "disc" or "outline".
    /// rect: `box` and `loops` (the board's cutouts); disc: `centre`,
    /// `radius`, `bore` and `loops` (its cutouts); outline: `loops`, the
    /// board's first.
    #[new]
    #[pyo3(signature = (kind, margin, r#box=None, loops=Vec::new(), centre=None, radius=0.0, bore=0.0))]
    fn new(
        kind: &str,
        margin: Option<f64>,
        r#box: Option<PyBox>,
        loops: Vec<Vec<Point>>,
        centre: Option<Point>,
        radius: f64,
        bore: f64,
    ) -> PyResult<Self> {
        let shape = match kind {
            "rect" | "none" => board::Shape::Rect {
                board: bx(r#box.unwrap_or((0.0, 0.0, 0.0, 0.0))),
                cutouts: board::Loops::new(&loops),
            },
            "disc" => {
                let (cx, cy) = centre.ok_or_else(|| PyValueError::new_err("a disc needs its centre"))?;
                board::Shape::Disc { cx, cy, radius, bore, cutouts: board::Loops::new(&loops) }
            }
            "outline" => board::Shape::Outline { loops: board::Loops::new(&loops) },
            _ => return Err(PyValueError::new_err(format!("unknown keep-in kind {kind:?}"))),
        };
        let margin = if kind == "none" { None } else { margin };
        Ok(NativeBoard { keepin: board::Keepin { margin, shape }, reservations: Vec::new() })
    }

    /// Add a reservation: its polygon and, for one of 24 points or more,
    /// its `PolyRaster` as (x0, y0, cell, nx, ny, state rows).
    #[pyo3(signature = (poly, raster=None))]
    fn add_reservation(&mut self, poly: Vec<Point>, raster: Option<(f64, f64, f64, i64, i64, Vec<Vec<u8>>)>) {
        let bbox = board::B::of_points(&poly);
        let raster = raster.map(|(x0, y0, cell, nx, ny, state)| board::Raster { x0, y0, cell, nx, ny, state });
        self.reservations.push(board::Reservation { poly, bbox, raster });
    }

    fn reservation_count(&self) -> usize {
        self.reservations.len()
    }

    /// The edge verdict for one body box (tests): 0 allowed, else the code.
    fn edge(&self, body: PyBox) -> u8 {
        self.keepin.why_not(&bx(body)).unwrap_or(0)
    }

    /// Whether reservation `i` refuses one body box (tests).
    fn reservation_overlaps(&self, i: usize, body: PyBox) -> bool {
        self.reservations[i].overlaps(&bx(body))
    }
}

/// A searched item's cost, as `Board._scorer` weighs a candidate: the wire
/// (each target's weight times its distance, the item's pads moved as
/// `Occupancy.candidate_pad_locations` moves them), `crossing` times the
/// ratsnest crossings its leaf airwires add, and the escape weights times
/// the escapes it crosses, closes and walls off. With `prune`, a candidate
/// whose wire alone reaches the best cost weighed so far (`floor`) is not
/// weighed further and scores its wire plus `pruned`.
#[pyclass]
struct NativeScoring {
    /// (pad centre at the item's reference, target, weight), in order.
    targets: Vec<((f64, f64), (f64, f64), f64)>,
    /// Per turn: the transform to the origin placement, (a, b, c, d, tx, ty).
    transforms: Vec<(f64, f64, f64, f64, f64, f64)>,
    /// Per turn: the item's pads (net, x, y) at the origin, nets interned.
    anchors: Vec<Vec<(u32, f64, f64)>>,
    turns: Vec<Py<NativeEscTurn>>,
    rn: Py<NativeRatsnest>,
    own: Vec<u32>,
    crossing: f64,
    escaping: bool,
    weights: (f64, f64, f64), // escape crossed, closed, walled
    depth: f64,
    prune: bool,
    pruned: f64,
    #[pyo3(get, set)]
    floor: f64,
}

#[pymethods]
impl NativeScoring {
    #[new]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (rn, targets, transforms, anchors, turns, own, crossing, escaping, weights, depth, prune, pruned, floor))]
    fn new(
        py: Python<'_>,
        rn: Py<NativeRatsnest>,
        targets: Vec<((f64, f64), (f64, f64), f64)>,
        transforms: Vec<(f64, f64, f64, f64, f64, f64)>,
        anchors: Vec<Vec<(String, f64, f64)>>,
        turns: Vec<Py<NativeEscTurn>>,
        own: Vec<String>,
        crossing: f64,
        escaping: bool,
        weights: (f64, f64, f64),
        depth: f64,
        prune: bool,
        pruned: f64,
        floor: f64,
    ) -> Self {
        let (anchors, own) = {
            let mut r = rn.borrow_mut(py);
            let anchors = anchors
                .iter()
                .map(|turn| turn.iter().map(|(n, x, y)| (r.inner.intern(n), *x, *y)).collect())
                .collect();
            let own = own.iter().map(|o| r.inner.intern(o)).collect();
            (anchors, own)
        };
        NativeScoring { targets, transforms, anchors, turns, rn, own, crossing, escaping, weights, depth, prune, pruned, floor }
    }
}

impl NativeScoring {
    /// The cost of the candidate at (x, y) on turn `turn`.
    fn score(&mut self, rn: &NativeRatsnest, turns: &[PyRef<'_, NativeEscTurn>], x: f64, y: f64, turn: usize) -> f64 {
        // Transform.then(translate(x, y)), then apply: as geometry.py does it
        let (a0, b0, c0, d0, tx0, ty0) = self.transforms[turn];
        let a = 1.0 * a0 + 0.0 * c0;
        let b = 1.0 * b0 + 0.0 * d0;
        let c = 0.0 * a0 + 1.0 * c0;
        let d = 0.0 * b0 + 1.0 * d0;
        let tx = 1.0 * tx0 + 0.0 * ty0 + x;
        let ty = 0.0 * tx0 + 1.0 * ty0 + y;
        let mut wire = exact::PySum::new(); // Python's sum(): compensated
        for &((px, py), (gx, gy), w) in &self.targets {
            let qx = exact::clean9(a * px + b * py + tx);
            let qy = exact::clean9(c * px + d * py + ty);
            wire.add(w * exact::hypot(qx - gx, qy - gy));
        }
        let mut cost = wire.total();
        if self.prune && cost >= self.floor {
            return cost + self.pruned;
        }
        let pads: Vec<(u32, f64, f64)> = self.anchors[turn].iter().map(|&(n, px, py)| (n, px + x, py + y)).collect();
        let (added, crossed) = rn.inner.leaf_costs(&pads, &self.own, self.depth);
        if self.crossing > 0.0 {
            cost += self.crossing * added;
        }
        if self.escaping {
            let (closed, walled) = rn.esc.closed(&rn.inner, &turns[turn].turn, x, y, &self.own);
            let (wc, wo, ww) = self.weights;
            cost += wc * crossed as f64 + wo * closed as f64 + ww * walled as f64;
        }
        if cost < self.floor {
            self.floor = cost;
        }
        cost
    }
}

/// One end of a link in a cleanup scan: a pad of the moving part (its
/// index), or a point that stays put.
#[derive(Clone, Copy)]
enum End {
    Pad(usize),
    Fixed(f64, f64),
}

/// A part's cost as `cleanup.cleanup` weighs a move or a swap of it
/// (`cost`, `limits_ok`, `satellite_ok`, `terms`), for the native sweep:
/// the HPWL of its nets with every other pin where it stands, each link's
/// weight times its length, the crossings and escapes at the escape
/// weights; a candidate past a limit scores `over`, one whose wire reaches
/// the best cost seen (`floor`) its wire plus `over`.
#[pyclass]
struct NativeCleanupScoring {
    /// Per turn: the part's pads at the origin, as `pads_at` offsets.
    pads: Vec<Vec<(f64, f64)>>,
    /// Per net: the other pins' extents (min x, max x, min y, max y), if
    /// any, and which of the part's pads are on it.
    nets: Vec<(Option<(f64, f64, f64, f64)>, Vec<usize>)>,
    /// (weight, end, end, limit, its length now).
    links: Vec<(f64, End, End, Option<f64>, f64)>,
    /// A satellite's limit: per turn its own pad's box at the origin, its
    /// pin's box, and how far apart they may be.
    satellite: Option<(Vec<PyBox>, PyBox, f64)>,
    anchors: Vec<Vec<(u32, f64, f64)>>,
    turns: Vec<Py<NativeEscTurn>>,
    rn: Option<Py<NativeRatsnest>>,
    own: Vec<u32>,
    crossing: f64,
    escaping: bool,
    weights: (f64, f64, f64),
    depth: f64,
    over: f64,
    #[pyo3(get, set)]
    floor: f64,
}

#[pymethods]
impl NativeCleanupScoring {
    #[new]
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    #[pyo3(signature = (pads, nets, links, satellite, rn, anchors, turns, own, crossing, escaping, weights, depth, over, floor))]
    fn new(
        py: Python<'_>,
        pads: Vec<Vec<(f64, f64)>>,
        nets: Vec<(Option<(f64, f64, f64, f64)>, Vec<usize>)>,
        links: Vec<(f64, (i64, f64, f64), (i64, f64, f64), Option<f64>, f64)>,
        satellite: Option<(Vec<PyBox>, PyBox, f64)>,
        rn: Option<Py<NativeRatsnest>>,
        anchors: Vec<Vec<(String, f64, f64)>>,
        turns: Vec<Py<NativeEscTurn>>,
        own: Vec<String>,
        crossing: f64,
        escaping: bool,
        weights: (f64, f64, f64),
        depth: f64,
        over: f64,
        floor: f64,
    ) -> Self {
        // an end is (pad index, x, y): a pad of the part when the index is 0 or more
        let end = |e: (i64, f64, f64)| if e.0 >= 0 { End::Pad(e.0 as usize) } else { End::Fixed(e.1, e.2) };
        let links = links.into_iter().map(|(w, a, b, lim, now)| (w, end(a), end(b), lim, now)).collect();
        let (anchors, own) = match &rn {
            Some(r) => {
                let mut r = r.borrow_mut(py);
                let anchors = anchors.iter()
                    .map(|turn| turn.iter().map(|(n, x, y)| (r.inner.intern(n), *x, *y)).collect())
                    .collect();
                (anchors, own.iter().map(|o| r.inner.intern(o)).collect())
            }
            None => (Vec::new(), Vec::new()),
        };
        NativeCleanupScoring { pads, nets, links, satellite, anchors, turns, rn, own, crossing, escaping, weights,
                               depth, over, floor }
    }
}

impl NativeCleanupScoring {
    fn pad(&self, turn: usize, i: usize, x: f64, y: f64) -> (f64, f64) {
        let (px, py) = self.pads[turn][i];
        (px + x, py + y)
    }

    fn end(&self, e: End, turn: usize, x: f64, y: f64) -> (f64, f64) {
        match e {
            End::Pad(i) => self.pad(turn, i, x, y),
            End::Fixed(fx, fy) => (fx, fy),
        }
    }

    fn score(&mut self, rn: Option<&NativeRatsnest>, turns: &[PyRef<'_, NativeEscTurn>], x: f64, y: f64, turn: usize) -> f64 {
        // limits_ok, then satellite_ok
        for &(_, a, b, lim, now) in &self.links {
            if let Some(lim) = lim {
                let (pa, pb) = (self.end(a, turn, x, y), self.end(b, turn, x, y));
                let after = exact::hypot(pa.0 - pb.0, pa.1 - pb.1);
                if after > lim + 1e-9 && after > now + 1e-9 {
                    return self.over;
                }
            }
        }
        if let Some((mine, theirs, mm)) = &self.satellite {
            let m = mine[turn];
            let (ml, mt, mr, mb) = (m.0 + x, m.1 + y, m.2 + x, m.3 + y);
            let (tl, tt, tr, tb) = *theirs;
            let dx = pymax3(ml - tr, tl - mr, 0.0);
            let dy = pymax3(mt - tb, tt - mb, 0.0);
            if !(exact::hypot(dx, dy) <= mm + 1e-9) {
                return self.over;
            }
        }
        // cost: the HPWL of its nets, then its links
        let mut wire = 0.0f64;
        for (fixed, mine) in &self.nets {
            let (mut x0, mut x1, mut y0, mut y1) = match fixed {
                Some(e) => *e,
                None => (f64::INFINITY, f64::NEG_INFINITY, f64::INFINITY, f64::NEG_INFINITY),
            };
            for &i in mine {
                let (px, py) = self.pad(turn, i, x, y);
                if px < x0 { x0 = px; }
                if px > x1 { x1 = px; }
                if py < y0 { y0 = py; }
                if py > y1 { y1 = py; }
            }
            wire += x1 - x0 + y1 - y0;
        }
        for &(w, a, b, _, _) in &self.links {
            if w > 0.0 {
                let (pa, pb) = (self.end(a, turn, x, y), self.end(b, turn, x, y));
                wire += w * exact::hypot(pa.0 - pb.0, pa.1 - pb.1);
            }
        }
        if wire >= self.floor {
            return wire + self.over;
        }
        // terms: its crossings and escapes
        let mut terms = 0.0f64;
        if let Some(rn) = rn {
            let pads: Vec<(u32, f64, f64)> = self.anchors[turn].iter().map(|&(n, px, py)| (n, px + x, py + y)).collect();
            let (added, crossed) = rn.inner.leaf_costs(&pads, &self.own, self.depth);
            terms = self.crossing * added;
            if self.escaping {
                let (closed, walled) = rn.esc.closed(&rn.inner, &turns[turn].turn, x, y, &self.own);
                let (wc, wo, ww) = self.weights;
                terms += wc * crossed as f64 + wo * closed as f64 + ww * walled as f64;
            }
        }
        let total = wire + terms;
        if total < self.floor {
            self.floor = total;
        }
        total
    }
}

/// Python's `max(a, b, c)`: the first, replaced by each later one that is larger.
fn pymax3(a: f64, b: f64, c: f64) -> f64 {
    let mut m = a;
    if b > m { m = b; }
    if c > m { m = c; }
    m
}

/// One sweep pass of `placer.scan`, judged natively: for each
/// (x, y, turn) the body box shifted and rounded as `shifted_body_box`
/// does, then the edge, then the reservations in `reservations` order, then
/// the near-obstacle conflict - the order `Occupancy.legal_bucket` tests
/// them - stopping at the first refusal. Returns (the indexes of the legal
/// candidates, in order; and each refusal as (kind, a, b, count, first
/// candidate index) in the order first met: kind 0 an edge refusal with
/// a = its code, 1 a reservation with a = its index, 2 a conflict with
/// a = the turn << 32 | the candidate's shape in that turn's list, and
/// b = the obstacle). With `stop_at_first`
/// it stops at the first legal candidate.
#[pyfunction]
#[pyo3(signature = (board, reservations, obstacles, origins, bodies, points, clearance, stop_at_first, scoring=None))]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn sweep(
    py: Python<'_>,
    board: &NativeBoard,
    reservations: Vec<usize>,
    obstacles: &NativeObstacles,
    origins: Vec<PyRef<'_, NativeOriginShapes>>,
    bodies: Vec<PyBox>,
    points: Vec<(f64, f64, usize)>,
    clearance: Option<f64>,
    stop_at_first: bool,
    scoring: Option<Bound<'_, PyAny>>,
) -> PyResult<(Vec<usize>, Vec<f64>, Vec<(u8, i64, i64, usize, usize)>)> {
    let mut search: Option<PyRefMut<'_, NativeScoring>> = None;
    let mut tidy: Option<PyRefMut<'_, NativeCleanupScoring>> = None;
    if let Some(sc) = scoring.as_ref() {
        if let Ok(s) = sc.cast::<NativeScoring>() {
            search = Some(s.borrow_mut());
        } else {
            tidy = Some(sc.cast::<NativeCleanupScoring>()?.borrow_mut());
        }
    }
    let rn_ref: Option<Py<NativeRatsnest>> = match (&search, &tidy) {
        (Some(s), _) => Some(s.rn.clone_ref(py)),
        (_, Some(t)) => t.rn.as_ref().map(|r| r.clone_ref(py)),
        _ => None,
    };
    let rn = rn_ref.as_ref().map(|r| r.borrow(py));
    let turn_handles: Vec<Py<NativeEscTurn>> = match (&search, &tidy) {
        (Some(s), _) => s.turns.iter().map(|t| t.clone_ref(py)).collect(),
        (_, Some(t)) => t.turns.iter().map(|t| t.clone_ref(py)).collect(),
        _ => Vec::new(),
    };
    let esc_turns: Vec<PyRef<'_, NativeEscTurn>> = turn_handles.iter().map(|t| t.borrow(py)).collect();
    let mut legal = Vec::new();
    let mut scores = Vec::new();
    let mut seen: HashMap<(u8, i64, i64), usize> = HashMap::new();
    let mut refused: Vec<(u8, i64, i64, usize, usize)> = Vec::new();
    let mut refuse = |k: (u8, i64, i64), idx: usize, refused: &mut Vec<(u8, i64, i64, usize, usize)>| {
        match seen.get(&k) {
            Some(&at) => refused[at].3 += 1,
            None => {
                seen.insert(k, refused.len());
                refused.push((k.0, k.1, k.2, 1, idx));
            }
        }
    };
    for (idx, &(x, y, turn)) in points.iter().enumerate() {
        let o = bodies[turn];
        let body = board::B {
            l: exact::clean9(o.0 + x),
            t: exact::clean9(o.1 + y),
            r: exact::clean9(o.2 + x),
            b: exact::clean9(o.3 + y),
        };
        if let Some(code) = board.keepin.why_not(&body) {
            refuse((0, code as i64, 0), idx, &mut refused);
            continue;
        }
        if let Some(&ri) = reservations.iter().find(|&&ri| board.reservations[ri].overlaps(&body)) {
            refuse((1, ri as i64, 0), idx, &mut refused);
            continue;
        }
        match obstacles.grid.first_conflict_shifted(&origins[turn].shapes, x, y, clearance, &obstacles.cfg) {
            Some((si, oi)) => refuse((2, ((turn as i64) << 32) | si as i64, oi as i64), idx, &mut refused),
            None => {
                legal.push(idx);
                scores.push(match (search.as_mut(), tidy.as_mut(), rn.as_ref()) {
                    (Some(sc), _, Some(rn)) => sc.score(rn, &esc_turns, x, y, turn),
                    (_, Some(tc), rn) => tc.score(rn.map(|r| &**r), &esc_turns, x, y, turn),
                    _ => 0.0,
                });
                if stop_at_first {
                    break;
                }
            }
        }
    }
    Ok((legal, scores, refused))
}

/// The occupancy's placed ratsnest, mirrored for `leaf_costs`
/// (native/src/ratsnest.rs). Python works out each net's tree and hands it
/// over after every `Ratsnest.set_net`.
#[pyclass]
struct NativeRatsnest {
    inner: ratsnest::Ratsnest,
    esc: escapes::Escapes,
}

/// A corridor as Python hands it over: (refdes, pad number, net, layer
/// bits, polygon, box, direction, via spot, open, the pad's centre).
type PyCorr = (String, String, String, u32, Vec<Point>, PyBox, (f64, f64), bool, bool, (f64, f64));
/// Copper as Python hands it over: (owner, net, layer bits, polygon, box).
type PyMetal = (String, String, u32, Vec<Point>, PyBox);

/// A candidate's own pads and corridors for one turn, at the origin.
#[pyclass]
struct NativeEscTurn {
    turn: escapes::Turn,
}

impl NativeRatsnest {
    fn corr(&mut self, t: &PyCorr) -> escapes::Corr {
        let (part, number, net, layers, poly, b, dir, via, open, centre) = t;
        escapes::Corr {
            part: self.inner.intern(part),
            pad: self.inner.pad_key(part, number),
            net: self.inner.intern(net),
            layers: *layers,
            poly: poly.clone(),
            bbox: bx(*b),
            dir: *dir,
            via: *via,
            open: *open,
            centre: *centre,
        }
    }

    fn metal(&mut self, t: &PyMetal) -> escapes::Metal {
        let (owner, net, layers, poly, b) = t;
        escapes::Metal { owner: self.inner.intern(owner), net: self.inner.intern(net), layers: *layers,
                         poly: poly.clone(), bbox: bx(*b) }
    }
}

#[pymethods]
impl NativeRatsnest {
    #[new]
    fn new(weights: HashMap<String, f64>) -> Self {
        let mut inner = ratsnest::Ratsnest::new();
        for (net, w) in weights {
            inner.set_weight(&net, w);
        }
        NativeRatsnest { inner, esc: escapes::Escapes::default() }
    }

    /// The quiet nets (a plane's, a free net's): any way out of their pads will do.
    fn esc_set_quiet(&mut self, nets: Vec<String>) {
        self.esc.quiet = nets.iter().map(|n| self.inner.intern(n)).collect();
    }

    /// Replace one part's corridors; their ids, in order.
    fn esc_set_part(&mut self, part: &str, corridors: Vec<PyCorr>) -> Vec<usize> {
        let p = self.inner.intern(part);
        let built: Vec<escapes::Corr> = corridors.iter().map(|c| self.corr(c)).collect();
        self.esc.set_corridors(p, built)
    }

    fn esc_set_open(&mut self, flags: Vec<(usize, bool)>) {
        for (id, open) in flags {
            self.esc.set_open(id, open);
        }
    }

    /// Replace (or with `add`, extend) the copper kept under `key`.
    #[pyo3(signature = (key, metal, add=false))]
    fn esc_set_metal(&mut self, key: &str, metal: Vec<PyMetal>, add: bool) {
        let k = self.inner.intern(key);
        let built: Vec<escapes::Metal> = metal.iter().map(|m| self.metal(m)).collect();
        if add {
            self.esc.add_metal(k, built);
        } else {
            self.esc.set_metal(k, built);
        }
    }

    /// A candidate's pads and its corridors in groups (one per pad, with the
    /// pad's centre), turned for one turn at the origin.
    fn esc_turn(&mut self, pads: Vec<PyMetal>, groups: Vec<(Vec<PyCorr>, (f64, f64))>) -> NativeEscTurn {
        let pads = pads.iter().map(|m| self.metal(m)).collect();
        let groups = groups.iter().map(|(cs, centre)| (cs.iter().map(|c| self.corr(c)).collect(), *centre)).collect();
        NativeEscTurn { turn: escapes::Turn { pads, groups } }
    }

    /// `Escapes.closed` less the crossed count: (closed, walled).
    fn esc_closed(&self, turn: &NativeEscTurn, dx: f64, dy: f64, own: Vec<String>) -> (i64, i64) {
        let own: Vec<u32> = own.iter().filter_map(|r| self.inner.lookup(r)).collect();
        self.esc.closed(&self.inner, &turn.turn, dx, dy, &own)
    }

    /// anchors (refdes, pad number, x, y) in the net's order; edges as
    /// (refdes, pad, x, y, refdes, pad, x, y) in `mst`'s order.
    #[allow(clippy::type_complexity)]
    fn set_net(&mut self, net: &str, anchors: Vec<(String, String, f64, f64)>,
               edges: Vec<(String, String, f64, f64, String, String, f64, f64)>) {
        self.inner.set_net(net, &anchors, &edges);
    }

    /// `Ratsnest.leaf_costs(pads, own, depth)`.
    fn leaf_costs(&mut self, pads: Vec<(String, f64, f64)>, own: Vec<String>, depth: f64) -> (f64, i64) {
        let pads: Vec<(u32, f64, f64)> = pads.iter().map(|(n, x, y)| (self.inner.intern(n), *x, *y)).collect();
        let own: Vec<u32> = own.iter().filter_map(|r| self.inner.lookup(r)).collect();
        self.inner.leaf_costs(&pads, &own, depth)
    }
}

#[pymodule]
fn placemat_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("PLACEMAT_VERSION"))?;      // the release (git tag) it was built from: build.rs
    m.add_function(wrap_pyfunction!(polys_overlap, m)?)?;
    m.add_function(wrap_pyfunction!(poly_distance, m)?)?;
    m.add_function(wrap_pyfunction!(point_segment_distance, m)?)?;
    m.add_function(wrap_pyfunction!(conflict, m)?)?;
    m.add_function(wrap_pyfunction!(largest_rectangle, m)?)?;
    m.add_function(wrap_pyfunction!(hypot, m)?)?;
    m.add_function(wrap_pyfunction!(mst, m)?)?;
    m.add_function(wrap_pyfunction!(clean9_many, m)?)?;
    m.add_function(wrap_pyfunction!(hypot_many, m)?)?;
    m.add_class::<NativeObstacles>()?;
    m.add_class::<NativeOriginShapes>()?;
    m.add_class::<NativeBoard>()?;
    m.add_class::<NativeRatsnest>()?;
    m.add_class::<NativeEscTurn>()?;
    m.add_class::<NativeScoring>()?;
    m.add_class::<NativeCleanupScoring>()?;
    m.add_function(wrap_pyfunction!(sweep, m)?)?;
    Ok(())
}
