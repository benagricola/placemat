"""Router flags as the router's argparse reads them (settings.resolve_flag): an exact flag, or the one flag a long
option abbreviates; the router's own flag list (krt_capabilities) where the router is known."""
import pytest

from placemat.kicad import net_clearance
from placemat.kicad.route import owned_args_refused, routing_clearance
from placemat.settings import resolve_flag, router_flag, router_owned

# a part of KRT route.py's own listing (krt_capabilities.py flags["route.py"])
KRT = ["--bus", "--bus-nets", "--clearance", "--clearance-ceiling", "--connections", "--grid-step", "--keep-away",
       "--keep-input-copper", "--layer-costs", "--layers", "--net-clearances", "--nets", "--no-power-tap-neckdown",
       "--output", "--overwrite", "--power-nets", "--power-nets-widths", "--smoothing", "--track-width"]


@pytest.mark.parametrize("arg, flag", [("--bus", "--bus"), ("--bus-n", "--bus-nets"), ("--clearance=0.2", "--clearance"),
                                       ("--clearance-c", "--clearance-ceiling"), ("--grid", "--grid-step"),
                                       ("--keep", None), ("--clear", None), ("--nope", None), ("-x", None)])
def test_a_flag_resolves_as_argparse_reads_a_long_option(arg, flag):
    assert resolve_flag(arg, KRT) == flag


@pytest.mark.parametrize("arg, owned", [("--keep-in", "--keep-input-copper"), ("--conn=f", "--connections"),
                                        ("--keep-a", None), ("--bus", None), ("--track", None),
                                        ("--power-net", "--power-nets"), ("-nVIN", "--nets")])
def test_with_the_routers_list_an_owned_flag_is_told_from_the_routers_others(arg, owned):
    assert router_owned(arg, KRT) == owned


def test_a_value_flag_is_read_by_its_abbreviation():
    assert router_flag(["--clearance-c", "0.3"], "--clearance-ceiling") == 0.3
    assert router_flag(["--grid-st=0.05"], "--grid-step", KRT) == 0.05
    assert router_flag(["--clearance-c", "0.3"], "--clearance", KRT) is None
    assert routing_clearance(0.2, ["--clearance=0.15"], {}, KRT) == 0.15
    assert net_clearance.ceiling(["--clearance-c", "0.25"], {}, KRT) == 0.25


def test_the_routers_list_decides_which_router_args_are_placemats_own():
    from tests.phase_helpers import phases
    caps = {"flags": {"route.py": KRT}}
    (phase,) = phases({"name": "x", "router_args": ["--track", "0.3"]})
    assert owned_args_refused(caps, ["--keep-in"], [phase]) == [
        {"phase": None, "flag": "--keep-in", "owned": "--keep-input-copper"}]
    assert owned_args_refused(caps, ["--keep-a", "1"], [phase]) == []
    assert owned_args_refused(None, ["--keep-in"], [phase]) == []


def test_an_owned_flag_the_routers_list_names_is_refused_in_words():
    from placemat.kicad.route import RouteRefused
    assert str(RouteRefused("router_owned", phase=None, flag="--keep-in", owned="--keep-input-copper")) == (
        "route: [route]: router_args --keep-in is the router's --keep-input-copper, which placemat sets itself")
