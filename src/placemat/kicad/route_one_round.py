#!/usr/bin/env python3
"""Runs KiCadRoutingTools' own command line with its final reconciliation
rounds switched off: the same copper, the same flags, ONE routing round.
The reconciliation rounds re-run the failing nets against the finished
board, cost most of a full run and rarely change the result, so the quick
route skips them. The router is executed from its own source with one
keyword added to its top-level call; nothing in the router checkout is
modified. Run by placemat's routing with `quick=True`, under the router's
own interpreter; $KRT_DIR is the checkout (default ~/work/KiCadRoutingTools).
"""
import os
import sys

router_dir = os.environ.get("KRT_DIR", os.path.expanduser("~/work/KiCadRoutingTools"))
py_router = os.path.join(router_dir, "py_router")
route_py = os.path.join(py_router, "route.py")
if not os.path.exists(route_py):
    sys.exit("route_one_round: no router at %s (set KRT_DIR)" % route_py)
sys.dont_write_bytecode = True   # no __pycache__ beside the sources
sys.path.insert(0, py_router)
src = open(route_py).read()
start = "_preview_out = batch_route(args.input_file,"
end = "collect_stats=args.stats)"
if src.count(start) != 1 or src.count(end) != 1 or src.index(end) < src.index(start):
    sys.exit("route_one_round: the router's top-level batch_route call is not where this wrapper expects it; "
             "the router changed - update the two anchors here")
src = src.replace(end, "collect_stats=args.stats, final_reconcile=False)")
sys.argv = [route_py] + sys.argv[1:]
g = {"__name__": "__main__", "__file__": route_py, "__builtins__": __builtins__}
exec(compile(src, route_py, "exec"), g)
