# tests/test_arrangement_units.py
"""Units: a module's items with options and its units combine in one product, in the order declared; exclusions leave combinations
out."""
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
    assert [k for k, _ in last.overrides] == ["c1", "r1", "c2", "r_far"]
    assert last.held == {"pair.upright", "caps.upright", "r_far.turned"}


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


def test_known_ids_follow_the_product():
    for ok in ("default", "pair.flat", "caps.upright+r_far.turned", "pair.upright+caps.upright+r_far.turned"):
        assert A.known_id(ok, *ARGS), ok
    for bad in ("pair", "pair.sideways", "caps.upright+pair.flat", "pair.flat+pair.upright", "c1.flat", ""):
        assert not A.known_id(bad, *ARGS), bad


def _released(tag: str):
    """arrangements.py as `tag` released it, loaded as a module of its own, or None where git or the tag is not to hand."""
    import importlib.util
    import pathlib
    import subprocess
    import sys
    root = pathlib.Path(__file__).resolve().parents[1]
    got = subprocess.run(["git", "show", "%s:src/placemat/arrangements.py" % tag], cwd=root, capture_output=True, text=True)
    if got.returncode != 0:
        return None
    spec = importlib.util.spec_from_loader("arrangements_" + tag.replace(".", "_"), loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                # dataclasses look their module up while the class is made
    try:
        exec(compile(got.stdout, "%s:arrangements.py" % tag, "exec"), mod.__dict__)
    finally:
        del sys.modules[spec.name]
    return mod


def test_a_module_of_items_alone_enumerates_exactly_as_0_99_15_did():
    """Ids, order, choices, overrides and the count of a module with items' options and no unit are those of the v0.99.15 tag,
    over every shape of up to four items of up to three options."""
    import itertools
    import pytest
    old = _released("v0.99.15")
    if old is None:
        pytest.skip("git or the v0.99.15 tag is not available")

    def shape(m, sizes):
        keys = ["i%d" % n for n in range(len(sizes))]
        return keys, {k: [m.Option(k, "o%d" % j, (("rotation", 90 * (j + 1)),)) for j in range(n)] for k, n in zip(keys, sizes)}

    def seen(e):
        return ([(s.id, s.pairs, tuple((k, o.item, o.name, o.keywords) for k, o in s.overrides)) for s in e.specs], e.declared,
                e.over and {k: v for k, v in e.over.items() if k != "excluded"})
    shapes = [sizes for n in range(1, 5) for sizes in itertools.product((0, 1, 2, 3), repeat=n)]
    for sizes in shapes:
        for limit in (8, 16, 64):
            then = seen(old.enumerate_specs(*shape(old, sizes), [], 4, limit))
            now = seen(A.enumerate_specs(*shape(A, sizes), [], 4, limit))
            assert now == then, (sizes, limit)
