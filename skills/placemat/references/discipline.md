# Script discipline

How a layout script is written, changed and kept honest: what belongs in it,
what a change to one costs, and what to do with a board somebody hand-edited.
Read before editing an existing script.

## Script discipline

- **Never re-implement shared machinery locally.** Before writing any helper
  (group move/rotate, bbox measurement, overlap tests, edge placement, silk
  labels, keepouts, design rules, stackup/render settings, width wrappers)
  read the library's whole API surface - list its public functions and methods
  and match by CONCEPT, since the primitive you want may carry a different
  word than the one in your head. A private copy silently diverges, and the
  divergence surfaces as one board behaving differently from its siblings, or
  as a local copy that never got the fix the library had.
  When nothing matches, the addition is a PROPOSAL, not a commit: say what it
  does and which boards would use it, and let the owner decide. A library that
  grew by whoever needed something first ends up with two names for one idea,
  and then no script can be read against it.
- **Start a new script from the scaffold (`placemat new-board`).** It carries the
  section order, the config/mechanism split, and a library call in each place a
  script is tempted to hand-roll one. Change the FORMAT there first, then bring
  the scripts to it - a format that lives only in the last script somebody
  touched is not a format.
- **Deterministic, and proven.** Board generators do not guarantee footprint
  order between generations, so any loop that iterates in board order places parts
  differently run to run. Iterate in an order you impose (reference,
  hierarchical path, geometry). Prove it: regenerate twice from clean board generations
  and compare placements as multisets.
- **Never key a placement on a refdes.** Refdes renumber whenever the
  schematic changes; a script that says "place C35 here" silently places a
  different part after the next capture edit and nothing catches it. Resolve
  parts by a stable identity (the hierarchical path the generated board records, or a
  role query such as "the part on nets X and Y") and assert the resolution.
- **Verify a reusable cell against the rule its consumers impose, per net.**
  A fragment DRC'd in isolation at the fab default passes, then fails when a
  board with a tighter netclass stamps it. Work out which of the cell's nets
  land in which consuming class and hold each to its own floor; blanket-
  applying the strictest class to a whole cell demands impossible geometry on
  nets that never needed it. DERIVE that mapping rather than maintaining it:
  a stamped footprint records its instance path, so a pad on a board traces
  back to the pad in the fragment that produced it, and the board's class for
  that pad is the floor for that net inside the cell. What no class can
  express stays with the module and only there - a floor RAISED because
  module-local copper carries a rail's potential under a local name, and a
  named pair excused BELOW the floor with the arithmetic showing the part
  forbids it and what the gap actually stands off.
- **Some minima are set by the package, not the layout.** A 0.4 mm-pitch QFN
  with 0.2 mm pads leaves 0.2 mm, full stop. Before "fixing" a tight pair,
  check whether any layout choice could change it; if not, record it as
  part-forced with the arithmetic.
- **Honesty gate.** If a stated target proves geometrically impossible, stop
  and report the measured menu of options instead of committing a bad
  compromise. Report results as numbers (mm, DRC bucket counts against a
  baseline, clearances), never impressions, and never filter a DRC bucket out
  of a summary.
- **Output discipline.** Never print board files, geometry dumps or DRC JSON
  inline; write them to scratch files and read back slices. Build scripts
  incrementally with targeted edits; a whole-file rewrite of a coordinate
  script is the most common way to overflow an output limit mid-task.
- **One runner, in the foreground.** A placement pass is one command (the
  project's round runner: clean board generation, script, occupancy,
  DRC, optional routing trial, record) run from any directory with absolute paths.
  Never write a private runner or wait loop: a private runner drifts from
  the gates, and the harness kills background shells on its own memory
  heuristic regardless of real free memory. Long tools (board generation,
  router, DRC) run in the foreground with an explicit timeout; only one
  router at a time per machine (the trial tool queues on a lock).
- **Verify the hand state before folding it.** Run DRC on a hand-edited
  fragment first; a hand pass can leave a real clearance violation
  (a moved terminator against a trace that stayed) and the fold-in must
  fix it and say so, not reproduce it.
- **Comments say what the code does and why it is that way - nothing else.**
  A layout script is read by whoever changes it next, and what they need is
  the constraint behind a number: which pad, courtyard, lane or datasheet
  rule fixes it, and what breaks if it moves. Write that, in the present
  tense, as a standing property of the design.
  Never write a script's history into it. No dates, no revision numbers, no
  "was X, now Y", no round or pass narrative, no who-asked-for-it, no
  measured-on-a-past-revision figures, no "the lesson". Git holds the
  history and the intent doc holds the design record; a comment that
  recounts either is stale the moment the next round lands, and it buries
  the constraint a reader actually needs. The test: delete every clause
  that would still be true if the file had been written from scratch today
 - what remains is the comment.
  A number in a comment is the geometry it comes from, not a measurement
  event: "clears the gate pad by the 0.25 floor", not "measured 0.254 at
  0.100". Cite a datasheet rule by section. Say "read from the part" where
  a value is derived at run time. And where a constraint is genuinely
  part-forced, state the arithmetic, because that is what stops the next
  round trying to fix it.


## Migrating a script onto the standard

Reached from step 0. **A script that predates the current standard gets
MIGRATED FIRST, whole.**
The standard is the scaffold (`placemat new-board`) plus the shared library: the
scaffold fixes the shape (config above the line with every value carrying
its source, the same mechanism sequence below it) and the library holds the
placement, copper, label, keepout and report primitives. The scaffold is the
standard precisely because it is not a board - a real script is always
mid-flight, and half-finished work is not a format to copy. A script written
before a primitive existed carries a hand-rolled version of it: a local
helper, an inline bounding-box calculation, a raw unit conversion, a
coordinate list maintained by hand. Bring the WHOLE FILE onto the standard
before making the change that was asked for, as a separate step, in this
order:
(a) **Replace, do not add.** Every piece of generic code that a library call
already covers becomes that call. Search the library by CONCEPT, not by
name - the primitive you want often exists under a different word (a
"keepout band" is a reserve, a "probe print" is a net offset, a "which way
did it land" is a stamp report). Read the library's API surface before
concluding anything is missing.
(b) **Propose the rest, do not write it.** Local code that is genuinely
generic and has NO library equivalent gets named in your report as a
proposed addition, with what it does and which boards would use it - it is
not moved into the library on your own authority. Adding blind is how the
library grows two functions for one idea, which is worse than the
duplication it was meant to fix.
(c) **Then the shape**: naming, section order and the config/mechanism split
follow the scaffold.
Verify the migration by regenerating and confirming the output is unchanged
- a migration that moves a part is a bug in the migration - then make the
actual change on top.
Two costs make this non-negotiable: a hand-rolled copy does not get the
library's later fixes (the local label helper that skips the silk audit,
the local overlap loop that never sees a courtyard), and a file nobody can
read is a file nobody can safely change.

If the migration is genuinely too large to land with the change, say so and do
the migration alone first - never the change alone.


## Where things live

- **Project-wide rules at the top level only.** The project's root rules
  file, its shared-module README and this skill carry what applies to every
  board and every cell: the toolchain flow, the shared library, clearance
  floors, verification gates, part standards. A fact about one board (its
  frame, its render extras, its connector edges) or one cell (its datasheet
  rules, its copper contract) never goes there.
- **Each board owns a `BOARD-INTENT.md`** (the spec its layout script
  implements: mechanics, zoning, envelope, connector edges, open items) and
  **each module owns a `LAYOUT-INTENT.md`** (datasheet layout rules, as-built
  structure, copper contract, floor, accepted exceptions) in its own folder.
  The intent file is the electrical input to the script; the script is the
  layout; hand edits are folded into the script and their why into the
  intent file.
- **A new board or module starts on the shared classes.** A module script is
  the project's cell class (place, pours, tracks, vias, stitch, save) and a
  board script is the project's board class (stamp, place_free, edges, rows,
  labels, pours, outline), both called directly; the first commit carries
  the intent file, the script, the verified fragment or board and both
  renders. Nothing in either script is a private copy of a mechanic the
  library has, and nothing in the top-level docs is about that one board.


## Two freedoms the layout owns

- **Pin assignment is a layout freedom.** When a device's pins can carry a
  function on more than one pin (MCU GPIO, peripheral instance groups), the
  layout may re-assign them to remove crossings and shorten escapes, and is
  encouraged to. A cell frontier whose stub order is inverted against the
  destinations cannot be fixed by placement; one swap fixes it. Legality:
  same function class and same peripheral grouping, never across a voltage
  domain or onto a strap or debug pin, every swap recorded with its reason,
  and the firmware pin map regenerated from the schematic so the two cannot
  drift. The schematic is where the pin map lives, so a swap is a schematic
  edit followed by a clean regeneration.
- **Interconnect inside a reusable cell is a contract, not copper.** A cell's
  structural copper (hot-loop pours, switch-node bars, Kelvin taps, local
  ground regions, an escape-via architecture the owner has ruled fixed) is
  stamped as drawn. Its interconnect traces, and the ORDER in which its nets
  land along a frontier line, are not structural: the contract names the
  side and the nets, the board chooses the order and the path per instance,
  and reference traces in the fragment are a preference the board may
  discard where they do not fit. A fixed stub order in a fragment is a
  crossing waiting to happen on the next board. A module contains a layout
  AND a routing; using that routing is the consuming layout's prerogative,
  kept where it fits the board and re-drawn where it does not. Only the
  structural copper is fixed, and the module's own layout-intent file says which copper that is.


## The concession ladder

Every move that makes placement or routing easier has a cost, and the
harness takes them in cost order. The KINDS of concession are fixed; their
costs, and therefore their order, come from the project's fab profile for
the fab and stackup in use, because the same concession is free on one
stackup and paid on another (via-in-pad with filled and capped vias can be
included on a fab's six-layer boards and an extra on its four-layer ones,
while a smaller via drill is charged on every stackup). Never assume an
order; read it.

Always on, tier 0, no cost: move loose parts; rotate or flip cells;
re-route a cell's interconnect and choose its stub order; add vias at the
default size; re-assign pins within the legality rule (a pin is fixed only
where the datasheet or the firmware requires one function on one pin, and
the pin-capability table records exactly that).

Costed concessions, ordered by the fab profile: longer routes and more vias
on low-priority classes; widen targets relaxed toward the floor; role swaps
between interchangeable parts; track width and clearance down toward the
fab's standard minimum on low classes (never below the standard tier);
longer detours on analog and pair nets within their budgets; via-in-pad;
smaller via drills; clearances that need the fab's advanced tier; smaller
passive packages; more layers; blind or buried vias; a different part,
package or connector; a function moved to another board.

A tier is unlocked only when the current one has STALLED: the target
(required routing closure, placement DRC clean) is unmet and the last N
passes at this tier (default 3) produced no improvement larger than the
measurement's own run-to-run spread. The unlock and its justification go in
the verdict log; every concession taken is a cost line in the scorecard, so
a result always carries its price. Any concession with a monetary or
fabrication cost waits for the owner's answer. Never reach past the current
tier because a lower one is tedious; the cheap tiers are where most boards
close.


## Iterating on feedback

This is the core loop, not an afterthought - expect several rounds.

- **Verbal feedback** ("too spread out", "move the divider left"): translate to
  tactic terms, edit the script, regenerate, re-verify, re-render.
- **Hand-edited board**: the human edits the generated board file IN PLACE (it
  is committed after every verified regen precisely for this), so `git diff`
  holds the edits. **An editor moves a part; it does not move the copper the
  script DERIVED from that part's pads.** So a hand pass that slides parts
  reliably leaves pours short of their new pad edges, traces shorting pads
  that moved out from under them, and vias stranded where a pad used to be -
  none of it intended, all of it real. Fold the PLACEMENT and let the script
  re-derive every dependent shape; DRC the hand file first so you know which
  violations you inherited, and say which ones the fold fixed. A hand pass is
  also allowed to be unfinished (an autosave, a deletion that stopped
  halfway): where it is, complete it to the cell's own stated rules rather
  than reproducing a half state, and flag what you completed. Diff semantically, element-by-element (footprint
  positions/rotations, tracks, vias, polygon vertices - extract with pcbnew,
  don't eyeball text diffs). For each change, work out *why* before copying
  it: the why generalizes; coordinates don't. A change that looks like mess
  may be functional (see tactic 8's notches) - measure what it clears before
  "improving" it. Then fold the intent into the script, regenerate, and prove
  the output matches the hand state (see `references/discipline.md`, folding in a hand-edited board), diverging
  only where a stated rule supersedes the hand file. Then commit.
  **The geometry is the specification; the owner's words are a pointer to
  what to look for, not a claim to verify.** When a description and the
  measurements disagree ("I made it squarer" vs an aspect ratio that moved
  the other way), the hand file still wins and the loose adjective is not
  worth a round - measure what changed, extract why it helps, fold it. Spend
  the scrutiny where it pays instead: on whether the edit disturbed
  something electrically load-bearing (a hot loop, a Kelvin tap, a sense
  injection point). Flag that; never silently correct it.
- **Generalize every lesson**: each fold-in should end with the *why* recorded
  as a role-based tactic (in this skill or the project's intent doc), so the
  next layout starts smarter.


## Folding in a hand-edited board

1. Extract, don't transcribe: dump placements/tracks/vias/poly vertices from the
   hand board with pcbnew into script literals. Express pad-drop vias as
   `stitch`/`drop_via` so they regenerate from pad positions.
2. Copy the hand board; strip its copper (tracks, vias, poly shapes - collect
   lists first, see gotchas); run the script against the stripped copy.
3. Machine-compare copy vs original at 0.01mm: footprint (ref, x, y, rot)
   sets; track (net, width, endpoints) multisets; via (net, x, y) multisets;
   polygon vertex sets per net. Use multisets (Counter) - set() hides
   duplicates, and duplicated copper is a real failure mode.
4. Require EXACT MATCH before regenerating the real output.
5. Record each change's *why* as a role-based tactic (skill or project intent
   doc) - coordinates don't generalize, reasons do.
