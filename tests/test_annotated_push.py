"""Pushes from part annotations: a part carrying Pm.Emits and a part carrying
Pm.Limit of one kind hold each other apart through board.push's machinery."""
import pytest

from placemat.layout import Board
from placemat.values import Cell, Face, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint

EMITS = "magnetic:3.2mT@13.5mm^3"
LIMIT = "magnetic:0.3mT"
RADIUS = 13.5 * (3.2 / 0.3) ** (1.0 / 3.0)      # ~29.7 mm


def _board(fps, width=60, height=60, **kw):
    return Board(board_geometry(fps, width=width, height=height), edge_margin=1.0, keep_going=True, **kw)


def _m1(x=10, y=10, **fields):
    return footprint("M1", x, y, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS, **fields})


def _u2(x=30, y=30, **fields):
    return footprint("U2", x, y, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT, **fields})


def _findings_of(plan, name):
    return [f for f in plan.findings if name in f]


def test_a_unit_mismatch_is_refused_when_the_run_starts_naming_both_parts():
    m1 = footprint("M1", 10, 10, inst="m1", fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 30, 30, inst="u2", fields={"Pm.Limit": "magnetic:500uT"})
    b = _board([m1, u2])
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(30, 30))
    with pytest.raises(ValueError) as e:
        b.resolve()
    assert "M1" in str(e.value) and "U2" in str(e.value)


def test_a_firm_sensitive_part_inside_the_hard_limit_is_refused_by_the_source():
    b = _board([_m1(), _u2(14, 10)])
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(14, 10))
    plan = b.resolve()
    found = _findings_of(plan, "u2")
    assert any("push from M1" in f and ("%.3g" % RADIUS) in f for f in found), found


def _landing_fps(annotated):
    m1 = footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND"),
                   fields={"Pm.Emits": "magnetic:3.2mT@2mm^3"} if annotated else None)
    u2 = footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"),
                   fields={"Pm.Limit": LIMIT} if annotated else None)
    j1 = footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))
    return [m1, u2, j1]


def _landing(annotated, pushed=True):
    b = _board(_landing_fps(annotated))
    b.place(Part("m1"), at=Location(10, 30))
    b.place(Part("j1"), at=Location(55, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    b.place(Part("u2"), radius=25.0, step=1.0)
    if pushed and not annotated:
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3)
    return b.resolve()


def test_an_annotated_pair_lands_where_the_equivalent_board_push_lands():
    by_hand, annotated = _landing(False), _landing(True)
    assert annotated.step("u2").placement == by_hand.step("u2").placement
    d = annotated.box("u2").center.distance(Location(10, 30))
    assert 3.2 * (2.0 / d) ** 3 <= 0.3 + 1e-6
    assert d > _landing(False, pushed=False).box("u2").center.distance(Location(10, 30))


def test_a_source_and_a_limit_of_different_kinds_do_not_pair():
    m1 = _m1()
    m1.fields["Pm.Emits"] = "heat:15C@5mm^1"
    b = _board([m1, _u2(14, 10)])
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(14, 10))
    plan = b.resolve()
    assert not _findings_of(plan, "u2")
    assert not plan.pushes


def _values_at(plan, point, kind_emits, sources):
    """The summed value at `point` of the sources (refdes) placed in `plan`."""
    total = 0.0
    for ref in sources:
        c = plan.occupancy.geometry_of(ref).body.center
        total += kind_emits.at(c.distance(point))
    return total


def test_two_sources_of_a_kind_add_for_the_hard_limit():
    """Each source alone is within the limit where the sensor lands unless
    the other's field is added: a disc per source would let it stand there."""
    emits = "magnetic:1mT@10mm^2"
    fps = [footprint("M1", 12, 24, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": emits}),
           footprint("M3", 12, 36, w=4, h=4, inst="m3", nets=("B", "GND"), fields={"Pm.Emits": emits}),
           footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": "magnetic:1mT"}),
           footprint("J1", 22, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    b = _board(fps)
    b.place(Part("m1"), at=Location(12, 24))
    b.place(Part("m3"), at=Location(12, 36))
    b.place(Part("j1"), at=Location(22, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"), weight=100)
    b.place(Part("u2"), radius=25.0, step=0.5)
    plan = b.resolve()
    where = plan.box("u2").center
    e = exposure_emission(emits)
    # the link pulls u2 as near j1 as it may stand: at that spot each alone is under 1 mT and both are over
    assert _values_at(plan, where, e, ["M1"]) < 1.0 and _values_at(plan, where, e, ["M1", "M3"]) <= 1.0 + 1e-6


def exposure_emission(text):
    from placemat import exposure
    kind, _, rest = text.partition(":")
    value, _, rest = rest.partition("@")
    r_ref, _, falloff = rest.partition("^")
    return exposure.Emission(kind, float(value[:-2]), "mT", float(r_ref[:-2]), float(falloff))


def test_a_source_placed_second_stays_outside_the_sensitive_parts_limit():
    m1 = footprint("M1", 30, 10, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 10, 10, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT})
    j1 = footprint("J1", 14, 10, w=2, h=2, inst="j1", nets=("A", "PWR"))
    b = _board([m1, u2, j1])
    b.place(Part("u2"), at=Location(10, 10))
    b.place(Part("j1"), at=Location(14, 10))
    b.link(PadRef(Part("m1"), "A"), PadRef(Part("j1"), "A"), weight=10)
    b.place(Part("m1"), radius=30.0, step=1.0)
    plan = b.resolve()
    d = plan.box("m1").center.distance(Location(10, 10))
    assert 3.2 * (13.5 / d) ** 3 <= 0.3 + 1e-6
    assert d < RADIUS + 3.0         # and as near as the link could draw it
    assert plan.step("m1").placement is not None


def _offset_source(emits_at, **place):
    m1 = footprint("M1", 10, 10, w=4, h=2, inst="m1", nets=("A", "GND"),
                   fields={"Pm.Emits": "magnetic:3.2mT@2mm^3", "Pm.EmitsAt": emits_at})
    u2 = footprint("U2", 40, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT})
    j1 = footprint("J1", 32, 30, w=2, h=2, inst="j1", nets=("A", "PWR"))
    b = _board([m1, u2, j1])
    b.place(Part("u2"), at=Location(40, 30))
    b.place(Part("j1"), at=Location(32, 30))
    b.link(PadRef(Part("m1"), "A"), PadRef(Part("j1"), "A"), weight=10)
    b.place(Part("m1"), radius=40.0, step=0.5, **place)
    return b.resolve()


def test_an_emission_point_in_the_footprints_frame_turns_and_flips_with_it():
    """The pad centre and the same point said as x,y in the footprint's frame
    are one point, whichever way the part is turned or flipped: the same landing."""
    for place in ({}, {"rotation": 90.0}, {"rotation": 90.0, "face": Face.BACK}):
        by_pad = _offset_source("pad:2", **place)
        by_xy = _offset_source("1.4,0", **place)
        assert by_xy.step("m1").placement == by_pad.step("m1").placement, place
        d = by_pad.occupancy.pad_location("M1", "2").distance(Location(40, 30))
        assert 3.2 * (2.0 / d) ** 3 <= 0.3 + 1e-6, (place, d)


def test_the_source_point_is_the_emission_point_not_the_origin():
    """With the emission at the far end of the part the sensor stands where a
    push from that point puts it, and a push from the origin puts it elsewhere."""
    def landing(emits_at, from_):
        m1 = footprint("M1", 10, 30, w=4, h=2, inst="m1", nets=("A", "GND"),
                       fields={"Pm.Emits": "magnetic:3.2mT@2mm^3", **({"Pm.EmitsAt": emits_at} if emits_at else {})})
        u2 = footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"),
                       fields={"Pm.Limit": "magnetic:0.1mT"} if from_ is None else None)
        j1 = footprint("J1", 18, 33, w=2, h=2, inst="j1", nets=("SIG", "PWR"))
        b = _board([m1, u2, j1])
        b.place(Part("m1"), at=Location(10, 30))
        b.place(Part("j1"), at=Location(18, 33))
        b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"), weight=5)
        b.place(Part("u2"), radius=25.0, step=0.5)
        if from_ is not None:
            b.push(Part("u2"), from_=from_, falloff=3, reference=(2.0, 3.2), limit=0.1)
        return b.resolve().step("u2").placement

    assert landing("8,0", None) == landing("8,0", Location(18, 30))
    assert landing("8,0", None) != landing("0,0", None)


def test_a_sensitive_part_already_over_its_limit_does_not_make_the_next_source_unplaceable():
    strong = footprint("M3", 12, 12, w=2, h=2, inst="m3", nets=("B", "GND"), fields={"Pm.Emits": "magnetic:9mT@1mm^3"})
    m1 = footprint("M1", 30, 30, w=2, h=2, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 14, 12, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT})
    b = _board([strong, m1, u2])
    b.place(Part("m3"), at=Location(12, 12))
    b.place(Part("u2"), at=Location(14, 12))      # over its limit already, by the first source
    b.place(Part("m1"), radius=20.0, step=1.0)
    plan = b.resolve()
    assert plan.step("m1").placement is not None


def test_the_part_placed_second_carries_the_disc_whichever_it_is():
    for first, second in (("m1", "u2"), ("u2", "m1")):
        b = _board([_m1(), _u2()])
        fixed = {"m1": Location(10, 30), "u2": Location(30, 30)}
        b.place(Part(first), at=fixed[first])
        b.place(Part(second), radius=40.0, step=1.0)
        plan = b.resolve()
        d = plan.box("m1").center.distance(plan.box("u2").center)
        assert 3.2 * (13.5 / d) ** 3 <= 0.3 + 1e-6, (first, d)
        assert any("push from" in s for s in [plan.step(second).note]), plan.step(second).note


def test_two_parts_that_both_emit_and_limit_heat_raise_no_cycle():
    def part(ref, x):
        return footprint(ref, x, 30, w=4, h=4, inst=ref.lower(), nets=("A", "GND"),
                         fields={"Pm.Emits": "heat:15C@5mm^1", "Pm.Limit": "heat:5C"})
    b = _board([part("U1", 10), part("U2", 30)])
    i1 = b.place(Part("u1"))
    i2 = b.place(Part("u2"))
    assert i1.needs == frozenset() and i2.needs == frozenset()
    plan = b.resolve()
    assert plan.step("u1").placement is not None and plan.step("u2").placement is not None
    d = plan.box("u1").center.distance(plan.box("u2").center)
    assert 15.0 * (5.0 / d) <= 5.0 + 1e-6


def test_the_step_note_gives_each_kinds_value_the_limit_and_the_nearest_source():
    emits = "magnetic:1mT@10mm^2"
    fps = [footprint("M1", 12, 24, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": emits}),
           footprint("M3", 12, 44, w=4, h=4, inst="m3", nets=("B", "GND"), fields={"Pm.Emits": emits}),
           footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": "magnetic:1mT"}),
           footprint("J1", 22, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    b = _board(fps)
    b.place(Part("m1"), at=Location(12, 24))
    b.place(Part("m3"), at=Location(12, 44))
    b.place(Part("j1"), at=Location(22, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"), weight=100)
    b.place(Part("u2"), radius=25.0, step=0.5)
    plan = b.resolve()
    note = plan.step("u2").note
    where = plan.box("u2").center
    e = exposure_emission(emits)
    total = _values_at(plan, where, e, ["M1", "M3"])
    assert "magnetic at U2: %.2g mT of 1 mT" % total in note, note
    assert "nearest source M1 at %.1f mm" % where.distance(plan.box("m1").center) in note, note


def test_the_note_of_a_source_placed_second_gives_the_sensitive_parts_value():
    m1 = footprint("M1", 30, 10, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 10, 10, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT})
    b = _board([m1, u2])
    b.place(Part("u2"), at=Location(10, 10))
    b.place(Part("m1"), radius=40.0, step=1.0)
    plan = b.resolve()
    d = plan.box("m1").center.distance(Location(10, 10))
    note = plan.step("m1").note
    assert "magnetic at U2: %.2g mT of 0.3 mT" % (3.2 * (13.5 / d) ** 3) in note, note
    assert "nearest source M1 at %.1f mm" % d in note, note


def test_board_push_on_an_annotated_item_adds_to_the_annotated_pushes():
    def landing(extra):
        b = _board(_landing_fps(True) + [footprint("M3", 10, 20, w=4, h=4, inst="m3", nets=("B", "GND"))])
        b.place(Part("m1"), at=Location(10, 30))
        b.place(Part("m3"), at=Location(10, 20))
        b.place(Part("j1"), at=Location(55, 30))
        b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
        b.place(Part("u2"), radius=25.0, step=1.0)
        if extra:
            b.push(Part("u2"), from_=Part("m3"), falloff=3, reference=(2.0, 3.2), limit=0.3)
        return b.resolve()

    alone, both = landing(False), landing(True)
    assert len(alone.pushes) == 1 and len(both.pushes) == 2
    assert "push from m3:" in both.step("u2").note and "magnetic at U2" in both.step("u2").note
    d3 = both.box("u2").center.distance(Location(10, 20))
    assert 3.2 * (2.0 / d3) ** 3 <= 0.3 + 1e-6      # the declared push's own hard limit
    d1 = both.box("u2").center.distance(Location(10, 30))
    assert 3.2 * (2.0 / d1) ** 3 <= 0.3 + 1e-6      # and the annotated one's


def test_members_of_one_cell_do_not_pair():
    fps = [footprint("M1", 10, 10, w=2, h=2, inst="sensor.m1", nets=("A", "GND"), cell="sensor",
                     fields={"Pm.Emits": EMITS}),
           footprint("U2", 14, 10, w=2, h=2, inst="sensor.u2", nets=("SIG", "GND"), cell="sensor",
                     fields={"Pm.Limit": LIMIT})]
    b = Board(board_geometry(fps, cells=["sensor"], width=60, height=60), edge_margin=1.0)
    b.place(Cell("sensor"), at=Location(12, 10))
    plan = b.resolve()
    assert not plan.pushes
    assert plan.step("sensor").placement is not None
