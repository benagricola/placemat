//! Sparse exact MST changes for the placement objective. A lifted net's
//! unjoined tree is the certificate; only edges incident to added pads are
//! offered alongside it. Scratch buffers are retained between candidates.
use crate::ratsnest::{nm, segments_cross};
use std::collections::{HashMap, HashSet};

pub type Node = (f64, f64, String, String);
pub type Pair = (usize, usize);
// Tags rank the full (nm x, nm y, ref, pad) endpoint key; their order
// is exactly the endpoint tie order, with a smaller sortable edge record.
type OrderedEdge = (i64, usize, usize, usize, usize);

pub struct Snapshot {
    pub name: String,
    pub kind: usize,
    pub partner: Option<String>,
    pub nodes: Vec<Node>,
    pub edges: Vec<Pair>,
}

pub struct TreeDelta {
    pub nodes: Vec<Node>,
    pub rest: usize,
    pub old: Vec<Pair>,
    pub tree: Vec<Pair>,
    pub added: Vec<Pair>,
    pub dropped: Vec<Pair>,
    old_index: HashMap<Pair, usize>,
    retained: Vec<bool>,
    candidates: Vec<OrderedEdge>,
    order: Vec<usize>,
    tags: Vec<usize>,
    parent: Vec<usize>,
    points: Vec<(i64, i64)>,
    old_length: f64,
    old_order: Vec<(i64, usize, usize)>,
}

/// Preserve MST's `floor(CPython_hypot(dx, dy) + .5)` weight exactly.
/// Integer-nm inputs cannot underflow. Below 2^50, ordinary products,
/// their positive sum and sqrt accumulate less than four ulps of error
/// relative to compensated hypot (each rounded operation has relative
/// error at most 2^-53). Eight ulps also cover the final +.5 rounding.
/// Only use that approximation when both answers must round identically;
/// near halves or large magnitudes use the authoritative arithmetic.
fn edge_weight(a: (i64, i64), b: (i64, i64)) -> i64 {
    let dx = (a.0 as i128 - b.0 as i128) as f64;
    let dy = (a.1 as i128 - b.1 as i128) as f64;
    let quick = (dx * dx + dy * dy).sqrt();
    let ulp = f64::from_bits(quick.to_bits() + 1) - quick;
    let h = if quick < (1u64 << 50) as f64 && (quick.fract() - 0.5).abs() > 8.0 * ulp {
        quick
    } else {
        crate::exact::hypot(dx, dy)
    };
    (h + 0.5).floor().max(1.0) as i64
}

// Leave room for subtracting two nm coordinates without i64 overflow.
fn point_valid(x: f64, y: f64) -> bool {
    let limit = i64::MAX as f64 / 4.0 / 1_000_000.0;
    x.is_finite() && y.is_finite() && x.abs() <= limit && y.abs() <= limit
}

/// Count each crossed escape pair once, as Ratsnest.crossed_pair_list does.
/// Crossings use nm predicates, but proximity uses the raw crossing point.
fn escaped(a: &[Node], ae: &[Pair], b: &[Node], be: &[Pair], depth: f64) -> i64 {
    let mut count = 0;
    for &(i, j) in ae {
        for &(k, l) in be {
            let (p, q, r, t) = (&a[i], &a[j], &b[k], &b[l]);
            if !segments_cross((p.0, p.1), (q.0, q.1), (r.0, r.1), (t.0, t.1)) {
                continue;
            }
            let den = (p.0 - q.0) * (r.1 - t.1) - (p.1 - q.1) * (r.0 - t.0);
            if den == 0.0 {
                continue;
            }
            let u = ((p.0 - r.0) * (r.1 - t.1) - (p.1 - r.1) * (r.0 - t.0)) / den;
            let at = (p.0 + u * (q.0 - p.0), p.1 + u * (q.1 - p.1));
            if [&p.2, &q.2].iter().any(|&name| {
                !name.is_empty()
                    && (name == &r.2 || name == &t.2)
                    && !(name == &p.2 && name == &q.2)
                    && !(name == &r.2 && name == &t.2)
                    && [p, q, r, t].iter().any(|v| {
                        &v.2 == name && crate::exact::hypot(at.0 - v.0, at.1 - v.1) <= depth
                    })
            }) {
                count += 1;
            }
        }
    }
    count
}

fn find_root(parent: &mut [usize], mut i: usize) -> usize {
    while parent[i] != i {
        parent[i] = parent[parent[i]];
        i = parent[i];
    }
    i
}

impl TreeDelta {
    fn validate(rest: &[Node], old: &[Pair]) -> Result<(), String> {
        if old.len() != rest.len().saturating_sub(1) {
            return Err("NativeDelta requires an unjoined complete rest tree".into());
        }
        let mut parent: Vec<usize> = (0..rest.len()).collect();
        for &(i, j) in old {
            if i >= rest.len() || j >= rest.len() || i == j {
                return Err("NativeDelta rest edge endpoint invalid".into());
            }
            let (a, b) = (find_root(&mut parent, i), find_root(&mut parent, j));
            if a == b {
                return Err("NativeDelta rest tree must be connected and acyclic".into());
            }
            parent[a] = b;
        }
        Ok(())
    }

    pub fn new(rest: &[Node], old: &[Pair], added: &[Node]) -> Result<Self, String> {
        Self::validate(rest, old)?;
        if rest.iter().chain(added).any(|p| !point_valid(p.0, p.1)) {
            return Err("NativeDelta anchors must be finite and representable in nm".into());
        }
        let mut nodes = rest.to_vec();
        nodes.extend_from_slice(added);
        let n = nodes.len();
        let mut old_order: Vec<_> = old
            .iter()
            .map(|&(i, j)| {
                let a = &nodes[i];
                let b = &nodes[j];
                let weight = edge_weight((nm(a.0), nm(a.1)), (nm(b.0), nm(b.1)));
                (weight, i, j)
            })
            .collect();
        old_order.sort_unstable_by_key(|&(weight, i, j)| {
            let key = |k: usize| (nm(nodes[k].0), nm(nodes[k].1), &nodes[k].2, &nodes[k].3);
            let (a, b) = if key(i) <= key(j) {
                (key(i), key(j))
            } else {
                (key(j), key(i))
            };
            (weight, a, b, i, j)
        });
        Ok(Self {
            nodes: nodes.clone(),
            rest: rest.len(),
            old: old.to_vec(),
            tree: Vec::with_capacity(n),
            added: Vec::with_capacity(n),
            dropped: Vec::with_capacity(old.len()),
            old_index: old
                .iter()
                .enumerate()
                .map(|(index, &(i, j))| ((i.min(j), i.max(j)), index))
                .collect(),
            retained: vec![false; old.len()],
            candidates: Vec::with_capacity(old.len() + added.len() * n),
            order: (0..n).collect(),
            tags: vec![0; n],
            parent: vec![0; n],
            points: nodes.iter().map(|p| (nm(p.0), nm(p.1))).collect(),
            old_length: length(rest, old),
            old_order,
        })
    }

    fn offer(&mut self, i: usize, j: usize) {
        let (i, j) = if i <= j { (i, j) } else { (j, i) };
        let a = self.points[i];
        let b = self.points[j];
        let weight = edge_weight(a, b);
        let (a, b) = if self.tags[i] <= self.tags[j] {
            (self.tags[i], self.tags[j])
        } else {
            (self.tags[j], self.tags[i])
        };
        self.candidates.push((weight, a, b, i, j));
    }

    pub fn solve(&mut self, x: f64, y: f64, added: &[Node]) -> f64 {
        for (i, p) in added.iter().enumerate() {
            self.nodes[self.rest + i].0 = p.0 + x;
            self.nodes[self.rest + i].1 = p.1 + y;
            self.points[self.rest + i] = (nm(p.0 + x), nm(p.1 + y));
        }
        let nodes = &self.nodes;
        let points = &self.points;
        self.order.sort_unstable_by(|&i, &j| {
            (points[i].0, points[i].1, &nodes[i].2, &nodes[i].3).cmp(&(
                points[j].0,
                points[j].1,
                &nodes[j].2,
                &nodes[j].3,
            ))
        });
        for (tag, &i) in self.order.iter().enumerate() {
            self.tags[i] = tag;
        }
        for i in 0..self.parent.len() {
            self.parent[i] = i;
        }
        self.candidates.clear();
        // The rest tree plus each added pad's nearest prior endpoint is
        // a connected certificate. Kruskal is complete by its largest
        // weight, so strictly heavier incident edges can never enter the
        // MST. Keep equal-weight edges for deterministic tie decisions.
        let mut bound = self.old_order.last().map_or(0, |e| e.0);
        for j in self.rest..self.nodes.len() {
            let start = self.candidates.len();
            for i in 0..j {
                self.offer(i, j);
            }
            if let Some(nearest) = self.candidates[start..].iter().map(|e| e.0).min() {
                bound = bound.max(nearest);
            }
        }
        self.candidates.retain(|e| e.0 <= bound);
        self.candidates.sort_unstable();
        self.tree.clear();
        self.added.clear();
        self.dropped.clear();
        self.retained.fill(false);
        // Unchanged edges keep their relative total order even as added
        // endpoint tags interleave. Merge their cached order with new edges.
        let (mut old, mut new) = (0, 0);
        while old < self.old_order.len() || new < self.candidates.len() {
            let prior = self.old_order.get(old).map(|&(weight, i, j)| {
                let (a, b) = if self.tags[i] <= self.tags[j] {
                    (self.tags[i], self.tags[j])
                } else {
                    (self.tags[j], self.tags[i])
                };
                (weight, a, b, i, j)
            });
            let next = self.candidates.get(new).copied();
            let edge = match (prior, next) {
                (Some(a), Some(b)) if a <= b => {
                    old += 1;
                    a
                }
                (_, Some(b)) => {
                    new += 1;
                    b
                }
                (Some(a), None) => {
                    old += 1;
                    a
                }
                (None, None) => break,
            };
            let (_, _, _, i, j) = edge;
            let (a, b) = (
                find_root(&mut self.parent, i),
                find_root(&mut self.parent, j),
            );
            if a != b {
                self.parent[a] = b;
                self.tree.push((i, j));
                if let Some(&index) = self.old_index.get(&(i.min(j), i.max(j))) {
                    self.retained[index] = true;
                } else {
                    self.added.push((i, j));
                }
                if self.tree.len() == self.nodes.len().saturating_sub(1) {
                    break;
                }
            }
        }
        self.dropped.extend(
            self.old
                .iter()
                .enumerate()
                .filter_map(|(i, &edge)| (!self.retained[i]).then_some(edge)),
        );
        length(&self.nodes, &self.tree) - self.old_length
    }
}

fn length(nodes: &[Node], edges: &[Pair]) -> f64 {
    let mut sum = crate::exact::PySum::new();
    for &(i, j) in edges {
        sum.add(crate::exact::hypot(
            nodes[i].0 - nodes[j].0,
            nodes[i].1 - nodes[j].1,
        ));
    }
    sum.total()
}

fn crossed(a: &[Node], ae: &[Pair], b: &[Node], be: &[Pair]) -> usize {
    let mut count = 0;
    for &(i, j) in ae {
        for &(k, l) in be {
            if segments_cross(
                (a[i].0, a[i].1),
                (a[j].0, a[j].1),
                (b[k].0, b[k].1),
                (b[l].0, b[l].1),
            ) {
                count += 1;
            }
        }
    }
    count
}

struct Touched {
    index: usize,
    added: Vec<Node>,
    tree: TreeDelta,
    evaluated: Vec<Node>,
    anchor_order: Vec<usize>,
}

fn anchor_order(nodes: &[Node]) -> Vec<usize> {
    let mut order: Vec<_> = (0..nodes.len()).collect();
    // Python's candidate ratsnest sorts by (ref, number), stably. Neither
    // nm endpoint order nor the MST edge order defines a nearest-target tie.
    order.sort_by(|&a, &b| (&nodes[a].2, &nodes[a].3).cmp(&(&nodes[b].2, &nodes[b].3)));
    order
}

struct AnchorAffine {
    a: f64, b: f64, c: f64, d: f64,
    tx: f64, ty: f64,
    source: (f64, f64),
}

impl AnchorAffine {
    fn from_record(values: &[f64]) -> Self {
        Self { a: values[0], b: values[1], c: values[2], d: values[3],
               tx: values[4], ty: values[5], source: (values[6], values[7]) }
    }

    fn at(&self, location: (f64, f64)) -> (f64, f64) {
        // Association matches Transform.apply after pose_transform appended
        // the candidate translation. Never fold source terms into tx/ty.
        (crate::exact::clean9(self.a*self.source.0+self.b*self.source.1+(self.tx+location.0)),
         crate::exact::clean9(self.c*self.source.0+self.d*self.source.1+(self.ty+location.1)))
    }
}

struct AnchorPose {
    member: Option<AnchorAffine>,
    read: AnchorAffine,
}

impl AnchorPose {
    fn at(&self, location: (f64, f64)) -> (f64, f64) {
        self.read.at(self.member.as_ref().map_or(location, |member| member.at(location)))
    }
}

pub struct Delta {
    snapshots: Vec<Snapshot>,
    turns: Vec<Vec<Touched>>,
    prices: Vec<Vec<f64>>,
    signal: HashSet<String>,
    impedance: f64,
    affines: Option<Vec<Vec<Vec<AnchorPose>>>>,
    net_index: HashMap<String, usize>,
    anchor_orders: Vec<Vec<usize>>,
}

impl Delta {
    pub fn new(
        mut snapshots: Vec<Snapshot>,
        anchors: Vec<Vec<(String, String, String, f64, f64)>>,
        own: &[String],
        signal: Vec<String>,
        settings: (f64, f64, f64, f64, f64),
    ) -> Result<Self, String> {
        let (crossing, impedance, pair_net, plane, pair) = settings;
        if snapshots.iter().any(|s| s.kind > 3) {
            return Err("NativeDelta net kind must be in 0..3".into());
        }
        if [crossing, impedance, pair_net, plane, pair]
            .iter()
            .any(|v| !v.is_finite() || *v < 0.0)
        {
            return Err("NativeDelta settings must be finite and nonnegative".into());
        }
        if snapshots
            .iter()
            .flat_map(|s| &s.nodes)
            .any(|p| !point_valid(p.0, p.1))
        {
            return Err("NativeDelta anchors must be finite and representable in nm".into());
        }
        if anchors.iter().flatten().any(|p| !point_valid(p.3, p.4)) {
            return Err("NativeDelta anchors must be finite and representable in nm".into());
        }
        if snapshots.iter().flat_map(|s| &s.nodes).any(|p| own.contains(&p.2)) {
            return Err("NativeDelta requires the item to be lifted on every net".into());
        }
        for snapshot in &snapshots {
            if snapshot.kind != 3 || plane != 0.0 {
                TreeDelta::validate(&snapshot.nodes, &snapshot.edges)?;
            }
        }
        let mut turns = Vec::new();
        for turn in anchors {
            let mut nets: Vec<(String, Vec<Node>)> = Vec::new();
            for (net, reference, number, x, y) in turn {
                let index = if let Some(i) = nets.iter().position(|v| v.0 == net) {
                    i
                } else {
                    nets.push((net.clone(), Vec::new()));
                    nets.len() - 1
                };
                nets[index].1.push((x, y, reference, number));
            }
            let mut touched = Vec::new();
            for (net, added) in nets {
                let index = if let Some(i) = snapshots.iter().position(|s| s.name == net) {
                    i
                } else {
                    snapshots.push(Snapshot {
                        name: net.clone(),
                        kind: 0,
                        partner: None,
                        nodes: Vec::new(),
                        edges: Vec::new(),
                    });
                    snapshots.len() - 1
                };
                let snapshot = &snapshots[index];
                if snapshot.kind == 3 && plane == 0.0 {
                    continue;
                }
                let tree = TreeDelta::new(&snapshot.nodes, &snapshot.edges, &added)?;
                let evaluated = added.clone();
                let anchor_order = anchor_order(&tree.nodes);
                touched.push(Touched { index, added, tree, evaluated, anchor_order });
            }
            turns.push(touched);
        }
        let prices = snapshots
            .iter()
            .map(|a| {
                snapshots
                    .iter()
                    .map(|b| {
                        if a.kind == 3 || b.kind == 3 {
                            crossing * plane
                        } else if a.partner.as_ref() == Some(&b.name) {
                            pair
                        } else {
                            crossing
                                * [1.0, impedance, pair_net, plane][a.kind]
                                    .max([1.0, impedance, pair_net, plane][b.kind])
                        }
                    })
                    .collect()
            })
            .collect();
        let net_index = snapshots.iter().enumerate().map(|(i, s)| (s.name.clone(), i)).collect();
        let anchor_orders = snapshots.iter().map(|s| anchor_order(&s.nodes)).collect();
        let delta = Self {
            snapshots,
            turns,
            prices,
            signal: signal.into_iter().collect(),
            impedance,
            affines: None,
            net_index,
            anchor_orders,
        };
        Ok(delta)
    }

    pub fn configure_affines(&mut self, turns: Vec<Vec<(String, String, String, Vec<f64>)>>) -> Result<(), String> {
        if turns.len() != self.turns.len() {
            return Err("NativeDelta affine turn count differs".into());
        }
        let mut prepared = Vec::new();
        for (turn, touched) in turns.into_iter().zip(&self.turns) {
            let mut map = HashMap::new();
            for (net, reference, number, values) in turn {
                if values.len() != 17 || values.iter().any(|v| !v.is_finite() || v.abs() > 1e9)
                    || (values[0] != 0.0 && values[0] != 1.0) {
                    return Err("NativeDelta affine record invalid".into());
                }
                let pose = AnchorPose {
                    member: if values[0] == 1.0 { Some(AnchorAffine::from_record(&values[1..9])) } else { None },
                    read: AnchorAffine::from_record(&values[9..17]),
                };
                if map.insert((net, reference, number), pose).is_some() {
                    return Err("NativeDelta duplicate affine anchor".into());
                }
            }
            let mut aligned = Vec::new();
            for t in touched {
                let mut nodes = Vec::new();
                for p in &t.added {
                    nodes.push(map.remove(&(self.snapshots[t.index].name.clone(), p.2.clone(), p.3.clone()))
                        .ok_or("NativeDelta missing affine anchor")?);
                }
                aligned.push(nodes);
            }
            prepared.push(aligned);
        }
        self.affines = Some(prepared);
        Ok(())
    }

    fn crossing_change(&self, touched: &[Touched]) -> f64 {
        let mut sum = 0.0;
        for (k, a) in touched.iter().enumerate() {
            let tree = &a.tree;
            for (i, other) in self.snapshots.iter().enumerate() {
                if touched.iter().any(|t| t.index == i) {
                    continue;
                }
                let price = self.prices[a.index][i];
                if price != 0.0 {
                    sum += price
                        * (crossed(&tree.nodes, &tree.added, &other.nodes, &other.edges) as f64
                            - crossed(&tree.nodes, &tree.dropped, &other.nodes, &other.edges)
                                as f64);
                }
            }
            for b in &touched[k + 1..] {
                let price = self.prices[a.index][b.index];
                if price == 0.0 {
                    continue;
                }
                let old = &self.snapshots[a.index];
                // F(A',B')-F(A,B) = F(added_A-dropped_A,B')
                // + F(A,added_B-dropped_B). Joint changes counted once.
                sum += price
                    * (crossed(&tree.nodes, &tree.added, &b.tree.nodes, &b.tree.tree) as f64
                        - crossed(&tree.nodes, &tree.dropped, &b.tree.nodes, &b.tree.tree) as f64
                        + crossed(&old.nodes, &old.edges, &b.tree.nodes, &b.tree.added) as f64
                        - crossed(&old.nodes, &old.edges, &b.tree.nodes, &b.tree.dropped) as f64);
            }
        }
        sum
    }

    pub fn wire_cross(&mut self, x: f64, y: f64, turn: usize) -> Result<(f64, f64), String> {
        if !point_valid(x, y) {
            return Err("NativeDelta candidate must be finite and representable in nm".into());
        }
        if turn >= self.turns.len() {
            return Err("NativeDelta turn index out of range".into());
        }
        if self.turns[turn]
            .iter()
            .flat_map(|t| &t.added)
            .any(|p| !point_valid(p.0 + x, p.1 + y))
        {
            return Err(
                "NativeDelta translated anchors must be finite and representable in nm".into(),
            );
        }
        let mut wire = 0.0;
        for (index, touched) in self.turns[turn].iter_mut().enumerate() {
            let change = if let Some(affines) = &self.affines {
                for (p, pose) in touched.evaluated.iter_mut().zip(&affines[turn][index]) {
                    (p.0, p.1) = pose.at((x, y));
                    if !point_valid(p.0, p.1) {
                        return Err("NativeDelta affine anchor exceeds representable nm".into());
                    }
                }
                touched.tree.solve(0.0, 0.0, &touched.evaluated)
            } else { touched.tree.solve(x, y, &touched.added) };
            let net = &self.snapshots[touched.index];
            if self.signal.contains(&net.name) {
                wire += change * if net.kind == 1 { self.impedance } else { 1.0 };
            }
        }
        Ok((wire, self.crossing_change(&self.turns[turn])))
    }

    /// After this turn's wire_cross: whether a candidate anchor on `net` stands within squared distance `d2` of
    /// `at`, ties included and a hair beyond (a bound, not a judgement: the anchors' nm rounding is inside it).
    pub fn candidate_within(&self, turn: usize, net: &str, at: (f64, f64), d2: f64, x: f64, y: f64) -> bool {
        let Some(&index) = self.net_index.get(net) else { return false; };
        let Some(touched) = self.turns.get(turn).and_then(|t| t.iter().find(|t| t.index == index)) else {
            return false;
        };
        let limit = d2 * (1.0 + 1e-9) + 1e-9;
        let near = |p: (f64, f64)| crate::exact::square(p.0 - at.0) + crate::exact::square(p.1 - at.1) <= limit;
        if self.affines.is_some() {
            touched.evaluated.iter().any(|p| near((p.0, p.1)))
        } else {
            touched.added.iter().any(|p| near((p.0 + x, p.1 + y)))
        }
    }

    /// Query after this turn's wire_cross: retain raw CPython squared-distance
    /// and stable ref/pad tie semantics. Prepared escapes call directly in Rust
    /// after one evaluation, without Python anchor reconstruction/callbacks.
    pub fn aim(&self, turn: usize, net: &str, owner: &str, number: &str,
               at: (f64, f64)) -> Result<Option<(f64, f64)>, String> {
        if turn >= self.turns.len() || !point_valid(at.0, at.1) {
            return Err("NativeDelta aim turn/centre invalid".into());
        }
        let Some(&index) = self.net_index.get(net) else { return Ok(None); };
        // A quiet net never asks for a directional target in _verdict.
        if !self.signal.contains(net) { return Ok(None); }
        let (nodes, order) = if let Some(touched) = self.turns[turn].iter().find(|t| t.index == index) {
            (&touched.tree.nodes, &touched.anchor_order)
        } else {
            (&self.snapshots[index].nodes, &self.anchor_orders[index])
        };
        let mut best = None;
        for &index in order {
            let p = &nodes[index];
            if p.2 == owner && p.3 == number { continue; }
            let direction = (p.0 - at.0, p.1 - at.1);
            let distance = crate::exact::square(direction.0) + crate::exact::square(direction.1);
            if best.is_none_or(|(d, _)| distance < d) { best = Some((distance, direction)); }
        }
        Ok(best.map(|(_, direction)| direction))
    }

    /// After wire_cross solved this turn: the same signed bilinear expansion
    /// as crossings, with the raw near-shared-part escape predicate.
    pub fn escape_cross(&self, turn: usize, depth: f64) -> Result<i64, String> {
        if turn >= self.turns.len() || !depth.is_finite() || depth < 0.0 {
            return Err("NativeDelta escape turn/depth invalid".into());
        }
        let touched = &self.turns[turn];
        let mut count = 0;
        for (k, a) in touched.iter().enumerate() {
            let tree = &a.tree;
            for (i, other) in self.snapshots.iter().enumerate() {
                if touched.iter().any(|t| t.index == i) {
                    continue;
                }
                count += escaped(&tree.nodes, &tree.added, &other.nodes, &other.edges, depth)
                    - escaped(
                        &tree.nodes,
                        &tree.dropped,
                        &other.nodes,
                        &other.edges,
                        depth,
                    );
            }
            for b in &touched[k + 1..] {
                let old = &self.snapshots[a.index];
                count += escaped(&tree.nodes, &tree.added, &b.tree.nodes, &b.tree.tree, depth)
                    - escaped(
                        &tree.nodes,
                        &tree.dropped,
                        &b.tree.nodes,
                        &b.tree.tree,
                        depth,
                    )
                    + escaped(&old.nodes, &old.edges, &b.tree.nodes, &b.tree.added, depth)
                    - escaped(
                        &old.nodes,
                        &old.edges,
                        &b.tree.nodes,
                        &b.tree.dropped,
                        depth,
                    );
            }
        }
        Ok(count)
    }
}

#[cfg(test)]
mod tests {
    use super::edge_weight;

    fn expected(x: i64, y: i64) -> i64 {
        (crate::exact::hypot(x as f64, y as f64) + 0.5)
            .floor()
            .max(1.0) as i64
    }

    #[test]
    fn guarded_weights_match_authoritative_halves_and_scales() {
        // x = t^2, y = t puts sqrt(x^2+y^2) just below x+.5.
        // At large t CPython's norm itself rounds to the half.
        for t in [1i64, 2, 3, 10, 100, 1000, 10_000, 1_000_000, 10_000_000] {
            for offset in -2..=2 {
                let (x, y) = (t * t + offset, t);
                assert_eq!(edge_weight((x, y), (0, 0)), expected(x, y));
            }
        }
        let mut state = 13u64;
        for bits in 1..=60 {
            let mask = (1u64 << bits) - 1;
            for _ in 0..10_000 {
                state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
                let x = (state & mask) as i64;
                state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
                let y = (state & mask) as i64;
                assert_eq!(edge_weight((x, -y), (0, 0)), expected(x, y));
            }
        }
    }
}
