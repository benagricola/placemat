# Pin names for pads

Date: 2026-09-24
Status: design

A script linking a bypass capacitor to a supply pin names the pad by number,
read from an exported netlist, and an IC with several pads on one rail (a
strap pin beside a supply pin) cannot be told apart by net. Source:
fairing-instrument `electronics/PLACEMAT_GAPS.md`, "2026-09-22: which pad is
the supply pin", and "the power cells" item 4.

## Where the names are

Measured on the fairing core's generated board: no pad carries a pin
function (0 of 864), and the generator's netlist (`layout/default.net`)
gives each node a pad number and no name. The netlist does name each
component's symbol (`libsource part`), and the symbol libraries the board's
.zen files reference (`Symbol("...kicad_sym")`, already listed by
`generator_inputs`) give every pin's number and name.

So a pin name is found by: reference designator -> symbol name (the
netlist beside the generated board) -> the `.kicad_sym` among the board's
generator inputs that defines that symbol -> its pins, number -> name.

A symbol defined in more than one library with different pins is left
unnamed rather than guessed. A part whose symbol is not among the inputs (a
stdlib passive, `@stdlib/...`) has no names, which costs nothing: its pins
are 1 and 2.

## Behaviour

- `BoardGeometry.pin_names`: `{refdes: {pad number: pin name}}`, filled by
  the runner (and `preview`) from the board's source; empty for a bare
  `.kicad_pcb` with no source beside it.
- `PadRef(part, pin="VDD")`: the pad whose pin is named `VDD`. Several pads
  with the name (a symbol's repeated GND) is an error naming their numbers;
  an unknown name is an error listing the part's pin names. `PadRef(part,
  key)` is unchanged.
- `placemat measure <board> <part> --pads` prints the pin name beside each
  pad number when known; `--json` gives it as `pin`.

## Test plan

Pure: the `.kicad_sym` pin parser on a two-unit symbol with a repeated GND;
the netlist parser; `PadRef(pin=)` resolving, the repeated-name and unknown-
name errors. With a fixture project: the runner's geometry carries the names.
