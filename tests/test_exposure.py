"""Pm.Emits / Pm.EmitsAt / Pm.Limit / Pm.SensesAt read off footprint fields."""
import pytest

from placemat import exposure
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint


def _geo(*fps):
    return board_geometry(list(fps), width=60, height=60)


def test_emits_with_two_kinds():
    m1 = footprint("M1", 10, 10, fields={"Pm.Emits": "magnetic:3.2mT@13.5mm^3 heat:15C@5mm^1"})
    ann = exposure.read(_geo(m1))
    src = ann.sources["M1"]
    assert [(e.kind, e.value, e.unit, e.r_ref, e.falloff) for e in src.emissions] == [
        ("magnetic", 3.2, "mT", 13.5, 3.0), ("heat", 15.0, "C", 5.0, 1.0)]
    assert src.at is None


def test_an_emission_falls_off_as_r_to_minus_falloff():
    e = exposure.Emission("magnetic", 3.2, "mT", 13.5, 3.0)
    assert e.at(27.0) == pytest.approx(3.2 / 8)
    assert e.radius(0.3) == pytest.approx(13.5 * (3.2 / 0.3) ** (1 / 3))


def test_emits_at_as_a_point_and_as_a_pad():
    a = footprint("M1", 10, 10, fields={"Pm.Emits": "heat:1C@1mm^1", "Pm.EmitsAt": "1.5, -2"})
    b = footprint("M2", 30, 10, fields={"Pm.Emits": "heat:1C@1mm^1", "Pm.EmitsAt": "pad:2"})
    ann = exposure.read(_geo(a, b))
    assert ann.sources["M1"].at == ("xy", 1.5, -2.0)
    assert ann.sources["M2"].at == ("pad", "2")


def test_limit_with_two_kinds_and_senses_at():
    u = footprint("U2", 30, 30, fields={"Pm.Limit": "magnetic:0.5mT heat:5C", "Pm.SensesAt": "pad:1"})
    ann = exposure.read(_geo(u))
    s = ann.sensitives["U2"]
    assert s.limits == (("magnetic", 0.5, "mT"), ("heat", 5.0, "C"))
    assert s.senses == "1"


def test_keys_are_read_case_insensitively():
    m1 = footprint("M1", 10, 10, fields={"Pm.Emitsat": "0,1", "Pm.Emits": "heat:1C@1mm^1"})
    u = footprint("U2", 30, 30, fields={"Pm.Sensesat": "pad:2", "Pm.Limit": "heat:1C"})
    ann = exposure.read(_geo(m1, u))
    assert ann.sources["M1"].at == ("xy", 0.0, 1.0)
    assert ann.sensitives["U2"].senses == "2"


def test_a_part_with_neither_is_not_listed():
    ann = exposure.read(_geo(footprint("R1", 10, 10)))
    assert not ann.sources and not ann.sensitives


@pytest.mark.parametrize("key,text", [
    ("Pm.Emits", "magnetic:3.2mT"), ("Pm.Emits", "magnetic:3.2mT@0mm^3"), ("Pm.Emits", "magnetic:3.2mT@5mm^0"),
    ("Pm.Emits", "magnetic:mT@5mm^3"), ("Pm.Limit", "magnetic"), ("Pm.Limit", "magnetic:0mT"),
])
def test_a_malformed_value_names_the_part_and_key(key, text):
    with pytest.raises(ValueError, match=r"M1.*%s" % key.replace(".", r"\.")):
        exposure.read(_geo(footprint("M1", 10, 10, fields={key: text})))


def test_a_pad_the_part_lacks_is_refused_naming_it():
    with pytest.raises(ValueError, match=r"M1.*pad 9"):
        exposure.read(_geo(footprint("M1", 10, 10, fields={"Pm.Emits": "heat:1C@1mm^1", "Pm.EmitsAt": "pad:9"})))
    with pytest.raises(ValueError, match=r"U2.*pad 9"):
        exposure.read(_geo(footprint("U2", 10, 10, fields={"Pm.Limit": "heat:1C", "Pm.SensesAt": "pad:9"})))


def test_a_bad_emits_at_is_refused():
    with pytest.raises(ValueError, match=r"M1.*Pm\.EmitsAt"):
        exposure.read(_geo(footprint("M1", 10, 10, fields={"Pm.Emits": "heat:1C@1mm^1", "Pm.EmitsAt": "left"})))


def test_a_unit_mismatch_names_both_parts_and_units():
    m1 = footprint("M1", 10, 10, fields={"Pm.Emits": "magnetic:3.2mT@13.5mm^3"})
    u2 = footprint("U2", 30, 30, fields={"Pm.Limit": "magnetic:500uT"})
    with pytest.raises(ValueError) as e:
        exposure.read(_geo(m1, u2))
    text = str(e.value)
    assert "M1" in text and "U2" in text and "mT" in text and "uT" in text and "magnetic" in text


def test_a_unit_mismatch_between_two_sources_is_refused_too():
    a = footprint("M1", 10, 10, fields={"Pm.Emits": "heat:15C@5mm^1"})
    b = footprint("M2", 30, 10, fields={"Pm.Emits": "heat:15K@5mm^1"})
    with pytest.raises(ValueError, match=r"M1.*M2|M2.*M1"):
        exposure.read(_geo(a, b))


def test_units_of_different_kinds_may_differ():
    m1 = footprint("M1", 10, 10, fields={"Pm.Emits": "magnetic:3.2mT@13.5mm^3 heat:15C@5mm^1"})
    u2 = footprint("U2", 30, 30, fields={"Pm.Limit": "magnetic:0.5mT heat:5C"})
    exposure.read(_geo(m1, u2))


def test_local_to_board_front_unturned_is_a_translation():
    p = exposure.local_to_board(Location(10, 20), 0.0, Face.FRONT, 2.0, -1.0)
    assert (p.x, p.y) == pytest.approx((12.0, 19.0))


def test_local_to_board_turns_ninety_degrees_counter_clockwise_on_screen():
    # y is down: a point east of the origin turned 90 degrees CCW lands north (smaller y)
    p = exposure.local_to_board(Location(10, 20), 90.0, Face.FRONT, 2.0, 0.0)
    assert (p.x, p.y) == pytest.approx((10.0, 18.0))


def test_local_to_board_back_face_mirrors_x_before_turning():
    p = exposure.local_to_board(Location(10, 20), 0.0, Face.BACK, 2.0, 1.0)
    assert (p.x, p.y) == pytest.approx((8.0, 21.0))
    q = exposure.local_to_board(Location(10, 20), 90.0, Face.BACK, 2.0, 0.0)
    assert (q.x, q.y) == pytest.approx((10.0, 22.0))
