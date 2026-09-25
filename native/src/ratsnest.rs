//! The placed ratsnest, mirrored from `placemat.ratsnest.Ratsnest` for the
//! one question a candidate asks of it: `leaf_costs` - the weighted
//! crossings its leaf airwires would add, and the escapes they would cross.
//! Python computes each net's tree (`mst`) and hands the anchors and the
//! airwires over after every `set_net`; this answers the question in
//! Python's own order, so a sum of weights adds up in the same order and
//! every comparison lands the same way.

use crate::exact::hypot;
use std::collections::HashMap;

const CELL: f64 = 2.0; // ratsnest._CELL

#[derive(Clone)]
pub struct Anchor {
    pub part: u32, // interned refdes; 0 is "" (a copper anchor)
    pub pad: u32,  // interned "refdes\u{1f}number": which pad it is
    pub x: f64,
    pub y: f64,
}

struct Edge {
    net: u32,
    a: Anchor,
    b: Anchor,
    nm: (i64, i64, i64, i64),
}

pub fn nm(v: f64) -> i64 {
    (v * 1e6).round_ties_even() as i64
}

#[inline]
fn turn(ax: i64, ay: i64, bx: i64, by: i64, cx: i64, cy: i64) -> i32 {
    let v = (bx - ax) as i128 * (cy - ay) as i128 - (by - ay) as i128 * (cx - ax) as i128;
    (v > 0) as i32 - (v < 0) as i32
}

/// `ratsnest._cross_nm`.
pub fn cross_nm(ax: i64, ay: i64, bx: i64, by: i64, cx: i64, cy: i64, dx: i64, dy: i64) -> bool {
    if ax.max(bx) < cx.min(dx) || cx.max(dx) < ax.min(bx) || ay.max(by) < cy.min(dy) || cy.max(dy) < ay.min(by) {
        return false;
    }
    turn(ax, ay, bx, by, cx, cy) * turn(ax, ay, bx, by, dx, dy) < 0
        && turn(cx, cy, dx, dy, ax, ay) * turn(cx, cy, dx, dy, bx, by) < 0
}

/// `ratsnest._dist`: the distance in nanometres, rounded, between anchor
/// positions already in nanometres.
fn dist_nm(ax: i64, ay: i64, bx: i64, by: i64) -> i64 {
    let h = hypot((ax - bx) as f64, (ay - by) as f64);
    (h + 0.5).floor() as i64
}

/// `ratsnest.mst`: the airwires of one net as index pairs into `anchors`
/// ((x, y, refdes, pad number)), in the order Kruskal takes them. `joined`
/// are pairs copper already connects.
pub fn mst(anchors: &[(f64, f64, String, String)], joined: &[(usize, usize)]) -> Vec<(usize, usize)> {
    let n = anchors.len();
    if n < 2 {
        return Vec::new();
    }
    let pos: Vec<(i64, i64)> = anchors.iter().map(|a| (nm(a.0), nm(a.1))).collect();
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&i, &j| {
        (pos[i].0, pos[i].1, &anchors[i].2, &anchors[i].3).cmp(&(pos[j].0, pos[j].1, &anchors[j].2, &anchors[j].3))
    });
    let mut tag = vec![0usize; n];
    for (t, &i) in order.iter().enumerate() {
        tag[i] = t;
    }
    let mut parent: Vec<usize> = (0..n).collect();
    fn find(parent: &mut [usize], mut i: usize) -> usize {
        while parent[i] != i {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        i
    }
    fn unite(parent: &mut [usize], i: usize, j: usize) -> bool {
        let (ri, rj) = (find(parent, i), find(parent, j));
        if ri == rj {
            return false;
        }
        parent[ri] = rj;
        true
    }
    for &(i, j) in joined {
        unite(&mut parent, i, j);
    }
    let end = |i: usize| (pos[i].0, pos[i].1, tag[i]);
    let mut cand: Vec<(i64, (i64, i64, usize), (i64, i64, usize), usize, usize)> = Vec::with_capacity(n * (n - 1) / 2);
    for i in 0..n {
        for j in i + 1..n {
            let w = dist_nm(pos[i].0, pos[i].1, pos[j].0, pos[j].1).max(1);
            let (a, b) = (end(i), end(j));
            let (first, second) = if a <= b { (a, b) } else { (b, a) };
            cand.push((w, first, second, i, j));
        }
    }
    cand.sort_unstable();
    let mut out = Vec::with_capacity(n - 1);
    for (_, _, _, i, j) in cand {
        if unite(&mut parent, i, j) {
            out.push((i, j));
            if out.len() == n - 1 {
                break;
            }
        }
    }
    out
}

/// `ratsnest.segments_cross`, points in mm.
pub fn segments_cross(p: (f64, f64), q: (f64, f64), r: (f64, f64), s: (f64, f64)) -> bool {
    cross_nm(nm(p.0), nm(p.1), nm(q.0), nm(q.1), nm(r.0), nm(r.1), nm(s.0), nm(s.1))
}

/// `ratsnest._crossing_point`.
fn crossing_point(p: (f64, f64), q: (f64, f64), r: (f64, f64), t: (f64, f64)) -> Option<(f64, f64)> {
    let ((x1, y1), (x2, y2), (x3, y3), (x4, y4)) = (p, q, r, t);
    let den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
    if den == 0.0 {
        return None;
    }
    let u = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den;
    Some((x1 + u * (x2 - x1), y1 + u * (y2 - y1)))
}

/// `ratsnest._cells` over the box of p and q, in Python's order.
fn cells(p: (f64, f64), q: (f64, f64)) -> impl Iterator<Item = (i64, i64)> {
    let (x0, x1) = if p.0 <= q.0 { (p.0, q.0) } else { (q.0, p.0) };
    let (y0, y1) = if p.1 <= q.1 { (p.1, q.1) } else { (q.1, p.1) };
    let (cx0, cx1) = ((x0 / CELL).floor() as i64, (x1 / CELL).floor() as i64);
    let (cy0, cy1) = ((y0 / CELL).floor() as i64, (y1 / CELL).floor() as i64);
    (cx0..=cx1).flat_map(move |cx| (cy0..=cy1).map(move |cy| (cx, cy)))
}

#[derive(Default)]
pub struct Ratsnest {
    names: HashMap<String, u32>,
    weights: HashMap<u32, f64>,
    // a differential pair's halves: their crossing counts pair_weight
    partners: HashMap<u32, u32>,
    pair_weight: f64,
    anchors: HashMap<u32, Vec<Anchor>>,
    edges: Vec<Option<Edge>>,
    free: Vec<usize>,
    by_net: HashMap<u32, Vec<usize>>,
    grid: HashMap<(i64, i64), Vec<usize>>,
}

impl Ratsnest {
    pub fn new() -> Ratsnest {
        let mut r = Ratsnest::default();
        r.intern(""); // 0: no part
        r
    }

    pub fn intern(&mut self, s: &str) -> u32 {
        if let Some(&i) = self.names.get(s) {
            return i;
        }
        let i = self.names.len() as u32;
        self.names.insert(s.to_string(), i);
        i
    }

    pub fn lookup(&self, s: &str) -> Option<u32> {
        self.names.get(s).copied()
    }

    pub fn set_weight(&mut self, net: &str, w: f64) {
        let n = self.intern(net);
        self.weights.insert(n, w);
    }

    fn weight(&self, net: u32) -> f64 {
        *self.weights.get(&net).unwrap_or(&1.0)
    }

    /// `Ratsnest(partners=, pair_weight=)`: the pairs whose own crossing
    /// counts `pair_weight` rather than the lighter net weight.
    pub fn set_partners(&mut self, pairs: &[(String, String)], pair_weight: f64) {
        self.partners.clear();
        for (a, b) in pairs {
            let (ia, ib) = (self.intern(a), self.intern(b));
            self.partners.insert(ia, ib);
        }
        self.pair_weight = pair_weight;
    }

    /// ratsnest._crossing_weight: the pair weight for a pair's two halves,
    /// else the lighter of the two nets' weights.
    fn crossing_weight(&self, a: u32, wa: f64, b: u32, wb: f64) -> f64 {
        if self.partners.get(&a) == Some(&b) {
            return self.pair_weight;
        }
        if wa < wb { wa } else { wb }
    }

    /// `Ratsnest.set_net` with the tree already worked out: `anchors` in the
    /// net's order, `edges` as `mst` returned them.
    pub fn pad_key(&mut self, part: &str, number: &str) -> u32 {
        self.intern(&format!("{part}\u{1f}{number}"))
    }

    pub fn set_net(&mut self, net: &str, anchors: &[(String, String, f64, f64)],
                   edges: &[(String, String, f64, f64, String, String, f64, f64)]) {
        let n = self.intern(net);
        if let Some(old) = self.by_net.remove(&n) {
            for id in old {
                let e = self.edges[id].take().expect("a live edge");
                for c in cells((e.a.x, e.a.y), (e.b.x, e.b.y)) {
                    if let Some(bucket) = self.grid.get_mut(&c) {
                        if let Some(pos) = bucket.iter().position(|&x| x == id) {
                            bucket.remove(pos);
                        }
                    }
                }
                self.free.push(id);
            }
        }
        let anchors: Vec<Anchor> = anchors
            .iter()
            .map(|(r, num, x, y)| Anchor { part: self.intern(r), pad: self.pad_key(r, num), x: *x, y: *y })
            .collect();
        self.anchors.insert(n, anchors);
        let mut ids = Vec::new();
        for (ar, an, ax, ay, br, bn, bx, by) in edges {
            let a = Anchor { part: self.intern(ar), pad: self.pad_key(ar, an), x: *ax, y: *ay };
            let b = Anchor { part: self.intern(br), pad: self.pad_key(br, bn), x: *bx, y: *by };
            let e = Edge { net: n, nm: (nm(*ax), nm(*ay), nm(*bx), nm(*by)), a, b };
            let id = match self.free.pop() {
                Some(id) => {
                    self.edges[id] = Some(e);
                    id
                }
                None => {
                    self.edges.push(Some(e));
                    self.edges.len() - 1
                }
            };
            let (p, q) = {
                let e = self.edges[id].as_ref().unwrap();
                ((e.a.x, e.a.y), (e.b.x, e.b.y))
            };
            for c in cells(p, q) {
                self.grid.entry(c).or_default().push(id);
            }
            ids.push(id);
        }
        self.by_net.insert(n, ids);
    }

    /// `Escapes._targets` without the quiet-net case: where the airwires of
    /// one placed pad go, as offsets from `at`; empty when it has none.
    pub fn neighbours(&self, net: u32, pad: u32, at: (f64, f64)) -> Vec<(f64, f64)> {
        let mut out = Vec::new();
        if let Some(ids) = self.by_net.get(&net) {
            for &id in ids {
                let e = self.edges[id].as_ref().unwrap();
                if e.a.pad == pad {
                    out.push((e.b.x - at.0, e.b.y - at.1));
                } else if e.b.pad == pad {
                    out.push((e.a.x - at.0, e.a.y - at.1));
                }
            }
        }
        out
    }

    /// `escapes._nearest`: the offset from `at` to the nearest placed anchor
    /// of `net` on no part in `own`, the first on a tie.
    pub fn nearest(&self, net: u32, at: (f64, f64), own: &[u32]) -> Option<(f64, f64)> {
        let mut best: Option<(f64, (f64, f64))> = None;
        for a in self.anchors.get(&net)? {
            if own.contains(&a.part) {
                continue;
            }
            let (dx, dy) = (a.x - at.0, a.y - at.1);
            let d = dx * dx + dy * dy;
            if best.is_none() || d < best.unwrap().0 {
                best = Some((d, (dx, dy)));
            }
        }
        best.map(|b| b.1)
    }

    /// `Ratsnest.leaf_costs`: (weighted crossings added, escapes crossed)
    /// for a candidate's pads (net, x, y), its own parts `own` left out.
    pub fn leaf_costs(&self, pads: &[(u32, f64, f64)], own: &[u32], depth: f64) -> (f64, i64) {
        // the leaves: each pad joined to the nearest placed anchor of its net
        let mut leaves: Vec<(u32, f64, (f64, f64), (f64, f64), u32)> = Vec::new();
        for &(net, x, y) in pads {
            let w = self.weight(net);
            if w <= 0.0 {
                continue;
            }
            let mut best: Option<(f64, &Anchor)> = None;
            if let Some(list) = self.anchors.get(&net) {
                for a in list {
                    if own.contains(&a.part) {
                        continue;
                    }
                    let (dx, dy) = (a.x - x, a.y - y);
                    let d = dx * dx + dy * dy;
                    if best.is_none() || d < best.unwrap().0 {
                        best = Some((d, a));
                    }
                }
            }
            if let Some((d, a)) = best {
                if d > 0.0 {
                    leaves.push((net, w, (x, y), (a.x, a.y), a.part));
                }
            }
        }
        let mut total = 0.0f64;
        let mut crossed = 0i64;
        let mut seen: Vec<usize> = Vec::new();
        for k in 0..leaves.len() {
            let (net, w, p, q, joined) = leaves[k];
            let pn = (nm(p.0), nm(p.1), nm(q.0), nm(q.1));
            seen.clear();
            for c in cells(p, q) {
                let Some(bucket) = self.grid.get(&c) else { continue };
                for &id in bucket {
                    let e = self.edges[id].as_ref().unwrap();
                    if e.net == net || seen.contains(&id) || own.contains(&e.a.part) || own.contains(&e.b.part) {
                        continue;
                    }
                    seen.push(id);
                    if !cross_nm(pn.0, pn.1, pn.2, pn.3, e.nm.0, e.nm.1, e.nm.2, e.nm.3) {
                        continue;
                    }
                    let we = self.weight(e.net);
                    total += self.crossing_weight(net, w, e.net, we);
                    if joined != 0 && (e.a.part == joined || e.b.part == joined) && !(e.a.part == joined && e.b.part == joined) {
                        if let Some(at) = crossing_point(p, q, (e.a.x, e.a.y), (e.b.x, e.b.y)) {
                            let mut m = hypot(at.0 - q.0, at.1 - q.1);
                            for v in [&e.a, &e.b] {
                                if v.part == joined {
                                    let h = hypot(at.0 - v.x, at.1 - v.y);
                                    if h < m {
                                        m = h;
                                    }
                                }
                            }
                            if m <= depth {
                                crossed += 1;
                            }
                        }
                    }
                }
            }
            for &(net2, w2, p2, q2, _) in &leaves[k + 1..] {
                if net2 != net && segments_cross(p, q, p2, q2) {
                    total += self.crossing_weight(net, w, net2, w2);
                }
            }
        }
        (total, crossed)
    }
}
