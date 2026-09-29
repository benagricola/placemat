# Capture for placemat

What a capture carries so placemat can lay the board out and check it: the
`Pm.*` annotations on parts, how part wrappers forward them, how nets take
their roles from them, how placemat reads net classes, and what `placemat
check` reports from all of it. General capture practice (where a fact
lives in Zener, net classes and interfaces, sourced numbers, design
records) is the circuit-capture skill's; this file is placemat's part of it.

## Annotations

`annotations` is a dict a part accepts and forwards into its footprint's
fields. The stdlib `Capacitor` and `Resistor` take it; a part wrapper
(`parts/<Part>.zen`) takes it when it declares
`annotations = config(dict, default = {}, optional = True)` and merges it into
its `Component(properties=...)`. KiCad writes a field name title-cased
(`Pm.TjMax` becomes `Pm.Tjmax`), so placemat reads keys case-insensitively;
use these:

| key | values | read by |
|---|---|---|
| `Pm.Role` | `switcher`, `inductor`, `output`, `bypass`, `sense`, `barrier`, `connector` | placement tactics, every check |
| `Pm.Loop` | `hot` (the fast-current loop: input caps, the switch), a name for any other loop | loop area |
| `Pm.Aggressor` | `true` | keep-out, parallel-run, crossing-under |
| `Pm.Sensitive` | the net on the part's pads that must stay clear, by name: `VFB` | keep-out, crossings-under |
| `Pm.I` | amps at full load per net the part's pads carry: `vin:3A sw:3A`; a bare `3A` means every pad | current path capacity |
| `Pm.Height` | the part's seated height in mm: `1.1mm` | a keepout's `max_height=` (the room a case leaves over a region) |
| `Pm.Pd` | watts at full load, worst case, from the datasheet | heat |
| `Pm.TjMax` | e.g. `125C` | heat |
| `Pm.ThetaJb` | junction-to-board, e.g. `15.5C/W`: what a board temperature wants | heat |
| `Pm.ThetaJa` | junction-to-ambient, the datasheet's JEDEC-board figure, used only without `Pm.ThetaJb` | heat |
| `Pm.Creepage` | mm across a `barrier` part | isolation (not built) |

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

Nets take their roles from the pins of annotated parts: the switch node is
the net on the switcher's `SW` pin and the inductor, the hot loop is the
copper between the parts marked `Pm.Loop: hot`, the feedback net is what the
`sense` resistors carry. A net-level fact with no class does not reach the
board: state a current on the parts that carry it (`Pm.I`) or give the net a
class.

## Net classes, as placemat reads them

Placemat treats a net class as a group: length spread, layer, corridor,
crossings under. A differential pair's class (`*_P`/`*_N`, with
`diff_pair_width` and `diff_pair_gap`) is what placemat's pair primitive and
the router read.

## What placemat checks from these

`placemat check <board>` reports, per check, a number, the limit it is
judged against and a verdict; a check whose fact is missing says which
fact, and a check with no limit reports the number. Built:

- `hot-loop`: per `Pm.Loop` name, the area (mm2) of the hull of its parts'
  pads on the nets two or more of them share, and the longest pad-to-pad
  reach on one of those nets; `--limit hot-loop=<mm2>` judges it
- `switch-node`: a net whose every pad belongs to an aggressor, its copper
  area (pads, tracks, pours) and extent; `--limit switch-node=<mm2>`
- `keep-out`: the nearest sensitive-net copper to each switch node,
  against `--keep-out` (default 2 mm), naming the two pieces of copper; a
  part's own pins are its package and are not judged
- `crossings-under`: other nets' copper on the other face under a
  sensitive net's tracks; zones do not count, the limit is zero
- `current-path`: per net a `Pm.I` names, each two parts carrying on it
  judged at the lesser of their currents by the narrowest point of the
  widest route between them (tracks, vias, pours; a zone fill joins but its
  own width is not measured) against the
  IPC-2221 outer-layer width at `--rise` (default 10 C) on `--copper-oz`
  (default 1 oz), with the neck's point and length; carriers no copper
  joins yet are reported, not judged
- `heat`: the board temperature (`--ambient`, default 100 C) plus `Pm.Pd`
  times `Pm.ThetaJb` (or `Pm.ThetaJa` when that is all the part has, which
  is pessimistic), against `Pm.TjMax`

Not built, and the capture may carry facts for them: parallel run length
beside an aggressor, plane continuity under a sensitive track, IR drop,
isolation and creepage across a `barrier` part, per-class group checks
(length spread, same layer, same corridor).

## Annotating a capture

1. Mark every part the datasheet's layout rules name: the switch, its input
   caps, the inductor, the output caps, the feedback divider (`Pm.Role`,
   `Pm.Loop`, `Pm.Aggressor`, `Pm.Sensitive`).
2. Give every part that dissipates or carries the load current its numbers
   (`Pm.I`, `Pm.Pd`, `Pm.TjMax`, `Pm.ThetaJb`), with the datasheet section
   cited beside each, and a part whose height matters its `Pm.Height`.
3. After `pcb build -D warnings` passes, the layout reads the header, the
   annotations and the classes as its intent.
