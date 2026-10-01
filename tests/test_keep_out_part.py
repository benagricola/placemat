"""A keep-out limit on a part, from its datasheet (`Pm.KeepOut`): the part's
pads on the nets it names keep that distance from the copper on the nets it
says to stay away from, in place of the board-wide `check.keep_out_mm`.
Pure: synthetic boards."""
import pytest

from placemat.checks import keep_out, keep_outs
from tests.fixtures import board_geometry, footprint, track

CITE = "datasheet rev B, section 10.2, layout example"


def _switch(extra_fields=None, gap=0.7):
    """Two aggressors own SW (q1, l1); u1's FB pad is `gap` mm below l1's SW pad."""
    q = footprint("Q1", 14, 13, nets=("VIN", "SW"), fields={"Pm.Aggressor": "true"})
    l = footprint("L1", 20, 13, nets=("SW", "VOUT"), fields={"Pm.Aggressor": "true"})
    fields = {"Pm.Sensitive": "fb", "Pm.Aggressor": "true"}
    fields.update(extra_fields or {})
    u = footprint("U1", 20.0, 13.5 + gap + 0.5, nets=("FB", "SW"), fields=fields)
    return [q, l, u]


def _one(parts, copper=(), limit=2.0):
    (v,) = keep_out(board_geometry(parts, copper=list(copper)), limit_mm=limit)
    return v


def test_without_the_annotation_the_board_wide_limit_judges_it():
    v = _one(_switch())
    assert v.value == pytest.approx(0.7) and v.limit == 2.0 and v.ok is False and "Pm.KeepOut" not in v.note


def test_a_part_with_the_annotation_is_judged_at_its_limit():
    v = _one(_switch({"Pm.KeepOut": "0.7mm away=SW; " + CITE}))
    assert v.value == pytest.approx(0.7) and v.limit == pytest.approx(0.7) and v.ok is True
    assert "U1's Pm.KeepOut" in v.note and CITE in v.note, v.note


def test_a_part_is_failed_at_its_own_limit_too():
    v = _one(_switch({"Pm.KeepOut": "0.9mm away=SW; " + CITE}))
    assert v.limit == pytest.approx(0.9) and v.ok is False


def test_a_datasheet_may_ask_for_more_than_the_board_wide_limit():
    v = _one(_switch({"Pm.KeepOut": "3 away=SW; " + CITE}, gap=2.5))
    assert v.limit == pytest.approx(3.0) and v.ok is False


def test_the_pads_default_to_the_parts_sensitive_net_and_the_away_nets_to_its_switch_nodes():
    q = footprint("Q1", 14, 13, nets=("VIN", "SW"), fields={"Pm.Aggressor": "true"})
    l = footprint("L1", 20, 13, nets=("SW", "VOUT"), fields={"Pm.Aggressor": "true"})
    # a regulator on the node and holding its feedback net: neither is named
    u = footprint("U1", 20.0, 15.7, nets=("FB", "SW"),
                  fields={"Pm.Aggressor": "true", "Pm.Sensitive": "FB", "Pm.KeepOut": "0.7mm; " + CITE})
    (k,) = keep_outs(board_geometry([q, l, u]))[0].values()
    assert (k.pads, k.away, k.distance_mm, k.source) == (("FB",), ("SW",), 0.7, CITE)


@pytest.mark.parametrize("text, why", [
    ("0.7mm away=SW", "no citation"),
    ("0.7mm away=SW;   ", "no citation"),
    ("away=SW; " + CITE, "distance"),
    ("-0.5mm away=SW; " + CITE, "distance"),
    ("0mm away=SW; " + CITE, "above zero"),
    ("0.7mm wibble=SW; " + CITE, "wibble"),
    ("0.7mm pads=NOPE away=SW; " + CITE, "NOPE"),
    ("0.7mm pads=FB away=GONE; " + CITE, "GONE"),
])
def test_an_annotation_that_does_not_read_is_refused_and_the_part_judged_at_the_board_wide_limit(text, why):
    verdicts = keep_out(board_geometry(_switch({"Pm.KeepOut": text})), limit_mm=2.0)
    refusal = next(v for v in verdicts if v.subject == "U1 Pm.KeepOut")
    assert refusal.ok is False and why in refusal.note and "board-wide 2" in refusal.note, refusal.note
    node = next(v for v in verdicts if v.subject == "SW")
    assert node.limit == 2.0 and node.ok is False


def test_no_sensitive_net_and_no_pads_is_refused():
    parts = _switch({"Pm.KeepOut": "0.7mm away=SW; " + CITE, "Pm.Sensitive": ""})
    got, refused = keep_outs(board_geometry(parts))
    assert not got and "names no pads" in refused[0][1]


def test_other_parts_keep_the_board_wide_limit():
    parts = _switch({"Pm.KeepOut": "0.7mm away=SW; " + CITE})
    # a divider resistor's sense pad 1.0 mm from the other end of SW: not U1's pad
    r = footprint("R1", 14, 15.0, nets=("SW2", "FB2"), fields={"Pm.Sensitive": "fb2"})
    verdicts = {v.subject: v for v in keep_out(board_geometry(parts + [r]), limit_mm=2.0)}
    assert verdicts["SW"].limit == pytest.approx(2.0) and verdicts["SW"].ok is False
    assert "Pm.KeepOut" not in verdicts["SW"].note


def test_the_nearest_pair_by_margin_is_the_verdict():
    """A sense track off u1's FB pad 1.2 mm from SW is another net's copper to the node
    (judged at the board-wide 2 mm), though u1's own pad at 0.7 mm passes its limit."""
    parts = _switch({"Pm.KeepOut": "0.7mm away=SW; " + CITE})
    sense = track("FB", 20.0, 15.4, 24.0, 15.4, w=0.2)          # 1.8 mm from l1's SW pad edge (y 13.5)
    v = _one(parts, [sense])
    assert v.limit == pytest.approx(2.0) and v.ok is False and v.value < 2.0, v.note
    assert "track FB" in v.note


def test_copper_leaving_the_parts_pad_is_not_the_parts_pad():
    parts = _switch({"Pm.KeepOut": "0.7mm away=SW; " + CITE})
    close = track("FB", 19.6, 15.0, 19.6, 14.4, w=0.2)          # leaves U1's pad towards the SW pad
    far_pad_fix = _one(parts, [close])
    assert far_pad_fix.limit == pytest.approx(2.0) and far_pad_fix.ok is False


def test_a_parts_own_pads_are_not_judged_against_its_limit():
    q = footprint("Q1", 14, 13, nets=("VIN", "SW"), fields={"Pm.Aggressor": "true"})
    # the regulator holds SW and FB 0.4 mm apart: its footprint sets that
    u = footprint("U1", 20, 13, w=2.6, nets=("SW", "FB"),
                  fields={"Pm.Aggressor": "true", "Pm.Sensitive": "FB", "Pm.KeepOut": "0.7mm; " + CITE})
    l = footprint("L1", 8, 13, nets=("SW", "VOUT"), fields={"Pm.Aggressor": "true"})
    (v,) = [x for x in keep_out(board_geometry([q, l, u]), limit_mm=2.0) if x.subject == "SW"]
    assert "own pads are 0.40 mm apart" in v.note
    assert v.limit == pytest.approx(0.7)


def test_a_module_stamped_twice_carries_its_parts_limit_to_the_parent_without_repeating():
    """The annotation is on the part and names its nets as the module does; the parent's nets carry each
    instance's path, and each instance is judged at the part's limit from its own copy of the field."""
    fields = {"Pm.Sensitive": "FB", "Pm.Aggressor": "true", "Pm.KeepOut": "0.7mm away=SW; " + CITE}
    parts = []
    for inst, dx in (("BUCK1", 0.0), ("BUCK2", 40.0)):
        q = footprint("Q%s" % inst[-1], 14 + dx, 13, nets=("%s.VIN" % inst, "%s.SW" % inst), fields={"Pm.Aggressor": "true"})
        l = footprint("L%s" % inst[-1], 20 + dx, 13, nets=("%s.SW" % inst, "%s.VOUT" % inst), fields={"Pm.Aggressor": "true"})
        u = footprint("U%s" % inst[-1], 20.0 + dx, 14.7, nets=("%s.FB" % inst, "%s.SW" % inst), fields=dict(fields))
        parts += [q, l, u]
    verdicts = {v.subject: v for v in keep_out(board_geometry(parts, width=80), limit_mm=2.0)}
    assert set(verdicts) == {"BUCK1.SW", "BUCK2.SW"}
    for v in verdicts.values():
        assert v.limit == pytest.approx(0.7) and v.ok is True, v.note


def test_a_net_name_is_the_whole_name_or_its_last_part_and_not_a_longer_name_ending_the_same():
    from placemat.checks import _net_named
    assert _net_named("SW", "SW") and _net_named("sw", "BUCK1.SW") and _net_named("SW", "buck1/sw")
    assert not _net_named("SW", "VSW") and not _net_named("SW", "BUCK1_SW") and not _net_named("SW", "SW2")
