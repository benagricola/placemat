//! The pin map study's airwire model (`placemat.pinmap_geom`, its Python twin), for the native core (pinmap.rs), which
//! asks it for every net a move puts on a pin it has not stood on before.
//!
//! A studied part's body is its courtyard's box. A pin's airwire leaves along the pin's outward normal - the side of the
//! box it is nearest - to its exit point, `margin` past the box, then takes the shorter way round the box grown by
//! `margin` to its target, corner to corner, until the target is in sight. A target inside the body's box is reached
//! straight. The bend at a pin is the angle between its outward normal and the bearing from its exit point to its
//! target. A `Pose` turns the part's own frame (the board's, moved to the courtyard box's centre and turned by what the
//! part's rotation is off the axes) about that centre, counter-clockwise on screen with y down, mirrored left to right
//! first for the other face.
//!
//! Every value is Python's: `clean9` is `geometry._clean`, `hypot` CPython's, angles go through CPython's `radians`
//! (`x * (pi / 180)`) and `degrees` (`(180 / pi) * x`), and sums are plain, in order.

use crate::exact::{clean9, hypot};

const EPS: f64 = 1e-9;
const SIDES: [(f64, f64); 4] = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]; // east, south, west, north
const DEG_TO_RAD: f64 = std::f64::consts::PI / 180.0; // CPython's degToRad
const RAD_TO_DEG: f64 = 180.0 / std::f64::consts::PI; // and its radToDeg

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pose {
    pub cx: f64,
    pub cy: f64,
    pub turn: f64,
    pub flip: bool,
}

impl Pose {
    pub fn new(cx: f64, cy: f64, turn: f64, flip: bool) -> Pose {
        Pose { cx, cy, turn, flip }
    }

    fn cs(&self) -> (f64, f64) {
        let r = self.turn * DEG_TO_RAD;
        (r.cos(), r.sin())
    }

    /// A direction in the part's own frame, in the board's.
    pub fn vector(&self, x: f64, y: f64) -> (f64, f64) {
        let x = if self.flip { -x } else { x };
        let (c, s) = self.cs();
        (clean9(c * x + s * y), clean9(-s * x + c * y))
    }

    pub fn to_board(self, x: f64, y: f64) -> (f64, f64) {
        let (vx, vy) = self.vector(x, y);
        (clean9(self.cx + vx), clean9(self.cy + vy))
    }

    pub fn to_local(self, x: f64, y: f64) -> (f64, f64) {
        let (dx, dy) = (x - self.cx, y - self.cy);
        let (c, s) = self.cs();
        let lx = c * dx - s * dy;
        let ly = s * dx + c * dy;
        (if self.flip { -lx } else { lx }, ly)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Exit {
    pub at: (f64, f64),
    pub local: (f64, f64),
    pub normal: (f64, f64),
    pub side: usize,
    pub pose: Pose,
    pub hw: f64,
    pub hh: f64,
    pub margin: f64,
}

/// The exit of a pin at (x, y) in the part's frame with outward `normal` (its frame), at `pose`.
pub fn exit_of(pose: Pose, x: f64, y: f64, normal: (f64, f64), hw: f64, hh: f64, margin: f64) -> Exit {
    let side = SIDES.iter().position(|s| *s == normal);
    debug_assert!(side.is_some(), "the normal {normal:?} is not an axis");
    let side = side.unwrap_or(0); // pinmap_search refuses such a normal before it gets here
    let local = [(hw + margin, y), (x, hh + margin), (-hw - margin, y), (x, -hh - margin)][side];
    Exit { at: pose.to_board(local.0, local.1), local, normal: pose.vector(normal.0, normal.1), side, pose, hw, hh, margin }
}

/// Whether segment p-q passes through the inside of the box (-hw, -hh)-(hw, hh).
pub fn through(p: (f64, f64), q: (f64, f64), hw: f64, hh: f64) -> bool {
    let (x0, y0) = p;
    let (dx, dy) = (q.0 - x0, q.1 - y0);
    let (mut t0, mut t1) = (0.0f64, 1.0f64);
    for (pp, qq) in [(-dx, x0 + hw), (dx, hw - x0), (-dy, y0 + hh), (dy, hh - y0)] {
        if pp.abs() < 1e-15 {
            if qq <= EPS {
                return false;
            }
            continue;
        }
        let r = qq / pp;
        if pp < 0.0 {
            if r > t0 {
                t0 = r;
            }
        } else if r < t1 {
            t1 = r;
        }
        if t1 - t0 <= EPS {
            return false;
        }
    }
    let mx = x0 + dx * (t0 + t1) / 2.0;
    let my = y0 + dy * (t0 + t1) / 2.0;
    -hw + EPS < mx && mx < hw - EPS && -hh + EPS < my && my < hh - EPS
}

/// A path's length, segment by segment in order.
pub fn length(points: &[(f64, f64)]) -> f64 {
    let mut total = 0.0;
    for w in points.windows(2) {
        total += hypot(w[1].0 - w[0].0, w[1].1 - w[0].1);
    }
    total
}

/// The way from exit `e` to `target` (board frame) round e's body: [e.at, corners..., target].
pub fn round_body(e: &Exit, target: (f64, f64)) -> Vec<(f64, f64)> {
    let t = e.pose.to_local(target.0, target.1);
    let (hw, hh) = (e.hw, e.hh);
    if (-hw < t.0 && t.0 < hw && -hh < t.1 && t.1 < hh) || !through(e.local, t, hw, hh) {
        return vec![e.at, target];
    }
    let (w, h) = (hw + e.margin, hh + e.margin);
    let corners = [(w, -h), (w, h), (-w, h), (-w, -h)]; // north-east, south-east, south-west, north-west
    let after = [1usize, 2, 3, 0];
    let mut best: Option<(f64, Vec<(f64, f64)>)> = None;
    for step in [1i64, -1] {
        let mut k = if step == 1 { after[e.side] } else { (after[e.side] + 3) % 4 };
        let mut local = vec![e.local];
        for _ in 0..4 {
            let c = corners[k];
            local.push(c);
            if !through(c, t, hw, hh) {
                break;
            }
            k = ((k as i64 + step + 4) % 4) as usize;
        }
        local.push(t);
        let n = length(&local);
        let better = match &best {
            None => true,
            Some((b, _)) => n < *b - EPS,
        };
        if better {
            best = Some((n, local));
        }
    }
    let local = best.map(|b| b.1).unwrap_or_default();
    let mut pts = vec![e.at];
    for c in &local[1..local.len() - 1] {
        pts.push(e.pose.to_board(c.0, c.1));
    }
    pts.push(target);
    pts
}

/// One end of an airwire: a studied pin's exit, or a point.
#[derive(Clone, Copy, Debug)]
pub enum End {
    Exit(Exit),
    Point((f64, f64)),
}

impl End {
    fn at(&self) -> (f64, f64) {
        match self {
            End::Exit(e) => e.at,
            End::Point(p) => *p,
        }
    }
}

/// An airwire's path from `a` to `b`: round the body of each end that is an exit, the second end's from the last turn
/// the first one's path makes.
pub fn route(a: &End, b: &End) -> Vec<(f64, f64)> {
    let (pa, pb) = (a.at(), b.at());
    let mut pts = match a {
        End::Exit(e) => round_body(e, pb),
        End::Point(_) => vec![pa, pb],
    };
    if let End::Exit(e) = b {
        let back = round_body(e, pts[pts.len() - 2]);
        pts.pop();
        pts.extend(back.iter().rev().skip(1));
    }
    pts
}

/// Degrees between a pin's outward `normal` and the bearing from its exit point `at` to `target`.
pub fn bend(normal: (f64, f64), at: (f64, f64), target: (f64, f64)) -> f64 {
    let (dx, dy) = (target.0 - at.0, target.1 - at.1);
    let d = hypot(dx, dy);
    if d <= EPS {
        return 0.0;
    }
    let cos = ((normal.0 * dx + normal.1 * dy) / d).clamp(-1.0, 1.0);
    RAD_TO_DEG * cos.acos()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn east(pose: Pose, y: f64) -> Exit {
        exit_of(pose, 2.0, y, (1.0, 0.0), 2.0, 2.0, 0.5)
    }

    #[test]
    fn a_target_in_sight_is_straight_and_one_behind_goes_round_the_shorter_way() {
        let e = east(Pose::new(10.0, 10.0, 0.0, false), 0.5);
        assert_eq!(e.at, (12.5, 10.5));
        assert_eq!(route(&End::Exit(e), &End::Point((20.0, 10.5))), vec![(12.5, 10.5), (20.0, 10.5)]);
        assert_eq!(route(&End::Exit(e), &End::Point((0.0, 10.0))), vec![(12.5, 10.5), (12.5, 12.5), (7.5, 12.5), (0.0, 10.0)]);
        assert_eq!(route(&End::Exit(e), &End::Point((9.0, 10.0))), vec![(12.5, 10.5), (9.0, 10.0)]);
    }

    #[test]
    fn a_quarter_turn_takes_an_east_pin_north_and_a_flip_takes_it_west() {
        let e = east(Pose::new(10.0, 10.0, 90.0, false), 0.5);
        assert_eq!((e.at, e.normal), ((10.5, 7.5), (0.0, -1.0)));
        let e = east(Pose::new(10.0, 10.0, 0.0, true), 0.5);
        assert_eq!((e.at, e.normal), ((7.5, 10.5), (-1.0, 0.0)));
    }

    #[test]
    fn the_bend_is_the_angle_from_the_normal_to_the_target() {
        assert_eq!(bend((1.0, 0.0), (12.5, 10.5), (20.0, 10.5)), 0.0);
        assert!((bend((1.0, 0.0), (12.5, 10.0), (0.0, 10.0)) - 180.0).abs() < 1e-9);
        assert!((bend((1.0, 0.0), (12.5, 10.0), (20.0, 2.5)) - 45.0).abs() < 1e-9);
        assert!((bend((1.0, 0.0), (12.5, 10.0), (12.5, 20.0)) - 90.0).abs() < 1e-9);
    }

    #[test]
    fn a_pin_on_each_side_exits_past_that_side() {
        let p = Pose::new(10.0, 10.0, 0.0, false);
        let s = exit_of(p, 0.5, 2.0, (0.0, 1.0), 2.0, 2.0, 0.5);
        let w = exit_of(p, -2.0, -0.5, (-1.0, 0.0), 2.0, 2.0, 0.5);
        let n = exit_of(p, -0.5, -2.0, (0.0, -1.0), 2.0, 2.0, 0.5);
        assert_eq!((s.at, s.normal, s.side), ((10.5, 12.5), (0.0, 1.0), 1));
        assert_eq!((w.at, w.normal, w.side), ((7.5, 9.5), (-1.0, 0.0), 2));
        assert_eq!((n.at, n.normal, n.side), ((9.5, 7.5), (0.0, -1.0), 3));
    }

    #[test]
    fn a_pin_north_of_the_centre_goes_round_the_north_corners() {
        let e = east(Pose::new(10.0, 10.0, 0.0, false), -0.5);
        assert_eq!(route(&End::Exit(e), &End::Point((0.0, 10.0))), vec![(12.5, 9.5), (12.5, 7.5), (7.5, 7.5), (0.0, 10.0)]);
    }

    #[test]
    fn a_flip_then_a_quarter_turn_takes_an_east_pin_south() {
        let e = east(Pose::new(10.0, 10.0, 90.0, true), 0.5);
        assert_eq!((e.at, e.normal), ((10.5, 12.5), (0.0, 1.0)));
    }

    #[test]
    fn an_airwire_between_two_exits_goes_round_both_bodies() {
        let a = exit_of(Pose::new(10.0, 10.0, 0.0, false), -2.0, 0.0, (-1.0, 0.0), 2.0, 2.0, 0.5);
        let b = exit_of(Pose::new(20.0, 10.0, 0.0, false), 2.0, 0.0, (1.0, 0.0), 2.0, 2.0, 0.5);
        assert_eq!(route(&End::Exit(a), &End::Exit(b)),
                   vec![(7.5, 10.0), (7.5, 7.5), (12.5, 7.5), (22.5, 7.5), (22.5, 10.0)]);
    }

    #[cfg(debug_assertions)]
    #[test]
    #[should_panic(expected = "not an axis")]
    fn a_normal_off_the_axes_is_refused() {
        exit_of(Pose::new(0.0, 0.0, 0.0, false), 1.0, 1.0, (0.6, 0.8), 2.0, 2.0, 0.5);
    }
}
