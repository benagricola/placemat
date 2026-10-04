import json

import pytest

from placemat import arrangement_note as N
from placemat.copper import Pour, Text, Track, Via, Zone
from placemat.layout import PlacedKeepout
from placemat.placement import Placement
from placemat.values import CopperLayer, Face, Location

F, B = CopperLayer.F, CopperLayer.B
OPS = [Track("VIN", F, 0.3, Location(1.0, 2.0), Location(3.5, 2.0)),
       Track("VIN", F, 0.3, Location(3.5, 2.0), Location(5.0, 4.0), mid=Location(4.5, 2.5)),
       Via("GND", Location(2.0, 3.0), 0.3, 0.6),
       Via("GND", Location(2.0, 5.0), 0.2, 0.45, layers=(F, CopperLayer.IN1)),
       Pour("SRC", F, ((0.0, 0.0), (4.0, 0.0), (4.0, 3.0)), 0.2, True),
       Zone("GND", CopperLayer.IN1, ((0.0, 0.0), (9.0, 0.0), (9.0, 9.0)), 0.2, 0.2, True, 0.25),
       Text("SW", Location(1.0, 1.0), Face.FRONT, 0.8, 0.15, 90.0, "left", "top", True, False, "", None, None)]


@pytest.mark.parametrize("op", OPS)
def test_an_op_round_trips_through_json(op):
    d = N.op_to_json(op)
    assert json.loads(json.dumps(d)) == d and N.op_from_json(d) == op


def test_a_keepout_round_trips_to_what_the_writer_needs():
    k = PlacedKeepout("ant", ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0)), Location(0, 0), 0.0, ("tracks", "vias"), (F,),
                      frozenset({"GND"}), frozenset({"U1"}), "an antenna", None, frozenset(), frozenset())
    back = N.keepout_from_json(json.loads(json.dumps(N.keepout_to_json(k))))
    assert (back.name, back.poly, back.excludes, back.layers, back.allow, back.why) == \
           (k.name, k.poly, k.excludes, k.layers, k.allow, k.why)


def test_the_base_digest_follows_the_default_places_and_nothing_else():
    a = [("c_in", Placement(Location(1, 2), 90.0, Face.FRONT)), ("u1", Placement(Location(5, 2), 0.0, Face.FRONT))]
    assert N.base_digest(a) == N.base_digest(list(reversed(a)))
    b = [(a[0][0], Placement(Location(1, 2.001), 90.0, Face.FRONT)), a[1]]
    assert N.base_digest(a) != N.base_digest(b)


def doc():
    return N.document("c_in.east", {"c_in": "east"},
                      [("c_in", Placement(Location(9.5, 3.0), 180.0, Face.FRONT), Placement(Location(2.5, 3.0), 0.0, Face.FRONT)),
                       ("u1", Placement(Location(6.0, 3.0), 0.0, Face.FRONT), Placement(Location(6.0, 3.0), 0.0, Face.FRONT))],
                      OPS, [])


def test_a_note_is_a_one_line_text_with_no_brace_dollar_quote_or_backslash_a_kicad_text_reads_as_markup():
    (text,) = N.encode(doc(), 100000)
    assert text.startswith(N.ARRANGEMENT_PREFIX) and "\n" not in text
    assert not any(c in text for c in '{}$"\\')
    docs, problems = N.read_notes([text])
    assert problems == [] and docs == [doc()]


def test_a_net_name_with_markup_characters_survives():
    d = N.document("x.y", {"x": "y"}, [], [Via("/VIN{a}$%", Location(1, 1), 0.3, 0.6)], [])
    docs, _ = N.read_notes(N.encode(d, 100000))
    assert docs[0]["ops"][0]["net"] == "/VIN{a}$%"


def test_a_long_note_splits_into_numbered_texts_and_joins_again():
    texts = N.encode(doc(), 120)
    assert len(texts) > 2 and all(len(t) <= 120 for t in texts)
    docs, problems = N.read_notes(list(reversed(texts)))            # the order KiCad lists a group's items in is not the order written
    assert problems == [] and docs == [doc()]


def test_two_arrangements_split_into_texts_that_are_told_apart():
    other = N.document("c_in.west", {"c_in": "west"}, [], [], [])
    docs, problems = N.read_notes(N.encode(doc(), 120) + N.encode(other, 120))
    assert problems == [] and sorted(d["id"] for d in docs) == ["c_in.east", "c_in.west"]


def test_a_truncated_or_newer_note_is_a_problem_not_a_crash():
    texts = N.encode(doc(), 120)
    docs, problems = N.read_notes(texts[:-1])
    assert docs == [] and problems and problems[0]["reason"] == "text"
    newer = dict(doc(), v=2)
    docs, problems = N.read_notes(N.encode(newer, 100000))
    assert docs == [] and problems == [{"reason": "version", "ids": ["c_in.east"]}]
    docs, problems = N.read_notes([N.ARRANGEMENT_PREFIX + "not%20json"])
    assert docs == [] and problems[0]["reason"] == "text"


def test_notes_of_a_cell_with_none_read_as_nothing():
    assert N.read_notes([]) == ([], [])


def test_the_order_a_module_run_laid_an_arrangement_in_survives_the_note():
    d = N.document("c_in.east", {"c_in": "east"}, [], [], [], order=3)
    assert d["order"] == 3 and N.document("c_in.east", {"c_in": "east"}, [], [], [])["order"] == 0
    docs, problems = N.read_notes(N.encode(d, 40))
    assert problems == [] and docs[0]["order"] == 3


@pytest.mark.parametrize("chars", [70, 120, 333])
def test_every_text_is_within_chars_header_included(chars):
    texts = N.encode(doc(), chars)
    assert all(len(t) <= chars for t in texts)
    assert N.read_notes(texts) == ([doc()], [])


@pytest.mark.parametrize("head", ["1/2/3 k x", "\u00b2/3 k x", "1/x k x", "1/2 k"])
def test_a_malformed_numbered_header_is_a_text_problem(head):
    docs, problems = N.read_notes([N.ARRANGEMENT_PREFIX + head])
    assert docs == [] and problems and problems[0]["reason"] == "text"


def test_a_zero_that_rounds_from_below_digests_as_zero():
    at = lambda x: [("a", Placement(Location(x, 0.0), 0.0, Face.FRONT))]
    assert N.base_digest(at(-0.0004)) == N.base_digest(at(0.0001))


def test_a_limit_with_no_room_for_a_chunk_is_an_error():
    with pytest.raises(N.NoteError):
        N.encode(doc(), 30)
