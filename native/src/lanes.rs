//! What an escape's layout asks of the board it is laid out on, ported from `src/placemat/occupancy.py`
//! (`copper_conflicts`, `hole_conflicts`, `_conflict` with `exact=True`, `_copper_gap`) and `layout.py`
//! (`Board._via_site_why`): whether a lane's track or a via's site meets anything placed.
//!
//! A layout asks thousands of such questions of a board that stays as it is, and wants only the answer yes or no
//! (the refusal that says why is Python's, asked for once the answer is yes). `Held` is the copper of one board
//! in a grid; `View` is that board with some of its shapes hidden and some others added, which is how one
//! candidate's board differs from the board it was made from.
//!
//! The copper conflict is the one `Occupancy._conflict` finds with `exact=True`: a copper gap is measured as
//! KiCad's DRC measures it (a track as the segment it is, a via as its circle, a pad as the effective shape it was
//! read with), where `shapes::conflict` measures the polygons the placement search judges by.

use crate::exact;
use crate::geometry::{point_in_polygon, point_segment_distance, poly_distance, polys_overlap, Point};
use crate::shapes::{self, Bounds, ConflictConfig, Shape, ShapeGrid};
use crate::ties::{self, K};
use std::collections::HashSet;
use std::sync::Arc;

/// What the exact copper gap reads of a shape beyond its polygon (`occupancy.Shape`'s `segment`, `circle`,
/// `drawn`).
#[derive(Clone, Default)]
pub struct Extra {
    /// A straight track: (ax, ay, bx, by, width), mm.
    pub segment: Option<(f64, f64, f64, f64, f64)>,
    /// A via: (x, y, radius), mm.
    pub circle: Option<(f64, f64, f64)>,
    /// A drawn copper polygon: (outlines, stroke width, filled).
    pub drawn: Option<(Vec<Vec<Point>>, f64, bool)>,
}

/// A shape and its extras. `shape.bbox` is the shape's own box (`occupancy.Shape.box`), which is not always the
/// bounds of its polygon.
pub struct Item {
    pub shape: Shape,
    pub extra: Extra,
}

/// Which pool of a board a question is asked of: `copper_conflicts`' (the placed pads and all the copper), or
/// `hole_conflicts`' (the pads and copper that are copper).
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Pool {
    Copper,
    Hole,
}

/// A drilled hole: its centre, diameter and net (`Board._via_obstacles`).
pub type Hole = (f64, f64, f64, String);
/// An unplated hole: its centre and diameter.
pub type Bare = (f64, f64, f64);

/// The shapes of a board as the escape layouts ask of them, in a grid, and its drilled holes.
pub struct Held {
    grid: ShapeGrid,
    extra: Vec<Extra>,
    cfg: ConflictConfig,
    /// `Occupancy._copper_reach`: how far from a box another's copper is looked for.
    reach: f64,
    holes: Vec<Hole>,
    bare: Vec<Bare>,
}

impl Held {
    pub fn new(items: Vec<Item>, holes: Vec<Hole>, bare: Vec<Bare>, cfg: ConflictConfig, reach: f64) -> Held {
        let (shapes, extra): (Vec<Shape>, Vec<Extra>) = items.into_iter().map(|i| (i.shape, i.extra)).unzip();
        Held { grid: ShapeGrid::new(shapes), extra, cfg, reach, holes, bare }
    }

    pub fn cfg(&self) -> &ConflictConfig {
        &self.cfg
    }
}

/// A `Held` board less the shapes and holes that are hidden and with some more.
pub struct View {
    held: Arc<Held>,
    hidden: Vec<bool>,
    extras: Vec<Item>,
    hidden_holes: Vec<bool>,
    holes: Vec<Hole>,
    hidden_bare: Vec<bool>,
    bare: Vec<Bare>,
}

fn mask(len: usize, hidden: &[usize]) -> Vec<bool> {
    let mut mask = vec![false; len];
    for &i in hidden {
        if let Some(m) = mask.get_mut(i) {
            *m = true;
        }
    }
    mask
}

fn within(a: Bounds, b: Bounds, gap: f64) -> bool {
    shapes::box_overlaps(a, b, gap)
}

impl View {
    pub fn new(held: Arc<Held>, hidden: &[usize], extras: Vec<Item>, hidden_holes: &[usize], holes: Vec<Hole>,
               hidden_bare: &[usize], bare: Vec<Bare>) -> View {
        View {
            hidden: mask(held.grid.shapes.len(), hidden), extras, hidden_holes: mask(held.holes.len(), hidden_holes),
            holes, hidden_bare: mask(held.bare.len(), hidden_bare), bare, held,
        }
    }

    pub fn cfg(&self) -> &ConflictConfig {
        self.held.cfg()
    }

    /// Whether `probe` meets any shape of `pool` within reach of it.
    pub fn meets(&self, probe: &Item, pool: Pool) -> bool {
        let h = &*self.held;
        let mut near = Vec::new();
        h.grid.near_into(probe.shape.bbox, h.reach, &mut near);
        for oi in near {
            if !self.hidden[oi] && conflicts(probe, &h.grid.shapes[oi], &h.extra[oi], pool, &h.cfg) {
                return true;
            }
        }
        self.extras.iter().any(|o| {
            within(probe.shape.bbox, o.shape.bbox, h.reach) && conflicts(probe, &o.shape, &o.extra, pool, &h.cfg)
        })
    }
}

/// `Occupancy._conflict(probe, o, None, exact=True)`, as a yes or no: for two pieces of copper the exact one,
/// else the placement search's own rule.
pub(crate) fn conflicts(probe: &Item, o: &Shape, ox: &Extra, pool: Pool, cfg: &ConflictConfig) -> bool {
    let both = probe.shape.kind.is_copperish() && o.kind.is_copperish();
    match pool {
        Pool::Hole if !o.kind.is_copperish() => false,
        _ if both => copper_conflict(&probe.shape, &probe.extra, o, ox, cfg),
        _ => shapes::conflict(&probe.shape, o, None, cfg),
    }
}

/// Python's `_box_gap`: its distance is `math.hypot`.
fn box_gap(a: Bounds, b: Bounds) -> f64 {
    let dx = if a.0 > b.2 { a.0 - b.2 } else if b.0 > a.2 { b.0 - a.2 } else { 0.0 };
    let dy = if a.1 > b.3 { a.1 - b.3 } else if b.1 > a.3 { b.1 - a.3 } else { 0.0 };
    if dy == 0.0 { dx } else if dx == 0.0 { dy } else { exact::hypot(dx, dy) }
}

/// The copper branch of `Occupancy._conflict(s, o, None, exact=True)`.
fn copper_conflict(s: &Shape, sx: &Extra, o: &Shape, ox: &Extra, cfg: &ConflictConfig) -> bool {
    if s.layers & o.layers == 0 {
        return false;
    }
    if !s.net.is_empty() && s.net == o.net {
        return false;
    }
    let clr = cfg.pair_clearance(None, s, o);
    let limit = shapes::clear_limit(clr, cfg.epsilon);
    if box_gap(s.bbox, o.bbox) >= limit {
        return false;
    }
    let gap = copper_gap(s, sx, o, ox, limit);
    gap < limit && !ties::net_tie_exclusion(s, o, clr, cfg.tie_eps)
}

/// `Occupancy._copper_gap`: `module_gap`, and where that is under `limit` and a pad or a footprint's copper was read
/// from KiCad, measured as the effective shape KiCad's DRC collides.
fn copper_gap(s: &Shape, sx: &Extra, o: &Shape, ox: &Extra, limit: f64) -> f64 {
    let gap = module_gap(s, sx, o, ox);
    if gap >= limit {
        return gap;
    }
    let (ks, ko) = (read_shape(s), read_shape(o));
    if ks.is_none() && ko.is_none() {
        return gap;
    }
    let far = box_gap(s.bbox, o.bbox) + 1.0;
    let a = ks.unwrap_or_else(|| kicad_of(s, sx));
    let b = ko.unwrap_or_else(|| kicad_of(o, ox));
    match ties::collide(&a, &b, ties::to_nm(far)) {
        Some((actual, _)) => actual as f64 / 1e6,
        None => gap,
    }
}

/// `occupancy._copper_gap`: the gap between two pieces of copper, a via measured as its circle and a straight track
/// and a drawn polygon by KiCad's own collisions.
fn module_gap(s: &Shape, sx: &Extra, o: &Shape, ox: &Extra) -> f64 {
    if sx.segment.is_some() || ox.segment.is_some() || sx.drawn.is_some() || ox.drawn.is_some() {
        let far = box_gap(s.bbox, o.bbox) + 1.0;
        if let Some((actual, _)) = ties::collide(&kicad_of(s, sx), &kicad_of(o, ox), ties::to_nm(far)) {
            return actual as f64 / 1e6;
        }
    }
    match (sx.circle, ox.circle) {
        (Some((ax, ay, ar)), Some((bx, by, br))) => (exact::hypot(ax - bx, ay - by) - ar - br).max(0.0),
        (Some((cx, cy, r)), None) => circle_gap((cx, cy), r, &o.poly),
        (None, Some((cx, cy, r))) => circle_gap((cx, cy), r, &s.poly),
        (None, None) => poly_distance(&s.poly, &o.poly),
    }
}

fn circle_gap(c: Point, r: f64, poly: &[Point]) -> f64 {
    if point_in_polygon(c, poly) {
        return 0.0;
    }
    let n = poly.len();
    let d = (0..n).map(|i| point_segment_distance(c, poly[i], poly[(i + 1) % n])).fold(f64::INFINITY, f64::min);
    (d - r).max(0.0)
}

/// `occupancy._kicad_of`: a shape as `kicad_collide` collides it (nm).
fn kicad_of(s: &Shape, x: &Extra) -> Vec<K> {
    let nm = |p: &Point| (ties::to_nm(p.0), ties::to_nm(p.1));
    if let Some((outlines, width, filled)) = &x.drawn {
        let mut parts = Vec::new();
        for outline in outlines {
            let pts: Vec<(i64, i64)> = outline.iter().map(nm).collect();
            if *filled {
                parts.push(K::P(pts.clone()));
            }
            if *width > 0.0 || !*filled {
                let w = ties::to_nm(*width);
                for k in 0..pts.len() {
                    let (a, b) = (pts[k], pts[(k + 1) % pts.len()]);
                    parts.push(K::S(a.0, a.1, b.0, b.1, w));
                }
            }
        }
        return parts;
    }
    if let Some((ax, ay, bx, by, w)) = x.segment {
        return vec![K::S(ties::to_nm(ax), ties::to_nm(ay), ties::to_nm(bx), ties::to_nm(by), ties::to_nm(w))];
    }
    if let Some((cx, cy, r)) = x.circle {
        return vec![K::C(ties::to_nm(cx), ties::to_nm(cy), ties::to_nm(r))];
    }
    vec![K::P(s.poly.iter().map(nm).collect())]
}

/// `Occupancy._read_shape`: the effective shape KiCad's DRC collides for a footprint's pad or copper drawing whose
/// shape was read and whose outline stands as `s.poly`, else None.
fn read_shape(s: &Shape) -> Option<Vec<K>> {
    let info = s.tie.as_deref()?;
    if !info.fp_copper {
        return None;
    }
    let (m, shapes) = ties::read_of(info, &s.poly)?;
    if shapes.is_empty() {
        return None;
    }
    Some(ties::move_shapes(shapes, m))
}

/// What a via's site is judged against beside the copper and the holes of the board (`Board._via_obstacles`): the
/// outline and the nets let through of every area that forbids vias.
pub struct ViaObstacles {
    pub forbidding: Vec<(Vec<Point>, HashSet<String>)>,
}

/// The via of `Board._via_site_why` after its edge and the copper planned in a batch (a layout has none): whether a
/// via of `net`, `size` and `drill` at `c` stands clear of the copper (`ring`, its copper, as a shape), the copper
/// its drill keeps the hole clearance from (`hole`), the drilled holes, the unplated ones and the areas that forbid
/// it.
pub fn via_site_free(view: &View, ring: &Item, hole: &Item, c: Point, net: &str, size: f64, drill: f64,
                     obs: &ViaObstacles) -> bool {
    if view.meets(ring, Pool::Copper) || view.meets(hole, Pool::Hole) {
        return false;
    }
    let cfg = view.held.cfg();
    let (hole_to_hole, hole_clearance) = (cfg.hole_to_hole, cfg.hole_clearance);
    let held = &*view.held;
    let holes = held.holes.iter().zip(&view.hidden_holes).filter(|(_, hidden)| !**hidden).map(|(h, _)| h);
    for (x, y, dia, hole_net) in holes.chain(&view.holes) {
        let d = exact::hypot(c.0 - x, c.1 - y);
        if d - (drill + dia) / 2.0 < hole_to_hole - 1e-9 {
            return false;
        }
        if hole_net != net && d - (size + dia) / 2.0 < hole_clearance - 1e-9 {
            return false;
        }
    }
    let bare = held.bare.iter().zip(&view.hidden_bare).filter(|(_, hidden)| !**hidden).map(|(b, _)| b);
    for (x, y, dia) in bare.chain(&view.bare) {
        let d = exact::hypot(c.0 - x, c.1 - y);
        if d - (drill + dia) / 2.0 < hole_to_hole - 1e-9 || d - (size + dia) / 2.0 < hole_clearance - 1e-9 {
            return false;
        }
    }
    !obs.forbidding.iter().any(|(poly, allowed)| !allowed.contains(net) && polys_overlap(&ring.shape.poly, poly))
}
