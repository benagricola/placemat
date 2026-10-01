# Neck length in current-path, and a keep-out limit per part

Status: approved (2026-10-01).

Source: a board's session, through the owner (2026-10-01). Two requests, one
spec because both change `src/placemat/checks.py` verdicts that fail where a
layout cannot do better.

## Problem

### 1. current-path judges a neck by its width alone

`current-path` takes the narrowest point of the widest route between two
current carriers and compares it with the IPC-2221 width for `[check]
rise_c` (`_need_mm`). On a switching converter a fitted pour escapes between
a package's adjacent pads, whose clearance caps its width. It necks to
1.22 mm and 1.03 mm against 1.76 mm needed at 3.6 A, and cannot be widened.
The owner's words, relayed: "It may not be physically possible to increase
the pour size without running into clearance issues. In this case, length is
important and that's probably something for the placemat agent to find a
solution for."

IPC-2221's chart is a long uniform conductor. A short constriction between
wide copper loses heat by conduction into the copper either side, so its
peak temperature is lower. The check has no notion of length: a 0.4 mm
neck and a 40 mm neck at the same width get the same verdict. Its note
names a neck's length for tracks only (`_neck`), and as the run of tracks
within `check.neck_band` of the narrowest, which is not the length over
which the copper is too narrow.

### 2. One keep-out limit for the whole board

The keep-out check judges every switch node against `check.keep_out_mm`
(2 mm). Several switching regulators' own pads and datasheet reference
layouts put the feedback and compensation pins closer than that to the
switch node: pad spacings of 0.7 mm to 1.2 mm, and a reference layout that
draws the compensation network 0.4 to 0.6 mm from the switch node. The
check fails on a distance the datasheet itself draws. `board.accept("keep-out",
net, at_least=, why=)` can take each one, but it is written per net in
each script, and a module stamped into a parent repeats it. The limit is a
fact about the part, not about the script.

The planner does not know it either: a fitted pour or a track on the switch
and boot nets is laid at the netclass clearance from the part's feedback and
compensation pads, nearer than the datasheet draws (1.1 mm from a pad where
the package's own pad gap is 1.3 mm). `board.rule(clearance=, between=)` is
not an answer: it is a typed number per board, and it moves unrelated copper
on those nets.

### 3. A load with several pins on a net

A session reported `current-path` naming one small pin of a load that has
several pins on the net, the pin's neck failing the route though the load's
larger pad is joined wide.

## Design

### 1. A short neck is credited by conduction to the copper either side

#### Sources

- D. Brooks and J. Adam, "Trace Currents and Temperatures Revisited"
  (UltraCAD, April 2015),
  <https://www.mathscinotes.com/wp-content/uploads/2016/06/pcbtempr.pdf>,
  section 5 ("Trace Length") and figures 2-3, 5-3. Thermal simulation of a
  1 oz, 200 mil wide external trace at 15 A with pads at each end: peak
  rise 94.7 C at 6 in., 81.5 C at 2 in., 64.6 C at 1 in.; at the 6 in.
  trace's ends the rise is 57.9 C. The authors conclude that "shorter
  traces [have] more opportunity to shed heat through the pads at each
  end", and that how much depends on "the nature and size of those pads".
  The same paper (section 2) says IPC's measured rise is the trace's
  average, not its peak.
- IPC-2152 (2009) replaced IPC-2221's chart with measured data; its
  published method has no length term, and it treats the chart as for a
  conductor long enough that end effects do not matter. Overview:
  <https://www.protoexpress.com/blog/how-to-optimize-your-pcb-trace-using-ipc-2152-standard/>.
  The standard itself is paywalled and was not opened; the statement that
  it has no length term is from that overview and from Brooks and Adam.
- Steady conduction along a strip with uniform heat generation and its ends
  held at one temperature: the profile is a parabola and the peak, at the
  middle, is `q L^2 / (8 k)` above the ends (q the volumetric generation, L the
  length between the ends, k the conductivity). Textbook: F. Incropera et al.,
  "Fundamentals of Heat and Mass Transfer", chapter 3 (conduction with
  thermal energy generation); the fin equation it extends, which has a
  side-loss term this rule leaves out, is on
  <https://en.wikipedia.org/wiki/Fin_(extended_surface)>. With
  `q = rho I^2 / A^2` for current `I` through cross-section `A`:

  `dT = rho I^2 L^2 / (8 k A^2)`

- Copper: resistivity 1.68e-8 ohm m at 20 C with a temperature coefficient of
  4.04e-3 per K
  (<https://en.wikipedia.org/wiki/Electrical_resistivity_and_conductivity>),
  so 2.2e-8 ohm m at 100 C; thermal conductivity 384 W/(m K) at 18 C
  (<https://en.wikipedia.org/wiki/Thermal_conductivity>).

#### The rule

A neck is the stretch of the route over which the copper is narrower than
the width the current needs (`need`, IPC-2221 as today). Its width `w` is the
narrowest on it and its length `L` is measured along the route. When `w <
need` the neck is credited as short if its own conduction to the copper at
each end holds the peak rise inside the neck's share of the rise budget:

`rho I^2 L^2 / (8 k (w t)^2) <= (1 - end_share) * rise_c`

`t` is the copper thickness of the neck's layer (the stackup's, as for
`need`), `I` the current the route is judged at. Equivalently, the longest
neck a width passes is

`L_max = (w t / I) * sqrt(8 k (1 - end_share) rise_c / rho)`

(1.03 mm wide in 1 oz copper at 3.6 A and a 10 C rise: 7.5 mm; the 0.4 mm
neck of the request passes with 0.01 C of rise). A neck longer than
`L_max` is "too long" and fails as it does today; so does any neck with
`w < need` and no measurable length.

Why this rule and not a longer one:

- It is the simplest closed form a source supports: one-dimensional
  conduction to the ends, with no side loss. Side loss to board and air only
  lowers the rise, so the rule errs towards failing.
- Brooks and Adam's simulation shows the end copper heats too: the ends of
  their 6 in. trace sit at 61 percent of its peak. `end_share` reserves that
  part of `rise_c` for the copper at the ends and gives the neck the rest.
  Checked against the same simulation, `end_share + dT` at 1 in. is
  `0.6 * 94.7 + 32 = 89 C`, above the simulated 64.6 C; at 2 in. it is above
  81.5 C by more. The rule never credits more than the simulation shows,
  for that trace.

Limits, said in the note and in api.md:

- The copper at both ends must be wide. The route's neck is by definition
  the stretch narrower than `need`, so what bounds it is a pad, a via or
  copper at least `need` wide. A pad is taken as a sink, as the route search
  already takes it as passing any width.
- The ends are taken as cool to the extent of `end_share`; copper at the ends
  that is itself hot (a long, loaded plane edge) is not modelled.
- Steady state, one current. A neck on a net the board loads in pulses is
  not judged by it any differently.
- A neck wider than `L_max` allows is not helped by being nearly wide
  enough: the credit is all or nothing against `rise_c`.

#### Measuring the length

- A track neck: the run of consecutive track nodes on the route narrower than
  `need` around the narrowest, stopped each way by a pad, a via, a pour or
  a track at least `need` wide (`_neck`; an arc counts along the arc). This
  replaces the `check.neck_band` run, which measured how far the route stays
  within a band of the narrowest width. `check.neck_band` is still accepted
  in a config and no longer read.
- A pour or zone fill neck, from the raster the check already builds
  (`_Fill`, at `check.zone_step`): the path `width` finds at the bottleneck
  level is cut where the cells reachable from the entry copper at the level
  `need` ends and where the cells reachable from the exit copper at that
  level begin; the neck's length is the path distance between them (8-connected
  steps of one cell, or a cell times root two on a diagonal), read within one
  step. A fill narrower than one step has no measurable length and is not
  credited. `reach=Reach.CURRENT` on a fitted pour keeps growing the pour
  toward the full width: only the verdict credits a short neck.

Both reuse the existing `_Fill.touching` and `_Fill._reach` (Python and
native); no change in `native/`.

#### The note

The note keeps what it says and adds the neck's width, length and the basis:

- `a 0.40 mm long neck at 1.03 mm, credited as short: 0.01 C of its 4 C
  share of the 10 C rise by conduction to the copper at each end (a 1.03 mm
  neck passes up to 7.5 mm at 3.6 A)`
- `a 9.00 mm long neck at 1.03 mm, too long: 5.7 C of its 4 C share ...`

The verdict is ok when `w >= need` or the neck is credited. A verdict with a
credited neck still reports `value` as the width and `limit` as `need`, so
`board.accept("current-path", ..., at_least=)` and the run record read as
before.

#### Settings

All under `[check]`:

| setting | default | meaning |
|---|---|---|
| `neck_end_share` | 0.6 | the share of `rise_c` the copper at a neck's ends is taken to have already used: Brooks and Adam's 57.9 C of 94.7 C. 1 turns the credit off |
| `neck_resistivity` | 2.2e-8 | copper's resistivity at the working temperature, ohm m (above) |
| `neck_conductivity` | 384 | copper's thermal conductivity, W/(m K) (above) |

### 2. `Pm.KeepOut`: a keep-out limit on the part, with its citation

A capture annotation on the part, read from its footprint fields like every
`Pm.*` (case-insensitively):

```
Pm.KeepOut: <distance>mm [pads=<net>[,<net>...]] [away=<net>[,<net>...]]; <citation>
Pm.KeepOut: 0.7mm pads=FB,COMP away=SW,BOOT; datasheet rev B, section 10.2, layout example
```

- **Distance.** In mm (`0.7mm` or `0.7`), above zero. It may be below or above
  `check.keep_out_mm`: a datasheet may ask for more.
- **Citation.** Everything after the first `;`: where the datasheet states or
  draws the distance. Required.
- **Which pads.** `pads=` names nets of this part's pads that keep the
  distance (the sensitive pins). Default: the part's `Pm.Sensitive` net.
- **Which copper.** `away=` names nets of this part's pads whose copper they
  keep away from (the switch and boot pins). Default: the switch nodes the
  part is on. Pins are named by their nets, as `Pm.Sensitive` names its net,
  because the part's pin functions are not on the board (a pad carries a
  number and a net). Naming nets of the part's own pads, and not any net,
  makes the annotation read in a module and in every parent that stamps it: a
  stamped module's nets carry its path, and a name matches a net it is the whole
  of or the last part of after `.` or `/` (`SW` is `BUCK1.SW` and `BUCK1/SW`,
  not `VSW`). A name no pad of the part carries refuses the annotation.
- **Refused.** An annotation with no citation, a distance that does not read
  or is not above zero, an unknown word, a net no pad of the part carries, or
  nothing to default to (`pads=` with no `Pm.Sensitive`, `away=` on no switch
  node) is refused. `placemat check` reports a failed `keep-out` verdict named
  `<ref> Pm.KeepOut` whose note says what is wrong, and judges the part at the
  board-wide limit; `Board.resolve()` raises, naming the part, so a run does not
  proceed on a datasheet fact with no source.
- **A stamped module** carries it: the annotation is on the part's footprint
  field, which the parent's netlist has for every stamped copy of the part, so
  the parent's check and planner read it with nothing repeated in a script.
- **`board.accept` stays** for a one-off verdict, where a layout cannot do
  better and says why. A datasheet fact about a part belongs on the part.

#### In the check

`keep-out` judges the nearest pair of switch-node copper and sensitive-net
copper. The nets judged are the switch nodes, and the `away` nets of
annotated parts (a boot net is not a switch node). Each pair carries a limit:
the `Pm.KeepOut` of the part whose pad on one of its `pads` nets is one of the
pair, with the other on one of its `away` nets and not that part's own pad (the
largest, where two parts do), and `check.keep_out_mm` otherwise; a pair only an
annotation names is judged by it alone. The verdict is the pair with the least
margin over its own limit, and the note says where the limit came from. A track
or pour leaving an annotated pad is not the part's pad and is judged at the
board-wide limit.

#### In the plan

The same distance is a clearance between those copper items, held where
`board.rule(clearance=, between=)` is held (a typed number per board that
moves every item on the nets) but scoped to the part's pads:

- `rules.Rule` gains `of=<ref>`, with `between=(away_net, pads_net)`: the rule
  matches a pair when the item on `pads_net` is a pad of that part and the item on
  `away_net` is not its own pad (in either order). `ClearanceRules.match`,
  the native `ClearanceRule`, and the `.kicad_dru` condition (`B.Reference ==
  '<ref>' && !(A.Reference == '<ref>')` in both orders, checked against
  kicad-cli's DRC) all say it. Everything that asks a pair's clearance
  (`Board._clearance`, `Occupancy.pair_clearance`, the native conflict
  search, the fitted pour's obstacle pieces at `layout.py` `add(sh,
  occ.pair_clearance(...))`, the track and via checks) already goes through
  `match`, so a fitted pour, a declared track, a via and another part's pad
  keep the distance from the part's pads.
- `Board.resolve()` derives one rule per (`away`, `pads`) net pair of each
  annotated part, after the script's rules, so the part's own, more
  particular, figure decides where both match. Its minimum is the larger of
  the datasheet distance and the clearance the pair has otherwise (the
  netclass's, or a script rule's): a datasheet distance never lowers a
  clearance.
- The part's own pads are exempt (the rule's `of` excludes them): the footprint
  sets that gap. This is the decision on a session's suggestion that where the
  nearest points are a part's own two pads the limit default to that pad gap:
  the check already leaves a part's own pads out of the verdict and says when
  they are nearer, and does not lower the limit for other copper (a pour or a
  track leaving those pads) to that gap, since a layout can change that
  copper. Where a datasheet asks for a distance, `Pm.KeepOut` states it.
- `[place] conflict_gap` must be at least the largest clearance a rule asks, as
  for any rule; a larger `Pm.KeepOut` makes the run say so.

### 3. A load is all of its pins on the net

A session reported `current-path` picking one pin of a load that has several
on the net (a small pin and an exposed pad), the small pin's neck failing
the route though the large pad is joined wide.

`_pairs` already does take a load as all its pins: each carrier's sources
are every pad of the part on the net, and for each pair of carriers the
widest route from any pad of one to any pad of the other is judged (`ends =
pads.get(b)`; `max(reach)` over the load's pads). A two-pin load whose small
pin necks and whose other pad is joined wide is judged by the wide route; a
test pins that (`tests/test_current_path_pins.py`). So there is nothing to
change in which pin is chosen.

Of the two readings the request offered (the widest route to any pin, or
the current shared between pins), the widest route at the full current is
the one kept. Parallel routes share a current in proportion to their
conductance (Kirchhoff's current law), so the widest route alone carrying
the whole current is the pessimistic bound: what the route carries is at
most the whole, and the others carry the rest. Where the routes to the pins
share one neck (the pour that joins both squeezes between the same
neighbouring pins), the neck carries the sum and no reading changes it; that is
the reported case's likely shape, and the length rule in section 1 is what
answers it. Where the routes have separate necks, a share would pass a load
neither route passes alone; that needs a flow over the route graph with a
width per neck, and a pour has no per-route width to flow, so it is filed as
open work in `BACKLOG.md` and not specced here.

## Verification

1. Neck length, `tests/test_neck_length.py` (synthetic boards):
   - a long narrow strip (0.9 mm wide, between pads 16 mm apart) fails as today, with `too long` and its length in the note;
   - a short constriction (0.4 mm long, 1.03 mm across) between two wide pours, which fails today, passes with `credited as short` and its length printed; the same in a zone fill and in tracks;
   - a constriction just over the length it passes fails (the same width passes at 3 mm, fails at 6 mm, and the note's length and `passes up to` agree);
   - settings change the outcome: `neck_end_share` 1 fails the short neck, a larger `neck_conductivity` and a smaller `neck_resistivity` pass a neck that fails by default;
   - a fill under one step wide has no length and is not credited;
   - `tests/test_current_path_neck.py`, `_zone_width`, `_pairs` and `test_checks.py` are updated where the neck was short enough to be credited, and where the length is now the run narrower than the need.
2. Per-part keep-out:
   - `tests/test_keep_out_part.py`: a part with the annotation is judged at its limit (passes at 0.7 mm where the board-wide 2 mm fails), a larger limit applies, a refused annotation (no citation, bad distance, unknown word or net) is a failed verdict and the part is judged at the board-wide limit, other parts keep the board-wide limit, a track off the annotated pad is judged at the board-wide limit, a part's own pads are not judged, a module stamped twice carries the limit to the parent;
   - `tests/test_keep_out_planning.py`: a track and a fitted pour on an `away` net keep the part's distance from its `pads` pads while the same net's copper near another part's pad keeps the netclass clearance, the derived rule is never below the netclass or a script rule, a refused annotation refuses `resolve()`, and kicad-cli's DRC agrees with the written rule (flags the track that ignores it, passes the one that keeps it); `native/src/shapes.rs` has the rule's unit test.
3. Loads, `tests/test_current_path_pins.py`: a load reached narrowly at one pin and wide at the other is judged by the wide route.
4. The full suite; `fixtures/bench.py --jobs 4`, which should not move
   (no placement code changes except the rule), with its tally in the commit message.
