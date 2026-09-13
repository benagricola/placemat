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


def test_a_quick_route_skips_the_smoothing_pass():
    """One round is a measurement: the octolinear smoothing the router runs
    after routing cannot change what closed, and on the Breakout it cost two
    of the run's two and a half minutes."""
    cmd = router_command("py", "route.py", "in.kicad_pcb", "out.kicad_pcb", set(), ["F.Cu"], "s.json", quick=True)
    assert "--no-smoothing" in cmd
    full = router_command("py", "route.py", "in.kicad_pcb", "out.kicad_pcb", set(), ["F.Cu"], "s.json", quick=False)
    assert "--no-smoothing" not in full
