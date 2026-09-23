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


def test_a_run_id_is_a_short_hash_of_the_inputs():
    from placemat.report import run_id
    a = run_id(script_text="board.size(1, 1)\n", board_bytes=b"pcb", tool_version="0.2.0-dev")
    b = run_id(script_text="board.size(1, 1)\n", board_bytes=b"pcb", tool_version="0.2.0-dev")
    c = run_id(script_text="board.size(2, 1)\n", board_bytes=b"pcb", tool_version="0.2.0-dev")
    assert a == b and a != c
    assert len(a) == 8 and all(ch in "0123456789abcdef" for ch in a)


def test_impact_says_when_a_cutout_moved():
    """A hole is placed like an item and can move like one, so a change in
    where the board is milled belongs in the impact the same way a part's
    does. It is kept apart from the placements because it is not a part."""
    a = _rec(cutouts={"ffc": {"x": 10.0, "y": 20.0, "rotation": 0.0}})
    b = _rec(run_id="b", cutouts={"ffc": {"x": 10.0, "y": 24.0, "rotation": 90.0}})
    text = impact(a, b)
    assert "ffc" in text and "4.00 mm" in text and "rot 0 -> 90" in text


def test_impact_says_when_a_cutout_appeared_or_went():
    a = _rec(cutouts={"ffc": {"x": 10.0, "y": 20.0, "rotation": 0.0}})
    b = _rec(run_id="b", cutouts={"vent": {"x": 5.0, "y": 5.0, "rotation": 0.0}})
    text = impact(a, b)
    assert "vent: new" in text and "ffc: gone" in text


def test_impact_is_quiet_about_cutouts_when_there_are_none():
    assert "cutout" not in impact(_rec(), _rec(run_id="b"))


def test_the_settings_change_the_run_id():
    """A setting that changes the board must change the id: the runner
    rmtrees a run directory whose id matches, so a collision destroys the
    previous run's route/."""
    from placemat.report import run_id
    from placemat.settings import Settings
    same = dict(script_text="board.size(1, 1)\n", board_bytes=b"pcb", tool_version="0.2.0-dev")
    a = run_id(**same, settings_json=Settings().json())
    b = run_id(**same, settings_json=Settings().json())
    c = run_id(**same, settings_json=Settings(place_step=0.05).json())
    assert a == b and a != c


def test_run_id_without_settings_is_still_stable():
    from placemat.report import run_id
    same = dict(script_text="s", board_bytes=b"p", tool_version="v")
    assert run_id(**same) == run_id(**same)


def test_a_step_records_its_freedom_and_a_decided_placement_has_no_priority():
    from placemat.layout import Board
    from placemat.values import Location, Part
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("J1", 10, 10, inst="j1", nets=("A", "B")),
           footprint("R1", 30, 10, inst="r1", nets=("B", "C"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("j1"), at=Location(20, 20))
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.step("j1").freedom.value == "fixed"
    assert plan.step("j1").priority is None
    assert plan.step("r1").freedom.value == "searched"
    assert plan.step("r1").priority is not None and plan.step("r1").rank == 1


def test_the_step_header_names_the_place_column():
    from placemat.layout import STEP_HEADER
    assert "place" in STEP_HEADER and "priority" not in STEP_HEADER


def test_a_copper_step_says_which_batch_planned_it():
    from placemat.layout import Board
    from placemat.values import CopperLayer, Freedom, Location, Net, PadRef, Part
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("U1", 10, 10, inst="u1", nets=("A", "GND")),
           footprint("R1", 30, 10, inst="r1", nets=("GND", "C"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.size(width=60, height=60)
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"))
    b.track(Net("GND"), [Location(5, 40), Location(50, 40)], layer=CopperLayer.F)
    b.track(Net("C"), [PadRef(Part("r1"), "C"), Location(50, 50)], layer=CopperLayer.F)
    plan = b.resolve()
    by_item = {s.item: s for s in plan.steps if s.kind == "copper"}
    assert by_item["track GND"].freedom is Freedom.FIXED
    assert by_item["track C"].freedom is Freedom.SEARCHED


def test_the_fab_profile_changes_the_run_id(tmp_path):
    """A fab profile changes the body placemat derives for every part, so a
    changed one is a different run."""
    import json
    from placemat.project import fab_profile
    from placemat.report import run_id
    same = dict(script_text="board.size(1, 1)\n", board_bytes=b"pcb", tool_version="0.2.0-dev")
    (tmp_path / "fab-profile.json").write_text(json.dumps({"courtyard": {"excess_mm": 0.10}}))
    a = run_id(**same, fab_json=fab_profile(tmp_path).json())
    (tmp_path / "fab-profile.json").write_text(json.dumps({"courtyard": {"excess_mm": 0.25}}))
    b = run_id(**same, fab_json=fab_profile(tmp_path).json())
    (tmp_path / "fab-profile.json").write_text(json.dumps({"courtyard": {"excess_mm": 0.25}}, indent=4) + "\n")
    c = run_id(**same, fab_json=fab_profile(tmp_path).json())
    assert a != b and b == c                    # the values count, not how the file is written
