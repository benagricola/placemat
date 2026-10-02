"""Runs a real module of fixtures/fairing/keep_out end to end, as `placemat run`
does: the cached generation put in the layout folder (the generator, `pcb
layout`, is not run), the module's own layout script, the written board, and
kicad-cli's DRC on it. The module's nets and part annotations come from the
fixture's `default.net`; `keep_out=` replaces the part's `Pm.KeepOut` there,
to run a module under the other wording of its annotation."""
import json
import re
import shutil
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fairing" / "keep_out"
MODULES = {"usb5v": "Usb5v", "logicsupply": "LogicSupply", "usbconverter": "UsbConverter"}
# a module of another fixture folder: (folder, generated name)
OTHER = {"usbtcpc": (FIXTURES.parent / "via_clearance", "UsbTcpc"), "mcu": (FIXTURES.parent / "mcu_fan", "Mcu")}

# The annotation each module's capture carries now (only the switch nodes in `away=`) ...
SWITCH_ONLY = {
    "usb5v": "1.28mm pads=FB_5V away=SW_5V; datasheet fig. 12-2: SW copper leaves the package beside FB at its own pad gap (1.28 mm)",
    "logicsupply": "1.22mm pads=FB_3V3 away=SW_3V3; datasheet fig. 12-2: SW copper leaves the package beside FB at its own pad gap (1.22 mm)",
    "usbconverter": "1.26mm pads=COMP_BB away=SW1,SW2; datasheet fig. 10-1: SW copper leaves the package beside COMP at its own pad gap (1.26 mm)",
}
# ... and what the fixture's generated netlist carries (the boot nets named too).
WITH_BOOT = None


def stage(tmp_path: Path, module: str, keep_out: str | None = None) -> Path:
    """A copy of the fixture under `tmp_path` laid out as a board folder, with the module's cached generation
    in `.placemat/generated`; returns the layout script's path."""
    folder, name = OTHER[module] if module in OTHER else (FIXTURES, MODULES[module])
    root = tmp_path / "board"
    shutil.copytree(folder, root, ignore=shutil.ignore_patterns("generated"))
    cache = root / "modules" / module / ".placemat" / "generated"
    cache.mkdir(parents=True)
    shutil.copytree(folder / "modules" / module / "generated" / name, cache / name)
    if keep_out is not None:
        for fname, pattern in (("default.net", r'(\(property \(name "Pm\.KeepOut"\) \(value ")[^"]*("\)\))'),
                               ("layout.kicad_pcb", r'(\(property "Pm\.Keepout" ")[^"]*(")')):
            path = cache / name / fname
            text, n = re.subn(pattern, lambda m: m.group(1) + keep_out + m.group(2), path.read_text())
            assert n == 1, "%s carries one Pm.KeepOut" % fname
            path.write_text(text)
    return root / "modules" / module / (name + "_layout.py")


def run(tmp_path: Path, module: str, keep_out: str | None = None, overrides: dict | None = None, keep_going: bool = False):
    """The module's layout run (no renders), as `(RunResult, DRC report as a dict, the written board's path)`."""
    from placemat import runner
    script = stage(tmp_path, module, keep_out)
    src = runner.find_board(script)

    def restore(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
        shutil.rmtree(src.layout_dir, ignore_errors=True)
        shutil.copytree(runner.cached_generation(src), src.layout_dir)
        return False
    was = runner.generate
    runner.generate = restore
    try:
        result = runner.run(script, render=False, quiet=True, reuse=False, overrides=overrides or {}, keep_going=keep_going)
    finally:
        runner.generate = was
        from placemat import console
        console.configure(quiet=False)          # a run sets it for the process; the tests that read the console's output need it off
    drc = json.loads((result.run_dir / "drc.json").read_text()) if (result.run_dir / "drc.json").exists() else {}
    return result, drc, src.pcb


def violations(drc: dict, *kinds) -> list:
    """The DRC report's violations of these kinds (all of them when none are named), as `type: description`."""
    out = []
    for section in ("violations", "unconnected_items"):
        for v in drc.get(section, []):
            if not kinds or v.get("type") in kinds:
                out.append("%s: %s" % (v.get("type"), v.get("description")))
    return out
