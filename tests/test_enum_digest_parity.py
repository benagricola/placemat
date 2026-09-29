"""0.52.0 accepted fixed-set arguments (line=, align=, excludes=, face=) as
plain strings; a later release gave several of them real Enum classes
(Line, Along, Forbid). A script that only ever used 0.52's own spellings
must still digest exactly as 0.52 did, or a lock or a reuse record it wrote
stops matching for no reason the script can see.

The digests below were computed by v0.52.0 for the board `_build` makes."""
from placemat import lock, reuse
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import Edge, Location, Part, X
from tests.fixtures import board_geometry, footprint

ACCEPTED_BY_0_52 = {
    "u1": "f3f6488e1b60c550",     # a plain place(): face defaults, untouched either way
    "j1": "fd0ab947a3bfe440",     # a row at a reference, default line=: stays deferred, so the Row itself digests
    "j2": "df7993f5e91a98ae",
    "j3": "002b6e8f05278514",     # a row at a reference, line="outer" (0.52's own spelling)
    "j4": "8c7eaed839cade86",     # a row, align="center" (0.52's own spelling)
}
ACCEPTED_EXCLUDES_BY_0_52 = "['parts','vias']"   # a keepout's excludes=["parts", "vias"] (0.52's own spelling)


def _build():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("J1", 30, 10, w=4, h=2, inst="j1", nets=("A", "B")),
           footprint("J2", 36, 10, w=4, h=2, inst="j2", nets=("A", "B")),
           footprint("J3", 10, 30, w=4, h=2, inst="j3", nets=("A", "B")),
           footprint("J4", 10, 40, w=4, h=2, inst="j4", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    # a row started at a reference stays deferred (a _RowSlot), so the Row
    # object - and its line field - is itself part of the intent's digest
    b.row([Part("j1"), Part("j2")], Edge.NORTH, gap=1.0, start=X(Part("u1")))
    b.row([Part("j3")], Edge.SOUTH, gap=1.0, start=X(Part("u1")), line="outer")
    b.row([Part("j4")], Edge.WEST, gap=1.0, align="center")
    b.keepout(Circle(4.0), "k1", at=Location(50, 50), excludes=["parts", "vias"], why="probe")
    return b


def test_a_script_using_only_0_52_spellings_digests_exactly_as_0_52_did():
    b = _build()
    placements = {i.key: lock.declaration_digest(b, i) for i in b._intents if hasattr(i, "item")}
    assert placements == ACCEPTED_BY_0_52


def test_a_keepouts_excludes_are_still_the_plain_strings_0_52_wrote():
    """Forbid gives excludes= its own enum now, but a script that named them
    the old way (plain strings) never touches it: excludes is stored - and
    digested - exactly as the script wrote it."""
    b = _build()
    k = next(i.keepout for i in b._intents if i.key == "keepout k1")
    assert reuse.canonical(k.excludes) == ACCEPTED_EXCLUDES_BY_0_52
