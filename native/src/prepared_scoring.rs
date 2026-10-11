//! Complete common-objective candidate scoring inside the native sweep.
//! `floor` is the incumbent record. With `configure_prune`, a candidate is
//! pruned when its exact terms so far plus proved lower bounds of the rest
//! exceed the `keep`-th best weighed cost (R13): it cannot be among the
//! `keep` best, so no scan that reads only that many is changed.
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
    prune: Option<Prune>,
    #[pyo3(get)]
    pruned: u64,
}

type Bounds = (f64, f64, f64, f64);

// The proved lower bounds of a lifted snapshot's candidates (`configure_prune`).
struct Prune {
    keep: usize,
    kept: Vec<f64>,
    congestion: f64,
    constant: f64,
    // a rest pad whose price may fall: net, centre, squared distance to its target now, price, box
    pads: Vec<(String, (f64, f64), f64, f64, Bounds)>,
    boxes: Vec<Bounds>,
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
        Ok(Self { candidate, delta, surface, weights, baseline, floor, prune: None, pruned: 0 })
    }

    /// Prune on proved bounds (R13). `keep`: how many of the best weighed candidates the scan reads, so a candidate
    /// is weighed in full while fewer than that are known. `congestion`: the least the congestion term can be (minus
    /// its price times the lifted board's worst steps). `constant`: the least the rest pads' escape prices can change
    /// by whatever stands where (a via pad that a candidate's copper turns into a closed one, when a via costs more).
    /// `pads`: the rest pads on the item's nets that hold a price, each as (net, centre, squared distance to its
    /// target, price, box): its price can fall only when a candidate anchor of its net comes as near as its target
    /// or the candidate's box (`boxes`, per turn at the origin) overlaps it.
    #[allow(clippy::type_complexity)]
    fn configure_prune(&mut self, keep: usize, congestion: f64, constant: f64,
                       pads: Vec<(String, (f64, f64), f64, f64, Bounds)>, boxes: Vec<Bounds>) -> PyResult<()> {
        if keep == 0 || !congestion.is_finite() || congestion > 0.0 || !constant.is_finite() || constant > 0.0
            || pads.iter().any(|p| !p.2.is_finite() || p.2 < 0.0 || !p.3.is_finite() || p.3 < 0.0)
            || boxes.iter().any(|b| ![b.0, b.1, b.2, b.3].iter().all(|v| v.is_finite())) {
            return Err(PyValueError::new_err("invalid prune bounds"));
        }
        self.prune = Some(Prune { keep, kept: Vec::new(), congestion, constant, pads, boxes });
        Ok(())
    }

    /// A new scan: the best weighed costs it prunes by are its own (`keep` is how many of its best it reads).
    fn begin_scan(&mut self) {
        if let Some(prune) = self.prune.as_mut() {
            prune.kept.clear();
        }
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
        let limit = self.prune.as_ref().and_then(|p| p.kept.get(p.keep - 1).copied());
        let (raw, crossed, vias, closed, walled) = if let Some(limit) = limit {
            // Stage by stage, R13: wire, crossings, escaped crossings, link and area exact; then congestion
            // exact; the escape prices' bound throughout. A candidate past the limit stands below every one
            // weighed in full.
            let tolerance = 1e-9 * limit.abs().max(1.0);
            let (wire, cross) = delta.inner.wire_cross(x, y, turn).map_err(PyValueError::new_err)?;
            let crossed = delta.inner.escape_cross(turn, surface.depth()).map_err(PyValueError::new_err)?;
            let prune = self.prune.as_ref().unwrap();
            let shift = prune.boxes.get(turn).map(|b| (b.0 + x, b.1 + y, b.2 + x, b.3 + y))
                .ok_or_else(|| PyValueError::new_err("prune turn invalid"))?;
            let mut escapes = prune.constant;
            for (net, at, d2, price, b) in &prune.pads {
                if (b.0 <= shift.2 && shift.0 <= b.2 && b.1 <= shift.3 && shift.1 <= b.3)
                    || delta.inner.candidate_within(turn, net, *at, *d2, x, y) {
                    escapes -= price;
                }
            }
            let layout = delta.layout.as_mut()
                .ok_or_else(|| PyValueError::new_err("prepared surface layout is not configured"))?;
            let (link, over, area) = layout.plain_terms(x, y, turn).map_err(PyValueError::new_err)?;
            let exact = wire + cross + link + over + area + self.weights.0 * crossed as f64;
            if exact + prune.congestion + escapes > limit + tolerance {
                self.pruned += 1;
                return Ok((exact + prune.congestion + escapes, i64::MAX));
            }
            let congestion = layout.congestion_term(x, y, turn).map_err(PyValueError::new_err)?;
            let bound = exact + congestion + escapes;
            if bound > limit + tolerance {
                self.pruned += 1;
                return Ok((bound, i64::MAX));
            }
            let (vias, closed, walled) = surface.escape_counts(py, candidate, delta, x, y, turn)?;
            ((wire, cross, link, over, area, congestion), crossed, vias, closed, walled)
        } else {
            let (raw, crossed, vias, closed, walled, _, _) =
                surface.evaluate_inner(py, candidate, delta, x, y, turn, false)?;
            (raw, crossed, vias, closed, walled)
        };
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
            if let Some(prune) = self.prune.as_mut() {
                let at = prune.kept.partition_point(|&k| k <= cost);
                if at < prune.keep {
                    prune.kept.insert(at, cost);
                    prune.kept.truncate(prune.keep);
                }
            }
        }
        Ok((cost, walled as i64))
    }
}
