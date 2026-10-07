//! Copper contact portion of the prepared escape snapshot. The candidate
//! polygons stay borrowed in Rust; no candidate geometry crosses into Python.
//! This is an explicit parity primitive until the complete escape kernel owns
//! eligibility, lanes, nearest targets and the supplemental path judgements.
use crate::candidate::{Bounds, PlacedRecord, Point, PreparedCandidate};
use crate::geometry::polys_overlap;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashSet;

struct Shape {
    owner: String,
    kind: String,
    net: String,
    pad: String,
    layers: u32,
    polygon: Vec<Point>,
    bounds: Bounds,
    lane: bool,
    wire: bool,
}
struct View<'a> {
    owner: &'a str,
    kind: &'a str,
    net: &'a str,
    pad: &'a str,
    layers: u32,
    polygon: &'a [Point],
    bounds: Bounds,
    lane: bool,
    wire: bool,
}
impl Shape {
    fn view(&self) -> View<'_> {
        View {
            owner: &self.owner,
            kind: &self.kind,
            net: &self.net,
            pad: &self.pad,
            layers: self.layers,
            polygon: &self.polygon,
            bounds: self.bounds,
            lane: self.lane,
            wire: self.wire,
        }
    }
}
fn overlaps(a: Bounds, b: Bounds) -> bool {
    a.0 < b.2 && b.0 < a.2 && a.1 < b.3 && b.1 < a.3
}
fn touches(a: &View<'_>, b: &View<'_>) -> bool {
    overlaps(a.bounds, b.bounds) && polys_overlap(a.polygon, b.polygon)
}
fn pad(kind: &str) -> bool {
    kind == "pad" || kind == "through"
}
fn copper(kind: &str) -> bool {
    kind == "copper" || kind == "through"
}
fn nondegenerate(polygon: &[Point]) -> bool {
    polygon.len() >= 3
        && polygon
            .iter()
            .find(|&&p| p != polygon[0])
            .is_some_and(|&q| {
                polygon.iter().any(|&p| {
                    (q.0 - polygon[0].0) * (p.1 - polygon[0].1)
                        - (q.1 - polygon[0].1) * (p.0 - polygon[0].0)
                        != 0.0
                })
            })
}

#[pyclass]
pub struct PreparedContacts {
    rest: Vec<Shape>,
    footprints: HashSet<String>,
    seen: Vec<bool>,
    todo: Vec<usize>,
    chain: Vec<usize>,
}
impl PreparedContacts {
    fn shape<'a>(
        &'a self,
        candidate: &'a PreparedCandidate,
        turn: usize,
        index: usize,
    ) -> View<'a> {
        if index < self.rest.len() {
            return self.rest[index].view();
        }
        let turn = candidate.turn(turn);
        let index = index - self.rest.len();
        let source = &turn.shapes[index];
        let placed = &turn.placed[index];
        View {
            owner: &source.owner,
            kind: &source.kind,
            net: &source.net,
            pad: &source.pad,
            layers: source.layers,
            polygon: &placed.polygon,
            bounds: placed.bounds,
            lane: source.lane,
            wire: source.wire,
        }
    }
}

#[pymethods]
impl PreparedContacts {
    #[new]
    fn new(py: Python<'_>, records: Vec<PlacedRecord>, footprints: Vec<String>) -> PyResult<Self> {
        if records.len() > 100_000 {
            return Err(PyValueError::new_err("escape contact shape count invalid"));
        }
        let mut rest = Vec::with_capacity(records.len());
        let mut vertices = 0usize;
        for (owner, kind, net, pad, layers, polygon, bounds, _ends, lane, wire) in records {
            py.check_signals()?;
            vertices = vertices
                .checked_add(polygon.len())
                .ok_or_else(|| PyValueError::new_err("escape contact vertex count invalid"))?;
            if !matches!(
                kind.as_str(),
                "pad" | "through" | "copper" | "npth" | "viaban"
            ) || (kind != "npth" && kind != "viaban" && layers == 0)
                || !nondegenerate(&polygon)
                || vertices > 1_000_000
                || !polygon.iter().all(|p| {
                    p.0.is_finite() && p.1.is_finite() && p.0.abs() <= 1e9 && p.1.abs() <= 1e9
                })
            {
                return Err(PyValueError::new_err("escape contact shape invalid"));
            }
            let actual = polygon.iter().fold(
                (
                    f64::INFINITY,
                    f64::INFINITY,
                    f64::NEG_INFINITY,
                    f64::NEG_INFINITY,
                ),
                |b, p| (b.0.min(p.0), b.1.min(p.1), b.2.max(p.0), b.3.max(p.1)),
            );
            // Imported geometry may retain an analytic/conservative box around
            // its polygon. Keep that box for Python's overlap prefilter, while
            // refusing one that omits copper or contains invalid coordinates.
            if ![bounds.0, bounds.1, bounds.2, bounds.3]
                .iter()
                .all(|v| v.is_finite() && v.abs() <= 1e9)
                || bounds.0 > actual.0
                || bounds.1 > actual.1
                || bounds.2 < actual.2
                || bounds.3 < actual.3
                || bounds.0 >= bounds.2
                || bounds.1 >= bounds.3
            {
                return Err(PyValueError::new_err("escape contact bounds invalid"));
            }
            rest.push(Shape {
                owner,
                kind,
                net,
                pad,
                layers,
                polygon,
                bounds,
                lane,
                wire,
            });
        }
        Ok(Self {
            rest,
            footprints: footprints.into_iter().collect(),
            seen: Vec::new(),
            todo: Vec::new(),
            chain: Vec::new(),
        })
    }

    /// (joined to drawn copper, on another part's pad, own chain indices,
    /// own chain reaches another footprint pad, contains a through shape,
    /// consists entirely of declared lane/wire copper). Indices walk rest then
    /// moved shapes. Consumers use membership, not grid-dependent chain order.
    fn contacts(
        &mut self,
        py: Python<'_>,
        mut candidate: PyRefMut<'_, PreparedCandidate>,
        x: f64,
        y: f64,
        turn: usize,
        owner: &str,
        number: &str,
        net: &str,
    ) -> PyResult<(bool, bool, Vec<usize>, bool, bool, bool)> {
        candidate.evaluate(py, (x, y), turn)?;
        let count = self.rest.len() + candidate.turn(turn).shapes.len();
        self.seen.resize(count, false);
        self.seen.fill(false);
        self.todo.clear();
        self.chain.clear();
        let mut layers = 0;
        let mut joined = false;
        let mut on_pad = false;
        for index in 0..count {
            if index % 128 == 0 {
                py.check_signals()?;
            }
            let mine = self.shape(&candidate, turn, index);
            if (pad(mine.kind) || copper(mine.kind))
                && (mine.layers == 0 || !nondegenerate(mine.polygon))
            {
                return Err(PyValueError::new_err(
                    "escape contact candidate copper invalid",
                ));
            }
            if mine.owner == owner && mine.pad == number && pad(mine.kind) {
                if mine.net != net || mine.layers == 0 {
                    return Err(PyValueError::new_err("escape contact pad intent mismatch"));
                }
                layers |= mine.layers;
                for other in 0..count {
                    if other % 128 == 0 {
                        py.check_signals()?;
                    }
                    let shape = self.shape(&candidate, turn, other);
                    if shape.net != net
                        || shape.layers & mine.layers == 0
                        || !touches(&mine, &shape)
                    {
                        continue;
                    }
                    joined |= copper(shape.kind) && !self.footprints.contains(shape.owner);
                    on_pad |= pad(shape.kind) && shape.owner != owner;
                }
                self.todo.push(index);
            }
        }
        if self.todo.is_empty() {
            return Err(PyValueError::new_err("escape contact pad missing"));
        }
        while let Some(index) = self.todo.pop() {
            py.check_signals()?;
            for other in 0..count {
                if other % 128 == 0 {
                    py.check_signals()?;
                }
                if self.seen[other] {
                    continue;
                }
                let at = self.shape(&candidate, turn, index);
                let shape = self.shape(&candidate, turn, other);
                if shape.net == net
                    && copper(shape.kind)
                    && !self.footprints.contains(shape.owner)
                    && shape.layers & layers != 0
                    && touches(&at, &shape)
                {
                    self.seen[other] = true;
                    self.chain.push(other);
                    self.todo.push(other);
                }
            }
        }
        let mut runs_on = false;
        let mut through = false;
        let mut declared = true;
        for &index in &self.chain {
            let own = self.shape(&candidate, turn, index);
            through |= own.kind == "through";
            declared &= own.lane || own.wire;
            for other in 0..count {
                if other % 128 == 0 {
                    py.check_signals()?;
                }
                let shape = self.shape(&candidate, turn, other);
                if pad(shape.kind)
                    && shape.net == net
                    && self.footprints.contains(shape.owner)
                    && !(shape.owner == owner && shape.pad == number)
                    && shape.layers & own.layers != 0
                    && touches(&own, &shape)
                {
                    runs_on = true;
                }
            }
        }
        Ok((
            joined,
            on_pad,
            self.chain.clone(),
            runs_on,
            through,
            declared,
        ))
    }
}
