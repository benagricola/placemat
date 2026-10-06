//! Obstacle registration and the near-obstacle conflict search, ported from
//! `src/placemat/occupancy.py`'s `ShapeIndex`, `_conflict` and
//! `_drawn_conflict`.
//!
//! This module answers ONE question: for a candidate's own (already
//! transformed) shapes, which registered obstacle shape is the FIRST one
//! `Occupancy.legal()`'s Python loop would find a conflict with, walking
//! shapes and obstacles in the same order Python does? It returns that pair
//! by index, nothing else - no reason string, no blame. Python re-runs its
//! own, unmodified `_conflict` / `_drawn_conflict` on the identified pair to
//! produce the text a script sees, so the message is always the reference
//! implementation's, byte for byte. See
//! docs/superpowers/specs/2026-09-24-native-core-design.md ("Phase 2").
//!
//! `ShapeIndex.near()`'s own two-stage filter (a coarse pass at the
//! candidate's overall reach and gap, then a precise pass per shape at its
//! own box and gap) is a performance detail, not a correctness one: the
//! coarse box is provably a superset of the precise one (`Occupancy.__init__`
//! asserts `_gap >= gap_for(s)` for every shape kind, and `reach` always
//! contains any one shape's box), so a single per-shape grid query at the
//! shape's own box and gap finds exactly the same obstacles `near` + `close`
//! would, in the same order, without needing the two-stage split.

use crate::geometry::{point_in_polygon, point_segment_distance, poly_distance_below, polys_overlap, Point};
use std::collections::{HashMap, HashSet};
use std::hash::BuildHasherDefault;

/// The registered shapes of each cell of a `ShapeGrid`, by (column, row).
type CellMap = HashMap<(i64, i64), Vec<usize>, BuildHasherDefault<crate::ratsnest::Fx>>;

/// A set of obstacle indices. The give-way search asks it once per obstacle near each offset it tries, so the
/// hash is `Fx`'s, not the default's; the set is only asked, never walked.
pub type IdSet = HashSet<usize, BuildHasherDefault<crate::ratsnest::Fx>>;

/// A net's own clearance, by its name: asked twice for each pair of shapes judged, never walked in order.
pub type NetMap = HashMap<String, f64, BuildHasherDefault<crate::ratsnest::Fx>>;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Courtyard,
    Pad,
    Through,
    Copper,
    Npth,
    Hole,
    Mask,
    Silk,
    Body,
    Yard,
    // a rule area that forbids vias: met only by a via's ring (`Occupancy.ban_shape`); its `net` lists the
    // nets it lets through, joined by ALLOW_SEP
    ViaBan,
    // a courtyard claimed as the part itself (Shape.claims): a courtyard that also keeps
    // another footprint's drawn shapes and pads out
    Keepclear,
}

impl Kind {
    pub fn from_str(s: &str) -> Option<Kind> {
        match s {
            "courtyard" => Some(Kind::Courtyard),
            "pad" => Some(Kind::Pad),
            "through" => Some(Kind::Through),
            "copper" => Some(Kind::Copper),
            "npth" => Some(Kind::Npth),
            "hole" => Some(Kind::Hole),
            "mask" => Some(Kind::Mask),
            "silk" => Some(Kind::Silk),
            "body" => Some(Kind::Body),
            "yard" => Some(Kind::Yard),
            "viaban" => Some(Kind::ViaBan),
            "keepclear" => Some(Kind::Keepclear),
            _ => None,
        }
    }

    fn is_drawn(self) -> bool {
        matches!(self, Kind::Silk | Kind::Mask | Kind::Body)
    }

    fn is_hole(self) -> bool {
        matches!(self, Kind::Hole | Kind::Npth)
    }
    fn is_copperish(self) -> bool {
        matches!(self, Kind::Pad | Kind::Through | Kind::Copper)
    }
}

pub type Bounds = (f64, f64, f64, f64); // left, top, right, bottom

pub fn box_overlaps(a: Bounds, b: Bounds, gap: f64) -> bool {
    a.0 < b.2 + gap && b.0 < a.2 + gap && a.1 < b.3 + gap && b.1 < a.3 + gap
}

fn box_gap(a: Bounds, b: Bounds) -> f64 {
    let dx = if a.0 > b.2 { a.0 - b.2 } else if b.0 > a.2 { b.0 - a.2 } else { 0.0 };
    let dy = if a.1 > b.3 { a.1 - b.3 } else if b.1 > a.3 { b.1 - a.3 } else { 0.0 };
    if dy == 0.0 { dx } else if dx == 0.0 { dy } else { (dx * dx + dy * dy).sqrt() }
}

/// One obstacle or candidate shape, in world coordinates at the placement
/// being asked about - mirrors `occupancy.Shape`, minus `label` (not needed
/// to decide a conflict, only to name one in a message, which Python's own
/// re-run of `_conflict` on the identified pair already has, from its own
/// Shape objects). `owner` IS needed here (unlike an earlier version of
/// this port): the courtyard-vs-lead rule below compares two shapes'
/// owners directly, not just whether either one is a footprint.
#[derive(Clone)]
pub struct Shape {
    pub kind: Kind,
    pub faces: u8,      // bit 0 = front, bit 1 = back
    pub layers: u32,    // bit per CopperLayer; 0 for a non-copper kind
    pub net: String,
    pub poly: Vec<Point>,
    pub bbox: Bounds,
    pub owner: String,
    pub owner_is_footprint: bool, // owner in Occupancy._footprint_refs (== "in self.items", see module doc)
    pub is_lead: bool,  // (owner, label) in Occupancy._leads: a through pad standing proud of the far face
    pub margin: f64,    // Occupancy._margins.get(owner, 0.0): how far KiCad's own courtyard lies inside courtyard_box
    pub wire: bool,     // a track or a via, which a rule of a part (`of`) does not hold
    /// What KiCad's net-tie exclusion reads of the shape (`ties`), for a shape it can excuse; None for the rest.
    pub tie: Option<std::sync::Arc<crate::ties::TieInfo>>,
}

/// One of the script's clearance rules (`rules.ClearanceRules`): `within` holds the owners of the
/// cell's members and of the copper it carries, and a shape with no owner is in no cell; with
/// `between` or `on` set too (a fragment's rule over its nets) both hold. Without `within`, the
/// first of `between` and `on` that is set is the condition.
#[derive(Clone, Default)]
pub struct ClearanceRule {
    pub on: Option<String>,
    pub between: Option<(String, String)>,
    pub within: Option<HashSet<String>>,
    pub min: f64,
    pub of: Option<String>, // with `between`: only where the shape on the second net is a pad of this part and the one on the first is not its own (not its pad, nor an escape of its pads)
}

impl ClearanceRule {
    fn matches(&self, a: &Shape, b: &Shape) -> bool {
        if let Some(owners) = &self.within {
            if !(!a.owner.is_empty() && !b.owner.is_empty() && owners.contains(&a.owner) && owners.contains(&b.owner)) {
                return false;
            }
            if self.between.is_none() && self.on.is_none() {
                return true;
            }
        }
        if let Some((x, y)) = &self.between {
            if let Some(part) = &self.of {
                return (a.net == *x && b.net == *y && b.owner == *part && a.owner != *part && !a.wire)
                    || (b.net == *x && a.net == *y && a.owner == *part && b.owner != *part && !b.wire);
            }
            return (a.net == *x && b.net == *y) || (a.net == *y && b.net == *x);
        }
        match &self.on {
            Some(n) => a.net == *n || b.net == *n,
            None => false,
        }
    }
}

pub struct ConflictConfig {
    pub touch: f64,
    pub vias_block_courtyards: bool,
    pub silk_clearance: f64,
    pub component_spacing: f64,
    pub default_clearance: f64,
    pub net_clearance: NetMap, // net name -> its netclass's own clearance
    pub rules: Vec<ClearanceRule>, // the script's clearance rules, in declaration order: the last that matches decides
    pub gap: f64,       // Occupancy._gap: the conflict-gap prefilter for a non-drawn shape
    pub drawn_gap: f64, // Occupancy._drawn_gap: for a silk/mask/body shape
    pub hole_to_hole: f64,   // BoardGeometry.hole_to_hole: two drilled holes, whatever their nets
    pub hole_clearance: f64, // BoardGeometry.hole_clearance: copper to a drilled hole
    pub epsilon: f64,        // BoardGeometry.drc_epsilon: a copper, hole or hole-to-hole gap short of its rule by no more is clear (KiCad's sub_e)
    pub max_clearance: f64,  // the largest clearance `pair_clearance` can answer (`largest_clearance`): a pair further apart than this is clear
    pub tie_eps: crate::ties::TieEps, // how far a collision may lie outside a net-tie pad and still be inside it
}

/// The largest figure `ConflictConfig::pair_clearance` can answer when no clearance is asked for: the
/// default, a netclass's, or a rule's.
pub fn largest_clearance(default_clearance: f64, net_clearance: &NetMap, rules: &[ClearanceRule]) -> f64 {
    net_clearance.values().chain(rules.iter().map(|r| &r.min)).fold(default_clearance, |m, &c| m.max(c))
}

impl ConflictConfig {
    fn pair_clearance(&self, explicit: Option<f64>, s: &Shape, o: &Shape) -> f64 {
        if let Some(c) = explicit {
            return c;
        }
        if let Some(r) = self.rules.iter().rev().find(|r| r.matches(s, o)) {
            return r.min;
        }
        match (self.net_clearance.get(&s.net), self.net_clearance.get(&o.net)) {
            (Some(&a), Some(&b)) => a.max(b),
            _ => self.default_clearance,
        }
    }

    /// `Occupancy.gap_for`: how far from a shape another can still conflict.
    pub fn gap_for(&self, s: &Shape) -> f64 {
        if s.kind.is_drawn() {
            self.drawn_gap
        } else {
            self.gap
        }
    }
}

/// `Occupancy._drawn_conflict`: silk, mask openings and bodies of two
/// different parts.
fn drawn_conflict(s: &Shape, o: &Shape, cfg: &ConflictConfig) -> bool {
    if s.faces & o.faces == 0 {
        return false;
    }
    let gap = match (s.kind, o.kind) {
        (Kind::Silk, Kind::Silk) | (Kind::Silk, Kind::Mask) | (Kind::Mask, Kind::Silk) => cfg.silk_clearance,
        (Kind::Silk, Kind::Body) | (Kind::Body, Kind::Silk) => 0.0,
        (Kind::Body, Kind::Npth) | (Kind::Npth, Kind::Body) => 0.0,
        (Kind::Body, Kind::Body) => cfg.component_spacing,
        (Kind::Body, Kind::Pad) | (Kind::Body, Kind::Through) => {
            if !o.owner_is_footprint {
                return false; // a track or via may run under a body
            }
            cfg.component_spacing
        }
        (Kind::Pad, Kind::Body) | (Kind::Through, Kind::Body) => {
            if !s.owner_is_footprint {
                return false;
            }
            cfg.component_spacing
        }
        _ => return false,
    };
    if gap <= 0.0 {
        return polys_overlap(&s.poly, &o.poly);
    }
    if box_gap(s.bbox, o.bbox) >= gap - 1e-9 {
        return false;
    }
    poly_distance_below(&s.poly, &o.poly, gap - 1e-9)
}

/// `occupancy._HOLE_SLACK`: how much further the hole rules' box prefilter
/// reaches, as a share of the boxes' widths (a hole's polygon, and a turned
/// one's box, lie inside its circle).
const HOLE_SLACK: f64 = 0.02;

/// `occupancy._circle`: a hole's centre and radius, from its polygon's
/// vertices, which lie on the circle.
fn circle(s: &Shape) -> (Point, f64) {
    let c = ((s.bbox.0 + s.bbox.2) / 2.0, (s.bbox.1 + s.bbox.3) / 2.0);
    let r = s.poly.iter().map(|p| ((p.0 - c.0).powi(2) + (p.1 - c.1).powi(2)).sqrt()).fold(0.0, f64::max);
    (c, r)
}

/// `occupancy._circle_distance`: copper's distance from a hole's circle.
fn circle_distance(hole: &Shape, poly: &[Point]) -> f64 {
    let (c, r) = circle(hole);
    if point_in_polygon(c, poly) {
        return -r;
    }
    let n = poly.len();
    (0..n).map(|i| point_segment_distance(c, poly[i], poly[(i + 1) % n])).fold(f64::INFINITY, f64::min) - r
}

/// Whether two kinds can meet at all: a plated hole meets another hole, or copper.
pub(crate) fn may_meet(a: Kind, b: Kind) -> bool {
    if a == Kind::Hole {
        return b.is_hole() || b.is_copperish();
    }
    if b == Kind::Hole {
        return a.is_hole() || a.is_copperish();
    }
    true
}

/// `Occupancy.clear_limit`: the gap below which a rule of `need` is broken, `need` less the DRC epsilon (as KiCad
/// compares a copper or hole clearance); a rule no larger than the epsilon keeps the nanometre it was judged with.
pub fn clear_limit(need: f64, epsilon: f64) -> f64 {
    if need > epsilon { need - epsilon } else { need - 1e-9 }
}

/// `Occupancy._conflict`: the DRC rules in occupancy terms.
pub fn conflict(s: &Shape, o: &Shape, explicit_clearance: Option<f64>, cfg: &ConflictConfig) -> bool {
    if s.kind == Kind::ViaBan || o.kind == Kind::ViaBan {
        // `Occupancy._conflict`'s via-ban rule: a via of a net the area does not let through, on a layer it
        // covers, whose ring overlaps its outline
        let (ban, other) = if s.kind == Kind::ViaBan { (s, o) } else { (o, s) };
        return other.kind == Kind::Through && !other.owner_is_footprint
            && !ban.net.split('\u{1f}').any(|n| n == other.net)
            && !(ban.layers != 0 && other.layers != 0 && ban.layers & other.layers == 0)
            && polys_overlap(&ban.poly, &other.poly);
    }
    if s.kind == Kind::Yard || o.kind == Kind::Yard {
        // Occupancy's yard: a drawn part's courtyard under the physical
        // envelope, judged only against another part's plated lead.
        let (yard, other) = if s.kind == Kind::Yard { (s, o) } else { (o, s) };
        return other.kind == Kind::Through && other.owner != yard.owner && other.is_lead
            && polys_overlap(&yard.poly, &other.poly);
    }
    if s.kind == Kind::Keepclear || o.kind == Kind::Keepclear {
        // Occupancy._conflict's claim rule: a courtyard claimed as the part itself keeps
        // another footprint's drawn shapes and pads out
        let (claim, other) = if s.kind == Kind::Keepclear { (s, o) } else { (o, s) };
        if matches!(other.kind, Kind::Body | Kind::Pad | Kind::Through) {
            if other.owner != claim.owner && other.owner_is_footprint && (claim.faces & other.faces) != 0
                && polys_overlap(&claim.poly, &other.poly)
            {
                return true;
            }
            if other.kind != Kind::Through {
                return false;
            }
        }
    }
    if s.kind.is_drawn() || o.kind.is_drawn() {
        return drawn_conflict(s, o, cfg);
    }
    if s.kind.is_hole() && o.kind.is_hole() {
        // hole to hole is net-blind, measured between the circles the
        // polygons were drawn from (Occupancy._conflict, _circle). Two via
        // holes that span no common layer never meet.
        if s.layers != 0 && o.layers != 0 && s.layers & o.layers == 0 {
            return false;
        }
        let need = cfg.hole_to_hole;
        let slack = HOLE_SLACK * ((s.bbox.2 - s.bbox.0) + (o.bbox.2 - o.bbox.0));
        if box_gap(s.bbox, o.bbox) >= need + slack - 1e-9 {
            return false;
        }
        let ((sx, sy), rs) = circle(s);
        let ((ox, oy), ro) = circle(o);
        return ((sx - ox).powi(2) + (sy - oy).powi(2)).sqrt() - rs - ro < clear_limit(need, cfg.epsilon);
    }
    if s.kind == Kind::Hole || o.kind == Kind::Hole {
        // a plated hole keeps the hole clearance from the copper of another net
        // (Occupancy._hole_conflict), but where a net tie excuses it (`_hole_tie_exclusion`)
        let (hole, metal) = if s.kind == Kind::Hole { (s, o) } else { (o, s) };
        if !metal.kind.is_copperish() || (!hole.net.is_empty() && hole.net == metal.net) {
            return false;
        }
        let common = if hole.layers != 0 { hole.layers & metal.layers } else { metal.layers };
        if common == 0 {
            return false;
        }
        let need = cfg.hole_clearance;
        let slack = HOLE_SLACK * (hole.bbox.2 - hole.bbox.0);
        return box_gap(hole.bbox, metal.bbox) < need + slack - 1e-9
            && circle_distance(hole, &metal.poly) < clear_limit(need, cfg.epsilon)
            && !(metal.tie.is_some() && crate::ties::hole_tie_exclusion(hole, metal, cfg.tie_eps));
    }
    let court = |k: Kind| matches!(k, Kind::Courtyard | Kind::Keepclear);
    if court(s.kind) && court(o.kind) {
        let depth = (s.bbox.2.min(o.bbox.2) - s.bbox.0.max(o.bbox.0))
            .min(s.bbox.3.min(o.bbox.3) - s.bbox.1.max(o.bbox.1));
        let has_width = (s.bbox.2 - s.bbox.0) > 0.0 && (o.bbox.2 - o.bbox.0) > 0.0;
        // KiCad's own courtyard polygon lies inside courtyard_box by each
        // part's margin, so two boxes can overlap by up to the sum of their
        // margins (less a stroke-width fudge) while KiCad's own courtyards
        // still only touch. place_courtyard_touch alone is the floor - a
        // plain "may touch" allowance - not the whole story (placemat
        // commit "Courtyards may overlap by the margin KiCad's own lie
        // inside them"; the flat-threshold-only version was c785a04).
        let allowed = cfg.touch.max(s.margin + o.margin - 0.001);
        // to a nanometre: depth is a difference of coordinates, and exactly
        // the allowance must not read as more.
        if depth <= allowed + 1e-9 && has_width {
            return false;
        }
        return (s.faces & o.faces) != 0 && polys_overlap(&s.poly, &o.poly);
    }
    if court(s.kind) || court(o.kind) {
        let (court, other) = if court(s.kind) { (s, o) } else { (o, s) };
        // A courtyard over another footprint's own through-hole lead (a pin
        // standing proud of the far face) is always a mechanical collision,
        // whatever vias_block_courtyards says - that setting is about
        // routed vias, not component leads. This is checked, and returned
        // on, before the via rule below: a lead match never falls through
        // to it (placemat commit "A through-hole part claims only its
        // holes on the far face").
        if other.kind == Kind::Through && other.owner != court.owner && other.is_lead {
            return polys_overlap(&court.poly, &other.poly);
        }
        let blocks = other.kind == Kind::Npth
            || (other.kind == Kind::Through && cfg.vias_block_courtyards && !other.owner_is_footprint);
        return blocks && polys_overlap(&court.poly, &other.poly);
    }
    let is_copperish = |k: Kind| matches!(k, Kind::Pad | Kind::Through | Kind::Copper);
    if is_copperish(s.kind) && is_copperish(o.kind) {
        if s.layers & o.layers == 0 {
            return false;
        }
        if !s.net.is_empty() && s.net == o.net {
            return false;
        }
        let apart = box_gap(s.bbox, o.bbox);
        if apart >= clear_limit(explicit_clearance.unwrap_or(cfg.max_clearance), cfg.epsilon) {
            return false;           // no clearance is larger than this: the cheap way out, before the rules are searched
        }
        let clr = cfg.pair_clearance(explicit_clearance, s, o);
        let limit = clear_limit(clr, cfg.epsilon);
        if apart >= limit {
            return false;
        }
        return poly_distance_below(&s.poly, &o.poly, limit) && !crate::ties::net_tie_exclusion(s, o, clr, cfg.tie_eps);
    }
    if (s.kind == Kind::Npth && is_copperish(o.kind)) || (o.kind == Kind::Npth && is_copperish(s.kind)) {
        if polys_overlap(&s.poly, &o.poly) {
            return true;
        }
        let need = cfg.hole_clearance;
        let (hole, metal) = if s.kind == Kind::Npth { (s, o) } else { (o, s) };
        let slack = HOLE_SLACK * (hole.bbox.2 - hole.bbox.0);
        return need > 0.0 && box_gap(hole.bbox, metal.bbox) < need + slack - 1e-9
            && circle_distance(hole, &metal.poly) < clear_limit(need, cfg.epsilon);
    }
    false
}

/// A uniform grid over registered obstacle boxes, built once per `scan()`
/// (mirrors `ShapeIndex`'s own grid, `CELL = 2.0`), queried once per
/// candidate shape at that shape's own box and gap - see the module doc for
/// why this one query replaces `near()` + the per-shape `close` filter.
pub struct ShapeGrid {
    pub(crate) shapes: Vec<Shape>,
    /// Each shape's box, in one array: a query tests a box of every shape its cells hold, and the shapes themselves
    /// are large and apart.
    boxes: Vec<Bounds>,
    /// The cells each shape was registered in, as (first column, last column, first row, last row).
    spans: Vec<(i64, i64, i64, i64)>,
    cell: f64,
    grid: CellMap,
    /// The same cells in a dense array over the cells the shapes reach (None: too many to hold densely, and
    /// `grid` answers).
    dense: Option<Dense>,
}

struct Dense {
    i0: i64,
    j0: i64,
    ni: usize,
    nj: usize,
    cells: Vec<Vec<usize>>,
}

/// Most cells a dense array may hold.
const MAX_DENSE: usize = 4_000_000;

thread_local! {
    /// What `near_into` fills, taken and given back by a search, so a candidate allocates none.
    static NEAR: std::cell::RefCell<Vec<usize>> = const { std::cell::RefCell::new(Vec::new()) };
}

const CELL: f64 = 2.0;

fn cell_at(v: f64, cell: f64) -> i64 {
    (v / cell).floor() as i64
}

/// What `ShapeGrid::any_conflict_shifted_excluding` keeps from one offset to the next.
pub struct Blockers {
    pairs: Vec<(usize, usize)>,          // (shape, obstacle) pairs that refused an offset, the latest first
    scratch: Vec<Shape>,                 // each shape as last drawn, and where
    at: Vec<Option<(f64, f64)>>,
}

impl Blockers {
    const KEPT: usize = 6;

    pub fn new(origin_shapes: &[Shape]) -> Self {
        Blockers { pairs: Vec::new(), scratch: origin_shapes.to_vec(), at: vec![None; origin_shapes.len()] }
    }

    /// `origin_shapes[si]` shifted by `(dx, dy)`.
    fn drawn(&mut self, origin_shapes: &[Shape], si: usize, dx: f64, dy: f64) -> &Shape {
        if self.at[si] != Some((dx, dy)) {
            let s0 = &origin_shapes[si];
            let s = &mut self.scratch[si];
            for (q, p) in s.poly.iter_mut().zip(&s0.poly) {
                *q = (p.0 + dx, p.1 + dy);
            }
            s.bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            self.at[si] = Some((dx, dy));
        }
        &self.scratch[si]
    }
}

impl Dense {
    fn of(grid: &CellMap) -> Option<Dense> {
        let (mut i0, mut i1, mut j0, mut j1) = (i64::MAX, i64::MIN, i64::MAX, i64::MIN);
        for &(i, j) in grid.keys() {
            i0 = i0.min(i);
            i1 = i1.max(i);
            j0 = j0.min(j);
            j1 = j1.max(j);
        }
        if i0 > i1 {
            return None;
        }
        let (ni, nj) = ((i1 - i0) as usize + 1, (j1 - j0) as usize + 1);
        if ni.checked_mul(nj)? > MAX_DENSE {
            return None;
        }
        let mut cells = vec![Vec::new(); ni * nj];
        for (&(i, j), ks) in grid {
            cells[(i - i0) as usize * nj + (j - j0) as usize] = ks.clone();
        }
        Some(Dense { i0, j0, ni, nj, cells })
    }
}

impl ShapeGrid {
    pub fn new(shapes: Vec<Shape>) -> Self {
        let mut grid = CellMap::default();
        let mut spans = Vec::with_capacity(shapes.len());
        for (k, s) in shapes.iter().enumerate() {
            let (x0, y0, x1, y1) = s.bbox;
            let span = (cell_at(x0, CELL), cell_at(x1, CELL), cell_at(y0, CELL), cell_at(y1, CELL));
            for i in span.0..=span.1 {
                for j in span.2..=span.3 {
                    grid.entry((i, j)).or_default().push(k);
                }
            }
            spans.push(span);
        }
        let dense = Dense::of(&grid);
        let boxes = shapes.iter().map(|s| s.bbox).collect();
        ShapeGrid { shapes, boxes, spans, cell: CELL, grid, dense }
    }

    /// The registered shapes in cell (i, j), in registration order.
    #[inline]
    fn cell_shapes(&self, i: i64, j: i64) -> Option<&[usize]> {
        match &self.dense {
            Some(d) => {
                let (a, b) = (i - d.i0, j - d.j0);
                if a < 0 || b < 0 || a as usize >= d.ni || b as usize >= d.nj {
                    return None;
                }
                Some(&d.cells[a as usize * d.nj + b as usize])
            }
            None => self.grid.get(&(i, j)).map(|v| v.as_slice()),
        }
    }

    /// Indices of registered shapes whose box overlaps `query` inflated by
    /// `gap`, in registration order (matching `ShapeIndex.near`'s own
    /// `sorted(hits)` - insertion order - so a "first conflict" search over
    /// this order matches Python's).
    pub(crate) fn near(&self, query: Bounds, gap: f64) -> Vec<usize> {
        let mut hits = Vec::new();
        self.near_into(query, gap, &mut hits);
        hits
    }

    /// `near`, into `out` (cleared first).
    pub(crate) fn near_into(&self, query: Bounds, gap: f64, out: &mut Vec<usize>) {
        out.clear();
        let (x0, y0, x1, y1) = (query.0 - gap, query.1 - gap, query.2 + gap, query.3 + gap);
        let (i0, i1) = (cell_at(x0, self.cell), cell_at(x1, self.cell));
        let (j0, j1) = (cell_at(y0, self.cell), cell_at(y1, self.cell));
        if i0 == i1 && j0 == j1 {
            // one cell: its shapes are in registration order, each once
            if let Some(ks) = self.cell_shapes(i0, j0) {
                out.extend(ks.iter().copied().filter(|&k| box_overlaps(self.boxes[k], query, gap)));
            }
            return;
        }
        // a dense array holds nothing past its edge: only the cells it has are visited
        let (ia, ib, ja, jb) = match &self.dense {
            Some(d) => (i0.max(d.i0), i1.min(d.i0 + d.ni as i64 - 1), j0.max(d.j0), j1.min(d.j0 + d.nj as i64 - 1)),
            None => (i0, i1, j0, j1),
        };
        for i in ia..=ib {
            for j in ja..=jb {
                if let Some(ks) = self.cell_shapes(i, j) {
                    // A shape is taken from the first of the visited cells it lies in (the later of its own first
                    // column and row and the query's), so each is met once, and its box is tested before the sort:
                    // most of a big query's cells hold shapes it does not reach.
                    for &k in ks {
                        let sp = self.spans[k];
                        if i == ia.max(sp.0) && j == ja.max(sp.2) && box_overlaps(self.boxes[k], query, gap) {
                            out.push(k);
                        }
                    }
                }
            }
        }
        out.sort_unstable();
    }

    /// The first (candidate shape index, obstacle index) pair that
    /// conflicts, walking `candidate_shapes` in order and, for each, its
    /// near obstacles in registration order - the same order
    /// `Occupancy.legal()`'s own nested loop visits them in.
    pub fn first_conflict(
        &self,
        candidate_shapes: &[Shape],
        explicit_clearance: Option<f64>,
        cfg: &ConflictConfig,
    ) -> Option<(usize, usize)> {
        for (si, s) in candidate_shapes.iter().enumerate() {
            let gap = cfg.gap_for(s);
            for oi in self.near(s.bbox, gap) {
                if !may_meet(s.kind, self.shapes[oi].kind) {
                    continue;
                }
                if conflict(s, &self.shapes[oi], explicit_clearance, cfg) {
                    return Some((si, oi));
                }
            }
        }
        None
    }

    /// As `first_conflict`, but `origin_shapes` are UNSHIFTED (at the
    /// item's own origin, as `Occupancy._origin_shapes` caches them - one
    /// turn per rotation and face, reused across every candidate at that
    /// turn) and the shift by `(dx, dy)` happens here, not in Python. This
    /// is the whole point: the caller marshals a candidate's shapes into
    /// Rust ONCE per (item, rotation, face) - not once per `legal()` call -
    /// and every candidate at that turn is then just two floats crossing
    /// the FFI boundary, not a rebuilt polygon per shape. A shape's poly is
    /// only actually shifted when it is near enough to test (`conflict`
    /// needs real coordinates); the bbox, needed for every near-query
    /// regardless of a hit, is cheap to shift unconditionally.
    pub fn first_conflict_shifted(
        &self,
        origin_shapes: &[Shape],
        dx: f64,
        dy: f64,
        explicit_clearance: Option<f64>,
        cfg: &ConflictConfig,
    ) -> Option<(usize, usize)> {
        let mut hits = NEAR.with(|n| std::mem::take(&mut *n.borrow_mut()));
        let mut found = None;
        'shapes: for (si, s0) in origin_shapes.iter().enumerate() {
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            let gap = cfg.gap_for(s0);
            let mut moved: Option<Shape> = None;        // the shape at the offset, built when an obstacle needs it
            self.near_into(bbox, gap, &mut hits);
            for &oi in &hits {
                if !may_meet(s0.kind, self.shapes[oi].kind) {
                    continue;
                }
                let s = moved.get_or_insert_with(|| {
                    let poly: Vec<Point> = s0.poly.iter().map(|p| (p.0 + dx, p.1 + dy)).collect();
                    Shape { poly, bbox, ..s0.clone() }
                });
                if conflict(s, &self.shapes[oi], explicit_clearance, cfg) {
                    found = Some((si, oi));
                    break 'shapes;
                }
            }
        }
        NEAR.with(|n| *n.borrow_mut() = hits);
        found
    }

    /// `first_conflict_shifted` over `drawn`, a copy of `origin_shapes` kept by the caller from one candidate to
    /// the next: a shape's polygon is shifted in it, in place, when an obstacle needs it, so a candidate
    /// builds nothing (the shapes carry strings, and a candidate meets thousands of pairs).
    pub fn first_conflict_shifted_in(
        &self,
        origin_shapes: &[Shape],
        drawn: &mut [Shape],
        dx: f64,
        dy: f64,
        explicit_clearance: Option<f64>,
        cfg: &ConflictConfig,
    ) -> Option<(usize, usize)> {
        let mut hits = NEAR.with(|n| std::mem::take(&mut *n.borrow_mut()));
        let mut found = None;
        'shapes: for (si, s0) in origin_shapes.iter().enumerate() {
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            let gap = cfg.gap_for(s0);
            let mut moved = false;                      // the shape at the offset, drawn when an obstacle needs it
            self.near_into(bbox, gap, &mut hits);
            for &oi in &hits {
                if !may_meet(s0.kind, self.shapes[oi].kind) {
                    continue;
                }
                let s = &mut drawn[si];
                if !moved {
                    for (q, p) in s.poly.iter_mut().zip(&s0.poly) {
                        *q = (p.0 + dx, p.1 + dy);
                    }
                    s.bbox = bbox;
                    moved = true;
                }
                if conflict(s, &self.shapes[oi], explicit_clearance, cfg) {
                    found = Some((si, oi));
                    break 'shapes;
                }
            }
        }
        NEAR.with(|n| *n.borrow_mut() = hits);
        found
    }

    /// Whether any of `origin_shapes`, shifted by `(dx, dy)`, conflicts with an obstacle outside `skip`:
    /// `first_conflict_shifted_excluding` is_some, tested the likeliest pairs first. `blockers` holds the
    /// pairs that refused the offsets before, the latest first; a refusal is only a yes or no, so which
    /// obstacle is tried first does not change the answer, and the next offset is mostly refused by one of
    /// them. It also holds the shapes drawn at an offset, so they are drawn once and over the same storage.
    pub fn any_conflict_shifted_excluding(
        &self,
        origin_shapes: &[Shape],
        dx: f64,
        dy: f64,
        explicit_clearance: Option<f64>,
        cfg: &ConflictConfig,
        skip: &IdSet,
        blockers: &mut Blockers,
    ) -> bool {
        let meets = |si: usize, oi: usize, blockers: &mut Blockers| -> bool {
            let s0 = &origin_shapes[si];
            let o = &self.shapes[oi];
            if skip.contains(&oi) || !may_meet(s0.kind, o.kind) {
                return false;
            }
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            if !box_overlaps(o.bbox, bbox, cfg.gap_for(s0)) {
                return false;
            }
            conflict(blockers.drawn(origin_shapes, si, dx, dy), o, explicit_clearance, cfg)
        };
        for k in 0..blockers.pairs.len() {
            let (si, oi) = blockers.pairs[k];
            if meets(si, oi, blockers) {
                blockers.pairs[..=k].rotate_right(1);       // the latest to refuse is tried first
                return true;
            }
        }
        for si in 0..origin_shapes.len() {
            let s0 = &origin_shapes[si];
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            for oi in self.near(bbox, cfg.gap_for(s0)) {
                if meets(si, oi, blockers) {
                    blockers.pairs.insert(0, (si, oi));
                    blockers.pairs.truncate(Blockers::KEPT);
                    return true;
                }
            }
        }
        false
    }

    /// As `first_conflict_shifted`, but an obstacle index in `skip` is
    /// never reported as a conflict - `give_way`'s own move search
    /// (`giveway.py` `_give`, via `NativeObstacles::first_clear_offset`):
    /// the via's own current-position shapes (and any other via's, also
    /// giving way to the same candidate) are registered obstacles like any
    /// other, but a via naturally sits near its own former position while
    /// searching, and a plated hole's own clearance rule
    /// (`conflict`'s hole-to-hole branch) is net-blind - so without this,
    /// a via would spuriously "conflict" with its own unmoved hole at
    /// every nearby offset. Python's `_Judge.near` excludes these same
    /// shapes from `pool` for the identical reason (`judge.hidden`); this
    /// mirrors that exclusion here.
    pub fn first_conflict_shifted_excluding(
        &self,
        origin_shapes: &[Shape],
        dx: f64,
        dy: f64,
        explicit_clearance: Option<f64>,
        cfg: &ConflictConfig,
        skip: &IdSet,
    ) -> Option<(usize, usize)> {
        for (si, s0) in origin_shapes.iter().enumerate() {
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            let gap = cfg.gap_for(s0);
            let mut moved: Option<Shape> = None;        // the shape at the offset, built when an obstacle needs it
            for oi in self.near(bbox, gap) {
                if skip.contains(&oi) || !may_meet(s0.kind, self.shapes[oi].kind) {
                    continue;
                }
                let s = moved.get_or_insert_with(|| {
                    let poly: Vec<Point> = s0.poly.iter().map(|p| (p.0 + dx, p.1 + dy)).collect();
                    Shape { poly, bbox, ..s0.clone() }
                });
                if conflict(s, &self.shapes[oi], explicit_clearance, cfg) {
                    return Some((si, oi));
                }
            }
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shape(kind: Kind, owner: &str, poly: Vec<Point>, faces: u8, layers: u32, net: &str, owner_is_footprint: bool) -> Shape {
        shape_ex(kind, owner, poly, faces, layers, net, owner_is_footprint, false)
    }

    fn shape_ex(kind: Kind, owner: &str, poly: Vec<Point>, faces: u8, layers: u32, net: &str,
                owner_is_footprint: bool, is_lead: bool) -> Shape {
        shape_margin(kind, owner, poly, faces, layers, net, owner_is_footprint, is_lead, 0.0)
    }

    #[allow(clippy::too_many_arguments)]
    fn shape_margin(kind: Kind, owner: &str, poly: Vec<Point>, faces: u8, layers: u32, net: &str,
                    owner_is_footprint: bool, is_lead: bool, margin: f64) -> Shape {
        let bbox = bounds(&poly);
        Shape { kind, faces, layers, net: net.into(), poly, bbox, owner: owner.into(), owner_is_footprint, is_lead, margin, wire: false, tie: None }
    }

    fn bounds(poly: &[Point]) -> Bounds {
        let x0 = poly.iter().map(|p| p.0).fold(f64::INFINITY, f64::min);
        let x1 = poly.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max);
        let y0 = poly.iter().map(|p| p.1).fold(f64::INFINITY, f64::min);
        let y1 = poly.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max);
        (x0, y0, x1, y1)
    }

    fn rect(cx: f64, cy: f64, w: f64, h: f64) -> Vec<Point> {
        vec![(cx - w / 2.0, cy - h / 2.0), (cx + w / 2.0, cy - h / 2.0), (cx + w / 2.0, cy + h / 2.0), (cx - w / 2.0, cy + h / 2.0)]
    }

    fn cfg() -> ConflictConfig {
        ConflictConfig {
            touch: 0.02,
            vias_block_courtyards: false,
            silk_clearance: 0.1,
            component_spacing: 0.2,
            default_clearance: 0.2,
            net_clearance: NetMap::default(),
            rules: Vec::new(),
            gap: 1.0,
            drawn_gap: 0.2,
            hole_to_hole: 0.25,
            hole_clearance: 0.0,
            epsilon: 1e-9,
            max_clearance: f64::INFINITY,       // the tests that add rules leave the early way out off
            tie_eps: crate::ties::TieEps { mm: 0.0005, nm: 500 },
        }
    }

    #[test]
    fn the_last_matching_clearance_rule_decides_the_pair() {
        // two pads 0.3 mm apart: clear under the 0.2 netclass figure
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true);
        let b = shape(Kind::Pad, "R1", rect(1.3, 0.0, 1.0, 1.0), 1, 1, "B", true);
        let mut c = cfg();
        assert!(!conflict(&a, &b, None, &c));
        c.rules.push(ClearanceRule { on: Some("A".into()), min: 0.4, ..Default::default() });
        assert!(conflict(&a, &b, None, &c)); // a rule on A raises it
        c.rules.push(ClearanceRule { between: Some(("B".into(), "A".into())), min: 0.1, ..Default::default() });
        assert!(!conflict(&a, &b, None, &c)); // the later between= decides, whichever way round
        assert!(conflict(&a, &b, Some(0.5), &c)); // an explicit clearance overrides every rule
        let owners: HashSet<String> = ["U1".to_string(), "R1".to_string()].into_iter().collect();
        c.rules.push(ClearanceRule { within: Some(owners), min: 0.35, ..Default::default() });
        assert!(conflict(&a, &b, None, &c)); // both owners in the cell
        let other = shape(Kind::Pad, "X1", rect(1.3, 0.0, 1.0, 1.0), 1, 1, "B", true);
        assert!(!conflict(&a, &other, None, &c)); // X1 is in no cell: the between= rule's 0.1 stands
    }

    #[test]
    fn a_rule_within_a_cell_and_between_nets_holds_only_where_both_do() {
        // two pads 0.3 mm apart: clear under the 0.2 netclass figure
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true);
        let b = shape(Kind::Pad, "R1", rect(1.3, 0.0, 1.0, 1.0), 1, 1, "B", true);
        let b_outside = shape(Kind::Pad, "X1", rect(1.3, 0.0, 1.0, 1.0), 1, 1, "B", true);
        let other_net = shape(Kind::Pad, "R1", rect(1.3, 0.0, 1.0, 1.0), 1, 1, "C", true);
        let mut c = cfg();
        let owners: HashSet<String> = ["U1".to_string(), "R1".to_string()].into_iter().collect();
        c.rules.push(ClearanceRule { within: Some(owners), between: Some(("A".into(), "B".into())), min: 0.5, ..Default::default() });
        assert!(conflict(&a, &b, None, &c)); // in the cell, on A and B
        assert!(!conflict(&a, &b_outside, None, &c)); // X1 is in no cell
        assert!(!conflict(&a, &other_net, None, &c)); // net C is not the rule's
    }

    #[test]
    fn a_rule_of_a_part_holds_only_that_parts_pad_against_copper_that_is_not_its_own_pad() {
        // U1's pad on FB, 0.5 mm from a pad of SW: clear under the 0.2 netclass figure
        let fb_u1 = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "FB", true);
        let sw_l1 = shape(Kind::Pad, "L1", rect(1.5, 0.0, 1.0, 1.0), 1, 1, "SW", true);
        let sw_u1 = shape(Kind::Pad, "U1", rect(1.5, 0.0, 1.0, 1.0), 1, 1, "SW", true);
        let fb_r1 = shape(Kind::Pad, "R1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "FB", true);
        let mut c = cfg();
        c.rules.push(ClearanceRule {
            between: Some(("SW".into(), "FB".into())),
            of: Some("U1".into()),
            min: 1.0,
            ..Default::default()
        });
        assert!(conflict(&fb_u1, &sw_l1, None, &c)); // U1's FB pad keeps 1.0 from another part's SW copper
        assert!(conflict(&sw_l1, &fb_u1, None, &c)); // whichever way round
        assert!(!conflict(&fb_u1, &sw_u1, None, &c)); // not from its own SW pad: the footprint sets that gap
        assert!(!conflict(&fb_r1, &sw_l1, None, &c)); // another part's FB pad keeps the netclass figure
    }

    #[test]
    fn a_rule_of_a_part_holds_a_pour_and_not_a_track_or_a_via() {
        // copper of SW 0.5 mm from U1's FB pad: held under U1's rule, unless it is a track or a via
        let fb_u1 = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "FB", true);
        let pour = shape(Kind::Copper, "", rect(1.5, 0.0, 1.0, 1.0), 1, 1, "SW", false);
        let mut track = pour.clone();
        track.wire = true;
        let mut c = cfg();
        c.rules.push(ClearanceRule {
            between: Some(("SW".into(), "FB".into())),
            of: Some("U1".into()),
            min: 1.0,
            ..Default::default()
        });
        assert!(conflict(&fb_u1, &pour, None, &c));
        assert!(conflict(&pour, &fb_u1, None, &c)); // whichever way round
        assert!(!conflict(&fb_u1, &track, None, &c)); // a track leaving U1's own pads is not held
        assert!(!conflict(&track, &fb_u1, None, &c));
    }

    #[test]
    fn touching_courtyards_do_not_conflict() {
        let a = shape(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let b = shape(Kind::Courtyard, "U2", rect(2.0, 0.0, 2.0, 2.0), 1, 0, "", true); // touching edge
        assert!(!conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn courtyards_overlapping_by_less_than_their_combined_margin_do_not_conflict() {
        // Each box reaches 0.05mm past its part's real (KiCad) courtyard.
        // Two such boxes can overlap by up to their margins summed (less
        // the 0.001 fudge) while the real courtyards only touch.
        let a = shape_margin(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true, false, 0.05);
        let b = shape_margin(Kind::Courtyard, "U2", rect(1.95, 0.0, 2.0, 2.0), 1, 0, "", true, false, 0.05);
        // overlap depth: a.right=1.0, b.left=0.95 -> depth 0.05, under
        // allowed = max(touch, 0.05+0.05-0.001) = 0.099.
        assert!(!conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn courtyards_overlapping_by_more_than_their_combined_margin_conflict() {
        let a = shape_margin(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true, false, 0.05);
        let b = shape_margin(Kind::Courtyard, "U2", rect(1.8, 0.0, 2.0, 2.0), 1, 0, "", true, false, 0.05);
        // depth = 1.0 - 0.8 = 0.2, over allowed = 0.099.
        assert!(conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn overlapping_courtyards_conflict() {
        let a = shape(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let b = shape(Kind::Courtyard, "U2", rect(1.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        assert!(conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn courtyards_on_different_faces_do_not_conflict() {
        let a = shape(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true); // front
        let b = shape(Kind::Courtyard, "U2", rect(1.0, 0.0, 2.0, 2.0), 2, 0, "", true); // back
        assert!(!conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn same_net_pads_never_conflict_however_close() {
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "GND", true);
        let b = shape(Kind::Pad, "U2", rect(0.3, 0.0, 1.0, 1.0), 1, 1, "GND", true);
        assert!(!conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn different_net_pads_closer_than_clearance_conflict() {
        // a's right edge at x=0.5, b's left edge at x=0.6: a 0.1mm gap, under
        // the default 0.2mm clearance.
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true);
        let b = shape(Kind::Pad, "U2", rect(1.1, 0.0, 1.0, 1.0), 1, 1, "B", true);
        assert!(conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn different_net_pads_at_exactly_clearance_do_not_conflict() {
        // a's right edge at x=0.5, b's left edge at x=0.7: exactly the
        // default 0.2mm clearance apart, which the box-gap prefilter alone
        // (>= the clearance less the epsilon) already rules legal, before any polygon walk.
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true);
        let b = shape(Kind::Pad, "U2", rect(1.2, 0.0, 1.0, 1.0), 1, 1, "B", true);
        assert!(!conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn a_gap_short_of_the_clearance_by_no_more_than_the_epsilon_is_clear() {
        // a 0.2 mm clearance, pads 0.1997 apart: short by 0.0003, under KiCad's 0.0005 epsilon
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true);
        let near = shape(Kind::Pad, "U2", rect(1.1997, 0.0, 1.0, 1.0), 1, 1, "B", true);
        let nearer = shape(Kind::Pad, "U3", rect(1.1993, 0.0, 1.0, 1.0), 1, 1, "B", true);
        let mut c = cfg();
        assert!(conflict(&a, &near, None, &c));         // the epsilon of the other tests: a nanometre
        c.epsilon = 0.0005;
        assert!(!conflict(&a, &near, None, &c));
        assert!(conflict(&a, &nearer, None, &c));       // short by 0.0007
    }

    #[test]
    fn a_rule_no_larger_than_the_epsilon_still_asks_whether_two_things_touch() {
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true);
        let over = shape(Kind::Pad, "U2", rect(0.8, 0.0, 1.0, 1.0), 1, 1, "B", true);
        let clear = shape(Kind::Pad, "U3", rect(1.01, 0.0, 1.0, 1.0), 1, 1, "B", true);
        let mut c = cfg();
        c.epsilon = 0.0005;
        assert!(conflict(&a, &over, Some(1e-4), &c));
        assert!(!conflict(&a, &clear, Some(1e-4), &c));
    }

    #[test]
    fn pads_on_different_layers_never_conflict() {
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true); // layer bit 0
        let b = shape(Kind::Pad, "U2", rect(0.3, 0.0, 1.0, 1.0), 1, 2, "B", true); // layer bit 1
        assert!(!conflict(&a, &b, None, &cfg()));
    }

    #[test]
    fn via_holes_on_no_common_layer_never_meet() {
        let back = shape(Kind::Hole, "", rect(0.0, 0.0, 0.3, 0.3), 2, 0b0110, "A", false);
        let front = shape(Kind::Hole, "", rect(0.35, 0.0, 0.3, 0.3), 1, 0b1001, "A", false);
        let deep = shape(Kind::Hole, "", rect(0.35, 0.0, 0.3, 0.3), 2, 0b1110, "A", false);
        let through = shape(Kind::Hole, "", rect(0.35, 0.0, 0.3, 0.3), 3, 0, "A", false);
        assert!(!conflict(&back, &front, None, &cfg()));
        assert!(conflict(&back, &deep, None, &cfg()));
        assert!(conflict(&back, &through, None, &cfg()));
    }

    #[test]
    fn a_plated_hole_keeps_the_hole_clearance_from_copper_of_another_net() {
        // a 0.3 mm drill to copper whose edge is at x = 0.5: 0.35 mm
        let ring: Vec<Point> = (0..16)
            .map(|i| (0.15 * (i as f64 * std::f64::consts::PI / 8.0).cos(), 0.15 * (i as f64 * std::f64::consts::PI / 8.0).sin()))
            .collect();
        let hole = shape(Kind::Hole, "", ring.clone(), 3, 0, "A", false);
        let bar = shape(Kind::Copper, "NT1", rect(0.6, 0.0, 0.2, 1.0), 1, 1, "", true);
        let mut c = cfg();
        c.hole_clearance = 0.3;
        assert!(!conflict(&hole, &bar, None, &c));
        c.hole_clearance = 0.4;
        assert!(conflict(&hole, &bar, None, &c)); // netless copper counts, whichever way round
        assert!(conflict(&bar, &hole, None, &c));
        let own = shape(Kind::Pad, "U1", rect(0.6, 0.0, 0.2, 1.0), 1, 1, "A", true);
        assert!(!conflict(&hole, &own, None, &c)); // its own net's copper is not judged
        let back = shape(Kind::Copper, "NT1", rect(0.6, 0.0, 0.2, 1.0), 2, 0b10, "", true);
        let blind = shape(Kind::Hole, "", ring, 1, 0b01, "A", false);
        assert!(!conflict(&blind, &back, None, &c)); // a hole spanning no layer of the copper's
        assert!(conflict(&hole, &back, None, &c));
    }

    #[test]
    fn silk_over_a_foreign_body_is_zero_gap() {
        let silk = shape(Kind::Silk, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 0, "", true);
        let body_touching = shape(Kind::Body, "U2", rect(1.0, 0.0, 1.0, 1.0), 1, 0, "", true);
        assert!(!conflict(&silk, &body_touching, None, &cfg())); // touching only: legal
        let body_inside = shape(Kind::Body, "U2", rect(0.4, 0.0, 1.0, 1.0), 1, 0, "", true);
        assert!(conflict(&silk, &body_inside, None, &cfg()));
    }

    #[test]
    fn body_under_a_via_is_not_a_conflict() {
        let body = shape(Kind::Body, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let via = shape(Kind::Through, "", rect(0.0, 0.0, 0.3, 0.3), 3, 0xFFFF_FFFF, "GND", false); // owner "" not a footprint
        assert!(!conflict(&body, &via, None, &cfg()));
    }

    #[test]
    fn a_yard_over_another_parts_lead_conflicts() {
        let yard = shape(Kind::Yard, "C1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let lead = shape_ex(Kind::Through, "J1", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "A", true, true);
        assert!(conflict(&yard, &lead, None, &cfg()));
        assert!(conflict(&lead, &yard, None, &cfg()));
    }

    #[test]
    fn a_yard_meets_nothing_but_another_parts_lead() {
        let yard = shape(Kind::Yard, "C1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let own = shape_ex(Kind::Through, "C1", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "A", true, true);
        let via = shape_ex(Kind::Through, "", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "A", false, false);
        let pad = shape(Kind::Pad, "R1", rect(0.5, 0.5, 0.3, 0.3), 1, 1, "B", true);
        let body = shape(Kind::Body, "R1", rect(0.5, 0.5, 0.3, 0.3), 1, 0, "", true);
        let court = shape(Kind::Courtyard, "R1", rect(0.5, 0.5, 0.3, 0.3), 1, 0, "", true);
        let other = shape(Kind::Yard, "R1", rect(0.5, 0.5, 0.3, 0.3), 1, 0, "", true);
        for o in [&own, &via, &pad, &body, &court, &other] {
            assert!(!conflict(&yard, o, None, &cfg()));
            assert!(!conflict(o, &yard, None, &cfg()));
        }
    }

    #[test]
    fn courtyard_over_another_footprints_lead_conflicts_regardless_of_vias_block_courtyards() {
        let court = shape(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let lead = shape_ex(Kind::Through, "U2", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "GND", true, true);
        let mut c = cfg();
        c.vias_block_courtyards = false; // the lead rule fires even so
        assert!(conflict(&court, &lead, None, &c));
    }

    #[test]
    fn courtyard_over_its_own_lead_is_not_a_conflict() {
        // other.owner != court.owner is part of the Python rule: a part's
        // own lead under its own courtyard is expected, not a collision.
        let court = shape(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let own_lead = shape_ex(Kind::Through, "U1", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "GND", true, true);
        assert!(!conflict(&court, &own_lead, None, &cfg()));
    }

    #[test]
    fn courtyard_over_a_through_pad_that_is_not_a_lead_falls_through_to_the_via_rule() {
        // Not a lead (a thermal via under its own exposed pad, say): the
        // via rule still applies, and is off by default.
        let court = shape(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let not_lead = shape_ex(Kind::Through, "U2", rect(0.5, 0.5, 0.3, 0.3), 3, 0xFFFF_FFFF, "GND", true, false);
        assert!(!conflict(&court, &not_lead, None, &cfg()));
        let mut c = cfg();
        c.vias_block_courtyards = true;
        // still not blocked: not_lead's owner IS a footprint, and the via
        // rule only blocks a through shape whose owner is NOT one (a routed
        // via, not another part's pad).
        assert!(!conflict(&court, &not_lead, None, &c));
    }

    /// `near` as it was: the hash grid's cells in turn, sorted, deduplicated, then filtered.
    fn near_by_hash(grid: &ShapeGrid, query: Bounds, gap: f64) -> Vec<usize> {
        let (x0, y0, x1, y1) = (query.0 - gap, query.1 - gap, query.2 + gap, query.3 + gap);
        let mut hits: Vec<usize> = Vec::new();
        for i in cell_at(x0, grid.cell)..=cell_at(x1, grid.cell) {
            for j in cell_at(y0, grid.cell)..=cell_at(y1, grid.cell) {
                if let Some(ks) = grid.grid.get(&(i, j)) {
                    hits.extend_from_slice(ks);
                }
            }
        }
        hits.sort_unstable();
        hits.dedup();
        hits.into_iter().filter(|&k| box_overlaps(grid.shapes[k].bbox, query, gap)).collect()
    }

    #[test]
    fn near_gives_what_the_hash_grid_gave_dense_or_not() {
        let mut state = 99u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
            ((state >> 33) as f64) / (u32::MAX as f64)
        };
        for spread in [1.0, 1.0e5] {      // the second is past what a dense array holds
            let mut obstacles = Vec::new();
            for i in 0..400 {
                let x = (next() * 100.0 - 50.0).round() / 2.0 * spread;
                let y = next() * 100.0 - 50.0;
                let (w, h) = (0.5 + next() * if i % 20 == 0 { 30.0 } else { 3.0 }, 0.5 + next() * 3.0);
                obstacles.push(shape(Kind::Pad, &format!("U{i}"), rect(x, y, w, h), 1, 1, "NET", true));
            }
            let grid = ShapeGrid::new(obstacles);
            assert_eq!(grid.dense.is_some(), spread < 100.0);
            let mut out = Vec::new();
            for _ in 0..3000 {
                let (x, y) = ((next() * 140.0 - 70.0) * if spread > 1.0 { 3.0e3 } else { 1.0 }, next() * 140.0 - 70.0);
                let q = (x, y, x + next() * 6.0, y + next() * 6.0);
                let gap = [0.0, 0.2, 1.0, 5.0][(next() * 4.0) as usize % 4];
                grid.near_into(q, gap, &mut out);
                assert_eq!(out, near_by_hash(&grid, q, gap));
                assert_eq!(grid.near(q, gap), out);
            }
        }
    }

    #[test]
    fn the_search_over_kept_shapes_finds_the_pair_the_one_that_builds_them_does() {
        let mut state = 4242u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
            ((state >> 33) as f64) / (u32::MAX as f64)
        };
        let kinds = [Kind::Pad, Kind::Courtyard, Kind::Silk, Kind::Body, Kind::Copper, Kind::Hole];
        let (mut some, mut none) = (0, 0);
        for round in 0..40 {
            let crowd = if round % 2 == 0 { 40 } else { 600 };
            let mut obstacles = Vec::new();
            for i in 0..crowd {
                let kind = kinds[(next() * 6.0) as usize % 6];
                obstacles.push(shape(kind, &format!("O{}", i % 7), rect(next() * 80.0, next() * 60.0, 0.4 + next() * 2.0, 0.4 + next() * 2.0), 1, 1,
                                      ["A", "B", ""][(next() * 3.0) as usize % 3], i % 3 == 0));
            }
            let item: Vec<Shape> = (0..30).map(|i| {
                let kind = kinds[(next() * 6.0) as usize % 6];
                shape(kind, &format!("P{}", i % 5), rect(next() * 8.0 - 4.0, next() * 6.0 - 3.0, 0.3 + next() * 1.5, 0.3 + next() * 1.5), 1, 1, "C", i % 2 == 0)
            }).collect();
            let grid = ShapeGrid::new(obstacles);
            let c = cfg();
            let mut drawn = item.clone();       // kept from one offset to the next, as a sweep keeps them
            for _ in 0..200 {
                let (dx, dy) = (next() * 100.0 - 10.0, next() * 80.0 - 10.0);
                let want = grid.first_conflict_shifted(&item, dx, dy, None, &c);
                let got = grid.first_conflict_shifted_in(&item, &mut drawn, dx, dy, None, &c);
                assert_eq!(got, want, "round {round} at ({dx}, {dy})");
                if want.is_some() { some += 1 } else { none += 1 }
            }
        }
        assert!(some > 300 && none > 300, "{some} conflicts, {none} clear");
    }

    #[test]
    fn grid_first_conflict_matches_a_brute_force_scan() {
        let mut rng_state = 12345u64;
        let mut next = move || {
            rng_state = rng_state.wrapping_mul(6364136223846793005).wrapping_add(1);
            ((rng_state >> 33) as f64) / (u32::MAX as f64)
        };
        let mut obstacles = Vec::new();
        for i in 0..500 {
            let x = next() * 100.0 - 50.0;
            let y = next() * 100.0 - 50.0;
            obstacles.push(shape(Kind::Pad, &format!("U{i}"), rect(x, y, 1.0, 1.0), 1, 1, "NET", true));
        }
        let grid = ShapeGrid::new(obstacles.clone());
        let candidates: Vec<Shape> = (0..50)
            .map(|i| {
                let x = (i as f64) * 2.0 - 50.0;
                shape(Kind::Pad, "CAND", rect(x, 0.0, 1.0, 1.0), 1, 1, "OTHER", true)
            })
            .collect();
        let c = cfg();
        let got = grid.first_conflict(&candidates, None, &c);
        // brute force
        let mut want = None;
        'outer: for (si, s) in candidates.iter().enumerate() {
            for (oi, o) in obstacles.iter().enumerate() {
                if box_overlaps(s.bbox, o.bbox, c.gap_for(s)) && conflict(s, o, None, &c) {
                    want = Some((si, oi));
                    break 'outer;
                }
            }
        }
        assert_eq!(got, want);
    }

    #[test]
    fn any_conflict_with_a_hint_is_the_same_as_the_first_conflict_at_every_offset() {
        let mut state = 99u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let mut obstacles = Vec::new();
        for i in 0..300 {
            let (x, y) = (next() * 20.0, next() * 20.0);
            let kind = [Kind::Pad, Kind::Through, Kind::Copper, Kind::Hole, Kind::Courtyard][(next() * 5.0) as usize % 5];
            let net = ["A", "B", "C", ""][(next() * 4.0) as usize % 4];
            let size = 0.3 + next();
            let layers = if kind == Kind::Courtyard { 0 } else { 1 + (next() * 3.0) as u32 % 3 };
            obstacles.push(shape(kind, &format!("O{i}"), rect(x, y, size, size * (0.5 + next())), 3, layers, net, i % 3 == 0));
        }
        let grid = ShapeGrid::new(obstacles);
        let c = cfg();
        let skip: IdSet = (0..300).filter(|i| i % 11 == 0).collect();
        let (mut clear, mut blocked) = (0, 0);
        for round in 0..20 {
            let origin = vec![
                shape(Kind::Through, "V", rect(0.0, 0.0, 0.6, 0.6), 3, 3, ["A", "B"][round % 2], false),
                shape(Kind::Hole, "V", rect(0.0, 0.0, 0.3, 0.3), 3, 0, ["A", "B"][round % 2], false),
            ];
            let (cx, cy) = (next() * 20.0, next() * 20.0);
            let mut hint = Blockers::new(&origin);
            for k in 0..400 {
                let (dx, dy) = (cx + (k % 20) as f64 * 0.05, cy + (k / 20) as f64 * 0.05);
                let want = grid.first_conflict_shifted_excluding(&origin, dx, dy, None, &c, &skip).is_some();
                let got = grid.any_conflict_shifted_excluding(&origin, dx, dy, None, &c, &skip, &mut hint);
                assert_eq!(got, want, "round {round} offset {k}");
                if got { blocked += 1 } else { clear += 1 }
            }
        }
        assert!(clear > 100 && blocked > 100, "{clear} clear, {blocked} blocked");
    }

    #[test]
    fn the_largest_clearance_cut_changes_no_answer() {
        let mut state = 7u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let mut c = cfg();
        c.net_clearance.insert("A".into(), 0.3);
        c.net_clearance.insert("B".into(), 0.15);
        c.rules.push(ClearanceRule { on: Some("C".into()), min: 0.5, ..Default::default() });
        c.rules.push(ClearanceRule { between: Some(("A".into(), "B".into())), min: 0.1, ..Default::default() });
        let mut cut = ConflictConfig { max_clearance: largest_clearance(c.default_clearance, &c.net_clearance, &c.rules), ..cfg() };
        cut.net_clearance = c.net_clearance.clone();
        cut.rules = c.rules.clone();
        assert_eq!(cut.max_clearance, 0.5);
        let kinds = [Kind::Pad, Kind::Through, Kind::Copper];
        let nets = ["A", "B", "C", "D", ""];
        let mut hits = 0;
        for _ in 0..20000 {
            let mk = |next: &mut dyn FnMut() -> f64| {
                let (x, y, w) = (next() * 3.0, next() * 3.0, 0.2 + next() * 0.8);
                shape(kinds[(next() * 3.0) as usize % 3], "o", rect(x, y, w, w * (0.5 + next())), 3, 1 + (next() * 3.0) as u32 % 3,
                      nets[(next() * 5.0) as usize % 5], false)
            };
            let (s, o) = (mk(&mut next), mk(&mut next));
            for explicit in [None, Some(0.25)] {
                let want = conflict(&s, &o, explicit, &c);
                assert_eq!(conflict(&s, &o, explicit, &cut), want);
                hits += want as usize;
            }
        }
        assert!(hits > 1000, "{hits}");
    }

    #[test]
    fn first_conflict_shifted_excluding_ignores_a_skipped_obstacle() {
        // A via's own hole (net-blind, so it always reads as a hole-to-hole
        // conflict with a shifted copy of itself unless excluded) - see
        // first_conflict_shifted_excluding's own doc.
        let own_hole = shape(Kind::Hole, "", rect(0.0, 0.0, 0.3, 0.3), 3, 0, "GND", false);
        let grid = ShapeGrid::new(vec![own_hole]);
        let moved_hole = vec![shape(Kind::Hole, "", rect(0.0, 0.0, 0.3, 0.3), 3, 0, "GND", false)];
        let c = cfg();
        // unskipped: the moved hole still conflicts with its own static copy
        assert_eq!(grid.first_conflict_shifted(&moved_hole, 0.05, 0.0, None, &c), Some((0, 0)));
        // skipped: no obstacle is left to conflict with
        let mut skip = IdSet::default();
        skip.insert(0usize);
        assert_eq!(grid.first_conflict_shifted_excluding(&moved_hole, 0.05, 0.0, None, &c, &skip), None);
    }

    #[test]
    fn first_clear_offset_style_loop_finds_the_first_unblocked_shift() {
        // give_way's own move search (giveway.py _give): NativeObstacles::
        // first_clear_offset is a thin loop over first_conflict_shifted,
        // tried here directly since the pyclass itself has no logic beyond
        // that loop.
        let blocker = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "NET", true);
        let grid = ShapeGrid::new(vec![blocker]);
        let via = shape(Kind::Pad, "V1", rect(0.0, 0.0, 0.4, 0.4), 1, 1, "OTHER", true);
        let origin = vec![via];
        let c = cfg();
        let offsets = [(0.0, 0.0), (0.3, 0.0), (1.0, 0.0)];
        let mut found = None;
        for (i, &(dx, dy)) in offsets.iter().enumerate() {
            if grid.first_conflict_shifted(&origin, dx, dy, None, &c).is_none() {
                found = Some(i);
                break;
            }
        }
        assert_eq!(found, Some(2)); // 1.0 mm clears a 1.0 mm pad's clearance from a 0.4 mm via
    }

    #[test]
    fn first_conflict_shifted_matches_first_conflict_on_pre_shifted_shapes() {
        let obstacles = vec![
            shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "NET", true),
            shape(Kind::Courtyard, "U2", rect(5.0, 5.0, 4.0, 4.0), 1, 0, "", true),
        ];
        let grid = ShapeGrid::new(obstacles);
        let origin = vec![
            shape(Kind::Pad, "CAND", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "OTHER", true),
            shape(Kind::Courtyard, "CAND", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true),
        ];
        let c = cfg();
        for (dx, dy) in [(0.0, 0.0), (0.3, 0.0), (5.0, 5.0), (4.9, 4.9), (20.0, 20.0)] {
            let shifted: Vec<Shape> = origin
                .iter()
                .map(|s| {
                    let bbox = (s.bbox.0 + dx, s.bbox.1 + dy, s.bbox.2 + dx, s.bbox.3 + dy);
                    let poly = s.poly.iter().map(|p| (p.0 + dx, p.1 + dy)).collect();
                    Shape { poly, bbox, ..s.clone() }
                })
                .collect();
            let want = grid.first_conflict(&shifted, None, &c);
            let got = grid.first_conflict_shifted(&origin, dx, dy, None, &c);
            assert_eq!(got, want, "at ({dx}, {dy})");
        }
    }
}
