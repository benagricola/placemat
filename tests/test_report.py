"""Run records and the impact between two of them, as an LLM reads them."""
from placemat.report import RunRecord, airwires_from_drc, impact


def _rec(**kw):
    base = dict(run_id="a", board="Widget", status="ok", placements={"r1": {"x": 1.0, "y": 2.0, "rotation": 0, "face": "front"}},
                metrics={"drc_real": {}, "unconnected": 3, "airwire_mm": 40.0, "crossings": 2,
                         "outstanding": {"track_dangling": 4}, "findings": 0, "board": [50.0, 40.0]},
                findings=[])
    base.update(kw)
    return RunRecord(**base)


def test_impact_reports_moves_and_metric_deltas_only():
    a = _rec()
    b = _rec(run_id="b", placements={"r1": {"x": 1.0, "y": 5.5, "rotation": 90, "face": "front"}},
             metrics={"drc_real": {"clearance": 1}, "unconnected": 1, "airwire_mm": 22.0, "crossings": 2,
                      "outstanding": {}, "findings": 0, "board": [50.0, 40.0]})
    text = impact(a, b)
    assert "r1" in text and "3.50 mm" in text and "rot 0 -> 90" in text
    assert "unconnected 3 -> 1" in text
    assert "airwire 40.0 -> 22.0" in text
    assert "clearance 0 -> 1" in text
    assert "crossings" not in text            # unchanged metrics stay out of the way
    assert "track_dangling 4 -> 0" in text


def test_impact_includes_the_other_drc_buckets():
    a = _rec(metrics={"drc_real": {}, "unconnected": 0, "airwire_mm": 0.0, "crossings": 0, "outstanding": {},
                      "other": {"tracks_crossing": 3}, "findings": 0, "board": [1, 1]})
    b = _rec(run_id="b", metrics={"drc_real": {}, "unconnected": 0, "airwire_mm": 0.0, "crossings": 0,
                                  "outstanding": {}, "other": {}, "findings": 0, "board": [1, 1]})
    assert "tracks_crossing 3 -> 0" in impact(a, b)


def test_impact_says_when_nothing_moved():
    a, b = _rec(), _rec(run_id="b")
    assert "nothing moved" in impact(a, b)


def test_airwires_are_read_off_the_drc_ratsnest():
    drc = {"unconnected_items": [
        {"items": [{"description": "Track [A] on F.Cu", "pos": {"x": 0, "y": 0}},
                   {"description": "Pad 1 [A] of R1", "pos": {"x": 3, "y": 4}}]},
        {"items": [{"description": "Pad 2 [B] of R2", "pos": {"x": 0, "y": 4}},
                   {"description": "Pad 1 [B] of R3", "pos": {"x": 3, "y": 0}}]},
    ]}
    aw = airwires_from_drc(drc)
    assert aw["count"] == 2 and aw["total_mm"] == 10.0 and aw["crossings"] == 1
    assert aw["per_net"] == {"A": 5.0, "B": 5.0}


def test_crossings_are_attributed_to_both_nets_of_each_pair():
    drc = {"unconnected_items": [
        {"items": [{"description": "Pad 1 [A] of R1", "pos": {"x": 0, "y": 0}}, {"description": "x", "pos": {"x": 10, "y": 10}}]},
        {"items": [{"description": "Pad 1 [B] of R2", "pos": {"x": 0, "y": 10}}, {"description": "x", "pos": {"x": 10, "y": 0}}]},
        {"items": [{"description": "Pad 1 [C] of R3", "pos": {"x": 5, "y": -5}}, {"description": "x", "pos": {"x": 5, "y": 15}}]},
    ]}
    aw = airwires_from_drc(drc)
    assert aw["crossings"] == 3                                  # A x B, A x C, B x C
    assert aw["crossings_per_net"] == {"A": 2, "B": 2, "C": 2}


def test_congestion_is_crossings_per_square_centimetre_of_free_board():
    from placemat.report import congestion
    assert congestion(crossings=12, free_area_mm2=600.0) == 2.0     # 12 crossings over 6 cm2
    assert congestion(crossings=0, free_area_mm2=600.0) == 0.0
    assert congestion(crossings=5, free_area_mm2=0.0) is None


def test_impact_shows_congestion_when_it_changes():
    a = _rec(metrics={"drc_real": {}, "unconnected": 0, "airwire_mm": 0.0, "crossings": 8, "congestion": 2.5,
                      "outstanding": {}, "findings": 0, "board": [1, 1]})
    b = _rec(run_id="b", metrics={"drc_real": {}, "unconnected": 0, "airwire_mm": 0.0, "crossings": 2, "congestion": 0.6,
                                  "outstanding": {}, "findings": 0, "board": [1, 1]})
    text = impact(a, b)
    assert "crossings 8 -> 2" in text and "congestion 2.50 -> 0.60" in text
