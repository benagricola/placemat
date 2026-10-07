"""Names vulture reports that are used, each with the reason vulture cannot see it. A bare name here counts as a use."""
exc  # channel.py: `__exit__(self, *exc)`, the context-manager protocol passes these arguments
fullname  # context.py: `get_code(self, fullname)` and `get_source(self, fullname)` override importlib's loader API
