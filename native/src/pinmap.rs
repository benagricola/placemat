//! The pin map study's core (`placemat.pinmap_core`; its Python twin is `placemat.pinmap_twin`, which this mirrors line
//! for line so the two give the same answers). It takes a study as plain arrays and, for the parts of one group and each
//! combination of their poses, returns the best assignment of the movable nets to pins with its tallies.
//!
//! - Score: weighted crossings of the studied nets' airwires against the board's other airwires (on a 2 mm grid) and
//!   among themselves, plus `length` times their length in mm, plus `bend` times their summed bend in degrees. A net's
//!   airwires are the minimum spanning tree of its pads (`ratsnest::mst`), each studied pin at its exit point and each
//!   airwire to one taken round the body (pinmap_geom.rs).
//! - Background: the board's other airwires. Those of a net with a pad on a studied part (a plane's, on the part's
//!   ground pins) are not fixed: `posed` carries such a net's pads, and at each pose its tree is worked out again with
//!   the part's pads turned with it, after the fixed wires in the order a segment meets its candidates.
//! - Incremental: a net's airwires, its crossings with the background and with each other net are kept per placing of
//!   its ends, so a move recounts only the nets it touches.
//! - Search: a first map (each group on the cheapest run of pins that leaves the rest a matching, then a minimum-cost
//!   matching), then per seed `moves` moves, swaps and group moves under annealing from `t0` down to `t1`, the clock
//!   checked every 32 moves and between poses. The random stream is SplitMix64, the twin's.

use crate::exact::hypot;
use crate::pinmap_geom::{bend, exit_of, length, route, End, Exit, Pose};
use crate::ratsnest::{cross_nm, mst, nm};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::rc::Rc;
use std::time::Instant;

pub const CELL_NM: i64 = 2_000_000; // pinmap_twin.CELL_NM
const PAIR: u8 = 1;
const IMPEDANCE: u8 = 2;
const PLANE: u8 = 3;

/// (ax, ay, bx, by, minx, miny, maxx, maxy) in whole nanometres.
pub type Seg = [i64; 8];
/// (total, against, among, weighted, length, bend).
pub type Tallies = (f64, i64, i64, f64, f64, f64);
pub type Paths = Vec<(usize, Vec<Vec<(f64, f64)>>)>;

/// A part (ref, cx, cy, hw, hh), or a pin (number, x, y, nx, ny).
pub type Row = (String, f64, f64, f64, f64);

/// A background net with a pad on a studied part (`Problem::posed`).
pub type Posed = (u8, Vec<(f64, f64, String, String, i64, i64)>, Vec<(usize, usize)>);

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
    pub margin: f64,
}

/// (pair, impedance, plane, length, bend) weights and the search's own figures.
pub struct Params {
    pub w: [f64; 5],
    pub seeds: u32,
    pub moves: u32,
    pub t0: f64,
    pub t1: f64,
    pub budget_ms: f64,
    pub step_ms: f64,
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

struct Clock {
    budget: f64,
    step: f64,
    elapsed: f64,
    start: Instant,
}

impl Clock {
    fn out(&mut self) -> bool {
        if self.step > 0.0 {
            self.elapsed += self.step;
        } else {
            self.elapsed = self.start.elapsed().as_secs_f64() * 1000.0;
        }
        self.elapsed >= self.budget
    }
}

fn one(w: &[f64; 5], k: u8) -> f64 {
    match k {
        PAIR => w[0],
        IMPEDANCE => w[1],
        _ => 1.0,
    }
}

/// What a crossing of classes `a` and `b` counts.
pub fn crossing(w: &[f64; 5], a: u8, b: u8) -> f64 {
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

fn cells(s: &Seg) -> Vec<(i64, i64)> {
    let mut out = Vec::new();
    for cx in s[4].div_euclid(CELL_NM)..=s[6].div_euclid(CELL_NM) {
        for cy in s[5].div_euclid(CELL_NM)..=s[7].div_euclid(CELL_NM) {
            out.push((cx, cy));
        }
    }
    out
}

struct Background {
    w: [f64; 5],
    kinds: Vec<u8>,
    segs: Vec<Seg>,
    grid: HashMap<(i64, i64), Vec<usize>>,
}

impl Background {
    fn new(wires: &[(u8, i64, i64, i64, i64)], w: [f64; 5]) -> Background {
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

/// The posed nets' airwires at `poses` (one per part): each net's tree over its pads, a pad of a part at a pose other
/// than its present one turned with the part about its centre, the rest where they stand. A plane's are left out when
/// its crossings weigh nothing, as the fixed wires' are.
pub fn posed_wires(pb: &Problem, poses: &[Pose], w: &[f64; 5]) -> Vec<(u8, Seg)> {
    let mut out = Vec::new();
    for (kind, pads, joined) in &pb.posed {
        if *kind == PLANE && w[2] <= 0.0 {
            continue;
        }
        let at: Vec<(f64, f64, String, String)> = pads.iter().map(|a| {
            let (x, y) = if a.4 >= 0 {
                let pose = poses[a.4 as usize];
                if pose.turn == 0.0 && !pose.flip {
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
    w: [f64; 5],
    bg: &'a Background,
    extra: Vec<(u8, Seg)>,
    exits: HashMap<(usize, usize), Exit>,
    wires: HashMap<(usize, Pins), Rc<NetWires>>,
    single: HashMap<(usize, Pins), (f64, f64, i64)>,
    pair: HashMap<(usize, Pins, usize, Pins), (f64, i64)>,
}

impl<'a> Scorer<'a> {
    fn new(pb: &'a Problem, poses: Vec<Pose>, w: [f64; 5], bg: &'a Background) -> Scorer<'a> {
        let extra = posed_wires(pb, &poses, &w);
        Scorer { pb, poses, w, bg, extra, exits: HashMap::new(), wires: HashMap::new(), single: HashMap::new(), pair: HashMap::new() }
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
        let hit = (weighted + self.w[3] * nw.length + self.w[4] * nw.bend, weighted, count);
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

    fn total(&mut self, assign: &[Pins]) -> Tallies {
        let (mut weighted, mut against, mut among, mut ln, mut bd) = (0.0, 0i64, 0i64, 0.0, 0.0);
        for (n, pins) in assign.iter().enumerate() {
            let (_, w, c) = self.single(n, pins);
            let nw = self.wires(n, pins);
            weighted += w;
            against += c;
            ln += nw.length;
            bd += nw.bend;
        }
        for a in 0..assign.len() {
            for b in a + 1..assign.len() {
                let (w, c) = self.pair(a, &assign[a], b, &assign[b]);
                weighted += w;
                among += c;
            }
        }
        (weighted + self.w[3] * ln + self.w[4] * bd, against, among, weighted, ln, bd)
    }

    fn paths(&mut self, group_parts: &[usize], assign: &[Pins]) -> Paths {
        let mut out = Vec::new();
        for (n, pins) in assign.iter().enumerate() {
            if (0..pins.len()).any(|k| group_parts.contains(&self.pb.ends[n][k].0)) {
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

fn first_map(sc: &mut Scorer, group_parts: &[usize], start: &[Pins]) -> (Vec<Pins>, Vec<(usize, usize)>) {
    let pb = sc.pb;
    let mut assign = start.to_vec();
    let mut problems = Vec::new();
    for &part in group_parts {
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
            ranked.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1)));
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
            let choices: Vec<usize> = mv.2.iter().copied().filter(|&q| q != here).collect();
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
            let mut changes = BTreeMap::new();
            for (m, &q) in members.iter().zip(win.iter()) {
                if *m >= 0 {
                    changes.insert(*m as usize, q);
                }
            }
            let left: Vec<usize> = now.iter().copied().collect::<BTreeSet<usize>>()
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

fn anneal(sc: &mut Scorer, group_parts: &[usize], start: &[Pins], pr: &Params, combo: usize, clock: &mut Clock) -> (Vec<Pins>, f64, bool) {
    let pb = sc.pb;
    let mut best = start.to_vec();
    let mut best_v = sc.total(start).0;
    let units = units(pb, group_parts);
    let n = pr.moves.max(1) as usize;
    for s in 0..pr.seeds.max(1) as usize {
        let mut rng = SplitMix64::new(stream_seed(pr.seed_key, combo, s));
        let mut tally = Tally::new(sc, start);
        let mut st = State::new(pb, start);
        for k in 0..n {
            if k % 32 == 0 && clock.out() {
                return (best, best_v, true);
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
    (best, best_v, false)
}

pub type SearchResult = (Tallies, Paths, Vec<(usize, Tallies, Vec<Pins>, Paths)>, bool, bool, Vec<(usize, usize)>);

/// `pinmap_twin.search`: (present tallies, present paths, [(combo, tallies, assignment, paths)], budget_out, first_map,
/// [(part, net)] no matching placed).
pub fn search(pb: &Problem, group_parts: &[usize], combos: &[Vec<(usize, f64, bool)>], pr: &Params) -> SearchResult {
    let bg = Background::new(&pb.wires, pr.w);
    let mut clock = Clock { budget: pr.budget_ms, step: pr.step_ms, elapsed: 0.0, start: Instant::now() };
    let present: Vec<Pins> = pb.ends.iter().map(|e| e.iter().map(|x| x.1).collect()).collect();
    let present_poses: Vec<Pose> = pb.parts.iter().map(|p| Pose::new(p.1, p.2, 0.0, false)).collect();
    let mut sc0 = Scorer::new(pb, present_poses.clone(), pr.w, &bg);
    let base = sc0.total(&present);
    let base_paths = sc0.paths(group_parts, &present);
    let (mut results, mut out, mut first, mut problems) = (Vec::new(), false, true, Vec::new());
    for (k, combo) in combos.iter().enumerate() {
        if clock.out() {
            out = true;
            if k == 0 {
                first = false;
            }
            break;
        }
        let mut poses = present_poses.clone();
        for &(part, turn, flip) in combo {
            poses[part] = Pose::new(pb.parts[part].1, pb.parts[part].2, turn, flip);
        }
        let mut fresh;
        let sc: &mut Scorer = if k == 0 {
            &mut sc0
        } else {
            fresh = Scorer::new(pb, poses, pr.w, &bg);
            &mut fresh
        };
        let (start, said) = first_map(sc, group_parts, &present);
        for p in &said {
            if !problems.contains(p) {
                problems.push(*p);
            }
        }
        if !said.is_empty() && k == 0 {
            return (base, base_paths, Vec::new(), false, true, problems);
        }
        let (best, _, ran_out) = anneal(sc, group_parts, &start, pr, k, &mut clock);
        let t = sc.total(&best);
        let paths = sc.paths(group_parts, &best);
        results.push((k, t, best, paths));
        if ran_out {
            out = true;
            break;
        }
    }
    (base, base_paths, results, out, first, problems)
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
            movable: (0..4).map(|i| (i, 0, vec![0, 1, 2, 3], -1)).collect(), groups: vec![], margin: 0.5,
        }
    }

    #[test]
    fn four_nets_in_reverse_order_are_uncrossed() {
        let pb = reversed_four();
        let pr = Params { w: [5.0, 3.0, 0.0, 0.25, 0.005], seeds: 3, moves: 400, t0: 1.0, t1: 0.02, budget_ms: 60000.0,
                          step_ms: 0.0, seed_key: 7 };
        let (base, _, results, out, first, problems) = search(&pb, &[0], &[vec![(0, 0.0, false)]], &pr);
        assert_eq!((base.2, out, first, problems.len()), (6, false, true, 0));
        assert_eq!(results[0].1 .2, 0);
        assert_eq!(results[0].2, vec![vec![3], vec![2], vec![1], vec![0]]);
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
        let w = [5.0, 3.0, 1.0, 0.25, 0.005];
        let here = posed_wires(&pb, &[Pose::new(10.0, 10.0, 0.0, false)], &w);
        let turned = posed_wires(&pb, &[Pose::new(10.0, 10.0, 180.0, false)], &w);
        assert_eq!(ends(here), vec![[(8_300_000, 10_000_000), (8_300_000, 0)].into_iter().collect()]);
        assert_eq!(ends(turned), vec![[(11_700_000, 10_000_000), (8_300_000, 0)].into_iter().collect()]);
        assert!(posed_wires(&pb, &[Pose::new(10.0, 10.0, 180.0, false)], &[5.0, 3.0, 0.0, 0.25, 0.005]).is_empty());
    }
}
