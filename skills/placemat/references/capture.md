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
| `Pm.KeepOut` | a datasheet keep-out distance for the part's pins, cited: `0.7mm pads=FB,COMP away=SW,BOOT; datasheet rev B, section 10.2, layout example` | keep-out, the layout (a clearance) |
| `Pm.I` | amps at full load per net the part's pads carry: `vin:3A sw:3A`; a bare `3A` means every pad | current-path |
| `Pm.Pd` | watts at full load, worst case, from the datasheet | heat |
| `Pm.TjMax` | e.g. `125C` | heat |
| `Pm.ThetaJb` | junction-to-board, e.g. `15.5C/W`: what a board temperature wants | heat |
| `Pm.ThetaJa` | junction-to-ambient, the datasheet's JEDEC-board figure, used only without `Pm.ThetaJb` | heat |
| `Pm.Height` | the part's seated height in mm: `1.1mm` | the layout: a keepout's `max_height=`, `board.height_of()`, `placemat parts` |
| `Pm.Emits` | on a source: `<kind>:<value><unit>@<r>mm^<falloff>`, several joined by spaces: `magnetic:3.2mT@13.5mm^3 heat:15C@5mm^1` | the layout (a push), exposure |
| `Pm.EmitsAt` | on a source: `x,y` in mm in the footprint's own frame, or `pad:<number>`; default the footprint's origin | the layout, exposure |
| `Pm.Limit` | on a sensitive part: `<kind>:<value><unit>`, several joined by spaces: `magnetic:0.5mT heat:5C` | the layout (a push), exposure |
| `Pm.SensesAt` | on a sensitive part: `pad:<number>`; default the body centre | the layout, exposure |

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

### Keep-out distance on a part

`Pm.KeepOut` is a datasheet fact about a part: its feedback or compensation
pin may stand only so near its switch node, and the datasheet's own reference
layout says how near. It lives on the part, so it holds in every board that
uses the part and in every module that is stamped into a parent; do not
write it as `board.accept("keep-out", ...)` in each layout script, which is
for one verdict a layout cannot do better on.

```
Pm.KeepOut: <distance>mm [pads=<net>[,<net>...]] [away=<net>[,<net>...]]; <citation>
```

- The distance is in mm (`0.7mm` or `0.7`), above zero. It may be below or
  above `check.keep_out_mm`.
- `pads=` names the nets of this part's pads that keep the distance (the
  sensitive pins: feedback, compensation). Without it, the part's
  `Pm.Sensitive` net.
- `away=` names the nets of this part's pads whose copper the pads keep away
  from (the switch and boot pins). Without it, the switch nodes the part is
  on.
- Name nets as the capture names them for this part; the last part of a
  net's path matches (`BUCK1.SW` is `SW`), so the same annotation reads in
  the module and in a parent that stamps it. A name no pad of the part
  carries refuses the annotation.
- The citation after `;` is required: the datasheet and where in it the
  distance is stated or drawn. An annotation without one is refused, and so is
  one whose distance does not read.
- It acts as a clearance between this part's `pads=` pads and the copper on
  the `away=` nets that is a pour or another part's pad, held by the planner
  and written to the `.kicad_dru` for KiCad's DRC. The part's own pads are not
  held to it (their spacing is the footprint's), and nor are the tracks and
  vias of the `away=` nets: those are the part's own pad escapes, which leave
  the package where its pins are, and KiCad's rule language cannot tell them
  from other tracks of the net. Other copper on the same nets keeps the
  netclass figure.
- `keep-out` judges the same nets as a pair: any copper on an `away=` net
  against any copper on a `pads=` net (the part's pads, and the tracks, vias
  and pours of those nets) at the cited distance, and its note says so. Not
  judged against it: a pair of the part's own pads; a track or via of an
  `away=` net that is joined to the part's own pad on it; the nets of the
  part's other pads that `away=` does not name, which are the package's (the
  boot pin of a regulator whose datasheet runs boot copper at the package gap
  is left out of `away=`). The part's own pad against copper of a `pads=` net
  is held to the cited distance or to the gap the package puts between those
  pads, whichever is less.

## Sources and limits

`Pm.Emits` says a part emits something (a field, heat): `<kind>:<value><unit>@<r>mm^<falloff>` reads "`value` at `r` mm, falling off as `r ** -falloff`",
so `value(r) = v_ref * (r_ref / r) ** falloff`. A dipole's field falls off as
the cube (`^3`), heat spreading through a plane roughly linearly (`^1`).
`Pm.Limit` says a part tolerates only so much of a kind: `<kind>:<value><unit>`. A source and a sensitive part pair when they name the same kind;
`kind` is free text.

```
M1  (a magnet)      Pm.Emits:  magnetic:3.2mT@13.5mm^3
    (a case-mounted magnet is a footprint the board's project draws, with its outline,
     the pads it lands on and Pm.EmitsAt at its source point)
U2  (a field sensor) Pm.Limit: magnetic:0.5mT      Pm.SensesAt: pad:3
U1  (a converter)    Pm.Emits: heat:15C@5mm^1      Pm.EmitsAt: pad:9
Y1  (a crystal)      Pm.Limit: heat:5C
```

- `Pm.EmitsAt` is in the footprint's own frame, so it turns and flips with
  the footprint as its pads do; `pad:<number>` names a pad. `Pm.SensesAt`
  names the sensing pad.
- A unit is the text after the value. A kind must carry one unit on every
  part that names it; a mismatch is refused when the run starts, naming both
  parts.
- Several sources of a kind add at the sensitive part.
- A part that measures a source (a temperature sensor placed to read a
  converter) carries no limit for that kind: it is not sensitive to that
  source. Keep it close with `Near` or a link.
- A source no footprint carries (a point in the enclosure) is not annotated:
  it is `board.push(item, from_=Location(x, y), ...)` in the script.
- `Pm.Aggressor` and `Pm.Sensitive` keep their meanings (copper checks);
  these four are about fields and heat, not copper.

The layout holds each pair apart by the same model `board.push` uses
(`references/api.md`, "Push, annotated"), and `placemat check` judges each
sensitive part's value at its final place against its limit. Whichever of the
two is searched first is placed where the other keeps a legal spot at the
limit distance, so a pair does not fail for the order the parts are searched
in; where no such spot exists for any candidate, the second part is
unplaced and its finding names the push.

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
  part's own pins are its package and are not judged. Where the pair is
  copper on a part's `Pm.KeepOut` `away` net and copper on its `pads` net, the
  part's cited distance is the limit instead, and the note says so
- `crossings-under`: other nets' copper on another layer under a
  sensitive net's tracks, unless a plane fill on a layer between them
  covers the crossing; zones and vias do not count, the limit is zero
- `current-path`: per net a `Pm.I` names, each two parts carrying on it
  judged at the lesser of their currents by the narrowest point of the
  widest route between them (tracks, vias, pours, and zone fills, each
  measured along the route at `check.zone_step`) against the IPC-2221
  width at `--rise` (default 10 C), on the copper weight the board's own
  stackup gives that layer (the IPC-2221 inner-layer constant on an inner
  layer, outer on F.Cu/B.Cu; a layer the stackup does not weigh falls back
  to 1 oz), with the neck's point; a neck narrower than the width needed
  is judged by its length too, credited as short or too long
  (`check.neck_end_share`, `neck_resistivity`, `neck_conductivity`); carriers
  no copper joins yet
  are reported, not judged, and so is a net only one part carries: give
  the part that takes the load (an input connector's load, a switch's
  inductor, a supply's output) its
  own `Pm.I` so the route between them is judged
- `exposure`: per sensitive part and kind, the summed modelled value at the
  part's sensing point (`Pm.SensesAt`, else its body centre) against its
  `Pm.Limit`, naming each contributing source with its value and distance;
  a kind no source emits passes at zero
- `heat`: the board temperature (`--ambient`, default 100 C) plus `Pm.Pd`
  times `Pm.ThetaJb` (or `Pm.ThetaJa` when that is all the part has, which
  is pessimistic), against `Pm.TjMax`

The defaults are settings (`[check]` in `placemat.toml`); `placemat
settings` prints them. A verdict no layout can improve (a package's pitch
sets a track's width) is taken as it is, with a reason, by the layout
script's `board.accept` (`references/api.md`, "Accepting a check verdict"),
not by loosening a limit for the whole board.

## Annotating a capture

1. Mark every part the datasheet's layout rules name: the switch and its
   input caps (`Pm.Loop`), the switch and the inductor (`Pm.Aggressor`),
   the feedback divider (`Pm.Sensitive`).
   A part that emits a field or heat other parts must not read (a magnet,
   an inductor, a hot converter) gets `Pm.Emits` and `Pm.EmitsAt`; a part
   sensitive to one (a field sensor, a crystal, a thermistor) gets
   `Pm.Limit` and `Pm.SensesAt`.
2. Give every part that dissipates or carries the load current its numbers
   (`Pm.I`, `Pm.Pd`, `Pm.TjMax`, `Pm.ThetaJb`), with the datasheet section
   cited beside each, and a part whose height matters its `Pm.Height`.
3. After `pcb build -D warnings` passes, `placemat check` on the generated
   board reads the annotations and the classes.

## Cells for placement

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
    requirement in common may be split into cells of their own.

A cell the search refuses to place at all is the other signal that it
does not fit the board.

Fix a `split` finding, or a refused cell, in the capture: split the
cell, or move a part into another one. A layout script cannot fix a
cell the capture drew wrong; it only places what the capture gives it.

A part the finding does not group has no net inside the cell that joins
it to another member - whether it carries no local net at all, or a
local net of its own that nothing else in the cell shares. A bypass
capacitor is one: it always belongs in the cell of the IC it
serves, and a bypass capacitor between a board-level supply and a plane
has no net inside its own cell, so the grouping shows it apart from that
IC - it is never a split candidate, whatever the grouping shows. A part
placed by what it senses or shields is the same: a thermistor sits at the
part whose temperature it measures, even though all its nets run
elsewhere. Neither is a split candidate; each is placed by that physical
need, not by a group. A part with no such need (a pull-up on a shared
bus, a status-line resistor) may belong with the rest of its job, in
another cell.
