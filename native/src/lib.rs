//! `placemat_native`: an optional accelerator for placemat's geometry hot
//! path. Imported by `placemat.geometry` when present; every function here
//! has a pure-Python reference implementation that stays the source of
//! truth for behaviour (see docs/superpowers/specs/2026-09-24-native-core-design.md).

mod geometry;
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

/// A `shapes::Shape` as a plain tuple, for tests to build from Python
/// without going through `Occupancy` at all: (kind, faces, layers, net,
/// poly, owner_is_footprint). `faces` bit 0 = front, bit 1 = back; `layers`
/// a bitmask (only its zero-ness matters to `conflict`, so any nonzero
/// value works in a test that never mixes it with a real layer set).
type PyShape = (String, u8, u32, String, Vec<Point>, bool);

fn build_shape(t: &PyShape) -> PyResult<shapes::Shape> {
    let (kind_s, faces, layers, net, poly, owner_is_footprint) = t;
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
        owner_is_footprint: *owner_is_footprint,
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
}

#[pymodule]
fn placemat_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(polys_overlap, m)?)?;
    m.add_function(wrap_pyfunction!(poly_distance, m)?)?;
    m.add_function(wrap_pyfunction!(point_segment_distance, m)?)?;
    m.add_function(wrap_pyfunction!(conflict, m)?)?;
    m.add_class::<NativeObstacles>()?;
    Ok(())
}
