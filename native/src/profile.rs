//! Stage timers for the sweep, built in only with `--features profile`
//! (`maturin develop --release --features profile`): `sweep_profile()` then
//! returns, per stage slot, the seconds spent and the times it ran since the
//! last call, and resets them. Without the feature every call is nothing.
//!
//! `sweep`'s slots: 0 shifting the candidate's boxes, 1 the edge, 3 the
//! reservations, 4 the obstacles; 6, 7 and 8 the whole time of a candidate
//! the edge, a reservation or an obstacle refused, and 9 of one that was legal.

use pyo3::prelude::*;

#[cfg(feature = "profile")]
mod on {
    use std::cell::RefCell;
    use std::time::Instant;

    thread_local! {
        static SLOTS: RefCell<[(f64, u64); 12]> = const { RefCell::new([(0.0, 0); 12]) };
    }

    pub type Mark = Instant;

    #[inline]
    pub fn mark() -> Mark {
        Instant::now()
    }

    #[inline]
    pub fn add(slot: usize, since: Mark) {
        SLOTS.with(|s| {
            let mut s = s.borrow_mut();
            s[slot].0 += since.elapsed().as_secs_f64();
            s[slot].1 += 1;
        });
    }

    pub fn take() -> Vec<(f64, u64)> {
        SLOTS.with(|s| std::mem::replace(&mut *s.borrow_mut(), [(0.0, 0); 12]).to_vec())
    }
}

#[cfg(not(feature = "profile"))]
mod on {
    pub type Mark = ();
    #[inline(always)]
    pub fn mark() -> Mark {}
    #[inline(always)]
    pub fn add(_slot: usize, _since: Mark) {}
    pub fn take() -> Vec<(f64, u64)> {
        Vec::new()
    }
}

pub use on::{add, mark};

/// The stage timers' (seconds, count) per slot, reset; empty without the `profile` feature.
#[pyfunction]
pub fn sweep_profile() -> Vec<(f64, u64)> {
    on::take()
}
