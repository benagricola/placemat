# tests/test_arrangement_units.py
"""Units: a module's items with options and its units combine in one product, in the order declared; a 0.99.15 board.arrangement is a unit
with one option that keeps its id; units that move one part never combine; exclusions leave combinations out."""
import time

from placemat import arrangements as A


def opt(item, name, **kw):
    return A.Option(item, name, tuple(kw.items()))


def unit(name, members, *options):
    """A unit as board.unit declares it: `options` are (option name, [Option, ...]) pairs."""
    return A.Group(name, members=tuple(members),
                   alternatives=tuple(A.GroupOption(name, n, tuple(os)) for n, os in options))


PAIR = unit("pair", ["c1", "r1"], ("flat", [opt("c1", "flat", rotation=0), opt("r1", "flat", rotation=0)]),
             ("upright", [opt("c1", "upright", rotation=90), opt("r1", "upright", rotation=90)]))
CAPS = unit("caps", ["c2", "c3"], ("upright", [opt("c2", "upright", rotation=90)]))
R_FAR = {"r_far": [opt("r_far", "turned", rotation=90)]}
ARGS = (["pair", "caps", "r_far"], R_FAR, [PAIR, CAPS])


def ids(e):
    return [s.id for s in e.specs]


def test_two_units_and_an_item_combine_in_product_order_the_first_declared_changing_slowest():
    e = A.enumerate_specs(*ARGS, 4, 100)
    assert ids(e) == [
        "default", "r_far.turned", "caps.upright", "caps.upright+r_far.turned",
        "pair.flat", "pair.flat+r_far.turned", "pair.flat+caps.upright", "pair.flat+caps.upright+r_far.turned",
        "pair.upright", "pair.upright+r_far.turned", "pair.upright+caps.upright", "pair.upright+caps.upright+r_far.turned"]
    assert e.declared == 12 and e.over is None and e.excluded == ()
    last = e.specs[-1]
    assert last.choices == {"pair": "upright", "caps": "upright", "r_far": "turned"}
    assert [k for k, _ in last.overrides] == ["c1", "r1", "c2", "r_far"] and last.group == ""


def test_a_one_option_unit_keeps_its_0_99_15_id_and_combines_with_the_items():
    caps_upright = A.Group("caps_upright", (opt("c2", "caps_upright", rotation=90), opt("c3", "caps_upright", rotation=90)),
                           why="both capacitors stand")
    pull = {"r_pull": [opt("r_pull", "upright", rotation=90)]}
    e = A.enumerate_specs(["caps_upright", "r_pull"], pull, [caps_upright], 4, 100)
    assert ids(e) == ["default", "r_pull.upright", "caps_upright", "caps_upright+r_pull.upright"]
    alone = e.specs[2]
    assert alone.choices == {"caps_upright": "caps_upright"} and alone.group == "caps_upright" and alone.why == "both capacitors stand"
    assert [k for k, _ in alone.overrides] == ["c2", "c3"]
    assert e.specs[3].group == "" and e.specs[3].choices == {"caps_upright": "caps_upright", "r_pull": "upright"}


def test_units_that_move_one_part_never_combine():
    """Review focus 1: two 0.99.15 board.arrangements over one pair, and one over a part with an option of its own."""
    mirrored = A.Group("mirrored", (opt("q1", "mirrored", rotation=180), opt("q2", "mirrored", rotation=180)))
    rotated = A.Group("rotated", (opt("q1", "rotated", rotation=90),))
    q2 = {"q2": [opt("q2", "turned", rotation=90)]}
    args = (["q2", "mirrored", "rotated"], q2, [mirrored, rotated])
    e = A.enumerate_specs(*args, 4, 100)
    assert ids(e) == ["default", "rotated", "mirrored", "q2.turned", "q2.turned+rotated"]
    assert e.declared == 5
    assert A.known_id("q2.turned+rotated", *args)
    for bad in ("mirrored+rotated", "q2.turned+mirrored"):
        assert not A.known_id(bad, *args), bad


def test_an_exclusion_leaves_out_every_combination_holding_all_its_choices():
    rule = A.Exclusion(("pair.upright", "caps.upright"), "both stand in the one column")
    e = A.enumerate_specs(*ARGS, 4, 100, exclusions=(rule,))
    gone = ["pair.upright+caps.upright", "pair.upright+caps.upright+r_far.turned"]
    assert [s.id for s, _ in e.excluded] == gone and all(r is rule for _, r in e.excluded)
    assert not set(gone) & set(ids(e)) and e.declared == 10 and len(e.specs) == 10


def test_the_limit_counts_after_exclusions():
    rule = A.Exclusion(("pair.upright", "caps.upright"))
    assert A.enumerate_specs(*ARGS, 4, 10, exclusions=(rule,)).over is None
    over = A.enumerate_specs(*ARGS, 4, 9, exclusions=(rule,))
    assert ids(over) == ["default"] and over.excluded == ()
    assert over.over == {"variant": "arrangements", "arrangements": 10, "max_arrangements": 9,
                         "options": {"pair": 3, "caps": 2, "r_far": 2}, "max_options": 4, "excluded": 2}


def test_a_units_default_counts_as_one_of_its_options():
    wide = unit("wide", ["a"], *[(n, [opt("a", n, rotation=r)]) for n, r in (("w", 90), ("x", 180), ("y", 270), ("z", 45))])
    e = A.enumerate_specs(["wide"], {}, [wide], 4, 100)
    assert e.over["variant"] == "options" and e.over["options"] == {"wide": 5} and ids(e) == ["default"]


def test_counting_does_not_walk_the_whole_product():
    """Review focus 3: 14 items of 3 options each make 4^14 combinations; an exclusion over two of them is counted over those two."""
    items = {"p%02d" % n: [opt("p%02d" % n, o, rotation=r) for o, r in (("a", 90), ("b", 180), ("c", 270))] for n in range(14)}
    t0 = time.monotonic()
    kept, excluded = A.tally(A.units(sorted(items), items, []), (A.Exclusion(("p00.a", "p01.b")),))
    assert (kept, excluded) == (4 ** 14 - 4 ** 12, 4 ** 12)
    assert time.monotonic() - t0 < 1.0


def test_known_ids_and_all_ids_follow_the_product():
    assert A.all_ids(*ARGS) == ids(A.enumerate_specs(*ARGS, 4, 100))
    assert A.all_ids(*ARGS, cap=3) == ["default", "r_far.turned", "caps.upright"]
    for ok in ("default", "pair.flat", "caps.upright+r_far.turned", "pair.upright+caps.upright+r_far.turned"):
        assert A.known_id(ok, *ARGS), ok
    for bad in ("pair", "pair.sideways", "caps.upright+pair.flat", "pair.flat+pair.upright", "c1.flat", ""):
        assert not A.known_id(bad, *ARGS), bad
