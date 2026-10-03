"""The 3D placement chain, composed once in Python: a model's own frame to the scene frame (x = board x, y = up, z = board y, millimetres), checked
against corners worked out by hand. Front and back, turned, offset, rotated and scaled by the model entry, moved and flipped by the plan."""
import math

import pytest

from placemat.geometry import Location, Transform
from placemat import model_place as mp

T = 1.6
PF, PB = T - 0.005, -0.085           # the model planes of a 1.6 mm board (KiCad's export: front T - 0.005, back -0.085)


def at(m, v):
    """The scene point a column-major 4x4 `m` (three.js's Matrix4 order) sends the model point `v` to."""
    x, y, z = v
    return tuple(m[i] * x + m[4 + i] * y + m[8 + i] * z + m[12 + i] for i in range(3))


def same(a, b, tol=1e-5):
    return all(abs(p - q) < tol for p, q in zip(a, b))


def entry(off=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    return ("m.step", off, rot, scale, True, 1.0)


def test_the_planes_follow_the_board_thickness():
    assert mp.planes(1.6) == pytest.approx((1.595, -0.085))
    assert mp.planes(0.8) == pytest.approx((0.795, -0.085))


def test_a_front_part_is_the_model_on_the_footprints_page_with_y_down_and_height_up():
    m = mp.placement(entry(), location=(10, 20), rotation=0, face="front", thickness=T)
    assert same(at(m, (4, 0, 1)), (14, PF + 1, 20))                  # x right, z up
    assert same(at(m, (0, 2, 0)), (10, PF, 18))                      # the model's y up the page: the board's y falls
    assert same(at(m, (0, 0, 0)), (10, PF, 20))


def test_the_footprints_orientation_turns_counter_clockwise_on_screen():
    m = mp.placement(entry(), location=(10, 20), rotation=90, face="front", thickness=T)
    assert same(at(m, (4, 0, 0)), (10, PF, 16))                       # to the right, turned 90: up the screen
    m = mp.placement(entry(), location=(10, 20), rotation=-50, face="front", thickness=T)
    c, s = math.cos(math.radians(-50)), math.sin(math.radians(-50))
    assert same(at(m, (4, 0, 0)), (10 + 4 * c, PF, 20 - 4 * s))


def test_a_back_part_keeps_x_and_y_and_hangs_below_the_back_plane():
    m = mp.placement(entry(), location=(10, 20), rotation=0, face="back", thickness=T)
    assert same(at(m, (4, 0, 1)), (14, PB - 1, 20))
    assert same(at(m, (0, 2, 0)), (10, PB, 22))                       # not mirrored in y: the back's y runs the other way on the page


def test_the_model_entry_scales_turns_x_then_y_then_z_by_the_negated_angles_and_offsets():
    m = mp.placement(entry(off=(1, 2, 3), rot=(0, 0, 90), scale=(2, 1, 0.5)), location=(10, 20), rotation=0, face="front", thickness=T)
    assert same(at(m, (1, 0, 0)), (11, PF + 3, 20))                   # (2,0,0) turned by -90 about z: (0,-2,0), plus (1,2,3): (1,0,3)
    assert same(at(m, (0, 0, 2)), (11, PF + 4, 18))                   # scaled (0,0,1), turned about z (unchanged), plus (1,2,3): (1,2,4); front: (1,-2)
    m = mp.placement(entry(rot=(90, 0, 0)), location=(0, 0), rotation=0, face="front", thickness=T)
    assert same(at(m, (0, 1, 0)), (0, PF - 1, 0))                     # about x by -90: y goes to -z
    m = mp.placement(entry(rot=(-90, 0, 0)), location=(0, 0), rotation=0, face="front", thickness=T)
    assert same(at(m, (0, 1, 0)), (0, PF + 1, 0))


def test_a_plan_move_without_a_flip_moves_x_and_y_and_keeps_the_height():
    plan = Transform.translate(-10, -20).then(Transform.rotate(90)).then(Transform.translate(50, 60))      # the part turned 90 and moved
    m = mp.placement(entry(), location=(10, 20), rotation=0, face="front", to=plan, thickness=T)
    assert same(at(m, (4, 0, 1)), (50, PF + 1, 56))                    # (4, 0) turned 90: (0, -4), then to (50, 60)


def test_a_plan_flip_mirrors_about_the_vertical_axis_and_mirrors_the_height_about_the_board():
    flip = Transform.translate(-10, -20).then(Transform.mirror_x(Location(0, 0))).then(Transform.translate(50, 60))
    m = mp.placement(entry(), location=(10, 20), rotation=0, face="front", to=flip, flipped=True, thickness=T)
    x, y, z = at(m, (4, 0, 1))
    assert (round(x, 6), round(z, 6)) == (46, 60) and y == pytest.approx(PB - 1)           # z' = PF + PB - (PF + 1)
    # a model point at the part's own face: the part has gone to the back, so its face is the back plane
    assert at(m, (0, 0, 0))[1] == pytest.approx(PB)


def test_the_matrix_is_sent_column_major_to_a_hundredth_of_a_micrometre_and_is_a_rigid_turn_for_unit_scale():
    m = mp.placement(entry(rot=(30, 20, 70)), location=(10.123456, 20.654321), rotation=33, face="back", thickness=T)
    assert len(m) == 16 and m[3] == m[7] == m[11] == 0 and m[15] == 1
    cols = [m[0:3], m[4:7], m[8:11]]
    for c in cols:
        assert math.sqrt(sum(v * v for v in c)) == pytest.approx(1.0, abs=1e-5)
    det = (m[0] * (m[5] * m[10] - m[9] * m[6]) - m[4] * (m[1] * m[10] - m[9] * m[2]) + m[8] * (m[1] * m[6] - m[5] * m[2]))
    assert det > 0                                                    # not mirrored: instanced meshes keep their winding


def test_a_scale_that_mirrors_makes_a_matrix_the_viewer_can_tell_by_its_determinant():
    m = mp.placement(entry(scale=(-1, 1, 1)), location=(0, 0), rotation=0, face="front", thickness=T)
    det = (m[0] * (m[5] * m[10] - m[9] * m[6]) - m[4] * (m[1] * m[10] - m[9] * m[2]) + m[8] * (m[1] * m[6] - m[5] * m[2]))
    assert det < 0


def test_the_board_thickness_is_read_from_the_boards_text(tmp_path):
    p = tmp_path / "a.kicad_pcb"
    p.write_text('(kicad_pcb (version 1) (general (thickness 0.8) (legacy_teardrops no)) (layers))')
    assert mp.board_thickness(str(p)) == 0.8
    p.write_text("(kicad_pcb (version 1))")
    assert mp.board_thickness(str(p)) == 1.6                          # KiCad's default
    assert mp.board_thickness(str(tmp_path / "gone.kicad_pcb")) == 1.6
