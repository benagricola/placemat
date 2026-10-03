"""The builder's facts batch with a real generation: `pcb layout` (the Zener tool, shipped with its stdlib) runs on a two-part board in a scratch
project, the facts are written to the .zen, fab-profile.json and placemat.toml, the board is regenerated and the facts read back from it, and
the script made from the outline resolves. Skipped where `pcb` is not installed."""
import shutil
import time

import pytest

from placemat.studio import Studio
from tests.test_studio_builder import Api
from tests.test_studio_builder import wait_phase as _wait

pytestmark = pytest.mark.skipif(shutil.which("pcb") is None, reason="the pcb tool is not installed")

ZEN = '''R = Module("@stdlib/generics/Resistor.zen")
C = Module("@stdlib/generics/Capacitor.zen")
a = Net("A")
g = Net("GND")
R(name = "r1", value = "10k", package = "0402", P1 = a, P2 = g)
C(name = "c1", value = "100nF", package = "0402", P1 = a, P2 = g)
Board(name = "Tiny", layout_path = "layout/Tiny", layers = 2)
'''
FACTS = {"stackup": {"copper_layers": 2, "rows": [{"kind": "copper", "role": "signal", "oz": 1}, {"kind": "dielectric", "thickness_mm": 1.5, "form": "core"},
                                                  {"kind": "copper", "role": "signal", "oz": 0.5}]},
         "via": {"micro": "no", "blind": "no", "buried": "no"}, "min": {"track_mm": 0.1}, "rise_c": 15}


def wait_phase(api, phase, seconds):
    return _wait(type("W", (), {"api": api}), phase, seconds)


def test_a_facts_batch_regenerates_the_board_and_reads_the_facts_back(tmp_path):
    (tmp_path / "pcb.toml").write_text('[workspace]\nname = "t"\npcb-version = "0.4"\n')
    (tmp_path / "placemat.toml").write_text("")
    board = tmp_path / "b"
    board.mkdir()
    (board / "Tiny.zen").write_text(ZEN)
    studio = Studio(None, root=tmp_path, port=0, open_browser=False)
    studio.start()
    try:
        api = Api(studio)
        assert api.post("/build/start", {"id": "b/Tiny.zen#Tiny"})[0] == 200
        wait_phase(api, "ready", 240)
        facts = api.get("/build/facts")[1]
        assert facts["zen"]["stackup"] == "none" and all(r["state"] == "undecided" for r in facts["model"]["rows"] if r["fact"] == "layer")
        st, out = api.post("/build/facts/apply", {"request": FACTS})
        assert st == 200, out
        assert out.get("readback") == [], (out.get("error"), out.get("tail"))              # the regenerated board carries what was asked
        zen = (board / "Tiny.zen").read_text()
        assert "CopperLayer(thickness = 0.035" in zen and "# 0.5 oz" in zen
        facts = api.get("/build/facts")[1]
        rows = {r["id"]: r for r in facts["model"]["rows"]}
        assert rows["layer:F.Cu"]["state"] == "decided" and rows["layer:B.Cu"]["value"]["copper_mm"] == pytest.approx(0.0175)
        assert rows["via:micro"]["state"] == "decided" and rows["min"]["state"] == "decided" and facts["rise"]["value"] == 15
        # the outline writes the script, which resolves on the regenerated board; the facts are then confirmed
        st, made = api.post("/build/outline/create", {"spec": {"shape": "rect", "width": 20.0, "height": 15.0}})
        assert st == 200, made
        wait_phase(api, "ready", 240)
        flags = {"no_pairs": True}
        flags.update({"plane:" + r["label"]: True for r in api.get("/build/facts")[1]["model"]["rows"] if r.get("flag")})
        st, conf = api.post("/build/facts/confirm", {"acks": flags})
        assert st == 200, conf
        end = time.monotonic() + 240
        while time.monotonic() < end and not studio.history:
            time.sleep(0.5)
        assert studio.history and studio._error is None
        parts = api.get("/build/parts")[1]
        assert parts["counts"]["unplaced"] == 2 and parts["outline"]["dims"] == {"width": 20.0, "height": 15.0}
    finally:
        studio.stop()
