"""A pin whose net has no other pad on the board is a handoff: the net leaves the board there (a module's pin for the
parent board). Nothing joins it, so it keeps no corridor in the placement search; where the board's own copper or parts
leave it no way out at all, that is a finding. A QFN-56 whose every pin is its own net, with a wall of another net's
track along the west row."""
from placemat.values import CopperLayer, Net, PadRef, Part, Location
from tests.escape_fixtures import fan_board, one_pad

F = CopperLayer.F


def _walled(plan):
    return [str(f) for f in plan.findings if f.kind == "escape_walled"]


def _wall_board(escape=None, x=26.0, pin_nets=None):
    """Two pads of net X, 4 mm apart down the west side, and a track between them at `x` (the pins' tips are at 26.2575);
    the QFN's exposed pad shares its net with a part far off, as a ground pad does."""
    a = one_pad("X1", "x1", "X", x, 28.0)
    c = one_pad("X2", "x2", "X", x, 32.0)
    g = one_pad("G1", "g1", "GND", 10.0, 10.0)
    b = fan_board([a, c, g], exposed=True, pin_nets=pin_nets, keep_going=True)
    b.place(Part("g1"), at=Location(10.0, 10.0))
    b.place(Part("x1"), at=Location(x, 28.0))
    b.place(Part("x2"), at=Location(x, 32.0))
    if escape:
        escape(b)
    b.track(Net("X"), [PadRef(Part("x1"), 1), PadRef(Part("x2"), 1)], layer=F, why="the wall")
    return b


def test_a_handoff_pin_that_copper_walls_in_is_a_finding_naming_what_closes_it():
    plan = _wall_board().resolve()
    walled = _walled(plan)
    assert any(w.startswith("U1 pin 50 (N50): ") and "no other pad" in w and "track X" in w for w in walled), walled


def test_a_handoff_pin_with_a_way_out_is_no_finding():
    plan = _wall_board().resolve()
    walled = _walled(plan)
    assert not any(w.startswith("U1 pin 43 ") or w.startswith("U1 pin 56 ") for w in walled), walled     # beyond the wall's ends


def test_no_wall_no_finding():
    g = one_pad("G1", "g1", "GND", 10.0, 10.0)
    b = fan_board([g], exposed=True, keep_going=True)
    b.place(Part("g1"), at=Location(10.0, 10.0))
    plan = b.resolve()
    assert _walled(plan) == []


def test_a_stub_that_ends_against_copper_is_walled_in_from_where_it_ends():
    """The pin's own copper is part of it: its way out is looked for from where the stub ends."""
    def escape(b):
        esc = b.escape(Part("mcu"), [50], why="pin 50 out")
        b.track(Net("N50"), [esc[50]], layer=F, why="its stub")
    plan = _wall_board(escape, x=25.75).resolve()
    assert any(w.startswith("U1 pin 50 ") and "track X" in w for w in _walled(plan)), _walled(plan)


def test_a_stub_with_room_beyond_its_end_is_no_finding():
    def escape(b):
        esc = b.escape(Part("mcu"), [50], why="pin 50 out")
        b.track(Net("N50"), [esc[50]], layer=F, why="its stub")
    plan = _wall_board(escape, x=20.0).resolve()          # the wall is far off: the stub has room to go on
    assert not any(w.startswith("U1 pin 50 ") for w in _walled(plan)), _walled(plan)


def test_a_stub_whose_way_on_is_a_lane_a_stagger_short_of_a_clearance_beside_it_and_a_part_is_walled_in():
    """Pin 44's 45 lane at the depth a lane parallel to the row needs, pin 45's straight stub ending level with its riser:
    going on at 45 from the stub's end is 0.28 mm off the lane across their direction, under track + clearance, and the
    bypass part stands west, joined to pin 46 by a track along the row. The stub itself is legal; the pin has no way out."""
    from placemat.values import Corner
    from tests.escape_fixtures import bypass_135, TRACK56, CLEAR56
    cap = bypass_135("C1", "cap", ("N46", "GND"), 25.02, 27.86)
    g = one_pad("G1", "g1", "GND", 10.0, 10.0)
    b = fan_board([cap, g], exposed=True, keep_going=True)
    b.place(Part("g1"), at=Location(10.0, 10.0))
    b.place(Part("cap"), at=Location(25.02, 27.86))
    lane = b.escape(Part("mcu"), [44], turn=Corner.NW, depth=TRACK56 + CLEAR56, why="pin 44's lane")
    stub = b.escape(Part("mcu"), [45], why="pin 45's stub")
    b.track(Net("N44"), [lane[44]], layer=F, why="its lane")
    b.track(Net("N45"), [stub[45]], layer=F, why="its stub")
    b.track(Net("N46"), [PadRef(Part("mcu"), 46), PadRef(Part("cap"), 1)], layer=F, why="pin 46's bypass")
    plan = b.resolve()
    walled = _walled(plan)
    assert any(w.startswith("U1 pin 45 (N45): ") and "no other pad" in w for w in walled), walled
    assert not any(w.startswith("U1 pin 44 ") for w in walled), walled


def test_a_pin_the_design_leaves_unconnected_is_not_a_handoff():
    """A generator's no-connect nets (Zener's NC_<part>_<pin>, KiCad's unconnected-(...)) go nowhere."""
    plan = _wall_board(pin_nets={50: "mcu.NC_chip_GPIO50", 51: "unconnected-(U1-Pad51)", 52: "mcu.GPIO52"}).resolve()
    walled = _walled(plan)
    assert any(w.startswith("U1 pin 49 ") for w in walled), walled
    assert not any(w.startswith("U1 pin %d " % n) for n in (50, 51, 52) for w in walled), walled


def test_a_pin_with_something_to_join_is_judged_as_before():
    """A net of two pads keeps its corridors in the search; the handoff check is for the nets with one."""
    a = one_pad("X1", "x1", "X", 26.0, 28.0)
    c = one_pad("X2", "x2", "X", 26.0, 32.0)
    far = one_pad("F1", "f1", "N50", 10.0, 30.0)                      # pin 50's net has a second pad
    g = one_pad("G1", "g1", "GND", 10.0, 10.0)
    b = fan_board([a, c, far, g], exposed=True, keep_going=True)
    for ref, xy in (("x1", (26.0, 28.0)), ("x2", (26.0, 32.0)), ("f1", (10.0, 30.0)), ("g1", (10.0, 10.0))):
        b.place(Part(ref), at=Location(*xy))
    b.track(Net("X"), [PadRef(Part("x1"), 1), PadRef(Part("x2"), 1)], layer=F, why="the wall")
    plan = b.resolve()
    assert not any("no other pad" in w for w in _walled(plan) if "pin 50" in w)
