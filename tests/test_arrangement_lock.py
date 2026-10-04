import dataclasses
import json

from placemat import lock as L
from placemat.findings import FindingCause as C
from placemat.finding_text import render
from placemat.freeze import edit_call, frozen_args, why_text
from placemat.layout import Board
from placemat.placement import Placement
from placemat.values import Cell, Face, Location, Near, Part
from tests.arrangement_support import east_doc, stamped_geometry, with_arrangement
from tests.test_arrangement_search import NEAR


def board(g, partner=(60.0, 30.0), **place):
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(*partner))
    b.place(Cell("mod"), at=Near(Location(40.0, 30.0), **NEAR), **place)
    return b


def test_an_entry_with_an_arrangement_round_trips_and_a_default_entry_writes_the_bytes_it_wrote(tmp_path):
    e = L.LockEntry("mod", None, None, (1.0, 2.0), 0.0, "front", "abc", 0, "r", "run", 1.5, "c_in.east")
    d = L.LockEntry("mod", None, None, (1.0, 2.0), 0.0, "front", "abc")
    path = tmp_path / "x.lock.json"
    L.write(path, [e])
    assert L.read(path)[0].arrangement == "c_in.east"
    L.write(path, [d])
    assert "arrangement" not in path.read_text() and L.read(path)[0].arrangement == ""


def test_the_declaration_digest_of_a_default_entry_is_unchanged_and_an_arranged_one_differs():
    b = board(with_arrangement(stamped_geometry(partner=(60.0, 30.0))))
    i = next(x for x in b._placements() if x.key == "mod")
    assert L.declaration_digest(b, i) == L.declaration_digest(b, i, arrangement="")
    assert L.declaration_digest(b, i, arrangement="c_in.east") != L.declaration_digest(b, i)


def test_an_accepted_entry_holds_the_arrangement_and_places_it_again():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g)
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east"
    entries = L.entries(b, plan, ["mod"])
    assert entries[0].arrangement == "c_in.east"
    again = board(g).resolve(lock=entries)
    assert again.placement("mod") == plan.placement("mod") and again.step("mod").lock == "held"


def test_an_entry_whose_arrangement_the_module_no_longer_offers_is_released_with_a_finding():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g)
    entries = L.entries(b, b.resolve(), ["mod"])
    gone = board(stamped_geometry(partner=(60.0, 30.0)))
    plan = gone.resolve(lock=entries)
    assert plan.step("mod").lock == "released" and plan.placement("mod").arrangement == ""
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.facts["asked"] == ["c_in.east"] and f.facts["source"] == "lock"


def test_freeze_writes_the_arrangement_into_the_call():
    turn = {"placement": Placement(Location(10.0, 20.0), 0.0, Face.FRONT, "c_in.east"), "anchor": None}
    b = board(with_arrangement(stamped_geometry(partner=(60.0, 30.0))))
    args = frozen_args(b, "mod", turn, False, why="'w'")
    assert args["arrangements"] == "'c_in.east'" and args["at"].startswith("Near(")
    entry = L.LockEntry("mod", None, None, (1.0, 2.0), 0.0, "front", "abc", 0, "", "run1", 41.2, "c_in.east")
    assert "arrangement c_in.east" in why_text("w", entry, "2026-10-04")
    src = 'board.place(Cell("mod"), at=Near(Location(1, 2)), why="w")\n'
    out = edit_call(src, 1, args)
    assert "arrangements='c_in.east'" in out or 'arrangements="c_in.east"' in out


# ------------------------------------------------------------------ beyond the plan's tests
def test_the_released_entry_says_the_arrangement_is_gone_and_the_finding_is_a_warning_from_the_lock():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g)
    entries = L.entries(b, b.resolve(), ["mod"])
    plan = board(stamped_geometry(partner=(60.0, 30.0))).resolve(lock=entries)
    (f,) = [f for f in plan.findings if f.cause == "arrangement.missing"]
    assert f.severity == "warning" and f.facts == {"item": "mod", "asked": ["c_in.east"], "offered": ["default"],
                                                   "source": "lock"}
    note = next(n for n in plan.step("mod").notes if n["kind"] == "lock_released")
    assert note["reason"] == {"form": "arrangement_gone", "id": "c_in.east"}
    text = render(C.ARRANGEMENT_MISSING, f.facts)
    assert "lock" in text and "c_in.east" in text and "arrangements=" not in text


def test_an_entry_whose_arrangement_moved_its_members_is_released_as_a_changed_declaration():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g)
    entries = L.entries(b, b.resolve(), ["mod"])
    from placemat import arrangement_note as N
    from tests.arrangement_support import DEFAULT_C_IN, DEFAULT_U1
    moved = N.document("c_in.east", {"c_in": "east"}, [("c_in", Placement(Location(11.5, 3.0), 180.0, Face.FRONT), DEFAULT_C_IN),
                                                         ("u1", DEFAULT_U1, DEFAULT_U1)], [], [], order=1)
    plan = board(with_arrangement(stamped_geometry(partner=(60.0, 30.0)), moved)).resolve(lock=entries)
    assert plan.step("mod").lock == "released"
    note = next(n for n in plan.step("mod").notes if n["kind"] == "lock_released")
    assert note["reason"] == {"form": "declaration_changed"}
    assert not [f for f in plan.findings if f.cause == "arrangement.missing"]


def test_a_cell_pinned_to_the_arrangement_its_entry_holds_is_held():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g, arrangements="c_in.east")
    plan = b.resolve()
    entries = L.entries(b, plan, ["mod"])
    assert entries[0].arrangement == "c_in.east"
    again = board(g, arrangements="c_in.east").resolve(lock=entries)
    assert again.placement("mod") == plan.placement("mod") and again.step("mod").lock == "held"


def test_a_locked_cell_is_laid_in_its_arrangement_where_the_search_would_choose_the_default():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = board(g)
    plan = b.resolve()
    p = plan.placement("mod")
    (e,) = L.entries(b, plan, ["mod"])
    e = dataclasses.replace(e, anchor=None, anchor_face=None, offset=(p.location.x, p.location.y), rotation=p.rotation)
    west = with_arrangement(stamped_geometry(partner=(18.0, 30.0)))     # the pull is west: the search keeps the default
    assert board(west, partner=(18.0, 30.0)).resolve().placement("mod").arrangement == ""
    again = board(west, partner=(18.0, 30.0)).resolve(lock=[e])
    assert again.step("mod").lock == "held" and again.placement("mod") == p
    assert again.occupancy.items["C1"].reference.rotation == 180.0


def test_a_cell_locked_in_its_default_freezes_to_the_default_where_an_arrangement_scores_better_at_that_spot():
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    held = board(g, arrangements="default").resolve()
    p = held.placement("mod")
    assert p.arrangement == ""
    turn = {"placement": p, "anchor": None}
    args = frozen_args(board(g), "mod", turn, False)
    assert args["arrangements"] == "'default'"

    def frozen(**pin):
        b = Board(g, edge_margin=0.0, keep_going=True)
        b.rect(width=80, height=60)
        b.place(Part("r8"), at=Location(60.0, 30.0))
        b.place(Cell("mod"), at=Near(p.location, radius=0), rotation=p.rotation, **pin)
        return b.resolve().placement("mod")
    assert frozen().arrangement == "c_in.east"         # unpinned, the search takes the arrangement at the same spot
    assert frozen(arrangements=eval(args["arrangements"])) == p


def test_a_cell_that_offers_no_arrangement_freezes_with_no_arrangements_keyword():
    turn = {"placement": Placement(Location(10.0, 20.0), 0.0, Face.FRONT), "anchor": None}
    assert "arrangements" not in frozen_args(board(stamped_geometry(partner=(60.0, 30.0))), "mod", turn, False)
    assert "arrangements" not in frozen_args(board(stamped_geometry(partner=(60.0, 30.0))), "r8", turn, False)
