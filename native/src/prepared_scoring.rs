//! Complete common-objective candidate scoring inside the native sweep.
//! Signed terms are evaluated exhaustively; floor is an incumbent record,
//! never a wire-only pruning bound.
use crate::candidate::PreparedCandidate;
use crate::prepared_surface::PreparedSurface;
use crate::NativeDelta;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyclass]
pub struct NativeDeltaScoring {
    pub(crate) candidate: Py<PreparedCandidate>,
    pub(crate) delta: Py<NativeDelta>,
    pub(crate) surface: Py<PreparedSurface>,
    weights: (f64, f64, f64),
    baseline: (usize, usize),
    #[pyo3(get, set)]
    pub(crate) floor: f64,
}

#[pymethods]
impl NativeDeltaScoring {
    #[new]
    fn new(candidate: Py<PreparedCandidate>, delta: Py<NativeDelta>, surface: Py<PreparedSurface>,
           weights: (f64, f64, f64), baseline: (usize, usize), floor: f64) -> PyResult<Self> {
        if [weights.0, weights.1, weights.2].iter().any(|w| !w.is_finite() || *w < 0.0)
            || floor.is_nan() {
            return Err(PyValueError::new_err("invalid common-objective weights or floor"));
        }
        Ok(Self { candidate, delta, surface, weights, baseline, floor })
    }

    fn evaluate(&mut self, py: Python<'_>, x: f64, y: f64, turn: usize) -> PyResult<(f64, i64)> {
        // Inspection entry point; production sweep borrows these handles once.
        let candidate = self.candidate.clone_ref(py);
        let delta = self.delta.clone_ref(py);
        let surface = self.surface.clone_ref(py);
        self.score(py, &mut candidate.borrow_mut(py), &mut delta.borrow_mut(py),
                   &mut surface.borrow_mut(py), x, y, turn)
    }
}

impl NativeDeltaScoring {
    pub(crate) fn score(&mut self, py: Python<'_>, candidate: &mut PreparedCandidate,
                       delta: &mut NativeDelta, surface: &mut PreparedSurface,
                       x: f64, y: f64, turn: usize) -> PyResult<(f64, i64)> {
        let (raw, crossed, vias, closed, walled, _, _) =
            surface.evaluate_inner(py, candidate, delta, x, y, turn, false)?;
        let mut total = crate::exact::PySum::new();
        // Keep the Python Delta term insertion order, including zero push.
        for value in [raw.0, raw.1, raw.2, raw.3, 0.0, 0.0, raw.4, raw.5,
                      self.weights.0 * crossed as f64,
                      self.weights.1 * (closed as f64 - self.baseline.0 as f64),
                      self.weights.2 * (vias as f64 - self.baseline.1 as f64)] {
            total.add(value);
        }
        let cost = total.total();
        if walled == 0 {
            self.floor = self.floor.min(cost);
        }
        Ok((cost, walled as i64))
    }
}
