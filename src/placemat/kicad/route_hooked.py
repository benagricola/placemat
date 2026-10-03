#!/usr/bin/env python3
"""Runs one of KiCadRoutingTools' own entry scripts (route.py, route_diff.py) with placemat's progress hooks in place: `route_hooked.py ENTRY
ARGS...`. The same copper and the same flags; the hooks (route_events.py) only watch. The router is executed from its own source and
nothing in its checkout is modified. Run by placemat's routing under the router's own interpreter; $KRT_DIR is the checkout (default
~/work/KRT-upstream). If the hooks' anchors are not where they expect, the router runs unhooked and `route_off` says why."""
import os
import sys

router_dir = os.environ.get("KRT_DIR", os.path.expanduser("~/work/KRT-upstream"))
py_router = os.path.join(router_dir, "py_router")
if len(sys.argv) < 2:
    sys.exit("route_hooked: give the router's entry script")
entry = sys.argv[1]
if not os.path.isabs(entry):
    entry = os.path.join(py_router, entry)
if not os.path.exists(entry):
    sys.exit("route_hooked: no router script at %s (set KRT_DIR)" % entry)
sys.dont_write_bytecode = True
sys.path.insert(0, py_router)
import importlib.util                                                # noqa: E402
_spec = importlib.util.spec_from_file_location("route_events", os.path.join(os.path.dirname(os.path.abspath(__file__)), "route_events.py"))
route_events = importlib.util.module_from_spec(_spec)               # beside this file: the progress hooks (loaded by path, no sys.path change)
_spec.loader.exec_module(route_events)

why = route_events.install()
if why:
    route_events.report_off(why)
src = open(entry).read()
sys.argv = [entry] + sys.argv[2:]
g = {"__name__": "__main__", "__file__": entry, "__builtins__": __builtins__}
exec(compile(src, entry, "exec"), g)
