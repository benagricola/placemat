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
    assert _after(cmd, "--heuristic-weight") == "1.2" and "--heuristic-weight" not in pairs    # pair_router_args


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


def test_the_pair_router_gets_its_own_args():
    """route_diff.py and route.py take different flags: router_args goes to
    route.py's passes, pair_router_args to the pair router's."""
    s = Settings(route_router_args=("--power-nets", "X"), route_pair_router_args=("--max-turn-angle", "90"))
    with bind(s):
        cmd = _cmd()
        pairs = pair_command("py", "route_diff.py", "in", "out", ["*"], ["F.Cu"])
    assert "--power-nets" not in pairs and _after(pairs, "--max-turn-angle") == "90"
    assert "--max-turn-angle" not in cmd


@pytest.mark.parametrize("value", ['["--via-cost", 50]', '["--turn-cost=5000"]', '["--max-iterations", "9"]',
                                   '["--power-nets", "X"]', '["--no-smoothing"]'])
def test_a_router_args_entry_that_cannot_work_is_refused_when_the_settings_load(tmp_path, value):
    (tmp_path / "placemat.toml").write_text('[route]\nrouter_args = %s\n' % value)
    with pytest.raises(SettingsError, match="router_args"):
        load(tmp_path)


def test_the_turn_cost_may_not_be_negative(tmp_path):
    (tmp_path / "placemat.toml").write_text('[route]\nturn_cost = -5\n')
    with pytest.raises(SettingsError, match="turn_cost"):
        load(tmp_path)


def test_release_all_with_nothing_kept_writes_nothing(tmp_path):
    from placemat import cli, routes
    script = tmp_path / "Board_layout.py"
    script.write_text("")
    assert cli.main(["routes", str(script), "--release-all"]) == 0
    assert not routes.path_for(script).exists()
