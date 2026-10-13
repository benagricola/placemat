"""A plane-net pad joined by drawn copper (a track) to a pad that carries a plane drop is connected: it has no way out
to look for and is not walled off, whether the part is laid out as a module alone or stamped as a cell on a board."""
import dataclasses
import json

from placemat.board_geometry import CopperItem, Footprint
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, Cell, CopperLayer, Face, Location, Net, PadRef, Part
from tests import real_modules as rm
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, pad, track

F, B = CopperLayer.F, CopperLayer.B
GAP = 0.1                       # under the clearance: the ring pads wall the centre pad in
R = 0.25 + GAP + 0.5            # the ring pads' distance from the centre pad


def _parts(cell=None):
    """U9's GND pad at (30, 30), walled in by pads of another net (N1's SIG) GAP mm clear of it all round, but for two on
    the east side that leave a slit too narrow for a track and its clearances, and N1's GND pad 2.4 mm east, beyond the slit:
    the pad U9's GND pad is joined to."""
    spots = [(-R, -R), (0.0, -R), (R, -0.725), (-R, 0.0), (-R, R), (0.0, R), (R, 0.725)]
    ring = [pad("N1", "n1", k, "SIG", 30 + x, 30 + y, 1.0, 1.0) for k, (x, y) in enumerate(spots, 2)]
    ring.append(pad("N1", "n1", "GND", "GND", 32.4, 30, 0.5, 0.5))
    body = Box(26, 26, 34, 34)
    n1 = Footprint("N1", "n1", cell, "N1", Location(30, 30), 0.0, Face.FRONT, body, body.inflate(0.1), body, tuple(ring))
    box = Box(29.7, 29.7, 30.3, 30.3)
    u9 = Footprint("U9", "u9", cell, "U9", Location(30, 30), 0.0, Face.FRONT, box, box, box,
                   (pad("U9", "u9", "GND", "GND", 30, 30, 0.5, 0.5),))
    return [u9, n1]


def _walled(plan):
    return [str(f) for f in plan.findings if f.kind == "escape_walled"]


def _board(fps, copper=(), cells=()):
    # the search and the report at one depth, as a board's escape_depth sets them: the report reads the escapes the search kept
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False, score_escape_depth=Settings().score_escape_depth)
    b = Board(board_geometry(fps, cells=cells, copper=copper, width=60, height=60), edge_margin=1.0, settings=cfg,
              keep_going=True)
    b.plane(Net("GND"), layers=(B,))
    return b


def _via(x, y, owner, size=0.45, drill=0.2):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", "GND", frozenset([F, B]), (ring,), Box.of_points(ring), owner, size, drill, ((x, y),))


def _module(copper):
    fps = _parts()
    b = _board(fps)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    if copper:
        b.track(Net("GND"), [PadRef(Part("u9"), "GND"), PadRef(Part("n1"), "GND")], layer=F, why="joins the pad to the drop")
        b.via(Net("GND"), PadRef(Part("n1"), "GND"), size=0.45, drill=0.2, why="the plane drop")
    return b.resolve()


def _cell(copper):
    fps = [footprint("T1", 50, 50, inst="t.t1", nets=("SIG", "B"), cell="t")] + _parts("m")
    own = [track("GND", 30, 30, 32.4, 30, w=0.2, owner="m"), _via(32.4, 30, "m")] if copper else []
    b = _board(fps, copper=own, cells=["t", "m"])
    b.place(Cell("t"), at=Location(50, 50))
    b.place(Cell("m"))
    return b.resolve()


def test_the_pad_with_no_copper_is_walled_off_as_a_module_and_as_a_cell():
    assert _walled(_module(False)) == ["U9 pin GND (GND): walled off by N1"]
    assert _walled(_cell(False)) == ["U9 pin GND (GND): walled off by N1"]


def test_a_module_joins_the_pad_to_a_plane_drop_by_a_track_so_it_is_not_walled_off():
    assert _walled(_module(True)) == []


def test_a_stamped_cell_joins_the_pad_to_a_plane_drop_by_a_track_so_it_is_not_walled_off():
    assert _walled(_cell(True)) == []


@needs_kicad
def test_the_switch_cells_of_a_real_board_are_not_walled_off_at_their_ground_pins(tmp_path):
    """fixtures/fairing/usb_cells: the source and sink switch cells stamped from a real generation, each with a track from the
    switch's ground pin to its resistor's ground pad, a pad that holds a via to the ground planes (a board's session, 2026-10-02)."""
    def captured_scene(_script):
        # Contact judgement needs the real owned copper, not an unrelated
        # search of two cells across every face and turn of a 40 mm disc.
        return '''from placemat import board, Cell, CopperLayer, Net
from placemat.occupancy import Occupancy
cells = [board.cell(key) for key in ("usbpd.esd", "usbpd.sink", "usbpd.source")]
# Plane drawing needs an explicit frame. Enclose the captured absolute
# poses without translating any of their copper or contact geometry.
board.rect(width=max(fp.body.x1 for cell in cells for fp in cell.members) + 2,
           height=max(fp.body.y1 for cell in cells for fp in cell.members) + 2)
board.plane(Net("GND"), layers=(CopperLayer.IN1, CopperLayer.IN4))
board.plane(Net("V3V3"), layers=(CopperLayer.IN3,))
occ = Occupancy(board.geometry)
for key in ("usbpd.esd", "usbpd.sink", "usbpd.source"):
    cell = board.cell(key)
    assert cell.members
    if key != "usbpd.esd":
        own = [c for c in board.geometry.copper if c.owner == key and c.net == "GND"]
        assert any(c.kind == "track" for c in own)
        assert any(c.kind == "via" for c in own)
    pose = occ._geometry(cell).reference
    board.place(Cell(key), at=pose.location, face=pose.face, rotation=pose.rotation)
'''

    result, _, _ = rm.run(tmp_path, "usbcells", keep_going=True, edit=captured_scene)
    walled = [str(f) for f in json.loads((result.run_dir / "run.json").read_text())["findings"] if "walled off" in str(f)]
    assert not [w for w in walled if "(GND)" in w], walled


def _ring_with_far_diagonal(track_ends):
    """U9's IN pad ringed 0.8 mm off by R9's pads (a via fits at its edge), and a diagonal track of another net well clear of
    the pad, whose box covers the window the way out is looked for in."""
    from tests.test_escape_findings import _walled_in
    fps = _walled_in(0.8)
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    b.track(Net("Z"), list(track_ends), layer=F, why="a diagonal track far from the pad")
    return b.resolve()


def test_a_diagonal_track_whose_box_covers_the_way_out_does_not_wall_a_pad_it_keeps_clear_of():
    plan = _ring_with_far_diagonal([Location(20.0, 50.0), Location(50.0, 20.0)])
    assert _walled(plan) == []
