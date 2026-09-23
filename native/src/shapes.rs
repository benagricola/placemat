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

use crate::geometry::{poly_distance, polys_overlap, Point};
use std::collections::HashMap;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Courtyard,
    Pad,
    Through,
    Copper,
    Npth,
    Mask,
    Silk,
    Body,
}

impl Kind {
    pub fn from_str(s: &str) -> Option<Kind> {
        match s {
            "courtyard" => Some(Kind::Courtyard),
            "pad" => Some(Kind::Pad),
            "through" => Some(Kind::Through),
            "copper" => Some(Kind::Copper),
            "npth" => Some(Kind::Npth),
            "mask" => Some(Kind::Mask),
            "silk" => Some(Kind::Silk),
            "body" => Some(Kind::Body),
            _ => None,
        }
    }

    fn is_drawn(self) -> bool {
        matches!(self, Kind::Silk | Kind::Mask | Kind::Body)
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

/// `Occupancy._conflict`: the DRC rules in occupancy terms.
pub fn conflict(s: &Shape, o: &Shape, explicit_clearance: Option<f64>, cfg: &ConflictConfig) -> bool {
    if s.kind.is_drawn() || o.kind.is_drawn() {
        return drawn_conflict(s, o, cfg);
    }
    if s.kind == Kind::Courtyard && o.kind == Kind::Courtyard {
        let depth = (s.bbox.2.min(o.bbox.2) - s.bbox.0.max(o.bbox.0))
            .min(s.bbox.3.min(o.bbox.3) - s.bbox.1.max(o.bbox.1));
        let has_width = (s.bbox.2 - s.bbox.0) > 0.0 && (o.bbox.2 - o.bbox.0) > 0.0;
        // to a nanometre: depth is a difference of coordinates, and exactly
        // the allowance must not read as more (placemat commit c785a04).
        if depth <= cfg.touch + 1e-9 && has_width {
            return false;
        }
        return (s.faces & o.faces) != 0 && polys_overlap(&s.poly, &o.poly);
    }
    if s.kind == Kind::Courtyard || o.kind == Kind::Courtyard {
        let (court, other) = if s.kind == Kind::Courtyard { (s, o) } else { (o, s) };
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
    if s.kind == Kind::Npth && is_copperish(o.kind) {
        return polys_overlap(&s.poly, &o.poly);
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
        let bbox = bounds(&poly);
        Shape { kind, faces, layers, net: net.into(), poly, bbox, owner: owner.into(), owner_is_footprint, is_lead }
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
        }
    }

    #[test]
    fn touching_courtyards_do_not_conflict() {
        let a = shape(Kind::Courtyard, "U1", rect(0.0, 0.0, 2.0, 2.0), 1, 0, "", true);
        let b = shape(Kind::Courtyard, "U2", rect(2.0, 0.0, 2.0, 2.0), 1, 0, "", true); // touching edge
        assert!(!conflict(&a, &b, None, &cfg()));
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
}
