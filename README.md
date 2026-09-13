# placemat

Lay out a KiCad board from a Python script, and see what each change did.

A script imports `board`, measures the generated board, declares where
things go and which copper joins them, and `placemat run` does the rest:
generate the board with the `pcb` toolchain, resolve the declarations in
priority order against an offline occupancy model, write through pcbnew,
run DRC, render, and record the run with an impact summary against the
previous one.

```sh
uv venv --python "$(which python3)" --system-site-packages   # pcbnew comes with KiCad, not PyPI
uv sync --extra dev
uv run placemat run boards/x/X_layout.py --label first
uv run pytest
```

The skill in `skills/placemat` is how an agent works with it; the script
surface is in `skills/placemat/references/api.md`. `PLAN.md` is the plan
this tree was built to.
