"""The skill check for arrangements: an agent given only the updated skill and a fixture module with no layout script lays it out; this
stages the module, prints the task, and checks what can be checked of the script it wrote. The rest (it ran the module, read the
arrangement report, and fixed or dropped an option the run found dead) is read from the transcript against the list in
docs/superpowers/skill-checks/arrangements.md."""
from __future__ import annotations

import ast
import json
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# module -> {"bypass": [...], "pullup": [...], "polarised": [...], "protruding": [...]}: part names, from `placemat parts`.
# usb5v: the two 100 nF input bypasses each stand beside the regulator; the two 100 uF reservoirs are polarised.
# usbtcpc: the 100 nF on VDD is a bypass beside the controller, INT_N's resistor is a pull-up, and the 1k on VCONN is the member
# that stands out past the rest (about 1.2 mm west of every other part) once the module is laid out.
ROLES: dict = {
    "usb5v": {"bypass": ["c_hf1", "c_hf2"], "pullup": [], "polarised": ["bulk_a", "bulk_b"], "protruding": []},
    "usbtcpc": {"bypass": ["c_vdd"], "pullup": ["r_irq"], "polarised": [], "protruding": ["r_vconn"]},
}
TASK = ("Lay out the module in {dir} with placemat. Use the placemat skill only. Run it, read the run's report, and finish when the "
        "module is correct.")


def _calls(text: str):
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            out.append(node)
    return out


def _part(call) -> str:
    a = call.args[0] if call.args else None
    return a.args[0].value if isinstance(a, ast.Call) and a.args and isinstance(a.args[0], ast.Constant) else ""


def _units(tree) -> dict:
    """variable -> unit name: each `v = board.unit("name", Part("..."), ...)` of the script."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            c = node.value
            if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "unit" and c.args
                    and isinstance(c.args[0], ast.Constant)):
                out[node.targets[0].id] = c.args[0].value
    return out


def check(script_text: str, roles: dict) -> list:
    from placemat.settings import Settings
    cap = Settings().place_arrangement_options_max
    unit_vars = _units(ast.parse(script_text))
    moved: dict = {}
    unit_options: dict = {}             # unit name -> its option names
    names = list(unit_vars.values())
    for c in _calls(script_text):
        if c.func.attr == "alternative" and len(c.args) >= 2 and isinstance(c.args[1], ast.Constant):
            names.append(c.args[1].value)
            unit = unit_vars.get(c.args[0].id) if isinstance(c.args[0], ast.Name) else None
            if unit is None:
                moved.setdefault(_part(c), []).append(c.args[1].value)
                continue
            unit_options.setdefault(unit, []).append(c.args[1].value)
            for a in c.args[2:]:            # a unit's option counts for each member it moves
                if isinstance(a, ast.Call) and getattr(a.func, "id", "") == "Alt":
                    moved.setdefault(_part(a), []).append(c.args[1].value)
    out = []
    for part in roles.get("bypass", ()):
        if part not in moved and not re.search(r"#\s*fixed:.*\b%s\b" % re.escape(part), script_text):
            out.append("%s (bypass) has no alternative: a bypass gets a turn at its pin, or a '# fixed:' line saying why "
                       "none fits" % part)
    for part in roles.get("pullup", ()):
        if part not in moved:
            out.append("%s (pullup) has no alternative: a pull-up whose side or turn is free gets one" % part)
    for part in roles.get("polarised", ()):
        if part in moved:
            out.append("%s is polarised: its place is a fact and it gets no alternative" % part)
    for part in roles.get("protruding", ()):
        if part not in moved and not re.search(r"#\s*extent:.*\b%s\b" % re.escape(part), script_text):
            out.append("%s sets the module's extent (protruding): it needs an alternative or a '# extent:' line saying why it has none" % part)
    for n in names:
        if re.fullmatch(r"alt\d*", n):
            out.append("%r names nothing: an option or a unit is named for what it does" % n)
    for part, opts in list(moved.items()) + list(unit_options.items()):
        if 1 + len(opts) > cap:
            out.append("%s has %d options, over the %d the caps allow" % (part, 1 + len(opts), cap))
    return out


def stage(module: str, target: pathlib.Path) -> str:
    sys.path.insert(0, str(ROOT))
    from tests import real_modules
    script = real_modules.stage(target, module)
    from placemat import runner
    src = runner.find_board(script)
    # the fixture holds the module's folder only, not the files its .zen loads, so `pcb layout` cannot run here: record the
    # cached generation as current, as the tests' runs restore it, so `placemat run` uses it
    runner._inputs_record(src).write_text(json.dumps(runner.generator_inputs(src), indent=1, sort_keys=True))
    script.unlink()                                     # the agent writes this one
    for other in script.parent.parent.iterdir():        # the fixture folder's other modules carry hand-written scripts to copy from
        if other.is_dir() and other != script.parent:
            shutil.rmtree(other)
    return TASK.format(dir=target / "board" / "modules" / module)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "stage":
        print(stage(sys.argv[2], pathlib.Path(sys.argv[3])))
    elif len(sys.argv) == 4 and sys.argv[1] == "check":
        problems = check(pathlib.Path(sys.argv[3]).read_text(), ROLES[sys.argv[2]])
        print("\n".join(problems) or "the script passes the machine-checkable criteria")
        sys.exit(1 if problems else 0)
    else:
        print("usage: skill_check.py stage MODULE DIR | check MODULE SCRIPT")
        sys.exit(2)
