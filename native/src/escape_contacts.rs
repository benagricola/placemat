//! Copper contact portion of the prepared escape snapshot. The candidate
//! polygons stay borrowed in Rust; no candidate geometry crosses into Python.
//! This is an explicit parity primitive until the complete escape kernel owns
//! eligibility, lanes, nearest targets and the supplemental path judgements.
use crate::candidate::{Bounds, PlacedRecord, Point, PreparedCandidate};
use crate::geometry::polys_overlap;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};

struct Shape {
    owner: String,
    kind: String,
    net: String,
    pad: String,
    layers: u32,
    polygon: Vec<Point>,
    ends: Vec<Point>,
    bounds: Bounds,
    lane: bool,
    wire: bool,
}
pub(crate) struct View<'a> {
    pub(crate) owner: &'a str,
    pub(crate) kind: &'a str,
    pub(crate) net: &'a str,
    pub(crate) pad: &'a str,
    pub(crate) layers: u32,
    pub(crate) polygon: &'a [Point],
    pub(crate) ends: &'a [Point],
    pub(crate) bounds: Bounds,
    pub(crate) lane: bool,
    pub(crate) wire: bool,
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
            ends: &self.ends,
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

/// Original concatenated shape indices, grouped only by immutable net and role.
/// No geometric pruning: exact touch tests and traversal order are unchanged.
#[derive(Default)]
struct ContactIndex {
    by_net: HashMap<String, Vec<usize>>,
    by_pad: HashMap<(String, String), Vec<usize>>,
}
impl ContactIndex {
    fn add(&mut self, index: usize, net: &str, owner: &str, number: &str, kind: &str) {
        self.by_net.entry(net.to_owned()).or_default().push(index);
        if pad(kind) {
            self.by_pad
                .entry((owner.to_owned(), number.to_owned()))
                .or_default()
                .push(index);
        }
    }
}

#[pyclass]
pub struct PreparedContacts {
    rest: Vec<Shape>,
    footprints: HashSet<String>,
    seen: Vec<bool>,
    todo: Vec<usize>,
    chain: Vec<usize>,
    rest_contact: Vec<bool>,
    moving_contact: Option<Vec<Vec<bool>>>,
    candidate_identity: Option<std::sync::Arc<()>>,
    rest_index: ContactIndex,
    turn_indexes: Option<Vec<ContactIndex>>,
}
impl PreparedContacts {
    pub(crate) fn shape<'a>(
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
            ends: &placed.ends,
            bounds: placed.bounds,
            lane: source.lane,
            wire: source.wire,
        }
    }
}

#[pymethods]
impl PreparedContacts {
    #[new]
    pub(crate) fn new(
        py: Python<'_>,
        records: Vec<PlacedRecord>,
        footprints: Vec<String>,
    ) -> PyResult<Self> {
        if records.len() > 100_000 {
            return Err(PyValueError::new_err("escape contact shape count invalid"));
        }
        let mut rest = Vec::with_capacity(records.len());
        let mut vertices = 0usize;
        for (owner, kind, net, pad, layers, polygon, bounds, ends, lane, wire) in records {
            py.check_signals()?;
            vertices = vertices
                .checked_add(polygon.len())
                .and_then(|v| v.checked_add(ends.len()))
                .ok_or_else(|| PyValueError::new_err("escape contact vertex count invalid"))?;
            if !matches!(
                kind.as_str(),
                "pad" | "through" | "copper" | "npth" | "viaban"
            ) || (kind != "npth" && kind != "viaban" && layers == 0)
                || !nondegenerate(&polygon)
                || vertices > 1_000_000
                || !polygon.iter().chain(&ends).all(|p| {
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
                || ends
                    .iter()
                    .any(|p| p.0 < bounds.0 || p.0 > bounds.2 || p.1 < bounds.1 || p.1 > bounds.3)
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
                ends,
                bounds,
                lane,
                wire,
            });
        }
        let mut rest_index = ContactIndex::default();
        for (i, shape) in rest.iter().enumerate() {
            rest_index.add(i, &shape.net, &shape.owner, &shape.pad, &shape.kind);
        }
        Ok(Self {
            rest_index,
            turn_indexes: None,
            rest_contact: vec![true; rest.len()],
            moving_contact: None,
            candidate_identity: None,
            rest,
            footprints: footprints.into_iter().collect(),
            seen: Vec::new(),
            todo: Vec::new(),
            chain: Vec::new(),
        })
    }

    /// Freeze contact membership separately from path obstacle membership.
    /// Carried geometry can obstruct a path without being planned copper in
    /// the occupancy contact grid. Configuration is validated before publish.
    pub(crate) fn configure_contact_roles(
        &mut self,
        candidate: PyRef<'_, PreparedCandidate>,
        rest: Vec<bool>,
        moving: Vec<Vec<bool>>,
    ) -> PyResult<()> {
        if rest.len() != self.rest.len()
            || moving.len() != candidate.turn_count()
            || moving
                .iter()
                .enumerate()
                .any(|(i, mask)| mask.len() != candidate.turn(i).shapes.len())
        {
            return Err(PyValueError::new_err(
                "escape contact role dimensions invalid",
            ));
        }
        // Build all lists privately before publishing any role configuration.
        let mut rest_index = ContactIndex::default();
        for (i, shape) in self.rest.iter().enumerate() {
            if rest[i] {
                rest_index.add(i, &shape.net, &shape.owner, &shape.pad, &shape.kind);
            }
        }
        let mut turn_indexes = Vec::with_capacity(candidate.turn_count());
        for (turn, roles) in moving.iter().enumerate() {
            let mut index = ContactIndex::default();
            for (i, shape) in candidate.turn(turn).shapes.iter().enumerate() {
                if roles[i] {
                    index.add(
                        self.rest.len() + i,
                        &shape.net,
                        &shape.owner,
                        &shape.pad,
                        &shape.kind,
                    );
                }
            }
            turn_indexes.push(index);
        }
        self.rest_index = rest_index;
        self.turn_indexes = Some(turn_indexes);
        self.candidate_identity = Some(candidate.identity.clone());
        self.rest_contact = rest;
        self.moving_contact = Some(moving);
        Ok(())
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
        let facts = self.inspect(py, &candidate, turn, owner, number, net)?;
        Ok((
            facts.joined,
            facts.on_pad,
            self.chain.clone(),
            facts.runs_on,
            facts.through,
            facts.declared,
        ))
    }
}

/// Named facts consumed by the native escape evaluator; inspection serializes
/// its chain only at the explicit Python parity boundary.
pub(crate) struct ContactFacts {
    pub(crate) joined: bool,
    pub(crate) on_pad: bool,
    pub(crate) runs_on: bool,
    pub(crate) through: bool,
    pub(crate) declared: bool,
}

impl PreparedContacts {
    pub(crate) fn is_contact(&self, turn: usize, index: usize) -> bool {
        if index < self.rest.len() {
            self.rest_contact[index]
        } else {
            self.moving_contact
                .as_ref()
                .map_or(true, |m| m[turn][index - self.rest.len()])
        }
    }

    /// The contact pad shapes of one pad, rest then moving, each in shape order: what a scan of every shape for
    /// contact shapes of kind pad or through with this owner and number lists. None before the roles are configured.
    pub(crate) fn pad_shapes(&self, turn: usize, owner: &str, number: &str) -> Option<Vec<usize>> {
        let indexes = self.turn_indexes.as_ref()?;
        let key = (owner.to_owned(), number.to_owned());
        let mut out = self.rest_index.by_pad.get(&key).cloned().unwrap_or_default();
        if let Some(moving) = indexes[turn].by_pad.get(&key) {
            out.extend(moving);
        }
        Some(out)
    }

    pub(crate) fn shape_count(&self, candidate: &PreparedCandidate, turn: usize) -> usize {
        self.rest.len() + candidate.turn(turn).shapes.len()
    }

    pub(crate) fn chain(&self) -> &[usize] {
        &self.chain
    }

    /// Candidate geometry has already been evaluated for this turn. The
    /// complete native evaluator calls this directly, never through Python.
    pub(crate) fn inspect(
        &mut self,
        py: Python<'_>,
        candidate: &PreparedCandidate,
        turn: usize,
        owner: &str,
        number: &str,
        net: &str,
    ) -> PyResult<ContactFacts> {
        // The immutable source snapshot defines shape identity and order, not
        // just array sizes. Arc identity is O(1) and survives wrapper movement.
        if self
            .candidate_identity
            .as_ref()
            .is_some_and(|id| !std::sync::Arc::ptr_eq(id, &candidate.identity))
        {
            return Err(PyValueError::new_err(
                "escape contact candidate identity changed",
            ));
        }
        if self.moving_contact.as_ref().is_some_and(|m| {
            m.len() != candidate.turn_count() || m[turn].len() != candidate.turn(turn).shapes.len()
        }) {
            return Err(PyValueError::new_err(
                "escape contact role dimensions invalid",
            ));
        }
        self.validate_candidate(py, candidate, turn)?;
        self.inspect_validated(py, candidate, turn, owner, number, net)
    }

    /// Validate the evaluated moving geometry once per complete surface call.
    /// Rest records were validated atomically at construction. Standalone
    /// inspection calls this itself, so malformed unused geometry still refuses.
    pub(crate) fn validate_candidate(
        &self,
        py: Python<'_>,
        candidate: &PreparedCandidate,
        turn: usize,
    ) -> PyResult<()> {
        let count = self.rest.len() + candidate.turn(turn).shapes.len();
        for index in self.rest.len()..count {
            if index % 128 == 0 {
                py.check_signals()?;
            }
            let mine = self.shape(&candidate, turn, index);
            if crate::shapes::Kind::from_str(mine.kind).is_none() {
                return Err(PyValueError::new_err(
                    "escape contact candidate kind invalid",
                ));
            }
            if (pad(mine.kind) || copper(mine.kind))
                && (mine.layers == 0 || !nondegenerate(mine.polygon))
            {
                return Err(PyValueError::new_err(
                    "escape contact candidate copper invalid",
                ));
            }
            if matches!(mine.kind, "npth" | "viaban") && !nondegenerate(mine.polygon) {
                return Err(PyValueError::new_err(
                    "escape contact candidate wall invalid",
                ));
            }
        }
        Ok(())
    }

    pub(crate) fn inspect_validated(
        &mut self,
        py: Python<'_>,
        candidate: &PreparedCandidate,
        turn: usize,
        owner: &str,
        number: &str,
        net: &str,
    ) -> PyResult<ContactFacts> {
        let count = self.rest.len() + candidate.turn(turn).shapes.len();
        // Rest precedes moving shapes exactly as in the original full scan.
        let mut indices = self.rest_index.by_net.get(net).cloned().unwrap_or_default();
        if let Some(indexes) = &self.turn_indexes {
            if let Some(moving) = indexes[turn].by_net.get(net) {
                indices.extend(moving);
            }
        } else {
            indices.extend(
                candidate
                    .turn(turn)
                    .shapes
                    .iter()
                    .enumerate()
                    .filter(|(_, shape)| shape.net == net)
                    .map(|(i, _)| self.rest.len() + i),
            );
        }
        let pad_key = (owner.to_owned(), number.to_owned());
        let mut seeds = self
            .rest_index
            .by_pad
            .get(&pad_key)
            .cloned()
            .unwrap_or_default();
        if let Some(indexes) = &self.turn_indexes {
            if let Some(moving) = indexes[turn].by_pad.get(&pad_key) {
                seeds.extend(moving);
            }
        } else {
            seeds.extend(
                candidate
                    .turn(turn)
                    .shapes
                    .iter()
                    .enumerate()
                    .filter(|(_, s)| s.owner == owner && s.pad == number && pad(&s.kind))
                    .map(|(i, _)| self.rest.len() + i),
            );
        }
        self.seen.resize(count, false);
        self.seen.fill(false);
        self.todo.clear();
        self.chain.clear();
        let mut layers = 0;
        let mut joined = false;
        let mut on_pad = false;
        for &index in &seeds {
            py.check_signals()?;
            let mine = self.shape(candidate, turn, index);
            if mine.owner == owner && mine.pad == number && pad(mine.kind) {
                if mine.net != net || mine.layers == 0 {
                    return Err(PyValueError::new_err("escape contact pad intent mismatch"));
                }
                layers |= mine.layers;
                for (walk, &other) in indices.iter().enumerate() {
                    if walk % 128 == 0 {
                        py.check_signals()?;
                    }
                    let shape = self.shape(candidate, turn, other);
                    if shape.layers & mine.layers == 0 || !touches(&mine, &shape) {
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
            for (walk, &other) in indices.iter().enumerate() {
                if walk % 128 == 0 {
                    py.check_signals()?;
                }
                if self.seen[other] || !self.is_contact(turn, other) {
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
            for (walk, &other) in indices.iter().enumerate() {
                if walk % 128 == 0 {
                    py.check_signals()?;
                }
                let shape = self.shape(&candidate, turn, other);
                if self.is_contact(turn, other)
                    && pad(shape.kind)
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
        Ok(ContactFacts {
            joined,
            on_pad,
            runs_on,
            through,
            declared,
        })
    }
}
