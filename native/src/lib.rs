//! `placemat_native`: an optional accelerator for placemat's geometry hot
//! path. Imported by `placemat.geometry` when present; every function here
//! has a pure-Python reference implementation that stays the source of
//! truth for behaviour (see docs/superpowers/specs/2026-09-24-native-core-design.md).

mod exact;
mod geometry;
mod pockets;
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

#[pymodule]
fn placemat_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("PLACEMAT_VERSION"))?;      // the release (git tag) it was built from: build.rs
    m.add_function(wrap_pyfunction!(polys_overlap, m)?)?;
    m.add_function(wrap_pyfunction!(poly_distance, m)?)?;
    m.add_function(wrap_pyfunction!(point_segment_distance, m)?)?;
    m.add_function(wrap_pyfunction!(conflict, m)?)?;
    m.add_function(wrap_pyfunction!(largest_rectangle, m)?)?;
    m.add_function(wrap_pyfunction!(hypot, m)?)?;
    m.add_function(wrap_pyfunction!(clean9_many, m)?)?;
    m.add_function(wrap_pyfunction!(hypot_many, m)?)?;
    m.add_class::<NativeObstacles>()?;
    m.add_class::<NativeOriginShapes>()?;
    Ok(())
}
