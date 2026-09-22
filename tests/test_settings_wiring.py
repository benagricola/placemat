"""A setting reaches the code that uses it. Each test changes one value and
asserts the behaviour it governs, rather than that the attribute exists."""
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location, Part
from tests.fixtures import board_geometry, footprint


def _geom():
    return board_geometry([footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "B")),
                           footprint("R1", 30, 30, w=2, h=1, inst="r1", nets=("B", "C"))],
                          width=60, height=60)


def test_the_board_carries_its_settings_and_hands_them_to_the_occupancy():
    s = Settings(place_step=0.05)
    b = Board(_geom(), edge_margin=1.0, settings=s)
    assert b.settings is s
    plan = b.resolve()
    assert plan.occupancy.settings is s


def test_a_default_board_gets_the_default_settings():
    b = Board(_geom(), edge_margin=1.0)
    assert b.settings == Settings()


def test_courtyard_touch_decides_whether_two_courtyards_overlap():
    """Two courtyards inside `place.courtyard_touch` of each other are packing,
    not a collision. Raise the tolerance and a real overlap reads as touching.

    Asserted on the message, not on legality: at this distance the pads of the
    two parts foul each other too, and that is a different rule."""
    g = _geom()
    tight = Occupancy(g, edge_margin=0.0, settings=Settings(place_courtyard_touch=0.02))
    loose = Occupancy(g, edge_margin=0.0, settings=Settings(place_courtyard_touch=5.0))
    u1 = g.footprint("U1")
    onto = Placement(Location(30.0, 30.0), 0.0, Face.FRONT)     # right on R1
    assert "courtyard overlaps" in (tight.legal(u1, onto) or "")
    assert "courtyard overlaps" not in (loose.legal(u1, onto) or "")


def test_the_scan_step_is_the_declared_one():
    """A scored scan walks the whole grid, so a finer step is more candidates.
    Without a score it stops at the first legal spot and tries exactly one."""
    from placemat.placer import scan
    g = _geom()
    occ = Occupancy(g, edge_margin=0.0, settings=Settings())
    u1 = g.footprint("U1")
    hint = Placement(Location(20, 20), 0, Face.FRONT)
    nowhere = lambda p: 0.0
    coarse = scan(occ, u1, hint, radius=1.0, step=1.0, score=nowhere)
    fine = scan(occ, u1, hint, radius=1.0, step=0.25, score=nowhere)
    assert fine.tried > coarse.tried


def test_the_coarse_pass_is_skipped_below_the_declared_ratio():
    """`place.coarse_from` is the radius-to-step ratio at which a scored scan
    goes coarse first. Below it the fine grid is walked once."""
    from placemat.placer import scan
    g = _geom()
    u1 = g.footprint("U1")
    hint = Placement(Location(20, 20), 0, Face.FRONT)
    nowhere = lambda p: 0.0
    never = Occupancy(g, edge_margin=0.0, settings=Settings(place_coarse_from=1e9))
    always = Occupancy(g, edge_margin=0.0, settings=Settings(place_coarse_from=1.0))
    direct = scan(never, u1, hint, radius=4.0, step=0.25, score=nowhere)
    staged = scan(always, u1, hint, radius=4.0, step=0.25, score=nowhere)
    assert staged.tried < direct.tried
