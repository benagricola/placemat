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


def test_a_quick_route_smooths_as_the_router_does():
    """The router's smoothing now costs a quick route about an eighth of its
    time (the Breakout, 2026-09-29: 42 s against 37 s), not most of it, so a
    quick route runs it; [route] smoothing = false skips it
    (tests/test_router_tuning.py)."""
    cmd = router_command("py", "route.py", "in.kicad_pcb", "out.kicad_pcb", set(), ["F.Cu"], "s.json", quick=True)
    assert "--no-smoothing" not in cmd


def test_the_router_keeps_the_scripts_own_copper():
    """Declared copper is the script's intent: the router's cleanup passes
    (dead-end sweep, orphan islands, prunes) may not remove it."""
    from placemat.kicad.route import pair_command, router_command
    single = router_command("py", "route.py", "in.kicad_pcb", "out.kicad_pcb", set(), ["F.Cu", "B.Cu"], "s.json")
    pairs = pair_command("py", "route_diff.py", "in.kicad_pcb", "out.kicad_pcb", ["USB_D*"], ["F.Cu", "B.Cu"])
    assert "--keep-input-copper" in single and "--keep-input-copper" in pairs
