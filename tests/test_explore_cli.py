"""--explore on preview and run, --accept, and placemat lock: the command
line round the search, on a fixture module."""
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("pcbnew")        # the fixture module is read with KiCad

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _module(tmp_path, searched=False):
    """The UsbC fixture module with its generation cached; `searched` leaves
    two of its passives to the search (their at= dropped), so there is
    something to explore."""
    mod = tmp_path / "UsbC"
    shutil.copytree(ROOT / "fixtures/mnb/modules/UsbC", mod)
    shutil.copytree(mod / "layout", mod / ".placemat/generated/UsbC")
    script = mod / "UsbC_layout.py"
    if searched:
        t = script.read_text()
        t = t.replace("board.place(R_CC2, at=Pin(CC2, X(ESD, -(esd_claim.width + r_claim.width) / 2), Y(E4)), "
                      "rotation=upright(R_CC2, CC2),", "board.place(R_CC2,")
        t = t.replace("board.place(C_VBUS, at=Pin(VBUS, X(R_CC1), Y(E1)), rotation=upright(C_VBUS, VBUS),",
                      "board.place(C_VBUS,")
        script.write_text(t)
    return mod, script


def _cli(*args):
    done = subprocess.run([sys.executable, "-m", "placemat", *map(str, args)], capture_output=True, text=True,
                          timeout=900)
    return done.returncode, done.stdout + done.stderr


def test_explore_reports_and_writes_nothing_without_accept(tmp_path):
    mod, script = _module(tmp_path, searched=True)
    rc, out = _cli("preview", script, "--svg", "--explore", "3", "--jobs", "2")
    assert rc == 0, out
    assert "explore" in out and "variants in" in out
    assert not (mod / "UsbC_layout.lock.json").exists()


def test_accepting_writes_the_lock_and_the_next_preview_holds_it(tmp_path):
    mod, script = _module(tmp_path, searched=True)
    rc, out = _cli("preview", script, "--svg", "--explore", "8", "--jobs", "2", "--accept")
    assert rc == 0, out
    lock = mod / "UsbC_layout.lock.json"
    assert "accepted: written to the lock" in out, out
    assert lock.exists() and json.loads(lock.read_text())["entries"]
    rc, out = _cli("preview", script, "--svg")
    assert rc == 0 and "held by lock" in out, out


def test_lock_release_all_empties_the_lock(tmp_path):
    mod, script = _module(tmp_path)
    lock = mod / "UsbC_layout.lock.json"
    lock.write_text(json.dumps({"format": 1, "entries": [
        {"key": "x", "anchor": None, "anchor_face": None, "offset": [1.0, 2.0], "rotation": 0.0,
         "face": "front", "declaration": "0", "turn": 0, "release": ""}]}))
    rc, out = _cli("lock", script, "--release-all")
    assert rc == 0 and "released 1" in out, out
    assert json.loads(lock.read_text())["entries"] == []


def test_a_module_with_nothing_searched_says_there_is_nothing_to_explore(tmp_path):
    mod, script = _module(tmp_path)
    rc, out = _cli("preview", script, "--svg", "--explore", "3")
    assert rc == 0 and "nothing to explore" in out, out


def test_focus_flags_need_explore(tmp_path):
    mod, script = _module(tmp_path)
    rc, out = _cli("preview", script, "--svg", "--accept")
    assert rc != 0 and "go with --explore" in out


def test_an_unknown_focus_is_a_clean_error(tmp_path):
    mod, script = _module(tmp_path, searched=True)
    rc, out = _cli("preview", script, "--svg", "--explore", "3", "--focus", "nope")
    assert rc != 0 and "nothing searched is called 'nope'" in out and "Traceback" not in out, out
