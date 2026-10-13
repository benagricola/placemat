"""Names vulture reports that are used, each with the reason vulture cannot see it. A bare name here counts as a use."""
exc  # channel.py: `__exit__(self, *exc)`, the context-manager protocol passes these arguments
fullname  # context.py: `get_code(self, fullname)` and `get_source(self, fullname)` override importlib's loader API
on_setup  # kicad/route.py: `_route_board(on_setup=)`, the callers' hook for setup findings said before the first router call; none since the net halos gave way to routing phases
prune_above  # score_delta.Delta's caller-supplied bound is deliberately ignored until signed terms have proved lower bounds; parity tests exercise this API
