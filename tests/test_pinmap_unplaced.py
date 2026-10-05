"""The pin map study with parts not yet placed: a studied net whose far end is on one has no pull, so it keeps its pin
and is listed; and below `pins.placed_share_min` of the movable nets with a placed far end, the study gives no map and
says it waits on placement."""
from placemat.findings import FindingCause as C
from placemat.pinmap import study_findings
from tests.pinmap_boards import complete, reversed_four, settings


def without_ta():
    """reversed_four with TP4, net A's far end, not placed."""
    pads, parts = reversed_four()
    pads = [p for p in pads if p.ref != "TP4"]
    return pads, complete(pads, parts), (("TP4", "1", "A"),)


def test_a_net_whose_far_end_is_not_placed_keeps_its_pin_and_is_listed():
    pads, parts, unplaced = without_ta()
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {},
                              settings(pins_rotations=(0.0,), pins_placed_share_min=0.5), unplaced=unplaced)
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    assert f.facts["unplaced_ends"] == [{"net": "A", "ref": "TP4"}]
    assert {"ref": "U1", "net": "A", "pin": "1", "name": "", "why": "unplaced"} in f.facts["held"]
    assert all(m["net"] != "A" for r in f.facts["rotations"] for m in r["map"])
    assert "1 net keeps its pin until its far end is placed: A" in f


def test_below_the_placed_share_the_study_gives_no_map_and_says_it_waits_on_placement():
    pads, parts, unplaced = without_ta()
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(pins_rotations=(0.0,)), unplaced=unplaced)
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    assert f.severity == "notice"
    assert f.facts["rotations"] == [] and f.facts["withheld"] == {"placed": 3, "of": 4, "share_min": 0.8}
    assert f.facts["unplaced_ends"] == [{"net": "A", "ref": "TP4"}]
    assert f == ("U1: the pin map study waits on placement: 1 of its 4 movable nets has no placed far end, and "
                 "pins.placed_share_min asks for 80 percent with one; no map or turn is advised")
    from placemat import suggestions as sg
    assert sg.suggest(f.cause, f.facts) == []


def test_the_placed_share_is_read_by_the_study_so_a_change_to_it_studies_again(tmp_path):
    pads, parts, unplaced = without_ta()
    cache = tmp_path / "pinmap.json"
    run = lambda share: study_findings(pads, parts, {}, frozenset(), {}, {},
                                       settings(pins_rotations=(0.0,), pins_placed_share_min=share), cache=cache,
                                       unplaced=unplaced)[1]["reused"]
    assert (run(0.8), run(0.8), run(0.5)) == (False, True, False)


def test_a_resolve_gives_the_study_the_pads_of_the_parts_it_has_not_placed():
    from placemat.pinmap import placed_from_plan
    from tests.test_pinmap_wiring import board
    b = board()
    plan = b.resolve()
    plan.occupancy.pending.add("R4")
    placed = placed_from_plan(b, plan)
    assert "R4" not in placed.parts and ("R4", "1", "A") in placed.unplaced
