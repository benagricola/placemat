import dataclasses

import pytest

from placemat import Alt, arrangement_run as run
from placemat.settings import Settings
from placemat.values import Beside, CopperLayer, Edge, Location, Net, PadRef, Part
from tests.arrangement_support import module

F = CopperLayer.F


def board():
    b = module()
    b.keep_going = True             # c_in east of u1 meets r_pull there: a collision is a finding, not the end of the resolve
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    return b


def test_the_default_resolves_as_the_script_says_and_an_alternative_lays_its_option_over():
    b = board()
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]
    default = run.resolve_spec(prepared, prepared.specs[0])
    east = run.resolve_spec(prepared, prepared.specs[2])
    collided = lambda plan: [f for f in plan.findings if f.cause == "fixed.part"]
    assert not collided(default) and collided(east)                    # east lands on r_pull: a finding under keep_going
    u1 = default.placement("u1").location.x
    assert default.placement("c_in").location.x < u1 < east.placement("c_in").location.x
    again = run.resolve_spec(prepared, prepared.specs[0])
    assert again.placements == default.placements                      # the board was put back between resolves


def test_the_option_turns_one_member_and_leaves_the_rest():
    b = board()
    prepared = run.begin(b)
    default = run.resolve_spec(prepared, prepared.specs[0])
    turned = run.resolve_spec(prepared, prepared.specs[1])
    assert turned.placement("r_pull").rotation == 180.0 and default.placement("r_pull").rotation == 0.0
    assert turned.placement("c_in") == default.placement("c_in")


def with_tracks():
    """OUT straight from u1 to r_pull in the default; turned, r_pull's OUT pad is on its far side, so a detour north of it."""
    b = board()
    b.track(Net("OUT"), [PadRef(Part("u1"), 2), PadRef(Part("r_pull"), 1)], layer=F, only=("default",))
    b.track(Net("OUT"), [PadRef(Part("u1"), 2), Location(22.4, 13), Location(25.6, 13), PadRef(Part("r_pull"), 1)], layer=F,
            only=("r_pull.turned",))
    b.via(Net("VIN"), PadRef(Part("u1"), 1))                            # no only=: in every arrangement
    return b


def detoured(plan) -> bool:
    return any(abs(p.y - 13) < 1e-6 for op in tracks(plan) for p in (op.start, op.end))


def tracks(plan) -> list:
    return [op for op in plan.copper if hasattr(op, "start")]


def vias(plan) -> list:
    return [op for op in plan.copper if not hasattr(op, "start")]


def test_copper_exists_only_in_the_arrangements_it_names():
    prepared = run.begin(with_tracks())
    default = run.resolve_spec(prepared, prepared.specs[0])
    turned = run.resolve_spec(prepared, prepared.specs[1])
    assert not detoured(default) and len(tracks(default)) == 1
    assert detoured(turned) and len(tracks(turned)) == 5                # the detour's segments, and no straight track
    assert all(op.net == "OUT" for op in tracks(turned))
    east = run.resolve_spec(prepared, prepared.specs[2])
    assert tracks(east) == []                                           # neither track exists in c_in.east
    for spec in prepared.specs:
        assert [op.net for op in vias(run.resolve_spec(prepared, spec))] == ["VIN"], spec.id


def test_a_plain_resolve_lays_the_default_copper():
    plan = with_tracks().resolve()
    assert not detoured(plan) and len(tracks(plan)) == 1 and [op.net for op in vias(plan)] == ["VIN"]


def test_resolving_an_arrangement_leaves_the_board_as_it_was():
    plain = with_tracks().resolve()
    b = with_tracks()
    prepared = run.begin(b)
    run.resolve_spec(prepared, prepared.specs[3])                       # c_in.east+r_pull.turned
    assert b._laid == "default"
    after = b.resolve()
    assert after.placements == plain.placements and after.copper == plain.copper and len(after.copper) == 2


def test_a_resolve_that_raises_leaves_the_board_as_it_was():
    b = with_tracks()
    b.keep_going = False
    prepared = run.begin(b)
    with pytest.raises(Exception, match="collide"):
        run.resolve_spec(prepared, prepared.specs[2])                   # c_in.east lands on r_pull
    assert b._laid == "default" and next(i for i in b._intents if i.key == "c_in").beside.side == Edge.WEST
    assert len(b._copper) == 3


def test_two_arrangements_that_resolve_alike_have_one_signature():
    b = board()
    b.alternative(Part("c_in"), "same", at=Beside(Part("u1"), Edge.WEST))      # the default's own relation
    prepared = run.begin(b)
    plans = {s.id: run.resolve_spec(prepared, s) for s in prepared.specs}
    assert run.signature(plans["c_in.same"]) == run.signature(plans["default"])
    assert run.signature(plans["c_in.east"]) != run.signature(plans["default"])


def test_the_limit_finding_is_on_the_default_plan_and_the_resolve_is_the_default_alone():
    b = module(dataclasses.replace(Settings(), place_arrangements_max=2))
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    prepared = run.begin(b)
    assert [s.id for s in prepared.specs] == ["default"]
    plan = run.resolve_spec(prepared, prepared.specs[0])
    (f,) = [f for f in plan.findings if f.cause == "arrangement.limit"]
    assert f.facts["arrangements"] == 4 and f.facts["max_arrangements"] == 2 and f.severity == "warning"


def untimed(record):
    if isinstance(record, dict):
        return {k: untimed(v) for k, v in record.items() if k != "seconds"}
    if isinstance(record, list):
        return [untimed(v) for v in record]
    return record


def test_a_board_that_declares_no_alternative_resolves_as_before():
    plain = module().resolve()
    prepared = run.begin(module())
    got = run.resolve_spec(prepared, prepared.specs[0])
    assert got.placements == plain.placements and [str(f) for f in got.findings] == [str(f) for f in plain.findings]
    assert untimed(got.reuse) == untimed(plain.reuse) and list(got.steps) == list(plain.steps)
    assert not [f for f in plain.findings if f.cause.startswith("arrangement.")]


def test_an_option_takes_the_declared_intents_slot_and_keeps_its_pushes():
    b = board()
    b.push(Part("c_in"), from_=Part("r_pull"), falloff=2.0, reference=(1.0, 1.0), limit=0.5)
    declared = {i.key: i for i in b._intents}
    c_in = declared["c_in"]
    slot = (c_in.index, c_in.line, c_in.file, c_in.pushes, c_in.needs)
    prepared = run.begin(b)
    b._restore(prepared.saved)
    b.lay_arrangement(prepared.specs[2])                                # c_in.east
    laid = next(i for i in b._intents if i.key == "c_in")
    assert laid is c_in and laid.beside.side == Edge.EAST
    assert (laid.index, laid.line, laid.file, laid.pushes) == slot[:4] and slot[4] <= laid.needs
    assert [i.key for i in b._intents] == [i.key for i in sorted(b._intents, key=lambda i: i.index)]
    b._restore(prepared.saved)
    assert next(i for i in b._intents if i.key == "c_in").beside.side == Edge.WEST


def test_an_unknown_only_id_is_refused_before_the_resolve():
    b = board()
    b.track(Net("OUT"), [PadRef(Part("r_pull"), 1), PadRef(Part("u1"), 2)], layer=F, only=("r_pull.sideways",))
    with pytest.raises(ValueError, match="not an arrangement of this module"):
        b.resolve()
    c = board()
    c.track(Net("OUT"), [PadRef(Part("r_pull"), 1), PadRef(Part("u1"), 2)], layer=F, only=("r_pull.sideways",))
    with pytest.raises(ValueError, match="not an arrangement of this module"):
        run.begin(c)
