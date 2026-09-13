---
name: placemat-design
description: Capture a circuit in Zener so its layout can be checked - the annotations, net classes and interfaces placemat's checks read (hot loops, switch nodes, sensitive nets, currents, dissipation, isolation). Use when writing or reviewing a .zen that will be laid out with placemat.
---

# placemat-design

A `.zen` is the schematic. Placemat lays it out and checks the layout
against what the capture says the circuit needs. Those needs are not in
the netlist unless the capture states them, so a capture written for
placemat carries them as annotations on parts, as net classes, and as
interfaces. Everything here lands on the board and is read back from it;
nothing is kept in a side file.

## Where a fact lives

| Fact | Where | How it reaches the board |
|---|---|---|
| A part's role, loop, dissipation, current, limits | `annotations={...}` on the part | forwarded into the footprint's fields (`Pm.*`) |
| A net's width, clearance, pair geometry | `NetClass(nets=[patterns])` in the board's `BoardConfig` | the project's net classes |
| A bus (SPI, CAN, a differential pair) | a stdlib `interface()` for the schematic, and a `NetClass` per bus for the board | the net class names the members |
| A net's voltage | `Net(voltage=)` | stays in Zener: checked at `pcb build`, not on the board |

Net-level facts with no class do not reach the board. State a current on the
parts that carry it (`Pm.I`) or give the net a class.

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
| `Pm.Sensitive` | `fb`, `sense`, `clk`, a name | keep-out, plane-split, crossing-under |
| `Pm.I` | amps at full load, e.g. `3A` | current path capacity, IR drop |
| `Pm.Pd` | watts at full load, worst case, from the datasheet | heat |
| `Pm.TjMax` | e.g. `125C` | heat |
| `Pm.Rth` | junction-to-board, e.g. `20K/W` | heat |
| `Pm.Creepage` | mm across a `barrier` part | isolation |

A value is a plain string with its unit. A placeholder is allowed while the
datasheet is pending, but say so in a comment beside it: a number with no
source is a defect at the completion gate.

Nets take their roles from the pins of annotated parts: the switch node is
the net on the switcher's `SW` pin and the inductor, the hot loop is the
copper between the parts marked `Pm.Loop: hot`, the feedback net is what the
`sense` resistors carry.

## Net classes and interfaces

- Every bus that must be laid out as one thing gets a `NetClass` whose
  `nets` patterns cover exactly its members: `NetClass(name = "SPI0", nets =
  ["spi0_*"])`. Placemat treats a class as a group: length spread, layer,
  corridor, crossings under.
- Use the stdlib interfaces (`Spi`, `Can`, `DiffPair`, `Usb2`, ...) for the
  schematic side; their child nets are named `<instance>_<field>`, which is
  what the class pattern matches.
- Differential pairs are `*_P`/`*_N` in a class with `diff_pair_width` and
  `diff_pair_gap`; placemat's pair primitive and the router read both.
- A high-current net has its own class with the width it needs; its
  clearance is the class's, and a clearance that must differ in one place
  (a fine-pitch pin on a wide-clearance net) is a rule the layout script
  declares, not a class.

## What placemat checks from these

Given the annotations and classes, a run reports, per check, a number and
a verdict; the layout script may set the limits it is judged against:

- hot loop area and longest leg, per declared loop
- switch node copper area and perimeter
- keep-out: sensitive-class copper within a radius of an aggressor
- parallel run length of an aggressor beside a sensitive net, same layer and adjacent layers
- plane continuity under a sensitive track; crossings under it by other nets
- current path capacity: the narrowest cross-section between declared pads on a current path and its IPC-2221 rise
- IR drop along a declared path against the rail's tolerance
- heat: copper area and vias at a dissipating part's pad and the estimated junction rise at a stated ambient
- isolation: no copper of a high-side net on the low side, nothing under a barrier part, creepage across it
- group checks per net class: length spread, same layer, same corridor

Which of these exist in the installed placemat is listed in the placemat
skill's `references/api.md` under Checks; a capture may carry facts for
checks not built yet.

## Writing the capture

1. Read the datasheet's layout section and write its rules into the header
   comment as numbered items, as the existing modules do.
2. Mark every part that appears in one of those rules: the switch, its
   input caps, the inductor, the output caps, the feedback divider.
3. Give every part that dissipates or carries the load current its numbers,
   with the datasheet section cited beside it.
4. Give every bus a class and every pair its `_P`/`_N` names.
5. `pcb build -D warnings` must pass. Then hand the capture to the layout,
   which reads the header, the annotations and the classes as its intent.
