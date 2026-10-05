//! The pin map study's core (`placemat.pinmap_core`; its Python twin is `placemat.pinmap_twin`, which this mirrors line
//! for line so the two give the same answers). It takes a study as plain arrays and, for the parts of one group and each
//! combination of their poses, returns the best assignment of the movable nets to pins with its tallies.
//!
//! - Score: weighted crossings of the studied nets' airwires against the board's other airwires (on a 2 mm grid) and
//!   among themselves, plus `length` times their length in mm, plus `bend` times their summed bend in degrees, plus the
//!   controlled impedances' extra length, plus `group` times the soft groups' spread. A net's airwires are the minimum
//!   spanning tree of its pads (`ratsnest::mst`), each studied pin at its exit point and each airwire to one taken
//!   round the body (pinmap_geom.rs).
//! - A studied net in a controlled impedance's class (`controlled`, a differential pair's half too) counts its length
//!   `impedance` times over.
//! - Frames: a part standing off the axes keeps its own frame (`frames`): its present pose is turned by it.
//! - Cohesion: per soft group, the sum over its neighbouring members (in its written order) of how far their pins'
//!   anchors stand apart beyond the pin pitch times the slots between them; an intact group in order spreads 0.
//! - Background: the board's other airwires. Those of a net with a pad on a studied part (a plane's, on the part's
//!   ground pins) are not fixed: `posed` carries such a net's pads, and at each pose its tree is worked out again with
//!   the part's pads turned with it, after the fixed wires in the order a segment meets its candidates.
//! - Incremental: a net's airwires, its crossings with the background and with each other net are kept per placing of
//!   its ends, so a move recounts only the nets it touches.
//! - Search: a first map (each hard group, then each soft group, on the cheapest run of pins that leaves the rest a
//!   matching, then a minimum-cost matching), then per seed `moves` moves, swaps and group moves (a soft group's too)
//!   under annealing from `t0` down to `t1`. The random stream is SplitMix64, the twin's. At the present pose the
//!   present map is a candidate too, when every net of it stands on a pin it may take.
//! - Budget: the search stops when it has taken `budget_steps` steps, a step being one move of a local search (tried
//!   whether or not a legal change came of it, and whether or not it was taken), checked before each move and before
//!   each pose. It never reads the time, so where it stops is the same on any machine and on either core.
//! - Guard: a safety net on the time, `guard_ms` (0 is off), read every 32 moves and before each pose. Past it the
//!   study gives no map (`slow`): a map cut short by the time would differ from run to run.

use crate::exact::hypot;
use crate::pinmap_geom::{bend, exit_of, length, route, End, Exit, Pose};
use crate::ratsnest::{cross_nm, mst, nm};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::rc::Rc;
use std::time::Instant;

pub const CELL_NM: i64 = 2_000_000; // pinmap_twin.CELL_NM
const SPREAD_SLACK_MM: f64 = 1e-3; // pinmap_twin.SPREAD_SLACK_MM
const PAIR: u8 = 1;
const IMPEDANCE: u8 = 2;
const PLANE: u8 = 3;

/// (ax, ay, bx, by, minx, miny, maxx, maxy) in whole nanometres.
pub type Seg = [i64; 8];
/// (total, against, among, weighted, length, bend, controlled impedances' length, spread, cohesion).
pub type Tallies = (f64, i64, i64, f64, f64, f64, f64, f64, f64);
pub type Paths = Vec<(usize, Vec<Vec<(f64, f64)>>)>;

/// A part (ref, cx, cy, hw, hh), or a pin (number, x, y, nx, ny).
pub type Row = (String, f64, f64, f64, f64);

/// A background net with a pad on a studied part (`Problem::posed`).
pub type Posed = (u8, Vec<(f64, f64, String, String, i64, i64)>, Vec<(usize, usize)>);
/// A soft group (`Problem::soft`): its part, the part's pin pitch, its members (slot in the group, movable or -1, pin
/// or -1), and the windows the first map may start it on (a pin per slot).
pub type Soft = (usize, f64, Vec<(usize, i64, i64)>, Vec<Vec<usize>>);

/// A study as `pinmap_core.Problem` holds it.
pub struct Problem {
    pub parts: Vec<Row>,
    pub pins: Vec<Vec<Row>>,
    pub nets: Vec<(String, u8)>,
    pub fixed: Vec<Vec<(f64, f64, String, String)>>,
    pub joined: Vec<Vec<(usize, usize)>>,
    pub ends: Vec<Vec<(usize, usize)>>,
    pub wires: Vec<(u8, i64, i64, i64, i64)>,
    /// Per background net with a pad on a studied part: its kind, its pads (x, y, ref, number, part or -1, pin or -1)
    /// as they stand, and the pairs of them that touch.
    pub posed: Vec<Posed>,
    pub movable: Vec<(usize, usize, Vec<usize>, i64)>,
    pub groups: Vec<(usize, Vec<i64>, Vec<Vec<usize>>)>,
    /// The soft groups: a movable member's pin is where the assignment puts it, a held one's is its own.
    pub soft: Vec<Soft>,
    pub margin: f64,
    /// Per part, its frame's turn from the board's (a part standing off the axes keeps its own); empty for none.
    pub frames: Vec<f64>,
    /// Per net, whether it is a controlled impedance's; empty for none.
    pub controlled: Vec<bool>,
}

/// (pair, impedance, plane, length, bend, group) weights and the search's own figures.
pub struct Params {
    pub w: [f64; 6],
    pub seeds: u32,
    pub moves: u32,
    pub t0: f64,
    pub t1: f64,
    pub budget_steps: u64,
    pub guard_ms: f64,
    pub seed_key: u64,
}

pub struct SplitMix64 {
    state: u64,
}

impl SplitMix64 {
    pub fn new(seed: u64) -> SplitMix64 {
        SplitMix64 { state: seed }
    }

    pub fn next(&mut self) -> u64 {
        self.state = self.state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.state;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }

    fn unit(&mut self) -> f64 {
        (self.next() >> 11) as f64 * (1.0 / (1u64 << 53) as f64)
    }
}

pub fn stream_seed(seed_key: u64, combo: usize, seed: usize) -> u64 {
    seed_key ^ ((combo as u64) << 32) ^ (seed as u64)
}

/// `pinmap_twin.Clock`: the search's budget in steps (one step: one move of a local search) and its wall-clock guard
/// in ms (0 is off).
struct Clock {
    budget: u64,
    guard: f64,
    steps: u64,
    start: Instant,
}

impl Clock {
    /// Whether a step is left: if so it is taken.
    fn take(&mut self) -> bool {
        if self.steps >= self.budget {
            return false;
        }
        self.steps += 1;
        true
    }

    fn spent(&self) -> bool {
        self.steps >= self.budget
    }

    /// Whether the guard is on and the time is past it.
    fn slow(&self) -> bool {
        self.guard > 0.0 && self.start.elapsed().as_secs_f64() * 1000.0 >= self.guard
    }
}

/// Why a local search stopped before its last move.
#[derive(PartialEq)]
enum Stop {
    Budget,
    Slow,
}

fn one(w: &[f64; 6], k: u8) -> f64 {
    match k {
        PAIR => w[0],
        IMPEDANCE => w[1],
        _ => 1.0,
    }
}

/// What a crossing of classes `a` and `b` counts.
pub fn crossing(w: &[f64; 6], a: u8, b: u8) -> f64 {
    if a == PLANE || b == PLANE {
        return w[2];
    }
    let (x, y) = (one(w, a), one(w, b));
    if x >= y { x } else { y }
}

fn segments(paths: &[Vec<(f64, f64)>]) -> Vec<Seg> {
    let mut out = Vec::new();
    for path in paths {
        for p in path.windows(2) {
            let (ax, ay, bx, by) = (nm(p[0].0), nm(p[0].1), nm(p[1].0), nm(p[1].1));
            out.push([ax, ay, bx, by, ax.min(bx), ay.min(by), ax.max(bx), ay.max(by)]);
        }
    }
    out
}

/// The grid cells segment `s` passes through, column by column (a cell is [k, k + 1) * CELL_NM each way): in each
/// column the cells between the segment's lowest and highest y over the column, rounded outward to the nanometre. Two
/// segments that cross share the cell their crossing point is in, so the grid meets every crossing the whole-box scan
/// met, and a segment's candidates, deduplicated in wire order, give the same sums.
fn cells(s: &Seg) -> Vec<(i64, i64)> {
    let ((ax, ay), (bx, by)) = if s[0] <= s[2] { ((s[0], s[1]), (s[2], s[3])) } else { ((s[2], s[3]), (s[0], s[1])) };
    let mut out = Vec::new();
    for cx in ax.div_euclid(CELL_NM)..=bx.div_euclid(CELL_NM) {
        let (lo, hi) = if ax == bx {
            (s[5], s[7])
        } else {
            let (x0, x1) = (ax.max(cx * CELL_NM), bx.min((cx + 1) * CELL_NM));
            let den = (bx - ax) as i128;
            let at = |x: i64| -> (i64, i64) {
                let num = (by - ay) as i128 * (x - ax) as i128;
                (ay + num.div_euclid(den) as i64, ay - (-num).div_euclid(den) as i64)
            };
            let ((f0, c0), (f1, c1)) = (at(x0), at(x1));
            (f0.min(f1), c0.max(c1))
        };
        for cy in lo.div_euclid(CELL_NM)..=hi.div_euclid(CELL_NM) {
            out.push((cx, cy));
        }
    }
    out
}

struct Background {
    w: [f64; 6],
    kinds: Vec<u8>,
    segs: Vec<Seg>,
    grid: HashMap<(i64, i64), Vec<usize>>,
}

impl Background {
    fn new(wires: &[(u8, i64, i64, i64, i64)], w: [f64; 6]) -> Background {
        let kept: Vec<&(u8, i64, i64, i64, i64)> = wires.iter().filter(|x| !(x.0 == PLANE && w[2] <= 0.0)).collect();
        let segs: Vec<Seg> = kept.iter().map(|x| [x.1, x.2, x.3, x.4, x.1.min(x.3), x.2.min(x.4), x.1.max(x.3), x.2.max(x.4)]).collect();
        let mut grid: HashMap<(i64, i64), Vec<usize>> = HashMap::new();
        for (k, s) in segs.iter().enumerate() {
            for c in cells(s) {
                grid.entry(c).or_default().push(k);
            }
        }
        Background { w, kinds: kept.iter().map(|x| x.0).collect(), segs, grid }
    }

    /// Crossings of `segs` (class `kind`) with the fixed wires and then `extra`, the posed nets' wires at this pose.
    fn cross(&self, kind: u8, segs: &[Seg], extra: &[(u8, Seg)]) -> (f64, i64) {
        let (mut total, mut count) = (0.0, 0i64);
        for s in segs {
            let mut near: BTreeSet<usize> = BTreeSet::new();
            for c in cells(s) {
                if let Some(v) = self.grid.get(&c) {
                    near.extend(v.iter().copied());
                }
            }
            for k in near {
                let t = &self.segs[k];
                if t[6] < s[4] || s[6] < t[4] || t[7] < s[5] || s[7] < t[5] {
                    continue;
                }
                if cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]) {
                    total += crossing(&self.w, kind, self.kinds[k]);
                    count += 1;
                }
            }
            for (k2, t) in extra {
                if t[6] < s[4] || s[6] < t[4] || t[7] < s[5] || s[7] < t[5] {
                    continue;
                }
                if cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]) {
                    total += crossing(&self.w, kind, *k2);
                    count += 1;
                }
            }
        }
        (total, count)
    }
}

/// What `mm` of a controlled impedance's airwire adds to the plain length term (`pinmap_twin.impedance_extra`).
fn impedance_extra(w: &[f64; 6], mm: f64) -> f64 {
    w[3] * (w[1] - 1.0) * mm
}

fn frame(pb: &Problem, part: usize) -> f64 {
    if pb.frames.is_empty() { 0.0 } else { pb.frames[part] }
}

/// Whether `pose` is the part's present one (`pinmap_twin._present`).
fn present(pb: &Problem, part: usize, pose: &Pose) -> bool {
    pose.turn == frame(pb, part) && !pose.flip
}

/// Part `part` turned `turn` degrees from where it stands, flipped first when `flip` (`pinmap_twin.pose_at`).
fn pose_at(pb: &Problem, part: usize, turn: f64, flip: bool) -> Pose {
    let f = frame(pb, part);
    Pose::new(pb.parts[part].1, pb.parts[part].2, if flip { turn - f } else { f + turn }, flip)
}

/// Soft group `g`'s spread with each movable member on `pin_of(movable)` and each held one on its pin
/// (`pinmap_twin.spread_at`, a gap counted as `pinmap_twin.spread` counts it); with `held_only`, only the gaps beside
/// a held member count.
fn spread_at(pb: &Problem, g: usize, pin_of: impl Fn(usize) -> usize, held_only: bool) -> f64 {
    let (part, pitch, members, _) = &pb.soft[g];
    let mut out = 0.0;
    let mut prev: Option<(usize, f64, f64, i64)> = None;
    for &(slot, mv, pin) in members {
        let row = &pb.pins[*part][if mv >= 0 { pin_of(mv as usize) } else { pin as usize }];
        if let Some((ps, px, py, pm)) = prev
            && (!held_only || mv < 0 || pm < 0)
        {
            let d = hypot(row.1 - px, row.2 - py) - (slot - ps) as f64 * pitch;
            if d > SPREAD_SLACK_MM {
                out += d;
            }
        }
        prev = Some((slot, row.1, row.2, mv));
    }
    out
}

/// The posed nets' airwires at `poses` (one per part): each net's tree over its pads, a pad of a part at a pose other
/// than its present one turned with the part about its centre, the rest where they stand. A plane's are left out when
/// its crossings weigh nothing, as the fixed wires' are.
pub fn posed_wires(pb: &Problem, poses: &[Pose], w: &[f64; 6]) -> Vec<(u8, Seg)> {
    let mut out = Vec::new();
    for (kind, pads, joined) in &pb.posed {
        if *kind == PLANE && w[2] <= 0.0 {
            continue;
        }
        let at: Vec<(f64, f64, String, String)> = pads.iter().map(|a| {
            let (x, y) = if a.4 >= 0 {
                let pose = poses[a.4 as usize];
                if present(pb, a.4 as usize, &pose) {
                    (a.0, a.1)
                } else {
                    let pin = &pb.pins[a.4 as usize][a.5 as usize];
                    pose.to_board(pin.1, pin.2)
                }
            } else {
                (a.0, a.1)
            };
            (x, y, a.2.clone(), a.3.clone())
        }).collect();
        for (i, j) in mst(&at, joined) {
            let (ax, ay, bx, by) = (nm(at[i].0), nm(at[i].1), nm(at[j].0), nm(at[j].1));
            out.push((*kind, [ax, ay, bx, by, ax.min(bx), ay.min(by), ax.max(bx), ay.max(by)]));
        }
    }
    out
}

pub fn segments_crossing(a: &[Seg], b: &[Seg]) -> i64 {
    let mut n = 0;
    for s in a {
        for t in b {
            if s[6] < t[4] || t[6] < s[4] || s[7] < t[5] || t[7] < s[5] {
                continue;
            }
            if cross_nm(s[0], s[1], s[2], s[3], t[0], t[1], t[2], t[3]) {
                n += 1;
            }
        }
    }
    n
}

struct NetWires {
    paths: Vec<Vec<(f64, f64)>>,
    length: f64,
    bend: f64,
    segs: Vec<Seg>,
    bbox: [i64; 4],
}

type Pins = Vec<usize>;

struct Scorer<'a> {
    pb: &'a Problem,
    poses: Vec<Pose>,
    w: [f64; 6],
    bg: &'a Background,
    extra: Vec<(u8, Seg)>,
    /// Per net, whether it has an end on a part of the group: only such nets' own terms, and pairs with one of them,
    /// count in the group's total.
    mine: Vec<bool>,
    /// Per net, whether it is a controlled impedance's: its length counts `impedance` times over.
    controlled: Vec<bool>,
    /// The soft groups on the group's parts, and per net the ones it is a movable member of.
    soft: Vec<usize>,
    soft_of: HashMap<usize, Vec<usize>>,
    exits: HashMap<(usize, usize), Exit>,
    wires: HashMap<(usize, Pins), Rc<NetWires>>,
    single: HashMap<(usize, Pins), (f64, f64, i64)>,
    pair: HashMap<(usize, Pins, usize, Pins), (f64, i64)>,
}

impl<'a> Scorer<'a> {
    fn new(pb: &'a Problem, poses: Vec<Pose>, w: [f64; 6], bg: &'a Background, group_parts: &[usize]) -> Scorer<'a> {
        let extra = posed_wires(pb, &poses, &w);
        let mine = pb.ends.iter().map(|e| e.iter().any(|x| group_parts.contains(&x.0))).collect();
        let controlled = if pb.controlled.is_empty() { vec![false; pb.ends.len()] } else { pb.controlled.clone() };
        let soft: Vec<usize> = (0..pb.soft.len()).filter(|&g| group_parts.contains(&pb.soft[g].0)).collect();
        let mut soft_of: HashMap<usize, Vec<usize>> = HashMap::new();
        for &g in &soft {
            for &(_, mv, _) in &pb.soft[g].2 {
                if mv >= 0 {
                    soft_of.entry(pb.movable[mv as usize].0).or_default().push(g);
                }
            }
        }
        Scorer { pb, poses, w, bg, extra, mine, controlled, soft, soft_of, exits: HashMap::new(),
                 wires: HashMap::new(), single: HashMap::new(), pair: HashMap::new() }
    }

    fn exit(&mut self, part: usize, pin: usize) -> Exit {
        if let Some(e) = self.exits.get(&(part, pin)) {
            return *e;
        }
        let (_, _, _, hw, hh) = self.pb.parts[part];
        let (_, x, y, nx, ny) = self.pb.pins[part][pin];
        let e = exit_of(self.poses[part], x, y, (nx, ny), hw, hh, self.pb.margin);
        self.exits.insert((part, pin), e);
        e
    }

    fn wires(&mut self, net: usize, pins: &Pins) -> Rc<NetWires> {
        if let Some(hit) = self.wires.get(&(net, pins.clone())) {
            return hit.clone();
        }
        let pb = self.pb;
        let fixed = &pb.fixed[net];
        let mut anchors: Vec<(f64, f64, String, String)> = fixed.clone();
        let mut exits = Vec::new();
        for (slot, &pin) in pins.iter().enumerate() {
            let part = pb.ends[net][slot].0;
            let e = self.exit(part, pin);
            exits.push(e);
            anchors.push((e.at.0, e.at.1, pb.parts[part].0.clone(), pb.pins[part][pin].0.clone()));
        }
        let first = fixed.len();
        let end_of = |i: usize| if i >= first { End::Exit(exits[i - first]) } else { End::Point((anchors[i].0, anchors[i].1)) };
        let mut paths = Vec::new();
        let mut bends: BTreeMap<usize, f64> = BTreeMap::new();
        for (i, j) in mst(&anchors, &pb.joined[net]) {
            paths.push(route(&end_of(i), &end_of(j)));
            for (me, other) in [(i, j), (j, i)] {
                if me >= first {
                    let e = exits[me - first];
                    let d = bend(e.normal, e.at, (anchors[other].0, anchors[other].1));
                    let v = bends.entry(me).or_insert(d);
                    if d < *v {
                        *v = d;
                    }
                }
            }
        }
        let mut ln = 0.0;
        for p in &paths {
            ln += length(p);
        }
        let mut bd = 0.0;
        for v in bends.values() {
            bd += *v;
        }
        let segs = segments(&paths);
        let bbox = if segs.is_empty() {
            [0, 0, 0, 0]
        } else {
            [segs.iter().map(|s| s[4]).min().unwrap(), segs.iter().map(|s| s[5]).min().unwrap(),
             segs.iter().map(|s| s[6]).max().unwrap(), segs.iter().map(|s| s[7]).max().unwrap()]
        };
        let hit = Rc::new(NetWires { paths, length: ln, bend: bd, segs, bbox });
        self.wires.insert((net, pins.clone()), hit.clone());
        hit
    }

    fn single(&mut self, net: usize, pins: &Pins) -> (f64, f64, i64) {
        if let Some(hit) = self.single.get(&(net, pins.clone())) {
            return *hit;
        }
        let nw = self.wires(net, pins);
        let (weighted, count) = self.bg.cross(self.pb.nets[net].1, &nw.segs, &self.extra);
        let mut term = weighted + self.w[3] * nw.length + self.w[4] * nw.bend;
        if self.controlled[net] {
            term += impedance_extra(&self.w, nw.length);
        }
        let hit = (term, weighted, count);
        self.single.insert((net, pins.clone()), hit);
        hit
    }

    fn pair(&mut self, a: usize, ea: &Pins, b: usize, eb: &Pins) -> (f64, i64) {
        let (a, ea, b, eb) = if b < a { (b, eb, a, ea) } else { (a, ea, b, eb) };
        let key = (a, ea.clone(), b, eb.clone());
        if let Some(hit) = self.pair.get(&key) {
            return *hit;
        }
        let (wa, wb) = (self.wires(a, ea), self.wires(b, eb));
        let (ba, bb) = (wa.bbox, wb.bbox);
        let hit = if ba[2] < bb[0] || bb[2] < ba[0] || ba[3] < bb[1] || bb[3] < ba[1] {
            (0.0, 0)
        } else {
            let n = segments_crossing(&wa.segs, &wb.segs);
            (n as f64 * crossing(&self.w, self.pb.nets[a].1, self.pb.nets[b].1), n)
        };
        self.pair.insert(key, hit);
        hit
    }

    /// Soft group `g`'s spread with its movables where `assign` puts them, but the nets in `changes` where it puts them
    /// (`pinmap_twin.Scorer.spread`).
    fn spread(&self, g: usize, assign: &[Pins], changes: Option<&BTreeMap<usize, Pins>>) -> f64 {
        let pb = self.pb;
        spread_at(pb, g, |mv| {
            let m = &pb.movable[mv];
            match changes.and_then(|c| c.get(&m.0)) {
                Some(pins) => pins[m.1],
                None => assign[m.0][m.1],
            }
        }, false)
    }

    fn total(&mut self, assign: &[Pins]) -> Tallies {
        let (mut weighted, mut against, mut among, mut ln, mut bd) = (0.0, 0i64, 0i64, 0.0, 0.0);
        let (mut im, mut xi) = (0.0, 0.0);
        for (n, pins) in assign.iter().enumerate() {
            if !self.mine[n] {
                continue;
            }
            let (_, w, c) = self.single(n, pins);
            let nw = self.wires(n, pins);
            weighted += w;
            against += c;
            ln += nw.length;
            bd += nw.bend;
            if self.controlled[n] {
                im += nw.length;
                xi += impedance_extra(&self.w, nw.length);
            }
        }
        for a in 0..assign.len() {
            for b in a + 1..assign.len() {
                if !self.mine[a] && !self.mine[b] {
                    continue;
                }
                let (w, c) = self.pair(a, &assign[a], b, &assign[b]);
                weighted += w;
                among += c;
            }
        }
        let mut sp = 0.0;
        for &g in &self.soft {
            sp += self.spread(g, assign, None);
        }
        let co = self.w[5] * sp;
        (weighted + self.w[3] * ln + self.w[4] * bd + xi + co, against, among, weighted, ln, bd, im, sp, co)
    }

    fn paths(&mut self, assign: &[Pins]) -> Paths {
        let mut out = Vec::new();
        for (n, pins) in assign.iter().enumerate() {
            if self.mine[n] {
                out.push((n, self.wires(n, pins).paths.clone()));
            }
        }
        out
    }
}

struct Tally {
    assign: Vec<Pins>,
    value: f64,
}

impl Tally {
    fn new(sc: &mut Scorer, assign: &[Pins]) -> Tally {
        let value = sc.total(assign).0;
        Tally { assign: assign.to_vec(), value }
    }

    /// The change in the total when the nets in `changes` take those pins. A move only touches nets with an end on
    /// the group, so every pair it changes counts.
    fn delta(&self, sc: &mut Scorer, changes: &BTreeMap<usize, Pins>) -> f64 {
        let now = &self.assign;
        let moved: Vec<usize> = changes.keys().copied().collect();
        let mut d = 0.0;
        for &n in &moved {
            d += sc.single(n, &changes[&n]).0 - sc.single(n, &now[n]).0;
        }
        for &n in &moved {
            for m in 0..now.len() {
                if changes.contains_key(&m) {
                    continue;
                }
                d += sc.pair(n, &changes[&n], m, &now[m]).0 - sc.pair(n, &now[n], m, &now[m]).0;
            }
        }
        for (i, &n) in moved.iter().enumerate() {
            for &m in &moved[i + 1..] {
                d += sc.pair(n, &changes[&n], m, &changes[&m]).0 - sc.pair(n, &now[n], m, &now[m]).0;
            }
        }
        let touched: BTreeSet<usize> = moved.iter().filter_map(|n| sc.soft_of.get(n)).flatten().copied().collect();
        for g in touched {
            d += sc.w[5] * sc.spread(g, now, Some(changes)) - sc.w[5] * sc.spread(g, now, None);
        }
        d
    }

    fn apply(&mut self, changes: &BTreeMap<usize, Pins>, d: f64) {
        for (n, pins) in changes {
            self.assign[*n] = pins.clone();
        }
        self.value += d;
    }
}

/// `pinmap_twin.hungarian`: each row's column, or None when every assignment meets an infinite cost.
pub fn hungarian(cost: &[Vec<f64>]) -> Option<Vec<usize>> {
    let n = cost.len();
    if n == 0 {
        return Some(Vec::new());
    }
    let m = cost[0].len();
    let a: Vec<Vec<f64>> = cost.iter().map(|row| row.iter().map(|&c| if c < 1e12 { c } else { 1e12 }).collect()).collect();
    let (mut u, mut v) = (vec![0.0f64; n + 1], vec![0.0f64; m + 1]);
    let (mut p, mut way) = (vec![0usize; m + 1], vec![0usize; m + 1]);
    for i in 1..=n {
        p[0] = i;
        let mut j0 = 0usize;
        let mut minv = vec![f64::INFINITY; m + 1];
        let mut used = vec![false; m + 1];
        loop {
            used[j0] = true;
            let (i0, mut delta, mut j1) = (p[j0], f64::INFINITY, 0usize);
            for j in 1..=m {
                if !used[j] {
                    let cur = a[i0 - 1][j - 1] - u[i0] - v[j];
                    if cur < minv[j] {
                        minv[j] = cur;
                        way[j] = j0;
                    }
                    if minv[j] < delta {
                        delta = minv[j];
                        j1 = j;
                    }
                }
            }
            for j in 0..=m {
                if used[j] {
                    u[p[j]] += delta;
                    v[j] -= delta;
                } else {
                    minv[j] -= delta;
                }
            }
            j0 = j1;
            if p[j0] == 0 {
                break;
            }
        }
        loop {
            let j1 = way[j0];
            p[j0] = p[j1];
            j0 = j1;
            if j0 == 0 {
                break;
            }
        }
    }
    let mut out = vec![0usize; n];
    for j in 1..=m {
        if p[j] != 0 {
            out[p[j] - 1] = j - 1;
        }
    }
    for i in 0..n {
        if cost[i][out[i]] == f64::INFINITY {
            return None;
        }
    }
    Some(out)
}

fn with(assign: &[Pins], net: usize, slot: usize, pin: usize) -> Pins {
    let mut pins = assign[net].clone();
    pins[slot] = pin;
    pins
}

fn part_of(pb: &Problem, mv: usize) -> usize {
    pb.ends[pb.movable[mv].0][pb.movable[mv].1].0
}

fn target_cost(sc: &mut Scorer, mv: usize, pin: usize, assign: &[Pins]) -> f64 {
    let pb = sc.pb;
    let (net, slot) = (pb.movable[mv].0, pb.movable[mv].1);
    let e = sc.exit(part_of(pb, mv), pin);
    let mut pts: Vec<(f64, f64)> = pb.fixed[net].iter().map(|a| (a.0, a.1)).collect();
    if pts.is_empty() {
        for (k, &q) in assign[net].iter().enumerate() {
            if k != slot {
                pts.push(sc.exit(pb.ends[net][k].0, q).at);
            }
        }
    }
    let mut best: Option<f64> = None;
    for (x, y) in pts {
        let d = hypot(e.at.0 - x, e.at.1 - y);
        if best.is_none() || d < best.unwrap() {
            best = Some(d);
        }
    }
    best.unwrap_or(0.0)
}

fn matching(sc: &mut Scorer, singles: &[usize], used: &BTreeSet<usize>, assign: &[Pins]) -> (Vec<usize>, Option<Vec<usize>>) {
    let pb = sc.pb;
    let pins: Vec<usize> = singles.iter().flat_map(|&k| pb.movable[k].2.iter().copied()).collect::<BTreeSet<usize>>()
        .difference(used).copied().collect();
    if pins.len() < singles.len() {
        return (pins, None);
    }
    let mut cost = Vec::new();
    for &k in singles {
        let mut row = Vec::new();
        for &q in &pins {
            row.push(if pb.movable[k].2.contains(&q) { target_cost(sc, k, q, assign) } else { f64::INFINITY });
        }
        cost.push(row);
    }
    let got = hungarian(&cost);
    (pins, got)
}

/// Whether every movable of `assign` stands on a pin it may take (`pinmap_twin.legal`).
fn legal(pb: &Problem, assign: &[Pins]) -> bool {
    pb.movable.iter().all(|mv| mv.2.contains(&assign[mv.0][mv.1]))
}

/// `pinmap_twin.first_map`: a hard group no window of which fits stays where it stands only when its nets may take
/// those pins; else no map is legal, and its first barred net is the problem.
fn first_map(sc: &mut Scorer, group_parts: &[usize], start: &[Pins]) -> (Vec<Pins>, Vec<(usize, usize)>) {
    let pb = sc.pb;
    let mut assign = start.to_vec();
    let mut problems = Vec::new();
    'parts: for &part in group_parts {
        let singles: Vec<usize> = (0..pb.movable.len()).filter(|&k| part_of(pb, k) == part && pb.movable[k].3 < 0).collect();
        let mut used: BTreeSet<usize> = BTreeSet::new();
        let mut changes: BTreeMap<usize, usize> = BTreeMap::new();
        for (gpart, members, windows) in &pb.groups {
            if *gpart != part {
                continue;
            }
            let mut ranked: Vec<(f64, usize)> = Vec::new();
            for (wi, win) in windows.iter().enumerate() {
                if win.iter().any(|q| used.contains(q)) {
                    continue;
                }
                let mut c = 0.0;
                for (m, &q) in members.iter().zip(win.iter()) {
                    if *m >= 0 {
                        c += target_cost(sc, *m as usize, q, &assign);
                    }
                }
                ranked.push((c, wi));
            }
            ranked.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
            let mut chosen: Option<&Vec<usize>> = None;
            for (_, wi) in &ranked {
                let mut trial = used.clone();
                trial.extend(windows[*wi].iter().copied());
                if matching(sc, &singles, &trial, &assign).1.is_some() {
                    chosen = Some(&windows[*wi]);
                    break;
                }
            }
            match chosen {
                None => {
                    let barred = members.iter().filter(|m| **m >= 0).map(|m| &pb.movable[*m as usize])
                        .find(|mv| !mv.2.contains(&assign[mv.0][mv.1]));
                    if let Some(mv) = barred {
                        problems.push((part, mv.0));
                        continue 'parts;
                    }
                    for m in members.iter().filter(|m| **m >= 0) {
                        let mv = &pb.movable[*m as usize];
                        used.insert(assign[mv.0][mv.1]);
                    }
                }
                Some(win) => {
                    used.extend(win.iter().copied());
                    for (m, &q) in members.iter().zip(win.iter()) {
                        if *m >= 0 {
                            changes.insert(*m as usize, q);
                        }
                    }
                }
            }
        }
        let mut placed: BTreeSet<usize> = BTreeSet::new();
        for (g, (gpart, _, members, windows)) in pb.soft.iter().enumerate() {
            if *gpart != part {
                continue;
            }
            let mine: Vec<(usize, usize)> = members.iter().filter(|m| m.1 >= 0 && !placed.contains(&(m.1 as usize)))
                .map(|m| (m.0, m.1 as usize)).collect();
            let rest: Vec<usize> = singles.iter().copied()
                .filter(|k| !placed.contains(k) && !mine.iter().any(|&(_, mv)| mv == *k)).collect();
            let mut ranked: Vec<(f64, usize)> = Vec::new();
            for (wi, win) in windows.iter().enumerate() {
                if mine.iter().any(|&(slot, _)| used.contains(&win[slot])) {
                    continue;
                }
                let mut c = 0.0;
                for &(slot, mv) in &mine {
                    c += target_cost(sc, mv, win[slot], &assign);
                }
                c += sc.w[5] * spread_at(pb, g, |mv| match mine.iter().find(|m| m.1 == mv) {
                    Some(&(slot, _)) => win[slot],
                    None => assign[pb.movable[mv].0][pb.movable[mv].1],
                }, true);
                ranked.push((c, wi));
            }
            ranked.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
            for (_, wi) in &ranked {
                let mut trial = used.clone();
                trial.extend(mine.iter().map(|&(slot, _)| windows[*wi][slot]));
                if matching(sc, &rest, &trial, &assign).1.is_some() {
                    used = trial;
                    for &(slot, mv) in &mine {
                        changes.insert(mv, windows[*wi][slot]);
                        placed.insert(mv);
                    }
                    break;
                }
            }
        }
        let singles: Vec<usize> = singles.into_iter().filter(|k| !placed.contains(k)).collect();
        if !singles.is_empty() {
            let (pins, got) = matching(sc, &singles, &used, &assign);
            match got {
                None => {
                    let bad = singles.iter().copied().find(|&k| !pins.iter().any(|q| pb.movable[k].2.contains(q))).unwrap_or(singles[0]);
                    problems.push((part, pb.movable[bad].0));
                    continue;
                }
                Some(got) => {
                    for (k, j) in singles.iter().zip(got.iter()) {
                        changes.insert(*k, pins[*j]);
                    }
                }
            }
        }
        for (k, q) in changes {
            let (net, slot) = (pb.movable[k].0, pb.movable[k].1);
            assign[net] = with(&assign, net, slot, q);
        }
    }
    (assign, problems)
}

struct State {
    pin: Vec<usize>,
    who: HashMap<(usize, usize), usize>,
}

impl State {
    fn new(pb: &Problem, assign: &[Pins]) -> State {
        let pin: Vec<usize> = pb.movable.iter().map(|mv| assign[mv.0][mv.1]).collect();
        let mut who = HashMap::new();
        for (k, &q) in pin.iter().enumerate() {
            who.insert((part_of(pb, k), q), k);
        }
        State { pin, who }
    }

    fn commit(&mut self, pb: &Problem, changes: &BTreeMap<usize, usize>) {
        for &k in changes.keys() {
            let key = (part_of(pb, k), self.pin[k]);
            if self.who.get(&key) == Some(&k) {
                self.who.remove(&key);
            }
        }
        for (&k, &q) in changes {
            self.pin[k] = q;
            self.who.insert((part_of(pb, k), q), k);
        }
    }
}

#[derive(Clone, Copy)]
enum Unit {
    Movable(usize),
    Group(usize),
    Soft(usize),
}

fn units(pb: &Problem, group_parts: &[usize]) -> Vec<Unit> {
    let mut out = Vec::new();
    for &part in group_parts {
        for k in 0..pb.movable.len() {
            if pb.movable[k].3 < 0 && part_of(pb, k) == part {
                out.push(Unit::Movable(k));
            }
        }
        for (g, gr) in pb.groups.iter().enumerate() {
            if gr.0 == part && !gr.2.is_empty() {
                out.push(Unit::Group(g));
            }
        }
        for (g, gr) in pb.soft.iter().enumerate() {
            if gr.0 == part && !gr.3.is_empty() {
                out.push(Unit::Soft(g));
            }
        }
    }
    out
}

/// Soft group `g`'s movables moved whole, in order, to another of its windows; the nets standing where they land take
/// the pins they leave, in pin order (`pinmap_twin._propose_soft`).
fn propose_soft(rng: &mut SplitMix64, st: &State, pb: &Problem, g: usize) -> Option<BTreeMap<usize, usize>> {
    let (part, _, members, windows) = &pb.soft[g];
    let mine: Vec<(usize, usize)> = members.iter().filter(|m| m.1 >= 0).map(|m| (m.0, m.1 as usize)).collect();
    let now: Vec<usize> = mine.iter().map(|&(_, mv)| st.pin[mv]).collect();
    let wins: Vec<&Vec<usize>> = windows.iter()
        .filter(|w| mine.iter().map(|&(slot, _)| w[slot]).collect::<Vec<usize>>() != now).collect();
    if wins.is_empty() {
        return None;
    }
    let win = wins[rng.below(wins.len())];
    let target: Vec<usize> = mine.iter().map(|&(slot, _)| win[slot]).collect();
    let reserved = gaps(pb, st, *part, usize::MAX);
    if target.iter().any(|q| reserved.contains(q)) {
        return None;
    }
    let mut changes: BTreeMap<usize, usize> = mine.iter().zip(target.iter()).map(|(&(_, mv), &q)| (mv, q)).collect();
    let left: Vec<usize> = now.iter().copied().collect::<BTreeSet<usize>>()
        .difference(&target.iter().copied().collect()).copied().collect();
    let mut sorted_target = target.clone();
    sorted_target.sort_unstable();
    let taken: Vec<usize> = sorted_target.into_iter()
        .filter(|q| match st.who.get(&(*part, *q)) {
            Some(o) => !changes.contains_key(o),
            None => false,
        })
        .collect();
    if taken.len() > left.len() {
        return None;
    }
    for (q, r) in taken.iter().zip(left.iter()) {
        let other = st.who[&(*part, *q)];
        if pb.movable[other].3 >= 0 || !pb.movable[other].2.contains(r) {
            return None;
        }
        changes.insert(other, *r);
    }
    Some(changes)
}

/// The window group `g` stands on, if it stands on one.
fn window_of<'p>(pb: &'p Problem, st: &State, g: usize) -> Option<&'p Vec<usize>> {
    let (_, members, windows) = &pb.groups[g];
    windows.iter().find(|w| members.iter().zip(w.iter()).all(|(m, q)| *m < 0 || st.pin[*m as usize] == *q))
}

/// The pins of the empty slots of the groups on `part` (but `except`) where they stand: reserved, as the first map
/// reserves them, so no other net takes one.
fn gaps(pb: &Problem, st: &State, part: usize, except: usize) -> BTreeSet<usize> {
    let mut out = BTreeSet::new();
    for (g, gr) in pb.groups.iter().enumerate() {
        if gr.0 != part || g == except {
            continue;
        }
        if let Some(win) = window_of(pb, st, g) {
            out.extend(gr.1.iter().zip(win.iter()).filter(|(m, _)| **m < 0).map(|(_, q)| *q));
        }
    }
    out
}

fn propose(rng: &mut SplitMix64, st: &State, pb: &Problem, units: &[Unit]) -> Option<BTreeMap<usize, usize>> {
    if units.is_empty() {
        return None;
    }
    match units[rng.below(units.len())] {
        Unit::Movable(i) => {
            let mv = &pb.movable[i];
            let part = part_of(pb, i);
            let here = st.pin[i];
            let reserved = gaps(pb, st, part, usize::MAX);
            let choices: Vec<usize> = mv.2.iter().copied().filter(|&q| q != here && !reserved.contains(&q)).collect();
            if choices.is_empty() {
                return None;
            }
            let to = choices[rng.below(choices.len())];
            let mut out = BTreeMap::new();
            match st.who.get(&(part, to)) {
                None => {
                    out.insert(i, to);
                    Some(out)
                }
                Some(&other) => {
                    if pb.movable[other].3 < 0 && pb.movable[other].2.contains(&here) {
                        out.insert(i, to);
                        out.insert(other, here);
                        Some(out)
                    } else {
                        None
                    }
                }
            }
        }
        Unit::Soft(g) => propose_soft(rng, st, pb, g),
        Unit::Group(g) => {
            let (gpart, members, windows) = &pb.groups[g];
            let now: Vec<usize> = members.iter().filter(|m| **m >= 0).map(|m| st.pin[*m as usize]).collect();
            let wins: Vec<&Vec<usize>> = windows.iter()
                .filter(|w| members.iter().zip(w.iter()).filter(|(m, _)| **m >= 0).map(|(_, q)| *q).collect::<Vec<usize>>() != now)
                .collect();
            if wins.is_empty() {
                return None;
            }
            let win = wins[rng.below(wins.len())];
            let reserved = gaps(pb, st, *gpart, g);
            if win.iter().any(|q| reserved.contains(q)) {
                return None;
            }
            let mut changes = BTreeMap::new();
            for (m, &q) in members.iter().zip(win.iter()) {
                if *m >= 0 {
                    changes.insert(*m as usize, q);
                }
            }
            // the pins it leaves, its empty slots' among them, go to the nets standing where it lands, in pin order
            let was: Vec<usize> = window_of(pb, st, g).cloned().unwrap_or_else(|| now.clone());
            let left: Vec<usize> = was.iter().copied().collect::<BTreeSet<usize>>()
                .difference(&win.iter().copied().collect()).copied().collect();
            let mut sorted_win = win.clone();
            sorted_win.sort_unstable();
            let taken: Vec<usize> = sorted_win.into_iter()
                .filter(|q| match st.who.get(&(*gpart, *q)) {
                    Some(&o) => !members.contains(&(o as i64)),
                    None => false,
                })
                .collect();
            if taken.len() > left.len() {
                return None;
            }
            for (q, r) in taken.iter().zip(left.iter()) {
                let other = st.who[&(*gpart, *q)];
                if pb.movable[other].3 >= 0 || !pb.movable[other].2.contains(r) {
                    return None;
                }
                changes.insert(other, *r);
            }
            Some(changes)
        }
    }
}

/// The local search from `start`: its best, the best's total, and why it stopped early, if it did. Its best starts as
/// `start`, or as `present` when that scores lower: at the present pose the study never reports a map worse than the
/// one the part has. `search` passes `present` only when it is legal.
fn anneal(sc: &mut Scorer, group_parts: &[usize], start: &[Pins], present: Option<&[Pins]>, pr: &Params, combo: usize,
          clock: &mut Clock) -> (Vec<Pins>, f64, Option<Stop>) {
    let pb = sc.pb;
    let mut best = start.to_vec();
    let mut best_v = sc.total(start).0;
    if let Some(present) = present {
        let v = sc.total(present).0;
        if v < best_v - 1e-9 {
            best = present.to_vec();
            best_v = v;
        }
    }
    let units = units(pb, group_parts);
    let n = pr.moves.max(1) as usize;
    for s in 0..pr.seeds.max(1) as usize {
        let mut rng = SplitMix64::new(stream_seed(pr.seed_key, combo, s));
        let mut tally = Tally::new(sc, start);
        let mut st = State::new(pb, start);
        for k in 0..n {
            if k % 32 == 0 && clock.slow() {
                return (best, best_v, Some(Stop::Slow));
            }
            if !clock.take() {
                return (best, best_v, Some(Stop::Budget));
            }
            let temp = if pr.t0 > 0.0 && pr.t1 > 0.0 {
                pr.t0 * (pr.t1 / pr.t0).powf(k as f64 / (n.saturating_sub(1).max(1)) as f64)
            } else {
                0.0
            };
            let got = match propose(&mut rng, &st, pb, &units) {
                Some(g) => g,
                None => continue,
            };
            let mut changes: BTreeMap<usize, Pins> = BTreeMap::new();
            for (&m, &q) in &got {
                let (net, slot) = (pb.movable[m].0, pb.movable[m].1);
                changes.insert(net, with(&tally.assign, net, slot, q));
            }
            let d = tally.delta(sc, &changes);
            if d < -1e-12 || (temp > 0.0 && rng.unit() < (-d / temp).exp()) {
                tally.apply(&changes, d);
                st.commit(pb, &got);
                if tally.value < best_v - 1e-9 {
                    best = tally.assign.clone();
                    best_v = tally.value;
                }
            }
        }
    }
    (best, best_v, None)
}

pub type SearchResult =
    (Tallies, Paths, Vec<(usize, Tallies, Vec<Pins>, Paths)>, bool, bool, Vec<(usize, usize)>, u64, bool);

/// `pinmap_twin.search`: (present tallies, present paths, [(combo, tallies, assignment, paths)], budget_out, first_map,
/// [(part, net)] no matching placed, steps taken, slow). A study past its guard (`slow`) gives no poses and no problems.
pub fn search(pb: &Problem, group_parts: &[usize], combos: &[Vec<(usize, f64, bool)>], pr: &Params) -> SearchResult {
    let bg = Background::new(&pb.wires, pr.w);
    let mut clock = Clock { budget: pr.budget_steps, guard: pr.guard_ms, steps: 0, start: Instant::now() };
    let present: Vec<Pins> = pb.ends.iter().map(|e| e.iter().map(|x| x.1).collect()).collect();
    let present_poses: Vec<Pose> =
        pb.parts.iter().enumerate().map(|(k, p)| Pose::new(p.1, p.2, frame(pb, k), false)).collect();
    let mut sc0 = Scorer::new(pb, present_poses.clone(), pr.w, &bg, group_parts);
    let base = sc0.total(&present);
    let base_paths = sc0.paths(&present);
    let present_legal = legal(pb, &present);
    let (mut results, mut out, mut first, mut problems) = (Vec::new(), false, true, Vec::new());
    for (k, combo) in combos.iter().enumerate() {
        if clock.slow() {
            return (base, base_paths, Vec::new(), out, first, Vec::new(), clock.steps, true);
        }
        if clock.spent() {
            out = true;
            if k == 0 {
                first = false;
            }
            break;
        }
        let mut poses = present_poses.clone();
        for &(part, turn, flip) in combo {
            poses[part] = pose_at(pb, part, turn, flip);
        }
        let mut fresh;
        let sc: &mut Scorer = if k == 0 {
            &mut sc0
        } else {
            fresh = Scorer::new(pb, poses, pr.w, &bg, group_parts);
            &mut fresh
        };
        let (start, said) = first_map(sc, group_parts, &present);
        for p in &said {
            if !problems.contains(p) {
                problems.push(*p);
            }
        }
        if !said.is_empty() && k == 0 {
            return (base, base_paths, Vec::new(), false, true, problems, clock.steps, false);
        }
        let at_present = present_legal && combo.iter().all(|&(_, turn, flip)| turn.rem_euclid(360.0) == 0.0 && !flip);
        let (best, _, stop) = anneal(sc, group_parts, &start, if at_present { Some(&present) } else { None }, pr, k,
                                     &mut clock);
        if stop == Some(Stop::Slow) {
            return (base, base_paths, Vec::new(), out, first, Vec::new(), clock.steps, true);
        }
        let t = sc.total(&best);
        let paths = sc.paths(&best);
        results.push((k, t, best, paths));
        if stop == Some(Stop::Budget) {
            out = true;
            break;
        }
    }
    (base, base_paths, results, out, first, problems, clock.steps, false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitmix_is_the_published_stream() {
        let mut r = SplitMix64::new(1234567);
        assert_eq!(r.next(), 6457827717110365317);
        assert_eq!(r.next(), 3203168211198807973);
    }

    #[test]
    fn the_matching_is_the_cheapest_and_refuses_what_cannot_be_matched() {
        assert_eq!(hungarian(&[vec![4.0, 1.0, 3.0], vec![2.0, 0.0, 5.0], vec![3.0, 2.0, 2.0]]), Some(vec![1, 0, 2]));
        assert_eq!(hungarian(&[vec![1.0, f64::INFINITY], vec![2.0, f64::INFINITY]]), None);
    }

    fn reversed_four() -> Problem {
        // U1 with A-D on its east side north to south; their test points due east in the opposite order
        let pins = (0..4).map(|i| ((i + 1).to_string(), 1.7, -1.5 + i as f64, 1.0, 0.0)).collect();
        let fixed = (0..4).map(|i| vec![(20.0, 11.5 - i as f64, format!("TP{}", 4 - i), "1".to_string())]).collect();
        Problem {
            parts: vec![("U1".into(), 10.0, 10.0, 2.25, 2.25)], pins: vec![pins],
            nets: vec![("A".into(), 0), ("B".into(), 0), ("C".into(), 0), ("D".into(), 0)], fixed,
            joined: vec![vec![]; 4], ends: (0..4).map(|i| vec![(0, i)]).collect(), wires: vec![], posed: vec![],
            movable: (0..4).map(|i| (i, 0, vec![0, 1, 2, 3], -1)).collect(), groups: vec![], soft: vec![], margin: 0.5,
            frames: vec![], controlled: vec![],
        }
    }

    #[test]
    fn four_nets_in_reverse_order_are_uncrossed() {
        let pb = reversed_four();
        let pr = Params { w: [5.0, 3.0, 0.0, 0.25, 0.005, 1.0], seeds: 3, moves: 400, t0: 1.0, t1: 0.02, budget_steps: 1 << 40,
                          guard_ms: 0.0, seed_key: 7 };
        let (base, _, results, out, first, problems, _, _) = search(&pb, &[0], &[vec![(0, 0.0, false)]], &pr);
        assert_eq!((base.2, out, first, problems.len()), (6, false, true, 0));
        assert_eq!(results[0].1 .2, 0);
        assert_eq!(results[0].2, vec![vec![3], vec![2], vec![1], vec![0]]);
    }

    #[test]
    fn the_search_stops_at_its_budget_in_steps_and_gives_no_map_past_its_guard() {
        let pb = reversed_four();
        let combos = [vec![(0, 0.0, false)], vec![(0, 90.0, false)]];
        let pr = |budget_steps, guard_ms| Params { w: [5.0, 3.0, 0.0, 0.25, 0.005, 1.0], seeds: 2, moves: 50, t0: 1.0,
                                                  t1: 0.02, budget_steps, guard_ms, seed_key: 7 };
        let (_, _, results, out, _, _, steps, slow) = search(&pb, &[0], &combos, &pr(1 << 40, 0.0));
        assert_eq!((results.len(), out, steps, slow), (2, false, 200, false));
        let (_, _, results, out, _, _, steps, slow) = search(&pb, &[0], &combos, &pr(130, 0.0));
        assert_eq!((results.len(), out, steps, slow), (2, true, 130, false));
        let (_, _, results, _, _, _, _, slow) = search(&pb, &[0], &combos, &pr(1 << 40, 1e-9));
        assert_eq!((results.len(), slow), (0, true));
    }

    /// A group of three on pins 2-4 whose middle net an allow rule holds on 3: its windows are 2-4 (where it stands)
    /// and 4-6. Every net faces its target where it stands.
    fn held_group() -> Problem {
        let pins = (0..6).map(|i| {
            let (nx, ny) = match i { 0 => (0.0, -1.0), 5 => (0.0, 1.0), _ => (1.0, 0.0) };
            ((i + 1).to_string(), 1.7, -2.5 + i as f64, nx, ny)
        }).collect();
        let fixed = (0..4).map(|i| vec![(20.0, 7.5 + i as f64, format!("T{i}"), "1".to_string())]).collect();
        let free = vec![0, 1, 3, 4, 5];
        Problem {
            parts: vec![("U1".into(), 10.0, 10.0, 2.25, 2.25)], pins: vec![pins],
            nets: vec![("A".into(), 0), ("D".into(), 0), ("E".into(), 0), ("F".into(), 0)], fixed,
            joined: vec![vec![]; 4], ends: (0..4).map(|i| vec![(0, i)]).collect(), wires: vec![], posed: vec![],
            movable: vec![(0, 0, free.clone(), -1), (1, 0, free.clone(), 0), (3, 0, free, 0)],
            groups: vec![(0, vec![1, -1, 2], vec![vec![1, 2, 3], vec![3, 4, 5]])], soft: vec![], margin: 0.5,
            frames: vec![], controlled: vec![],
        }
    }

    #[test]
    fn at_the_present_pose_the_best_is_never_worse_than_the_present_map() {
        // one seed of 100 moves from the first map ends on the 4-6 window, worse than where the group stands
        let pb = held_group();
        let pr = Params { w: [5.0, 3.0, 0.0, 0.25, 0.005, 1.0], seeds: 1, moves: 100, t0: 1.0, t1: 0.02, budget_steps: 1 << 40,
                          guard_ms: 0.0, seed_key: 15606770251161693233 };
        let (base, _, results, _, _, _, _, _) = search(&pb, &[0], &[vec![(0, 0.0, false)]], &pr);
        assert_eq!(results[0].2, vec![vec![0], vec![1], vec![2], vec![3]]);
        assert_eq!(results[0].1 .0.to_bits(), base.0.to_bits());
    }

    /// A and B on east pins 1 and 2 of six, their targets due east of them, and allowed only `allowed`: the present
    /// map is the cheapest there is, and breaks the rule. `group` makes them a hard group, `windows` its windows.
    fn barred(allowed: Vec<usize>, group: Option<Vec<Vec<usize>>>) -> Problem {
        let pins = (0..6).map(|i| ((i + 1).to_string(), 1.7, -2.5 + i as f64, 1.0, 0.0)).collect();
        let fixed = (0..2).map(|i| vec![(20.0, 7.5 + i as f64, format!("T{i}"), "1".to_string())]).collect();
        let g = if group.is_some() { 0 } else { -1 };
        Problem {
            parts: vec![("U1".into(), 10.0, 10.0, 2.25, 2.25)], pins: vec![pins],
            nets: vec![("A".into(), 0), ("B".into(), 0)], fixed, joined: vec![vec![]; 2],
            ends: (0..2).map(|i| vec![(0, i)]).collect(), wires: vec![], posed: vec![],
            movable: (0..2).map(|i| (i, 0, allowed.clone(), g)).collect(),
            groups: group.map(|w| vec![(0, vec![0, 1], w)]).unwrap_or_default(), soft: vec![], margin: 0.5,
            frames: vec![], controlled: vec![],
        }
    }

    fn short() -> Params {
        Params { w: [5.0, 3.0, 0.0, 0.25, 0.005, 1.0], seeds: 2, moves: 200, t0: 1.0, t1: 0.02, budget_steps: 1 << 40,
                 guard_ms: 0.0, seed_key: 7 }
    }

    #[test]
    fn a_present_map_that_breaks_its_rule_is_no_candidate() {
        for group in [None, Some(vec![vec![4, 5]])] {
            let pb = barred(vec![4, 5], group);
            let (base, _, results, _, _, problems, _, _) = search(&pb, &[0], &[vec![(0, 0.0, false)]], &short());
            assert!(problems.is_empty());
            let got: BTreeSet<usize> = results[0].2.iter().map(|p| p[0]).collect();
            assert_eq!(got, BTreeSet::from([4, 5]));
            assert!(results[0].1 .0 > base.0);
        }
    }

    #[test]
    fn a_hard_group_on_barred_pins_with_no_window_is_reported_not_kept() {
        let pb = barred(vec![4, 5], Some(vec![]));
        let (_, _, results, _, first, problems, _, _) = search(&pb, &[0], &[vec![(0, 0.0, false)]], &short());
        assert_eq!((results.len(), first, problems), (0, true, vec![(0, 0)]));
    }

    fn seg(ax: i64, ay: i64, bx: i64, by: i64) -> Seg {
        [ax, ay, bx, by, ax.min(bx), ay.min(by), ax.max(bx), ay.max(by)]
    }

    #[test]
    fn a_long_diagonal_is_filed_only_in_the_cells_it_passes_through() {
        // 20 mm square diagonal: 10 cells along it and their neighbours at most, not the 121 of its box
        let got = cells(&seg(0, 0, 20_000_000, 20_000_000));
        assert!(got.len() <= 31, "{} cells", got.len());
        for k in 0..10 {
            assert!(got.contains(&(k, k)));
        }
        let flat = cells(&seg(-1_000_000, 5_000_000, 9_000_000, 5_000_000));
        assert_eq!(flat, (-1..=4).map(|x| (x, 2)).collect::<Vec<_>>());
    }

    #[test]
    fn the_grid_finds_every_crossing_a_full_scan_finds() {
        let w = [5.0, 3.0, 0.7, 0.25, 0.005, 1.0];
        let mut r = SplitMix64::new(11);
        let mut c = |lo: i64, hi: i64| lo + (r.next() % (hi - lo) as u64) as i64;
        let mut wires = Vec::new();
        for k in 0..300 {
            let (ax, ay) = (c(-40_000_000, 40_000_000), c(-40_000_000, 40_000_000));
            // some on cell lines exactly, some long
            let ax = if k % 10 == 0 { (ax / CELL_NM) * CELL_NM } else { ax };
            let (bx, by) = if k % 5 == 0 { (ax, ay + c(-30_000_000, 30_000_000)) } else {
                (ax + c(-30_000_000, 30_000_000), (ay / CELL_NM) * CELL_NM)
            };
            wires.push(((k % 4) as u8, ax, ay, bx, by));
        }
        let bg = Background::new(&wires, w);
        for _ in 0..200 {
            let (ax, ay) = (c(-40_000_000, 40_000_000), c(-40_000_000, 40_000_000));
            let s = seg(ax, ay, ax + c(-30_000_000, 30_000_000), ay + c(-30_000_000, 30_000_000));
            let (mut total, mut count) = (0.0, 0i64);
            for t in &wires {
                if cross_nm(s[0], s[1], s[2], s[3], t.1, t.2, t.3, t.4) {
                    total += crossing(&w, 1, t.0);
                    count += 1;
                }
            }
            let got = bg.cross(1, &[s], &[]);
            assert_eq!((got.0.to_bits(), got.1), (total.to_bits(), count));
        }
    }

    #[test]
    fn a_quiet_net_on_a_studied_part_turns_with_it() {
        // U1's pin 2 (west) on a plane net whose other pad is due north of it
        let mut pb = reversed_four();
        pb.pins[0].push(("5".into(), -1.7, 0.0, -1.0, 0.0));
        let pads = vec![(8.3, 10.0, "U1".into(), "5".into(), 0, 4), (8.3, 0.0, "J1".into(), "1".into(), -1, -1)];
        pb.posed = vec![(PLANE, pads, vec![])];
        let ends = |segs: Vec<(u8, Seg)>| -> Vec<BTreeSet<(i64, i64)>> {
            segs.iter().map(|(_, s)| [(s[0], s[1]), (s[2], s[3])].into_iter().collect()).collect()
        };
        let w = [5.0, 3.0, 1.0, 0.25, 0.005, 1.0];
        let here = posed_wires(&pb, &[Pose::new(10.0, 10.0, 0.0, false)], &w);
        let turned = posed_wires(&pb, &[Pose::new(10.0, 10.0, 180.0, false)], &w);
        assert_eq!(ends(here), vec![[(8_300_000, 10_000_000), (8_300_000, 0)].into_iter().collect()]);
        assert_eq!(ends(turned), vec![[(11_700_000, 10_000_000), (8_300_000, 0)].into_iter().collect()]);
        assert!(posed_wires(&pb, &[Pose::new(10.0, 10.0, 180.0, false)], &[5.0, 3.0, 0.0, 0.25, 0.005, 1.0]).is_empty());
    }
}

#[cfg(test)]
mod prop {
    use super::*;

    fn rnd(r: &mut SplitMix64, lo: f64, hi: f64) -> f64 {
        lo + (hi - lo) * r.unit()
    }

    /// U1 (12 pins E/S/W + 1 north pin on a plane net), U2 (4 west pins); a group [n0, -, n1]; a fixed net; a net joining
    /// U1 and U2; a multi-pad net; random anchors, kinds and background.
    fn problem(seed: u64) -> (Problem, Vec<usize>) {
        let mut r = SplitMix64::new(seed);
        let mut u1 = Vec::new();
        for i in 0..4 { u1.push(((u1.len() + 1).to_string(), 3.0, -1.5 + i as f64, 1.0, 0.0)); }
        for i in 0..4 { u1.push(((u1.len() + 1).to_string(), 1.5 - i as f64, 3.0, 0.0, 1.0)); }
        for i in 0..4 { u1.push(((u1.len() + 1).to_string(), -3.0, 1.5 - i as f64, -1.0, 0.0)); }
        u1.push(("13".into(), 0.0, -3.0, 0.0, -1.0));
        let u2: Vec<Row> = (0..4).map(|i| ((i + 1).to_string(), -2.0, -1.5 + i as f64, -1.0, 0.0)).collect();
        let parts = vec![("U1".into(), 10.0, 10.0, 3.0, 3.0), ("U2".into(), 30.0, 12.0, 2.0, 2.0)];
        // nets 0..5 single on U1, 6 joint U1-U2, 7 fixed on U1 pin 6, 8 multi-pad on U1, 9 single on U2
        let mut nets = Vec::new();
        for n in 0..10 { nets.push((format!("N{n}"), (r.below(3)) as u8)); }
        let mut fixed = Vec::new();
        for n in 0..10 {
            let k = match n { 6 => 0, 8 => 3, _ => 1 };
            fixed.push((0..k).map(|j| (rnd(&mut r, -10.0, 50.0), rnd(&mut r, -10.0, 40.0), format!("T{n}"), (j + 1).to_string())).collect::<Vec<_>>());
        }
        let mut joined = vec![vec![]; 10];
        joined[8] = vec![(0, 1)];
        let present = [0usize, 2, 3, 4, 5, 7];
        let mut ends: Vec<Vec<(usize, usize)>> = present.iter().map(|&p| vec![(0, p)]).collect();
        ends.push(vec![(0, 8), (1, 1)]);
        ends.push(vec![(0, 6)]);
        ends.push(vec![(0, 9)]);
        ends.push(vec![(1, 0)]);
        let all: Vec<usize> = (0..12).filter(|&p| p != 6).collect();
        let movable = vec![
            (0, 0, all.clone(), 0), (1, 0, all.clone(), 0),
            (2, 0, vec![3, 5, 7, 11], -1), (3, 0, all.clone(), -1), (4, 0, all.clone(), -1), (5, 0, all.clone(), -1),
            (6, 0, all.clone(), -1), (6, 1, vec![0, 1, 2, 3], -1), (8, 0, all.clone(), -1), (9, 0, vec![0, 1, 2, 3], -1),
        ];
        let groups = vec![(0, vec![0, -1, 1], vec![vec![0, 1, 2], vec![3, 4, 5], vec![8, 9, 10]])];
        let mut wires = Vec::new();
        for _ in 0..40 {
            let (ax, ay) = (rnd(&mut r, -10.0, 50.0), rnd(&mut r, -10.0, 40.0));
            let (bx, by) = (ax + rnd(&mut r, -15.0, 15.0), ay + rnd(&mut r, -15.0, 15.0));
            wires.push((r.below(4) as u8, nm(ax), nm(ay), nm(bx), nm(by)));
        }
        let posed = vec![(PLANE, vec![(10.0, 7.0, "U1".into(), "13".into(), 0, 12), (rnd(&mut r, 0.0, 20.0), -5.0, "J1".into(), "1".into(), -1, -1)], vec![])];
        // a soft group of nets 3, 4 and 5 round net 7, held on pin 6, with an empty slot between 4 and 5
        let soft = vec![(0, 1.0, vec![(0, 3, -1), (1, -1, 6), (2, 4, -1), (4, 5, -1)],
                         vec![vec![0, 1, 2, 3, 4], vec![7, 8, 9, 10, 11]])];
        let frames = vec![[0.0, 30.0, 45.0][r.below(3)], 0.0];
        let controlled = (0..10).map(|_| r.below(3) == 0).collect();
        let pb = Problem { parts, pins: vec![u1, u2], nets, fixed, joined, ends, wires, posed, movable, groups, soft,
                           margin: 0.5, frames, controlled };
        (pb, vec![0, 1])
    }

    fn check_constraints(pb: &Problem, a: &[Pins]) {
        // net 7 held on U1 pin 6; every movable on an allowed pin; one net per pin; the group whole and in order on a
        // window, and no single on the pin of its empty slot
        assert_eq!(a[7], vec![6]);
        let mut seen = BTreeSet::new();
        for (n, pins) in a.iter().enumerate() {
            for (k, &q) in pins.iter().enumerate() {
                assert!(seen.insert((pb.ends[n][k].0, q)), "two nets on part {} pin {q}", pb.ends[n][k].0);
            }
        }
        for mv in &pb.movable {
            assert!(mv.2.contains(&a[mv.0][mv.1]), "net {} off its allowed pins", mv.0);
        }
        let (_, members, wins) = &pb.groups[0];
        let at: Vec<Option<usize>> = members.iter()
            .map(|&m| if m >= 0 { let mv = &pb.movable[m as usize]; Some(a[mv.0][mv.1]) } else { None }).collect();
        let win = wins.iter().find(|w| at.iter().zip(w.iter()).all(|(p, q)| p.is_none_or(|p| p == *q)));
        let win = win.unwrap_or_else(|| panic!("group off its windows: {at:?}"));
        for (m, q) in members.iter().zip(win.iter()) {
            if *m < 0 {
                assert!(!seen.contains(&(0, *q)), "a single on the group's empty slot, pin {q}");
            }
        }
    }

    /// After each accepted move the running total is the full rescore's, and the constraints hold: a few boards and
    /// poses, every gain and most losses taken.
    #[test]
    fn the_running_total_is_a_full_rescore_after_every_move() {
        let w = [5.0, 3.0, 0.7, 0.25, 0.005, 1.0];
        let mut accepted = 0;
        for seed in 0..4u64 {
            let (pb, both) = problem(seed);
            let gp: Vec<usize> = if seed % 2 == 0 { both } else { vec![0] };
            let bg = Background::new(&pb.wires, w);
            let present: Vec<Pins> = pb.ends.iter().map(|e| e.iter().map(|x| x.1).collect()).collect();
            let mut r = SplitMix64::new(seed ^ 0xABCDEF);
            let turns = [0.0, 90.0, 180.0, 270.0, 45.0];
            let mut poses: Vec<Pose> = pb.parts.iter().map(|p| Pose::new(p.1, p.2, 0.0, false)).collect();
            for (p, pose) in poses.iter_mut().enumerate() {
                *pose = Pose::new(pb.parts[p].1, pb.parts[p].2, turns[r.below(5)], r.below(2) == 1);
            }
            let mut sc = Scorer::new(&pb, poses.clone(), w, &bg, &gp);
            let (start, probs) = first_map(&mut sc, &gp, &present);
            assert!(probs.is_empty());
            check_constraints(&pb, &start);
            let units = units(&pb, &gp);
            let mut tally = Tally::new(&mut sc, &start);
            let mut st = State::new(&pb, &start);
            for _ in 0..150 {
                let got = match propose(&mut r, &st, &pb, &units) {
                    Some(g) => g,
                    None => continue,
                };
                let mut changes: BTreeMap<usize, Pins> = BTreeMap::new();
                for (&m, &q) in &got {
                    let (net, slot) = (pb.movable[m].0, pb.movable[m].1);
                    changes.insert(net, with(&tally.assign, net, slot, q));
                }
                let d = tally.delta(&mut sc, &changes);
                if d < 0.0 || r.unit() < 0.7 {
                    tally.apply(&changes, d);
                    st.commit(&pb, &got);
                    accepted += 1;
                    let full = sc.total(&tally.assign).0;
                    let fresh = Scorer::new(&pb, poses.clone(), w, &bg, &gp).total(&tally.assign).0;
                    assert_eq!(full.to_bits(), fresh.to_bits());
                    assert!((tally.value - full).abs() <= 1e-9 * full.abs().max(1.0), "seed {seed}: {} vs {full}", tally.value);
                    check_constraints(&pb, &tally.assign);
                    for (k, mv) in pb.movable.iter().enumerate() {
                        assert_eq!(st.pin[k], tally.assign[mv.0][mv.1]);
                    }
                }
            }
        }
        assert!(accepted > 200, "{accepted} moves taken");
    }
}
