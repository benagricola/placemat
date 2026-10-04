//! `placemat_native`: an optional accelerator for placemat's geometry hot
//! path. Imported by `placemat.geometry` when present; every function here
//! has a pure-Python reference implementation that stays the source of
//! truth for behaviour (see docs/superpowers/specs/2026-09-24-native-core-design.md).

mod board;
mod cutouts;
mod escapes;
mod exact;
mod fill;
mod geometry;
mod giveway;
mod judge;
mod pockets;
mod profile;
mod ratsnest;
mod shapes;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};
use std::hash::BuildHasherDefault;
use shapes::IdSet;

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
type PyShape = (String, u8, u32, String, Vec<Point>, String, bool, bool, f64, bool);

fn build_shape(t: &PyShape) -> PyResult<shapes::Shape> {
    let (kind_s, faces, layers, net, poly, owner, owner_is_footprint, is_lead, margin, wire) = t;
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
        wire: *wire,
    })
}

fn geometry_bounds(poly: &[Point]) -> (f64, f64, f64, f64) {
    let x0 = poly.iter().map(|p| p.0).fold(f64::INFINITY, f64::min);
    let x1 = poly.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max);
    let y0 = poly.iter().map(|p| p.1).fold(f64::INFINITY, f64::min);
    let y1 = poly.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max);
    (x0, y0, x1, y1)
}

/// One clearance rule as Python hands it over: (on, between, within owners, min, of). See
/// `placemat.rules.ClearanceRules`; the rules arrive in declaration order.
type RuleArg = (Option<String>, Option<(String, String)>, Option<Vec<String>>, f64, Option<String>);

fn build_rules(rules: Option<Vec<RuleArg>>) -> Vec<shapes::ClearanceRule> {
    rules
        .unwrap_or_default()
        .into_iter()
        .map(|(on, between, within, min, of)| shapes::ClearanceRule {
            on,
            between,
            within: within.map(|w| w.into_iter().collect()),
            min,
            of,
        })
        .collect()
}

/// `Occupancy._conflict`'s boolean decision (not its reason string), for
/// direct fuzzing against the live Python method - see
/// tests/test_native_conflict.py.
#[pyfunction]
#[pyo3(signature = (s, o, clearance, touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance, hole_to_hole, hole_clearance, rules=None))]
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
    net_clearance: shapes::NetMap,
    hole_to_hole: f64,
    hole_clearance: f64,
    rules: Option<Vec<RuleArg>>,
) -> PyResult<bool> {
    // gap/drawn_gap are only read by ShapeGrid::first_conflict's gap_for,
    // not by conflict() itself: unused here.
    let rules = build_rules(rules);
    let max_clearance = shapes::largest_clearance(default_clearance, &net_clearance, &rules);
    let cfg = shapes::ConflictConfig {
        touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance,
        rules, gap: 0.0, drawn_gap: 0.0, hole_to_hole, hole_clearance, max_clearance,
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
    #[pyo3(signature = (obstacles, touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance, gap, drawn_gap, hole_to_hole, hole_clearance, rules=None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        obstacles: Vec<PyShape>,
        touch: f64,
        vias_block_courtyards: bool,
        silk_clearance: f64,
        component_spacing: f64,
        default_clearance: f64,
        net_clearance: shapes::NetMap,
        gap: f64,
        drawn_gap: f64,
        hole_to_hole: f64,
        hole_clearance: f64,
        rules: Option<Vec<RuleArg>>,
    ) -> PyResult<Self> {
        let built: Vec<shapes::Shape> = obstacles.iter().map(build_shape).collect::<PyResult<_>>()?;
        let rules = build_rules(rules);
        let max_clearance = shapes::largest_clearance(default_clearance, &net_clearance, &rules);
        let cfg = shapes::ConflictConfig {
            touch, vias_block_courtyards, silk_clearance, component_spacing, default_clearance, net_clearance,
            rules, gap, drawn_gap, hole_to_hole, hole_clearance, max_clearance,
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

    /// give_way's own move search (`giveway.py` `_give`): every offset of
    /// `offsets`, nearest first, at which `shapes` (registered once, at
    /// their CURRENT position - the offsets are relative to it, dx = dy = 0
    /// meaning "stay put") meet nothing in the grid when shifted by it,
    /// ignoring any registered obstacle whose index is in `skip` (the
    /// via's own current shapes, and any other via also giving way to the
    /// same candidate - `giveway._native_move_offsets` builds this from
    /// `judge.hidden`; see `first_conflict_shifted_excluding`'s own doc for
    /// why it must be excluded, not just deprioritised). With
    /// `stop_at_first`, the search stops at the first clear offset (a via's
    /// own vias, whose ring position moves with the candidate being
    /// placed, so nothing here is worth caching); without it, every clear
    /// offset is found in one call (a placed via's move search, whose ring
    /// position is fixed for the whole scan - the Python side caches this
    /// list per via and reuses it across every candidate the scan tries
    /// against it).
    fn first_clear_offset(
        &self,
        shapes: Vec<PyShape>,
        offsets: Vec<(f64, f64)>,
        clearance: Option<f64>,
        stop_at_first: bool,
        skip: Vec<usize>,
    ) -> PyResult<Vec<usize>> {
        let built: Vec<shapes::Shape> = shapes.iter().map(build_shape).collect::<PyResult<_>>()?;
        let skip: IdSet = skip.into_iter().collect();
        let mut out = Vec::new();
        let mut hint = shapes::Blockers::new(&built);
        for (i, &(dx, dy)) in offsets.iter().enumerate() {
            if !self.grid.any_conflict_shifted_excluding(&built, dx, dy, clearance, &self.cfg, &skip, &mut hint) {
                out.push(i);
                if stop_at_first {
                    break;
                }
            }
        }
        Ok(out)
    }

    /// `giveway.py`'s judgement of a share's tail (`_Judge.hit` on the tail
    /// shape): whether none of `shapes` meets the board, less the obstacles
    /// in `skip`, or `mine` (the item's own copper and what earlier
    /// actions left, which the index does not hold).
    fn tail_clear(&self, shapes: Vec<PyShape>, mine: Vec<PyShape>, clearance: Option<f64>, skip: Vec<usize>) -> PyResult<bool> {
        let built: Vec<shapes::Shape> = shapes.iter().map(build_shape).collect::<PyResult<_>>()?;
        let mine: Vec<shapes::Shape> = mine.iter().map(build_shape).collect::<PyResult<_>>()?;
        let skip: IdSet = skip.into_iter().collect();
        Ok(giveway::tail_clear(&self.grid, &built, &mine, clearance, &self.cfg, &skip))
    }

    /// `giveway._Judge.hit` against the board: the first of `shapes` that meets the board (less `skip`) or
    /// `mine` (what the index does not hold: the item's own copper, what earlier actions left), as
    /// (the shape's index, whether the other is in `mine`, its index there), or `None`. Which refusal it is,
    /// and the board's edge, are Python's.
    fn first_hit(&self, shapes: Vec<PyShape>, mine: Vec<PyShape>, clearance: Option<f64>, skip: Vec<usize>)
        -> PyResult<Option<(usize, bool, usize)>> {
        let built: Vec<shapes::Shape> = shapes.iter().map(build_shape).collect::<PyResult<_>>()?;
        let mine: Vec<shapes::Shape> = mine.iter().map(build_shape).collect::<PyResult<_>>()?;
        let skip: IdSet = skip.into_iter().collect();
        Ok(giveway::first_hit(&self.grid, &built, &mine, clearance, &self.cfg, &skip))
    }

    /// The index in `offsets` (from `start`) of the first at which a via's
    /// move passes every test `giveway._give`'s loop applies, or `None`:
    /// the disc inside `pad` (poly, radius), the copper `first` met
    /// (poly, clearance, radius) no longer met, `via` (ring, hole) shifted
    /// clear of `mine`, and `tail` (shape, far end, width, cap steps) redrawn clear of
    /// the board less `skip`, and of `mine`. The offsets are the ones
    /// `first_clear_offset` found clear of the board, or where `board` is given (the vias to set
    /// aside) every offset, the ring and hole judged against the board here. See `giveway.rs`.
    #[pyo3(signature = (via, offsets, clearance, skip, mine, centre, first, pad, tail, start, board=None))]
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    fn first_move(
        &self,
        via: Vec<PyShape>,
        offsets: Vec<(f64, f64)>,
        clearance: Option<f64>,
        skip: Vec<usize>,
        mine: Vec<PyShape>,
        centre: Point,
        first: Option<(Vec<Point>, f64, f64)>,
        pad: Option<(Vec<Point>, f64)>,
        tail: Option<(PyShape, Point, f64, usize)>,
        start: usize,
        board: Option<Vec<usize>>,
    ) -> PyResult<Option<usize>> {
        let via: Vec<shapes::Shape> = via.iter().map(build_shape).collect::<PyResult<_>>()?;
        let mine: Vec<shapes::Shape> = mine.iter().map(build_shape).collect::<PyResult<_>>()?;
        let skip: IdSet = skip.into_iter().collect();
        let board: Option<IdSet> = board.map(|b| b.into_iter().collect());
        let proto = match &tail {
            Some((t, _, _, _)) => Some(build_shape(t)?),
            None => None,
        };
        let m = giveway::Move {
            via: &via,
            mine: &mine,
            centre,
            first: first.as_ref().map(|(p, c, r)| (p.as_slice(), *c, *r)),
            pad: pad.as_ref().map(|(p, r)| (p.as_slice(), *r)),
            tail: match (&proto, &tail) {
                (Some(p), Some((_, far, w, cap))) => Some((p, *far, *w, *cap)),
                _ => None,
            },
            board: board.as_ref(),
        };
        Ok(giveway::first_move(&self.grid, &self.cfg, &m, &offsets, clearance, &skip, start))
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

/// The (x, y, turn) triples `placer.scan`'s own `seen` Python set used to
/// dedupe across a scan's several passes (coarse, half-coarse, fine round
/// each refined candidate) - kept here instead, one instance per scan
/// (`Occupancy.native_sweeper` builds one `NativeSweeper` per `scan()`
/// call, which owns one of these), so the loop that builds triples from
/// `points x rots` runs in Rust once per pass instead of once per
/// (point, rotation) pair in Python. Coordinates are compared by exact bit
/// pattern (`f64::to_bits`), matching Python's own `(x, y, rot) in seen`
/// set-membership exactly: `placer._grid`'s `round(v, 6)` is deterministic,
/// so the same conceptual point always produces the same bits, from
/// whichever pass reaches it first.
#[pyclass]
#[derive(Default)]
struct NativeSweepSeen {
    seen: HashSet<(u64, u64, usize), BuildHasherDefault<ratsnest::Fx>>,
}

thread_local! {
    /// `placer._grid_offsets`' own cache (it keeps sixteen), by the bits of (radius, step).
    static GRID_OFFSETS: std::cell::RefCell<HashMap<(u64, u64), std::rc::Rc<Vec<(f64, f64, f64)>>>> =
        std::cell::RefCell::new(HashMap::new());
}

/// `placer._grid_offsets(radius, step)`: (d, dx, dy) within `radius` on a `step` grid, nearest first.
fn grid_offsets(radius: f64, step: f64) -> std::rc::Rc<Vec<(f64, f64, f64)>> {
    let key = (radius.to_bits(), step.to_bits());
    if let Some(hit) = GRID_OFFSETS.with(|c| c.borrow().get(&key).cloned()) {
        return hit;
    }
    let n = (radius / step + 1e-9).floor() as i64;
    let mut pts = Vec::new();
    for i in -n..=n {
        for j in -n..=n {
            let (dx, dy) = (i as f64 * step, j as f64 * step);
            let d = exact::hypot(dx, dy);
            if d <= radius + 1e-9 {
                pts.push((d, dx, dy));
            }
        }
    }
    pts.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let pts = std::rc::Rc::new(pts);
    GRID_OFFSETS.with(|c| {
        let mut c = c.borrow_mut();
        if c.len() >= 16 {
            c.clear();
        }
        c.insert(key, pts.clone());
    });
    pts
}

#[pymethods]
impl NativeSweepSeen {
    #[new]
    fn new() -> Self {
        NativeSweepSeen::default()
    }

    /// `expand` for the points of `placer._grid(Location(cx, cy), radius, step)`, in its order, those within
    /// `around` = (x, y, r) of its point when that is given (`hypot <= r + 1e-9`): the lattice is made here, not
    /// in Python and handed over a point at a time.
    #[pyo3(signature = (cx, cy, radius, step, n_rots, around=None))]
    fn expand_grid(&mut self, cx: f64, cy: f64, radius: f64, step: f64, n_rots: usize, around: Option<(f64, f64, f64)>)
        -> Vec<(f64, f64, usize)> {
        let offsets = grid_offsets(radius, step);
        let mut out = Vec::new();
        for &(_, dx, dy) in offsets.iter() {
            let (x, y) = (exact::round6(cx + dx), exact::round6(cy + dy));
            if let Some((hx, hy, r)) = around {
                if !(exact::hypot(x - hx, y - hy) <= r + 1e-9) {
                    continue;
                }
            }
            let (kx, ky) = (x.to_bits(), y.to_bits());
            for turn in 0..n_rots {
                if self.seen.insert((kx, ky, turn)) {
                    out.push((x, y, turn));
                }
            }
        }
        out
    }

    /// (x, y, turn) triples for every (x, y) in `points` at every turn in
    /// 0..n_rots not already returned by an earlier call on this instance.
    fn expand(&mut self, points: Vec<(f64, f64)>, n_rots: usize) -> Vec<(f64, f64, usize)> {
        let mut out = Vec::new();
        for (x, y) in points {
            let kx = x.to_bits();
            let ky = y.to_bits();
            for turn in 0..n_rots {
                if self.seen.insert((kx, ky, turn)) {
                    out.push((x, y, turn));
                }
            }
        }
        out
    }
}

#[cfg(test)]
mod sweep_seen_tests {
    use super::NativeSweepSeen;

    #[test]
    fn expand_skips_what_was_already_returned() {
        let mut s = NativeSweepSeen::default();
        let first = s.expand(vec![(1.0, 2.0), (3.0, 4.0)], 2);
        assert_eq!(first, vec![(1.0, 2.0, 0), (1.0, 2.0, 1), (3.0, 4.0, 0), (3.0, 4.0, 1)]);
        let second = s.expand(vec![(1.0, 2.0), (5.0, 6.0)], 2);
        // (1.0, 2.0) at both turns already seen; (5.0, 6.0) is new.
        assert_eq!(second, vec![(5.0, 6.0, 0), (5.0, 6.0, 1)]);
    }
}

/// `cutouts.loop_gap`: the shortest distance between two closed loops (native/src/cutouts.rs).
#[pyfunction]
fn loop_gap(a: Vec<Point>, b: Vec<Point>) -> f64 {
    cutouts::loop_gap(&a, &b)
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

/// `round(v, 6)` on each value, for comparing against Python in bulk.
#[pyfunction]
fn round6_many(values: Vec<f64>) -> Vec<f64> {
    values.into_iter().map(exact::round6).collect()
}

/// `geometry.transform_polygon(poly, t)` with its rounding: each vertex as `Transform.apply` takes it,
/// `a x + b y + tx` and `c x + d y + ty` in that order, each side through `_clean`.
#[pyfunction]
fn transform_polygon(poly: Vec<(f64, f64)>, a: f64, b: f64, c: f64, d: f64, tx: f64, ty: f64) -> Vec<(f64, f64)> {
    poly.into_iter()
        .map(|(x, y)| (exact::clean9(a * x + b * y + tx), exact::clean9(c * x + d * y + ty)))
        .collect()
}

/// `math.hypot` on each pair, for comparing against Python in bulk.
#[pyfunction]
fn hypot_many(xs: Vec<f64>, ys: Vec<f64>) -> Vec<f64> {
    xs.into_iter().zip(ys).map(|(a, b)| exact::hypot(a, b)).collect()
}

/// `checks.py`'s `_Fill`, in Rust - see `fill` module doc. `_Fill` keeps
/// `x0`/`y0`/`s`/`nx`/`ny`/`sq`/`levels` in Python (read once, at
/// construction) for its own neck-selection code in `width()`, which
/// stays Python; `touching`/`reach`/`centre`/`radius` are asked of this
/// object each time.
#[pyclass]
struct NativeFill {
    inner: fill::Fill,
}

#[pymethods]
impl NativeFill {
    #[new]
    fn new(poly: Vec<Point>, step: f64) -> Self {
        NativeFill { inner: fill::Fill::new(&poly, step) }
    }

    #[getter]
    fn x0(&self) -> f64 {
        self.inner.x0
    }

    #[getter]
    fn y0(&self) -> f64 {
        self.inner.y0
    }

    #[getter]
    fn s(&self) -> f64 {
        self.inner.s
    }

    #[getter]
    fn nx(&self) -> usize {
        self.inner.nx
    }

    #[getter]
    fn ny(&self) -> usize {
        self.inner.ny
    }

    #[getter]
    fn sq(&self) -> Vec<f64> {
        self.inner.sq.clone()
    }

    #[getter]
    fn levels(&self) -> Vec<f64> {
        self.inner.levels.clone()
    }

    fn centre(&self, c: usize) -> Point {
        self.inner.centre(c)
    }

    fn radius(&self, tau: f64) -> f64 {
        self.inner.radius(tau)
    }

    /// `polys_id`: an integer the Python `_Fill` assigns per distinct
    /// `entry`/`exit_` tuple it calls `touching` with (their `id()`, same
    /// as `checks.py`'s own `_Fill._copper_distance` cache key, kept alive
    /// by a Python-side reference so an id can never be reused within one
    /// `_Fill`'s lifetime) - `polys` is only needed (and only rasterised)
    /// the FIRST time a given id is seen by this `NativeFill` instance.
    fn touching(&mut self, polys_id: usize, polys: Option<Vec<Vec<Point>>>, tau: f64) -> Vec<usize> {
        self.inner.touching(polys_id, polys.as_deref(), tau)
    }

    /// `checks._Fill._reach`'s own contract: (the goal cell reached, or
    /// None, the BFS's parent map). The parent map comes back as a
    /// `NativeReach`, not a plain dict: `width()`'s own code only ever
    /// asks it `c in parent`, `parent[c]` (walking a short chain back from
    /// the hit) or iterates its keys (the "no path at all" branch) - never
    /// its values in bulk - and a fill with a wide, mostly-open pour can
    /// have a BFS visit hundreds of thousands of cells before reaching a
    /// distant goal (or none, when `goal` is empty - `width()`'s own
    /// `from_entry`/`from_exit` calls, which want reachability alone).
    /// Marshalling that whole map into a Python dict, one key and value
    /// each crossing the FFI boundary as their own object, cost far more
    /// than the search itself; `NativeReach` keeps it in Rust and answers
    /// those three operations directly.
    fn reach(&self, start: Vec<usize>, goal: Vec<usize>, tau: f64) -> (Option<usize>, NativeReach) {
        let (hit, parent, order) = self.inner.reach(&start, &goal, tau);
        (hit, NativeReach { parent, order })
    }
}

/// The parent map `NativeFill::reach` hands back - see that method's own
/// doc for why it is not a plain Python dict. `order` is the cells in the
/// order the BFS gained them (`start` first, in `start`'s own order, then
/// discovery order) - a Rust `HashMap`'s own iteration order is
/// unrelated to insertion order (and, with Rust's default hasher,
/// randomised per process), where a Python dict's is always insertion
/// order; `__iter__` must answer with the latter, since `width()`'s "no
/// path at all" branch breaks a tie in `min(seen, key=...)` by picking
/// whichever `seen` iterates first.
#[pyclass]
struct NativeReach {
    parent: HashMap<usize, Option<usize>>,
    order: Vec<usize>,
}

#[pymethods]
impl NativeReach {
    fn __contains__(&self, key: usize) -> bool {
        self.parent.contains_key(&key)
    }

    fn __getitem__(&self, key: usize) -> PyResult<Option<usize>> {
        self.parent.get(&key).copied().ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(key))
    }

    fn __len__(&self) -> usize {
        self.parent.len()
    }

    fn __iter__(&self) -> NativeReachKeys {
        NativeReachKeys { keys: self.order.clone().into_iter() }
    }
}

/// `iter(a NativeReach)`: its keys, one Rust `Vec` built once rather than
/// a Python object per key up front - `width()`'s own "no path at all"
/// branch only ever walks this once, with `min(seen, key=...)`.
#[pyclass]
struct NativeReachKeys {
    keys: std::vec::IntoIter<usize>,
}

#[pymethods]
impl NativeReachKeys {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> Option<usize> {
        slf.keys.next()
    }
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
    #[pyo3(signature = (poly, raster=None, courtyard=false))]
    fn add_reservation(&mut self, poly: Vec<Point>, raster: Option<(f64, f64, f64, i64, i64, Vec<Vec<u8>>)>, courtyard: bool) {
        let raster = raster.map(|(x0, y0, cell, nx, ny, state)| board::Raster { x0, y0, cell, nx, ny, state });
        self.reservations.push(board::Reservation::new(poly, raster, courtyard));
    }

    fn reservation_count(&self) -> usize {
        self.reservations.len()
    }

    /// The edge verdict for one body box (tests): 0 allowed, else the code.
    #[pyo3(signature = (body, flat=false))]
    fn edge(&self, body: PyBox, flat: bool) -> u8 {
        let b = bx(body);
        (if flat { self.keepin.why_not_flat(&b) } else { self.keepin.why_not(&b) }).unwrap_or(0)
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
/// a = its code (plus `COPPER_EDGE` when it is the copper's, judged at the
/// keep-in; a courtyard or body is judged against the edge itself), 1 a reservation with a = its index, 2 a conflict with
/// a = the turn << 32 | the candidate's shape in that turn's list, and
/// b = the obstacle). With `stop_at_first`
/// it stops at the first legal candidate. `judged`, beside `parts`: for
/// each reservation in `reservations` order, the indexes of the parts it
/// judges (a cell's members it does not let in, and its own copper, as
/// `Occupancy.judged` gives them); without it every part is judged.
/// `edges` (per turn) and `edge_parts` (per turn, beside `parts`) are what
/// the edge judges, as `Occupancy._item_edge_why` does: the courtyard and
/// body box, and the copper's box or None for no copper.
#[pyfunction]
#[pyo3(signature = (board, reservations, obstacles, origins, bodies, edges, points, clearance, stop_at_first, scoring=None, parts=None, judged=None, edge_parts=None, yards=None))]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn sweep(
    py: Python<'_>,
    board: &NativeBoard,
    reservations: Vec<usize>,
    obstacles: &NativeObstacles,
    origins: Vec<PyRef<'_, NativeOriginShapes>>,
    bodies: Vec<PyBox>,
    edges: Vec<(PyBox, Option<PyBox>)>,
    points: Vec<(f64, f64, usize)>,
    clearance: Option<f64>,
    stop_at_first: bool,
    scoring: Option<Bound<'_, PyAny>>,
    parts: Option<Vec<Vec<PyBox>>>,
    judged: Option<Vec<Vec<usize>>>,
    edge_parts: Option<Vec<Vec<(PyBox, Option<PyBox>)>>>,
    yards: Option<Vec<Vec<Option<Vec<Point>>>>>,
) -> PyResult<(Vec<usize>, Vec<f64>, Vec<(u8, i64, i64, usize, usize)>)> {
    let yards = yards.unwrap_or_default();
    let parts = parts.unwrap_or_default();
    let edge_parts = edge_parts.unwrap_or_default();
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
    let turn_yards: Vec<judge::TurnYards> = yards.iter().map(|y| judge::TurnYards::new(y)).collect();
    // per turn, a box holding the item's body, parts and courtyards at the origin; and, past them, every place
    // a candidate's boxes and courtyards can be: the reservations clear of it are never asked
    let hulls: Vec<board::B> = (0..bodies.len()).map(|t| {
        let mut h = bx(bodies[t]);
        for p in parts.get(t).map(|v| v.as_slice()).unwrap_or(&[]) {
            h = judge::hull(&h, &bx(*p));
        }
        for yb in turn_yards.get(t).map(|y| y.boxes.as_slice()).unwrap_or(&[]).iter().flatten() {
            h = judge::hull(&h, yb);
        }
        h
    }).collect();
    let reach = match (hulls.iter().copied().reduce(|a, b| judge::hull(&a, &b)), points.first()) {
        (Some(h), Some(&(x0, y0, _))) => {
            let (mut lx, mut ly, mut hx, mut hy) = (x0, y0, x0, y0);
            for &(x, y, _) in &points {
                lx = lx.min(x); ly = ly.min(y); hx = hx.max(x); hy = hy.max(y);
            }
            Some(board::B { l: lx + h.l, t: ly + h.t, r: hx + h.r, b: hy + h.b })
        }
        _ => None,
    };
    let mut drawn: Vec<Vec<shapes::Shape>> = origins.iter().map(|o| o.shapes.clone()).collect();
    let mut pass = judge::ReservationPass::new(&board.reservations, &reservations, judged.as_ref(), &turn_yards, &hulls, reach);
    let part_boxes: Vec<Vec<board::B>> = parts.iter().map(|ps| ps.iter().map(|p| bx(*p)).collect()).collect();
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
        let t_all = profile::mark();
        let o = bodies[turn];
        let body = board::B {
            l: exact::clean9(o.0 + x),
            t: exact::clean9(o.1 + y),
            r: exact::clean9(o.2 + x),
            b: exact::clean9(o.3 + y),
        };
        // A cell whose box fails is judged again by its members' boxes
        // (`Occupancy._edge_or_reservation_conflict`); b names the member
        // whose box the edge refused, 1-based, or 0 for the whole box.
        let has_members = parts.get(turn).is_some_and(|ps| !ps.is_empty());
        let shift = |p: PyBox| board::B {
            l: exact::clean9(p.0 + x),
            t: exact::clean9(p.1 + y),
            r: exact::clean9(p.2 + x),
            b: exact::clean9(p.3 + y),
        };
        let (flat, copper) = edges[turn];
        let member_edges: &[(PyBox, Option<PyBox>)] = match edge_parts.get(turn) {
            Some(ps) if has_members => ps,
            _ => &[],
        };
        profile::add(0, t_all);
        let t_edge = profile::mark();
        let mut edge_hit: Option<(u8, usize)> = None;
        if let Some(code) = board.keepin.why_not_flat(&shift(flat)) {
            edge_hit = if member_edges.is_empty() {
                Some((code, 0usize))
            } else {
                member_edges.iter().enumerate()
                    .find_map(|(k, m)| board.keepin.why_not_flat(&shift(m.0)).map(|c| (c, k + 1)))
            };
        }
        if edge_hit.is_none() {
            if let Some(cb) = copper {
                if let Some(code) = board.keepin.why_not(&shift(cb)) {
                    edge_hit = if member_edges.is_empty() {
                        Some((code | board::COPPER_EDGE, 0usize))
                    } else {
                        member_edges.iter().enumerate().find_map(|(k, m)| {
                            m.1.and_then(|c| board.keepin.why_not(&shift(c)).map(|c| (c | board::COPPER_EDGE, k + 1)))
                        })
                    };
                }
            }
        }
        profile::add(1, t_edge);
        if let Some((code, k)) = edge_hit {
            profile::add(6, t_all);
            refuse((0, code as i64, k as i64), idx, &mut refused);
            continue;
        }
        // b: the part the reservation refuses, 1-based (a cell's member or its own copper, in
        // `Occupancy.judged` order); 0 for an item with no parts
        let t_res = profile::mark();
        let rh = pass.hit(turn, &body, part_boxes.get(turn).map(|v| v.as_slice()).unwrap_or(&[]), x, y);
        profile::add(3, t_res);
        if let Some((ri, k)) = rh {
            profile::add(7, t_all);
            refuse((1, ri as i64, k as i64), idx, &mut refused);
            continue;
        }
        let t_obs = profile::mark();
        let conflict = obstacles.grid.first_conflict_shifted_in(&origins[turn].shapes, &mut drawn[turn], x, y, clearance, &obstacles.cfg);
        match conflict {
            Some((si, oi)) => { profile::add(4, t_obs); profile::add(8, t_all); refuse((2, ((turn as i64) << 32) | si as i64, oi as i64), idx, &mut refused) },
            None => {
                profile::add(4, t_obs);
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

    /// The differential pairs, (net, partner) both ways: a crossing between a
    /// pair's two halves counts `pair_weight` (ratsnest._crossing_weight).
    fn set_partners(&mut self, pairs: Vec<(String, String)>, pair_weight: f64) {
        self.inner.set_partners(&pairs, pair_weight);
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
    m.add_function(wrap_pyfunction!(profile::sweep_profile, m)?)?;
    m.add_function(wrap_pyfunction!(polys_overlap, m)?)?;
    m.add_function(wrap_pyfunction!(poly_distance, m)?)?;
    m.add_function(wrap_pyfunction!(point_segment_distance, m)?)?;
    m.add_function(wrap_pyfunction!(conflict, m)?)?;
    m.add_function(wrap_pyfunction!(largest_rectangle, m)?)?;
    m.add_function(wrap_pyfunction!(hypot, m)?)?;
    m.add_function(wrap_pyfunction!(loop_gap, m)?)?;
    m.add_function(wrap_pyfunction!(mst, m)?)?;
    m.add_function(wrap_pyfunction!(clean9_many, m)?)?;
    m.add_function(wrap_pyfunction!(round6_many, m)?)?;
    m.add_function(wrap_pyfunction!(transform_polygon, m)?)?;
    m.add_function(wrap_pyfunction!(hypot_many, m)?)?;
    m.add_class::<NativeFill>()?;
    m.add_class::<NativeReach>()?;
    m.add_class::<NativeReachKeys>()?;
    m.add_class::<NativeObstacles>()?;
    m.add_class::<NativeOriginShapes>()?;
    m.add_class::<NativeSweepSeen>()?;
    m.add_class::<NativeBoard>()?;
    m.add_class::<NativeRatsnest>()?;
    m.add_class::<NativeEscTurn>()?;
    m.add_class::<NativeScoring>()?;
    m.add_class::<NativeCleanupScoring>()?;
    m.add_function(wrap_pyfunction!(sweep, m)?)?;
    Ok(())
}
