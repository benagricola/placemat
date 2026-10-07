//! Exact source polygons for a frozen placement candidate snapshot. Keep the
//! original affine coefficients: translating an already rounded origin shape
//! can change clearance, pad-field and congestion threshold decisions.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

pub type Point = (f64, f64);
pub type Bounds = (f64, f64, f64, f64);
pub type AffineRecord = (f64, f64, f64, f64, f64, f64);
/// owner, kind, net, pad, layers, source polygon, source track ends, lane, wire
pub type ShapeRecord = (
    String,
    String,
    String,
    String,
    u32,
    Vec<Point>,
    Vec<Point>,
    bool,
    bool,
);
pub type PlacedRecord = (
    String,
    String,
    String,
    String,
    u32,
    Vec<Point>,
    Bounds,
    Vec<Point>,
    bool,
    bool,
);

struct Affine {
    a: f64,
    b: f64,
    c: f64,
    d: f64,
    tx: f64,
    ty: f64,
}
impl Affine {
    fn from_record((a, b, c, d, tx, ty): AffineRecord) -> PyResult<Self> {
        if [a, b, c, d, tx, ty]
            .iter()
            .any(|v| !v.is_finite() || v.abs() > 1e9)
        {
            return Err(PyValueError::new_err("candidate affine invalid"));
        }
        Ok(Self { a, b, c, d, tx, ty })
    }
    fn at(&self, p: Point, location: Point) -> Point {
        // Transform.apply after pose_transform appends translation. Preserve
        // this association, including the final clean9 and positive zero.
        (
            crate::exact::clean9(self.a * p.0 + self.b * p.1 + (self.tx + location.0)),
            crate::exact::clean9(self.c * p.0 + self.d * p.1 + (self.ty + location.1)),
        )
    }
}

pub(crate) struct Source {
    pub(crate) owner: String,
    pub(crate) kind: String,
    pub(crate) net: String,
    pub(crate) pad: String,
    pub(crate) layers: u32,
    polygon: Vec<Point>,
    ends: Vec<Point>,
    pub(crate) lane: bool,
    pub(crate) wire: bool,
}
pub struct Placed {
    pub polygon: Vec<Point>,
    pub bounds: Bounds,
    pub ends: Vec<Point>,
}
pub(crate) struct Turn {
    affine: Affine,
    pub(crate) shapes: Vec<Source>,
    pub(crate) placed: Vec<Placed>,
}

fn valid_point(p: Point) -> bool {
    p.0.is_finite() && p.1.is_finite() && p.0.abs() <= 1e9 && p.1.abs() <= 1e9
}

#[pyclass]
pub struct PreparedCandidate {
    turns: Vec<Turn>,
}

impl PreparedCandidate {
    pub(crate) fn turn(&self, turn: usize) -> &Turn {
        // The caller must first evaluate, which checks the turn index.
        &self.turns[turn]
    }
    pub fn evaluate(&mut self, py: Python<'_>, location: Point, turn: usize) -> PyResult<()> {
        if !valid_point(location) {
            return Err(PyValueError::new_err("candidate location invalid"));
        }
        let turn = self
            .turns
            .get_mut(turn)
            .ok_or_else(|| PyValueError::new_err("candidate turn index invalid"))?;
        for (index, (source, placed)) in turn.shapes.iter().zip(&mut turn.placed).enumerate() {
            if index % 128 == 0 {
                py.check_signals()?;
            }
            let mut bounds = (
                f64::INFINITY,
                f64::INFINITY,
                f64::NEG_INFINITY,
                f64::NEG_INFINITY,
            );
            for (vertex, (source, target)) in
                source.polygon.iter().zip(&mut placed.polygon).enumerate()
            {
                if vertex % 1024 == 0 {
                    py.check_signals()?;
                }
                let point = turn.affine.at(*source, location);
                if !valid_point(point) {
                    return Err(PyValueError::new_err(
                        "candidate polygon exceeds coordinate bounds",
                    ));
                }
                *target = point;
                bounds = (
                    bounds.0.min(point.0),
                    bounds.1.min(point.1),
                    bounds.2.max(point.0),
                    bounds.3.max(point.1),
                );
            }
            placed.bounds = bounds;
            for (endpoint, (source, target)) in source.ends.iter().zip(&mut placed.ends).enumerate()
            {
                if endpoint % 1024 == 0 {
                    py.check_signals()?;
                }
                *target = turn.affine.at(*source, location);
                if !valid_point(*target) {
                    return Err(PyValueError::new_err(
                        "candidate track end exceeds coordinate bounds",
                    ));
                }
            }
        }
        Ok(())
    }
}

#[pymethods]
impl PreparedCandidate {
    #[new]
    fn new(records: Vec<(AffineRecord, Vec<ShapeRecord>)>) -> PyResult<Self> {
        if records.is_empty() || records.len() > 360 {
            return Err(PyValueError::new_err("candidate turn count invalid"));
        }
        let mut turns = Vec::new();
        for (affine, records) in records {
            if records.len() > 100_000 {
                return Err(PyValueError::new_err("candidate shape count invalid"));
            }
            let mut shapes = Vec::new();
            let mut placed = Vec::new();
            let mut vertices = 0usize;
            for (owner, kind, net, pad, layers, polygon, ends, lane, wire) in records {
                vertices = vertices
                    .checked_add(polygon.len())
                    .and_then(|v| v.checked_add(ends.len()))
                    .ok_or_else(|| PyValueError::new_err("candidate vertex count invalid"))?;
                if polygon.is_empty()
                    || vertices > 1_000_000
                    || !polygon.iter().chain(&ends).all(|p| valid_point(*p))
                {
                    return Err(PyValueError::new_err("candidate source polygon invalid"));
                }
                placed.push(Placed {
                    polygon: vec![(0.0, 0.0); polygon.len()],
                    bounds: (0.0, 0.0, 0.0, 0.0),
                    ends: vec![(0.0, 0.0); ends.len()],
                });
                shapes.push(Source {
                    owner,
                    kind,
                    net,
                    pad,
                    layers,
                    polygon,
                    ends,
                    lane,
                    wire,
                });
            }
            turns.push(Turn {
                affine: Affine::from_record(affine)?,
                shapes,
                placed,
            });
        }
        Ok(Self { turns })
    }

    /// Parity inspection only. Hot native consumers borrow the evaluated
    /// geometry directly; this Python view deliberately materializes copies.
    fn shapes(
        &mut self,
        py: Python<'_>,
        x: f64,
        y: f64,
        turn: usize,
    ) -> PyResult<Vec<PlacedRecord>> {
        self.evaluate(py, (x, y), turn)?;
        let turn = &self.turns[turn];
        Ok(turn
            .shapes
            .iter()
            .zip(&turn.placed)
            .map(|(source, placed)| {
                (
                    source.owner.clone(),
                    source.kind.clone(),
                    source.net.clone(),
                    source.pad.clone(),
                    source.layers,
                    placed.polygon.clone(),
                    placed.bounds,
                    placed.ends.clone(),
                    source.lane,
                    source.wire,
                )
            })
            .collect())
    }
}
