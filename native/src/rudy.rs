//! congestion.py's RudyGrid cells: each cell's demand by net, its exact sum (CPython `math.fsum`, as `score_layout`'s
//! `Sum` ports it) and how many cells stand at each congestion step. Python keeps the frame and works out each net's
//! contribution; this keeps the cells, so a net's change re-sums each cell it touches once.
use crate::score_layout::Sum;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::{BTreeMap, HashMap};

#[pyclass]
pub struct RudyCells {
    // The frame's left and top, the cell, the grid's width and height in cells, and the net box floor.
    left: f64,
    top: f64,
    cell: f64,
    nx: usize,
    ny: usize,
    floor: f64,
    capacity: f64,
    step: f64,
    demand: Vec<f64>,
    cells: Vec<Vec<(u32, f64)>>,
    nets: HashMap<String, (u32, Vec<(usize, f64)>)>,
    ids: u32,
    counts: BTreeMap<i64, usize>,
    sum: Sum,
}

impl RudyCells {
    /// congestion.py's `_box_contribution`: a net's demand by cell from its pads' box (x0, x1, y0, y1), floored by
    /// `_floored` and spread by `_spans`, with its arithmetic in the same order (as `score_layout`'s `offer_box`).
    fn box_contribution(&self, raw: (f64, f64, f64, f64)) -> PyResult<Vec<(usize, f64)>> {
        let (mut x0, mut x1, mut y0, mut y1) = raw;
        let wire = (x1 - x0) + (y1 - y0);
        if x1 - x0 < self.floor {
            let (a, b) = ((x0 + x1 - self.floor) / 2.0, (x0 + x1 + self.floor) / 2.0);
            x0 = a;
            x1 = b;
        }
        if y1 - y0 < self.floor {
            let (a, b) = ((y0 + y1 - self.floor) / 2.0, (y0 + y1 + self.floor) / 2.0);
            y0 = a;
            y1 = b;
        }
        let area = (x1 - x0) * (y1 - y0);
        let density = wire.max(self.cell) / area;
        if !area.is_finite() || area <= 0.0 || !density.is_finite() {
            return Err(PyValueError::new_err("RUDY net box has no area"));
        }
        let ix0 = (((x0 - self.left) / self.cell).floor() as isize).max(0) as usize;
        let iy0 = (((y0 - self.top) / self.cell).floor() as isize).max(0) as usize;
        let ix1 = (((x1 - self.left) / self.cell).ceil() as isize).clamp(0, self.nx as isize) as usize;
        let iy1 = (((y1 - self.top) / self.cell).ceil() as isize).clamp(0, self.ny as isize) as usize;
        let mut out = Vec::with_capacity(ix1.saturating_sub(ix0) * iy1.saturating_sub(iy0));
        for j in iy0..iy1 {
            let a = self.top + j as f64 * self.cell;
            let oy = y1.min(a + self.cell) - y0.max(a);
            if oy <= 0.0 {
                continue;
            }
            for i in ix0..ix1 {
                let a = self.left + i as f64 * self.cell;
                let ox = x1.min(a + self.cell) - x0.max(a);
                if ox > 0.0 {
                    out.push((j * self.nx + i, density * ox * oy));
                }
            }
        }
        Ok(out)
    }

    /// congestion.py's `_step`: `int(max(0.0, value) / capacity / step + 1e-9)`, 0 without a step.
    fn step_of(&self, value: f64) -> i64 {
        if self.step == 0.0 {
            return 0;
        }
        (value.max(0.0) / self.capacity / self.step + 1e-9) as i64
    }

    fn count(counts: &mut BTreeMap<i64, usize>, step: i64, by: isize) {
        let n = counts.entry(step).or_insert(0);
        *n = (*n as isize + by) as usize;
        if *n == 0 {
            counts.remove(&step);
        }
    }

    fn id(&mut self, net: &str) -> u32 {
        if let Some((id, _)) = self.nets.get(net) {
            return *id;
        }
        self.ids += 1;
        self.ids
    }

    fn check(&self, contribution: &[(usize, f64)]) -> PyResult<()> {
        if contribution.iter().any(|(i, a)| *i >= self.demand.len() || !a.is_finite()) {
            return Err(PyValueError::new_err("RUDY contribution outside the grid or not finite"));
        }
        Ok(())
    }
}

#[pymethods]
impl RudyCells {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(left: f64, top: f64, cell: f64, nx: usize, ny: usize, floor: f64, capacity: f64, step: f64)
           -> PyResult<Self> {
        let cells = nx.checked_mul(ny).unwrap_or(0);
        if cells == 0 || cells > 100_000_000 || !capacity.is_finite() || capacity <= 0.0 || !step.is_finite()
            || step < 0.0 || !cell.is_finite() || cell <= 0.0 || !floor.is_finite() || floor < 0.0
            || !left.is_finite() || !top.is_finite() {
            return Err(PyValueError::new_err("RUDY grid parameters invalid"));
        }
        let mut counts = BTreeMap::new();
        counts.insert(0, cells);
        Ok(Self {
            left,
            top,
            cell,
            nx,
            ny,
            floor,
            capacity,
            step,
            demand: vec![0.0; cells],
            cells: vec![Vec::new(); cells],
            nets: HashMap::new(),
            ids: 0,
            counts,
            sum: Sum::default(),
        })
    }

    /// `net`'s demand replaced by `contribution` (cell, amount); an empty one removes it. Every cell either touches
    /// is re-summed once, from the amounts it then holds.
    fn replace(&mut self, net: &str, contribution: Vec<(usize, f64)>) -> PyResult<()> {
        self.check(&contribution)?;
        let id = self.id(net);
        let old = self.nets.remove(net).map(|(_, c)| c).unwrap_or_default();
        let mut touched: Vec<usize> = old.iter().map(|(i, _)| *i).collect();
        for (index, _) in &old {
            self.cells[*index].retain(|(n, _)| *n != id);
        }
        for (index, amount) in &contribution {
            let cell = &mut self.cells[*index];
            match cell.iter_mut().find(|(n, _)| *n == id) {
                Some(slot) => slot.1 = *amount,
                None => cell.push((id, *amount)),
            }
            touched.push(*index);
        }
        touched.sort_unstable();
        touched.dedup();
        for index in touched {
            let before = self.step_of(self.demand[index]);
            Self::count(&mut self.counts, before, -1);
            self.sum.clear();
            for (_, amount) in &self.cells[index] {
                self.sum.add(*amount);
            }
            self.demand[index] = self.sum.total();
            let after = self.step_of(self.demand[index]);
            Self::count(&mut self.counts, after, 1);
        }
        if !contribution.is_empty() {
            self.nets.insert(net.to_owned(), (id, contribution));
        }
        Ok(())
    }

    /// `replace` with the demand of a net whose pads' box is `raw` (x0, x1, y0, y1), or none.
    fn replace_box(&mut self, net: &str, raw: Option<(f64, f64, f64, f64)>) -> PyResult<()> {
        let contribution = match raw {
            Some(raw) => self.box_contribution(raw)?,
            None => Vec::new(),
        };
        self.replace(net, contribution)
    }

    /// `change` for nets given by their pads' boxes (none: the net would have no demand).
    fn change_boxes(&mut self, boxes: Vec<(String, Option<(f64, f64, f64, f64)>)>) -> PyResult<i64> {
        let mut contributions = HashMap::new();
        for (net, raw) in boxes {
            let c = match raw {
                Some(raw) => self.box_contribution(raw)?,
                None => Vec::new(),
            };
            contributions.insert(net, c);
        }
        self.change(contributions)
    }

    fn worst(&self) -> f64 {
        self.demand.iter().cloned().fold(0.0, f64::max) / self.capacity
    }

    fn steps(&self) -> i64 {
        self.counts.keys().next_back().copied().unwrap_or(0)
    }

    /// congestion.py's `change`: the signed change in the worst step if each net in `contributions` had that
    /// demand instead; nothing is changed.
    fn change(&mut self, contributions: HashMap<String, Vec<(usize, f64)>>) -> PyResult<i64> {
        for c in contributions.values() {
            self.check(c)?;
        }
        let replaced: Vec<u32> = contributions.keys().filter_map(|n| self.nets.get(n).map(|(id, _)| *id)).collect();
        let mut fresh: HashMap<usize, Vec<f64>> = HashMap::new();
        let mut touched: Vec<usize> = Vec::new();
        for (net, contribution) in &contributions {
            if let Some((_, old)) = self.nets.get(net) {
                touched.extend(old.iter().map(|(i, _)| *i));
            }
            for (index, amount) in contribution {
                touched.push(*index);
                fresh.entry(*index).or_default().push(*amount);
            }
        }
        touched.sort_unstable();
        touched.dedup();
        let mut counts = self.counts.clone();
        for index in touched {
            Self::count(&mut counts, self.step_of(self.demand[index]), -1);
            self.sum.clear();
            for (n, amount) in &self.cells[index] {
                if !replaced.contains(n) {
                    self.sum.add(*amount);
                }
            }
            for amount in fresh.get(&index).into_iter().flatten() {
                self.sum.add(*amount);
            }
            let value = self.sum.total();
            Self::count(&mut counts, self.step_of(value), 1);
        }
        Ok(counts.keys().next_back().copied().unwrap_or(0) - self.steps())
    }

    /// Each cell's demand, for inspection and parity tests.
    fn demand(&self) -> Vec<f64> {
        self.demand.clone()
    }
}
