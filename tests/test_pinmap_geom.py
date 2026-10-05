"""The pin map study's airwire model: a pin leaves along its outward normal to a point past the courtyard, then goes the
shorter way round the courtyard's box to its target; the bend is the angle between the normal and the bearing to the
target; a pose turns the part about its centre, and mirrors it for the other face."""
import pytest

from placemat.pinmap_geom import Pose, bend, exit_of, route, through

HW = HH = 2.0           # a 4 mm square body


def east_exit(pose=Pose(10, 10), y=0.5):
    return exit_of("U1", pose, 2.0, y, (1.0, 0.0), HW, HH, 0.5)


def test_the_exit_point_is_the_margin_past_the_box_on_the_pins_side():
    e = east_exit()
    assert e.at == (12.5, 10.5) and e.normal == (1.0, 0.0) and e.side == 0


def test_a_pin_on_each_side_exits_past_that_side():
    p = Pose(10, 10)
    s = exit_of("U1", p, 0.5, 2.0, (0.0, 1.0), HW, HH, 0.5)
    w = exit_of("U1", p, -2.0, -0.5, (-1.0, 0.0), HW, HH, 0.5)
    n = exit_of("U1", p, -0.5, -2.0, (0.0, -1.0), HW, HH, 0.5)
    assert (s.at, s.normal, s.side) == ((10.5, 12.5), (0.0, 1.0), 1)
    assert (w.at, w.normal, w.side) == ((7.5, 9.5), (-1.0, 0.0), 2)
    assert (n.at, n.normal, n.side) == ((9.5, 7.5), (0.0, -1.0), 3)


def test_a_target_in_sight_is_reached_straight():
    assert route(east_exit(), (20.0, 10.5)) == ((12.5, 10.5), (20.0, 10.5))
    assert route(east_exit(), (10.0, 30.0)) == ((12.5, 10.5), (10.0, 30.0))


def test_a_target_behind_the_part_is_reached_round_its_body_the_shorter_way_and_never_through_it():
    path = route(east_exit(), (0.0, 10.0))
    assert path == ((12.5, 10.5), (12.5, 12.5), (7.5, 12.5), (0.0, 10.0))         # south of it: nearer the pin
    path = route(east_exit(y=-0.5), (0.0, 10.0))
    assert path == ((12.5, 9.5), (12.5, 7.5), (7.5, 7.5), (0.0, 10.0))           # north of it
    for p, q in zip(path, path[1:]):
        assert not through((p[0] - 10, p[1] - 10), (q[0] - 10, q[1] - 10), HW, HH)


def test_a_target_inside_the_body_is_reached_straight():
    assert route(east_exit(), (9.0, 10.0)) == ((12.5, 10.5), (9.0, 10.0))


def test_a_quarter_turn_takes_an_east_pin_north_and_the_other_face_takes_it_west():
    e = east_exit(Pose(10, 10, 90.0))
    assert e.at == (10.5, 7.5) and e.normal == (0.0, -1.0)
    e = east_exit(Pose(10, 10, 0.0, True))
    assert e.at == (7.5, 10.5) and e.normal == (-1.0, 0.0)
    e = east_exit(Pose(10, 10, 90.0, True))                            # mirrored, then turned: south
    assert e.at == (10.5, 12.5) and e.normal == (0.0, 1.0)


def test_an_airwire_between_two_studied_pins_goes_round_both_bodies():
    a = exit_of("U1", Pose(10, 10), -2.0, 0.0, (-1.0, 0.0), HW, HH, 0.5)
    b = exit_of("U2", Pose(20, 10), 2.0, 0.0, (1.0, 0.0), HW, HH, 0.5)
    assert route(a, b) == ((7.5, 10.0), (7.5, 7.5), (12.5, 7.5), (22.5, 7.5), (22.5, 10.0))
    a = east_exit(Pose(10, 10))
    b = exit_of("U2", Pose(30, 10), 2.0, 0.5, (1.0, 0.0), HW, HH, 0.5)     # U2's pin faces away from U1
    path = route(a, b)
    assert path[0] == a.at and path[-1] == b.at
    assert (32.5, 12.5) in path                                        # round U2's south-east corner to its exit
    for p, q in zip(path, path[1:]):
        assert not through((p[0] - 30, p[1] - 10), (q[0] - 30, q[1] - 10), HW, HH)
        assert not through((p[0] - 10, p[1] - 10), (q[0] - 10, q[1] - 10), HW, HH)


def test_the_bend_is_the_angle_from_the_normal_to_the_target():
    assert bend((1.0, 0.0), (12.5, 10.5), (20.0, 10.5)) == 0.0
    assert bend((1.0, 0.0), (12.5, 10.5), (12.5, 20.0)) == pytest.approx(90.0)
    assert bend((1.0, 0.0), (12.5, 10.0), (0.0, 10.0)) == pytest.approx(180.0)
    assert bend((1.0, 0.0), (12.5, 10.0), (20.0, 2.5)) == pytest.approx(45.0)


def test_the_way_back_to_the_part_frame_is_not_rounded():
    p = Pose(10.0, 10.0, 30.0)
    x, y = p.to_local(13.0, 7.0)
    assert (x, y) != (round(x, 9), round(y, 9))
