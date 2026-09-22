"""A searched item's place in the queue is what it IS: how much board its
courtyard needs, and how many pins it has, both against the rest of this
board. No threshold, no share of the board area."""
from placemat.ranking import pin_count, rank_scores
from tests.fixtures import footprint, pad


def _score(items, area=0.7, pins=0.3):
    return rank_scores(items, area, pins)


def test_the_four_bands_come_out_in_order():
    """Large and many pins, then large and few, then small and many, then
    small and few. The band boundaries are nowhere in the code: the weights
    produce this ordering on their own."""
    s = _score({"large_many": (50.0, 56), "large_few": (50.0, 2),
                "small_many": (1.0, 56), "small_few": (1.0, 2)})
    assert s["large_many"] > s["large_few"] > s["small_many"] > s["small_few"]


def test_identical_items_tie_exactly():
    """The passive tail must tie so that link pull decides between them."""
    s = _score({"a": (0.5, 2), "b": (0.5, 2), "c": (0.5, 2)})
    assert s["a"] == s["b"] == s["c"]


def test_the_order_survives_a_change_of_units():
    """Standardising in log space makes the score scale-free: measuring the
    same board in um2 must not reorder it."""
    mm = _score({"a": (50.0, 56), "b": (8.0, 4), "c": (0.5, 2)})
    um = _score({"a": (50.0e6, 56), "b": (8.0e6, 4), "c": (0.5e6, 2)})
    assert sorted(mm, key=lambda k: -mm[k]) == sorted(um, key=lambda k: -um[k])


def test_one_huge_outlier_does_not_collapse_the_rest():
    """Dividing by the maximum compresses everything else toward zero and
    lets pins decide by accident. Standardising does not."""
    without = _score({"a": (8.0, 4), "b": (4.0, 4), "c": (0.5, 2)})
    with_outlier = _score({"huge": (5000.0, 8), "a": (8.0, 4), "b": (4.0, 4), "c": (0.5, 2)})
    assert without["a"] > without["b"] > without["c"]
    assert with_outlier["a"] > with_outlier["b"] > with_outlier["c"]
    assert with_outlier["huge"] > with_outlier["a"]


def test_a_single_item_scores_zero_rather_than_dividing_by_nothing():
    assert _score({"only": (12.0, 9)}) == {"only": 0.0}


def test_all_items_alike_score_zero_and_tie():
    assert _score({"a": (2.0, 2), "b": (2.0, 2)}) == {"a": 0.0, "b": 0.0}


def test_weighting_pins_at_nothing_ranks_by_area_alone():
    s = _score({"big_few": (50.0, 2), "small_many": (1.0, 56)}, area=1.0, pins=0.0)
    assert s["big_few"] > s["small_many"]


def _with_pads(ref, inst, pads):
    fp = footprint(ref, 0, 0, inst=inst)
    object.__setattr__(fp, "pads", tuple(pads))
    return fp


def test_pin_count_is_distinct_non_empty_pad_numbers():
    """The datasheet's pin count, not the pad count. The Keystone 1285 numbers
    BOTH of its legs 1, so it is one pin; the 1287 numbers them 1 and 2."""
    k1285 = _with_pads("J1", "j1", [pad("J1", "j1", 1, "VBIKE", -2.5, 0),
                                    pad("J1", "j1", 1, "VBIKE", 2.5, 0)])
    k1287 = _with_pads("J2", "j2", [pad("J2", "j2", 1, "VBIKE", -2.5, 0),
                                    pad("J2", "j2", 2, "VBIKE", 2.5, 0)])
    assert pin_count(k1285) == 1
    assert pin_count(k1287) == 2


def test_unnamed_netless_pads_are_not_pins():
    """The TPS16630's four unnamed through-hole pads were not thermal vias and
    are not pins either."""
    fp = _with_pads("U1", "u1", [pad("U1", "u1", 1, "VIN", -1, 0),
                                 pad("U1", "u1", 2, "VOUT", 1, 0),
                                 pad("U1", "u1", "", "", 0, 1),
                                 pad("U1", "u1", "", "", 0, 2)])
    assert pin_count(fp) == 2


def test_a_footprint_with_no_numbered_pads_still_counts_as_one():
    """log(0) is not a number; a pinless part is the least complex thing there
    is, not an error."""
    assert pin_count(_with_pads("MH1", "mh1", [])) == 1


def test_the_api_reference_documents_the_rank_and_required():
    from pathlib import Path
    doc = Path("skills/placemat/references/api.md").read_text()
    for phrase in ("required=", "rank", "Freedom"):
        assert phrase in doc, phrase
    assert "HIGH also needs a real share of the board" not in doc
    assert "`Priority.FIXED` copper is planned" not in doc
