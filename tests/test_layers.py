"""What copper layers placemat can name, and what it does with a board that
has more of them than it expects."""
import pytest

from placemat.values import CopperLayer, Face


def test_every_layer_kicad_can_have_is_nameable():
    """KiCad's maximum is 32 copper layers: the two faces and In1 to In30."""
    assert len(CopperLayer) == 32
    assert CopperLayer.of("In30.Cu").value == "In30.Cu"
    assert CopperLayer.of("In7.Cu") is CopperLayer.IN7


def test_the_faces_keep_their_names_and_their_faces():
    assert CopperLayer.F.value == "F.Cu" and CopperLayer.B.value == "B.Cu"
    assert CopperLayer.F.face is Face.FRONT and CopperLayer.B.face is Face.BACK
    assert CopperLayer.F.other_face is CopperLayer.B
    assert CopperLayer.B.other_face is CopperLayer.F


def test_an_inner_layer_has_no_face_and_no_opposite():
    assert CopperLayer.IN7.face is None
    with pytest.raises(ValueError, match="inner layer"):
        CopperLayer.IN7.other_face


def test_a_layer_that_is_not_copper_is_refused_by_name():
    with pytest.raises(ValueError, match="F.SilkS"):
        CopperLayer.of("F.SilkS")
    with pytest.raises(ValueError, match="In31.Cu"):
        CopperLayer.of("In31.Cu")          # past KiCad's own maximum


def test_a_layer_is_still_a_string_and_still_hashable():
    """Everything downstream treats a layer as its KiCad name."""
    assert isinstance(CopperLayer.IN7, str) and CopperLayer.IN7 == "In7.Cu"
    assert len(frozenset([CopperLayer.F, CopperLayer.IN7, CopperLayer.F])) == 2
    assert CopperLayer.of(CopperLayer.IN7) is CopperLayer.IN7
