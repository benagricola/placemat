import dataclasses

from placemat import explore as E
from placemat.explore import Explore
from placemat.layout import Board
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Cell, Face, Location, Near, Part
from tests.arrangement_support import stamped_geometry, with_arrangement
from tests.test_arrangement_search import NEAR


def seeded_board(g, **place):
    s = dataclasses.replace(Settings(), explore_spot_slack=5.0)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=s)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), **place)
    return b


def seeded_plan(seed, g, **place):
    b = seeded_board(g, **place)
    return b, b.resolve(explore=Explore(seed, frozenset({"mod"})))


def seeded(seed, g, **place):
    return seeded_plan(seed, g, **place)[1].placement("mod").arrangement


def test_a_variant_draws_among_the_arrangements_within_the_slack():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    seen = {seeded(seed, g) for seed in range(1, 25)}
    assert seen == {"", "c_in.east"}


def test_a_seed_draws_the_same_arrangement_and_spot_every_time():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    for seed in range(1, 9):
        assert seeded_plan(seed, g)[1].placement("mod") == seeded_plan(seed, g)[1].placement("mod")


def test_a_pinned_cell_is_not_drawn_into_another_arrangement():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    assert {seeded(seed, g, arrangements=("default",)) for seed in range(1, 25)} == {""}


def test_a_drawn_arrangement_is_in_the_step_note_and_the_lock_entries():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    seed = next(s for s in range(1, 25) if seeded(s, g) == "")       # a draw that leaves the cheaper arrangement
    b, plan = seeded_plan(seed, g)
    note = next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")
    assert note["id"] == "default" and [t["id"] for t in note["tried"]] == ["default", "c_in.east"]
    seed = next(s for s in range(1, 25) if seeded(s, g) == "c_in.east")
    b, plan = seeded_plan(seed, g)
    assert [e["arrangement"] for e in E._payload(b, plan, frozenset({"mod"}))["entries"]] == ["c_in.east"]


def test_the_plain_placement_is_still_the_best():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    plain = Board(g, edge_margin=0.0, keep_going=True)
    plain.rect(width=80, height=60)
    plain.place(Part("r8"), at=Location(60.0, 30.0))
    plain.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR))
    assert plain.resolve().placement("mod").arrangement == "c_in.east"


def test_a_move_reports_the_arrangement_change():
    was = Placement(Location(1.0, 1.0), 0.0, Face.FRONT, "")
    now = Placement(Location(1.0, 1.0), 0.0, Face.FRONT, "c_in.east")
    assert E._move_of("mod", was, now) == {"key": "mod", "mm": 0.0, "rotation": [0.0, 0.0], "arrangement": ["", "c_in.east"]}
    assert E._move_of("mod", was, was) is None


def test_the_report_words_an_arrangement_change():
    report = {"baseline": 10.0, "best": 9.0, "tried": 3, "focus": ["mod"], "best_seed": 2, "accepted": False,
              "moves": [{"key": "mod", "mm": 0.0, "rotation": [0.0, 0.0], "arrangement": ["", "c_in.east"]}]}
    assert "  mod: 0.00 mm, arrangement default -> c_in.east" in E._report_lines(report)
