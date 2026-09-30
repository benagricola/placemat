"""The exposure check: each sensitive part's modelled value per kind against its limit."""
import pytest

from placemat import checks
from placemat.values import Face
from tests.fixtures import board_geometry, footprint


def _geo(*fps):
    return board_geometry(list(fps), width=80, height=80)


def _exposure(*fps):
    return [v for v in checks.run_checks(_geo(*fps)) if v.check == "exposure"]


def _magnet(ref, x, y, emits="magnetic:3.2mT@13.5mm^3", **fields):
    return footprint(ref, x, y, w=4, h=4, fields={"Pm.Emits": emits, **fields})


def _sensor(x, y, limit="magnetic:0.3mT", **fields):
    return footprint("U2", x, y, w=2, h=2, fields={"Pm.Limit": limit, **fields})


def test_a_sensitive_part_within_its_limit_passes_naming_its_source():
    d = 40.0
    (v,) = _exposure(_magnet("M1", 10, 40), _sensor(10 + d, 40))
    assert v.ok is True and v.unit == "mT" and v.limit == 0.3
    assert v.value == pytest.approx(3.2 * (13.5 / d) ** 3)
    assert "M1" in v.note and "40.0 mm" in v.note and v.subject == "U2 magnetic"


def test_a_sensitive_part_over_its_limit_fails_naming_every_contributor():
    vs = _exposure(_magnet("M1", 10, 40), _magnet("M3", 10, 50), _sensor(40, 45))
    (v,) = vs
    assert v.ok is False
    assert "M1" in v.note and "M3" in v.note
    assert v.value > 0.3


def test_sources_of_a_kind_add():
    one = _exposure(_magnet("M1", 10, 40), _sensor(40, 40))[0].value
    two = _exposure(_magnet("M1", 10, 40), _magnet("M3", 10, 40), _sensor(40, 40))[0].value
    assert two == pytest.approx(2 * one)


def test_each_kind_is_judged_on_its_own():
    m1 = _magnet("M1", 10, 40, emits="magnetic:3.2mT@13.5mm^3 heat:15C@5mm^1")
    u2 = _sensor(40, 40, limit="magnetic:0.3mT heat:5C")
    vs = {v.subject: v for v in _exposure(m1, u2)}
    assert set(vs) == {"U2 magnetic", "U2 heat"}
    assert vs["U2 heat"].unit == "C" and vs["U2 heat"].value == pytest.approx(15.0 * 5.0 / 30.0)


def test_a_kind_no_source_emits_passes_at_zero():
    (v,) = _exposure(_sensor(40, 40))
    assert v.ok is True and v.value == 0.0 and "no source" in v.note


def test_a_source_is_measured_from_its_emission_point_and_a_sensor_at_its_pad():
    m1 = _magnet("M1", 10, 40, **{"Pm.EmitsAt": "pad:2"})       # pad 2 at x = 10 + 1.4
    u2 = _sensor(40, 40, **{"Pm.SensesAt": "pad:1"})            # pad 1 at x = 40 - 0.4
    (v,) = _exposure(m1, u2)
    d = (40 - 0.4) - (10 + 1.4)
    assert v.value == pytest.approx(3.2 * (13.5 / d) ** 3)
    m1 = _magnet("M1", 10, 40, **{"Pm.EmitsAt": "5,0"})
    (v,) = _exposure(m1, _sensor(40, 40))
    assert v.value == pytest.approx(3.2 * (13.5 / 25.0) ** 3)


def test_an_emission_point_turns_and_flips_with_the_footprint():
    m1 = footprint("M1", 10, 40, w=4, h=4, rotation=90.0, fields={"Pm.Emits": "magnetic:3.2mT@13.5mm^3", "Pm.EmitsAt": "5,0"})
    (v,) = _exposure(m1, _sensor(10, 20))        # 5 mm north of the origin after a 90 degree turn: 15 mm from the sensor
    assert v.value == pytest.approx(3.2 * (13.5 / 15.0) ** 3)
    m1 = footprint("M1", 10, 40, w=4, h=4, face=Face.BACK, fields={"Pm.Emits": "magnetic:3.2mT@13.5mm^3", "Pm.EmitsAt": "5,0"})
    (v,) = _exposure(m1, _sensor(10 - 30, 40))   # flipped: 5 mm west, 25 mm from the sensor
    assert v.value == pytest.approx(3.2 * (13.5 / 25.0) ** 3)


def test_a_part_that_emits_and_limits_one_kind_is_not_exposed_to_itself():
    both = footprint("U1", 10, 40, w=4, h=4, fields={"Pm.Emits": "heat:15C@5mm^1", "Pm.Limit": "heat:5C"})
    (v,) = _exposure(both)
    assert v.value == 0.0 and v.ok is True


def test_a_parse_error_is_not_judged_rather_than_a_crash():
    (v,) = _exposure(_magnet("M1", 10, 40, emits="magnetic:3.2mT"), _sensor(40, 40))
    assert v.ok is None and "M1" in v.note and "not judged" in v.note


def test_a_unit_mismatch_is_not_judged_naming_both_parts():
    (v,) = _exposure(_magnet("M1", 10, 40), _sensor(40, 40, limit="magnetic:300uT"))
    assert v.ok is None and "M1" in v.note and "U2" in v.note


def test_a_board_without_annotations_adds_no_exposure_verdict():
    assert _exposure(footprint("R1", 10, 10)) == []
