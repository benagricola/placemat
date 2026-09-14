---
name: placemat
description: Lay out a KiCad board from a Python script with placemat - understand the board electrically first, declare placement and copper by intent, run, read the numbers, iterate. Use for any board or module layout, a placement change, or a "why did DRC change" question.
---

# placemat

`placemat run <script>` generates the board, runs the script, writes the
KiCad file, runs DRC and renders, and records what happened. One run is
seconds once the board is cached; the record and the impact against the
previous run are how a change is judged. The point of the tool is that a
placement decision can be tried and measured cheaply, so try many.

Read `references/api.md` for the script surface. Everything below is how to
work, not what to call.

## The loop

1. **Run** `placemat run boards/<x>/<X>_layout.py`. A run is named by a
   short hash of the script, the generated board and the tool, so the same
   inputs are the same run; `--label <name>` adds an alias you can pass to
   `impact` later. Read the terminal stream: placed/copper/findings, then
   one DRC line, then the impact. `-v` prints every step as it resolves.
2. **Read the numbers before the picture.** `real` DRC buckets and
   `unconnected` are the gate; `outstanding` (dangling copper) says what has
   not been drawn yet. `airwires` (count, length), `crossings` (ratsnest
   lines of different nets that cross), `crossings by net` and `congestion`
   (crossings per square centimetre of free board) say how hard the board
   will be to route BEFORE any routing is run: a placement change that cuts
   crossings and congestion is the one to keep, and the nets with the most
   crossings name the parts to move. Two firm placements that collide stop
   the run at once with the reason: fix the declaration, do not search
   around it. Findings name a searched part that had nowhere to go.
3. **Look** at `layout/<X>/layout.png` (and `layout-bottom.png` on a
   two-face board) only after the numbers say the change did what you meant.
4. **Change one thing, run again.** The impact text says what moved and
   which numbers changed (`placemat impact <run> <run>` compares any two, by
   id, id prefix, label or path). If it says "nothing moved" and you
   expected movement, your change was not where you thought.
5. **Route only when the placement has settled.** Routing is a separate,
   slow step you ask for: `placemat run ... --route` (after the checks) or
   `placemat route <board>`. It routes a COPY with every existing track and
   pour locked and the plane nets excluded, then reports closure: the share
   of open signal connections it closed under the board's own rules, and the
   clean closure that counts a net closed through a violation as still
   open. Run it when crossings and congestion have stopped falling, never
   while big parts are still moving; read `still open` for the nets that
   name the next placement problem. The routed copy is evidence, not the
   layout: the script does not change because the router found a path.
6. Full record: `.placemat/runs/<id>/run.json`, `script.log`,
   `drc.json`, `generate.log`, `layout.kicad_pcb`, and `route/` when routing
   ran. Logs are files; read the tail, not the whole thing.

Never edit `layout.kicad_pcb` by hand as the fix. The script is the layout;
a hand edit is a measurement that gets folded back into the script.

## A fresh board

Do this before writing a line of the script. The script is a translation of
this model into declarations, and a script written without it is a table of
coordinates nobody chose.

1. **Read the board `.zen`**: every instance, every net, the net classes,
   which nets are planes, each module's `io()` ports, which parts are
   connectors and which edge or face their mating side needs.
2. **Read each cell's layout script**: its docstring is the cell's intent
   (what it is, which side is outward, what continues at board level) and
   its declarations are the geometry. Read the datasheet layout section of
   every active part that has one.
3. **Build the electrical model.** Classify every relationship:
   - high-current paths: source to consumer (an input connector to the
     bridge it feeds, switching FETs to the output connector). Short for
     resistance and heat, wide copper, no vias in the path.
   - switching loops: the FET, its return and its decoupling. Small area.
   - sense and Kelvin paths: at the pin, nothing between.
   - length-sensitive signals: matched or tuned pairs, clocks, fast buses.
   - isolation boundaries: what may not cross what.
   - ordinary signals whose off-board length dwarfs the board: an
     optoisolated input's connector does NOT need to sit at its optoisolator.
   - mechanical facts: mounting patterns, case windows, a sensor whose
     position is its function.
4. **Write the proposal as the script's opening comment**: which edge each
   connector takes and why, what is FIXED (mechanical fact), what is EDGE
   (one degree of freedom), which cells cluster with what, which copper is
   FIXED (nothing later may cut into it), where the corridors are, and which
   constraint outranks which when they conflict. Say which relationships are
   about current and heat and which about signal integrity: they want
   different things.
5. Only then declare.

## Script standard

- The script is the only intent document: its docstring says what the
  board is, which edge carries what and why, what is fixed and what
  outranks what; requirements live as comments beside the declaration that
  implements them, and as `assert`s where a number can be checked. There is
  no separate intent file for a board or a cell.
- Every design number is a named constant at the top of the file with a
  one-line reason it was chosen. Arithmetic on named values is fine; a bare
  scalar inside a `place()`, `track()` or `X()` is not.
- Every script is for one board: name it `<Board>_layout.py` after the
  `Board(name=)` or `Layout(name=)` in the `.zen` beside it; a directory
  with several boards is told apart by that name.
- Measure, do not type: `board.extent(cell, rotation=)`, `board.pitch(part)`,
  `board.pad(part, n).box` and the pad references give the generated board's
  real geometry, so a part swapped in the `.zen` cannot leave a stale number
  behind. A board dimension is derived from rows plus named margins.
- Declarations, not procedures: one `place()` per item, one copper call per
  net feature. Write each call out where a reader must see what it does:
  three drops are three lines, not a loop; two ends are two blocks, not a
  table of dicts. A short function called once per thing is fine when its
  name says what it lays out. No globals, no helpers defined inside a phase.
- Priority, not order: file order never decides execution. Say how firm a
  thing is (`at=`/`center=` are FIXED, `edge=` is EDGE, `near=` is searched;
  `priority=Priority.FIXED` on copper that nothing may cut into; `HIGH`,
  `DEFAULT`, `LOW` on tracks to say who passes under whom). The runner
  schedules: setup, FIXED, EDGE, cells, FIXED copper, loose parts, copper.
- Say which searched items are critical: `priority=Priority.HIGH` on the
  MCU, the driver, the bridge. They go down first in their tier, and one
  that finds no place stops the run with the free rectangles on its face
  and the board written as it stood, so what was free at that moment is
  what you look at; nothing else is placed into that space first. Firm
  only what is mechanical. Furniture (test points, LEDs, buttons) is
  `edge=` with no `along=`: one degree of freedom, it slides along its
  edge to the room that is left, so it cannot take an edge before the
  critical cells have theirs. `along=` is for a spot that is a mechanical
  fact, never for spacing things out.
- Copper is declared against pads and lanes (`PadRef`, `CellPadRef`, `X()`,
  `Y()`), never against coordinates that were true before the parts moved.
- Typed values: `Net`, `Part`, `Cell`, `CopperLayer`, `Edge`, `Location`.
  Pad numbers are ints, nets are strings. A pad reference that names a
  missing net fails when declared, not at write time.
- Module cells are rigid: place them, never their members. A cell that does
  not fit is a module question, not a script workaround.

## Placement tactics

- Say what is FIXED (a mechanical fact) and what is EDGE; leave the rest
  searched with a bare `place(item)`. The placer orders searched items
  itself (cells, blocks, loose parts; biggest need and strongest pull
  first), seeds each from the placed pads it is wired to, and says why in
  each step. Do not hand-order them with hints.
- No floorplan by coordinate: a `Location` constant that means "the power
  area" is the placer's job typed by hand, and every part hinted at it
  competes for one rectangle. `near=` is for a requirement the netlist
  cannot say (a thermal sensor by the FETs it shares no net with); a part
  with a wired neighbour on the board is linked and left bare.
- A clearance that must differ in one place (a fine-pitch part inside a
  wide-clearance class, a high-voltage pair) is `board.rule(clearance=,
  within=|between=|on=, why=)`, never a hand edit of the project file.
- Price the connections, not the parts: a bypass capacitor is a SHORT link
  with a limit at its pin; a series resistor between two distant parts is
  PREFER on both links and lands where there is room between them; a net
  whose off-board cable dwarfs the board is `free_net`, so nothing is
  dragged toward its connector. Every undeclared connection weighs DEFAULT.
- A part with satellites at its pins (a regulator and its caps) is a block:
  declare the satellites by the net each serves; the placer lays the block
  out from the real pads and searches it as one.
- A cell faces its partner: its handoff pads toward the cell they connect
  to, its quiet side away from the aggressor.
- A high-current path is copper you draw (a pour or a wide track), declared
  FIXED so no loose part settles on it. A plane serves what it reaches by a
  via; a bypass capacitor served through a via is a bulk capacitor.
- Tracks are drawn as KiCad draws them, and the tool enforces it: every
  leg at 0, 45 or 90 degrees (an odd leg becomes a 45 and a straight,
  ordered to turn least against the legs either side, the 45 at the pad
  end on a tie) and every right angle cut into two 45s (`chamfer=0` keeps
  one). Between two points the tool tries the octilinear routes of up to
  three legs, drops those that touch another net's pad or copper, and keeps
  the one with the fewest turns, then the shortest. Every turn costs signal
  integrity: give a track its ends and only the waypoints that say where it
  must go, and let the tool find the rest. Draw a daisy chain as a chain: the run bows out at 45 to an
  apex and one line leaves the apex for the pin; never a bus with stubs.
- Rows and references before numbers: things along an edge are a `row`
  (connectors `line="outer"`, small parts on their centre line); a row
  inboard of an edge row is `behind=` it; a part between two pads sits at
  `Mid()` of them; a row under a pin pair is `centre=X(Mid(...))`, a row
  beside another is `before=`/`after=`, a row after a hole starts at
  `Y(pad, gap)`. A number typed where a reference would do is a defect.
- The edge is the board's: no script carries an edge standoff. An EDGE
  item's reach sits at `board.keep_in`; a face that must stand proud of
  the edge says `overhang=` with a why. Two firm things that must sit
  beside each other are placed relative to each other (`behind=`,
  `after=`, a pad reference), never by independent numbers from opposite
  edges: the first collision is the run stopping, not a finding to tune.
- Label what a user touches: every connector, jumper, switch and LED gets
  a `board.label()` on the face it is used from, saying what it does
  ("MOTOR", "CAN IN", "TERM"), knocked out where the silk is busy; a pin
  1 mark on every keyed connector. A refdes is not a label.
- A bus down a board is one long track per net and a short track per pad
  into it. Two same-layer nets may cross only where the one that yields is
  declared `bridge=True`; who yields is decided by `priority`, never by
  declaration order, and a crossing nobody may bridge is a finding. Give
  the long runs the higher priority and the short reaches `bridge=True`.
- Use placemat's words in the script's comments, and define any word of
  your own (a "corridor", a "column", a "bank") where it first appears, in
  terms of what is on the board. A comment and the run log must mean the
  same thing by the same word.
- Keep a corridor open by not placing in it; reservations are for copper the
  script has not drawn yet, not for space you like.

## When a track or a placement fails

- Read the finding as a claim about the script first. A track that hits
  a pad may have a waypoint steering it there (the run says so when pad to
  pad would clear), or its two ends may be placed so that no clean route
  exists, or the tool may have no candidate that fits. Take those in that
  order: remove the waypoint, then look at the placement, then at the tool.
- Never say a route is impossible from one run. Draw the thing the plain
  way (pad to pad, no waypoints, no offsets), run, and read the numbers.
  "The geometry forbids it" is a claim to be tested like any other, and it
  is usually a waypoint or a constant in the script.
- When a number in the script was chosen to dodge something, it is a
  workaround for a rule the tool should carry. Say so in the run notes so
  the rule gets built instead of the number being copied.

## Gates, in order

`real` DRC buckets empty; `unconnected` 0 (or only the nets you have not
drawn yet, by name); no findings; `outstanding` explained (a module's
frontier stubs are dangling until the board picks them up); the render
reads as intended. A run that regenerated the board is compared against the
committed board, not against the previous run.
