"""The router's search budget is the router's own default unless the caller
sets one: placemat used to cap every search at 2000 iterations, a hundredth
of the router's default, and on a 230 mm board a net that had to detour
around routed copper died in the cap while it routed alone in 60000."""
from placemat.kicad.route import router_command


def test_no_iteration_flags_unless_asked():
    cmd = router_command("py", "route.py", "in.kicad_pcb", "out.kicad_pcb", set(), ["F.Cu"], "s.json")
    assert "--max-iterations" not in cmd and "--max-probe-iterations" not in cmd
    assert cmd[:4] == ["py", "route.py", "in.kicad_pcb", "out.kicad_pcb"]


def test_an_iteration_cap_is_passed_through():
    cmd = router_command("py", "route.py", "in.kicad_pcb", "out.kicad_pcb", {"GND"}, ["F.Cu"], "s.json", iterations=200)
    assert cmd[cmd.index("--max-iterations") + 1] == "200"
    assert "!GND" in cmd
