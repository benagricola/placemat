//! A carried via's move, judged whole (`giveway.py` `_give`): the moved via
//! against the item's own copper, the tail redrawn from its pad, and the
//! two quick tests that come first (the disc inside its pad, the copper it
//! first met). Each function ports its Python original with the same
//! tolerances and the same order of arithmetic, so the same offset is
//! chosen (docs/superpowers/specs/2026-09-30-give-way-native-move-design.md).

use crate::exact;
use crate::geometry::{point_in_polygon, point_segment_distance, Point};
use crate::shapes::{box_overlaps, conflict, may_meet, Bounds, ConflictConfig, Shape, ShapeGrid};
use std::collections::HashSet;

/// `giveway._disc_inside`: whether the disc of radius `r` round `c` lies
/// inside `poly`: its centre inside, and every side at least `r` from it.
pub fn disc_inside(poly: &[Point], c: Point, r: f64) -> bool {
    if !point_in_polygon(c, poly) {
        return false;
    }
    let n = poly.len();
    (0..n).all(|i| point_segment_distance(c, poly[i], poly[(i + 1) % n]) >= r)
}

/// `giveway._still_meets`'s `still`: whether a via of radius `r` centred on
/// `c` still meets `poly`, the copper it first met: its centre in it, or
/// nearer it than `clr` plus `r`.
pub fn still_meets(poly: &[Point], clr: f64, r: f64, c: Point) -> bool {
    if point_in_polygon(c, poly) {
        return true;
    }
    let n = poly.len();
    let d = (0..n).map(|i| point_segment_distance(c, poly[i], poly[(i + 1) % n])).fold(f64::INFINITY, f64::min);
    d - r < clr - 1e-9
}

/// `copper._segment_polygon`: a track as KiCad draws it, its two sides and
/// a round end at each end, `cap_steps` segments round each (`[geometry] cap_steps`).
pub fn segment_polygon(a: Point, b: Point, width: f64, cap_steps: usize) -> Vec<Point> {
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let n = exact::hypot(dx, dy);
    let h = width / 2.0;
    let (ux, uy) = if n == 0.0 { (1.0, 0.0) } else { (dx / n, dy / n) };
    let base = uy.atan2(ux);
    let far = h / (std::f64::consts::PI / (2 * cap_steps) as f64).cos();
    let step = std::f64::consts::PI / cap_steps as f64;
    let cap = |c: Point, start: f64| -> Vec<Point> {
        let mut pts = vec![(c.0 + h * start.cos(), c.1 + h * start.sin())];
        for j in 0..cap_steps {
            let ang = start + (j as f64 + 0.5) * step;
            pts.push((c.0 + far * ang.cos(), c.1 + far * ang.sin()));
        }
        let end = start + std::f64::consts::PI;
        pts.push((c.0 + h * end.cos(), c.1 + h * end.sin()));
        pts
    };
    let mut out = cap(b, base - std::f64::consts::PI / 2.0);
    out.extend(cap(a, base + std::f64::consts::PI / 2.0));
    out
}

fn bounds(poly: &[Point]) -> Bounds {
    let x0 = poly.iter().map(|p| p.0).fold(f64::INFINITY, f64::min);
    let x1 = poly.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max);
    let y0 = poly.iter().map(|p| p.1).fold(f64::INFINITY, f64::min);
    let y1 = poly.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max);
    (x0, y0, x1, y1)
}

/// Whether `s` meets any of `list` (`_Judge.hit`'s loop over the pool or the
/// item's own copper, as a yes or no).
fn meets_any(s: &Shape, list: &[Shape], clearance: Option<f64>, cfg: &ConflictConfig) -> bool {
    let gap = cfg.gap_for(s);
    list.iter().any(|o| box_overlaps(o.bbox, s.bbox, gap) && may_meet(s.kind, o.kind) && conflict(s, o, clearance, cfg))
}

/// Whether `s` meets a registered obstacle outside `skip`.
fn meets_board(grid: &ShapeGrid, s: &Shape, clearance: Option<f64>, cfg: &ConflictConfig, skip: &HashSet<usize>) -> bool {
    let gap = cfg.gap_for(s);
    grid.near(s.bbox, gap).into_iter().any(|oi| {
        !skip.contains(&oi) && may_meet(s.kind, grid.shapes[oi].kind) && conflict(s, &grid.shapes[oi], clearance, cfg)
    })
}

/// Whether none of `shapes` meets the board (less `skip`) or `mine`.
pub fn tail_clear(grid: &ShapeGrid, shapes: &[Shape], mine: &[Shape], clearance: Option<f64>, cfg: &ConflictConfig,
                  skip: &HashSet<usize>) -> bool {
    shapes.iter().all(|s| !meets_board(grid, s, clearance, cfg, skip) && !meets_any(s, mine, clearance, cfg))
}

/// Where `first_hit` found a conflict: the index of the shape asked about, whether the other was on the
/// board (`false`) or among `mine` (`true`), and its index there.
pub type Hit = (usize, bool, usize);

/// The first of `shapes` that meets the board (less `skip`) or `mine`, in `_Judge.hit`'s order: each shape
/// against the board's shapes near it, then against `mine`, before the next shape.
pub fn first_hit(grid: &ShapeGrid, shapes: &[Shape], mine: &[Shape], clearance: Option<f64>, cfg: &ConflictConfig,
                 skip: &HashSet<usize>) -> Option<Hit> {
    for (si, s) in shapes.iter().enumerate() {
        let gap = cfg.gap_for(s);
        for oi in grid.near(s.bbox, gap) {
            if !skip.contains(&oi) && may_meet(s.kind, grid.shapes[oi].kind) && conflict(s, &grid.shapes[oi], clearance, cfg) {
                return Some((si, false, oi));
            }
        }
        for (mi, o) in mine.iter().enumerate() {
            if box_overlaps(o.bbox, s.bbox, gap) && may_meet(s.kind, o.kind) && conflict(s, o, clearance, cfg) {
                return Some((si, true, mi));
            }
        }
    }
    None
}

/// What a via's move is judged against, other than the board's own shapes.
pub struct Move<'a> {
    pub via: &'a [Shape],
    pub mine: &'a [Shape],
    pub centre: Point,
    /// the copper first met: its outline, the clearance and the via's radius
    pub first: Option<(&'a [Point], f64, f64)>,
    /// the pad the via lies in, and the disc radius it must keep inside it
    pub pad: Option<(&'a [Point], f64)>,
    /// the tail's shape (its outline is replaced at each offset), its far end, its width and the
    /// segments round each of its round ends
    pub tail: Option<(&'a Shape, Point, f64, usize)>,
    /// where the offsets are not yet known to be clear of the board: the vias to set aside; the ring and
    /// hole (`via`) are then judged against the board at each offset, after the cheaper tests
    pub board: Option<&'a HashSet<usize>>,
}

/// The index in `offsets` (from `start`) of the first that passes every test `_give`'s loop applies, or
/// None. The ring and hole are clear of the board at every offset where `m.board` is None; where it is
/// set they are judged here, with the vias it names set aside, after the cheaper tests (a spot is taken
/// only when all pass, so the order does not change which).
#[allow(clippy::too_many_arguments)]
pub fn first_move(grid: &ShapeGrid, cfg: &ConflictConfig, m: &Move, offsets: &[(f64, f64)], clearance: Option<f64>,
                  skip: &HashSet<usize>, start: usize) -> Option<usize> {
    let mut hint = None;
    'offsets: for (i, &(dx, dy)) in offsets.iter().enumerate().skip(start) {
        let to = (exact::round9(m.centre.0 + dx), exact::round9(m.centre.1 + dy));
        if let Some((poly, r)) = m.pad {
            if !disc_inside(poly, to, r) {
                continue;
            }
        }
        if let Some((poly, clr, r)) = m.first {
            if still_meets(poly, clr, r, to) {
                continue;
            }
        }
        for s0 in m.via {
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            let gap = cfg.gap_for(s0);
            if !m.mine.iter().any(|o| box_overlaps(o.bbox, bbox, gap)) {
                continue;
            }
            let poly: Vec<Point> = s0.poly.iter().map(|p| (p.0 + dx, p.1 + dy)).collect();
            let s = Shape { poly, bbox, ..s0.clone() };
            if meets_any(&s, m.mine, clearance, cfg) {
                continue 'offsets;
            }
        }
        if let Some(aside) = m.board {
            if grid.any_conflict_shifted_excluding(m.via, dx, dy, clearance, cfg, aside, &mut hint) {
                continue;
            }
        }
        if let Some((proto, far, width, cap_steps)) = m.tail {
            let poly = segment_polygon(far, to, width, cap_steps);
            let s = Shape { bbox: bounds(&poly), poly, ..proto.clone() };
            if meets_board(grid, &s, clearance, cfg, skip) || meets_any(&s, m.mine, clearance, cfg) {
                continue;
            }
        }
        return Some(i);
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::shapes::Kind;
    use std::collections::HashMap;

    fn square(cx: f64, cy: f64, half: f64) -> Vec<Point> {
        vec![(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]
    }

    fn cfg() -> ConflictConfig {
        ConflictConfig {
            touch: 0.02, vias_block_courtyards: false, silk_clearance: 0.1, component_spacing: 0.2,
            default_clearance: 0.2, net_clearance: HashMap::new(), rules: Vec::new(), gap: 1.0, drawn_gap: 0.2, hole_to_hole: 0.25,
            hole_clearance: 0.0, max_clearance: 0.2,
        }
    }

    fn copper(kind: Kind, poly: Vec<Point>, net: &str) -> Shape {
        let bbox = bounds(&poly);
        Shape { kind, faces: 1, layers: 1, net: net.into(), poly, bbox, owner: "o".into(), owner_is_footprint: false,
                is_lead: false, margin: 0.0, wire: false }
    }

    #[test]
    fn a_disc_outside_its_pad_is_not_inside() {
        assert!(!disc_inside(&square(0.0, 0.0, 1.0), (2.0, 0.0), 0.1));
    }

    #[test]
    fn a_disc_inside_needs_every_side_at_least_its_radius_away() {
        let pad = square(0.0, 0.0, 1.0);
        assert!(disc_inside(&pad, (0.0, 0.0), 1.0));
        assert!(!disc_inside(&pad, (0.0, 0.0), 1.01));
        assert!(disc_inside(&pad, (0.5, 0.0), 0.5));
        assert!(!disc_inside(&pad, (0.5, 0.0), 0.51));
    }

    #[test]
    fn a_via_still_meets_what_holds_its_centre_or_lies_within_clearance_and_radius() {
        let poly = square(0.0, 0.0, 1.0);
        assert!(still_meets(&poly, 0.2, 0.25, (0.0, 0.0)));
        assert!(still_meets(&poly, 0.2, 0.25, (1.4, 0.0)));      // 0.4 from the side, less 0.25 is 0.15 < 0.2
        assert!(!still_meets(&poly, 0.2, 0.25, (1.5, 0.0)));     // 0.5 - 0.25 = 0.25 >= 0.2
    }

    const CAP_STEPS: usize = 8;                 // [geometry] cap_steps' default

    #[test]
    fn a_track_outline_has_two_ends_of_ten_points() {
        let p = segment_polygon((0.0, 0.0), (2.0, 0.0), 0.2, CAP_STEPS);
        assert_eq!(p.len(), 2 * (CAP_STEPS + 2));
        let b = bounds(&p);
        assert!((b.0 + 0.1).abs() < 1e-12 && (b.2 - 2.1).abs() < 1e-12, "{:?}", b);
        assert!((b.1 + b.3).abs() < 1e-12);                    // symmetric about the line
    }

    #[test]
    fn a_track_of_no_length_points_along_x() {
        let p = segment_polygon((1.0, 1.0), (1.0, 1.0), 0.2, CAP_STEPS);
        let q = segment_polygon((1.0, 1.0), (2.0, 1.0), 0.2, CAP_STEPS);
        assert_eq!(p.len(), q.len());
        assert_eq!(p[0], (1.0 + 0.1 * (-std::f64::consts::FRAC_PI_2).cos(), 1.0 + 0.1 * (-std::f64::consts::FRAC_PI_2).sin()));
    }

    #[test]
    fn first_move_takes_the_first_offset_clear_of_its_own_copper_and_the_board() {
        let ring = copper(Kind::Through, square(0.0, 0.0, 0.3), "A");
        let mine = vec![copper(Kind::Pad, square(0.6, 0.0, 0.3), "B")];       // the item's pad, 0.6 to the right
        let grid = ShapeGrid::new(vec![copper(Kind::Pad, square(0.0, -3.0, 0.3), "B")]);
        let offsets = vec![(0.3, 0.0), (0.0, 0.3), (-0.3, 0.0)];
        let via = vec![ring];
        let m = Move { via: &via, mine: &mine, centre: (0.0, 0.0), first: None, pad: None, tail: None, board: None };
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &HashSet::new(), 0), Some(2));
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &HashSet::new(), 3), None);
    }

    #[test]
    fn first_move_judges_the_redrawn_tail_against_the_board_less_what_is_skipped() {
        let ring = copper(Kind::Through, square(0.0, 0.0, 0.3), "A");
        let other = copper(Kind::Copper, square(0.0, 1.0, 0.3), "B");          // in the way of a tail going up
        let grid = ShapeGrid::new(vec![other]);
        let proto = copper(Kind::Copper, vec![(0.0, 0.0); 3], "A");
        let via = vec![ring];
        let offsets = vec![(0.0, 1.0), (2.0, 0.0)];
        let m = Move { via: &via, mine: &[], centre: (0.0, 0.0), first: None, pad: None,
                       tail: Some((&proto, (0.0, -1.0), 0.2, CAP_STEPS)), board: None };
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &HashSet::new(), 0), Some(1));
        let skip: HashSet<usize> = [0].into_iter().collect();
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &skip, 0), Some(0));
    }

    #[test]
    fn first_move_keeps_a_via_inside_its_pad_and_off_what_it_first_met() {
        let ring = copper(Kind::Through, square(0.0, 0.0, 0.3), "A");
        let grid = ShapeGrid::new(vec![]);
        let pad = square(0.0, 0.0, 1.0);
        let first = square(-1.0, 0.0, 0.5);                                     // spans -1.5..-0.5 in x
        let via = vec![ring];
        let offsets = vec![(5.0, 0.0), (-0.2, 0.0), (0.2, 0.0)];
        let m = Move { via: &via, mine: &[], centre: (0.0, 0.0), first: Some((&first, 0.2, 0.3)),
                       pad: Some((&pad, 0.3)), tail: None, board: None };
        // 5.0 leaves the pad; -0.2 is still within clearance + radius of what it met; 0.2 is free
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &HashSet::new(), 0), Some(2));
    }

    #[test]
    fn first_hit_names_the_shape_and_where_the_other_was() {
        let grid = ShapeGrid::new(vec![copper(Kind::Pad, square(0.0, 0.0, 0.3), "B"), copper(Kind::Pad, square(5.0, 0.0, 0.3), "B")]);
        let near_second = copper(Kind::Copper, square(5.0, 0.4, 0.1), "A");
        let far = copper(Kind::Copper, square(20.0, 0.0, 0.1), "A");
        let mine = vec![copper(Kind::Pad, square(20.0, 0.3, 0.1), "B")];
        let skip = HashSet::new();
        assert_eq!(first_hit(&grid, &[far.clone(), near_second.clone()], &[], Some(0.2), &cfg(), &skip), Some((1, false, 1)));
        assert_eq!(first_hit(&grid, &[far.clone()], &mine, Some(0.2), &cfg(), &skip), Some((0, true, 0)));
        let skipped: HashSet<usize> = [1].into_iter().collect();
        assert_eq!(first_hit(&grid, &[near_second], &[], Some(0.2), &cfg(), &skipped), None);
        assert_eq!(first_hit(&grid, &[far], &[], Some(0.2), &cfg(), &skip), None);
    }

    #[test]
    fn first_move_judging_the_board_itself_takes_the_spot_the_clear_offsets_do() {
        let mut state = 17u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let (mut found, mut none) = (0, 0);
        for round in 0..300 {
            let mut board = Vec::new();
            for _ in 0..40 {
                let kind = [Kind::Pad, Kind::Copper, Kind::Through][(next() * 3.0) as usize % 3];
                board.push(copper(kind, square(next() * 6.0, next() * 6.0, 0.15 + next() * 0.4), ["A", "B", "C"][(next() * 3.0) as usize % 3]));
            }
            let grid = ShapeGrid::new(board);
            let c = cfg();
            let (cx, cy) = (1.0 + next() * 4.0, 1.0 + next() * 4.0);
            let via = vec![copper(Kind::Through, square(cx, cy, 0.3), "A"), copper(Kind::Hole, square(cx, cy, 0.15), "A")];
            let mine: Vec<Shape> = (0..(next() * 4.0) as usize)
                .map(|_| copper(Kind::Pad, square(cx + next() * 2.0 - 1.0, cy + next() * 2.0 - 1.0, 0.3), "B")).collect();
            let skip: HashSet<usize> = (0..40).filter(|i| i % 9 == round % 9).collect();
            let mut offsets = Vec::new();
            for i in -6..=6 {
                for j in -6..=6 {
                    if i != 0 || j != 0 {
                        offsets.push((i as f64 * 0.1, j as f64 * 0.1));
                    }
                }
            }
            offsets.sort_by(|a, b| (a.0 * a.0 + a.1 * a.1).partial_cmp(&(b.0 * b.0 + b.1 * b.1)).unwrap());
            let pad = square(cx, cy, 0.8);
            let first = square(cx - 0.9, cy, 0.5);
            let proto = copper(Kind::Copper, vec![(0.0, 0.0); 3], "A");
            let origin_shapes = via.clone();
            let clear: Vec<usize> = (0..offsets.len()).filter(|&i| {
                grid.first_conflict_shifted_excluding(&origin_shapes, offsets[i].0, offsets[i].1, Some(0.2), &c, &skip).is_none()
            }).collect();
            let kept: Vec<(f64, f64)> = clear.iter().map(|&i| offsets[i]).collect();
            for variant in 0..4 {
                let m = Move {
                    via: &via, mine: &mine, centre: (cx, cy),
                    first: if variant & 1 == 1 { Some((&first, 0.2, 0.3)) } else { None },
                    pad: if variant & 2 == 2 { Some((&pad, 0.3)) } else { None },
                    tail: if round % 2 == 0 { Some((&proto, (cx - 1.5, cy), 0.2, CAP_STEPS)) } else { None },
                    board: None,
                };
                let want = first_move(&grid, &c, &m, &kept, Some(0.2), &skip, 0).map(|i| kept[i]);
                let fused = Move { board: Some(&skip), ..m };
                let got = first_move(&grid, &c, &fused, &offsets, Some(0.2), &skip, 0).map(|i| offsets[i]);
                assert_eq!(got, want, "round {round} variant {variant}");
                if want.is_some() { found += 1 } else { none += 1 }
            }
        }
        assert!(found > 200 && none > 100, "{found} {none}");
    }

    #[test]
    fn tail_clear_is_false_when_a_shape_meets_mine() {
        let grid = ShapeGrid::new(vec![]);
        let tail = copper(Kind::Copper, square(0.0, 0.0, 0.1), "A");
        let near = vec![copper(Kind::Pad, square(0.3, 0.0, 0.1), "B")];
        assert!(!tail_clear(&grid, &[tail.clone()], &near, Some(0.2), &cfg(), &HashSet::new()));
        assert!(tail_clear(&grid, &[tail], &[], Some(0.2), &cfg(), &HashSet::new()));
    }
}
