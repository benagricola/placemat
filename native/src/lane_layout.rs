//! An escape's layout, ported from `src/placemat/lanes.py`'s `Layouter` and `layout.py`'s `_LaneEnv`: for the pads of
//! a pin row and an escape's declaration, each pin's riser, lane and via, and which lanes meet something placed.
//!
//! Python's `Layouter` is the reference. Every method here names the one it ports and does what it does in the same
//! order and with the same rounding; the board is asked as `lanes.rs` answers it, whose copper conflict is
//! `Occupancy._conflict`'s exact one. What Python works out here only to say it (the refusal that names what stands
//! in a lane's way, the message of a via with no spot) is not worked out: a lane is blocked or it is not, and a layout
//! that cannot be laid out is an `Err`. The search that prices a candidate by the lanes it blocks counts them.
//!
//! A clearance, a track's width and a pair's gap are the script's rules, which stay in Python: `Rules` asks for each
//! once and keeps the answer.

use crate::exact;
use crate::geometry::{point_in_polygon, point_segment_distance, poly_distance};
use crate::giveway::segment_polygon;
use crate::lanes::{self, Extra, Item, Pool, View, ViaObstacles};
use crate::shapes::{Bounds, Kind, Shape};
use crate::ties::TieInfo;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

type P = (f64, f64);

const TOL: f64 = 1e-9;
const SQ2: f64 = std::f64::consts::SQRT_2;

/// The script's rules for the lanes of a board, as Python answers them (`_LaneEnv.clearance`, `width`, `pair_gap`).
#[pyclass]
pub struct Rules {
    clearance: Py<PyAny>,
    width: Py<PyAny>,
    pair_gap: Py<PyAny>,
    clearances: HashMap<(String, String, String), f64>,
    widths: HashMap<String, f64>,
    gaps: HashMap<String, f64>,
}

#[pymethods]
impl Rules {
    #[new]
    fn new(clearance: Py<PyAny>, width: Py<PyAny>, pair_gap: Py<PyAny>) -> Self {
        Rules { clearance, width, pair_gap, clearances: HashMap::new(), widths: HashMap::new(), gaps: HashMap::new() }
    }
}

impl Rules {
    /// `_LaneEnv.clearance(net_a, net_b, owner_b)`: the clearance a track of `net_a` keeps from copper of `net_b`
    /// (a pad of `owner_b` where that is given).
    fn clearance(&mut self, py: Python<'_>, a: &str, b: &str, owner: &str) -> PyResult<f64> {
        let key = (a.to_owned(), b.to_owned(), owner.to_owned());
        if let Some(&c) = self.clearances.get(&key) {
            return Ok(c);
        }
        let c: f64 = self.clearance.call1(py, (a, b, owner))?.extract(py)?;
        self.clearances.insert(key, c);
        Ok(c)
    }

    fn width(&mut self, py: Python<'_>, net: &str) -> PyResult<f64> {
        if let Some(&w) = self.widths.get(net) {
            return Ok(w);
        }
        let w: f64 = self.width.call1(py, (net,))?.extract(py)?;
        self.widths.insert(net.to_owned(), w);
        Ok(w)
    }

    fn pair_gap(&mut self, py: Python<'_>, net: &str) -> PyResult<f64> {
        if let Some(&g) = self.gaps.get(net) {
            return Ok(g);
        }
        let g: f64 = self.pair_gap.call1(py, (net,))?.extract(py)?;
        self.gaps.insert(net.to_owned(), g);
        Ok(g)
    }
}

/// A pad of the part, as the layout reads it.
pub struct PadShape {
    pub poly: Vec<P>,
    pub bbox: Bounds,
    pub net: String,
    pub owner: String,
}

/// `lanes.EscapeDecl`, and the part's pads and the row's frame (`Layouter.__init__`).
pub struct Spec {
    pub pins: Vec<String>,
    pub turn: bool,
    pub vias: HashSet<String>,
    pub depth: Option<f64>,
    pub run: Option<f64>,
    pub widths: HashMap<String, f64>,
    pub pairs: Vec<(String, String)>,
    pub chamfer: f64,
    pub chamfers: HashMap<String, f64>,
    pub via_size: f64,
    pub via_drill: f64,
    /// The pads by number, in the order the part lists them, each with its lands.
    pub pads: Vec<(String, Vec<PadShape>)>,
    /// The lands of a pin drawn as several that stand in the row.
    pub lands: HashMap<String, Vec<usize>>,
    pub u: P,
    pub t: P,
    pub diagonal: bool,
    pub oblique: bool,
}

impl Spec {
    fn chamfer_of(&self, number: &str) -> f64 {
        self.chamfers.get(number).copied().unwrap_or(self.chamfer)
    }
}

/// What the layout asks of the board and the script's rules (`_LaneEnv`).
pub struct Env<'a, 'p> {
    pub py: Python<'p>,
    pub rules: &'a mut Rules,
    pub view: &'a View,
    pub obstacles: &'a ViaObstacles,
    pub off_board: &'a Bound<'p, PyAny>,
    pub step: f64,
    pub reach: f64,
    pub hole_to_hole: f64,
    pub grid_step: f64,
    /// The copper layer the lanes are on, as a layer bit and the faces it is on.
    pub layer: u32,
    pub layer_faces: u8,
    pub via_layers: u32,
    pub board_layers: u32,
    pub cap_steps: usize,
    pub copper_reach: f64,
    /// The nets a net tie's pads carry, where the board has net ties.
    pub tie_nets: Option<HashSet<String>>,
    /// The pads of the part itself, where it is a candidate not yet in the board.
    pub own: Vec<Item>,
    /// The placed items' unplated holes.
    pub npth: Vec<Item>,
    /// The box of every place the layout asked the board about.
    pub asked: Vec<Bounds>,
}

fn bounds(poly: &[P]) -> Bounds {
    let x0 = poly.iter().map(|p| p.0).fold(f64::INFINITY, f64::min);
    let x1 = poly.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max);
    let y0 = poly.iter().map(|p| p.1).fold(f64::INFINITY, f64::min);
    let y1 = poly.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max);
    (x0, y0, x1, y1)
}

/// `geometry.circle_polygon(centre, radius, 16)`.
fn circle_polygon(c: P, radius: f64) -> Vec<P> {
    let n = 16;
    (0..n)
        .map(|i| {
            let a = 2.0 * std::f64::consts::PI * i as f64 / n as f64;
            (c.0 + radius * a.cos(), c.1 + radius * a.sin())
        })
        .collect()
}

/// `geometry.via_ring`.
fn via_ring(c: P, size: f64) -> Vec<P> {
    circle_polygon(c, size / 2.0 / (std::f64::consts::PI / 16.0).cos())
}

fn shape(kind: Kind, faces: u8, layers: u32, net: &str, owner: &str, poly: Vec<P>, wire: bool, tie: Option<Arc<TieInfo>>)
    -> Shape {
    let bbox = bounds(&poly);
    Shape { kind, faces, layers, net: net.to_owned(), poly, bbox, owner: owner.to_owned(), owner_is_footprint: false,
            is_lead: false, margin: 0.0, wire, tie }
}

impl Env<'_, '_> {
    /// What the net-tie exclusion reads of a probe (`Occupancy._native_ties` of one shape): something only where the
    /// board has net ties and the probe's net is one a net tie's pads carry.
    fn tie_of(&self, net: &str, ends: Option<(P, P)>, circle: Option<(f64, f64, f64)>) -> Option<Arc<TieInfo>> {
        let nets = self.tie_nets.as_ref()?;
        if !nets.contains(net) {
            return None;
        }
        Some(Arc::new(TieInfo { has_fp: false, fp_graphic: false, fp_copper: false, tie_graphic: false, circle, ends,
                                reads: None, fp: None }))
    }

    /// `layout._shape_of(Track(...))`.
    fn track(&self, net: &str, width: f64, a: P, b: P) -> Item {
        let poly = segment_polygon(a, b, width, self.cap_steps);
        let tie = self.tie_of(net, Some((a, b)), None);
        Item {
            shape: shape(Kind::Copper, self.layer_faces, self.layer, net, "", poly, true, tie),
            extra: Extra { segment: Some((a.0, a.1, b.0, b.1, width)), ..Extra::default() },
        }
    }

    /// `layout._shape_of(Via(...))`: a through via.
    fn via(&self, net: &str, at: P, size: f64) -> Item {
        let poly = via_ring(at, size);
        let circle = (at.0, at.1, size / 2.0);
        let tie = self.tie_of(net, None, Some(circle));
        Item {
            shape: shape(Kind::Through, 3, self.via_layers, net, "", poly, true, tie),
            extra: Extra { circle: Some(circle), ..Extra::default() },
        }
    }

    /// `_LaneEnv._beside`: whether `probe` meets the part's own pads, where it is a candidate, or an unplated hole.
    fn beside(&self, probe: &Item) -> bool {
        let cfg = self.view.cfg();
        self.own.iter().any(|o| lanes::conflicts(probe, &o.shape, &o.extra, Pool::Copper, cfg))
            || self.npth.iter().any(|o| {
                crate::shapes::box_overlaps(probe.shape.bbox, o.shape.bbox, self.copper_reach)
                    && lanes::conflicts(probe, &o.shape, &o.extra, Pool::Copper, cfg)
            })
    }

    fn free(&mut self, probe: Item) -> bool {
        self.asked.push(probe.shape.bbox);
        !self.view.meets(&probe, Pool::Copper) && !self.beside(&probe)
    }

    /// `_LaneEnv.free` of a track.
    fn free_track(&mut self, net: &str, width: f64, a: P, b: P) -> bool {
        let probe = self.track(net, width, a, b);
        self.free(probe)
    }

    /// `_LaneEnv.free` of a via.
    fn free_via(&mut self, net: &str, at: P, size: f64) -> bool {
        let probe = self.via(net, at, size);
        self.free(probe)
    }

    /// `_LaneEnv.via_free`: a via of `net` at `at`.
    fn via_free(&mut self, at: P, net: &str, size: f64, drill: f64) -> PyResult<bool> {
        let ring = via_ring(at, size);
        let bbox = bounds(&ring);
        self.asked.push(bbox);
        let off: bool = self.off_board.call1((bbox.0, bbox.1, bbox.2, bbox.3))?.extract()?;
        if off {
            return Ok(false);
        }
        let tie = self.tie_of(net, None, None);
        let ring = Item {
            shape: shape(Kind::Copper, 0, self.board_layers, net, "via", ring, true, tie),
            extra: Extra::default(),
        };
        let hole = Item {
            shape: shape(Kind::Hole, 3, 0, net, "via", circle_polygon(at, drill / 2.0), false, None),
            extra: Extra::default(),
        };
        Ok(lanes::via_site_free(self.view, &ring, &hole, at, net, size, drill, self.obstacles))
    }
}

/// `lanes._away`.
fn away(v: f64, sign: f64) -> f64 {
    let q = v * 1e6;
    (if sign > 0.0 { (q - 1e-3).ceil() } else { (q + 1e-3).floor() }) / 1e6
}

fn point_poly_distance(p: P, poly: &[P]) -> f64 {
    if point_in_polygon(p, poly) {
        return 0.0;
    }
    let n = poly.len();
    (0..n).map(|i| point_segment_distance(p, poly[i], poly[(i + 1) % n])).fold(f64::INFINITY, f64::min)
}

fn dist(a: P, b: P) -> f64 {
    exact::hypot(a.0 - b.0, a.1 - b.1)
}

/// `copper._unit`.
fn unit(a: P, b: P) -> P {
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let n = exact::hypot(dx, dy);
    if n > 1e-12 { (dx / n, dy / n) } else { (0.0, 0.0) }
}

/// `copper.chamfer_cuts(pts, c)[0]`.
fn chamfer_cuts(pts: &[P], c: f64) -> Vec<P> {
    if c <= 0.0 || pts.len() < 3 {
        return pts.to_vec();
    }
    let mut out = vec![pts[0]];
    for i in 1..pts.len() - 1 {
        let (a, v, b) = (pts[i - 1], pts[i], pts[i + 1]);
        let (u1, u2) = (unit(a, v), unit(v, b));
        let dot = u1.0 * u2.0 + u1.1 * u2.1;
        let axis = [u1, u2].iter().all(|u| u.0.abs() < 1e-9 || u.1.abs() < 1e-9);
        if dot.abs() > 1e-6 || !axis {
            out.push(v);
            continue;
        }
        let k = c.min(dist(a, v) / 2.0).min(dist(v, b) / 2.0);
        out.push((exact::round6(v.0 - u1.0 * k), exact::round6(v.1 - u1.1 * k)));
        out.push((exact::round6(v.0 + u2.0 * k), exact::round6(v.1 + u2.1 * k)));
    }
    out.push(pts[pts.len() - 1]);
    out
}

/// `copper.polyline_tracks`: the legs of a polyline, less those with no length.
fn legs(pts: &[P]) -> Vec<(P, P)> {
    pts.windows(2).filter(|w| w[0] != w[1]).map(|w| (w[0], w[1])).collect()
}

/// `lanes._Lane`: one lane while it is being laid out.
#[derive(Clone)]
struct Lane {
    number: String,
    net: String,
    width: f64,
    via: Option<(f64, f64)>,
    centre: P,
    s: f64,
    copper: f64,
    h: f64,
    corner: P,
    a: f64,
    via_at: Option<P>,
    end_at: P,
    blocked_why: bool,
    jog: Option<P>,
    ca: f64,
}

impl Lane {
    fn new(number: &str, net: &str, width: f64, via: Option<(f64, f64)>, centre: P, s: f64) -> Lane {
        Lane {
            number: number.to_owned(), net: net.to_owned(), width, via, centre, s,
            copper: via.map_or(width, |v| v.0), h: 0.0, corner: (0.0, 0.0), a: 0.0, via_at: None, end_at: (0.0, 0.0),
            blocked_why: false, jog: None, ca: 0.0,
        }
    }
}

/// Why a layout cannot be laid out: Python raises an `EscapeError` (or `NoViaSpot`).
#[derive(Debug, PartialEq)]
pub enum Refused {
    /// A pin off the row, a pair of a row without a turn or of lanes that are not neighbours, or a via with no spot.
    Escape,
    /// Something Python raises other than an `EscapeError`: the layout is left to it.
    Unsupported,
}

/// What a lane came to.
pub struct LaneOut {
    pub number: String,
    pub points: Vec<P>,
    pub tracks: Vec<(P, P)>,
    pub via: Option<P>,
    pub blocked: bool,
}

pub struct Laid {
    /// The lanes, innermost first.
    pub lanes: Vec<LaneOut>,
}

impl Laid {
    pub fn blocked(&self) -> usize {
        self.lanes.iter().filter(|l| l.blocked).count()
    }
}

/// How `first` judges a point on a lane: a via of the lane stands clear of the part's own pads, or of everything.
#[derive(Clone, Copy)]
enum Judge {
    Pads,
    Via { others: bool },
}

pub type Result<T> = std::result::Result<T, Failure>;

pub enum Failure {
    Refused(Refused),
    Python(PyErr),
}

impl From<PyErr> for Failure {
    fn from(e: PyErr) -> Failure {
        Failure::Python(e)
    }
}

impl From<Refused> for Failure {
    fn from(r: Refused) -> Failure {
        Failure::Refused(r)
    }
}

pub struct Layouter<'s, 'a, 'p> {
    spec: &'s Spec,
    env: Env<'a, 'p>,
    u: P,
    t: P,
    lanes: Vec<Lane>,
    at: HashMap<String, usize>,
    order: Vec<usize>,
    paired: HashMap<String, String>,
    /// Indices into `spec.pads` of the pads that stand in the row.
    row: Vec<usize>,
    tips: f64,
    row_end: f64,
    /// The clearance each lane keeps from each pad shape, by lane and then pad shape in `spec.pads` order.
    need: Vec<Vec<f64>>,
    base: Vec<usize>,
    tip: Vec<Option<f64>>,
}

impl<'s, 'a, 'p> Layouter<'s, 'a, 'p> {
    pub fn new(spec: &'s Spec, env: Env<'a, 'p>) -> Self {
        Layouter {
            spec, env, u: spec.u, t: spec.t, lanes: Vec::new(), at: HashMap::new(), order: Vec::new(),
            paired: HashMap::new(), row: Vec::new(), tips: 0.0, row_end: 0.0, need: Vec::new(), base: Vec::new(),
            tip: Vec::new(),
        }
    }

    pub fn into_asked(self) -> Vec<Bounds> {
        self.env.asked
    }

    // ---- the frame: s along the row toward the turn side, h out along the way out
    fn s_of(&self, p: P) -> f64 {
        p.0 * self.t.0 + p.1 * self.t.1
    }

    fn h_of(&self, p: P) -> f64 {
        p.0 * self.u.0 + p.1 * self.u.1
    }

    fn at(&self, s: f64, h: f64) -> P {
        (s * self.t.0 + h * self.u.0, s * self.t.1 + h * self.u.1)
    }

    /// `Layouter._snap`.
    fn snap(&self, p: P) -> P {
        if self.spec.oblique {
            return p;
        }
        (away(p.0, self.u.0 + self.t.0), away(p.1, self.u.1 + self.t.1))
    }

    /// `Layouter._snap_out`.
    fn snap_out(&self, p: P) -> P {
        if self.spec.oblique {
            return self.snap(p);
        }
        if self.u.0 != 0.0 {
            return (away(p.0, self.u.0), exact::round6(p.1));
        }
        (exact::round6(p.0), away(p.1, self.u.1))
    }

    /// `Layouter._row_lands`: the shapes of a pad that stand in the row.
    fn row_lands(&self, g: usize) -> Vec<&PadShape> {
        let (number, shapes) = &self.spec.pads[g];
        match self.spec.lands.get(number) {
            Some(lands) => lands.iter().map(|&i| &shapes[i]).collect(),
            None => shapes.iter().collect(),
        }
    }

    /// `Layouter._extent`: (least h, greatest h, least s, greatest s) of a pad's lands in the row.
    fn extent(&self, g: usize) -> (f64, f64, f64, f64) {
        let pts: Vec<P> = self.row_lands(g).iter().flat_map(|sh| sh.poly.iter().copied()).collect();
        let hs: Vec<f64> = pts.iter().map(|&p| self.h_of(p)).collect();
        let ss: Vec<f64> = pts.iter().map(|&p| self.s_of(p)).collect();
        let lo = |v: &[f64]| v.iter().copied().fold(f64::INFINITY, f64::min);
        let hi = |v: &[f64]| v.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        (lo(&hs), hi(&hs), lo(&ss), hi(&ss))
    }

    /// `Layouter._centre`.
    fn centre(&self, g: usize) -> P {
        let boxes: Vec<Bounds> = self.row_lands(g).iter().map(|sh| sh.bbox).collect();
        let x0 = boxes.iter().map(|b| b.0).fold(f64::INFINITY, f64::min);
        let y0 = boxes.iter().map(|b| b.1).fold(f64::INFINITY, f64::min);
        let x1 = boxes.iter().map(|b| b.2).fold(f64::NEG_INFINITY, f64::max);
        let y1 = boxes.iter().map(|b| b.3).fold(f64::NEG_INFINITY, f64::max);
        ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
    }

    fn pad_group(&self, number: &str) -> Option<usize> {
        self.spec.pads.iter().position(|(n, _)| n == number)
    }

    // ---- the whole layout
    /// `Layouter.lay_out`.
    pub fn lay_out(&mut self) -> Result<Laid> {
        let spec = self.spec;
        let first_pin = self.pad_group(&spec.pins[0]).ok_or(Refused::Unsupported)?;
        let first = self.extent(first_pin);
        let mut row = Vec::new();
        for g in 0..spec.pads.len() {
            let (lo, hi, _, _) = self.extent(g);
            let overlap = hi.min(first.1) - lo.max(first.0);
            if overlap > 0.5 * (hi - lo).min(first.1 - first.0) - 1e-9 {
                row.push(g);
            }
        }
        let mut groups = Vec::new();
        for n in &spec.pins {
            let g = self.pad_group(n).ok_or(Refused::Unsupported)?;
            if !row.contains(&g) {
                return Err(Refused::Escape.into());
            }
            groups.push(g);
        }
        self.tips = row.iter().map(|&g| self.extent(g).1).fold(f64::NEG_INFINITY, f64::max);
        self.row_end = row.iter().map(|&g| self.extent(g).3).fold(f64::NEG_INFINITY, f64::max);
        self.row = row;
        let mut base = Vec::new();
        let mut n = 0;
        for (_, shapes) in &spec.pads {
            base.push(n);
            n += shapes.len();
        }
        self.base = base;
        for (k, number) in spec.pins.iter().enumerate() {
            let net = spec.pads[groups[k]].1[0].net.clone();
            let width = match spec.widths.get(number) {
                Some(&w) if w != 0.0 => w,
                _ => self.env.rules.width(self.env.py, &net)?,
            };
            let via = if spec.vias.contains(number) { Some((spec.via_size, spec.via_drill)) } else { None };
            let c = self.centre(groups[k]);
            let s = self.s_of(c);
            self.lanes.push(Lane::new(number, &net, width, via, c, s));
            self.at.insert(number.clone(), k);
        }
        self.tip = vec![None; self.lanes.len()];
        for i in 0..self.lanes.len() {
            let net = self.lanes[i].net.clone();
            let mut row_need = Vec::new();
            for (_, shapes) in &spec.pads {
                for sh in shapes {
                    row_need.push(self.env.rules.clearance(self.env.py, &net, &sh.net, &sh.owner)?);
                }
            }
            self.need.push(row_need);
        }
        self.order = (0..self.lanes.len()).collect();
        if spec.turn {
            let lanes = &self.lanes;
            self.order.sort_by(|&a, &b| (-lanes[a].s).partial_cmp(&(-lanes[b].s)).unwrap_or(std::cmp::Ordering::Equal));
        }
        for (a, b) in &spec.pairs {
            self.paired.insert(a.clone(), b.clone());
            self.paired.insert(b.clone(), a.clone());
            if !spec.turn {
                return Err(Refused::Escape.into());
            }
            let ia = self.order.iter().position(|&i| &self.lanes[i].number == a).ok_or(Refused::Unsupported)?;
            let ib = self.order.iter().position(|&i| &self.lanes[i].number == b).ok_or(Refused::Unsupported)?;
            if ia.abs_diff(ib) != 1 {
                return Err(Refused::Escape.into());
            }
        }
        self.offsets()?;
        self.place_vias()?;
        self.ends()?;
        self.finish()
    }

    /// `Layouter._tip_clearance`.
    fn tip_clearance(&mut self, li: usize) -> Result<f64> {
        if let Some(c) = self.tip[li] {
            return Ok(c);
        }
        let net = self.lanes[li].net.clone();
        let mut best: Option<f64> = None;
        for k in 0..self.row.len() {
            let g = self.row[k];
            let sh = &self.spec.pads[g].1[0];
            if sh.net != net {
                let c = self.need[li][self.base[g]];
                best = Some(best.map_or(c, |b| b.max(c)));
            }
        }
        let c = match best {
            Some(c) => c,
            None => self.env.rules.clearance(self.env.py, &net, "", "")?,
        };
        self.tip[li] = Some(c);
        Ok(c)
    }

    /// `Layouter._step`: from an inner lane's centreline to the next one out.
    fn step(&mut self, inner: &Lane, outer: &Lane) -> Result<f64> {
        let gap = if self.paired.get(&inner.number) == Some(&outer.number) {
            self.env.rules.pair_gap(self.env.py, &inner.net)?
        } else {
            let mut gap = self.env.rules.clearance(self.env.py, &inner.net, &outer.net, "")?;
            if self.spec.turn {
                gap += self.env.grid_step / SQ2;
            }
            gap
        };
        let mut need = inner.width / 2.0 + outer.width / 2.0;
        if let Some(v) = inner.via {
            need = need.max(v.0 / 2.0 + outer.width / 2.0);
        }
        if let Some(v) = outer.via {
            need = need.max(inner.width / 2.0 + v.0 / 2.0);
        }
        Ok(need + gap)
    }

    /// `Layouter._lane_step`.
    fn lane_step(&mut self, li: usize) -> Result<f64> {
        let k = self.order.iter().position(|&i| i == li).unwrap_or(0);
        if k > 0 {
            let (inner, outer) = (self.lanes[self.order[k - 1]].clone(), self.lanes[li].clone());
            return self.step(&inner, &outer);
        }
        if self.order.len() > 1 {
            let (inner, outer) = (self.lanes[li].clone(), self.lanes[self.order[1]].clone());
            return self.step(&inner, &outer);
        }
        Ok(self.lanes[li].copper + self.tip_clearance(li)?)
    }

    /// `Layouter._offsets`.
    fn offsets(&mut self) -> Result<()> {
        if !self.spec.turn {
            return Ok(());
        }
        if self.spec.diagonal && self.spec.depth.is_none() {
            return self.staggered();
        }
        let mut prev: Option<usize> = None;
        for k in 0..self.order.len() {
            let li = self.order[k];
            let h = match prev {
                None => match self.spec.depth {
                    Some(d) => d,
                    None => self.lanes[li].copper + self.tip_clearance(li)?,
                },
                Some(p) => {
                    let (inner, outer) = (self.lanes[p].clone(), self.lanes[li].clone());
                    let step = self.step(&inner, &outer)?;
                    inner.h + if self.spec.diagonal { step * SQ2 - (inner.s - outer.s) } else { step }
                }
            };
            let corner = self.snap_out(self.at(self.lanes[li].s, self.tips + h));
            self.lanes[li].corner = corner;
            self.lanes[li].h = self.h_of(corner) - self.tips;
            prev = Some(li);
        }
        Ok(())
    }

    /// `Layouter._staggered`: the risers of lanes at 45, a step apart across their direction counted from the row's
    /// turn-side end.
    fn staggered(&mut self) -> Result<()> {
        let last = self.lanes[*self.order.last().unwrap_or(&0)].s;
        let mut sorted: Vec<(usize, f64)> = self.row.iter().map(|&g| (g, self.s_of(self.centre(g)))).collect();
        sorted.sort_by(|a, b| (-a.1).partial_cmp(&(-b.1)).unwrap_or(std::cmp::Ordering::Equal));
        let mut chain: Vec<(Lane, Option<usize>)> = Vec::new();
        for (g, s) in sorted {
            let number = &self.spec.pads[g].0;
            if let Some(&li) = self.at.get(number) {
                chain.push((self.lanes[li].clone(), Some(li)));
            } else if s >= last - 1e-9 {
                let c = self.centre(g);
                let net = self.spec.pads[g].1[0].net.clone();
                let width = if !net.is_empty() {
                    self.env.rules.width(self.env.py, &net)?
                } else {
                    self.lanes[self.order[0]].width
                };
                chain.push((Lane::new(number, &net, width, None, c, s), None));
            }
        }
        let mut prev: Option<Lane> = None;
        for k in 0..chain.len() {
            let mut lane = chain[k].0.clone();
            let mut h = match &prev {
                None => 0.0,
                Some(p) => p.h + self.step(p, &lane)? * SQ2 - (p.s - lane.s),
            };
            if let Some(li) = chain[k].1 {
                h = self.near_h(li, h)?;
            }
            lane.corner = self.snap_out(self.at(lane.s, self.tips + h));
            lane.h = self.h_of(lane.corner) - self.tips;
            if let Some(li) = chain[k].1 {
                self.lanes[li].corner = lane.corner;
                self.lanes[li].h = lane.h;
            }
            prev = Some(lane);
        }
        Ok(())
    }

    /// The row's pad shapes of another net than `lane`'s, other than the lane's own pad, with the clearance the
    /// lane keeps from each: `Layouter._near_h`'s and `_corner_least`'s `others`.
    fn row_others(&self, li: usize) -> Vec<(&'s PadShape, f64)> {
        let lane = &self.lanes[li];
        let spec: &'s Spec = self.spec;
        let mut out = Vec::new();
        for &g in &self.row {
            if spec.pads[g].0 == lane.number {
                continue;
            }
            for (k, sh) in spec.pads[g].1.iter().enumerate() {
                if sh.net != lane.net {
                    out.push((sh, self.need[li][self.base[g] + k]));
                }
            }
        }
        out
    }

    /// The tracks of a lane through `pts` and whether each is clear of `others` by its clearance:
    /// `row_clear` and `_corner_least.clear`.
    fn clear_of(&self, li: usize, pts: &[P], others: &[(&PadShape, f64)]) -> bool {
        let w = self.lanes[li].width;
        legs(pts).iter().all(|&(a, b)| {
            let poly = segment_polygon(a, b, w, self.env.cap_steps);
            others.iter().all(|(sh, need)| poly_distance(&poly, &sh.poly) >= need - TOL)
        })
    }

    /// `Layouter._near_h`: the offset past the tips of a lane at 45, from `floor`.
    fn near_h(&mut self, li: usize, mut floor: f64) -> Result<f64> {
        let lane = self.lanes[li].clone();
        let min_h = self.row.iter().map(|&g| self.extent(g).0).fold(f64::INFINITY, f64::min);
        let depth = self.tips - min_h + lane.width + self.tip_clearance(li)?;
        let own = lane.copper + self.tip_clearance(li)?;
        let has_others = !self.row_others(li).is_empty();
        let reach = self.env.reach;
        let mut work = lane;

        // lay(h): the lane's corner at h and the tracks from its pad through it to `depth` out
        let row_clear = |me: &mut Self, work: &mut Lane, h: f64| -> bool {
            let c = me.snap_out(me.at(work.s, me.tips + h));
            work.corner = c;
            let end = me.end_at(work, depth * SQ2);
            let others = me.row_others(li);
            me.clear_of(li, &[work.centre, c, end], &others)
        };
        if has_others && !row_clear(self, &mut work, floor) {
            let mut hi = floor.max(own);
            while !row_clear(self, &mut work, hi) {
                hi *= 2.0;
                if hi > reach {
                    return Ok(floor.max(own));
                }
            }
            floor = self.least(&mut work, li, depth, floor, hi, true)?;
        }
        if self.placed_clear(&mut work, li, depth, floor)? {
            return Ok(floor);
        }
        let step = self.env.step;
        let (mut prev, mut h) = (floor, floor + step);
        while h <= floor + reach + 1e-9 {
            if self.placed_clear(&mut work, li, depth, h)? {
                return self.least(&mut work, li, depth, prev, h, false);
            }
            prev = h;
            h += step;
        }
        Ok(floor)
    }

    /// `_near_h.placed_clear(h)`.
    fn placed_clear(&mut self, work: &mut Lane, li: usize, depth: f64, h: f64) -> Result<bool> {
        work.corner = self.snap_out(self.at(work.s, self.tips + h));
        let stub = self.stub_a(li, &[])?;
        let end = self.end_at(work, stub.max(depth * SQ2));
        let (net, w) = (work.net.clone(), work.width);
        for (a, b) in legs(&[work.centre, work.corner, end]) {
            if !self.env.free_track(&net, w, a, b) {
                return Ok(false);
            }
        }
        Ok(true)
    }

    /// `_near_h.least` and `_near_h.nm`: the least h in (lo, hi] where it is clear (`row`) or free of what is placed,
    /// to the nanometre.
    fn least(&mut self, work: &mut Lane, li: usize, depth: f64, mut lo: f64, mut hi: f64, row: bool) -> Result<f64> {
        for _ in 0..26 {
            let mid = (lo + hi) / 2.0;
            if self.near_ok(work, li, depth, mid, row)? {
                hi = mid;
            } else {
                lo = mid;
            }
        }
        let mut h = (hi * 1e6 - 1e-3).ceil() / 1e6;
        for _ in 0..8 {
            if self.near_ok(work, li, depth, h, row)? {
                return Ok(h);
            }
            h += 1e-6;
        }
        Ok(h)
    }

    fn near_ok(&mut self, work: &mut Lane, li: usize, depth: f64, h: f64, row: bool) -> Result<bool> {
        if !row {
            return self.placed_clear(work, li, depth, h);
        }
        let c = self.snap_out(self.at(work.s, self.tips + h));
        work.corner = c;
        let end = self.end_at(work, depth * SQ2);
        let others = self.row_others(li);
        Ok(self.clear_of(li, &[work.centre, c, end], &others))
    }

    // ---- the lane's own line
    /// `Layouter._direction`.
    fn direction(&self, lane: Option<&Lane>) -> P {
        if let Some(Lane { jog: Some(j), .. }) = lane {
            return ((j.0 + self.u.0) / SQ2, (j.1 + self.u.1) / SQ2);
        }
        if !self.spec.turn {
            return self.u;
        }
        if self.spec.diagonal {
            return ((self.t.0 + self.u.0) / SQ2, (self.t.1 + self.u.1) / SQ2);
        }
        self.t
    }

    /// `Layouter._end_at`.
    fn end_at(&self, lane: &Lane, a: f64) -> P {
        if self.spec.oblique {
            return self.oblique_end_at(lane, a);
        }
        if lane.jog.is_some() {
            if a > lane.ca {
                let (dx, dy) = self.direction(Some(lane));
                let m = ((a - lane.ca) / SQ2 * 1e6 - 1e-3).ceil() / 1e6;
                return (exact::round6(lane.corner.0 + m.copysign(dx)), exact::round6(lane.corner.1 + m.copysign(dy)));
            }
            return self.snap(self.at(lane.s, self.tips + a));
        }
        if !self.spec.turn {
            return self.snap(self.at(lane.s, self.tips + a));
        }
        let (dx, dy) = self.direction(None);
        if self.spec.diagonal {
            let m = (a / SQ2 * 1e6 - 1e-3).ceil() / 1e6;
            return (exact::round6(lane.corner.0 + m.copysign(dx)), exact::round6(lane.corner.1 + m.copysign(dy)));
        }
        self.snap((lane.corner.0 + a * dx, lane.corner.1 + a * dy))
    }

    /// `Layouter._oblique_end_at`.
    fn oblique_end_at(&self, lane: &Lane, a: f64) -> P {
        if lane.jog.is_some() && a > lane.ca {
            return run(lane.corner, self.direction(Some(lane)), a - lane.ca);
        }
        if lane.jog.is_some() || !self.spec.turn {
            return run(lane.centre, self.u, self.tips + a - self.h_of(lane.centre));
        }
        run(lane.corner, self.direction(None), a)
    }


    /// `Layouter._a_min`: how far along its lane its first via may stand.
    fn a_min(&self, lane: &Lane) -> f64 {
        if !self.spec.turn {
            return self.spec.depth.unwrap_or(0.0);
        }
        0.0_f64.max((self.row_end - lane.s) * if self.spec.diagonal { SQ2 } else { 1.0 })
    }

    /// `Layouter._segments`: the lane's copper as it stands, as segments.
    fn segments(&self, lane: &Lane, a: Option<f64>) -> Vec<(P, P)> {
        let reach = match a {
            None => self.a_min(lane) + self.env.reach,
            Some(a) => a,
        };
        let mut pts = vec![lane.centre];
        if self.spec.turn || lane.jog.is_some() {
            pts.push(lane.corner);
        }
        pts.push(self.end_at(lane, reach));
        let chamfer = self.spec.chamfer_of(&lane.number);
        let mut cuts = vec![chamfer_cuts(&pts, chamfer)];
        if a.is_none() && chamfer > 0.0 {
            cuts.push(chamfer_cuts(&pts, 0.0));
        }
        cuts.iter().flat_map(|cut| cut.windows(2).map(|w| (w[0], w[1])).collect::<Vec<_>>()).collect()
    }

    /// `Layouter._others_segments`: the copper of another lane as a via keeps clear of it; None where it is not known.
    fn others_segments(&mut self, oi: usize) -> Result<Option<Vec<(P, P)>>> {
        let other = self.lanes[oi].clone();
        if other.via_at.is_some() {
            return Ok(Some(self.segments(&other, Some(other.a))));
        }
        if self.spec.turn {
            return Ok(Some(self.segments(&other, None)));
        }
        if other.via.is_some() {
            return Ok(None);
        }
        let stub = self.stub_a(oi, &[])?;
        Ok(Some(self.segments(&other, Some(stub))))
    }

    fn polys_of(&self, segs: &[(P, P)], width: f64) -> Vec<Vec<P>> {
        segs.iter().map(|&(a, b)| segment_polygon(a, b, width, self.env.cap_steps)).collect()
    }

    fn clear_net(&mut self, a: usize, b: usize) -> Result<f64> {
        let (na, nb) = (self.lanes[a].net.clone(), self.lanes[b].net.clone());
        Ok(self.env.rules.clearance(self.env.py, &na, &nb, "")?)
    }

    /// `Layouter._pads_fails`, as a yes or no: whether a via of the lane at `q` keeps clear of the part's pads.
    fn pads_clear(&self, li: usize, q: P) -> bool {
        let size = self.lanes[li].via.map_or(0.0, |v| v.0);
        for (g, (_, shapes)) in self.spec.pads.iter().enumerate() {
            for (k, sh) in shapes.iter().enumerate() {
                let need = self.need[li][self.base[g] + k];
                if point_poly_distance(q, &sh.poly) - size / 2.0 < need - TOL {
                    return false;
                }
            }
        }
        true
    }

    /// `Layouter._via_fails` found nothing: whether a via of the lane at `q` is legal, `others` asking the board too.
    fn via_clear(&mut self, li: usize, q: P, others: bool) -> Result<bool> {
        let lane = self.lanes[li].clone();
        let (size, drill) = lane.via.unwrap_or((0.0, 0.0));
        if !self.pads_clear(li, q) {
            return Ok(false);
        }
        for oi in 0..self.lanes.len() {
            if oi == li || self.lanes[oi].net == lane.net {
                continue;
            }
            let need = self.clear_net(li, oi)?;
            if let Some(segs) = self.others_segments(oi)? {
                let other = &self.lanes[oi];
                let gap = if !self.spec.turn {
                    // the copper as it is drawn: a track's round end is a polygon outside its circle
                    self.polys_of(&segs, other.width).iter().map(|poly| point_poly_distance(q, poly))
                        .fold(f64::INFINITY, f64::min) - size / 2.0
                } else {
                    segs.iter().map(|&(a, b)| point_segment_distance(q, a, b)).fold(f64::INFINITY, f64::min)
                        - other.width / 2.0 - size / 2.0
                };
                if gap < need - TOL {
                    return Ok(false);
                }
            }
            let other = &self.lanes[oi];
            if let (Some(ov), Some(ovia)) = (other.via_at, other.via) {
                if dist(q, ov) - (size + ovia.0) / 2.0 < need - TOL {
                    return Ok(false);
                }
            }
        }
        for oi in 0..self.lanes.len() {
            let other = &self.lanes[oi];
            if oi == li {
                continue;
            }
            if let (Some(ov), Some(ovia)) = (other.via_at, other.via) {
                if dist(q, ov) - (drill + ovia.1) / 2.0 < self.env.hole_to_hole - TOL {
                    return Ok(false);
                }
            }
        }
        if !self.spec.turn && !self.path_clear(li, q, others)? {
            return Ok(false);
        }
        if others && !self.env.via_free(q, &lane.net, size, drill)? {
            return Ok(false);
        }
        Ok(true)
    }

    /// `Layouter._path_fails`, as a yes or no: the lane's own copper out to a via at `q` (a lane without a turn).
    fn path_clear(&mut self, li: usize, q: P, others: bool) -> Result<bool> {
        let lane = self.lanes[li].clone();
        let mut pts = vec![lane.centre];
        if lane.jog.is_some() {
            pts.push(lane.corner);
        }
        pts.push(q);
        let pts: Vec<P> = (0..pts.len()).filter(|&i| i == 0 || pts[i] != pts[i - 1]).map(|i| pts[i]).collect();
        let w = lane.width;
        let mine = legs(&pts);
        let mine_polys = self.polys_of(&mine, w);
        for oi in 0..self.lanes.len() {
            if oi == li || self.lanes[oi].net == lane.net {
                continue;
            }
            let need = self.clear_net(li, oi)?;
            let other = &self.lanes[oi];
            if let (Some(ov), Some(ovia)) = (other.via_at, other.via) {
                let gap = mine_polys.iter().map(|poly| point_poly_distance(ov, poly)).fold(f64::INFINITY, f64::min)
                    - ovia.0 / 2.0;
                if gap < need - TOL {
                    return Ok(false);
                }
            }
        }
        if lane.jog.is_none() {
            return Ok(true);
        }
        for oi in 0..self.lanes.len() {
            if oi == li || self.lanes[oi].net == lane.net {
                continue;
            }
            let segs = match self.others_segments(oi)? {
                Some(s) if !s.is_empty() => s,
                _ => continue,
            };
            let need = self.clear_net(li, oi)?;
            let theirs = self.polys_of(&segs, self.lanes[oi].width);
            let gap = mine_polys.iter().flat_map(|t| theirs.iter().map(move |u| poly_distance(t, u)))
                .fold(f64::INFINITY, f64::min);
            if gap < need - TOL {
                return Ok(false);
            }
        }
        let spec = self.spec;
        let boxes: Vec<Bounds> = mine_polys.iter().map(|p| bounds(p)).collect();
        for (g, (_, shapes)) in spec.pads.iter().enumerate() {
            for (k, sh) in shapes.iter().enumerate() {
                if sh.net == lane.net {
                    continue;
                }
                let need = self.need[li][self.base[g] + k];
                if !boxes.iter().any(|&b| crate::shapes::box_overlaps(b, sh.bbox, need)) {
                    continue;
                }
                let gap = mine_polys.iter().map(|t| poly_distance(t, &sh.poly)).fold(f64::INFINITY, f64::min);
                if gap < need - TOL {
                    return Ok(false);
                }
            }
        }
        if others {
            for &(a, b) in &mine {
                if !self.env.free_track(&lane.net, w, a, b) {
                    return Ok(false);
                }
            }
        }
        Ok(true)
    }

    fn clear_at(&mut self, li: usize, judge: Judge, a: f64) -> Result<bool> {
        let q = self.end_at(&self.lanes[li].clone(), a);
        match judge {
            Judge::Pads => Ok(self.pads_clear(li, q)),
            Judge::Via { others } => self.via_clear(li, q, others),
        }
    }

    /// `Layouter._first`: the first `a` along the lane, from `a_from`, where `judge` finds nothing wrong: looked for at
    /// `env.step`, then bisected back to the nearest nanometre.
    fn first(&mut self, li: usize, judge: Judge, a_from: f64) -> Result<Option<f64>> {
        let (reach, step) = (self.env.reach, self.env.step);
        let (mut a, mut prev) = (a_from, None);
        while a <= a_from + reach + 1e-9 {
            if self.clear_at(li, judge, a)? {
                let Some(p) = prev else { return Ok(Some(a)) };
                let (mut lo, mut hi) = (p, a);
                for _ in 0..26 {
                    let mid = (lo + hi) / 2.0;
                    if self.clear_at(li, judge, mid)? {
                        hi = mid;
                    } else {
                        lo = mid;
                    }
                }
                hi = (hi * 1e6 - 1e-3).ceil() / 1e6;
                for _ in 0..8 {
                    // the point is rounded to the nanometre too: never short of legal
                    if self.clear_at(li, judge, hi)? {
                        return Ok(Some(hi));
                    }
                    hi += 1e-6;
                }
                return Ok(Some(a));
            }
            prev = Some(a);
            a += step;
        }
        Ok(None)
    }

    /// `Layouter._scan`: the first `a` along the lane with a legal via there.
    fn scan(&mut self, li: usize, others: bool, a_from: Option<f64>) -> Result<Option<f64>> {
        let a0 = match a_from {
            Some(a) => a,
            None => self.a_min(&self.lanes[li].clone()),
        };
        let Some(start) = self.first(li, Judge::Pads, a0)? else { return Ok(None) };
        self.first(li, Judge::Via { others }, start)
    }

    // ---- a lane that jogs
    /// `Layouter._set_corner`.
    fn set_corner(&mut self, li: usize, c: f64) {
        let corner = self.snap_out(self.at(self.lanes[li].s, self.tips + c));
        self.lanes[li].corner = corner;
        self.lanes[li].ca = self.h_of(corner) - self.tips;
    }

    /// `_corner_least.clear`.
    fn corner_clear(&mut self, li: usize, c: f64, depth: f64) -> bool {
        self.set_corner(li, c);
        let lane = self.lanes[li].clone();
        let end = self.end_at(&lane, lane.ca + depth);
        let others = self.row_others(li);
        self.clear_of(li, &[lane.centre, lane.corner, end], &others)
    }

    /// `Layouter._corner_least`: how far out a lane that jogs runs straight before it does, the lane's corner left
    /// set; None where none within the search's reach does.
    fn corner_least(&mut self, li: usize) -> Result<Option<f64>> {
        let lane = self.lanes[li].clone();
        let min_h = self.row.iter().map(|&g| self.extent(g).0).fold(f64::INFINITY, f64::min);
        let depth = (self.tips - min_h + lane.width + self.tip_clearance(li)?) * SQ2;
        let floor = self.a_min(&lane);
        if self.corner_clear(li, floor, depth) {
            return Ok(Some(self.lanes[li].ca));
        }
        let (mut lo, mut hi) = (floor, floor.max(self.env.step));
        while !self.corner_clear(li, hi, depth) {
            lo = hi;
            hi *= 2.0;
            if hi > self.env.reach {
                return Ok(None);
            }
        }
        for _ in 0..26 {
            let mid = (lo + hi) / 2.0;
            if self.corner_clear(li, mid, depth) {
                hi = mid;
            } else {
                lo = mid;
            }
        }
        hi = (hi * 1e6 - 1e-3).ceil() / 1e6;
        for _ in 0..8 {
            if self.corner_clear(li, hi, depth) {
                return Ok(Some(self.lanes[li].ca));
            }
            hi += 1e-6;
        }
        Ok(Some(self.lanes[li].ca))
    }

    /// `Layouter._jogged`: the nearest via a lane without a turn finds by jogging at 45 along the row, to either side:
    /// (how far out it stands, the way it jogs, its corner, where the corner is, and how far along the lane the via
    /// is), or None. The lane's own state is left as it was.
    fn jogged(&mut self, li: usize, others: bool) -> Result<Option<(f64, P, P, f64, f64)>> {
        let mut best: Option<(f64, P, P, f64, f64)> = None;
        let was = (self.lanes[li].jog, self.lanes[li].corner, self.lanes[li].ca);
        for sign in [1.0, -1.0] {
            self.lanes[li].jog = Some((self.t.0 * sign, self.t.1 * sign));
            if self.corner_least(li)?.is_some() {
                let ca = self.lanes[li].ca;
                if let Some(a) = self.scan(li, others, Some(ca))? {
                    let lane = self.lanes[li].clone();
                    let q = self.end_at(&lane, a);
                    let h = self.h_of(q);
                    if best.is_none_or(|b| h < b.0 - 1e-9) {
                        best = Some((h, lane.jog.unwrap_or((0.0, 0.0)), lane.corner, lane.ca, a));
                    }
                }
            }
        }
        (self.lanes[li].jog, self.lanes[li].corner, self.lanes[li].ca) = was;
        Ok(best)
    }

    /// `Layouter._place_vias`.
    fn place_vias(&mut self) -> Result<()> {
        for k in 0..self.order.len() {
            let li = self.order[k];
            if self.lanes[li].via.is_none() {
                continue;
            }
            let jogging = !self.spec.turn;
            let mut a = self.scan(li, true, None)?;
            let mut jogged = if a.is_none() && jogging { self.jogged(li, true)? } else { None };
            if a.is_none() && jogged.is_none() {
                a = self.scan(li, false, None)?;
                jogged = if a.is_none() && jogging { self.jogged(li, false)? } else { None };
                if a.is_none() && jogged.is_none() {
                    return Err(Refused::Escape.into());
                }
                if let Some((_, jog, corner, ca, ja)) = jogged {
                    self.lanes[li].jog = Some(jog);
                    self.lanes[li].corner = corner;
                    self.lanes[li].ca = ca;
                    a = Some(ja);
                }
                let at = a.unwrap_or(0.0);
                self.lanes[li].a = at;
                self.lanes[li].blocked_why = true;
                // Python works out why the via has no spot here, asking the board of the same place
                let q = self.end_at(&self.lanes[li].clone(), at);
                self.via_clear(li, q, true)?;
            } else if let Some((_, jog, corner, ca, ja)) = jogged {
                self.lanes[li].jog = Some(jog);
                self.lanes[li].corner = corner;
                self.lanes[li].ca = ca;
                a = Some(ja);
            }
            let at = a.unwrap_or(0.0);
            self.lanes[li].a = at;
            self.lanes[li].via_at = Some(self.end_at(&self.lanes[li].clone(), at));
        }
        Ok(())
    }

    /// `Layouter._stub_a`: how far a lane with no via runs along its lane.
    fn stub_a(&mut self, li: usize, placed: &[usize]) -> Result<f64> {
        let spec = self.spec;
        if !spec.turn {
            return match spec.depth {
                Some(d) => Ok(d),
                None => Ok(self.lanes[li].copper + self.tip_clearance(li)?),
            };
        }
        if spec.diagonal {
            if let Some(r) = spec.run {
                return Ok(r);
            }
        }
        let level = if let Some(r) = spec.run {
            self.row_end + r
        } else if !placed.is_empty() {
            placed.iter().map(|&p| self.s_of(self.lanes[p].via_at.unwrap_or((0.0, 0.0)))).fold(f64::NEG_INFINITY, f64::max)
        } else {
            self.row_end + self.lane_step(li)?
        };
        Ok(0.0_f64.max((level - self.lanes[li].s) * if spec.diagonal { SQ2 } else { 1.0 }))
    }

    /// `Layouter._ends`: a lane with no via ends level with the outermost via, or one step past the row's turn-side
    /// end where there is none.
    fn ends(&mut self) -> Result<()> {
        let placed: Vec<usize> = (0..self.lanes.len()).filter(|&i| self.lanes[i].via_at.is_some()).collect();
        for k in 0..self.order.len() {
            let li = self.order[k];
            if self.lanes[li].via_at.is_some() {
                continue;
            }
            let a = self.stub_a(li, &placed)?;
            self.lanes[li].a = a;
            self.lanes[li].end_at = self.end_at(&self.lanes[li].clone(), a);
        }
        for &li in &placed {
            self.lanes[li].end_at = self.lanes[li].via_at.unwrap_or((0.0, 0.0));
        }
        Ok(())
    }

    /// `Layouter._finish`: the tracks and the via of each lane, and which of them meet something placed.
    fn finish(&mut self) -> Result<Laid> {
        let spec = self.spec;
        let mut out = Vec::new();
        for k in 0..self.order.len() {
            let lane = self.lanes[self.order[k]].clone();
            let mut pts = vec![lane.centre];
            if spec.turn || lane.jog.is_some() {
                pts.push(lane.corner);
            }
            pts.push(lane.end_at);
            let pts: Vec<P> = (0..pts.len()).filter(|&i| i == 0 || pts[i] != pts[i - 1]).map(|i| pts[i]).collect();
            let cut = chamfer_cuts(&pts, spec.chamfer_of(&lane.number));
            let tracks = legs(&cut);
            let mut blocked = lane.blocked_why;
            for &(a, b) in &tracks {
                if !self.env.free_track(&lane.net, lane.width, a, b) {
                    blocked = true;
                }
            }
            if let (Some(at), Some(v)) = (lane.via_at, lane.via) {
                if !self.env.free_via(&lane.net, at, v.0) {
                    blocked = true;
                }
            }
            out.push(LaneOut { number: lane.number.clone(), points: pts, tracks, via: lane.via_at, blocked });
        }
        Ok(Laid { lanes: out })
    }
}

/// `Layouter._run`: the point `a` from `p` along the unit vector `d`, not rounded.
fn run(p: P, d: P, a: f64) -> P {
    if d.0.abs() < 1e-9 || d.1.abs() < 1e-9 {
        if d.0.abs() > d.1.abs() {
            return (p.0 + a.copysign(d.0), p.1);
        }
        return (p.0, p.1 + a.copysign(d.1));
    }
    let m = a / SQ2;
    (p.0 + m.copysign(d.0), p.1 + m.copysign(d.1))
}

// ------------------------------------------------------------------ from Python

/// `lanes.EscapeDecl`, as Python hands it over: (pins, whether it turns, the pins whose lane ends in a via, depth, run,
/// widths, pairs, chamfer, chamfers, via size, via drill).
pub type PyDecl = (
    Vec<String>, bool, Vec<String>, Option<f64>, Option<f64>, Vec<(String, f64)>, Vec<(String, String)>, f64,
    Vec<(String, f64)>, f64, f64,
);
/// A pad's lands: (outline, box, net, owner), and the pads by number.
pub type PyPads = Vec<(String, Vec<(Vec<P>, Bounds, String, String)>)>;
/// The row's frame: (the way out, the way along the row toward the turn, whether the lanes run at 45 to the row, whether
/// the frame is at 45 to the board's axes).
pub type PyFrame = (P, P, bool, bool);
/// The board and the script as the layout asks of them: (the via search's step and reach, the hole-to-hole rule, the
/// router's grid step, the lanes' copper layer as a bit and its faces, every copper layer as bits, the board's, the
/// cap steps of a track's end, how far from a box another's copper is looked for).
pub type PyEnv = (f64, f64, f64, f64, u32, u8, u32, u32, usize, f64);
/// The boxes of the places a layout asked the board about, kept to say whether a candidate that changes the board comes
/// near any of them (`layout._asked_near`).
#[pyclass]
pub struct Asked {
    boxes: Vec<Bounds>,
}

#[pymethods]
impl Asked {
    /// Whether any of the boxes lies within `reach` of any of `changed`.
    fn near(&self, changed: Vec<Bounds>, reach: f64) -> bool {
        self.boxes.iter().any(|&b| changed.iter().any(|&c| crate::shapes::box_overlaps(b, c, reach)))
    }

    /// The boxes, as (left, top, right, bottom).
    fn boxes(&self) -> Vec<Bounds> {
        self.boxes.clone()
    }
}

/// What comes of a layout: (whether it could not be laid out, the lanes blocked, the boxes asked about), and with
/// `full` each lane's (number, points, tracks, via, whether blocked).
pub type PyLaid = (bool, usize, Asked, Option<Vec<(String, Vec<P>, Vec<(P, P)>, Option<P>, bool)>>);

#[allow(clippy::too_many_arguments)]
pub fn lay_out(
    py: Python<'_>,
    view: &View,
    rules: &mut Rules,
    decl: PyDecl,
    pads: PyPads,
    lands: Vec<(String, Vec<usize>)>,
    frame: PyFrame,
    env: PyEnv,
    tie_nets: Option<Vec<String>>,
    own: Vec<Item>,
    npth: Vec<Item>,
    obstacles: &ViaObstacles,
    off_board: &Bound<'_, PyAny>,
    full: bool,
) -> PyResult<Option<PyLaid>> {
    let (pins, turn, vias, depth, run, widths, pairs, chamfer, chamfers, via_size, via_drill) = decl;
    let spec = Spec {
        pins, turn, vias: vias.into_iter().collect(), depth, run, widths: widths.into_iter().collect(), pairs, chamfer,
        chamfers: chamfers.into_iter().collect(), via_size, via_drill,
        pads: pads
            .into_iter()
            .map(|(n, shapes)| {
                (n, shapes.into_iter().map(|(poly, bbox, net, owner)| PadShape { poly, bbox, net, owner }).collect())
            })
            .collect(),
        lands: lands.into_iter().collect(), u: frame.0, t: frame.1, diagonal: frame.2, oblique: frame.3,
    };
    let (step, reach, hole_to_hole, grid_step, layer, layer_faces, via_layers, board_layers, cap_steps, copper_reach) = env;
    let env = Env {
        py, rules, view, obstacles, off_board, step, reach, hole_to_hole, grid_step, layer, layer_faces, via_layers,
        board_layers, cap_steps, copper_reach, tie_nets: tie_nets.map(|n| n.into_iter().collect()), own, npth,
        asked: Vec::new(),
    };
    let mut layouter = Layouter::new(&spec, env);
    let laid = layouter.lay_out();
    let mut asked = layouter.into_asked();
    asked.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    asked.dedup();
    match laid {
        Ok(laid) => {
            let lanes = full.then(|| {
                laid.lanes.iter().map(|l| (l.number.clone(), l.points.clone(), l.tracks.clone(), l.via, l.blocked)).collect()
            });
            Ok(Some((false, laid.blocked(), Asked { boxes: asked }, lanes)))
        }
        Err(Failure::Refused(Refused::Escape)) => Ok(Some((true, 0, Asked { boxes: asked }, None))),
        Err(Failure::Refused(Refused::Unsupported)) => Ok(None),
        Err(Failure::Python(e)) => Err(e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_coordinate_is_rounded_away_from_the_row_to_the_nanometre() {
        assert_eq!(away(1.0000004, 1.0), 1.000001);
        assert_eq!(away(1.0000004, -1.0), 1.0);
        assert_eq!(away(1.0 + 1e-10, 1.0), 1.0, "float noise under 1e-9 mm is not rounded up");
    }

    #[test]
    fn a_right_angle_is_cut_back_along_both_legs_and_a_short_leg_cuts_less() {
        let corner = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)];
        assert_eq!(chamfer_cuts(&corner, 0.5), vec![(0.0, 0.0), (1.5, 0.0), (2.0, 0.5), (2.0, 2.0)]);
        assert_eq!(chamfer_cuts(&corner, 5.0), vec![(0.0, 0.0), (1.0, 0.0), (2.0, 1.0), (2.0, 2.0)]);
        assert_eq!(chamfer_cuts(&corner, 0.0), corner.to_vec());
        let diagonal = [(0.0, 0.0), (1.0, 1.0), (2.0, 1.0)];
        assert_eq!(chamfer_cuts(&diagonal, 0.5), diagonal.to_vec(), "a turn made of 45s is drawn as meant");
    }

    #[test]
    fn a_polyline_has_a_leg_for_each_pair_of_points_that_differ() {
        assert_eq!(legs(&[(0.0, 0.0), (0.0, 0.0), (1.0, 0.0)]), vec![((0.0, 0.0), (1.0, 0.0))]);
        assert!(legs(&[(1.0, 1.0)]).is_empty());
    }

    #[test]
    fn a_lane_runs_along_an_axis_or_at_45_by_the_distance_asked() {
        assert_eq!(run((1.0, 1.0), (0.0, -1.0), 2.0), (1.0, -1.0));
        assert_eq!(run((1.0, 1.0), (-1.0, 0.0), 2.0), (-1.0, 1.0));
        let (x, y) = run((0.0, 0.0), (SQ2 / 2.0, SQ2 / 2.0), 2.0);
        assert!((x - SQ2).abs() < 1e-12 && (y - SQ2).abs() < 1e-12);
    }
}
