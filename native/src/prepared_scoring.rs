//! Complete common-objective candidate scoring inside the native sweep.
//!
//! With `escapes` off (the one-score search's scan, D25) a candidate is scored on every term but the escape grades
//! (`escape_via`, `escape_closed`) and the walled check: its partial cost stands at (cost, `PARTIAL`), and the scan
//! asks `full` of the best few by it. With `escapes` on (the default, and an explore's draw, which reads every
//! candidate) every candidate is scored in full. `floor` is the incumbent record of a candidate scored in full that
//! walls none. With `configure_prune` (partial scoring only), a candidate is pruned when its exact terms so far plus a
//! proved lower bound of congestion exceed the `keep`-th best partial cost (R13): it stands at (that bound,
//! `UNWEIGHED`), and the scan weighs it if its walk reaches it.
use crate::candidate::PreparedCandidate;
use crate::prepared_surface::PreparedSurface;
use crate::NativeDelta;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// A candidate scored on every term but the escape grades and the walled check: below a pruned one (`UNWEIGHED`),
/// above every count of pads walled. `placer.PARTIAL`.
const PARTIAL: i64 = i64::MAX - 1;

#[pyclass]
pub struct NativeDeltaScoring {
    pub(crate) candidate: Py<PreparedCandidate>,
    pub(crate) delta: Py<NativeDelta>,
    pub(crate) surface: Py<PreparedSurface>,
    weights: (f64, f64, f64),
    baseline: (usize, usize),
    #[pyo3(get, set)]
    pub(crate) floor: f64,
    // whether the sweep scores each candidate's escape grades and walled check
    #[pyo3(get, set)]
    escapes: bool,
    prune: Option<Prune>,
    #[pyo3(get)]
    pruned: u64,
    // how many candidates were given the escape grades: the sweep's in full and `full`'s
    #[pyo3(get)]
    escaped: u64,
    // the sweep's turn k is this scorer's turn `turn_map[k]` (a scan of some of the turns it was prepared for)
    turn_map: Option<Vec<usize>>,
}

// The proved lower bound of a lifted snapshot's partial costs (`configure_prune`).
struct Prune {
    keep: usize,
    kept: Vec<f64>,
    congestion: f64,
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
        Ok(Self { candidate, delta, surface, weights, baseline, floor, escapes: true, prune: None, pruned: 0,
                  escaped: 0, turn_map: None })
    }

    /// Prune partial costs on a proved bound (R13). `keep`: how many of the best partial costs the scan's walk
    /// takes at the least (`place.escape_spots`), so a candidate is scored while fewer than that are known.
    /// `congestion`: the least the congestion term can be (minus its price times the lifted board's worst steps).
    fn configure_prune(&mut self, keep: usize, congestion: f64) -> PyResult<()> {
        if keep == 0 || !congestion.is_finite() || congestion > 0.0 {
            return Err(PyValueError::new_err("invalid prune bounds"));
        }
        self.prune = Some(Prune { keep, kept: Vec::new(), congestion });
        Ok(())
    }

    /// Which of its turns a sweep's turns are: the sweep's turn k is turn `map[k]`; None, the same turns. `evaluate`,
    /// `full` and `partial_cost` take this scorer's own turns.
    #[pyo3(signature = (map=None))]
    fn set_turn_map(&mut self, map: Option<Vec<usize>>) {
        self.turn_map = map;
    }

    /// A new scan: the best partial costs it prunes by are its own.
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
        let map = self.turn_map.take();
        let result = self.score(py, &mut candidate.borrow_mut(py), &mut delta.borrow_mut(py),
                                &mut surface.borrow_mut(py), x, y, turn);
        self.turn_map = map;
        result
    }

    /// The partial cost of one candidate (every term but the escape grades and the walled check), never pruned:
    /// what a scan's walk asks of a pruned candidate it reaches. Neither `floor` nor the pruning bounds move.
    fn partial_cost(&mut self, py: Python<'_>, x: f64, y: f64, turn: usize) -> PyResult<f64> {
        let candidate = self.candidate.clone_ref(py);
        let delta = self.delta.clone_ref(py);
        let surface = self.surface.clone_ref(py);
        let (cost, _) = self.partial(&mut delta.borrow_mut(py), &surface.borrow(py), &candidate.borrow(py),
                                     x, y, turn, false)?;
        Ok(cost)
    }

    /// (cost, walled) of one candidate scored in full, escape grades and walled check included, whatever `escapes`
    /// says. Neither `floor` nor the pruning bounds move.
    fn full(&mut self, py: Python<'_>, x: f64, y: f64, turn: usize) -> PyResult<(f64, i64)> {
        let candidate = self.candidate.clone_ref(py);
        let delta = self.delta.clone_ref(py);
        let surface = self.surface.clone_ref(py);
        let (raw, crossed, vias, closed, walled, _, _) = surface.borrow_mut(py).evaluate_inner(
            py, &mut candidate.borrow_mut(py), &mut delta.borrow_mut(py), x, y, turn, false)?;
        self.escaped += 1;
        Ok((self.total(raw, crossed, vias, closed), walled as i64))
    }
}

impl NativeDeltaScoring {
    pub(crate) fn score(&mut self, py: Python<'_>, candidate: &mut PreparedCandidate,
                       delta: &mut NativeDelta, surface: &mut PreparedSurface,
                       x: f64, y: f64, turn: usize) -> PyResult<(f64, i64)> {
        let turn = match &self.turn_map {
            Some(map) => *map.get(turn).ok_or_else(|| PyValueError::new_err("sweep turn outside the turn map"))?,
            None => turn,
        };
        if !self.escapes {
            return self.partial(delta, surface, candidate, x, y, turn, true);
        }
        let (raw, crossed, vias, closed, walled, _, _) =
            surface.evaluate_inner(py, candidate, delta, x, y, turn, false)?;
        self.escaped += 1;
        let cost = self.total(raw, crossed, vias, closed);
        if walled == 0 {
            self.floor = self.floor.min(cost);
        }
        Ok((cost, walled as i64))
    }

    /// Every term but the escape grades and the walled check, in the Python Delta's order: wire, crossings, link,
    /// link over, area, congestion, escaped crossings. The candidate's shapes are not placed: only the escape grades
    /// read them. `prune`: the pruning bounds apply and move.
    #[allow(clippy::too_many_arguments)]
    fn partial(&mut self, delta: &mut NativeDelta, surface: &PreparedSurface, candidate: &PreparedCandidate,
               x: f64, y: f64, turn: usize, prune: bool) -> PyResult<(f64, i64)> {
        surface.check(candidate, delta)?;
        let layout = delta.layout.as_ref()
            .ok_or_else(|| PyValueError::new_err("prepared surface layout is not configured"))?;
        layout.check_congestion(x, y, turn).map_err(PyValueError::new_err)?;
        let (wire, cross) = delta.inner.wire_cross(x, y, turn).map_err(PyValueError::new_err)?;
        let crossed = delta.inner.escape_cross(turn, surface.depth()).map_err(PyValueError::new_err)?;
        let layout = delta.layout.as_mut().unwrap();
        let (link, over, area) = layout.plain_terms(x, y, turn).map_err(PyValueError::new_err)?;
        let limit = self.prune.as_ref().filter(|_| prune).and_then(|p| p.kept.get(p.keep - 1).copied());
        if let (Some(limit), Some(prune)) = (limit, self.prune.as_ref()) {
            let tolerance = 1e-9 * limit.abs().max(1.0);
            let bound = wire + cross + link + over + area + self.weights.0 * crossed as f64 + prune.congestion;
            if bound > limit + tolerance {
                self.pruned += 1;
                return Ok((bound, crate::UNWEIGHED));
            }
        }
        let congestion = layout.congestion_term(x, y, turn).map_err(PyValueError::new_err)?;
        let mut total = crate::exact::PySum::new();
        for value in [wire, cross, link, over, 0.0, 0.0, area, congestion, self.weights.0 * crossed as f64] {
            total.add(value);
        }
        let cost = total.total();
        if let Some(prune) = self.prune.as_mut().filter(|_| prune) {
            let at = prune.kept.partition_point(|&k| k <= cost);
            if at < prune.keep {
                prune.kept.insert(at, cost);
                prune.kept.truncate(prune.keep);
            }
        }
        Ok((cost, PARTIAL))
    }

    fn total(&self, raw: (f64, f64, f64, f64, f64, f64), crossed: i64, vias: usize, closed: usize) -> f64 {
        let mut total = crate::exact::PySum::new();
        // Keep the Python Delta term insertion order, including zero push.
        for value in [raw.0, raw.1, raw.2, raw.3, 0.0, 0.0, raw.4, raw.5,
                      self.weights.0 * crossed as f64,
                      self.weights.1 * (closed as f64 - self.baseline.0 as f64),
                      self.weights.2 * (vias as f64 - self.baseline.1 as f64)] {
            total.add(value);
        }
        total.total()
    }
}
