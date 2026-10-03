"""Small findings of a few causes, for a test that needs a finding of a kind and is not about what it says."""
from placemat.findings import Finding, FindingCause as C

_LINK = {"link": "a.1>b.2", "a": {"key": "a", "ref": "A", "pad": "1"}, "b": {"key": "b", "ref": "B", "pad": "2"},
         "achieved_mm": 3.0, "limit_mm": 2.0, "why": ""}

FACTS = {
    C.LINK_OVER: _LINK,
    C.UNPLACED_RIDES: {"item": "c4", "variant": "rode", "rider_of": "u1"},
    C.VIAS_GAVE_WAY: {"item": "c4", "nets": [], "fields": []},
    C.COPPER_STITCH: {"variant": "no_edge", "net": "X"},
    C.SETUP_UNDECLARED: {"item": "c1", "ref": "C1"},
    C.ESCAPE_WALLED: {"variant": "walled", "ref": "U1", "pin": "8", "net": "GND",
                      "by": [{"form": "who", "name": "R4"}, {"form": "who", "name": "U1"}]},
}


def finding(cause, severity=None):
    return Finding(cause, FACTS[cause], severity)
