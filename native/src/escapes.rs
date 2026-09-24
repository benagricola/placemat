//! The placed pads' escape corridors, mirrored from
//! `placemat.escapes.Escapes` for the question every candidate asks:
//! `closed` - how many pads a candidate at (dx, dy) would close toward what
//! they join, and how many it would wall off (its neighbours' pads and its
//! own). Python builds the corridors, judges which are open, and hands both
//! over as they change; this answers the question as `Escapes.closed` does.
//! The answer is two counts, so the order corridors are visited in does not
//! matter, only which are closed.

use crate::board::B;
use crate::geometry::polys_overlap;
use crate::ratsnest::Ratsnest;
use std::collections::{HashMap, HashSet};

type Point = (f64, f64);
const CELL: f64 = 2.0; // escapes._CELL

fn cells(b: &B) -> impl Iterator<Item = (i64, i64)> {
    let (cx0, cx1) = ((b.l / CELL).floor() as i64, (b.r / CELL).floor() as i64);
    let (cy0, cy1) = ((b.t / CELL).floor() as i64, (b.b / CELL).floor() as i64);
    (cx0..=cx1).flat_map(move |cx| (cy0..=cy1).map(move |cy| (cx, cy)))
}

/// A corridor or a via spot, as `escapes.Corridor` has it.
#[derive(Clone)]
pub struct Corr {
    pub part: u32,
    pub pad: u32,
    pub net: u32,
    pub layers: u32,
    pub poly: Vec<Point>,
    pub bbox: B,
    pub dir: (f64, f64),
    pub via: bool,
    pub open: bool,
    pub centre: (f64, f64), // the pad's centre: occ.pad_location
}

/// Copper that can close a corridor: a pad, a track, a via.
#[derive(Clone)]
pub struct Metal {
    pub owner: u32,
    pub net: u32,
    pub layers: u32,
    pub poly: Vec<Point>,
    pub bbox: B,
}

#[derive(Default)]
pub struct Escapes {
    corrs: Vec<Option<Corr>>,
    by_part: HashMap<u32, Vec<usize>>,
    by_pad: HashMap<u32, Vec<usize>>,
    cgrid: HashMap<(i64, i64), Vec<usize>>,
    metal: Vec<Option<Metal>>,
    metal_of: HashMap<u32, Vec<usize>>,
    mgrid: HashMap<(i64, i64), Vec<usize>>,
    pub quiet: HashSet<u32>,
}

/// A candidate's own pads and corridors, turned for one turn at the origin.
pub struct Turn {
    pub pads: Vec<Metal>,
    pub groups: Vec<(Vec<Corr>, (f64, f64))>,
}

fn moved(b: &B, dx: f64, dy: f64) -> B {
    B { l: b.l + dx, t: b.t + dy, r: b.r + dx, b: b.b + dy }
}

fn shifted(poly: &[Point], dx: f64, dy: f64) -> Vec<Point> {
    poly.iter().map(|&(x, y)| (x + dx, y + dy)).collect()
}

fn toward(c: &Corr, targets: Option<&[(f64, f64)]>) -> bool {
    match targets {
        None => true,
        Some(ts) => c.via || ts.iter().any(|&(dx, dy)| c.dir.0 * dx + c.dir.1 * dy > 1e-9),
    }
}

impl Escapes {
    /// Replace one part's corridors; their ids, in order.
    pub fn set_corridors(&mut self, part: u32, corrs: Vec<Corr>) -> Vec<usize> {
        if let Some(old) = self.by_part.remove(&part) {
            for id in old {
                let c = self.corrs[id].take().unwrap();
                for cell in cells(&c.bbox) {
                    if let Some(v) = self.cgrid.get_mut(&cell) {
                        v.retain(|&x| x != id);
                    }
                }
                if let Some(v) = self.by_pad.get_mut(&c.pad) {
                    v.retain(|&x| x != id);
                }
            }
        }
        let mut ids = Vec::new();
        for c in corrs {
            let id = self.corrs.len();
            for cell in cells(&c.bbox) {
                self.cgrid.entry(cell).or_default().push(id);
            }
            self.by_pad.entry(c.pad).or_default().push(id);
            self.corrs.push(Some(c));
            ids.push(id);
        }
        self.by_part.insert(part, ids.clone());
        ids
    }

    pub fn set_open(&mut self, id: usize, open: bool) {
        if let Some(c) = self.corrs[id].as_mut() {
            c.open = open;
        }
    }

    /// Replace the copper kept under `key` (a part's pads, or the planned copper).
    pub fn set_metal(&mut self, key: u32, metal: Vec<Metal>) {
        if let Some(old) = self.metal_of.remove(&key) {
            for id in old {
                let m = self.metal[id].take().unwrap();
                for cell in cells(&m.bbox) {
                    if let Some(v) = self.mgrid.get_mut(&cell) {
                        v.retain(|&x| x != id);
                    }
                }
            }
        }
        self.add_metal(key, metal);
    }

    pub fn add_metal(&mut self, key: u32, metal: Vec<Metal>) {
        for m in metal {
            let id = self.metal.len();
            for cell in cells(&m.bbox) {
                self.mgrid.entry(cell).or_default().push(id);
            }
            self.metal.push(Some(m));
            self.metal_of.entry(key).or_default().push(id);
        }
    }

    fn closes(s_net: u32, s_owner: u32, s_layers: u32, s_box: &B, s_poly: &[Point], c: &Corr) -> bool {
        s_net != c.net && s_owner != c.part && (s_layers & c.layers) != 0 && s_box.overlaps(&c.bbox)
            && polys_overlap(s_poly, &c.poly)
    }

    /// `Escapes.closed` less the crossed escapes (the ratsnest's leaf search
    /// counts those): (closed, walled).
    pub fn closed(&self, rn: &Ratsnest, turn: &Turn, dx: f64, dy: f64, own: &[u32]) -> (i64, i64) {
        let mut closed = 0i64;
        let mut walled = 0i64;
        // its copper against the corridors of what is placed
        let mut taken: HashMap<u32, HashSet<usize>> = HashMap::new();
        for s in &turn.pads {
            let sb = moved(&s.bbox, dx, dy);
            let mut poly: Option<Vec<Point>> = None;
            let mut seen: HashSet<usize> = HashSet::new();
            for cell in cells(&sb) {
                let Some(ids) = self.cgrid.get(&cell) else { continue };
                for &id in ids {
                    if !seen.insert(id) {
                        continue;
                    }
                    let c = self.corrs[id].as_ref().unwrap();
                    if own.contains(&c.part) || !c.open {
                        continue;
                    }
                    if s.net == c.net || s.owner == c.part || (s.layers & c.layers) == 0 || !sb.overlaps(&c.bbox) {
                        continue;
                    }
                    let p = poly.get_or_insert_with(|| shifted(&s.poly, dx, dy));
                    if Self::closes(s.net, s.owner, s.layers, &sb, p, c) {
                        taken.entry(c.pad).or_default().insert(id);
                    }
                }
            }
        }
        for (pad, gone) in &taken {
            let ids = &self.by_pad[pad];
            let before: Vec<&Corr> = ids.iter().map(|&i| self.corrs[i].as_ref().unwrap()).filter(|c| c.open).collect();
            let after: Vec<&Corr> = ids.iter().filter(|i| !gone.contains(i))
                .map(|&i| self.corrs[i].as_ref().unwrap()).filter(|c| c.open).collect();
            if !before.is_empty() && after.is_empty() {
                walled += 1;
                continue;
            }
            let c0 = self.corrs[ids[0]].as_ref().unwrap();
            let targets: Option<Vec<(f64, f64)>> = if self.quiet.contains(&c0.net) {
                None
            } else {
                let t = rn.neighbours(c0.net, c0.pad, c0.centre);
                if t.is_empty() { None } else { Some(t) }
            };
            let t = targets.as_deref();
            if before.iter().any(|c| toward(c, t)) && !after.iter().any(|c| toward(c, t)) {
                closed += 1;
            }
        }
        // its own pads against what is placed
        for (group, centre) in &turn.groups {
            let c0 = &group[0];
            let mut open: Vec<&Corr> = Vec::new();
            for c in group {
                let cb = moved(&c.bbox, dx, dy);
                let mut poly: Option<Vec<Point>> = None;
                let mut shut = false;
                let mut seen: HashSet<usize> = HashSet::new();
                'cells: for cell in cells(&cb) {
                    let Some(ids) = self.mgrid.get(&cell) else { continue };
                    for &id in ids {
                        if !seen.insert(id) {
                            continue;
                        }
                        let m = self.metal[id].as_ref().unwrap();
                        if own.contains(&m.owner) || m.net == c0.net || (m.layers & c.layers) == 0 || !m.bbox.overlaps(&cb) {
                            continue;
                        }
                        let p = poly.get_or_insert_with(|| shifted(&c.poly, dx, dy));
                        if polys_overlap(&m.poly, p) {
                            shut = true;
                            break 'cells;
                        }
                    }
                }
                if !shut {
                    open.push(c);
                }
            }
            if open.is_empty() {
                walled += 1;
                continue;
            }
            if self.quiet.contains(&c0.net) {
                continue;
            }
            if let Some(near) = rn.nearest(c0.net, (centre.0 + dx, centre.1 + dy), own) {
                if !open.iter().any(|c| toward(c, Some(&[near]))) {
                    closed += 1;
                }
            }
        }
        (closed, walled)
    }
}
