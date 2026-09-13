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

1. **Run** `placemat run boards/<x>/<X>_layout.py --label <what-changed>`.
   Read the terminal stream: placed/copper/findings, then one DRC line, then
   the impact. `-v` prints every step as it resolves.
2. **Read the numbers before the picture.** `real` DRC buckets and
   `unconnected` are the gate; `outstanding` (dangling copper) says what has
   not been drawn yet. `airwires` (count, length), `crossings` (ratsnest
   lines of different nets that cross), `crossings by net` and `congestion`
   (crossings per square centimetre of free board) say how hard the board
   will be to route BEFORE any routing is run: a placement change that cuts
   crossings and congestion is the one to keep, and the nets with the most
   crossings name the parts to move. Findings name a fixed placement that
   collides or a searched part that had nowhere to go, with the reason.
3. **Look** at `layout/<X>/layout.png` (and `layout-bottom.png` on a
   two-face board) only after the numbers say the change did what you meant.
4. **Change one thing, label it, run again.** The impact text says what
   moved and which numbers changed. If it says "nothing moved" and you
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
6. Full record: `.placemat/runs/<label>/run.json`, `script.log`,
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
2. **Read each cell's `LAYOUT-INTENT.md`** and the datasheet layout section
   of every active part that has one.
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

- The script is the only intent document. Requirements live as comments
  beside the declaration that implements them, and as `assert`s where a
  number can be checked. No separate intent file.
- Every design number is a named constant with a one-line reason. Arithmetic
  on named values is fine; a bare scalar inside a `place()` or `track()` is
  not.
- Measure, do not type: `board.extent(cell, rotation=)` and the pad
  references give the generated board's real geometry. A board dimension is
  derived from measured cells plus named margins.
- Declarations, not procedures: one `place()` per item, one copper call per
  net feature. A loop over stations is fine; a data table passed to one
  call is not. No globals, no helpers defined inside a phase.
- Priority, not order: file order never decides execution. Say how firm a
  thing is (`at=`/`center=` are FIXED, `edge=` is EDGE, `near=` is searched;
  `priority=Priority.FIXED` on copper that nothing may cut into; `HIGH`,
  `DEFAULT`, `LOW` on tracks to say who passes under whom). The runner
  schedules: setup, FIXED, EDGE, cells, FIXED copper, loose parts, copper.
- Copper is declared against pads and lanes (`PadRef`, `CellPadRef`, `X()`,
  `Y()`), never against coordinates that were true before the parts moved.
- Typed values: `Net`, `Part`, `Cell`, `CopperLayer`, `Edge`, `Location`.
  Pad numbers are ints, nets are strings. A pad reference that names a
  missing net fails when declared, not at write time.
- Module cells are rigid: place them, never their members. A cell that does
  not fit is a module question, not a script workaround.

## Placement tactics

- Fixed and edge things first, then the largest and most constrained cells,
  then whatever is left. Adjacency and separation are scarce; the first to
  ask gets them.
- A cell faces its partner: its handoff pads toward the cell they connect
  to, its quiet side away from the aggressor.
- A high-current path is copper you draw (a pour or a wide track), declared
  FIXED so no loose part settles on it. A plane serves what it reaches by a
  via; a bypass capacitor served through a via is a bulk capacitor.
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

## Gates, in order

`real` DRC buckets empty; `unconnected` 0 (or only the nets you have not
drawn yet, by name); no findings; `outstanding` explained (a module's
frontier stubs are dangling until the board picks them up); the render
reads as intended. A run that regenerated the board is compared against the
committed board, not against the previous run.
