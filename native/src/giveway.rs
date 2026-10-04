//! A carried via's move, judged whole (`giveway.py` `_give`): the moved via
//! against the item's own copper, the tail redrawn from its pad, and the
//! two quick tests that come first (the disc inside its pad, the copper it
//! first met). Each function ports its Python original with the same
//! tolerances and the same order of arithmetic, so the same offset is
//! chosen (docs/superpowers/specs/2026-09-30-give-way-native-move-design.md).

use crate::exact;
use crate::geometry::{point_in_polygon, point_segment_distance, point_segment_distance_below, Point};
use crate::shapes::{box_overlaps, clear_limit, conflict, may_meet, Blockers, Bounds, ConflictConfig, Shape, ShapeGrid};
use crate::shapes::IdSet;

/// `giveway._disc_inside`: whether the disc of radius `r` round `c` lies
/// inside `poly`: its centre inside, and every side at least `r` from it.
pub fn disc_inside(poly: &[Point], c: Point, r: f64) -> bool {
    if !point_in_polygon(c, poly) {
        return false;
    }
    let n = poly.len();
    // a side clearly further than `r` answers infinity, which is at least `r` as its exact distance is
    (0..n).all(|i| point_segment_distance_below(c, poly[i], poly[(i + 1) % n], r) >= r)
}

/// `giveway._still_meets`'s `still`: whether a via of radius `r` centred on
/// `c` still meets `poly`, the copper it first met: its centre in it, or
/// nearer it than `clr` less the DRC epsilon `eps`, plus `r`.
pub fn still_meets(poly: &[Point], clr: f64, r: f64, c: Point, eps: f64) -> bool {
    if point_in_polygon(c, poly) {
        return true;
    }
    let n = poly.len();
    // a side clearly further than the limit (a micrometre more, for rounding) answers infinity: the nearest
    // side is then not near enough, as its exact distance would say
    let lim = clear_limit(clr, eps);
    let limit = lim + r + 1e-6;
    let d = (0..n).map(|i| point_segment_distance_below(c, poly[i], poly[(i + 1) % n], limit)).fold(f64::INFINITY, f64::min);
    d - r < lim
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

/// Whether `c` lies within `reach` of `b` along both axes.
fn within(b: Bounds, c: Point, reach: f64) -> bool {
    c.0 >= b.0 - reach && c.0 <= b.2 + reach && c.1 >= b.1 - reach && c.1 <= b.3 + reach
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

/// `meets_any`, the one that last refused a shape tried first (`hint`, set to the one that refuses this): a yes
/// or no does not depend on which is asked first, and a spot next to the last is mostly refused by the same.
fn meets_any_hinted(s: &Shape, list: &[Shape], clearance: Option<f64>, cfg: &ConflictConfig, hint: &mut Option<usize>) -> bool {
    let gap = cfg.gap_for(s);
    let refuses = |o: &Shape| box_overlaps(o.bbox, s.bbox, gap) && may_meet(s.kind, o.kind) && conflict(s, o, clearance, cfg);
    if let Some(k) = *hint {
        if refuses(&list[k]) {
            return true;
        }
    }
    match list.iter().position(refuses) {
        Some(k) => {
            *hint = Some(k);
            true
        }
        None => false,
    }
}

/// `meets_board`, hinted as `meets_any_hinted`.
fn meets_board_hinted(grid: &ShapeGrid, s: &Shape, clearance: Option<f64>, cfg: &ConflictConfig, skip: &IdSet,
                      hint: &mut Option<usize>) -> bool {
    let refuses = |oi: usize| {
        !skip.contains(&oi) && may_meet(s.kind, grid.shapes[oi].kind) && conflict(s, &grid.shapes[oi], clearance, cfg)
    };
    if let Some(oi) = *hint {
        if box_overlaps(grid.shapes[oi].bbox, s.bbox, cfg.gap_for(s)) && refuses(oi) {
            return true;
        }
    }
    match grid.near(s.bbox, cfg.gap_for(s)).into_iter().find(|&oi| refuses(oi)) {
        Some(oi) => {
            *hint = Some(oi);
            true
        }
        None => false,
    }
}

/// Whether `s` meets a registered obstacle outside `skip`.
fn meets_board(grid: &ShapeGrid, s: &Shape, clearance: Option<f64>, cfg: &ConflictConfig, skip: &IdSet) -> bool {
    let gap = cfg.gap_for(s);
    grid.near(s.bbox, gap).into_iter().any(|oi| {
        !skip.contains(&oi) && may_meet(s.kind, grid.shapes[oi].kind) && conflict(s, &grid.shapes[oi], clearance, cfg)
    })
}

/// Whether none of `shapes` meets the board (less `skip`) or `mine`.
pub fn tail_clear(grid: &ShapeGrid, shapes: &[Shape], mine: &[Shape], clearance: Option<f64>, cfg: &ConflictConfig,
                  skip: &IdSet) -> bool {
    shapes.iter().all(|s| !meets_board(grid, s, clearance, cfg, skip) && !meets_any(s, mine, clearance, cfg))
}

/// Where `first_hit` found a conflict: the index of the shape asked about, whether the other was on the
/// board (`false`) or among `mine` (`true`), and its index there.
pub type Hit = (usize, bool, usize);

/// The first of `shapes` that meets the board (less `skip`) or `mine`, in `_Judge.hit`'s order: each shape
/// against the board's shapes near it, then against `mine`, before the next shape.
pub fn first_hit(grid: &ShapeGrid, shapes: &[Shape], mine: &[Shape], clearance: Option<f64>, cfg: &ConflictConfig,
                 skip: &IdSet) -> Option<Hit> {
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
    pub board: Option<&'a IdSet>,
}

/// The index in `offsets` (from `start`) of the first that passes every test `_give`'s loop applies, or
/// None. The ring and hole are clear of the board at every offset where `m.board` is None; where it is
/// set they are judged here, with the vias it names set aside, after the cheaper tests (a spot is taken
/// only when all pass, so the order does not change which).
#[allow(clippy::too_many_arguments)]
pub fn first_move(grid: &ShapeGrid, cfg: &ConflictConfig, m: &Move, offsets: &[(f64, f64)], clearance: Option<f64>,
                  skip: &IdSet, start: usize) -> Option<usize> {
    let mut hint = Blockers::new(m.via);
    let mut mine_hint: Vec<Option<usize>> = vec![None; m.via.len()];
    let (mut tail_board_hint, mut tail_mine_hint) = (None, None);
    let mut moved: Vec<Shape> = m.via.to_vec();
    let mut tail: Option<Shape> = None;
    let pad_box = m.pad.map_or((0.0, 0.0, 0.0, 0.0), |(poly, _)| bounds(poly));
    let first_box = m.first.map_or((0.0, 0.0, 0.0, 0.0), |(poly, _, _)| bounds(poly));
    'offsets: for (i, &(dx, dy)) in offsets.iter().enumerate().skip(start) {
        let to = (exact::round9(m.centre.0 + dx), exact::round9(m.centre.1 + dy));
        if let Some((poly, r)) = m.pad {
            if !within(pad_box, to, 0.0) || !disc_inside(poly, to, r) {
                continue;               // a centre outside the box of the pad is outside the pad
            }
        }
        if let Some((poly, clr, r)) = m.first {
            // a centre further from the box of what it met than the clearance and the radius is neither in it
            // nor near enough (a micrometre more, for rounding): the test is spared
            if within(first_box, to, clr + r + 1e-6) && still_meets(poly, clr, r, to, cfg.epsilon) {
                continue;
            }
        }
        for (k, s0) in m.via.iter().enumerate() {
            let bbox = (s0.bbox.0 + dx, s0.bbox.1 + dy, s0.bbox.2 + dx, s0.bbox.3 + dy);
            let gap = cfg.gap_for(s0);
            if !m.mine.iter().any(|o| box_overlaps(o.bbox, bbox, gap)) {
                continue;
            }
            let s = &mut moved[k];              // the shape at this offset, drawn over the copy kept for the loop
            for (q, p) in s.poly.iter_mut().zip(&s0.poly) {
                *q = (p.0 + dx, p.1 + dy);
            }
            s.bbox = bbox;
            if meets_any_hinted(s, m.mine, clearance, cfg, &mut mine_hint[k]) {
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
            // the tail drawn at this offset, over one copy of its prototype kept for the loop
            let s = tail.get_or_insert_with(|| Shape { poly: Vec::new(), ..proto.clone() });
            s.bbox = bounds(&poly);
            s.poly = poly;
            if meets_board_hinted(grid, s, clearance, cfg, skip, &mut tail_board_hint)
                || meets_any_hinted(s, m.mine, clearance, cfg, &mut tail_mine_hint)
            {
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

    fn square(cx: f64, cy: f64, half: f64) -> Vec<Point> {
        vec![(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]
    }

    fn cfg() -> ConflictConfig {
        ConflictConfig {
            touch: 0.02, vias_block_courtyards: false, silk_clearance: 0.1, component_spacing: 0.2,
            default_clearance: 0.2, net_clearance: crate::shapes::NetMap::default(), rules: Vec::new(), gap: 1.0, drawn_gap: 0.2, hole_to_hole: 0.25,
            hole_clearance: 0.0, max_clearance: 0.2, epsilon: 1e-9,
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
        assert!(still_meets(&poly, 0.2, 0.25, (0.0, 0.0), 1e-9));
        assert!(still_meets(&poly, 0.2, 0.25, (1.4, 0.0), 1e-9));      // 0.4 from the side, less 0.25 is 0.15 < 0.2
        assert!(!still_meets(&poly, 0.2, 0.25, (1.5, 0.0), 1e-9));     // 0.5 - 0.25 = 0.25 >= 0.2
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
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &IdSet::default(), 0), Some(2));
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &IdSet::default(), 3), None);
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
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &IdSet::default(), 0), Some(1));
        let skip: IdSet = [0].into_iter().collect();
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
        assert_eq!(first_move(&grid, &cfg(), &m, &offsets, Some(0.2), &IdSet::default(), 0), Some(2));
    }

    #[test]
    fn first_hit_names_the_shape_and_where_the_other_was() {
        let grid = ShapeGrid::new(vec![copper(Kind::Pad, square(0.0, 0.0, 0.3), "B"), copper(Kind::Pad, square(5.0, 0.0, 0.3), "B")]);
        let near_second = copper(Kind::Copper, square(5.0, 0.4, 0.1), "A");
        let far = copper(Kind::Copper, square(20.0, 0.0, 0.1), "A");
        let mine = vec![copper(Kind::Pad, square(20.0, 0.3, 0.1), "B")];
        let skip = IdSet::default();
        assert_eq!(first_hit(&grid, &[far.clone(), near_second.clone()], &[], Some(0.2), &cfg(), &skip), Some((1, false, 1)));
        assert_eq!(first_hit(&grid, &[far.clone()], &mine, Some(0.2), &cfg(), &skip), Some((0, true, 0)));
        let skipped: IdSet = [1].into_iter().collect();
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
            let skip: IdSet = (0..40).filter(|i| i % 9 == round % 9).collect();
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
    fn the_quick_tests_answer_what_the_exact_distances_do() {
        let mut state = 29u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let (mut a, mut b, mut c, mut d) = (0, 0, 0, 0);
        for _ in 0..30000 {
            let n = 3 + (next() * 14.0) as usize;
            let (cx, cy, rad) = (next() * 4.0, next() * 4.0, 0.2 + next() * 1.5);
            let poly: Vec<Point> = (0..n).map(|i| {
                let t = (i as f64 + next() * 0.4) * std::f64::consts::TAU / n as f64;
                let r = rad * (0.5 + next() * 0.5);
                (cx + r * t.cos(), cy + r * t.sin())
            }).collect();
            let p = (cx + (next() - 0.5) * 3.0 * rad, cy + (next() - 0.5) * 3.0 * rad);
            let (clr, r) = (0.05 + next() * 0.4, 0.05 + next() * 0.5);
            let edges: Vec<f64> = (0..n).map(|i| point_segment_distance(p, poly[i], poly[(i + 1) % n])).collect();
            // the exact answers, as the functions were before the quick way out
            let inside_ref = point_in_polygon(p, &poly) && edges.iter().all(|&d| d >= r);
            let still_ref = point_in_polygon(p, &poly) || edges.iter().cloned().fold(f64::INFINITY, f64::min) - r < clr - 1e-9;
            assert_eq!(disc_inside(&poly, p, r), inside_ref);
            assert_eq!(still_meets(&poly, clr, r, p, 1e-9), still_ref);
            // and at the thresholds themselves
            let near = edges.iter().cloned().fold(f64::INFINITY, f64::min);
            for rr in [near, near + 1e-12, near - 1e-12] {
                if rr > 0.0 {
                    assert_eq!(disc_inside(&poly, p, rr), point_in_polygon(p, &poly) && edges.iter().all(|&d| d >= rr));
                    let cc = near - rr + 1e-9;
                    assert_eq!(still_meets(&poly, cc.max(0.0), rr, p, 1e-9),
                               point_in_polygon(p, &poly) || near - rr < cc.max(0.0) - 1e-9);
                }
            }
            if inside_ref { a += 1 } else { b += 1 }
            if still_ref { c += 1 } else { d += 1 }
        }
        assert!(a > 1000 && b > 1000 && c > 1000 && d > 1000, "{a} {b} {c} {d}");
    }

    #[test]
    fn a_centre_outside_the_box_is_not_inside_or_near_enough() {
        let mut state = 23u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let (mut outside, mut inside) = (0, 0);
        for _ in 0..20000 {
            let n = 3 + (next() * 9.0) as usize;
            let (cx, cy, rad) = (next() * 4.0, next() * 4.0, 0.2 + next() * 1.5);
            let poly: Vec<Point> = (0..n).map(|i| {
                let t = (i as f64 + next() * 0.4) * std::f64::consts::TAU / n as f64;
                let r = rad * (0.5 + next() * 0.5);
                (cx + r * t.cos(), cy + r * t.sin())
            }).collect();
            let c = (next() * 6.0 - 1.0, next() * 6.0 - 1.0);
            let (clr, r) = (0.1 + next() * 0.3, 0.1 + next() * 0.4);
            let b = bounds(&poly);
            if !within(b, c, 0.0) {
                assert!(!disc_inside(&poly, c, r));
            }
            if !within(b, c, clr + r + 1e-6) {
                assert!(!still_meets(&poly, clr, r, c, 1e-9));
                outside += 1;
            } else {
                inside += 1;
            }
        }
        assert!(outside > 2000 && inside > 2000, "{outside} {inside}");
    }

    #[test]
    fn a_hinted_test_answers_what_the_plain_one_does() {
        let mut state = 31u64;
        let mut next = move || {
            state = state.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let c = cfg();
        let (mut yes, mut no) = (0, 0);
        for round in 0..200 {
            let mk = |next: &mut dyn FnMut() -> f64, n: usize| -> Vec<Shape> {
                (0..n).map(|_| {
                    let kind = [Kind::Pad, Kind::Copper, Kind::Through][(next() * 3.0) as usize % 3];
                    copper(kind, square(next() * 5.0, next() * 5.0, 0.1 + next() * 0.4), ["A", "B", "C"][(next() * 3.0) as usize % 3])
                }).collect()
            };
            let board = mk(&mut next, 30);
            let mine = mk(&mut next, 12);
            let grid = ShapeGrid::new(board);
            let skip: IdSet = (0..30).filter(|i| i % 7 == round % 7).collect();
            let (mut hint_mine, mut hint_board) = (None, None);
            for _ in 0..60 {
                let probe = copper(Kind::Copper, square(next() * 5.0, next() * 5.0, 0.1 + next() * 0.3), ["A", "B"][(next() * 2.0) as usize % 2]);
                let want_mine = meets_any(&probe, &mine, Some(0.2), &c);
                assert_eq!(meets_any_hinted(&probe, &mine, Some(0.2), &c, &mut hint_mine), want_mine);
                let want_board = meets_board(&grid, &probe, Some(0.2), &c, &skip);
                assert_eq!(meets_board_hinted(&grid, &probe, Some(0.2), &c, &skip, &mut hint_board), want_board);
                if want_mine || want_board { yes += 1 } else { no += 1 }
            }
        }
        assert!(yes > 1000 && no > 1000, "{yes} {no}");
    }

    #[test]
    fn tail_clear_is_false_when_a_shape_meets_mine() {
        let grid = ShapeGrid::new(vec![]);
        let tail = copper(Kind::Copper, square(0.0, 0.0, 0.1), "A");
        let near = vec![copper(Kind::Pad, square(0.3, 0.0, 0.1), "B")];
        assert!(!tail_clear(&grid, &[tail.clone()], &near, Some(0.2), &cfg(), &IdSet::default()));
        assert!(tail_clear(&grid, &[tail], &[], Some(0.2), &cfg(), &IdSet::default()));
    }
}
