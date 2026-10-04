import pytest

from placemat import arrangements as A


def opt(item, name, **kw):
    return A.Option(item, name, tuple(kw.items()))


def test_a_name_is_lower_case_words_digits_and_underscores():
    A.check_name("option", "east_2")
    for bad in ("East", "a-b", "a.b", "a+b", "", "default"):
        with pytest.raises(ValueError):
            A.check_name("option", bad)


def test_an_option_takes_the_place_keywords_that_say_where_and_why():
    A.check_keywords("c_in", {"at": 1, "rotation": 90, "rotations": (0, 90), "face": 1, "radius": 2, "step": 0.1, "why": "w"})
    with pytest.raises(TypeError) as e:
        A.check_keywords("c_in", {"required": True})
    assert "required" in str(e.value) and "rotation" in str(e.value)


def test_the_arrangements_are_the_default_the_product_and_the_groups_in_declaration_order():
    options = {"c_in": [opt("c_in", "east")], "r_pull": [opt("r_pull", "turned"), opt("r_pull", "back")]}
    group = A.Group("mirrored", (opt("c_in", "mirrored"), opt("r_pull", "mirrored")))
    e = A.enumerate_specs(["c_in", "r_pull"], options, [group], 4, 20)
    assert [s.id for s in e.specs] == ["default", "r_pull.turned", "r_pull.back", "c_in.east", "c_in.east+r_pull.turned",
                                       "c_in.east+r_pull.back", "mirrored"]
    assert e.over is None and e.declared == 7
    both = e.specs[4]
    assert both.choices == {"c_in": "east", "r_pull": "turned"} and [k for k, _ in both.overrides] == ["c_in", "r_pull"]
    assert e.specs[-1].choices == {"group": "mirrored"} and e.specs[0].choices == {}


def test_exactly_the_limit_is_accepted_and_one_over_is_not():
    options = {"a": [opt("a", "x")], "b": [opt("b", "x")], "c": [opt("c", "x")]}      # 2 * 2 * 2 = 8
    assert A.enumerate_specs(["a", "b", "c"], options, [], 4, 8).over is None
    over = A.enumerate_specs(["a", "b", "c"], options, [A.Group("g", (opt("a", "g"),))], 4, 8)
    assert [s.id for s in over.specs] == ["default"]
    assert over.over == {"variant": "arrangements", "arrangements": 9, "max_arrangements": 8,
                         "options": {"a": 2, "b": 2, "c": 2}, "max_options": 4}


def test_an_item_over_the_option_limit_is_the_options_variant():
    options = {"a": [opt("a", n) for n in "wxyz"]}      # 5 with its place()
    e = A.enumerate_specs(["a"], options, [], 4, 100)
    assert e.over["variant"] == "options" and e.over["options"] == {"a": 5} and len(e.specs) == 1


def test_an_id_is_known_as_written():
    options = {"c_in": [opt("c_in", "east")], "r.pull": [opt("r.pull", "turned")]}
    group = A.Group("mirrored", ())
    args = (["c_in", "r.pull"], options, [group])
    for ok in ("default", "mirrored", "c_in.east", "r.pull.turned", "c_in.east+r.pull.turned"):
        assert A.known_id(ok, *args), ok
    for bad in ("east", "c_in.west", "r.pull.turned+c_in.east", "c_in.east+c_in.east", "nope"):
        assert not A.known_id(bad, *args), bad


def test_the_default_arrangement_has_no_overrides():
    assert A.DEFAULT_SPEC.id == "default" and A.DEFAULT_SPEC.choices == {} and A.DEFAULT_SPEC.overrides == ()


def test_all_ids_are_the_enumerated_ids_up_to_the_cap():
    options = {"c_in": [opt("c_in", "east")], "r_pull": [opt("r_pull", "turned"), opt("r_pull", "back")]}
    group = A.Group("mirrored", ())
    args = (["c_in", "r_pull"], options, [group])
    assert A.all_ids(*args) == [s.id for s in A.enumerate_specs(*args, 4, 20).specs]
    assert A.all_ids(*args, cap=3) == ["default", "r_pull.turned", "r_pull.back"]
