"""A decided cell tries its arrangements at its spot: each laid as the declaration lays it, judged as a firm item is judged and
scored once against what is placed."""
import dataclasses

from placemat import finding_text, step_text
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, Location, Part
from tests.arrangement_support import OBSTACLE, stamped_geometry, with_arrangement

AT = Location(40.0, 30.0)


def firm(partner=None, searched_partner=False, settings=None, ids=None, doc=None, obstacle=None):
    g = with_arrangement(stamped_geometry(partner=partner, obstacle=obstacle), doc)
    b = Board(g, edge_margin=0.0, keep_going=True, settings=settings or Settings())
    b.rect(width=80, height=60)
    if obstacle is not None:
        b.place(Part("obst"), at=Location(obstacle[0], obstacle[1]))
    if partner is not None:
        (b.place(Part("r8")) if searched_partner else b.place(Part("r8"), at=Location(*partner)))
    b.place(Cell("mod"), at=AT, **({"arrangements": ids} if ids else {}))
    return b.resolve()


def note_of(plan):
    return next(n for n in plan.step("mod").notes if n["kind"] == "arrangement")


def test_a_firm_cell_takes_the_arrangement_that_scores_lower_at_its_spot():
    plan = firm(partner=(60.0, 30.0))
    assert plan.placement("mod").arrangement == "c_in.east"
    note = note_of(plan)
    assert [(t["id"], t["legal"]) for t in note["tried"]] == [("default", True), ("c_in.east", True)]
    assert note["score"] < note["default_score"] and plan.placement("mod").location == AT
    east = with_arrangement().cells["mod"].arranged("c_in.east").box
    assert abs(plan.box("mod").left - (AT.x - east.width / 2)) < 1e-3     # its box centre on the point; its west edge is c_in's body


def test_it_keeps_the_default_on_a_tie_and_when_its_partners_are_unplaced():
    assert firm(partner=None).placement("mod").arrangement == ""
    assert firm(partner=(60.0, 30.0), searched_partner=True).placement("mod").arrangement == ""
    assert firm(partner=(18.0, 30.0)).placement("mod").arrangement == ""
    big = dataclasses.replace(Settings(), score_arrangement=1000.0)
    assert firm(partner=(60.0, 30.0), settings=big).placement("mod").arrangement == ""


def test_the_only_legal_arrangement_is_taken_when_the_default_is_illegal_and_none_when_none_is():
    plan = firm(obstacle=OBSTACLE)
    assert plan.placement("mod").arrangement == "c_in.east"
    note = note_of(plan)
    assert note["tried"][0]["legal"] is False and "default_blame" in note
    held = firm(obstacle=OBSTACLE, ids=("default",))                      # pinned to the layout that collides: a firm collision as today
    (f,) = [f for f in held.findings if f.cause == "fixed.part"]
    assert f.facts["item"] == "mod" and held.placement("mod").arrangement == ""
    both = firm(obstacle=(40.0, 30.0, 12.0, 8.0))                          # a part over the whole cell: no arrangement is legal
    (g,) = [f for f in both.findings if f.cause == "fixed.part" and f.facts["item"] == "mod"]
    assert [a["id"] for a in g.facts["arrangements"]] == ["c_in.east"]    # the default's finding, the others' refusals under it


def test_arrangements_with_one_id_lays_that_one_and_several_limit_the_trial():
    assert firm(partner=(60.0, 30.0), ids="default").placement("mod").arrangement == ""
    assert firm(partner=(18.0, 30.0), ids="c_in.east").placement("mod").arrangement == "c_in.east"
    assert firm(partner=(60.0, 30.0), ids=("default", "c_in.east")).placement("mod").arrangement == "c_in.east"


def test_a_cell_that_offers_none_is_settled_exactly_as_before():
    plain = Board(stamped_geometry(partner=(60.0, 30.0)), edge_margin=0.0, keep_going=True)
    plain.rect(width=80, height=60)
    plain.place(Part("r8"), at=Location(60.0, 30.0))
    plain.place(Cell("mod"), at=AT)
    p = plain.resolve()
    assert p.placement("mod").arrangement == "" and not [n for n in p.step("mod").notes if n["kind"] == "arrangement"]


def test_a_part_placed_beside_the_cell_follows_the_arrangement_it_took():
    from placemat.values import Beside, Edge
    g = with_arrangement(stamped_geometry(partner=(60.0, 30.0)))
    b = Board(g, edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Cell("mod"), at=AT)
    b.place(Part("r9"), at=Beside(Cell("mod"), Edge.EAST))
    plan = b.resolve()
    assert plan.placement("mod").arrangement == "c_in.east" and plan.box("r9").left >= plan.box("mod").right - 1e-6


def test_the_margin_keeps_the_default_when_the_other_is_not_that_much_better():
    gain = (lambda n: n["default_score"] - n["score"] - n["cost"])(note_of(firm(partner=(60.0, 30.0))))
    wide = dataclasses.replace(Settings(), place_arrangement_margin=gain + 0.01)
    plan = firm(partner=(60.0, 30.0), settings=wide)
    note = note_of(plan)
    assert plan.placement("mod").arrangement == "" and note["within"]["id"] == "c_in.east"
    assert note["default_score"] == note["score"]
    named = firm(partner=(60.0, 30.0), settings=wide, ids=("default", "c_in.east"))   # the script chose among them: no margin
    assert named.placement("mod").arrangement == "c_in.east"


def test_the_notes_and_the_finding_render():
    taken = step_text.render(note_of(firm(obstacle=OBSTACLE)))
    assert taken.startswith("arrangement c_in.east: the default module has no legal spot (") and "R7" in taken
    scored = step_text.render(note_of(firm(partner=(60.0, 30.0))))
    assert scored.startswith("arrangement c_in.east: ") and "as the default module stands" in scored
    both = firm(obstacle=(40.0, 30.0, 12.0, 8.0))
    assert step_text.render(note_of(both)).startswith("no arrangement has a legal spot: tried default and c_in.east")
    (g,) = [f for f in both.findings if f.cause == "fixed.part" and f.facts["item"] == "mod"]
    said = finding_text.render(g.cause, g.facts)
    assert said.startswith("mod (fixed): ") and "; arrangement c_in.east: " in said


def labelled(y=26.0):
    """The firm cell with a placed partner and a label south of part r9, at `y`, in the way of the cell."""
    from placemat.values import Edge
    b = Board(with_arrangement(stamped_geometry(partner=(60.0, 30.0))), edge_margin=0.0, keep_going=True)
    b.rect(width=80, height=60)
    b.place(Part("r8"), at=Location(60.0, 30.0))
    b.place(Part("r9"), at=Location(40.0, y))
    b.label(Part("r9"), "LONGTEXT", side=Edge.SOUTH, gap=0.2)
    b.place(Cell("mod"), at=AT)
    return b.resolve()


def test_a_label_in_the_way_gives_way_to_the_arrangement_taken():
    plan = labelled()
    assert plan.placement("mod").arrangement == "c_in.east"
    assert "moved from south" in plan.step("label r9 LONGTEXT").note
    assert not [f for f in plan.findings if f.cause == "fixed.part"]


def test_a_label_that_does_not_give_way_is_a_firm_collision(monkeypatch):
    monkeypatch.setattr(Board, "_labels_give_way", lambda *a, **k: False)
    plan = labelled()
    (f,) = [f for f in plan.findings if f.cause == "fixed.part"]
    assert f.facts["item"] == "mod" and plan.placement("mod").arrangement == "c_in.east"
    assert [n["kind"] for n in plan.step("mod").notes][-2:] == ["refused", "arrangement"]
