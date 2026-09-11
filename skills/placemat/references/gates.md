# The loop, and the gates

How a pass is run, what it measures, and what has to be true before a board is
published. Read when running or reading a pass - round steps 7 to 10.

## The fast loop

A placement pass is judged three ways, and they cost three different
amounts. Spend the cheap ones freely and the expensive one rarely:

1. **Every move (seconds):** the airwire measure. Ask the oracle what a pose
   costs before and after; a move that lengthens the ratsnest or adds
   crossings is not worth a router run. The script itself is the next cost:
   run it with renders off (`placemat round` does this unless a pass is
   recorded or asked to render; renders are most of a script's run time).
2. **Every pass (under a minute):** the placement gates - occupancy, DRC, the
   declared links, the airwire line - `placemat round`'s default. This is the
   loop; a session makes many of these. The link line is the one that says
   whether the adjacency went where it was asked to go: it reports the
   heaviest tier declared and the worst length reached in it, so a constraint
   that lost its room shows up as a number in the pass it happened, not as an
   unexplained routing failure three passes later.
3. **When the airwires say a move helped (minutes):** `placemat trial`, run
   on the layers the stackup calls signal layers and only once that stackup's
   planes exist - a closure number from a board still carrying its rails and
   returns on the signal layers is not that board's number (round step 2).
   The QUICK trial runs the router's main round only (its reconciliation
   rounds cost most of the run and rarely change the result); it is the number
   to iterate on. The FULL trial is the recorded evidence: run it to commit a
   pass, not to test one.
   **Read WHY each net is open before spending another pass**, not just how
   many, and take that from the router's STRUCTURED output rather than its log
   prose: a modern router records its own verdict per net (what it judged, at
   what grid and clearance) and names the copper that was in the way. Parsing
   sentences for it is fragile and, worse, invites a heuristic like "few
   iterations means boxed in" - which is wrong in both directions, since a net
   can search hard and still be boxed, and can fail instantly for want of a
   rippable blocker without being boxed at all. Record the iteration count by
   all means; do not classify with it.
   The classes call for different work. A net BOXED AT A TERMINAL is held by
   its own pad's neighbours, so no placement move frees it - the fix is the
   cell's escape, the pad pitch or the routing grid. A net BLOCKED BY COPPER
   names what is in its way, which is a placement or routing-order problem and
   the one another pass is for. A MULTI-PAD net short of pads has a route and
   an unreached pad, named. Chasing a terminal failure with placement is the
   most expensive way to learn this distinction.

Pass records carry the timings of every step; when a pass is slower than
this, read the record before adding another run.


## Verification gates

- Real DRC, zero violations - except, for a standalone module fragment:
  `invalid_outline` (no board edge yet), dangling/unconnected on plane-drop
  vias, and dangling on edge-stub handoffs. These allowances are PER-NET, not
  blanket: a dangling via is expected only on a net that has a board plane (or
  is a documented strap landing) - on any other net it is a defect the bucket
  must not hide.
- **On a BOARD that allowance is void.** A fragment's drop dangles because
  there is no board yet; on a board the same finding means the plane or the
  trace that should pick it up was never drawn, and a dangling via there is
  outstanding work, never an accepted bucket. Count it, attribute it to the
  cell and net that owns it, and drive it to zero - the only survivors are
  landings the board deliberately leaves for a later strap, named as such.
  Filtering the bucket is how a board keeps dozens of decorative drops and a
  stack whose inner planes were never drawn: run the stamp-contract check
  (does every cell's drop land, does every declared copper layer carry
  copper?) as a hard gate in the pass, not as a report to read later.
- **Check the board is CURRENT before working on it.** A cell reaches a board
  only when that board is generated from empty, so a board placed before its
  cells were last laid out is stale and says nothing: it opens, it passes DRC,
  and its own geometry asserts fail only once someone regenerates. Ask the
  question first (the board records which fragment version it was placed
  against), because the answer changes what the session is - a stale board's
  first job is to take the new cells and re-verify, not to make the change that
  was asked for. The same check run the other way is a fragment edit's blast
  radius: every board stamping that cell is now stale, and a module round should
  say so rather than leave it to be discovered.
- A declared link limit is a hard gate, at any weight. The pass runner reads
  the achieved length of every declared link and fails the pass on one that
  missed its stated limit, naming both endpoints and the miss. A link with no
  limit is reported and not enforced - which is the right default, since the
  length a circuit needs is a property of the circuit - so state a limit
  wherever the datasheet or the topology gives you one, or the weight can only
  ever be a preference the placer is free to spend.
- Judge a pass against the one before it, not in isolation: the runner
  compares the two records and prints what moved (unconnected, airwires,
  crossings, DRC buckets, unlanded drops, closure). A number with no
  predecessor is not evidence, and "nothing moved" is itself a result worth
  seeing before another idea is spent.
- Regenerate from scratch before applying a script - incremental layout flows
  duplicate copper if you re-apply onto an existing output. Regenerating must
  be CHEAP TO REVIEW as well as correct: if the generator reassigns item
  identity (UUIDs) or reorders its output on every run, then a regeneration of
  an unchanged design produces a diff of thousands of lines carrying no
  information, and worse, one that hides the lines that do. Check it - generate
  the same design twice and diff. If it churns, fix it at the GENERATOR (seed
  its identity, order its output) rather than avoiding regeneration or
  post-processing the file: a downstream canonicaliser fights the tool on every
  run, and the identity the generator already computes for its own bookkeeping
  is usually the value it should be writing.
- Two-sided boards with stamped cells: EVERY HOLE PUNCHES BOTH FACES -
  vias, THT/NPTH component pins, mounting holes. Each must miss the other
  face's pad map (foreign-net landing = hard fail; same-net = flag unless
  an intended merge - and filling changes nothing electrically: the barrel
  is copper end to end) AND must miss the other face's COMPONENT BODIES.
  That second one is an assembly constraint DRC is silent about: a THT
  pin and its solder fillet occupy the far side, so an SMD part cannot sit
  over them even where no copper clearance is violated. Audit both classes;
  a courtyard-only check misses the
  first and a copper-only check misses the second. A cell's internal via field moves only with the
  cell - cross-face collisions are solved by JOINT placement search
  across both faces, never by packing each face alone. Run the
  cross-face via-vs-pad audit as a standing per-generation gate. A cell OWNS
  ITS UNDERPRINT, and the rule is asymmetric: a cell that ROUTES on its
  far layer (relief lanes, local straps) reserves territory - its real
  far-layer copper extent blocks opposite-face placement - while a cell
  whose far-layer presence is only via lands reserves confetti (point
  keepouts). Model each cell's true far-layer geometry; a uniform rule
  is wrong in both directions.
- Diff-pair nets must end `_P`/`_N` (uppercase, same base name) or KiCad will
  not pair them. A termination's internal nets are series bridges - single-ended
  by topology; give them the pair's net class so widths match.
- Render and look before declaring done.


## Testing and publishing

A layout script is a Python program, so it is TESTED like one - and the test
entry point is the only one: `uv run pytest`. Markers separate the costs
instead of a second command, because two entry points means two things to keep
in step and one of them is always stale.

    uv run pytest                    the units. No board, no toolchain,
                                     under a second - this is the inner loop
    uv run pytest -m board           build a board and put it through the gates
    uv run pytest -k links           one question in isolation ("did the
                                     adjacency go where I asked?")

**A TEST NEVER WRITES THE TRACKED BOARD.** It builds into the pass's own
directory and asserts on that. The board under `layout/` is a RELEASE: it is
what a person opens, hand-edits and commits, and what the next fold-in diffs
against. Publishing is a separate, deliberate step that the gates gate:

    <pass runner> <board>.zen --label <name> --publish

and it REFUSES when a gate failed. Publish only after the tests pass; a build
that fails its gates is evidence, not a release. The order is: edit the script,
run the tests, look at the renders, publish.

Two rules for writing the tests, because both failure modes are common:

- **State an INVARIANT, never a coordinate.** A test that asserts positions
  breaks every time the layout legitimately improves, so it gets deleted, and
  then nothing is tested. Assert the property the callers rely on: a 45 stays
  inside the box its endpoints make; a final leg rides the destination pad's
  axis; a declared link is inside its limit; no copper lies outside the
  outline. Those hold across every good layout and fail on exactly the bad
  ones.
- **Test the PRIMITIVE, not only the board.** Every placement and copper bug
  this harness has had lived in a primitive - a 45 that encoded a direction, a
  seed that could not see a declared link, a drop offset measured against a
  position the part later left. Each was found by a five-minute board pass and
  a DRC dump; each is four lines of test on an empty in-memory board or a small
  real cell fragment that loads in milliseconds. A primitive that needs a
  whole board to exercise is a primitive nobody exercises.


## The test environment

`pcbnew` ships with the system KiCad install and is not a PyPI package, so the
environment is PINNED to the interpreter that carries it and inherits its
site-packages. The KiCad AppImage interpreter has no pip and cannot host pytest;
it is not the interpreter for tests.

    uv venv --python "$(which python3)" --system-site-packages
    uv sync --group dev
    uv run pytest

A pass BUILDS into its own directory under the work root and leaves the tracked
board alone. Two separate reasons, and both were live faults before the split:

- a pass that generated in place tore the tracked directory down for its whole
  run - minutes during which the file on disk is a board with no outline and
  every part at its netlist position, which is indistinguishable from a broken
  layout to anyone who opens it mid-pass;
- and a pass that promoted its own output would make every experiment a
  release, including the ones that fail their gates.

So the board under `layout/` changes only on `--publish`, which refuses unless
the gates passed. The build stays in the pass directory either way, which is
where a render or a failure screenshot comes from.

The save itself is atomic - written beside the target and moved into place -
so even a script run by hand cannot leave a half-written board where a person
is looking.


## Pass costs and runner modes

The costs of a pass, from cheapest to dearest: the airwire measure (well
under a second), DRC, `placemat occupancy`, the script (its two renders are
most of its time), the quick routing trial, the full routing trial. The full
trial's extra time is the router's reconciliation rounds, which re-run the
failing nets against the finished board and rarely change the result.

So `placemat round` has three shapes:
- `placemat round <zen> --label L` - gates + airwires, no renders: the iteration
  loop. The generation is cached by input hash, so a pass that changes only the
  script reuses it; `--fresh` forces a new one and is the right move whenever
  the inputs moved or the cache is in doubt. With a deterministic generator
  that costs the generation's time and nothing else - it does not dirty the
  board file - so prefer it over reasoning about whether the cache is stale.
- `placemat round <zen> --label L --trial --quick` - plus the one-round trial:
  the closure to iterate on. Quick closures compare with each other, not
  with recorded full ones.
- `placemat round <zen> --label L --trial --record` - the full trial, renders on,
  full record kept under the pass's own work dir: the round's evidence.
`--render` renders without recording. The router itself is not modified:
`placemat trial-round` runs its source with the reconciliation switched
off.

The cell settler and compactor measure the moving cell once and slide its
boxes per candidate (the exact copper test still reads the live shapes),
so a settle search is seconds, not tens of seconds; nothing in a script
should re-measure a cell per candidate.


## A cell reaches a board only at generation

A module's layout is applied to a board when that board is generated from an
EMPTY directory, and at no other time. The generator stamps a fragment onto
footprints that are NEW in that sync; where the parts already exist it leaves
them alone, deliberately, because re-applying a fragment to placed parts would
move them. So:

- re-running the board script does not pick up a changed cell (the script places
  what is already on the board),
- an incremental generation onto an existing board directory does not either -
  it updates footprints and nets and keeps the old cell copper and placement,
- only `rm -rf <board layout dir>` then generate does.

The consequence is a board that goes stale SILENTLY. It still opens, still
passes DRC, and its own geometry asserts - the ones that encode "this cell is
this size, and my rows are packed against it" - fail only when somebody finally
regenerates it, often months later and usually in the middle of unrelated work.
Three boards in this project sat in that state at once.

So a board RECORDS what it was placed against: a hash of each cell fragment,
written into the board file itself on save, so it survives a checkout and can be
checked without regenerating anything. Check it before working on a board and
after regenerating a fragment - a fragment change's blast radius is every board
that stamps that cell, and the check names them.

The pass runner needs no special handling: its generation cache is keyed on the
fragments too, so a changed cell forces a fresh generation on the next pass.


## Regenerating a board

Some board generators (e.g. Zener's `pcb layout`) are incremental - running the
layout script onto an already-scripted output duplicates copper. Always
regenerate the board file from source (delete/move the old output first), then
apply the script once.

A regeneration should cost time and nothing else. Two generations of an
unchanged design ought to be byte-identical; if they are not, the generator is
minting fresh identity (UUIDs) or emitting in an unstable order, and every
regeneration then rewrites the tracked board file for no reason - which also
means an edit's real diff is buried in the noise. Test it with two clean
generations and a diff, and fix it in the generator: seed its UUID source, key
each managed item on its own stable identity, and let the emission order follow
from that. Both symptoms usually share one cause, since a writer that orders
items by UUID inherits whatever randomness the identity has.


## Verification

- `kicad-cli pcb drc --format json --output out.json board.kicad_pcb`, then read
  the JSON - never approximate DRC with bounding boxes.
- DRC a board file WITH its `.kicad_pro` in the same directory: without it,
  kicad-cli falls back to KiCad default rules, not the design's netclass
  floors - a hand file can pass its owner's standalone DRC while carrying
  real sub-floor pairs. An independent all-pairs
  clearance sweep is the belt to DRC's braces.
- Expected artifacts for a standalone module fragment: `invalid_outline` (no
  board edge yet), `via_dangling`/`unconnected_items` for plane-drop vias (the
  board's planes complete them). Everything else is real.
- Render for eyes: `kicad-cli pcb render --side top --background opaque
  --quality high -o out.png board.kicad_pcb`. Look at it before declaring done.


## Proving a script refactor

A refactor that must not change a layout is proved on a fresh generation, not
by eye: generate once, run the old script on a copy and the new script on
another, then compare the two saved boards block by block with UUIDs dropped
and coordinates rounded to the nanometre (an element diff that only counts
tracks misses a moved label or a nudged reference). Run both sides with
asserts stripped so a pre-existing failing check cannot mask the comparison,
and save the board from the exception handler when a script stops early, so
two versions that stop at the same line are still compared up to it. A
script that fails at HEAD is reported, not silently repaired during the
refactor.
