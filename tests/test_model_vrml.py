"""The VRML 2 reader: a model with no STEP beside it, read by placemat itself (the unit is 0.1 inch)."""
import math

import pytest

from placemat import model_mesh as mm
from placemat import model_vrml as vr

BOX = """#VRML V2.0 utf8
# a comment
Transform {
  translation 0 0 0
  children [
    Shape {
      appearance Appearance { material DEF M Material { diffuseColor 0.8 0.1 0.1 transparency 0.25 } }
      geometry IndexedFaceSet {
        creaseAngle 0.5
        coordIndex [ 0 1 2 3 -1  4 7 6 5 -1  0 4 5 1 -1  1 5 6 2 -1  2 6 7 3 -1  3 7 4 0 -1 ]
        coord Coordinate { point [ 0 0 0, 1 0 0, 1 1 0, 0 1 0, 0 0 1, 1 0 1, 1 1 1, 0 1 1 ] }
      }
    }
  ]
}
"""


def test_a_box_is_read_as_triangles_in_millimetres_with_its_colour_and_opacity():
    mesh = vr.read_vrml(BOX)
    assert mm.triangles(mesh) == 12                                  # six quads, each fanned to two triangles
    x0, y0, z0, x1, y1, z1 = mm.bbox(mesh)
    assert (x0, y0, z0) == pytest.approx((0, 0, 0)) and (x1, y1, z1) == pytest.approx((2.54, 2.54, 2.54))        # 1 unit = 0.1 inch
    (m,) = mesh.materials
    assert m.colour == (204, 26, 26) and m.opacity == pytest.approx(0.75)


def test_a_sharp_edge_keeps_its_two_normals_and_a_smooth_one_shares_them():
    flat = vr.read_vrml(BOX.replace("creaseAngle 0.5", "creaseAngle 0.1"))
    (m,) = flat.materials
    for v in range(len(m.positions) // 3):
        n = m.normals[3 * v:3 * v + 3]
        assert math.isclose(sum(c * c for c in n), 1.0, abs_tol=1e-5) and sorted(abs(c) for c in n)[:2] == pytest.approx([0, 0], abs=1e-5)   # on one axis
    smooth = vr.read_vrml(BOX.replace("creaseAngle 0.5", "creaseAngle 3.2"))
    assert len(smooth.materials[0].positions) < len(m.positions)     # corners share their averaged normal


def test_def_and_use_share_a_material_and_a_coordinate_list():
    text = """#VRML V2.0 utf8
    DEF Pts Coordinate { point [ 0 0 0, 1 0 0, 0 1 0 ] }
    Shape { appearance Appearance { material DEF Red Material { diffuseColor 1 0 0 } } geometry IndexedFaceSet { coordIndex [0 1 2 -1] coord USE Pts } }
    Shape { appearance Appearance { material USE Red } geometry IndexedFaceSet { coordIndex [2 1 0 -1] coord USE Pts } }
    """
    mesh = vr.read_vrml(text)
    assert mm.triangles(mesh) == 2 and len(mesh.materials) == 1 and mesh.materials[0].colour == (255, 0, 0)


def test_a_transform_scales_turns_and_moves_its_children():
    text = """#VRML V2.0 utf8
    Transform { translation 1 0 0 rotation 0 0 1 1.5707963 scale 2 2 2 children [
      Shape { geometry IndexedFaceSet { coordIndex [0 1 2 -1] coord Coordinate { point [ 0 0 0, 1 0 0, 0 1 0 ] } } } ] }
    """
    mesh = vr.read_vrml(text)
    p = mesh.materials[0].positions
    pts = sorted((round(p[3 * i], 4), round(p[3 * i + 1], 4)) for i in range(3))
    k = 2.54                                                         # the point (1,0): scaled 2, turned 90 about z to (0, 2), moved by 1
    assert pts == pytest.approx(sorted([(1 * k, 0.0), (1 * k, 2 * k), (-1 * k, 0.0)]), abs=1e-3)


def test_a_file_with_no_geometry_or_garbage_is_an_error_that_says_so():
    with pytest.raises(vr.VrmlError, match="no geometry"):
        vr.read_vrml("#VRML V2.0 utf8\nGroup { }")
    with pytest.raises(vr.VrmlError):
        vr.read_vrml("not vrml at all {{{")
