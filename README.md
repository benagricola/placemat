# placemat

Lay out a KiCad board by writing a Python script that describes the
constraints, and let the library work out the positions.

You say a connector is on the north edge, that this cell's output feeds that
one, that a regulator's capacitors serve its pins. placemat searches for
positions that satisfy that, checks the result against real DRC, and tells you
what it could not satisfy. Re-run it after a schematic change and you get a
board again, not a merge conflict.

It comes with a skill, so an agent can drive it. Most people start there.

## What you get

- A layout script you can read and re-run, instead of a `.kicad_pcb` whose
  history is a binary blob.
- Placement from constraints: a cell goes where the things it connects to are,
  or in the best free space that fits its actual shape.
- Gates that fail loudly: real `kicad-cli` DRC, courtyard and clearance checks,
  copper-neck audits, and a router run purely as a measurement of routability.
- Reusable cells. A module is laid out and routed once, then stamped onto every
  board that uses it.

## Requirements

KiCad 9 or 10 installed, with its Python module (`pcbnew`) available to your
system Python. placemat runs inside that interpreter, because `pcbnew` is not
on PyPI and cannot be pip-installed.

## Install the skill

The skill teaches an agent the craft - placement and copper tactics, the
process, the verification gates - and it ships alongside the code it describes.

```sh
claude plugin marketplace add benagricola/placemat
claude plugin install placemat@placemat
```

Then, in the project you want to lay out:

```sh
uv venv --python "$(which python3)" --system-site-packages
uv add git+https://github.com/benagricola/placemat
uv run placemat init
```

`init` checks that `pcbnew` imports, writes a fab profile you should edit, and
creates the directories a project needs. Now ask for a board:

> lay out the power board in boards/power.zen - the barrel jack is on the
> north edge and the regulator sits near it

The agent writes the layout script, runs passes, reads the gates, and shows you
renders. You review those and say what is wrong.

## Use it directly

```sh
uv run placemat new-board Power          # a layout script to fill in
uv run placemat round boards/power.zen --label pass1
uv run placemat --help                   # the individual gates
```

A layout script looks like this:

```python
from placemat import stage, context

layout, board = context()   # layout is the artwork; board is the board

BOARD_W, BOARD_H = 50.0, 50.0        # source: the enclosure
PLANE_NETS = {"GND", "3V3"}          # on a plane, so never routed

@stage("frame")
def _frame():
    board.outline_chamfered(2.0)

@stage("anchors")
def _anchors():
    board.place("j_power", 10.0, 0.0)   # a fact: the enclosure fixes this
    board.edge_align("j_power", "N")

@stage("cells")
def _cells():
    board.settle_all([dict(inst="buck"), dict(inst="mcu")])   # no coordinates
```

The stages run in a fixed order - frame, anchors, cells, loose parts, copper,
drops, repair, silk, report - because each reads what the one before it left.
You fill in bodies; the library decides when they run and in which order the
parts inside them are placed.

`placemat round` generates the board, runs your script, and puts the result
through the gates in one command, recording the numbers so the next pass can be
compared against this one.

## Where placemat looks

By default a board is a top-level directory holding a `.zen` that declares
`Board(...)`, and a cell is a directory under `modules/` holding `<Name>.zen`.
A project laid out differently says so in its `pcb.toml`:

```toml
[placemat]
boards = ["pcbs/*"]                 # globs, relative to the project root
cells  = ["lib/*", "pcbs/*/local"]
parts  = ["footprints/*"]
```

Each glob matches the THINGS, not the folder holding them - `"footprints/*"`,
not `"footprints"` - and placemat says so if a setting matches nothing. The
globs say where to look; the file inside says what a thing is, so a directory
of shared code never becomes a board by accident. `placemat status` prints the
search paths when they are not the defaults.

## Status

Early. The API still moves. It lays out real four-layer boards today, and the
tests run against real KiCad geometry rather than mocks.
