//! `placer._largest_rectangle`, ported whole: the largest all-free
//! axis-aligned rectangle in a boolean grid, by the histogram method.
//!
//! Unlike the geometry predicates and the conflict search, this has no
//! floating point in it at all - `free` is a grid of booleans, `rows` and
//! `cols` are cell counts, and the answer is cell indices - so there is no
//! _clean-rounding or epsilon-boundary question to preserve: the same
//! integer algorithm in Rust gives the identical answer Python's does, for
//! every input, not just "the same to a tolerance". See
//! docs/superpowers/specs/2026-09-24-native-core-design.md.
//!
//! `pockets()` (placer.py) calls this once per pocket it looks for (up to
//! `limit` times), each time over a grid that can be large (a board
//! rastered at a fine step) - the histogram scan itself, not the grid
//! setup around it, is what a profile shows dominating `pockets()`'s cost.

/// Largest all-free rectangle at least `need_r` rows by `need_c` columns;
/// `(area, r0, c0, r1, c1)` (r1, c1 exclusive) or `None`. Ties break the
/// same way Python's does: `area > best` is strict, so the FIRST rectangle
/// of the largest area found in row-then-column scan order wins - matching
/// that requires walking rows and the histogram stack in the same order,
/// which this does.
pub fn largest_rectangle(
    free: &[Vec<bool>],
    rows: usize,
    cols: usize,
    need_r: usize,
    need_c: usize,
) -> Option<(usize, usize, usize, usize, usize)> {
    if cols == 0 {
        return None;
    }
    let mut heights = vec![0i64; cols];
    let mut best: Option<(i64, usize, usize, usize, usize)> = None;
    for r in 0..rows {
        let row = &free[r];
        for c in 0..cols {
            heights[c] = if row[c] { heights[c] + 1 } else { 0 };
        }
        let mut stack: Vec<(usize, i64)> = Vec::new();
        for c in 0..=cols {
            let h = if c < cols { heights[c] } else { 0 };
            let mut start = c;
            while let Some(&(s, sh)) = stack.last() {
                if sh < h {
                    break;
                }
                stack.pop();
                let area = sh * (c as i64 - s as i64);
                if sh >= need_r as i64 && (c - s) >= need_c && best.is_none_or(|b| area > b.0) {
                    best = Some((area, r + 1 - sh as usize, s, r + 1, c));
                }
                start = s;
            }
            stack.push((start, h));
        }
    }
    best.map(|(area, r0, c0, r1, c1)| (area as usize, r0, c0, r1, c1))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn grid(rows: &[&str]) -> Vec<Vec<bool>> {
        rows.iter().map(|r| r.chars().map(|c| c == '.').collect()).collect()
    }

    #[test]
    fn empty_grid_has_no_rectangle() {
        let g: Vec<Vec<bool>> = vec![];
        assert_eq!(largest_rectangle(&g, 0, 0, 1, 1), None);
    }

    #[test]
    fn fully_blocked_grid_has_no_rectangle() {
        let g = grid(&["###", "###"]);
        assert_eq!(largest_rectangle(&g, 2, 3, 1, 1), None);
    }

    #[test]
    fn a_single_free_cell() {
        let g = grid(&["#.#", "###"]);
        assert_eq!(largest_rectangle(&g, 2, 3, 1, 1), Some((1, 0, 1, 1, 2)));
    }

    #[test]
    fn the_whole_grid_free() {
        let g = grid(&["....", "....", "...."]);
        assert_eq!(largest_rectangle(&g, 3, 4, 1, 1), Some((12, 0, 0, 3, 4)));
    }

    #[test]
    fn a_wide_low_rectangle_beats_a_narrow_tall_one_when_bigger() {
        // A 1x5 strip (area 5) on top of a 3x1 column (area 3): the strip wins.
        let g = grid(&[".....", "#.###", "#.###"]);
        let (area, r0, c0, r1, c1) = largest_rectangle(&g, 3, 5, 1, 1).unwrap();
        assert_eq!(area, 5);
        assert_eq!((r0, c0, r1, c1), (0, 0, 1, 5));
    }

    #[test]
    fn a_minimum_size_prunes_rectangles_too_small() {
        // Only 1-wide free columns: needs 2 columns, so nothing qualifies.
        let g = grid(&[".#.#.", ".#.#."]);
        assert_eq!(largest_rectangle(&g, 2, 5, 1, 2), None);
        // 1x1 is fine.
        assert!(largest_rectangle(&g, 2, 5, 1, 1).is_some());
    }

    #[test]
    fn ties_go_to_the_first_found_in_row_then_column_order() {
        // Two 1x2 free runs of equal area, on DIFFERENT columns in
        // different rows (so they cannot combine into one bigger
        // rectangle): the histogram method meets row 0's on row 0, before
        // row 1's is ever seen, and Python's strict `area > best[0]` means
        // an equal-area later find never replaces an earlier one.
        let g = grid(&["..###", "###.."]);
        let got = largest_rectangle(&g, 2, 5, 1, 1).unwrap();
        assert_eq!(got, (2, 0, 0, 1, 2)); // row 0's block, not row 1's equal-area one
    }
}
