//! Complete prepared escape judgements. All intent, pool membership and pair
//! clearances are frozen before candidates; geometry and nearest targets stay
//! in Rust. This surface is not adopted until independent board parity gates.
use crate::candidate::{Bounds, PlacedRecord, Point, PreparedCandidate};
use crate::escape_contacts::{ContactFacts, PreparedContacts, View};
use crate::surface::{self, Path, Shape};
use crate::NativeDelta;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

type Evaluation = ((f64, f64, f64, f64, f64, f64), i64, usize, usize, usize,
                   Vec<(String, String, u8)>, Vec<(String, String)>);
#[derive(Default)]
struct Profile {
    candidate: f64, wire_cross: f64, escape_cross: f64, records: f64,
    lanes: f64, contacts: f64, classification: f64, aim: f64, blockers: f64,
    path_setup: f64, judge: f64, supplemental: f64, layout: f64,
}
impl Profile {
    fn rows(self) -> Vec<(&'static str, f64)> {
        vec![("candidate_us", self.candidate), ("wire_cross_us", self.wire_cross),
             ("escape_cross_us", self.escape_cross), ("records_us", self.records),
             ("lanes_us", self.lanes), ("contacts_us", self.contacts),
             ("classification_total_us", self.classification), ("aim_us", self.aim),
             ("blockers_us", self.blockers), ("path_setup_us", self.path_setup),
             ("surface_judge_us", self.judge), ("supplemental_us", self.supplemental),
             ("layout_us", self.layout)]
    }
}
// Only inspection supplies Some: production does not read the clock.
macro_rules! profiled {
    ($profile:expr, $stage:ident, $call:expr) => {{
        if let Some(timing) = $profile.as_mut() {
            let started = std::time::Instant::now();
            let result = $call;
            timing.$stage += started.elapsed().as_secs_f64() * 1e6;
            result
        } else { $call }
    }};
}

const CONTACT: u8 = 1;
const PATH: u8 = 2;
const HOLE: u8 = 4;
const BAN: u8 = 8;
// pad number, original net, original unconnected flag
pub type PadIntent = (String, String, bool);
// ref, pads in original grouping order, (rotation, cos, sin) for each turn
pub type FieldRecord = (String, Vec<PadIntent>, Vec<(f64, f64, f64)>);
// net, size, quiet, track width, clearance, via diameter, drill, maximum foe
// reach, exact pair-via clearances in rest-then-moving shape order
pub type NetRecord = (String, usize, bool, f64, f64, f64, f64, f64, Vec<f64>);
struct Pad {
    number: String,
    net: String,
    unconnected: bool,
}
// Baseline facts are produced by the independent lifted-board oracle.
// owner, (number, net, unconnected, way, full influence region, wall, handoff)
type RestCacheRecord = (String, Vec<(String, String, bool, u8, Bounds, bool, bool)>);
struct CachedPad {
    way: u8, region: Bounds, wall: bool, handoff: bool,
}
// One field's lanes and via spots, and each pad's contact shapes and their box: all of a fixed field's own geometry,
// so a rest field's are made once per turn.
struct FieldLanes {
    lanes: Vec<(String, surface::Lane, Point)>,
    spots: Vec<(String, surface::Spot)>,
    mines: Vec<(Vec<usize>, Bounds)>,
}
// What a rest pad's judgement is without its target's direction, on the lifted board, and the boxes that geometry
// must stay out of for that to hold: the pad's blocker region, both search reaches and its own copper chain. Moving
// geometry clear of every box is invisible to every test the judgement makes.
struct PadFacts {
    // Gathered with no candidate geometry reaching the guard: the facts hold for the lifted board. Facts that are not
    // valid keep only their guard, which sends the pad to a full judgement while geometry still reaches it.
    valid: bool,
    // The pad is judged (a signal net with a target, not joined or on another part's pad).
    eligible: bool,
    centre: Point,
    surface: Option<surface::SurfaceFacts>,
    wall: bool,
    handoff: bool,
    guard: Vec<Bounds>,
}
// One pad's judgement: its way, whether its own copper chain is walled in, whether it is an unanswered hand-off,
// and, when its facts were gathered, those facts.
struct Judged {
    way: u8,
    wall: bool,
    handoff: bool,
    facts: Option<PadFacts>,
}
struct Field {
    owner: String,
    pads: Vec<Pad>,
    turns: Vec<(f64, f64, f64)>,
    cached: Option<Vec<CachedPad>>,
}
struct Net {
    size: usize,
    quiet: bool,
    track_width: f64,
    clearance: f64,
    diameter: f64,
    drill: f64,
    foe_reach: f64,
    pairs: Vec<f64>,
}
struct Search {
    path: Path,
    copper: Vec<Shape>,
    holes: Vec<Shape>,
    // The box a shape must overlap to take part in the search.
    reach: Bounds,
}
struct Settings {
    reach: f64,
    depth: f64,
    cell: f64,
    minimum: usize,
    epsilon: f64,
    hole_clearance: f64,
    lane_via_exit: bool,
}
#[pyclass]
pub struct PreparedSurface {
    contacts: PreparedContacts,
    identity: Arc<()>,
    delta_identity: Arc<()>,
    delta_revision: u64,
    rest_roles: Vec<u8>,
    moving_roles: Vec<Vec<u8>>,
    fields: Vec<Field>,
    nets: HashMap<String, Net>,
    settings: Settings,
    cache_usage: (usize, usize),
    cache_reasons: (usize, usize, usize, usize, usize),
    rest_index: Option<RestIndex>,
    // Per (field, turn): a rest field's lanes. Per (field, pad, turn): a rest pad's facts on the lifted board.
    field_lanes: HashMap<(usize, usize), Arc<FieldLanes>>,
    pad_facts: HashMap<(usize, usize, usize), PadFacts>,
    // Per (field, pad): a rest pad's contacts on the lifted board, its copper chain, and the boxes of its contact
    // shapes and chain members. A candidate whose shapes on the pad's net overlap none of those boxes touches none of
    // those shapes, so its contacts are the same.
    contact_cache: HashMap<(usize, usize), (ContactFacts, Vec<usize>, Vec<Bounds>)>,
    // Per (field, pad, turn): a rest pad's search on the lifted board.
    lifted: HashMap<(usize, usize, usize), surface::LiftedPad>,
}

// The rest shapes by the Python blocker grid's 2 mm buckets (`near`): a shape is in every bucket its box's
// floor(/2) range covers. Shapes whose bucket ranges meet a box's are a superset of those that overlap it or
// are near it, so a judgement that reads them, in index order, reads what a pass over every shape reads.
struct RestIndex {
    cells: HashMap<(i64, i64), Vec<usize>>,
    bans: Vec<usize>,
}
impl RestIndex {
    fn bucket(v: f64) -> i64 {
        (v / 2.0).floor() as i64
    }
    // The rest shapes whose buckets meet `b`'s, and `extra`, ascending, each once.
    fn near(&self, b: Bounds, extra: &[usize]) -> Vec<usize> {
        let mut out: Vec<usize> = extra.to_vec();
        for x in Self::bucket(b.0)..=Self::bucket(b.2) {
            for y in Self::bucket(b.1)..=Self::bucket(b.3) {
                if let Some(cell) = self.cells.get(&(x, y)) {
                    out.extend_from_slice(cell);
                }
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }
}
fn bounds_union(boxes: impl Iterator<Item = Bounds>) -> Bounds {
    boxes.fold(
        (
            f64::INFINITY,
            f64::INFINITY,
            f64::NEG_INFINITY,
            f64::NEG_INFINITY,
        ),
        |b, a| (b.0.min(a.0), b.1.min(a.1), b.2.max(a.2), b.3.max(a.3)),
    )
}
fn inflate(b: Bounds, r: f64) -> Bounds {
    (b.0 - r, b.1 - r, b.2 + r, b.3 + r)
}
fn overlaps(a: Bounds, b: Bounds) -> bool {
    a.0 < b.2 && b.0 < a.2 && a.1 < b.3 && b.1 < a.3
}
// The Python blocker grid uses inclusive floor(box / 2) buckets. It is a
// candidate set, not exact overlap: keep its deliberate conservative margin.
fn near(a: Bounds, b: Bounds) -> bool {
    (a.0 / 2.0).floor() <= (b.2 / 2.0).floor()
        && (b.0 / 2.0).floor() <= (a.2 / 2.0).floor()
        && (a.1 / 2.0).floor() <= (b.3 / 2.0).floor()
        && (b.1 / 2.0).floor() <= (a.3 / 2.0).floor()
}
fn record(s: &View<'_>, adjustment: f64) -> Shape {
    (
        s.polygon.to_vec(),
        s.bounds,
        s.layers,
        s.ends.to_vec(),
        adjustment,
    )
}
fn valid_role(kind: &str, layers: u32, role: u8) -> bool {
    crate::shapes::Kind::from_str(kind).is_some()
        && (role & CONTACT == 0 || matches!(kind, "pad" | "through" | "copper" | "npth"))
        && (role & PATH == 0 || matches!(kind, "pad" | "through" | "copper"))
        && (role & HOLE == 0 || kind == "npth")
        && (role & BAN == 0 || kind == "viaban")
        && (role & (CONTACT | PATH) == 0 || kind == "npth" || layers != 0)
}

// Which shapes a judgement's inputs are built from: the rest of the board's, the candidate's, or both.
#[derive(Clone, Copy, PartialEq)]
enum Part {
    All,
    Rest,
    Moving,
}

impl PreparedSurface {
    fn role(&self, turn: usize, index: usize) -> u8 {
        if index < self.rest_roles.len() {
            self.rest_roles[index]
        } else {
            self.moving_roles[turn][index - self.rest_roles.len()]
        }
    }
    fn mine(
        &self,
        candidate: &PreparedCandidate,
        turn: usize,
        owner: &str,
        number: &str,
    ) -> Vec<usize> {
        if let Some(found) = self.contacts.pad_shapes(turn, owner, number) {
            return found;
        }
        (0..self.contacts.shape_count(candidate, turn))
            .filter(|&i| {
                let s = self.contacts.shape(candidate, turn, i);
                self.role(turn, i) & CONTACT != 0
                    && s.owner == owner
                    && s.pad == number
                    && matches!(s.kind, "pad" | "through")
            })
            .collect()
    }
    /// The foes and via bans of a pad's lanes and spots within its blocker `region`.
    #[allow(clippy::too_many_arguments)]
    fn blockers(&self, candidate: &PreparedCandidate, turn: usize, field: &Field, pad: &Pad, net: &Net,
                region: Bounds, index: &RestIndex, part: Part) -> (Vec<surface::Foe>, Vec<Shape>) {
        let track = net.track_width / 2.0 + net.clearance;
        let mut foes = Vec::new();
        let mut bans = Vec::new();
        let rest = self.rest_roles.len();
        let near_rest = if part == Part::Moving { Vec::new() } else { index.near(region, &index.bans) };
        let moving = if part == Part::Rest { rest..rest } else { rest..self.contacts.shape_count(candidate, turn) };
        for i in near_rest.into_iter().chain(moving) {
            let s = self.contacts.shape(candidate, turn, i);
            let role = self.role(turn, i);
            if role & CONTACT != 0 && near(s.bounds, region) {
                let reach = if s.kind == "npth" {
                    Some((
                        track + self.settings.hole_clearance - net.clearance,
                        self.settings.hole_clearance,
                    ))
                } else if matches!(s.kind, "pad" | "through" | "copper")
                    && s.net != pad.net
                    && !(s.owner == field.owner && s.pad == pad.number)
                {
                    Some((track, net.pairs[i]))
                } else {
                    None
                };
                if let Some((lane, clr)) = reach {
                    foes.push((
                        record(&s, 0.0),
                        (lane - self.settings.epsilon).max(0.0)
                            + self.settings.cell,
                        clr - self.settings.epsilon,
                        s.kind == "npth",
                    ));
                }
            }
            if role & BAN != 0 && !s.net.split('\u{1f}').any(|n| n == pad.net) {
                bans.push(record(&s, 0.0));
            }
        }
        (foes, bans)
    }

    fn path(
        &self,
        candidate: &PreparedCandidate,
        turn: usize,
        field: &Field,
        pad: &Pad,
        mine: &[usize],
        own: &[usize],
        net: &Net,
        depth: f64,
        toward: Option<Point>,
        supplemental: bool,
        via_exit: bool,
        index: &RestIndex,
        part: Part,
    ) -> Search {
        let starts: Vec<_> = mine
            .iter()
            .chain(own)
            .map(|&i| self.contacts.shape(candidate, turn, i))
            .collect();
        let start_box = bounds_union(starts.iter().map(|s| s.bounds));
        let win = inflate(start_box, depth);
        let track = net.track_width / 2.0 + net.clearance;
        let via = net.diameter / 2.0 + net.clearance;
        let reach = inflate(win, track.max(via));
        let grid_box = inflate(start_box, self.settings.depth + 1.0);
        let layers = mine.iter().fold(0, |bits, &i| {
            bits | self.contacts.shape(candidate, turn, i).layers
        });
        let mut foes = Vec::new();
        let mut bans = Vec::new();
        let mut copper = Vec::new();
        let mut holes = Vec::new();
        let rest = self.rest_roles.len();
        let near_rest = if part == Part::Moving { Vec::new() } else { index.near(reach, &[]) };
        let moving = if part == Part::Rest { rest..rest } else { rest..self.contacts.shape_count(candidate, turn) };
        for i in near_rest.into_iter().chain(moving) {
            let s = self.contacts.shape(candidate, turn, i);
            let role = self.role(turn, i);
            if role & HOLE != 0 && overlaps(s.bounds, reach) {
                let hole = record(&s, self.settings.hole_clearance - net.clearance);
                holes.push(hole.clone());
                foes.push(hole);
            } else if role & (if supplemental { CONTACT } else { PATH }) != 0
                && s.kind != "npth"
                && (s.net != pad.net || pad.net.is_empty())
                && !(s.owner == field.owner && s.pad == pad.number)
                && overlaps(s.bounds, reach)
                && (!supplemental || near(s.bounds, grid_box))
            {
                let foe = record(&s, 0.0);
                copper.push(foe.clone());
                foes.push(foe);
            }
            if role & BAN != 0
                && overlaps(s.bounds, reach)
                && !s.net.split('\u{1f}').any(|n| n == pad.net)
            {
                bans.push(record(&s, -net.clearance));
            }
        }
        Search {
            path: (
                starts.iter().map(|s| record(s, 0.0)).collect(),
                foes,
                layers,
                win,
                track,
                via,
                toward,
                bans,
                self.settings.cell,
                self.settings.epsilon,
                via_exit,
            ),
            copper,
            holes,
            reach,
        }
    }
}
#[pymethods]
impl PreparedSurface {
    #[new]
    fn new(
        py: Python<'_>,
        candidate: PyRef<'_, PreparedCandidate>,
        delta: PyRef<'_, NativeDelta>,
        rest: Vec<PlacedRecord>,
        footprints: Vec<String>,
        rest_roles: Vec<u8>,
        moving_roles: Vec<Vec<u8>>,
        fields: Vec<FieldRecord>,
        nets: Vec<NetRecord>,
        settings: (f64, f64, f64, usize, f64, f64, bool),
    ) -> PyResult<Self> {
        let (reach, depth, cell, minimum, epsilon, hole_clearance, lane_via_exit) = settings;
        if [reach, depth, epsilon, hole_clearance]
            .iter()
            .any(|v| !v.is_finite() || *v < 0.0 || *v > 1e9)
            || !cell.is_finite()
            || cell <= 0.0
            || cell > 1e9
            || minimum == 0
            || rest_roles.len() != rest.len()
            || moving_roles.len() != candidate.turn_count()
            || moving_roles
                .iter()
                .enumerate()
                .any(|(t, m)| m.len() != candidate.turn(t).shapes.len())
            || rest_roles
                .iter()
                .chain(moving_roles.iter().flatten())
                .any(|r| *r > 15)
            || moving_roles.iter().any(|r| r != &moving_roles[0])
        {
            return Err(PyValueError::new_err(
                "prepared surface dimensions/settings invalid",
            ));
        }
        let count = rest.len() + moving_roles[0].len();
        if nets.len().checked_mul(count).is_none_or(|n| n > 4_000_000) || fields.len() > 100_000 {
            return Err(PyValueError::new_err(
                "prepared surface intent capacity invalid",
            ));
        }
        for (record, role) in rest.iter().zip(&rest_roles) {
            if !valid_role(&record.1, record.4, *role) {
                return Err(PyValueError::new_err("prepared surface rest role invalid"));
            }
        }
        for (turn, roles) in moving_roles.iter().enumerate() {
            for (index, (shape, role)) in candidate.turn(turn).shapes.iter().zip(roles).enumerate()
            {
                let original = &candidate.turn(0).shapes[index];
                if !valid_role(&shape.kind, shape.layers, *role)
                    || shape.owner != original.owner
                    || shape.kind != original.kind
                    || shape.net != original.net
                    || shape.pad != original.pad
                    || shape.layers != original.layers
                    || shape.lane != original.lane
                    || shape.wire != original.wire
                {
                    return Err(PyValueError::new_err(
                        "prepared surface moving role/source invalid",
                    ));
                }
            }
        }
        let footprint_refs: HashSet<_> = footprints.iter().map(String::as_str).collect();
        let expected_pads: HashSet<_> = rest
            .iter()
            .zip(&rest_roles)
            .filter(|(s, r)| {
                **r & CONTACT != 0
                    && matches!(s.1.as_str(), "pad" | "through")
                    && footprint_refs.contains(s.0.as_str())
            })
            .map(|(s, _)| (s.0.clone(), s.3.clone()))
            .chain(
                candidate
                    .turn(0)
                    .shapes
                    .iter()
                    .zip(&moving_roles[0])
                    .filter(|(s, r)| {
                        **r & CONTACT != 0
                            && matches!(s.kind.as_str(), "pad" | "through")
                            && footprint_refs.contains(s.owner.as_str())
                    })
                    .map(|(s, _)| (s.owner.clone(), s.pad.clone())),
            )
            .collect();
        let declared_pads: HashSet<_> = fields
            .iter()
            .flat_map(|(owner, pads, _)| {
                pads.iter()
                    .map(move |(number, _, _)| (owner.clone(), number.clone()))
            })
            .collect();
        if expected_pads != declared_pads
            || fields
                .iter()
                .any(|(owner, _, _)| !footprint_refs.contains(owner.as_str()))
        {
            return Err(PyValueError::new_err(
                "prepared surface pad manifest incomplete",
            ));
        }

        let mut net_map = HashMap::new();
        for (name, size, quiet, track_width, clearance, diameter, drill, foe_reach, pairs) in nets {
            if name.is_empty()
                || pairs.len() != count
                || [track_width, clearance, diameter, drill, foe_reach]
                    .iter()
                    .chain(&pairs)
                    .any(|v| !v.is_finite() || *v < 0.0 || *v > 1e9)
                || net_map.contains_key(&name)
            {
                return Err(PyValueError::new_err("prepared surface net intent invalid"));
            }
            net_map.insert(
                name,
                Net {
                    size,
                    quiet,
                    track_width,
                    clearance,
                    diameter,
                    drill,
                    foe_reach,
                    pairs,
                },
            );
        }
        let mut field_records = Vec::new();
        let mut refs = HashSet::new();
        for (owner, pads, turns) in fields {
            let mut numbers = HashSet::new();
            if !refs.insert(owner.clone())
                || turns.len() != candidate.turn_count()
                || pads.len() > 100_000
                || turns.iter().any(|(r, c, s)| {
                    !r.is_finite()
                        || !c.is_finite()
                        || !s.is_finite()
                        || c.abs() > 1.0
                        || s.abs() > 1.0
                        || (crate::exact::hypot(*c, *s) - 1.0).abs() > 1e-9
                })
                || pads.iter().any(|(number, net, _)| {
                    !numbers.insert(number.clone())
                        || (pads.len() >= minimum && !net.is_empty() && !net_map.contains_key(net))
                })
            {
                return Err(PyValueError::new_err(
                    "prepared surface field intent invalid",
                ));
            }
            field_records.push(Field {
                owner,
                pads: pads
                    .into_iter()
                    .map(|(number, net, unconnected)| Pad {
                        number,
                        net,
                        unconnected,
                    })
                    .collect(),
                turns,
                cached: None,
            });
        }
        let identity = candidate.identity.clone();
        let mut contacts = PreparedContacts::new(py, rest, footprints)?;
        contacts.configure_contact_roles(
            candidate,
            rest_roles.iter().map(|r| r & CONTACT != 0).collect(),
            moving_roles
                .iter()
                .map(|m| m.iter().map(|r| r & CONTACT != 0).collect())
                .collect(),
        )?;
        Ok(Self {
            contacts,
            identity,
            delta_identity: delta.identity.clone(),
            delta_revision: delta.revision,
            rest_roles,
            moving_roles,
            fields: field_records,
            nets: net_map,
            settings: Settings {
                reach,
                depth,
                cell,
                minimum,
                epsilon,
                hole_clearance,
                lane_via_exit,
            },
            cache_usage: (0, 0),
            cache_reasons: (0, 0, 0, 0, 0),
            rest_index: None,
            field_lanes: HashMap::new(),
            pad_facts: HashMap::new(),
            contact_cache: HashMap::new(),
            lifted: HashMap::new(),
        })
    }

    /// Bind independent baseline facts atomically to this exact manifest.
    fn configure_rest_cache(&mut self, candidate: PyRef<'_, PreparedCandidate>,
                            delta: PyRef<'_, NativeDelta>, records: Vec<RestCacheRecord>) -> PyResult<()> {
        if !Arc::ptr_eq(&self.identity, &candidate.identity)
            || !Arc::ptr_eq(&self.delta_identity, &delta.identity)
            || self.delta_revision != delta.revision {
            return Err(PyValueError::new_err("rest cache snapshot identity changed"));
        }
        let mut prepared = Vec::new();
        let mut owners = HashSet::new();
        for (owner, pads) in records {
            let Some(index) = self.fields.iter().position(|field| field.owner == owner) else {
                return Err(PyValueError::new_err("rest cache field is missing"));
            };
            let field = &self.fields[index];
            if !owners.insert(owner.clone()) || pads.len() != field.pads.len()
                || candidate.turn(0).shapes.iter().any(|shape| shape.owner == owner) {
                return Err(PyValueError::new_err("rest cache field source is moving or duplicated"));
            }
            let mut cached = Vec::new();
            for ((number, net, unconnected, way, region, wall, handoff), expected) in pads.into_iter().zip(&field.pads) {
                if number != expected.number || net != expected.net || unconnected != expected.unconnected
                    || way > 4 || (way == 3 && !wall)
                    || [region.0, region.1, region.2, region.3].iter().any(|v| !v.is_finite())
                    || region.0 > region.2 || region.1 > region.3 {
                    return Err(PyValueError::new_err("rest cache pad manifest invalid"));
                }
                let net_record = self.nets.get(&net);
                if handoff && !net_record.is_some_and(|n| n.size < 2) {
                    return Err(PyValueError::new_err("rest cache handoff intent invalid"));
                }
                let mine = self.mine(&candidate, 0, &owner, &number);
                if mine.is_empty() || mine.iter().any(|&i| i >= self.rest_roles.len()) {
                    return Err(PyValueError::new_err("rest cache pad is not immutable rest geometry"));
                }
                let bounds = bounds_union(mine.iter().map(|&i| self.contacts.shape(&candidate, 0, i).bounds));
                let minimum = inflate(inflate(inflate(bounds, self.settings.reach.max(self.settings.depth)),
                                               net_record.map_or(0.0, |n| n.foe_reach)), self.settings.cell);
                if region.0 > minimum.0 || region.1 > minimum.1 || region.2 < minimum.2 || region.3 < minimum.3 {
                    return Err(PyValueError::new_err("rest cache influence omits the pad search window"));
                }
                cached.push(CachedPad { way, region, wall, handoff });
            }
            prepared.push((index, cached));
        }
        // No partial cache publication after a later malformed record.
        for field in &mut self.fields { field.cached = None; }
        self.field_lanes.clear();
        self.pad_facts.clear();
        self.contact_cache.clear();
        self.lifted.clear();
        for (index, pads) in prepared { self.fields[index].cached = Some(pads); }
        Ok(())
    }

    fn cache_usage(&self) -> (usize, usize) { self.cache_usage }

    /// Why the last evaluation judged fields again: (fields without a cache, cached fields with a pad on a net the
    /// candidate touches but no region it reaches, cached fields whose region it reaches, pads judged again in full,
    /// pads judged on their facts against a new aim).
    fn cache_reasons(&self) -> (usize, usize, usize, usize, usize) { self.cache_reasons }

    /// Full native geometry, eligibility, aim and supplemental judgements.
    /// Counts are absolute except signed crossed-edge change. Returned ways
    /// are inspection evidence; search adoption remains separately gated.
    #[pyo3(signature=(candidate,delta,x,y,turn,inspect=false))]
    fn evaluate(
        &mut self,
        py: Python<'_>,
        mut candidate: PyRefMut<'_, PreparedCandidate>,
        mut delta: PyRefMut<'_, NativeDelta>,
        x: f64,
        y: f64,
        turn: usize,
        inspect: bool,
    ) -> PyResult<(
        (f64, f64, f64, f64, f64, f64),
        i64,
        usize,
        usize,
        usize,
        Vec<(String, String, u8)>,
        Vec<(String, String)>,
    )> {
        self.evaluate_inner(py, &mut candidate, &mut delta, x, y, turn, inspect)
    }

    /// Diagnostic stage timings include timer overhead; never used by sweep.
    fn profile(&mut self, py: Python<'_>, mut candidate: PyRefMut<'_, PreparedCandidate>,
               mut delta: PyRefMut<'_, NativeDelta>, x: f64, y: f64, turn: usize)
               -> PyResult<(Evaluation, Vec<(&'static str, f64)>)> {
        let mut timings = Some(Profile::default());
        let result = self.evaluate_profiled(py, &mut candidate, &mut delta, x, y, turn, true, &mut timings)?;
        Ok((result, timings.unwrap().rows()))
    }
}

impl PreparedSurface {
    pub(crate) fn evaluate_inner(&mut self, py: Python<'_>, candidate: &mut PreparedCandidate,
        delta: &mut NativeDelta, x: f64, y: f64, turn: usize, inspect: bool) -> PyResult<Evaluation> {
        self.evaluate_profiled(py, candidate, delta, x, y, turn, inspect, &mut None)
    }

    fn evaluate_profiled(&mut self, py: Python<'_>, candidate: &mut PreparedCandidate,
        delta: &mut NativeDelta, x: f64, y: f64, turn: usize, inspect: bool,
        profile: &mut Option<Profile>) -> PyResult<Evaluation> {
        self.check(candidate, delta)?;
        profiled!(profile, candidate, candidate.evaluate(py, (x, y), turn))?;
        profiled!(profile, contacts, self.contacts.validate_candidate(py, candidate, turn))?;
        let (wire, cross) = profiled!(profile, wire_cross,
            delta.inner.wire_cross(x, y, turn).map_err(PyValueError::new_err))?;
        let crossed = profiled!(profile, escape_cross,
            delta.inner.escape_cross(turn, self.settings.depth).map_err(PyValueError::new_err))?;
        let (vias, away, walled, ways, identities) = self.fields(py, candidate, delta, turn, inspect, profile)?;
        let layout = delta
            .layout
            .as_mut()
            .ok_or_else(|| PyValueError::new_err("prepared surface layout is not configured"))?;
        let (link, over, area, congestion) =
            profiled!(profile, layout, layout.terms(x, y, turn).map_err(PyValueError::new_err))?;
        Ok(((wire, cross, link, over, area, congestion), crossed, vias, away, walled, ways, identities))
    }

    fn check(&self, candidate: &PreparedCandidate, delta: &NativeDelta) -> PyResult<()> {
        if !Arc::ptr_eq(&self.identity, &candidate.identity) {
            return Err(PyValueError::new_err(
                "prepared surface candidate identity changed",
            ));
        }
        if !Arc::ptr_eq(&self.delta_identity, &delta.identity)
            || self.delta_revision != delta.revision
        {
            return Err(PyValueError::new_err(
                "prepared surface delta snapshot changed",
            ));
        }
        Ok(())
    }

    /// The escape search depth, for the signed escaped-crossing change.
    pub(crate) fn depth(&self) -> f64 {
        self.settings.depth
    }

    /// `evaluate`'s first checks and the candidate's geometry: the snapshot identities, the placed shapes and their
    /// validation. A staged caller runs it first, so a candidate it prunes is refused as `evaluate` refuses it.
    pub(crate) fn place_candidate(&self, py: Python<'_>, candidate: &mut PreparedCandidate,
        delta: &NativeDelta, x: f64, y: f64, turn: usize) -> PyResult<()> {
        self.check(candidate, delta)?;
        candidate.evaluate(py, (x, y), turn)?;
        self.contacts.validate_candidate(py, candidate, turn)
    }

    /// (vias, away, walled) of a candidate `place_candidate` has placed and whose wire and crossings `delta` has
    /// just solved (`wire_cross` at the same x, y and turn): the escape judgements of `evaluate`, without its wire,
    /// crossings or layout terms.
    pub(crate) fn escape_counts(&mut self, py: Python<'_>, candidate: &mut PreparedCandidate,
        delta: &mut NativeDelta, turn: usize) -> PyResult<(usize, usize, usize)> {
        let (vias, away, walled, _, _) = self.fields(py, candidate, delta, turn, false, &mut None)?;
        Ok((vias, away, walled))
    }

    #[allow(clippy::type_complexity)]
    fn fields(&mut self, py: Python<'_>, candidate: &mut PreparedCandidate, delta: &mut NativeDelta, turn: usize,
              inspect: bool, profile: &mut Option<Profile>)
              -> PyResult<(usize, usize, usize, Vec<(String, String, u8)>, Vec<(String, String)>)> {
        if self.rest_index.is_none() {
            let mut cells: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
            let mut bans = Vec::new();
            for i in 0..self.rest_roles.len() {
                let b = self.contacts.shape(candidate, turn, i).bounds;
                for x in RestIndex::bucket(b.0)..=RestIndex::bucket(b.2) {
                    for y in RestIndex::bucket(b.1)..=RestIndex::bucket(b.3) {
                        cells.entry((x, y)).or_default().push(i);
                    }
                }
                if self.rest_roles[i] & BAN != 0 {
                    bans.push(i);
                }
            }
            self.rest_index = Some(RestIndex { cells, bans });
        }
        let index = self.rest_index.take().unwrap();
        let result = self.fields_indexed(py, candidate, delta, turn, inspect, profile, &index);
        self.rest_index = Some(index);
        result
    }

    #[allow(clippy::type_complexity, clippy::too_many_arguments)]
    fn fields_indexed(&mut self, py: Python<'_>, candidate: &mut PreparedCandidate, delta: &mut NativeDelta,
                      turn: usize, inspect: bool, profile: &mut Option<Profile>, index: &RestIndex)
              -> PyResult<(usize, usize, usize, Vec<(String, String, u8)>, Vec<(String, String)>)> {
        let physical: Vec<_> = (0..candidate.turn(turn).shapes.len())
            .filter(|&i| self.moving_roles[turn][i] != 0)
            .map(|i| {
                let shape = self.contacts.shape(&candidate, turn, self.rest_roles.len() + i);
                shape.bounds
            }).collect();
        // A quiet net's pad takes no target (it is judged for walled only), so a candidate on its net changes its
        // verdict only by standing on or near it, which the region test sees: quiet nets are not touched.
        let touched: HashSet<String> = candidate.turn(turn).shapes.iter().enumerate()
            .filter(|(i, shape)| self.moving_roles[turn][*i] != 0 && !shape.net.is_empty()
                    && !self.nets.get(shape.net.as_str()).is_some_and(|n| n.quiet))
            .map(|(_, shape)| shape.net.clone()).collect();
        let reaches = |b: Bounds| physical.iter().any(|p| overlaps(b, *p));
        let mut reused = 0;
        let mut rejudged = 0;
        let mut reasons = (0, 0, 0, 0, 0);
        let mut vias = 0;
        let mut away = 0;
        let mut walls = HashSet::new();
        let mut handoffs = Vec::new();
        let mut ways = Vec::new();
        #[derive(Clone, Copy, PartialEq)]
        enum Mode { Reuse, Aim, Full }
        for fi in 0..self.fields.len() {
            py.check_signals()?;
            if self.fields[fi].pads.len() < self.settings.minimum {
                continue;
            }
            // The rest board was already lifted: only added physical geometry can alter a rest pad's contacts and
            // paths. A pad the candidate's geometry reaches is judged again in full. A pad on a net it touches
            // keeps its geometry but may aim elsewhere: its facts on the lifted board, gathered once, are judged
            // against the new aim. Any other pad keeps its cached verdict.
            let modes: Vec<Mode> = match &self.fields[fi].cached {
                Some(cached) => {
                    let field = &self.fields[fi];
                    let by_net = field.pads.iter().any(|pad| touched.contains(&pad.net));
                    let by_region = cached.iter().any(|pad| reaches(pad.region));
                    if by_region { reasons.2 += 1; } else if by_net { reasons.1 += 1; }
                    cached.iter().zip(&field.pads).enumerate().map(|(pi, (c, pad))| {
                        let facts = self.pad_facts.get(&(fi, pi, turn));
                        if reaches(c.region) || facts.is_some_and(|f| f.guard.iter().any(|g| reaches(*g))) {
                            Mode::Full
                        } else if touched.contains(&pad.net) {
                            Mode::Aim
                        } else {
                            Mode::Reuse
                        }
                    }).collect()
                }
                None => {
                    reasons.0 += 1;
                    vec![Mode::Full; self.fields[fi].pads.len()]
                }
            };
            if modes.iter().all(|m| *m == Mode::Reuse) {
                reused += 1;
            } else {
                rejudged += 1;
            }
            let lanes = if modes.iter().any(|m| *m != Mode::Reuse) {
                Some(self.lanes_of(py, candidate, turn, fi, profile)?)
            } else {
                None
            };
            for (pi, mode) in modes.iter().enumerate() {
                let (owner, number, net) = {
                    let pad = &self.fields[fi].pads[pi];
                    (self.fields[fi].owner.clone(), pad.number.clone(), pad.net.clone())
                };
                if *mode == Mode::Reuse {
                    if !self.nets.contains_key(&net) { continue; }
                    let c = &self.fields[fi].cached.as_ref().unwrap()[pi];
                    if c.way == 1 { vias += 1; }
                    else if c.way == 2 { away += 1; }
                    if c.wall { walls.insert((owner.clone(), number.clone())); }
                    if c.handoff { handoffs.push((owner.clone(), number.clone())); }
                    if inspect { ways.push((owner, number, c.way)); }
                    continue;
                }
                if !self.nets.contains_key(&net) { continue; }
                if *mode == Mode::Full { reasons.3 += 1; } else { reasons.4 += 1; }
                let lanes = lanes.as_ref().unwrap();
                let judged = if *mode == Mode::Aim {
                    let key = (fi, pi, turn);
                    let gathered = if self.pad_facts.get(&key).is_some_and(|f| f.valid) {
                        None
                    } else {
                        let judged = self.judge_pad(py, candidate, delta, turn, fi, pi, lanes, index, true, profile)?;
                        Some(judged.facts.unwrap())
                    };
                    let facts = gathered.as_ref().or_else(|| self.pad_facts.get(&key)).unwrap();
                    let mut way = 4;
                    if facts.eligible {
                        let aim_started = profile.as_ref().map(|_| std::time::Instant::now());
                        let aim = delta.inner.aim(turn, &net, &owner, &number, facts.centre)
                            .map_err(PyValueError::new_err)?;
                        if let (Some(timing), Some(started)) = (profile.as_mut(), aim_started) {
                            timing.aim += started.elapsed().as_secs_f64() * 1e6;
                        }
                        if let Some(d) = aim {
                            way = facts.surface.as_ref().unwrap().way(d);
                        }
                    }
                    let judged = Judged { way, wall: facts.wall, handoff: facts.handoff, facts: None };
                    // Facts gathered while candidate geometry reaches the guard boxes describe this candidate,
                    // not the lifted board: they answer it, and only their guard is kept.
                    if let Some(mut facts) = gathered {
                        facts.valid = !facts.guard.iter().any(|g| reaches(*g));
                        self.pad_facts.insert(key, facts);
                    }
                    judged
                } else {
                    self.judge_pad(py, candidate, delta, turn, fi, pi, lanes, index, false, profile)?
                };
                if judged.way == 1 {
                    vias += 1;
                } else if judged.way == 2 {
                    away += 1;
                } else if judged.way == 3 {
                    walls.insert((owner.clone(), number.clone()));
                }
                if judged.wall {
                    walls.insert((owner.clone(), number.clone()));
                }
                if judged.handoff {
                    handoffs.push((owner.clone(), number.clone()));
                }
                if inspect {
                    ways.push((owner, number, judged.way));
                }
            }
        }
        let mut identities = if inspect {
            walls
                .iter()
                .cloned()
                .chain(handoffs.iter().cloned())
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        identities.sort();
        self.cache_usage = (reused, rejudged);
        self.cache_reasons = reasons;
        Ok((vias, away, walls.len() + handoffs.len(), ways, identities))
    }

    /// A field's lanes, via spots and pad contact shapes for `turn`, made once per turn for a rest field.
    fn lanes_of(&mut self, py: Python<'_>, candidate: &PreparedCandidate, turn: usize, fi: usize,
                profile: &mut Option<Profile>) -> PyResult<Arc<FieldLanes>> {
        let rest = self.fields[fi].cached.is_some();
        if rest {
            if let Some(found) = self.field_lanes.get(&(fi, turn)) {
                return Ok(found.clone());
            }
        }
        let field = &self.fields[fi];
        let records_started = profile.as_ref().map(|_| std::time::Instant::now());
        let mut records = Vec::new();
        let mut mines = Vec::new();
        for pad in &field.pads {
            let mine = self.mine(candidate, turn, &field.owner, &pad.number);
            if mine.is_empty() {
                return Err(PyValueError::new_err("prepared surface pad missing"));
            }
            let mut layers = 0;
            let mut polys = Vec::new();
            let mut boxes = Vec::new();
            for &i in &mine {
                let s = self.contacts.shape(candidate, turn, i);
                if s.net != pad.net {
                    return Err(PyValueError::new_err("prepared surface pad intent changed"));
                }
                layers |= s.layers;
                polys.push(s.polygon.to_vec());
                boxes.push(s.bounds);
            }
            let net = self.nets.get(&pad.net);
            let eligible = net.is_some_and(|n| n.size >= 2) && !pad.unconnected;
            let (tr, vr, dr, clr) = if eligible {
                let n = net.unwrap();
                (
                    n.track_width / 2.0 + n.clearance,
                    n.diameter / 2.0,
                    n.drill / 2.0,
                    n.clearance,
                )
            } else {
                (0.0, 0.0, 0.0, 0.0)
            };
            let b = bounds_union(boxes.into_iter());
            records.push((pad.number.clone(), layers, b, Some(polys), eligible, tr, vr, dr, clr));
            mines.push((mine, b));
        }
        if let (Some(timing), Some(started)) = (profile.as_mut(), records_started) {
            timing.records += started.elapsed().as_secs_f64() * 1e6;
        }
        let (rotation, cos, sin) = field.turns[turn];
        let (lanes, spots) = profiled!(profile, lanes, surface::surface_lanes(
            py,
            records,
            rotation,
            (cos, sin),
            self.settings.reach,
            self.settings.minimum,
        ))?;
        let made = Arc::new(FieldLanes { lanes, spots, mines });
        if rest {
            self.field_lanes.insert((fi, turn), made.clone());
        }
        Ok(made)
    }

    /// One pad's full judgement on the candidate's board: its contacts, its way and its supplemental search. With
    /// `gather`, the way's search runs to the end and the pad's facts are returned with it; the way then comes from
    /// those facts.
    #[allow(clippy::too_many_arguments)]
    fn judge_pad(&mut self, py: Python<'_>, candidate: &PreparedCandidate, delta: &mut NativeDelta, turn: usize,
                 fi: usize, pi: usize, lanes: &FieldLanes, index: &RestIndex, gather: bool,
                 profile: &mut Option<Profile>) -> PyResult<Judged> {
        let (owner, number, net_name, unconnected) = {
            let pad = &self.fields[fi].pads[pi];
            (self.fields[fi].owner.clone(), pad.number.clone(), pad.net.clone(), pad.unconnected)
        };
        let (mine, b) = &lanes.mines[pi];
        let rest = self.fields[fi].cached.is_some();
        // A contact walk reads only shapes on the pad's net, and a shape it adds must overlap the box of the pad or
        // of a chain member: the candidate's shapes on that net clear of every such box leave the walk unchanged.
        let on_net: Vec<Bounds> = self.contacts.moving_on_net(candidate, turn, &net_name).iter()
            .map(|&i| self.contacts.shape(candidate, turn, i).bounds).collect();
        let reaches = |boxes: &[Bounds]| boxes.iter().any(|b| on_net.iter().any(|p| overlaps(*b, *p)));
        let kept = if rest {
            self.contact_cache.get(&(fi, pi)).filter(|(_, _, boxes)| !reaches(boxes))
                .map(|(facts, own, _)| (facts.clone(), own.clone()))
        } else {
            None
        };
        let (facts, own) = match kept {
            Some(kept) => kept,
            None => {
                let facts = profiled!(profile, contacts, self.contacts.inspect_validated(
                    py,
                    candidate,
                    turn,
                    &owner,
                    &number,
                    &net_name,
                ))?;
                let own = self.contacts.chain().to_vec();
                if rest {
                    let boxes: Vec<Bounds> = mine.iter().chain(&own)
                        .map(|&i| self.contacts.shape(candidate, turn, i).bounds).collect();
                    if !reaches(&boxes) {
                        self.contact_cache.insert((fi, pi), (facts.clone(), own.clone(), boxes));
                    }
                }
                (facts, own)
            }
        };
        let net = self.nets.get(&net_name).unwrap();
        let field = &self.fields[fi];
        let pad = &field.pads[pi];
        let judge_started = profile.as_ref().map(|_| std::time::Instant::now());
        let centre = ((b.0 + b.2) / 2.0, (b.1 + b.3) / 2.0);
        let mut guard: Vec<Bounds> = own.iter().map(|&i| self.contacts.shape(candidate, turn, i).bounds).collect();
        let mut way = 4;
        let eligible = net.size >= 2 && !unconnected && !facts.joined && !facts.on_pad;
        let mut gathered = None;
        if eligible {
            let aim_started = profile.as_ref().map(|_| std::time::Instant::now());
            let aim = if net.quiet || gather {
                None
            } else {
                delta
                    .inner
                    .aim(turn, &net_name, &owner, &number, centre)
                    .map_err(PyValueError::new_err)?
            };
            if let (Some(timing), Some(started)) = (profile.as_mut(), aim_started) {
                timing.aim += started.elapsed().as_secs_f64() * 1e6;
            }
            if net.quiet || aim.is_some() || gather {
                let blockers_started = profile.as_ref().map(|_| std::time::Instant::now());
                let pad_lanes: Vec<_> = lanes.lanes
                    .iter()
                    .filter(|l| l.0 == number)
                    .map(|l| l.1.clone())
                    .collect();
                let pad_spots: Vec<_> = lanes.spots
                    .iter()
                    .filter(|s| s.0 == number)
                    .map(|s| s.1.clone())
                    .collect();
                let region = bounds_union(
                    std::iter::once(*b)
                        .chain(pad_lanes.iter().map(|l| l.2))
                        .chain(pad_spots.iter().map(|s| s.2)),
                );
                let region = inflate(region, net.foe_reach);
                guard.push(inflate(region, self.settings.cell));
                if rest && !gather {
                    // A rest pad's own geometry and the rest of the board are fixed for the visit: their search is
                    // made once, and each candidate adds only its own shapes to it.
                    let key = (fi, pi, turn);
                    if !self.lifted.contains_key(&key) {
                        let (foes, bans) = self.blockers(candidate, turn, field, pad, net, region, index, Part::Rest);
                        let search = self.path(candidate, turn, field, pad, mine, &[], net, self.settings.reach, None,
                                               false, false, index, Part::Rest);
                        let lifted = profiled!(profile, judge, surface::lift_pad(
                            py, pad_lanes.clone(), pad_spots.clone(), foes, bans, centre, search.path,
                        ))?;
                        self.lifted.insert(key, lifted);
                    }
                    let field = &self.fields[fi];
                    let pad = &field.pads[pi];
                    let (foes, bans) = self.blockers(candidate, turn, field, pad, net, region, index, Part::Moving);
                    if let (Some(timing), Some(started)) = (profile.as_mut(), blockers_started) {
                        timing.blockers += started.elapsed().as_secs_f64() * 1e6;
                    }
                    let search = profiled!(profile, path_setup, self.path(candidate, turn, field, pad, mine, &[], net,
                        self.settings.reach, aim, false, false, index, Part::Moving));
                    guard.push(search.reach);
                    way = profiled!(profile, judge, self.lifted[&key].judge(
                        py, &foes, &bans, &search.path.1, &search.path.7, aim, net.quiet,
                    ))?;
                } else {
                let (foes, bans) = self.blockers(candidate, turn, field, pad, net, region, index, Part::All);
                if let (Some(timing), Some(started)) = (profile.as_mut(), blockers_started) {
                    timing.blockers += started.elapsed().as_secs_f64() * 1e6;
                }
                let search = profiled!(profile, path_setup, self.path(
                    candidate,
                    turn,
                    field,
                    pad,
                    mine,
                    &[],
                    net,
                    self.settings.reach,
                    aim,
                    false,
                    false,
                    index,
                    Part::All,
                ));
                guard.push(search.reach);
                if gather {
                    let found = profiled!(profile, judge, surface::surface_facts(
                        py, pad_lanes, pad_spots, foes, bans, centre, search.path,
                    ))?;
                    gathered = Some(found);
                } else {
                    way = profiled!(profile, judge, surface::surface_judge(
                        py, pad_lanes, pad_spots, foes, bans, aim, centre, net.quiet, search.path,
                    ))?;
                }
                }
            }
        }
        if let (Some(timing), Some(started)) = (profile.as_mut(), judge_started) {
            timing.classification += started.elapsed().as_secs_f64() * 1e6;
        }
        let supplemental_started = profile.as_ref().map(|_| std::time::Instant::now());
        let declared = net.size >= 2
            && !own.is_empty()
            && !facts.through
            && facts.declared
            && !facts.runs_on;
        let handoff = net.size < 2 && !unconnected && !facts.through;
        let mut wall = false;
        let mut unanswered = false;
        if declared || handoff {
            let search = self.path(
                candidate,
                turn,
                field,
                pad,
                mine,
                &own,
                net,
                self.settings.depth,
                None,
                true,
                self.settings.lane_via_exit,
                index,
                Part::All,
            );
            guard.push(search.reach);
            let path = search.path;
            let coarse = if handoff && own.is_empty() {
                surface::surface_box_path_out(
                    py,
                    path.0.clone(),
                    search.copper,
                    search.holes,
                    path.2,
                    path.3,
                    path.4,
                    path.5,
                    None,
                    path.7.clone(),
                    path.8,
                )?
            } else {
                false
            };
            if !coarse
                && !surface::surface_path_out(
                    py, path.0, path.1, path.2, path.3, path.4, path.5, None, path.7,
                    path.8, path.9, path.10,
                )?
            {
                if handoff {
                    unanswered = true;
                } else {
                    wall = true;
                }
            }
        }
        if let (Some(timing), Some(started)) = (profile.as_mut(), supplemental_started) {
            timing.supplemental += started.elapsed().as_secs_f64() * 1e6;
        }
        let facts = gather.then(|| PadFacts {
            valid: false,
            eligible: eligible && !net.quiet,
            centre,
            surface: gathered,
            wall,
            handoff: unanswered,
            guard,
        });
        Ok(Judged { way, wall, handoff: unanswered, facts })
    }
}
