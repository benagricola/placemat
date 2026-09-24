//! Arithmetic that must land on the same bits as CPython's.
//!
//! - `hypot`: CPython's own `math.hypot` for two arguments, which is not the
//!   C library's: `vector_norm` in Modules/mathmodule.c (3.12, lines
//!   2470-2519), with its lossless scaling, compensated squaring and
//!   summation, and one differential correction. `dl_mul` uses `fma`
//!   (CPython's default where `fma` is reliable, which it is on every
//!   platform placemat builds wheels for).
//! - `clean9`: `geometry._clean`, `round(v, 9)` with -0.0 read as 0.0.
//!   CPython rounds a float to 9 decimals correctly from its exact binary
//!   value (`_Py_dg_dtoa` mode 3, then `_Py_dg_strtod`). The fast path takes
//!   the nearest integer to `v * 1e9` and divides it by `1e9`: both steps
//!   are correctly rounded, so the result is the nearest double to the
//!   decimal CPython prints - unless `v * 1e9`'s own rounding could have
//!   crossed a half, which `fma` measures; then the slow path formats with
//!   Rust's `{:.9}` (also correctly rounded from the exact value, ties to
//!   even) and parses the decimal back.

/// 2**k exactly, for k in [-1074, 1023].
fn pow2(k: i32) -> f64 {
    if k >= -1022 {
        f64::from_bits(((k + 1023) as u64) << 52)
    } else {
        f64::from_bits(1u64 << (k + 1074))
    }
}

/// C's `frexp` exponent: `x == m * 2**e` with 0.5 <= |m| < 1, for x != 0.
fn frexp_exp(x: f64) -> i32 {
    let bits = x.to_bits();
    let exp = ((bits >> 52) & 0x7ff) as i32;
    if exp == 0 {
        // subnormal: the leading bit sets the exponent
        let mant = bits & ((1u64 << 52) - 1);
        let lead = 63 - mant.leading_zeros() as i32; // position of the top set bit
        lead - 1074 + 1
    } else {
        exp - 1022
    }
}

#[inline]
fn dl_fast_sum(a: f64, b: f64) -> (f64, f64) {
    let x = a + b;
    let y = (a - x) + b;
    (x, y)
}

#[inline]
fn dl_mul(x: f64, y: f64) -> (f64, f64) {
    let z = x * y;
    let zz = x.mul_add(y, -z);
    (z, zz)
}

fn vector_norm2(mut v: [f64; 2], max: f64, found_nan: bool) -> f64 {
    if max.is_infinite() {
        return max;
    }
    if found_nan {
        return f64::NAN;
    }
    if max == 0.0 {
        return max;
    }
    let max_e = frexp_exp(max);
    if max_e < -1023 {
        for x in v.iter_mut() {
            *x /= f64::MIN_POSITIVE; // subnormals to normals
        }
        return f64::MIN_POSITIVE * vector_norm2(v, max / f64::MIN_POSITIVE, found_nan);
    }
    let scale = pow2(-max_e);
    let (mut csum, mut frac1, mut frac2) = (1.0f64, 0.0f64, 0.0f64);
    for &x0 in v.iter() {
        let x = x0 * scale;
        let (pr_hi, pr_lo) = dl_mul(x, x);
        let (sm_hi, sm_lo) = dl_fast_sum(csum, pr_hi);
        csum = sm_hi;
        frac1 += pr_lo;
        frac2 += sm_lo;
    }
    let mut h = (csum - 1.0 + (frac1 + frac2)).sqrt();
    let (pr_hi, pr_lo) = dl_mul(-h, h);
    let (sm_hi, sm_lo) = dl_fast_sum(csum, pr_hi);
    csum = sm_hi;
    frac1 += pr_lo;
    frac2 += sm_lo;
    let x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    h / scale
}

/// CPython's `math.hypot(a, b)`, bit for bit.
pub fn hypot(a: f64, b: f64) -> f64 {
    let (x, y) = (a.abs(), b.abs());
    let found_nan = x.is_nan() || y.is_nan();
    let mut max = 0.0f64;
    if x > max {
        max = x;
    }
    if y > max {
        max = y;
    }
    vector_norm2([x, y], max, found_nan)
}

fn clean9_slow(v: f64) -> f64 {
    let s = format!("{:.9}", v);
    s.parse::<f64>().unwrap_or(v)
}

/// `round(v, 9)`, correctly rounded as CPython does it.
pub fn round9(v: f64) -> f64 {
    if !v.is_finite() {
        return v;
    }
    let p = v * 1e9;
    if p.abs() >= 4.0e15 {
        return clean9_slow(v); // near the end of exact integers: take no chances
    }
    let err = v.mul_add(1e9, -p); // the exact v*1e9 is p + err
    let r = p.round_ties_even();
    let off = (p - r).abs();
    // Unsure only when the exact product may sit on the other side of a half
    // than its rounded value p does, or exactly on one.
    if (off - 0.5).abs() <= err.abs() * 2.0 + 1e-6 {
        return clean9_slow(v);
    }
    let _ = err;
    r / 1e9
}

/// `geometry._clean`: `round(v, 9)`, and 0.0 for either zero.
pub fn clean9(v: f64) -> f64 {
    let r = round9(v);
    if r == 0.0 { 0.0 } else { r }
}

/// CPython 3.12's built-in `sum()` over floats (Python/bltinmodule.c,
/// lines 2609-2643): Neumaier's compensated summation, the compensation
/// added once at the end. A sum that starts from the int 0 adds its first
/// float exactly, which starting from 0.0 does too.
pub struct PySum {
    f: f64,
    c: f64,
}

impl PySum {
    pub fn new() -> PySum {
        PySum { f: 0.0, c: 0.0 }
    }

    pub fn add(&mut self, x: f64) {
        let t = self.f + x;
        if self.f.abs() >= x.abs() {
            self.c += (self.f - t) + x;
        } else {
            self.c += (x - t) + self.f;
        }
        self.f = t;
    }

    pub fn total(&self) -> f64 {
        if self.c != 0.0 && self.c.is_finite() { self.f + self.c } else { self.f }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hypot_of_a_right_triangle() {
        assert_eq!(hypot(3.0, 4.0), 5.0);
        assert_eq!(hypot(0.0, 0.0), 0.0);
        assert_eq!(hypot(-3.0, 0.0), 3.0);
    }

    #[test]
    fn clean9_rounds_to_nine_places_and_reads_negative_zero_as_zero() {
        assert_eq!(clean9(1.0000000004), 1.0);
        assert_eq!(clean9(1.0000000006), 1.000000001);
        assert_eq!(clean9(-0.0000000001).to_bits(), 0.0f64.to_bits());
    }

    #[test]
    fn pysum_compensates_as_cpython_does() {
        let mut s = PySum::new();
        for x in [1e16, 1.0, -1e16] {
            s.add(x);
        }
        assert_eq!(s.total(), 1.0);             // CPython 3.12: sum([1e16, 1.0, -1e16]) == 1.0
    }

    #[test]
    fn frexp_matches_c() {
        assert_eq!(frexp_exp(1.0), 1);
        assert_eq!(frexp_exp(0.5), 0);
        assert_eq!(frexp_exp(0.75), 0);
        assert_eq!(frexp_exp(f64::MIN_POSITIVE), -1021);
        assert_eq!(frexp_exp(f64::from_bits(1)), -1073);
    }
}
