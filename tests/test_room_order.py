"""`place.order = "room"`: within a tier the item with the fewest legal spots left goes first, then the rank; the
default (`freedoms`) is the order it always was."""
import dataclasses

import pytest

from placemat import room
from placemat.layout import Board
from placemat.settings import Settings, SettingsError, load
from placemat.cutouts import Circle
from placemat.values import Centre, Edge, Location, Near, Part, Priority
from tests.fixtures import board_geometry, footprint


def _board(**settings):
    """A large part, a small one and a smaller one, on a board 40 wide and 50 tall."""
    fps = [footprint("BIG", 20, 25, w=10, h=10, inst="big", nets=("A", "B")),
           footprint("SML", 20, 25, w=3, h=2, inst="sml", nets=("C", "D")),
           footprint("T1", 20, 25, w=2, h=1, inst="t1", nets=("E", "F"))]
    return Board(board_geometry(fps, width=40, height=50), edge_margin=0.5, keep_going=True,
                 settings=dataclasses.replace(Settings(), **settings))


def _order(plan, *keys):
    return [s.item for s in plan.steps if s.item in keys]


def _declare(b):
    """A slide the length of the board, and an item held to a 2 mm radius round a point."""
    b.place(Part("big"), at=Centre(20, None, toward=Edge.SOUTH))
    b.place(Part("sml"), at=Near(Location(20, 25), radius=2.0))


def test_by_default_the_item_with_fewer_freedoms_goes_first():
    b = _board()
    _declare(b)
    assert _order(b.resolve(), "big", "sml") == ["big", "sml"]


def test_with_room_the_item_with_fewer_legal_spots_goes_first():
    b = _board(place_order="room")
    _declare(b)
    assert _order(b.resolve(), "big", "sml") == ["sml", "big"]


def test_room_leaves_the_tiers_alone():
    b = _board(place_order="room")
    b.place(Part("big"), at=Centre(20, None, toward=Edge.SOUTH), priority=Priority.HIGH)
    b.place(Part("sml"), at=Near(Location(20, 25), radius=2.0))
    assert _order(b.resolve(), "big", "sml") == ["big", "sml"]


def test_items_in_one_band_of_room_go_by_rank():
    b = _board(place_order="room")
    for key in ("t1", "sml", "big"):
        b.place(Part(key))
    assert _order(b.resolve(), "big", "sml", "t1") == ["big", "sml", "t1"]


def test_a_keepout_that_bars_an_item_narrows_its_room():
    """A hint 8 mm wide is more room than the slide, until a keepout over most of it takes the room."""
    plain, fenced = _board(place_order="room"), _board(place_order="room")
    for b in (plain, fenced):
        b.place(Part("big"), at=Centre(20, None, toward=Edge.SOUTH))
        b.place(Part("sml"), at=Near(Location(20, 25), radius=8.0))
    fenced.keepout(Circle(15.0), "fence", at=Location(20, 25), excludes=("parts",), why="test")
    assert _order(plain.resolve(), "big", "sml") == ["big", "sml"]
    assert _order(fenced.resolve(), "big", "sml") == ["sml", "big"]


def test_the_step_records_how_much_room_the_item_had():
    b = _board(place_order="room")
    _declare(b)
    notes = {s.item: s.notes for s in b.resolve().steps if s.item in ("big", "sml")}
    note = next(n for n in notes["sml"] if n["kind"] == "room")
    assert note["form"] == "near" and note["pitch_mm"] == 1.0
    assert note["spots"] == pytest.approx(3.14159 * 4.0, abs=0.1)
    slide = next(n for n in notes["big"] if n["kind"] == "room")
    assert slide["form"] == "line" and slide["spots"] > note["spots"] and slide["level"] > note["level"]


def test_the_default_records_no_room():
    b = _board()
    _declare(b)
    assert not [n for s in b.resolve().steps for n in s.notes if n["kind"] == "room"]


def test_a_slide_counts_its_length_less_its_own_size():
    b = _board(place_order="room")
    b.place(Part("sml"), at=Centre(20, None, toward=Edge.SOUTH))
    i = next(i for i in b._placements() if i.key == "sml")
    found = room.measure(b, b.resolve().occupancy, i, 1.0)
    body = b.resolve().occupancy._geometry(i.item).body       # 50 mm tall, 0.5 mm in from each edge, less the part's mean size
    assert found["form"] == "line" and found["spots"] == pytest.approx(49 - (body.width + body.height) / 2, abs=1e-6)


@pytest.mark.parametrize("spots,ratio,band", [(0.0, 2.0, -1), (0.5, 2.0, -1), (1.0, 2.0, 0), (1.9, 2.0, 0), (2.0, 2.0, 1),
                                              (63.0, 2.0, 5), (64.0, 2.0, 6), (9.0, 3.0, 2)])
def test_level_is_how_many_times_the_ratio_goes_into_the_spots(spots, ratio, band):
    assert room.level(spots, ratio) == band


def test_place_order_is_a_project_and_a_script_setting(tmp_path):
    (tmp_path / "placemat.toml").write_text('[place]\norder = "room"\nroom_pitch = 0.5\n'
                                            '[scripts."a.py".place]\norder = "freedoms"\n')
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    assert load(tmp_path).place_order == "room" and load(tmp_path).place_room_pitch == 0.5
    assert load(tmp_path, script=tmp_path / "a.py").place_order == "freedoms"
    assert load(tmp_path, script=tmp_path / "b.py").place_order == "room"


def test_an_unknown_order_is_refused(tmp_path):
    (tmp_path / "placemat.toml").write_text('[place]\norder = "size"\n')
    with pytest.raises(SettingsError):
        load(tmp_path)
