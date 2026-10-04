import pytest

from placemat import reuse
from placemat.values import Beside, CopperLayer, Edge, Net, PadRef, Part
from tests.arrangement_support import module

F = CopperLayer.F


def declared(b):
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("mirrored", __import__("placemat").Alt(Part("c_in"), rotation=180))
    return b


def track(b, **kw):
    return b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=F, **kw)


def test_a_declaration_without_only_is_in_every_arrangement():
    b = declared(module())
    c = track(b)
    assert c.only == () and c.applies_in("default") and c.applies_in("c_in.east")


def test_only_names_the_arrangements_a_declaration_exists_in():
    b = declared(module())
    c = track(b, only=("mirrored", "c_in.east+r_pull.turned"))
    assert c.only == ("mirrored", "c_in.east+r_pull.turned")
    assert c.applies_in("mirrored") and not c.applies_in("default") and not c.applies_in("c_in.east")
    b.finish_declarations()


@pytest.mark.parametrize("only", [("nope",), ("east",), ("r_pull.turned+c_in.east",)])
def test_an_unknown_id_is_refused_with_the_line_and_the_ids_the_module_has(only):
    b = declared(module())
    track(b, only=only)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    text = str(e.value)
    assert "test_arrangement_only.py:" in text and "only=" in text and "c_in.east" in text and "mirrored" in text
    assert "arrangements:" in text and "groups:" in text


def test_an_empty_only_and_a_bare_string_are_refused_where_written():
    b = declared(module())
    with pytest.raises(ValueError):
        track(b, only=())
    with pytest.raises(TypeError):
        track(b, only="default")
    with pytest.raises(TypeError):
        b.place(Part("r_free"), only=("default",))                    # a form that takes no only=


def test_default_names_the_default_arrangement():
    b = declared(module())
    assert track(b).applies_in("default")
    narrowed = track(b, only=("default",))
    assert narrowed.applies_in("default")
    other = track(b, only=("mirrored",))
    assert not other.applies_in("default")
    b.finish_declarations()


def test_every_copper_form_takes_only():
    import inspect
    from placemat.layout import Board
    for form in ("track", "pair", "vias", "via", "stitch", "pour", "plane", "finger"):
        assert "only" in inspect.signature(getattr(Board, form)).parameters, form


def test_only_is_in_the_reuse_digest_only_when_given():
    b = declared(module())
    plain, narrowed = track(b), track(b, only=("mirrored",))
    assert "only=" not in reuse.canonical(plain) and "only=" in reuse.canonical(narrowed)


def test_finish_declarations_is_idempotent():
    b = declared(module())
    track(b, only=("mirrored",))
    b.finish_declarations()
    b.finish_declarations()


def test_a_pour_fitted_round_a_via_that_exists_in_fewer_arrangements_is_refused():
    b = declared(module())
    v = b.via(Net("VIN"), PadRef(Part("u1"), 1), only=("mirrored",))
    b.pour(Net("VIN"), [PadRef(Part("u1"), 1), v], layer=F, swallow_pads=True)           # in every arrangement, its via in one
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert "via" in str(e.value) and "only" in str(e.value)
