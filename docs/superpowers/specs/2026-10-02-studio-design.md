# placemat studio: a live view of a layout as it is made

Date: 2026-10-02
Status: design, for the user's review
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
4. **Compare.** When a resolve ends, the page holds the previous plan beside
   it: moved items are marked with a ghost of their old place and an arrow,
   new and lost findings are listed, and the score's change is shown.

Transport: Server-Sent Events from the Python standard library's HTTP server
(one direction is enough; edits go back by plain POST). No new Python
dependency.

### What the page shows

- **The board, 2D**, drawn from the same model `preview` draws (preview.py
  becomes the shared drawing source: the page draws the model's JSON, not an
  SVG file). Front, back (mirrored as seen from the front) or both. Pan, zoom,
  layer toggles (keepouts, courtyards, copper, links, congestion, labels) as
  `preview` offers.
- **The step list**, in placement order, with each step's note. Clicking a
  step zooms to its item; a slider replays the placement step by step.
- **Findings**, with a click to zoom to each one's place.
- **Hover a part**: its name, value, cell, face, rotation, how it was placed
  (decided, searched, slide), its links and their lengths.
- **Script, linked**: the script beside the board, read only in phase 1.
  Clicking a part highlights its declaring line; clicking a line highlights
  what it declares.
- **Who changed what**: each resolve is listed with the files that changed
  and their diff, so an agent's edit is seen as an edit, with what it moved.

### Editing (phase 2)

The script pane becomes an editor (a vendored CodeMirror build, no build
step). Saving writes the file; the watcher sees it as it sees any edit, so a
user's edit and an agent's edit take the same path and land in the same view.
If the file changes on disk while the pane holds unsaved text, the pane says
so and shows the difference before anything is overwritten; it never
overwrites an agent's edit silently.

A **Run** button runs `placemat run` on the script (write, DRC, render, a run
record), and its result (DRC by kind, the render) appears in the page. Runs
started elsewhere (an agent's `placemat run`) are picked up from
`.placemat/runs` and shown the same way.

### 3D (phase 3)

A 3D view built from the model: the board as a slab of its stackup thickness,
each part as its body box at its height (`Pm.Height` or its model's box),
copper as thin layers. three.js, vendored. The full 3D models stay
kicad-cli's job: a button exports and shows the written board's GLB on
demand, since that takes seconds to tens of seconds.

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
   the linked read-only script, the compare and the change log.
2. The editor and the Run button; runs from elsewhere picked up.
3. The 3D view from the model; kicad-cli GLB on demand.
4. The agent note channel.

Each phase is usable on its own. Phase 1 alone answers "I never see what
placemat is doing".

## Open questions for the user

1. Editing in the page, or keep your own editor and have the page watch?
   (Phase 2 can be left out.)
2. How soon is 3D worth it over a good 2D view?
3. Should the Run button be there, or should a full run stay an agent's or
   the terminal's?
4. Any need to view from another machine (another host on the LAN, a tablet)?
   That needs authentication beyond a local token.

## Verification

- A script edited on disk is shown re-resolved within the replay time plus
  `debounce_ms` (target: under 2 s for a late-part change on the large test
  board; measure and report).
- Steps arrive in order and the final page matches `placemat preview` of the
  same script (same items, places, findings).
- A change mid-resolve cancels it; no stale plan is shown as current.
- Moved items in the compare equal the differences between the two plans.
- A file changed on disk under unsaved editor text is never overwritten
  silently.
- Clicking a part selects its declaring line, and the reverse, on a real
  board's script.
- The server binds only to 127.0.0.1 and refuses requests without the token.
- No new Python dependency; vendored JavaScript is MIT or similar, with its
  licence beside it.
