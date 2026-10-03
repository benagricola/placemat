"""The small parts of phase 6: the builders' rule (no measurement, no searched suggestion), the settings, the channel's words for a
probe, apply's refusal of a suggestion with no value."""
import json

import pytest

from placemat import channel, probe, suggestions as sg
from placemat.findings import FindingCause as C
from placemat.settings import Settings, SettingsError, load

CORNER = {"key": "track A#1", "net": "A", "edge": "NE", "names": ["R1"], "near_mm": 0.1, "need_mm": 0.3, "chamfer_mm": 1.0}
MEETS = {"key": "track A#1", "net": "A", "word": "track", "layer": "F", "waypoints": 1, "chamfer_hit": True, "arc_hit": False,
         "chamfer_mm": 1.0, "radius_mm": None, "hit": {"code": "copper_near", "gap_mm": 0.05, "need_mm": 0.16}}


def picks(cause, facts):
    return sg.suggest(cause, facts)


def figure(cause, facts, name):
    return next(s.figure for s in picks(cause, facts) if s.how == "searched" and s.figure["name"] == name)


# ------------------------------------------------------------------ figures come from the finding's measurement
def test_the_corner_chamfer_is_searched_from_its_declared_size_down_by_twice_the_measured_shortfall():
    f = figure(C.COPPER_CORNER, CORNER, "chamfer")
    assert f["kind"] == "bisect" and f["declared"] == 1.0 and f["far"] == pytest.approx(0.6)
    assert (f["lo"], f["hi"], f["direction"], f["of"], f["times"]) == (0.6, 1.0, "lower clears", "need_mm - near_mm", 2)
    assert f["unit"] == "mm" and f["const"] == "A_CHAMFER_MM" and f["edit"] == 0


def test_the_corner_bend_is_a_set_and_brings_its_import_with_it():
    s = next(s for s in picks(C.COPPER_CORNER, CORNER) if s.figure["name"] == "bend")
    assert s.figure["values"] == ["START", "END", "BOTH"] and s.figure["enum"] == "Bend" and s.figure["edit"] == 1
    assert [e.op for e in s.edits] == ["ensure_import", "set_kwarg"] and s.edits[1].value is None


def test_the_meets_chamfer_and_arc_radius_are_searched_from_the_clearance_shortfall_at_the_cut():
    f = figure(C.COPPER_MEETS, MEETS, "chamfer")
    assert f["far"] == pytest.approx(0.78) and f["of"] == "need_mm - gap_mm"
    arc = dict(MEETS, chamfer_hit=False, arc_hit=True, radius_mm=2.0)
    assert figure(C.COPPER_MEETS, arc, "radius")["far"] == pytest.approx(1.78)


@pytest.mark.parametrize("cause, facts", [
    (C.COPPER_CORNER, {k: v for k, v in CORNER.items() if k != "near_mm"}),          # no shortfall measured
    (C.COPPER_CORNER, dict(CORNER, near_mm=0.4)),                                     # no shortfall
    (C.COPPER_MEETS, dict(MEETS, hit={"code": "copper_near"})),                       # the cut's gap was not recorded
    (C.COPPER_MEETS, dict(MEETS, chamfer_mm=None)),                                   # no declared value to reduce
    (C.COPPER_MEETS, dict(MEETS, chamfer_mm=0.0)),
    (C.COPPER_MEETS, dict(MEETS, chamfer_hit=False)),
])
def test_no_measurement_no_searched_chamfer(cause, facts):
    assert not [s for s in picks(cause, facts) if s.how == "searched" and s.figure["name"] == "chamfer"]


def test_without_a_shortfall_not_even_the_bend_is_offered():
    assert [s for s in picks(C.COPPER_CORNER, dict(CORNER, need_mm=0.1)) if s.how == "searched"] == []


def test_a_searched_suggestion_is_worded_as_a_question_never_a_fix():
    for s in picks(C.COPPER_CORNER, CORNER):
        assert s.how == "searched" and s.text.startswith("Changing ") and s.text.endswith("might fix this: search options?")


def test_a_searched_suggestion_round_trips_through_json_with_its_figure():
    s = picks(C.COPPER_CORNER, CORNER)[0]
    again = sg.Suggestion.from_json(json.loads(json.dumps(s.to_json())))
    assert again.how == "searched" and again.figure == s.figure and again.edits[0].value is None


def test_apply_refuses_a_searched_suggestion_and_says_how_to_get_a_value():
    s = sg.replace(picks(C.COPPER_CORNER, CORNER)[0], id="s2a")
    with pytest.raises(sg.EditRefused, match=r"placemat apply s2a --search"):
        sg.apply_suggestion([s], "s2a", dry_run=True)


# ------------------------------------------------------------------ settings
def test_the_probe_settings_default_and_come_from_a_placemat_toml(tmp_path):
    s = Settings()
    assert (s.studio_probe_budget_s, s.studio_probe_candidates) == (120, 12)
    (tmp_path / "placemat.toml").write_text("[studio]\nprobe_budget_s = 30\nprobe_candidates = 5\n")
    s = load(tmp_path)
    assert (s.studio_probe_budget_s, s.studio_probe_candidates) == (30, 5)


@pytest.mark.parametrize("line", ["probe_budget_s = 0", "probe_candidates = 0"])
def test_probe_settings_that_cannot_work_are_refused(tmp_path, line):
    (tmp_path / "placemat.toml").write_text("[studio]\n%s\n" % line)
    with pytest.raises(SettingsError):
        load(tmp_path)


# ------------------------------------------------------------------ the channel
def test_watch_words_a_probe_and_its_progress_file_keeps_it():
    start = {"ev": "probe", "id": "s3a", "figure": {"name": "chamfer", "what": "the chamfer of the A track", "kind": "bisect",
                                                    "lo": 0.6, "hi": 1.0}, "budget_s": 120, "candidates": 12}
    cand = {"ev": "candidate", "id": "s3a", "value": 0.6, "cleared": True, "gained": [], "score": 1.5, "seconds": 2.0, "n": 1, "of": 12}
    done = {"ev": "probe_done", "id": "s3a", "state": "found", "n": 3, "of": 12, "best": {"value": 0.8}, "candidates": [cand],
            "neighbour": {"value": 0.81, "cleared": False}, "monotone": True}
    assert channel.describe(start).startswith("probe s3a: the chamfer of the A track, 0.6 to 1")
    assert channel.describe(cand) == "  s3a = 0.6: cleared, score 1.50 (2.0 s)"
    assert channel.describe(done) == "found 0.8; 0.81 does not"
    assert channel.compact(start)["figure"]["name"] == "chamfer" and channel.compact(cand)["value"] == 0.6
    assert "candidates" not in channel.compact(done) and channel.compact(done)["state"] == "found"


def test_paused_keeps_a_resolve_off_the_channel_and_puts_it_back():
    class Beacon:
        sent = []

        def send(self, ev):
            self.sent.append(ev)
    held = channel._state.copy()
    try:
        channel._state.update(reporter=Beacon(), checked=True, off=False)
        with channel.paused():
            assert channel.current() is None and channel.reporter("x.py") is None
        assert isinstance(channel.current(), Beacon)
        channel.send({"ev": "probe"})
        assert Beacon.sent == [{"ev": "probe"}]
    finally:
        channel._state.clear()
        channel._state.update(held)


# ------------------------------------------------------------------ what it will cost
def test_the_estimate_is_data_and_says_where_each_candidate_resolves_the_whole_board(tmp_path):
    s = sg.Suggestion("x", (sg.Edit("set_kwarg", sg.Target("track", "k")),), how="searched", figure={"kind": "set"})
    est = probe.estimate(s, tmp_path, tmp_path / "layout.py", 12, 120)
    assert est == {"board_wide": True, "candidates": 12, "resolve_s": None, "budget_s": 120.0, "total_s": None}
    assert "no earlier resolve time" in probe.estimate_line(est)
    placed = sg.Suggestion("x", (sg.Edit("set_kwarg", sg.Target("place", "c1")),), how="searched", figure={"kind": "set"})
    assert probe.estimate(placed, tmp_path, tmp_path / "layout.py", 12, 120)["board_wide"] is False
    line = probe.estimate_line({"board_wide": True, "candidates": 12, "resolve_s": 8.0, "budget_s": 120.0, "total_s": 96.0})
    assert line == ("this probe resolves the whole board for each candidate, up to 12 candidates, about 8 s each "
                    "(the last resolve took 8 s): about 96 s in all")
    capped = {"board_wide": True, "candidates": 12, "resolve_s": 25.0, "budget_s": 120.0, "total_s": 120.0}
    assert "about 120 s in all" in probe.estimate_line(capped)
