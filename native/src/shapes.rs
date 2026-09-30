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

use crate::geometry::{point_in_polygon, point_segment_distance, poly_distance, polys_overlap, Point};
use std::collections::HashMap;

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
}

pub struct ConflictConfig {
    pub touch: f64,
    pub vias_block_courtyards: bool,
    pub silk_clearance: f64,
    pub component_spacing: f64,
    pub default_clearance: f64,
    pub net_clearance: HashMap<String, f64>, // net name -> its netclass's own clearance
    pub gap: f64,       // Occupancy._gap: the conflict-gap prefilter for a non-drawn shape
    pub drawn_gap: f64, // Occupancy._drawn_gap: for a silk/mask/body shape
    pub hole_to_hole: f64,   // BoardGeometry.hole_to_hole: two drilled holes, whatever their nets
    pub hole_clearance: f64, // BoardGeometry.hole_clearance: copper to an unplated hole
}

impl ConflictConfig {
    fn pair_clearance(&self, explicit: Option<f64>, net_a: &str, net_b: &str) -> f64 {
        if let Some(c) = explicit {
            return c;
        }
        match (self.net_clearance.get(net_a), self.net_clearance.get(net_b)) {
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
    poly_distance(&s.poly, &o.poly) < gap - 1e-9
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

/// Whether two kinds can meet at all: a plated hole meets only another hole.
fn may_meet(a: Kind, b: Kind) -> bool {
    if a == Kind::Hole {
        return b.is_hole();
    }
    if b == Kind::Hole {
        return a.is_hole();
    }
    true
}

/// `Occupancy._conflict`: the DRC rules in occupancy terms.
pub fn conflict(s: &Shape, o: &Shape, explicit_clearance: Option<f64>, cfg: &ConflictConfig) -> bool {
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
        return ((sx - ox).powi(2) + (sy - oy).powi(2)).sqrt() - rs - ro < need - 1e-9;
    }
    if s.kind == Kind::Hole || o.kind == Kind::Hole {
        return false; // its pad or via ring answers for everything else
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
        let clr = cfg.pair_clearance(explicit_clearance, &s.net, &o.net);
        if box_gap(s.bbox, o.bbox) >= clr - 1e-9 {
            return false;
        }
        return poly_distance(&s.poly, &o.poly) < clr - 1e-9;
    }
    if (s.kind == Kind::Npth && is_copperish(o.kind)) || (o.kind == Kind::Npth && is_copperish(s.kind)) {
        if polys_overlap(&s.poly, &o.poly) {
            return true;
        }
        let need = cfg.hole_clearance;
        let (hole, metal) = if s.kind == Kind::Npth { (s, o) } else { (o, s) };
        let slack = HOLE_SLACK * (hole.bbox.2 - hole.bbox.0);
        return need > 0.0 && box_gap(hole.bbox, metal.bbox) < need + slack - 1e-9
            && circle_distance(hole, &metal.poly) < need - 1e-9;
    }
    false
}

/// A uniform grid over registered obstacle boxes, built once per `scan()`
/// (mirrors `ShapeIndex`'s own grid, `CELL = 2.0`), queried once per
/// candidate shape at that shape's own box and gap - see the module doc for
/// why this one query replaces `near()` + the per-shape `close` filter.
pub struct ShapeGrid {
    shapes: Vec<Shape>,
    cell: f64,
    grid: HashMap<(i64, i64), Vec<usize>>,
}

const CELL: f64 = 2.0;

fn cell_at(v: f64, cell: f64) -> i64 {
    (v / cell).floor() as i64
}

impl ShapeGrid {
    pub fn new(shapes: Vec<Shape>) -> Self {
        let mut grid: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
        for (k, s) in shapes.iter().enumerate() {
            let (x0, y0, x1, y1) = s.bbox;
            for i in cell_at(x0, CELL)..=cell_at(x1, CELL) {
                for j in cell_at(y0, CELL)..=cell_at(y1, CELL) {
                    grid.entry((i, j)).or_default().push(k);
                }
            }
        }
        ShapeGrid { shapes, cell: CELL, grid }
    }

    /// Indices of registered shapes whose box overlaps `query` inflated by
    /// `gap`, in registration order (matching `ShapeIndex.near`'s own
    /// `sorted(hits)` - insertion order - so a "first conflict" search over
    /// this order matches Python's).
    fn near(&self, query: Bounds, gap: f64) -> Vec<usize> {
        let (x0, y0, x1, y1) = (query.0 - gap, query.1 - gap, query.2 + gap, query.3 + gap);
        let mut hits: Vec<usize> = Vec::new();
        let mut seen = vec![false; self.shapes.len()];
        for i in cell_at(x0, self.cell)..=cell_at(x1, self.cell) {
            for j in cell_at(y0, self.cell)..=cell_at(y1, self.cell) {
                if let Some(ks) = self.grid.get(&(i, j)) {
                    for &k in ks {
                        if !seen[k] {
                            seen[k] = true;
                            hits.push(k);
                        }
                    }
                }
            }
        }
        hits.sort_unstable();
        hits.into_iter().filter(|&k| box_overlaps(self.shapes[k].bbox, query, gap)).collect()
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
        for (si, s0) in origin_shapes.iter().enumerate() {
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            let gap = cfg.gap_for(s0);
            for oi in self.near(bbox, gap) {
                if !may_meet(s0.kind, self.shapes[oi].kind) {
                    continue;
                }
                let poly: Vec<Point> = s0.poly.iter().map(|p| (p.0 + dx, p.1 + dy)).collect();
                let s = Shape { poly, bbox, ..s0.clone() };
                if conflict(&s, &self.shapes[oi], explicit_clearance, cfg) {
                    return Some((si, oi));
                }
            }
        }
        None
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
        skip: &std::collections::HashSet<usize>,
    ) -> Option<(usize, usize)> {
        for (si, s0) in origin_shapes.iter().enumerate() {
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            let gap = cfg.gap_for(s0);
            for oi in self.near(bbox, gap) {
                if skip.contains(&oi) || !may_meet(s0.kind, self.shapes[oi].kind) {
                    continue;
                }
                let poly: Vec<Point> = s0.poly.iter().map(|p| (p.0 + dx, p.1 + dy)).collect();
                let s = Shape { poly, bbox, ..s0.clone() };
                if conflict(&s, &self.shapes[oi], explicit_clearance, cfg) {
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
        Shape { kind, faces, layers, net: net.into(), poly, bbox, owner: owner.into(), owner_is_footprint, is_lead, margin }
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
            net_clearance: HashMap::new(),
            gap: 1.0,
            drawn_gap: 0.2,
            hole_to_hole: 0.25,
            hole_clearance: 0.0,
        }
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
        // (>= clr - 1e-9) already rules legal, before any polygon walk.
        let a = shape(Kind::Pad, "U1", rect(0.0, 0.0, 1.0, 1.0), 1, 1, "A", true);
        let b = shape(Kind::Pad, "U2", rect(1.2, 0.0, 1.0, 1.0), 1, 1, "B", true);
        assert!(!conflict(&a, &b, None, &cfg()));
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
        let mut skip = std::collections::HashSet::new();
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
