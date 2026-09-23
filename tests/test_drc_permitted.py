"""KiCad lists a part a keepout allows as `items_not_allowed`: the rule
area KiCad reads has no allow list. Those are permitted, not violations."""
from placemat.kicad.drc import count_violations


def _v(area, item, kind="items_not_allowed"):
    return {"type": kind, "description": "Items not allowed (keepout area '%s')" % area,
            "items": [{"description": item}]}


def test_a_part_the_keepout_allows_is_permitted_and_others_still_count():
    data = {"violations": [
        _v("keepout antenna [*.Cu]", "Footprint U3"),                         # allowed by name
        _v("keepout antenna [*.Cu]", "Footprint R9"),                         # not allowed
        _v("keepout antenna [*.Cu]", "Track [ANT_FEED] on F.Cu, length 1.2000 mm"),   # an allowed net
        _v("keepout light_sensor", "Footprint U3"),                           # another keepout: not allowed there
        {"type": "clearance", "description": "Clearance violation", "items": []},
    ]}
    allow = {"keepout antenna": ({"U3"}, {"ANT_FEED"})}
    counted, permitted = count_violations(data, allow)
    assert counted == {"items_not_allowed": 2, "clearance": 1}
    assert permitted == {"items_not_allowed": 2}


def test_with_nothing_allowed_every_violation_counts():
    data = {"violations": [_v("keepout antenna", "Footprint U3")]}
    assert count_violations(data, {}) == ({"items_not_allowed": 1}, {})
