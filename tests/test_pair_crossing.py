"""A differential pair's own crossing costs `score.pair_crossing` at placement
(docs/superpowers/specs/2026-09-25-pair-crossing-design.md): the search and
cleanup uncross it by a swap or a turn, and the score carries it."""
import dataclasses

from placemat import score
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Near, Part
from tests.fixtures import board_geometry, footprint


def _board(parts, **settings):
    cfg = dataclasses.replace(Settings(), **settings)
    return Board(board_geometry(parts, width=60, height=60), edge_margin=1.0, settings=cfg)


def _chip():
    # the pair leaves the chip upright: D_P on the north pad, D_N on the south
    return footprint("U1", 10, 30, inst="u1", nets=("D_P", "D_N"), rotation=90.0)


def test_the_score_prices_a_pairs_own_crossing_at_the_pair_weight():
    # R1 carries D_P south of R2's D_N: the two airwires from the chip cross
    parts = [_chip(), footprint("R1", 25, 32, inst="r1", nets=("D_P", "E_P")),
             footprint("R2", 25, 28, inst="r2", nets=("D_N", "E_N"))]
    b = _board(parts)
    for ref, at in (("u1", (10, 30)), ("r1", (25, 32)), ("r2", (25, 28))):
        b.place(Part(ref), at=Location(*at))
    plan = b.resolve()
    m = score.plan_measures(b, plan)
    assert m["crossings"].get("pair") == 1
    t = score.terms(m, b.settings)
    assert t["crossings"] >= b.settings.score_pair_crossing


def _forced(**settings):
    # D_P leaves north (A1) and D_N south (A2); their series parts R1 and R2
    # run on to far ends whose order is the other way round (EA south, EB
    # north). One crossing is forced: in the pair (D side) or between the
    # ordinary nets EA and EB (far side)
    parts = [footprint("A1", 10, 26, inst="a1", nets=("Z1", "D_P")),
             footprint("A2", 10, 34, inst="a2", nets=("Z2", "D_N")),
             footprint("J1", 40, 26, inst="j1", nets=("EB", "Z3")),
             footprint("J2", 40, 34, inst="j2", nets=("EA", "Z4")),
             footprint("R1", 5, 5, inst="r1", nets=("D_P", "EA")),
             footprint("R2", 5, 10, inst="r2", nets=("D_N", "EB"))]
    b = _board(parts, **settings)
    for ref, at in (("a1", (10, 26)), ("a2", (10, 34)), ("j1", (40, 26)), ("j2", (40, 34))):
        b.place(Part(ref), at=Location(*at))
    # held at rotation 0 (pad 1 west): turned, a two-pad part is itself a
    # crossover, and the crossing would not be forced
    b.place(Part("r1"), rotations=(0,))
    b.place(Part("r2"), rotations=(0,))
    return b, b.resolve()


def test_the_weighted_search_keeps_a_pair_uncrossed_where_wire_alone_crosses_it():
    b, plan = _forced(score_pair_crossing=0.0, score_crossing=0.0)
    assert score.plan_measures(b, plan)["crossings"]["pair"] == 1       # wire alone: the pair crosses
    b, plan = _forced()
    assert score.plan_measures(b, plan)["crossings"]["pair"] == 0


def test_the_search_turns_a_part_to_uncross_a_pair():
    # a two-pad part carrying the pair's far ends: turned 90 its D_P pad faces
    # south and the pair crosses; turned 270 it does not
    parts = [_chip(), footprint("J1", 30, 30, inst="j1", nets=("D_P", "D_N"), rotation=90.0)]
    b = _board(parts)
    b.place(Part("u1"), at=Location(10, 30))
    b.place(Part("j1"), at=Near(Location(30, 30), radius=0.5), rotations=(90, 270))
    plan = b.resolve()
    assert score.plan_measures(b, plan)["crossings"].get("pair", 0) == 0


def test_a_crossed_pair_on_decided_parts_is_reported_with_its_parts():
    parts = [_chip(), footprint("R1", 25, 32, inst="r1", nets=("D_P", "E_P")),
             footprint("R2", 25, 28, inst="r2", nets=("D_N", "E_N"))]
    b = _board(parts)
    for ref, at in (("u1", (10, 30)), ("r1", (25, 32)), ("r2", (25, 28))):
        b.place(Part(ref), at=Location(*at))
    plan = b.resolve()
    said = [f for f in plan.findings if f.kind == "pair_crossed"]
    assert len(said) == 1, list(plan.findings)
    text = str(said[0])
    assert "D_P/D_N" in text and "R1" in text and "R2" in text and "U1" in text
    # priced once, by the crossings term, not again as a finding
    t = score.terms(score.plan_measures(b, plan), b.settings)
    assert "pair_crossed" not in t
