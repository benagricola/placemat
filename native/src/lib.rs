//! `placemat_native`: an optional accelerator for placemat's geometry hot
//! path. Imported by `placemat.geometry` when present; every function here
//! has a pure-Python reference implementation that stays the source of
//! truth for behaviour (see docs/superpowers/specs/2026-09-24-native-core-design.md).

mod geometry;

use pyo3::prelude::*;

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

#[pymodule]
fn placemat_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(polys_overlap, m)?)?;
    m.add_function(wrap_pyfunction!(poly_distance, m)?)?;
    m.add_function(wrap_pyfunction!(point_segment_distance, m)?)?;
    Ok(())
}
