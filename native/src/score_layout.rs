//! The declared-link, fitted-area and RUDY terms of a lifted candidate.
//! All geometry is prepared per turn; candidates reuse cell and sum buffers.
use crate::exact;
use std::collections::{BTreeMap, HashMap};

pub type Bounds = (f64, f64, f64, f64);
pub type Link = (f64, f64, bool, f64, f64, bool, f64, Option<f64>);

// CPython math.fsum's non-overlapping partials and final half-even fix.
// Grid demands are finite, nonnegative numbers; no overflow is admitted.
#[derive(Default)]
struct Sum {
    partials: Vec<f64>,
}
impl Sum {
    fn clear(&mut self) {
        self.partials.clear();
    }
    fn add(&mut self, mut x: f64) {
        let mut keep = 0;
        for index in 0..self.partials.len() {
            let mut y = self.partials[index];
            if x.abs() < y.abs() {
                std::mem::swap(&mut x, &mut y);
            }
            let hi = x + y;
            let lo = y - (hi - x);
            if lo != 0.0 {
                self.partials[keep] = lo;
                keep += 1;
            }
            x = hi;
        }
        self.partials.truncate(keep);
        if x != 0.0 {
            self.partials.push(x);
        }
    }
    fn total(&self) -> f64 {
        let mut n = self.partials.len();
        if n == 0 {
            return 0.0;
        }
        n -= 1;
        let mut hi = self.partials[n];
        let mut lo = 0.0;
        while n > 0 {
            let x = hi;
            n -= 1;
            let y = self.partials[n];
            hi = x + y;
            lo = y - (hi - x);
            if lo != 0.0 {
                break;
            }
        }
        if n > 0
            && ((lo < 0.0 && self.partials[n - 1] < 0.0)
                || (lo > 0.0 && self.partials[n - 1] > 0.0))
        {
            let y = lo * 2.0;
            let x = hi + y;
            if y == x - hi {
                hi = x;
            }
        }
        hi
    }
}

fn union(a: Bounds, b: Bounds) -> Bounds {
    (a.0.min(b.0), a.1.min(b.1), a.2.max(b.2), a.3.max(b.3))
}
fn shifted(b: Bounds, x: f64, y: f64) -> Bounds {
    (
        exact::clean9(b.0 + x),
        exact::clean9(b.1 + y),
        exact::clean9(b.2 + x),
        exact::clean9(b.3 + y),
    )
}
fn finite_box(b: Bounds) -> bool {
    [b.0, b.1, b.2, b.3].iter().all(|v| v.is_finite()) && b.0 <= b.2 && b.1 <= b.3
}

pub struct Grid {
    frame: Bounds,
    nx: usize,
    ny: usize,
    cell: f64,
    capacity: f64,
    step: f64,
    rest: Vec<Vec<(f64, f64)>>,
    contributions: Vec<Vec<(usize, f64)>>,
    cells: Vec<Vec<(usize, f64)>>,
    demand: Vec<f64>,
    counts: BTreeMap<usize, usize>,
    turns: Vec<Vec<(usize, Bounds)>>,
    affected: Vec<Vec<bool>>,
    scratch: Vec<Vec<(usize, f64)>>,
    touched: Vec<usize>,
    marked: Vec<bool>,
    sum: Sum,
}

impl Grid {
    pub fn new(
        frame: Bounds,
        layers: usize,
        pitch: f64,
        step: f64,
        cell: f64,
        pads: Vec<(String, f64, f64)>,
        turns: Vec<Vec<(String, Bounds)>>,
    ) -> Result<Self, String> {
        if !finite_box(frame)
            || layers == 0
            || !pitch.is_finite()
            || pitch <= 0.0
            || !step.is_finite()
            || step <= 0.0
            || !cell.is_finite()
            || cell <= 0.0
        {
            return Err("NativeDelta congestion grid parameters invalid".into());
        }
        let capacity = layers as f64 * cell * cell / pitch;
        if !capacity.is_finite() || capacity <= 0.0 {
            return Err("NativeDelta congestion capacity must be finite and positive".into());
        }
        let nx = (((frame.2 - frame.0) / cell).ceil() as usize).max(1);
        let ny = (((frame.3 - frame.1) / cell).ceil() as usize).max(1);
        let size = nx
            .checked_mul(ny)
            .filter(|&n| n <= 4_000_000)
            .ok_or("NativeDelta congestion grid is too large")?;
        let mut names = HashMap::new();
        for (name, _, _) in &pads {
            let n = names.len();
            names.entry(name.clone()).or_insert(n);
        }
        for turn in &turns {
            for (name, _) in turn {
                let n = names.len();
                names.entry(name.clone()).or_insert(n);
            }
        }
        let mut rest = vec![Vec::new(); names.len()];
        for (net, x, y) in pads {
            if !x.is_finite() || !y.is_finite() {
                return Err("NativeDelta congestion pads must be finite".into());
            }
            if x < frame.0 - 1e-9 || x > frame.2 + 1e-9 || y < frame.1 - 1e-9 || y > frame.3 + 1e-9
            {
                return Err("NativeDelta rest pads exceed the fixed search frame".into());
            }
            rest[names[&net]].push((x, y));
        }
        let turns: Vec<Vec<(usize, Bounds)>> = turns
            .into_iter()
            .map(|turn| turn.into_iter().map(|(net, b)| (names[&net], b)).collect())
            .collect();
        if turns.iter().flatten().any(|(_, b)| !finite_box(*b)) {
            return Err("NativeDelta congestion pad bounds invalid".into());
        }
        let affected = turns
            .iter()
            .map(|turn| {
                let mut touched = vec![false; names.len()];
                for (net, _) in turn {
                    touched[*net] = true;
                }
                touched
            })
            .collect();
        let mut grid = Self {
            frame,
            nx,
            ny,
            cell,
            capacity,
            step,
            rest,
            contributions: Vec::new(),
            cells: vec![Vec::new(); size],
            demand: vec![0.0; size],
            counts: BTreeMap::new(),
            turns,
            affected,
            scratch: vec![Vec::new(); size],
            touched: Vec::new(),
            marked: vec![false; size],
            sum: Sum::default(),
        };
        for net in 0..grid.rest.len() {
            let values = grid.offer(&grid.rest[net])?;
            for &(i, v) in &values {
                grid.cells[i].push((net, v));
            }
            grid.contributions.push(values);
        }
        for i in 0..size {
            grid.sum.clear();
            for &(_, v) in &grid.cells[i] {
                grid.sum.add(v);
            }
            grid.demand[i] = grid.sum.total();
            *grid.counts.entry(grid.level(grid.demand[i])?).or_default() += 1;
        }
        Ok(grid)
    }
    fn level(&self, value: f64) -> Result<usize, String> {
        if !value.is_finite() || value < 0.0 {
            return Err("NativeDelta congestion demand must be finite and nonnegative".into());
        }
        let level = value.max(0.0) / self.capacity / self.step + 1e-9;
        if !level.is_finite() || level >= (i64::MAX / 2) as f64 {
            return Err("NativeDelta congestion step count is not representable".into());
        }
        Ok(level as usize)
    }
    fn offer(&self, points: &[(f64, f64)]) -> Result<Vec<(usize, f64)>, String> {
        if points.len() < 2 {
            return Ok(Vec::new());
        }
        let (mut x0, mut y0, mut x1, mut y1) = (points[0].0, points[0].1, points[0].0, points[0].1);
        for &(x, y) in points {
            x0 = x0.min(x);
            y0 = y0.min(y);
            x1 = x1.max(x);
            y1 = y1.max(y);
        }
        let wire = (x1 - x0) + (y1 - y0);
        if x1 - x0 < self.cell {
            let (a, b) = ((x0 + x1 - self.cell) / 2.0, (x0 + x1 + self.cell) / 2.0);
            x0 = a;
            x1 = b;
        }
        if y1 - y0 < self.cell {
            let (a, b) = ((y0 + y1 - self.cell) / 2.0, (y0 + y1 + self.cell) / 2.0);
            y0 = a;
            y1 = b;
        }
        let area = (x1 - x0) * (y1 - y0);
        let density = wire.max(self.cell) / area;
        if !wire.is_finite()
            || !area.is_finite()
            || area <= 0.0
            || !density.is_finite()
            || density <= 0.0
        {
            return Err("NativeDelta congestion density is not finite and positive".into());
        }
        let ix0 = (((x0 - self.frame.0) / self.cell).floor() as isize).max(0) as usize;
        let iy0 = (((y0 - self.frame.1) / self.cell).floor() as isize).max(0) as usize;
        let ix1 =
            (((x1 - self.frame.0) / self.cell).ceil() as isize).clamp(0, self.nx as isize) as usize;
        let iy1 =
            (((y1 - self.frame.1) / self.cell).ceil() as isize).clamp(0, self.ny as isize) as usize;
        let mut out = Vec::with_capacity(ix1.saturating_sub(ix0) * iy1.saturating_sub(iy0));
        for j in iy0..iy1 {
            let a = self.frame.1 + j as f64 * self.cell;
            let oy = y1.min(a + self.cell) - y0.max(a);
            for i in ix0..ix1 {
                let a = self.frame.0 + i as f64 * self.cell;
                let ox = x1.min(a + self.cell) - x0.max(a);
                if ox > 0.0 && oy > 0.0 {
                    out.push((j * self.nx + i, density * ox * oy));
                }
            }
        }
        Ok(out)
    }
    fn mark(&mut self, index: usize) {
        if !self.marked[index] {
            self.marked[index] = true;
            self.touched.push(index);
        }
    }
    pub fn change(&mut self, x: f64, y: f64, turn: usize) -> Result<i64, String> {
        if turn >= self.turns.len() {
            return Err("NativeDelta congestion turn index invalid".into());
        }
        for &index in &self.touched {
            self.marked[index] = false;
            self.scratch[index].clear();
        }
        self.touched.clear();
        let mut new: HashMap<usize, Vec<(f64, f64)>> = HashMap::new();
        for &(net, b) in &self.turns[turn] {
            let b = shifted(b, x, y);
            let p = ((b.0 + b.2) / 2.0, (b.1 + b.3) / 2.0);
            if p.0 < self.frame.0 - 1e-9
                || p.0 > self.frame.2 + 1e-9
                || p.1 < self.frame.1 - 1e-9
                || p.1 > self.frame.3 + 1e-9
            {
                return Err("NativeDelta candidate pads exceed the fixed search frame".into());
            }
            new.entry(net)
                .or_insert_with(|| self.rest[net].clone())
                .push(p);
        }
        for (net, points) in new {
            let values = self.offer(&points)?;
            for &(index, value) in &values {
                self.mark(index);
                self.scratch[index].push((net, value));
            }
            for i in 0..self.contributions[net].len() {
                self.mark(self.contributions[net][i].0);
            }
        }
        let mut changes: BTreeMap<usize, i64> = BTreeMap::new();
        for &index in &self.touched {
            *changes.entry(self.level(self.demand[index])?).or_default() -= 1;
            self.sum.clear();
            for &(net, value) in &self.cells[index] {
                if !self.affected[turn][net] {
                    self.sum.add(value);
                }
            }
            for &(_, value) in &self.scratch[index] {
                self.sum.add(value);
            }
            *changes.entry(self.level(self.sum.total())?).or_default() += 1;
        }
        let before = *self.counts.keys().next_back().unwrap_or(&0);
        let mut after = 0;
        for &level in self.counts.keys().chain(changes.keys()) {
            if self.counts.get(&level).copied().unwrap_or(0) as i64
                + changes.get(&level).copied().unwrap_or(0)
                > 0
            {
                after = after.max(level);
            }
        }
        Ok(after as i64 - before as i64)
    }
}

pub struct Layout {
    links: Vec<Vec<Link>>,
    boxes: Vec<Bounds>,
    fit: Option<(Option<Bounds>, f64, Option<f64>, Option<f64>, f64)>,
    grid: Option<Grid>,
    weights: (f64, f64, f64, f64),
}
impl Layout {
    pub fn new(
        links: Vec<Vec<Link>>,
        boxes: Vec<Bounds>,
        fit: Option<(Option<Bounds>, f64, Option<f64>, Option<f64>, f64)>,
        grid: Option<Grid>,
        weights: (f64, f64, f64, f64),
    ) -> Result<Self, String> {
        if links.len() != boxes.len() || boxes.iter().any(|b| !finite_box(*b)) {
            return Err("NativeDelta layout turns/bounds invalid".into());
        }
        if links.iter().flatten().any(|l| {
            ![l.0, l.1, l.3, l.4, l.6].iter().all(|v| v.is_finite())
                || l.6 < 0.0
                || l.7.is_some_and(|v| !v.is_finite() || v < 0.0)
        }) {
            return Err("NativeDelta layout links invalid".into());
        }
        if let Some((others, margin, w, h, area)) = fit {
            if others.is_some_and(|b| !finite_box(b))
                || !margin.is_finite()
                || margin < 0.0
                || !area.is_finite()
                || area < 0.0
                || [w, h]
                    .iter()
                    .any(|v| v.is_some_and(|v| !v.is_finite() || v < 0.0))
            {
                return Err("NativeDelta fit parameters invalid".into());
            }
        }
        if [weights.0, weights.1, weights.2, weights.3]
            .iter()
            .any(|v| !v.is_finite() || *v < 0.0)
        {
            return Err("NativeDelta layout weights invalid".into());
        }
        Ok(Self {
            links,
            boxes,
            fit,
            grid,
            weights,
        })
    }
    pub fn terms(&mut self, x: f64, y: f64, turn: usize) -> Result<(f64, f64, f64, f64), String> {
        if turn >= self.links.len() {
            return Err("NativeDelta layout turn invalid".into());
        }
        let (mut link, mut over) = (exact::PySum::new(), exact::PySum::new());
        for &(ax, ay, am, bx, by, bm, w, limit) in &self.links[turn] {
            let (ax, ay) = if am {
                (exact::clean9(ax + x), exact::clean9(ay + y))
            } else {
                (ax, ay)
            };
            let (bx, by) = if bm {
                (exact::clean9(bx + x), exact::clean9(by + y))
            } else {
                (bx, by)
            };
            let length = exact::hypot(ax - bx, ay - by);
            link.add(w * length);
            if let Some(limit) = limit {
                over.add(w * (length - limit).max(0.0));
            }
        }
        let area = if let Some((others, margin, w, h, before)) = self.fit {
            let candidate = shifted(self.boxes[turn], x, y);
            let b = others.map_or(candidate, |b| union(b, candidate));
            w.unwrap_or(b.2 - b.0 + 2.0 * margin) * h.unwrap_or(b.3 - b.1 + 2.0 * margin) - before
        } else {
            0.0
        };
        let congestion = if let Some(grid) = &mut self.grid {
            grid.change(x, y, turn)? as f64
        } else {
            0.0
        };
        let terms = (
            self.weights.0 * link.total(),
            self.weights.1 * over.total(),
            self.weights.2 * area,
            self.weights.3 * congestion,
        );
        if [terms.0, terms.1, terms.2, terms.3]
            .iter()
            .any(|v| !v.is_finite())
        {
            return Err("NativeDelta layout terms must be finite".into());
        }
        Ok(terms)
    }
}

#[cfg(test)]
mod tests {
    use super::Sum;
    #[test]
    fn sum_preserves_small_demands_and_half_even_rounding() {
        let mut sum = Sum::default();
        for value in [1e16, 1.0, 1.0] {
            sum.add(value);
        }
        assert_eq!(sum.total(), 10000000000000002.0);
        sum.clear();
        for value in [1.0, 2.0f64.powi(-53), 2.0f64.powi(-54)] {
            sum.add(value);
        }
        assert_eq!(sum.total(), f64::from_bits(1.0f64.to_bits() + 1));
    }
}
