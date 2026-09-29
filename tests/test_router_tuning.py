"""The router's own tuning on every pass: a turn cost (20000 by default,
placemat's measured choice over the router's 1000: straighter routes, less
copper, no less closure), its smoothing as it defaults, and whatever else a
board asks for in [route] router_args."""
import pytest

from placemat.kicad.route import pair_command, router_command
from placemat.settings import Settings, SettingsError, bind, load


def _cmd(**kw):
    return router_command("py", "route.py", "in", "out", set(), ["F.Cu", "B.Cu"], "s.json", quick=True, **kw)


def _after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_every_pass_carries_the_turn_cost_and_smooths_by_default():
    with bind(Settings()):
        cmd = _cmd()
        pairs = pair_command("py", "route_diff.py", "in", "out", ["*"], ["F.Cu"])
    assert _after(cmd, "--turn-cost") == "20000" and "--no-smoothing" not in cmd
    assert _after(pairs, "--turn-cost") == "20000"


def test_the_settings_reach_the_command_line():
    s = Settings(route_turn_cost=1000, route_smoothing=False, route_router_args=("--heuristic-weight", "1.2"))
    with bind(s):
        cmd = _cmd()
        pairs = pair_command("py", "route_diff.py", "in", "out", ["*"], ["F.Cu"])
    assert _after(cmd, "--turn-cost") == "1000" and "--no-smoothing" in cmd
    assert _after(cmd, "--heuristic-weight") == "1.2" and _after(pairs, "--heuristic-weight") == "1.2"


@pytest.mark.parametrize("flag", ["--nets", "--layers", "--escalation", "--keep-input-copper", "--turn-cost"])
def test_a_flag_placemat_sets_itself_is_refused_in_router_args(tmp_path, flag):
    (tmp_path / "placemat.toml").write_text('[route]\nrouter_args = ["%s", "1"]\n' % flag)
    with pytest.raises(SettingsError, match="router_args"):
        load(tmp_path)


def test_release_all_drops_every_kept_route(tmp_path):
    from placemat import cli, routes
    script = tmp_path / "Board_layout.py"
    script.write_text("")
    routes.write(routes.path_for(script), [routes.RouteEntry("A", (), ()), routes.RouteEntry("B", (), ())])
    assert cli.main(["routes", str(script), "--release-all"]) == 0
    assert routes.read(routes.path_for(script)) == []
