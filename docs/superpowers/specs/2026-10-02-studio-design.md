# placemat studio: a live view of a layout as it is made

Date: 2026-10-02
Status: design, revised with the user's answers (2026-10-02)
Source: the user, 2026-10-02: "I never really see what placemat is actually
doing or how it's called because agents just adjust the layout files in the
back end and then eventually I see a kicad PCB file or a render. I'd love an
interactive web view in 2d or 3d that shows updates to the layout script in
as real time as possible, possibly even being able to edit the script
directly in the interface or watch as agent edits come in. Anything to speed
up iteration whether that involves input from myself or one or more agents."

## Problem

placemat's work is invisible until it is over. A script changes, a run takes
seconds to minutes, and what comes out is a written board, a render, or a
preview PNG an agent may or may not show. The user cannot:

- see the board change as the script changes, whoever edits it;
- watch a run place items one by one, with the reason for each spot;
- go from a part on the board to the line that declares it, or back;
- see what an agent's edit moved, beside what it was before;
- edit and see the result without a full run and a file to open.

What placemat already has, which this builds on:

- `placemat preview` places the board as a run does and draws the plan as SVG
  from placemat's own model (preview.py): outline, keepouts, parts per face,
  planned copper, links, pockets, congestion. No board written, no DRC, no
  kicad-cli: seconds.
- A run replays the previous run up to the first changed step (reuse.py), so
  a change to a late part costs seconds even on the large board.
- Every step settles with a note (placed where, why, what it refused); the
  console prints them as they happen.
- `script_fingerprint` (project.py) knows every file a script depends on: the
  script, the modules it imports, the lock.
- Each declaration knows the line it was declared on (`--focus-after LINE`
  uses it).

## Design

### The command

```
placemat studio <script> [--port N] [--no-open]
```

It starts a local web server bound to 127.0.0.1 and opens the browser on it.
The page shows the board and keeps it current. Settings, with defaults:
`[studio] port` (0 = any free port), `debounce_ms` (300), `open` (true).
One studio serves one script; a second script is a second studio.

### The loop

1. **Watch.** The studio watches every file `script_fingerprint` names, the
   board's placemat.toml files and the lock. A change (from the user's editor,
   the studio's own editor, or an agent) starts a resolve after `debounce_ms`
   of quiet. A change arriving mid-resolve cancels it and starts again.
2. **Resolve warm.** A worker process holds pcbnew, the cached generation and
   the last plan in memory, so a resolve skips start-up and replays the
   unchanged steps (reuse) as `preview` does. Nothing is written to the board,
   no DRC, no render.
3. **Stream.** As each step settles, the worker sends an event: the item, its
   shapes as placed (courtyard, body, pads by net, face), its step note, its
   findings, and its declaring line. Copper, links, congestion and the score
   follow when planned. The page draws each event as it arrives, so a resolve
   is watched, not waited for.
4. **Compare.** When a resolve ends, the page compares it with the previous
   one it showed, both ways the user asked for:
   - **lines**: a diff of the script (and of each changed file it depends
     on) between the two resolves, side by side, changed lines marked;
   - **the diagram**: moved items drawn as a ghost at their old place with an
     arrow to the new one, added and removed items marked, copper that
     changed drawn in both states, new and lost findings listed, and the
     score's change shown.
   The two halves are linked: selecting a changed line marks what it moved
   on the board, and selecting a moved item marks the lines that changed its
   declaration. The page keeps the last few resolves so any two can be
   compared, not only the last two.

Transport: Server-Sent Events from the Python standard library's HTTP server
(one direction is enough; edits go back by plain POST). No new Python
dependency.

### What the page shows

- **The board, 2D**, drawn from the same model `preview` draws (preview.py
  becomes the shared drawing source: the page draws the model's JSON, not an
  SVG file). Front, back (mirrored as seen from the front) or both. Pan, zoom,
  layer toggles (keepouts, courtyards, copper, links, congestion, findings,
  labels) as `preview` offers. Mouse: wheel zoom, drag pan. Touch: one finger
  pans, two pinch, a double tap fits; the board takes the gestures, the page
  does not zoom. A millimetre grid (major lines every 10 mm, labelled on the
  edges) covers the whole visible area at any pan and zoom.
- **The step list**, in placement order, with each step's item, how it was
  placed and its note. Clicking a step zooms to its item. The slider and the
  list share one set of positions: the placement steps, one per item the
  board draws, in order. Copper steps (fanouts, escapes, vias, pours) and
  steps that placed nothing are listed apart and are not positions. Dragging
  shows steps 1..k, changing only the items between the old and the new
  position; play advances at a steady rate from the clock and stops when a
  new resolve starts.
- **Findings**, grouped by kind with counts, with a click to zoom to each
  one's place.
- **Hover a part**: its name, value, cell, face, rotation, how it was placed
  (decided, searched, slide), its links and their lengths.
- **Script, linked**: the script beside the board, read only in phase 1.
  Clicking a part highlights its declaring line; clicking a line highlights
  what it declares.
- **Who changed what**: each resolve is listed with the files that changed
  and their diff, so an agent's edit is seen as an edit, with what it moved.

### A checked run, on request (phase 2)

No editing in the page for now (the user, 2026-10-02: not needed straight
away): edits come from the user's editor and from agents, and the page
watches and previews on every change. A preview already gives the placement,
each step's note, placemat's placement findings, and its own reuse record
(kept between previews, so the next one replays). What only a run gives:
the design checks (current-path, keep-out, loops; they read the written
board and its fills), KiCad's DRC, the score (it counts both), and a run
record (history, `best`, `placemat impact`).

So a **Run** button (the user, 2026-10-02: "a button to run properly is the
way to go with default behaviour being to watch the file and preview on any
change") runs `placemat run` on the script without the render (seconds plus
DRC), and the page shows DRC by kind, the checks and the score, and compares
the run with the last one as it compares resolves. Runs started elsewhere
(an agent's `placemat run`) are picked up from `.placemat/runs` and shown
the same way.

### Watching an explore (phase 2)

The user (2026-10-02): "I wonder if it's possible to view an explore session
as well to see what the agent is actually trying". An explore resolves
seeded variants of the focused items' spots and order in worker processes
(explore.py `explore`, `_work`): each variant comes back as (seed, score,
measures) on a queue, and only the best is reported or kept today.

- **A progress log.** Every explore (from `placemat run --explore`, `preview
  --explore`, by an agent or the user) appends one line per finished variant
  to `.placemat/views/explore/<id>.jsonl`: the seed, its score and measures,
  and the focused items' placements (key, position, turn, face) and the
  order they were placed in; the first line holds the plain placement (seed
  0), the focus, the time budget and the job count. Regenerable output,
  under `.placemat/views/` like the other views.
- **The page tails the log**, live while the explore runs and afterwards:
  - the variants as they finish, with a plot of score against time and the
    best so far marked;
  - each variant as a diagram diff against the plain placement (the focused
    items' ghosts at their plain spots, arrows to where the variant put
    them), and a step through the variants in order or by score;
  - the variant the explore kept (`--accept`) marked, and what it moved.
  - **live, while it runs** (the user: "show a diagram of explore placements
    as it goes ... obviously not all of them"): the board shows the latest
    variant's focused items over the plain placement, replaced as new ones
    arrive, at most a few a second (a setting, `[studio] explore_fps`,
    default 2), so the drawing is watchable; variants that arrive between
    frames are logged and plotted, not drawn. The best so far stays drawn
    in its own colour beside the latest. A small strip of thumbnails keeps
    the last few drawn variants and the best, each clickable.
  - **where it tried**: a density layer over the board marking where each
    focused item landed across all variants so far, so the spread of what
    was tried is seen at a glance even when most variants are never drawn.
- Seeing what was tried and rejected needs nothing from the agent beyond
  running explore; the log is written whoever runs it.

### 3D (phase 3)

3D only with the parts' real 3D models (the user: it "only really makes
sense when we import models"); no box-only view. The models are the ones
the footprints name (`Footprint.models`: file, offset, rotation, scale),
resolved through KiCad's model paths. Two ways in, to decide when phase 3 is
specced in detail:
- the written board exported by kicad-cli as GLB (models included), shown in
  three.js: exact, but needs a written board and takes seconds to tens of
  seconds, so it follows a run, not each resolve;
- placemat loading each model once (STEP or WRL converted to a mesh, cached
  by file) and placing it at the resolve's position and turn, so 3D follows
  the live 2D view; needs a model converter, which may be a dependency.
The 3D view also gets the compare: a moved part shown at both places.

### Agents (phase 4)

- Agents keep editing files; the studio needs nothing from them to show
  their work.
- An optional note channel: `placemat studio note "<text>" [--at X,Y |
  --item NAME]` appends to `.placemat/views/studio/notes.jsonl`, which the
  page shows as a pin on the board and a line in the log, so an agent can
  say "trying c_cpu further west" where the user is looking.
- Several agents on one script are seen as successive edits; the studio does
  not merge or lock.

### What stays out

- No new placement or copper behaviour: the studio shows what placemat does.
- No editing by dragging parts. A dragged part is a coordinate, which the
  charter forbids; the page may offer "explore round here", which runs
  `preview --explore --focus-box` on the dragged box instead.
- No remote access: bound to localhost, with a random token in the URL.
- No cloud service; it runs where placemat runs.

### Charter fit

It serves the purpose (intent to board) by making the intent and its result
visible together. It is project-agnostic. Its tunables are settings. It adds
no form a script uses. It writes nothing to a board except through the
normal run, on request.

## Phases

1. Watch, warm resolve, streamed steps, the 2D board, steps, findings, hover,
   the linked read-only script, and the compare: a line diff and a diagram
   diff, linked.
2. The Run button (a run without the render) and runs from elsewhere,
   shown with DRC, checks and score, and compared; an explore's variants
   logged and watched as they finish.
3. 3D with the parts' real models.
4. The agent note channel.

Each phase is usable on its own. Phase 1 alone answers "I never see what
placemat is doing".

## Decided with the user (2026-10-02)

- No editing in the page for now; the page watches.
- A diff of lines and a diff in the diagram between the previous and the
  latest resolve.
- 3D only with real models.
- Watch and preview on every change by default; a Run button for a checked
  run (no render). No access from other machines.

## Verification

- A script edited on disk is shown re-resolved within the replay time plus
  `debounce_ms` (target: under 2 s for a late-part change on the large test
  board; measure and report).
- Steps arrive in order and the final page matches `placemat preview` of the
  same script (same items, places, findings).
- A change mid-resolve cancels it; no stale plan is shown as current.
- Moved items in the compare equal the differences between the two plans.
- The line diff and the diagram diff of two resolves agree: every moved item
  traces to a changed line or a changed file, and selecting one marks the
  other.
- Clicking a part selects its declaring line, and the reverse, on a real
  board's script.
- The server binds only to 127.0.0.1 and refuses requests without the token.
- No new Python dependency; vendored JavaScript is MIT or similar, with its
  licence beside it.
