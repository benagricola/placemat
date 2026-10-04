import dataclasses

import pytest

from placemat import explore as E
from placemat.explore import Explore
from placemat.layout import Board
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Cell, Face, Location, Near, Part
from tests.arrangement_support import stamped_geometry, with_arrangement
from tests.test_arrangement_search import NEAR


def seeded_board(g, settings=None, **place):
    s = settings or dataclasses.replace(Settings(), explore_spot_slack=5.0)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=s)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), **place)
    return b


def seeded_plan(seed, g, settings=None, **place):
    b = seeded_board(g, settings, **place)
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


def arrangement_note(plan):
    return next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")


def test_a_tight_slack_draws_only_the_best():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    tight = dataclasses.replace(Settings(), explore_spot_slack=0.0)
    plain = arrangement_note(seeded_board(g, tight).resolve())
    for seed in range(1, 13):
        note = arrangement_note(seeded_plan(seed, g, tight)[1])
        assert (note["id"], note["score"]) == (plain["id"], plain["score"])


EITHER = dataclasses.replace(Settings(), explore_spot_slack=5.0, score_back_face=0.5)


def test_an_either_face_cell_is_drawn_onto_either_face_in_either_arrangement():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    seen = set()
    for seed in range(1, 41):
        p = seeded_plan(seed, g, EITHER, face=Face.EITHER)[1].placement("mod")
        seen.add((p.arrangement, p.face))
    assert {f for _, f in seen} == {Face.FRONT, Face.BACK} and {a for a, _ in seen} == {"", "c_in.east"}


def test_a_drawn_back_spot_is_noted_at_its_own_score():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    backs = fronts = 0
    for seed in range(1, 41):
        plan = seeded_plan(seed, g, EITHER, face=Face.EITHER)[1]
        faced = [n for n in plan.step("mod").notes if n["kind"] == "back_face"]
        if plan.placement("mod").face is Face.FRONT:
            fronts += 1
            assert not faced and not plan.step("mod").back_face
            continue
        backs += 1
        (said,) = faced
        assert plan.step("mod").back_face
        assert said["cost"] == 0.5 and arrangement_note(plan)["score"] == pytest.approx(said["back"] + said["cost"], abs=1e-3)
    assert backs and fronts


def test_the_back_face_cost_prices_back_spots_out_of_the_pool():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    dear = dataclasses.replace(Settings(), explore_spot_slack=5.0, score_back_face=1e4)
    assert {seeded_plan(seed, g, dear, face=Face.EITHER)[1].placement("mod").face for seed in range(1, 25)} == {Face.FRONT}


def test_an_accepted_variant_replays_its_drawn_arrangement_from_the_lock(tmp_path):
    from placemat import lock as _lock
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    seed = next(s for s in range(1, 25) if seeded(s, g) == "")         # drawn off the best arrangement
    b, variant = seeded_plan(seed, g)
    path = tmp_path / "layout.lock.json"
    E._write_lock(path, [], {"mod"}, _lock.entries(b, variant, ["mod"]), variant)
    replay = seeded_board(g).resolve(lock=_lock.read(path))
    assert replay.step("mod").lock == "held"
    assert replay.placement("mod") == variant.placement("mod") and replay.placement("mod").arrangement == ""
