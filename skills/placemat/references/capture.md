# Capture for placemat

What a capture carries so placemat can lay the board out and check it: the
`Pm.*` annotations on parts, how part wrappers forward them, how the checks
find their nets from them, what placemat reads from net classes, and what
`placemat check` reports.

## Annotations

`annotations` is a dict a part accepts and forwards into its footprint's
fields. The stdlib `Capacitor` and `Resistor` take it; a part wrapper
(`parts/<Part>.zen`) takes it when it declares
`annotations = config(dict, default = {}, optional = True)` and merges it into
its `Component(properties=...)`. KiCad writes a field name title-cased
(`Pm.TjMax` becomes `Pm.Tjmax`), and the checks read keys
case-insensitively; use these:

| key | values | read by |
|---|---|---|
| `Pm.Loop` | a loop's name: the parts that share one form one loop; `hot` by convention for the fast-current loop (input caps, the switch) | hot-loop |
| `Pm.Aggressor` | `true` | switch-node, keep-out |
| `Pm.Sensitive` | the net on the part's pads that must stay clear, by name: `VFB` | keep-out, crossings-under |
| `Pm.I` | amps at full load per net the part's pads carry: `vin:3A sw:3A`; a bare `3A` means every pad | current-path |
| `Pm.Pd` | watts at full load, worst case, from the datasheet | heat |
| `Pm.TjMax` | e.g. `125C` | heat |
| `Pm.ThetaJb` | junction-to-board, e.g. `15.5C/W`: what a board temperature wants | heat |
| `Pm.ThetaJa` | junction-to-ambient, the datasheet's JEDEC-board figure, used only without `Pm.ThetaJb` | heat |
| `Pm.Height` | the part's seated height in mm: `1.1mm` | the layout: a keepout's `max_height=`, `board.height_of()`, `placemat parts` |

`Pm.Height` is read under that exact name. It lets a layout script say the
room a case leaves over a region once, `board.keepout(shape, name,
excludes=(Forbid.PARTS,), max_height=4.0, why=...)`, rather than list the
short parts; a part with no `Pm.Height` counts as too tall there, and the
refusal names it.

Name the net `Pm.Sensitive` protects as the capture names it; a name no pad
of the part carries makes placemat take the part's least-connected net and
say so in the verdict. Give `Pm.I` per net: a bare current on a switcher
sizes its feedback pin for the load path. A controller that senses a load's
net (a current-sense pin, an ideal-diode controller's anode and cathode)
gives that net its own small current, or leaves it out: the check judges a
pair of carriers at the lesser of their currents, so its sense pin is judged
at what it draws, not at the load.

A value is a plain string with its unit, with its source in a comment
beside it (the datasheet section); a placeholder says so.

## How the checks find their nets

- A hot loop is the parts sharing one `Pm.Loop` name, and the nets two or
  more of them share.
- A switch node is a net on two or more parts whose every pad belongs to a
  `Pm.Aggressor` part: mark the switch and the inductor.
- A sensitive net is the net `Pm.Sensitive` names on its part: the feedback
  node on the feedback divider's resistors.
- A current path is a net some part gives a current in `Pm.I`.

A net-level fact with no part to carry it does not reach the board: state a
current on the parts that carry it (`Pm.I`).

## Net classes

placemat reads each net's class from the board's project: its track width is
a track's and a via tail's default width, its clearance is what placement
and copper keep from other nets, its via diameter and drill are what
`board.vias()` drills (a single `board.via()` takes the board's), and a
differential pair's `diff_pair_width` and `diff_pair_gap` are what
`board.pair()` and the router use. KiCad pairs nets by name (`_P`/`_N`,
`P`/`N`, `+`/`-`). A class whose clearance does not fit a part's pad pitch
is a setup finding on every run, naming the part.

## What placemat checks

`placemat check <board>` reports, per check, a number, the limit it is
judged against and a verdict; a check whose fact is missing says which
fact, and a check with no limit reports the number. Every `placemat run`
runs the same checks on the board it wrote.

- `hot-loop`: per `Pm.Loop` name, the area (mm2) of the hull of its parts'
  pads on the nets two or more of them share, and the longest pad-to-pad
  reach on one of those nets; `--limit hot-loop=<mm2>` judges it
- `switch-node`: each switch node's copper area (pads, tracks, pours) and
  extent; `--limit switch-node=<mm2>`
- `keep-out`: the nearest sensitive-net copper to each switch node,
  against `--keep-out` (default 2 mm), naming the two pieces of copper; a
  part's own pins are its package and are not judged
- `crossings-under`: other nets' copper on the other face under a
  sensitive net's tracks; zones and vias do not count, the limit is zero
- `current-path`: per net a `Pm.I` names, each two parts carrying on it
  judged at the lesser of their currents by the narrowest point of the
  widest route between them (tracks, vias, pours, and zone fills, each
  measured along the route at `check.zone_step`) against the IPC-2221
  width at `--rise` (default 10 C), on the copper weight the board's own
  stackup gives that layer (the IPC-2221 inner-layer constant on an inner
  layer, outer on F.Cu/B.Cu; a layer the stackup does not weigh falls back
  to 1 oz), with the neck's point and length; carriers no copper joins yet
  are reported, not judged, and so is a net only one part carries: give
  the part that takes the load (an input connector's load, a switch's
  inductor, a supply's output) its
  own `Pm.I` so the route between them is judged
- `heat`: the board temperature (`--ambient`, default 100 C) plus `Pm.Pd`
  times `Pm.ThetaJb` (or `Pm.ThetaJa` when that is all the part has, which
  is pessimistic), against `Pm.TjMax`

The defaults are settings (`[check]` in `placemat.toml`); `placemat
settings` prints them.

## Annotating a capture

1. Mark every part the datasheet's layout rules name: the switch and its
   input caps (`Pm.Loop`), the switch and the inductor (`Pm.Aggressor`),
   the feedback divider (`Pm.Sensitive`).
2. Give every part that dissipates or carries the load current its numbers
   (`Pm.I`, `Pm.Pd`, `Pm.TjMax`, `Pm.ThetaJb`), with the datasheet section
   cited beside each, and a part whose height matters its `Pm.Height`.
3. After `pcb build -D warnings` passes, `placemat check` on the generated
   board reads the annotations and the classes.

## Modules for placement

A cell is placed by placemat as one rigid piece: every member goes
together, wherever the cell's tightest job needs to sit. A cell that
holds two or more jobs joined only through board-level nets - a shared
bus, status lines, pull-ups, a plane - carries every other job's part to
wherever the tightest one goes.

`placemat run` reports this back as a `split` finding, naming the groups
it found among a cell's parts:

    m: its parts form 3 groups joined only by board-level nets: U3, C7,
    R2; U5, R4; Q2, R9 (and 4 parts no net inside the cell joins to the
    others: C1, C2, C3, R1; judge each by what places it: a bypass
    capacitor stays with the IC it serves, a sensing part at what it
    senses). Parts with no close placement
    requirement in common may be split into modules of their own.

A cell the search refuses to place at all is the other signal that its
module does not fit the board.

Fix a `split` finding, or a refused cell, in the capture: split the
module, or move a part into another one. A layout script cannot fix a
module the capture drew wrong; it only places what the capture gives it.

A part the finding does not group has no net inside the cell that joins
it to another member - whether it carries no local net at all, or a
local net of its own that nothing else in the cell shares. A bypass
capacitor is one: it always belongs in the module of the IC it
serves, and a bypass capacitor between a board-level supply and a plane
has no net inside its own cell, so the grouping shows it apart from that
IC - it is never a split candidate, whatever the grouping shows. A part
placed by what it senses or shields is the same: a thermistor sits at the
part whose temperature it measures, even though all its nets run
elsewhere. Neither is a split candidate; each is placed by that physical
need, not by a group. A part with no such need (a pull-up on a shared
bus, a status-line resistor) may belong with the rest of its job, in
another module.
