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
  list share one set of positions: the placement steps (one per item the
  board draws), the copper steps and the cutouts, in order. A copper step
  draws the copper ops it laid (the step's `copper` indexes) and a cutout step
  the hole it cut (its `loop`); copper no step laid shows with the last
  position. Keepouts and the other steps that draw nothing are listed apart
  and are not positions. A step is coloured by its kind and opens into the
  same labelled sections as a part's card. Dragging
  shows steps 1..k, changing only the groups between the old and the new
  position; play advances at a steady rate from the clock and stops when a
  new resolve starts.
- **Findings**, grouped by kind with counts, with a click to zoom to each
  one's place. A finding's `severity` (notice, warning, critical; absent
  means warning) groups them and filters them when any carries one; each row
  keeps a slot for a fix action.
- **The legend** beside the board (a sheet from a button on a phone) is the
  colour key and the switch for each kind of thing: parts, copper per layer
  (with "only"), vias drawn as rings with their drill, links within / over /
  without a limit, keepouts and reserved areas (each expandable to one row
  per region), findings, congestion, changes. A link is drawn from the pad of
  the part it was declared on to its partner pad with an arrow, coloured by
  its limit. Designators are off until switched on; the tooltip and the
  selected-item card carry the name, value, kind, module, face, rotation, how
  it was placed, links with their kind and limit, findings, and for a keepout
  its layers, excludes and allow. A part offers "select its module", which
  lights all the module's parts. Distances, areas and angles show units.
- **The board's name** is the one placemat knows it by (the `.zen` name), the
  first line of the script's docstring is its subtitle (a leading "<name>:"
  removed), the folder's name stands in when there is no name.
- **The script** has a view of its own at the full width, with Python syntax
  colours. Its selector lists the project's layout scripts: Python files that
  call `board.` as they load and that `find_board` resolves; helper modules
  are not listed, their changes still show in the Compare line diff. Choosing
  one POSTs `/switch` (token required, a listed script only) and the studio
  watches and resolves that script.
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

### Live channel (phase 2)

Decided by the user, 2026-10-03, replacing the progress log file this section first had:

**The studio reads only structured data, never log text.** Anything it shows about a command comes from a record
(`run.json`, an explore's result file) or from the live channel's JSON events. It does not parse a command's printed
lines or `worker.log`.

**Records stay records; live state is ephemeral.** `run.json`, and an explore's result (which keeps a summary of every
variant: seed, score, measures, the focused items' placements and the order they were placed in, and which variant was
kept), are written when a command ends and read afterwards, so what was tried can be browsed later. Nothing live goes
through a file.

**Live state goes over a local socket** (Linux and macOS):

- Each studio listens on a Unix socket in its project, `<project root>/.placemat/studio/<pid>.sock` (the project root
  as `studio.project_root` finds it; where that path is too long for a socket address, a short path under the
  temporary directory, named in the registry), and writes a small registry entry beside it, `<pid>.json`: pid, socket,
  started, address, the script it watches. Both are removed when it exits; an entry whose pid is dead is removed by
  whoever finds it.
- Every placemat command that resolves a board (`run`, `preview`, an explore inside them, `route`, `check`, anything
  that calls `Board.resolve`) looks for studios of its project the first time it resolves and, if there are any,
  connects to all of them and sends newline-delimited JSON: `hello` (command, pid, script, arguments, started); the
  events the studio's own worker sends (`board`, `item` per settled step with its copper or cutout, `begin` and its
  phases); a `plan` event with the finished plan; for an explore, `explore` (the plain placement, the focus, the
  budget, the jobs), one `variant` per finished variant and `explore_done`; then `done` (the record's path) or
  `error` (message, file, line). Not restricted to the script a studio watches: any command in the project reports.
- A command is never in the way. With no studio there is one directory check, once. With one, a sender thread with a
  small bounded queue takes the events: a full queue drops the event, and a socket that goes away is dropped
  silently. Measured: the bench at `--jobs 2` unchanged with no studio, a resolve with one listening within noise.
- A command that dies without `done` is a closed connection; the studio shows it as lost, with the last step it
  reported. The internal resolve worker is the studio's own process and does not use the channel; the channel would let
  it move to an external `placemat preview` process later (not in this round). A worker crash is its lost pipe and
  the last step it reported; the faulthandler traceback is optional detail only.

**The page's Runs view** lists the live commands from anywhere in the project (and the recent finished ones, from their
records): command, script, pid, elapsed by the server's clock, state. A toast says when one starts ("explore started:
Core_layout.py, by pid 4312"); it opens that command. Opening a live resolve or run shows its streamed steps on the
board, in place of the studio's own plan until closed, without disturbing the studio's own watch. Opening an explore
shows the explore view:

- the variants as they finish, with a plot of score against time and the best so far marked;
- each variant as a diagram over the plain placement (the focused items at their plain spots, drawn again where the
  variant put them), and a step through the variants in order or by score;
- the variant the explore kept (`--accept`) marked;
- **live** (the user: "show a diagram of explore placements as it goes ... obviously not all of them"): the latest
  variant over the plain placement, replaced as new ones arrive at most `[studio] explore_fps` times a second
  (default 2); variants that arrive between frames are plotted, not drawn. The best so far stays drawn in its own
  colour beside the latest, with a strip of thumbnails of the last few drawn variants and the best, each clickable;
- **where it tried**: a density layer marking where each focused item landed across all variants so far.

Finished explores are browsed the same way from their result file.

**The studio's own Run button** is a command like any other: it starts `placemat run`, which reports over the channel,
and the page shows its live steps; the studio does not read its printed lines.

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
