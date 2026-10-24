"""A routed run can leave a training record: the placed board as a raster and each net's route outcome
(kicad/training.py), written when route.training_record is set."""
from pathlib import Path

import pytest

from placemat.kicad.training import Raster, rudy
from tests.conftest import needs_kicad

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "fixtures/fairing/keep_out/modules/usb5v/generated/Usb5v/layout.kicad_pcb"


def test_a_segment_fills_the_cells_within_its_half_width():
    r = Raster(0, 0, 4, 1, 0.5)                      # 8 x 2 cells
    r.fill_segment("t", 0.25, 0.25, 3.75, 0.25, 0.2)
    ch = r.channel("t")
    assert list(ch[:8]) == [255] * 8 and list(ch[8:]) == [0] * 8


def test_rudy_puts_the_busiest_cell_at_255_and_a_lone_pad_adds_nothing():
    r = Raster(0, 0, 4, 4, 1.0)
    rudy(r, {"A": [(0.5, 0.5), (1.5, 1.5)], "B": [(0.5, 0.5), (3.5, 3.5)], "C": [(2.5, 0.5)]})
    ch = r.channel("rudy")
    assert ch[0] == 255                              # both nets' boxes cover the corner cell
    assert 0 < ch[3 * 4 + 3] < 255                   # only B's box
    assert ch[0 * 4 + 2] < ch[0] and ch[0 * 4 + 3] == ch[3 * 4 + 3]


@needs_kicad
def test_a_record_holds_the_boards_raster_and_each_nets_outcome(tmp_path):
    from placemat.kicad.training import read_raster, write_record
    path = write_record(BOARD, BOARD, tmp_path, {"GND": 2}, {"GND": 1}, {"closure": 0.5}, 0.25)
    record, channels = read_raster(path)
    assert record["closure"] == 0.5 and record["format"] == 1 and record["cell_mm"] == 0.25
    size = record["width"] * record["height"]
    assert set(channels) == set(record["channels"]) and all(len(v) == size for v in channels.values())
    assert {"board", "hole", "keepout", "rudy", "pad:F.Cu", "track:F.Cu"} <= set(channels)
    assert channels["board"].count(255) > size // 2
    assert channels["pad:F.Cu"].count(255) > 0 and max(channels["rudy"]) == 255
    gnd = record["nets"]["GND"]
    assert (gnd["open_before"], gnd["open_after"], gnd["track_mm"], gnd["vias"]) == (2, 1, 0.0, 0)
    assert len(gnd["pads"]) >= 2


@needs_kicad
@pytest.mark.parametrize("on", [True, False])
def test_a_route_writes_the_record_only_when_asked(rig, on):  # noqa: F811
    from placemat.settings import Settings, bind
    with bind(Settings(route_training_record=on)):
        report = rig.route()
    written = (Path(report.work) / "training.json").exists()
    assert written == on


@needs_kicad
def test_the_record_setting_does_not_change_which_phases_are_reused(rig):  # noqa: F811
    from placemat.settings import Settings, bind
    rig.route()
    with bind(Settings(route_training_record=True)):
        again = rig.route()
    assert again.resumed == ["pour", "signals"]


from tests.test_route_resume import rig  # noqa: E402,F401 - the fixture


def test_the_collector_copies_each_record_once(tmp_path):
    import importlib.util
    import json
    spec = importlib.util.spec_from_file_location("training_collect", ROOT / "tools/training_collect.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    run = tmp_path / "runs/abc/route"
    run.mkdir(parents=True)
    (run / "training.json").write_text(json.dumps({"raster": "training.raster", "closure": 0.9}))
    (run / "training.raster").write_bytes(b"x")
    (tmp_path / "runs/def/route").mkdir(parents=True)          # a route with no record
    first = mod.collect(tmp_path / "data", [tmp_path / "runs"])
    again = mod.collect(tmp_path / "data", [tmp_path / "runs"])
    assert [r["closure"] for r in first] == [0.9] and again == []
    assert len((tmp_path / "data/index.jsonl").read_text().splitlines()) == 1
    assert (tmp_path / "data" / first[0]["record"] / "training.raster").read_bytes() == b"x"
