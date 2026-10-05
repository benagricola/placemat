"""The module run over combined units: a combination of two options that cannot stand together is refused alone; an option
refused in every combination that holds it is `arrangement.option_dead`; an excluded combination is recorded, not laid out; the
limit counts after exclusions."""
import dataclasses

from placemat import Alt, arrangement_run as run
from placemat.finding_text import arrangement_row_text, subject
from placemat.findings import Finding, FindingCause as C
from placemat.settings import Settings
from placemat.values import Beside, Edge, Part
from tests.arrangement_support import module

FIXED = {"form": "finding", "cause": "fixed.part", "item": "r_pull"}
UNPLACED = {"form": "unplaced", "item": "r_pull"}


def colliding(settings=None):
    """Two units of one part each whose `upright` stands the part north of u1, turned: each alone fits, the two together take
    one spot and collide. (Without the turn, Beside would stand the second part further out.)"""
    b = module(settings)
    b.keep_going = True                 # a collision is a finding, not the end of the resolve
    cap = b.unit("cap", Part("c_in"))
    b.alternative(cap, "upright", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH), rotation=90))
    pull = b.unit("pull", Part("r_pull"))
    b.alternative(pull, "upright", Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.NORTH), rotation=90))
    return b


def entry(ident, choices, offered, **more):
    return dict({"id": ident, "choices": choices, "offered": offered}, **more)


DEFAULT = entry("default", {}, True)


def test_two_options_that_cannot_stand_together_refuse_only_their_combination():
    prepared = run.begin(colliding())
    assert [s.id for s in prepared.specs] == ["default", "pull.upright", "cap.upright", "cap.upright+pull.upright"]
    default = run.resolve_spec(prepared, prepared.specs[0])
    refusals = {s.id: run.plan_refusals(run.resolve_spec(prepared, s), default) for s in prepared.specs}
    assert refusals["default"] == [] and refusals["pull.upright"] == [] and refusals["cap.upright"] == []
    assert refusals["cap.upright+pull.upright"]


def test_a_refused_combination_whose_options_stand_elsewhere_is_no_dead_option():
    """Review focus 5."""
    units = colliding().arrangement_units()
    record = [DEFAULT, entry("pull.upright", {"pull": "upright"}, True), entry("cap.upright", {"cap": "upright"}, True),
              entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, refused=[FIXED])]
    assert run.option_dead_findings(units, record) == []


def test_an_option_refused_in_every_combination_that_holds_it_is_dead_with_its_refusals():
    units = colliding().arrangement_units()
    record = [DEFAULT, entry("pull.upright", {"pull": "upright"}, False, refused=[UNPLACED]), entry("cap.upright", {"cap": "upright"}, True),
              entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, refused=[FIXED])]
    (f,) = run.option_dead_findings(units, record)
    assert f.cause is C.ARRANGEMENT_OPTION_DEAD and f.severity == "warning"
    assert f.facts == {"unit": "pull", "option": "upright", "choice": "pull.upright", "refused": ["pull.upright", "cap.upright+pull.upright"],
                       "reasons": {"pull.upright": [UNPLACED], "cap.upright+pull.upright": [FIXED]}}
    assert subject(f.cause, f.facts) == "pull.upright"


def test_a_duplicate_is_not_a_refusal_and_an_excluded_combination_does_not_count():
    """Review focus 5."""
    units = colliding().arrangement_units()
    duplicate = [DEFAULT, entry("pull.upright", {"pull": "upright"}, False, duplicate_of="default"),
                 entry("cap.upright", {"cap": "upright"}, True),
                 entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, refused=[FIXED])]
    assert run.option_dead_findings(units, duplicate) == []
    excluded = [DEFAULT, entry("pull.upright", {"pull": "upright"}, False, refused=[UNPLACED]), entry("cap.upright", {"cap": "upright"}, True),
                entry("cap.upright+pull.upright", {"cap": "upright", "pull": "upright"}, False, excluded={"why": "", "by": []})]
    (f,) = run.option_dead_findings(units, excluded)
    assert f.facts["refused"] == ["pull.upright"] and list(f.facts["reasons"]) == ["pull.upright"]


def test_an_excluded_combination_is_recorded_with_its_why_and_not_laid_out():
    b = colliding()
    b.exclude("cap.upright", "pull.upright", why="both stand north of u1")
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default", "pull.upright", "cap.upright"]
    assert [u.name for u in prepared.units] == ["cap", "pull"]
    gone = run.excluded_entries(prepared.excluded)
    assert gone == [{"id": "cap.upright+pull.upright", "choices": {"cap": "upright", "pull": "upright"}, "offered": False,
                     "excluded": {"why": "both stand north of u1", "by": ["cap.upright", "pull.upright"]}}]
    rows = run.lines([DEFAULT] + gone)
    assert rows[1] == {"id": "cap.upright+pull.upright", "state": "excluded", "why": "both stand north of u1",
                       "by": ["cap.upright", "pull.upright"]}
    assert arrangement_row_text(rows[1]) == "cap.upright+pull.upright: excluded, not laid out: both stand north of u1"
    assert arrangement_row_text(dict(rows[1], why="")) == "cap.upright+pull.upright: excluded, not laid out"


def test_the_limit_is_counted_after_exclusions_and_its_finding_says_how_to_come_under_it():
    tight = dataclasses.replace(Settings(), place_arrangements_max=3)
    facts = colliding(tight).arrangement_limit()
    assert facts == {"variant": "arrangements", "arrangements": 4, "max_arrangements": 3, "options": {"cap": 2, "pull": 2},
                     "max_options": 4, "excluded": 0}
    assert str(Finding(C.ARRANGEMENT_LIMIT, facts)) == (
        "this module declares 4 arrangements, over the 3 place.arrangements_max allows, so only the default is laid out; "
        "leave out the combinations that do not matter with board.exclude")
    b = colliding(tight)
    b.exclude("cap.upright", "pull.upright")
    assert b.arrangement_limit() is None and len(b.arrangement_specs()) == 3
