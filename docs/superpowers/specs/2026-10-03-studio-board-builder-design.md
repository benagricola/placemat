# Studio board builder

Date: 2026-10-03
Status: design, revised with the user's answers (2026-10-03)
Source: the user, 2026-10-03, condensed: a studio feature to build a layout for a new board from its `.zen` file. The
outline comes from simple shapes (circles, polygons, rectangles; anything more complex is a pain). A list of the
modules and components to click and place: fixed by intent (the middle of the top edge, say), or searched, or
something else; fix a few, then a button searches all the rest on the whole board. It writes the layout script as it
goes. Select an unplaced part, then select what to place it near and how: an intent-based editor in the web UI.
New boards first, editing existing scripts later ("that would be really cool").

Builds on `2026-10-02-studio-design.md` (the studio) and `2026-10-02-finding-suggestions-design.md` (the edit engine
and its one application path; branch `suggestions-core` for what is built). The suggestions spec's "Later work that
builds on this" names this spec.

## Problem

A layout script is the only place a board's intent lives, and writing the first one is the slow part of a board: read
the `.zen`, work out what is a part and what is a cell, pick the forms, type forty `board.place` calls, run, look,
repeat. The studio shows a script's board live but cannot write the script. A person who can see the board and the
parts list can say most of the first script in clicks: this connector goes on that edge, this capacitor goes beside
that pin, the rest can be searched.

What exists to build on:

- The studio's watch, warm resolve and streamed steps, the linked script view, the resolve history and compare.
- The suggestions engine (`script_edit.py`, branch `suggestions-core`): pure `apply(edit, text)` in the shared splicing editor,
  with `set_kwarg`, `remove_kwarg`, `set_arg`, `edit_list`, `insert_statement`, `remove_statement`, `set_constant` and
  `toml_set`; a digest check; an atomic write; the applied log with undo (`.placemat/applied.jsonl`); Show (diff, no
  write) and Try (a resolve of the edited text, no write). The studio endpoints for them are the studio branch's.
- `find_board` (project.py): the `.zen` beside a script that declares `Board`, `Project` or `Layout`;
  `runner.generate` runs `pcb layout` and caches the generated board.
- Every item in the plan knows its declaring file and line (`preview_json.declared_sites`), so a part on the board
  maps to a statement and back.
- A footprint no declaration places stays where the generator put it, and `layout._report_undeclared` raises a
  `setup` finding for it. That is the state every part starts in.

## Design

### The principle

**The builder is a front end for structured script edits.** Every click that changes the layout becomes an `Edit`
(or a list of them, as one multi-edit suggestion) that goes through the suggestions engine's one application path:
digest check, atomic write, applied-log entry. The watcher sees the file change and re-resolves, as it does for any
edit. The builder has no state of its own that the script does not hold: no sidecar file, no session model. After
every resolve the page reads what is placed, how, and relative to what, from the script and the plan, so an edit made
in an editor or by an agent shows up in the builder the same way.

- **The script reads as if written by hand.** The builder writes the forms a person would write, in the layout a
  person would use (below), with the script's own spelling, and a golden-file test pins the text byte for byte.
- **No coordinates.** The builder writes relations, edges and references. It never writes a `Location`, a numeric
  `Centre`, a `.local()` or `.offset()`, an `X()` or `Y()` with an offset, or `board.figure`. `Centre(...,
  coordinates=True)` exists as the user's escape hatch; the builder never sets it. `coordinates=False` is the default
  and is never written. A drag on the board may choose a target or a side; it is never read as a position.
- **Numbers are named constants.** A number the builder writes (a board size, a gap) is a constant with a comment
  saying where it came from: measured by placemat, or chosen by the user in the builder, said so. The call uses the
  name. This is `set_constant` from the suggestions spec, not a second mechanism.
- **Structured data inside, text at the edge.** The page, the server and the edit engine pass records (an intent, a
  target, an `Edit`), never source text, and nothing parses a sentence. The one text the user types is a `why=`
  note, and the board's name in the new-board dialog; both reach the script as an escaped string literal through the
  renderer (`{"str": ...}`).

### Where it lives

A mode of the studio page, "Build", beside the existing views. The server side is one module, `builder.py`: pure
functions from (plan, script text, a subject and a target) to a list of offered intents, each a suggestion record
(below). The page only draws what these return and sends back what the user chose. The module has no pcbnew or web
code, so tests call it directly, and a command line or an agent could call the same functions later (not in this
spec).

**A builder action is a suggestion without a finding.** It is the suggestions spec's `Suggestion` (text, `edits`,
`how`, `rank`, `id`, `digests`), registered in the resolve's suggestion table when the page asks for it. The existing
`POST /suggest/show`, `/suggest/try`, `/suggest/apply` and `/suggest/undo` then work on it unchanged, and one new
endpoint, `POST /build/offer`, returns the intents for a click. A request carries `{resolve, subject, target,
intent, params}`; `params` are enumerated values or a number or note the user typed, validated on the server. The
client never sends source.

## A new board

### Starting

The whole flow is in the web page; there is no command and no command-line entry for building. `placemat studio`
only starts the server (on a host, as it does today). With no script argument the page's start view lists the
project's layout scripts and, as a second group, "Boards with no layout": each `.zen` in the project that declares a
`Board`, `Project` or `Layout` and has no `<Board>_layout.py` beside it. Picking one starts the builder: the page
runs the steps below. `placemat studio <script>` for an existing script is unchanged. `[studio]` gains no setting
for this; the studio already finds the project's `.zen` files for the script list.

1. **Find the board.** `find_board` on the `.zen`'s folder, with the board's name passed as `wanted` when the file
   declares several (the same rule a script's `<Board>_layout.py` name follows).
2. **Generate.** `runner.generate`, as a first `placemat run` or `preview` does: `pcb layout`, cached beside the runs.
   It reports over the live channel like any command that resolves a board (the page shows its progress); a failure
   shows the generator's log tail. Nothing is written to the project except what `pcb layout` and the cache already
   write.
3. **Read the board.** The generated board gives the parts, cells and nets (the data `placemat parts` and `board.parts()`
   read). Nothing is placed yet: every footprint is an undeclared item.
4. **Facts** (below): the panel lists every fact `placemat facts` reports and which are undecided. The user decides
   each in a structured form; the edits go to the `.zen`, `fab-profile.json` and `placemat.toml`, and the board is
   regenerated after each batch. This is before any placement, as the skill's loop requires.
5. **The outline dialog** (below) collects the shape and its size, and offers a size suggested from the parts.
6. **Create the script**, in one write, from the skeleton with the outline in it. Until this write there is no script
   and nothing to resolve; after it, the script resolves as any script does. The file is never in a state that does
   not resolve (a skeleton with no outline would raise "the board has no size yet").
7. **Confirm the facts** for the new script. The confirmation is keyed to the script's path and its digest reads the
   script's own `plane()` calls, so it can only be recorded once the script exists. Until it is recorded, the part
   list's placement actions and "Search the rest" are disabled, with the reason shown.

### The file

Beside the `.zen`, in the board's folder, named `<Board>_layout.py` after `Board(name=)` (the script standard). If a
file of that name exists the builder does not start: it opens that script as an existing one (phase B3 below; until
then, the studio's ordinary read-only view). A skeleton:

```python
"""Demo: layout."""
from placemat import board

# The board's width, chosen in the studio's board builder.
BOARD_WIDTH_MM = 60.0
# The board's height, chosen in the studio's board builder.
BOARD_HEIGHT_MM = 40.0

board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM)
```

- The docstring is the board's name, a colon and the description the user typed in the dialog (optional; with none,
  `"""Demo layout."""`). It is the script's intent document, so the builder leaves it for the user and any agent to
  write; it does not describe placements.
- Imports are one `from placemat import board, ...` line: `board` first, then the other names in alphabetical order,
  as the repository's scripts write it. A name the builder needs is added to that line when its statement is
  inserted; a name no longer used is left (an unused import is harmless and removing it is a guess about the file).
- The constants block follows the imports; `set_constant` adds to its end (suggestions spec, "Numbers are named
  constants"). The decided placements follow the outline, then the searched block (below).
- Where a name is already bound, `set_constant` takes a counter, never overwrites.

## Facts

The skill's loop says to establish the board's facts before any placement and never to proceed on a default. The
builder does that in the page: the user states each fact in a form, the builder writes it to its home, regenerates,
and records the confirmation that `placemat facts --confirm` records. The state is read from the same function the
command uses (`facts.facts_of`, `facts.unconfirmed_reasons`), so the page and the command cannot disagree.

### The panel

A "Facts" view in Build, first in the new-board flow and always available after. Each fact is a row with a state:

| State | Meaning |
|---|---|
| decided | the value is written in the file that is its home; the row names the file |
| undecided | the value is a default nobody wrote down (a layer with no declared weight, a via type `fab-profile.json` names no tier for, no `min` section, a rise not set in `placemat.toml`) |
| flagged | `facts_of` raises a plane mismatch: a signal layer that carries a `plane()`, or a power layer with none |
| changed | decided, but different from the last confirmed digest |

The header counts them ("4 undecided, 1 flagged") and shows the reasons from `unconfirmed_reasons` as structured
rows. Nothing proceeds on a default: the confirm button is enabled only when no row is undecided and each flag has
been acknowledged. Leaving a default unwritten is not a decision; accepting a default is one, by clicking it, and it
is then written. "Changed" appears after a hand edit or a later builder edit moves the digest, and reopens the gate
below.

### The forms

Each fact is edited in a structured form with typed fields (a number in mm, a choice from a list, a net picker over
the generated board's nets). No fact is edited as free text.

| Fact | Form | Home | What is written |
|---|---|---|---|
| Layer roles and copper weights | a stackup table, one row per layer in order: copper rows (role `signal`, `power` or `mixed`; weight 0.5, 1 or 2 oz) and dielectric rows (thickness in mm; `core` or `prepreg`); the copper count follows `Board(layers=)`, a field in the form | the `.zen`: `Board(config=BoardConfig(stackup=Stackup(layers=[...])))` | the layer records with `thickness=` (the weight converted to mm by the mapping placemat already uses) and `role=`; a trailing comment on each value, "chosen in the studio's board builder" |
| Differential pair nets | a list of candidate pairs found from the net names (the `_P`/`_N`, `+`/`-` families) that the user ticks, plus a net picker to make any other pair; per pair: width and gap in mm. A tick box says "this board has no differential pairs" | the `.zen`: a `NetClass(name=, diff_pair_width=, diff_pair_gap=, nets=[...])` in `design_rules.netclasses` | one class per pair with exactly its two nets |
| Via types and their tier | micro, blind, buried: each `yes`, `no` or `if-needed`; the default drill and size | `fab-profile.json`, `via` | all three types named, `"no"` included, since a type with no tier is undecided |
| Fab minimums | track, clearance, drill, annular ring, via size, in mm | `fab-profile.json`, `min` | the `min` section |
| The rise | a number in degrees C | `placemat.toml`, `[check] rise_c` | the key, by the existing line-level toml edit |

The values are the user's. The forms start empty where the fact is undecided and prefilled from the file where it is
decided; the builder never prefills a number it invented. A candidate pair is a suggestion from a net name, shown as
such. Candidate nets and the layer count come from the generated board, as structured data.

Where a file does not exist the builder creates it: `fab-profile.json` beside the nearest `placemat.toml` above the
board, else beside the `.zen` (open question), and `placemat.toml` by the command's own rule (the nearest one above the
board, a new one beside it only when none exists).

### Editing a `.zen`

A `.zen` is Zener source, which uses Python's call and list syntax (`Board(...)`, `BoardConfig(...)`, `NetClass(...)`,
`load(...)`). The editor is the same shared splicing editor as for layout scripts, with a `.zen` dialect:

- **Parse.** Python's `ast` reads the file for node positions. A `.zen` that `ast.parse` cannot read (syntax only
  Starlark has) is shown read only with the reason; the facts it holds are listed from the generated board, and the
  other homes stay editable.
- **Locate.** The `Board(...)` call whose `name=` is the board, and inside it the path `config` -> `BoardConfig` ->
  `stackup` -> `Stackup` -> `layers`, or `design_rules` -> `DesignRules` -> `netclasses`. Each step must be a literal
  call or list; a `config=` that is a name, a merge or a function result is not found exactly once and the edit is
  refused, naming the expression. A missing branch is created in place (a `stackup=Stackup(...)` keyword added to the
  `BoardConfig` call), and the names it needs are added to the file's `load(...)` of `board_config.zen`.
- **Edit.** The same operations as for scripts: nested `set_kwarg`, `edit_list`, `insert` of a keyword or an element,
  as minimal span splices that leave every other byte of the file, comments included, as it was. A new keyword or
  element takes the layout of its neighbours.
- **Verify.** The edited text must parse; the `ast` outside the target node must equal the original's (the engine's
  masked check); the digest of the file at the plan must equal its digest on disk. After the file is written and the
  board regenerated, the page reads the fact back from the generated board (`facts_of`) and compares it with what was
  asked. A fact that did not take effect (the generator ignored a field) is reported, and an undo is offered.
- **Undo.** The write is an applied-log entry with the file's before and after text, one entry for the batch, as for
  scripts. Undo restores the text if the file still equals the entry's `after`, regenerates, and the gate reopens.
- Literals in a `.zen` follow the file's own convention (the netclasses there carry literal numbers); the comment on
  the value says where it came from. This is a deliberate difference from the layout script's named constants.

`fab-profile.json` is edited the same way with a JSON dialect: the value spans are found by a small scanner over
`json.JSONDecoder.raw_decode`, the target key's value replaced or the key inserted in the file's own indentation, the
rest of the file left byte for byte, and `json.loads` before and after must differ only in the target. A file that
does not parse is refused. `placemat.toml` uses `toml_set` as built.

A batch of facts is one multi-edit across the three files (and the digests of all of them are checked), then one
regeneration (`runner.generate`, which already regenerates when its inputs changed), shown on the live channel.
Regeneration before placement costs a generation; after placement it re-resolves the placements, and the page says so
before applying a fact edit on a board with decided items.

### The gate and the confirmation

- **The gate.** While any row is undecided, flagged and unacknowledged, or changed, the part list's placement actions
  and "Search the rest" are disabled, with the list of rows that hold it. The outline editor and the facts forms stay
  usable.
- **Flags.** A plane mismatch is not fixed by a fact (a plane is copper, declared in the layout script, which the
  builder does not write). The row says what is mismatched; the user either changes the layer role in the stackup
  table, or acknowledges that the plane will be declared in the script. An acknowledgement is a click in the page and
  is not recorded; the digest does not include mismatches, so a later `plane()` does not unconfirm.
- **Confirm.** The Confirm button records the digest of the facts for this script in the nearest `placemat.toml`,
  `[facts.boards] "<script path>" = "<digest>"`, through the same function `placemat facts --confirm` calls
  (`facts.write_confirmed`, refactored so its text edit is a pure function the apply path can log). It is an
  applied-log entry like any edit: undoing it removes the record and the gate closes.
- **After confirmation.** An edit to any fact, from the page, an editor or an agent, changes the digest. The page shows
  "changed" rows (the difference between the confirmed document and the current one, per fact) and closes the gate until
  the user confirms again. The run's own `facts` finding is unchanged.

## The outline editor

The first panel of Build, and always available after: the outline is one statement and a few constants.

| Shape | Statement | Constants |
|---|---|---|
| Rectangle | `board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM)` | `BOARD_WIDTH_MM`, `BOARD_HEIGHT_MM` |
| Rectangle, corners cut | `board.rect(width=..., height=..., chamfer=BOARD_CHAMFER_MM)` | `BOARD_CHAMFER_MM` |
| Rectangle, corners rounded | `board.rect(width=..., height=..., radius=BOARD_CORNER_RADIUS_MM)` | `BOARD_CORNER_RADIUS_MM` |
| Circle | `board.disc(diameter=BOARD_DIAMETER_MM)` | `BOARD_DIAMETER_MM` |
| Circle with a bore | `board.disc(diameter=..., hole=BOARD_BORE_MM)` | `BOARD_BORE_MM` |
| Slot (a stadium) | `board.outline(Slot(BOARD_LENGTH_MM, BOARD_WIDTH_MM))` | `BOARD_LENGTH_MM`, `BOARD_WIDTH_MM` |
| Polygon | `board.outline(BOARD_OUTLINE_MM)` | `BOARD_OUTLINE_MM`, a list of `(x, y)` pairs |

`api.md` allows `board.outline` to take a shape (`Circle`, `Slot`, `Path`); the slot row relies on that reading of
`layout.outline`, which implementation tests will confirm. Arcs in an outline (`Arc(to=, via=)`) are not offered:
the editor draws and edits straight legs only. An existing outline with arcs is shown and left alone.

**Dimensions are sizes.** The fields take millimetres. Dragging an edge handle on the preview changes the width or
the height; dragging the rim changes the diameter; the rectangle's origin is the board's top-left corner and does not
move, so a drag is a change of size by construction. A dragged value snaps to `[studio] builder_grid_mm` (default
0.5). Dragging is drawing in the page; the edit is made when the drag ends, as one `set_constant` that changes the
constant's value and keeps its comment.

**A polygon** is the one place the builder writes positions, because `board.outline` declares a shape by its
vertices. They are the board's own geometry, not a placement, and are a named constant list with a comment:

```python
# The outline's vertices, chosen in the studio's board builder: mm from the board's top-left, y down.
BOARD_OUTLINE_MM = [(0.0, 0.0), (60.0, 0.0), (60.0, 25.0), (35.0, 25.0), (35.0, 40.0), (0.0, 40.0)]
```

Vertices are typed or dragged (snapped to the grid), added by clicking a leg and removed by selecting one. The page
refuses a polygon with fewer than three vertices, a repeated vertex, a self-intersection or no area, before any
edit is made. Decided with the user: vertex numbers are fine, because the outline is the board's own shape.

**A suggested size.** The dialog offers a board area and size computed from the parts, and the user may change any
figure before the outline is written.

- **Inputs.** The total courtyard area of the generated board's footprints (a cell's members count; the footprint's
  box where it has no courtyard, as the placer's claim does); whether components go on one face or both (a switch in
  the dialog, default one); the maximum fill, a `[studio] builder_max_fill` setting; and an aspect ratio (width over
  height) for a rectangle, a field defaulting to `[studio] builder_aspect`.
- **Formula.** `area = total_courtyard_area / (faces * max_fill)`, with `faces` 1 or 2. The unfilled share, `1 -
  max_fill` on each face, is what is left for routing. For a rectangle `width = sqrt(area * aspect)` and `height =
  area / width`; for a disc `diameter = sqrt(4 * area / pi)`. The page shows the total, the face count, the fill, the
  area and the resulting figures, and the user can type any of them over (a typed size replaces the suggestion; a
  typed area recomputes the size). Two faces assume the parts split evenly between them, which a placement need not
  do; the figure is a starting size, not a check.
- **Rounded.** Sizes are rounded up to `builder_grid_mm`.
- **Default fill, from a measurement.** Of the fixture boards, one has a board outline and parts placed on it (the
  others are module fragments with a fit frame, or an unplaced generation, which have no outline to divide by). On
  that board the 258 footprints have 1690.7 mm2 of courtyard (1046.4 on the front face, 644.3 on the back) on a
  2551.7 mm2 outline: 0.66 of the board area over both faces, 0.33 per face averaged, 0.41 on the busier face. The
  default is `builder_max_fill = 0.33`, the per-face mean, so a two-sided suggestion reproduces that board and a
  one-sided one leaves more room than that board's front face had. This is one board; the setting exists so it can
  be tuned as more boards are measured, and the measurement should be repeated on the bench boards when the feature
  is built.
- **What is written.** The suggested size goes in as the same named constants as a typed one, with a comment that says
  how it was derived:

```python
# The board's width, suggested by the studio's board builder from the parts' courtyard area: 1690.7 mm2 on two
# faces, at most 33% filled per face, aspect 1.5.
BOARD_WIDTH_MM = 62.0
```

  A size the user typed over the suggestion says "chosen in the studio's board builder" as before.

**Holes and cutouts.** `holes=[Cutout(...)]` on the outline statement. The editor offers a round hole or a slot with
a name, sized by constants, and a place the cutout forms allow without a coordinate: on an edge
(`at=OnEdge(Edge.NORTH, along=Along.START)`, which puts a hole in a corner), or on a disc at a radius and a compass
bearing (`at=Polar(HOLE_RADIUS_MM, Edge.EAST)`, the radius a constant). `web=` is a constant when set. A hole placed
by anything else is the user's to write in the script. Written:

```python
MOUNT = Cutout(Circle(MOUNT_DIAMETER_MM), "mount", at=OnEdge(Edge.NORTH, along=Along.START))
board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM, holes=[MOUNT])
```

The cutout is bound to a name and used in `holes=`, as `api.md`'s example does. Editing the list is `edit_list`
(add, remove, move) on the `holes=` argument, plus `insert_statement` for the binding.

**Changing the shape** (rectangle to circle) is one multi-edit: the board statement and the constants it alone used
are replaced, the other statements are untouched. Placements that name an `Edge` of a rectangle stop being valid on a
disc (`OnEdge(Edge.NORTH)` is refused on a round board); the page lists them before the edit is applied, and the
edit is offered only with a choice for each (search it, or place it on the rim with `OnRim`). The outline kind
decides which forms the placement intents offer.

## The parts list

A panel listing what the generated board holds, grouped as the board holds it. It is built from the plan JSON's items
and the generated board's netlist, never from text.

- **Rows.** One per cell (a rigid group; its members are listed under it and are not placeable alone, as the skill's
  "Cells are rigid" says) and one per loose part. Columns: name, value or kind, cell, courtyard size, pad count,
  nets shared with the selection.
- **Status**, one of:
  - `unplaced`: no declaration places it. It stays where the generator put it, and is drawn in a tray beside the
    board, in the page only. The tray is a drawing of the undeclared items; it writes nothing and gives them no
    position.
  - `searched`: a `board.place(item)` with no `at=`, or with `Near`, possibly with a `board.link`; its spot is found
    by the placer, from its links.
  - `decided`: a place the plan reports as `fixed` or `edge` (`Freedom`), with the relation read from the script
    (`OnEdge(NORTH, MID)`, `Beside(J1, EAST)`). The relation is a structured record the page renders as a phrase.
  - `by hand`: a declaration the builder cannot read as one of its intents (a loop, a helper, a `Location`, a
    numeric `Centre`). Shown with its source line, read only.
- **Filters and order.** Status; a text filter on name and value; the order is the placer's rank (courtyard area, pin
  count) by default, since that is the order a person reasons about big parts first.
- **Counts.** `12 unplaced, 3 searched, 5 decided`. In Build the `setup` findings "no declaration places it" are
  folded into the unplaced count in the findings view, so a half-built board is not a wall of warnings; they remain in
  the run record.
- **Highlights.** Selecting a part marks, in the list and on the board, the parts it shares a net with, with the
  count of shared nets: the information a person uses to choose a target.

## Placing by intent

### The click flow

1. **Select the subject**: one or more unplaced or already placed items, in the list or on the board. Several
   unplaced items selected together offer the group intents (a row).
2. **Select the target**, with a chip row that says what a click picks, so the click is never ambiguous: Edge, Part,
   Pad, or None (leave it to the search). The default chip follows what is under the pointer.
   - Edge: a run of the outline. On a rectangle the four sides are `Edge.NORTH/EAST/SOUTH/WEST`. On a disc the rim,
     named by the nearest compass `Edge`, or the whole rim. On a shaped board a run is selectable when
     `board.edge(facing=)` can name it uniquely (the run's facing snapped to an `Edge`, or `outermost=True` where
     that makes it unique); a run that cannot be named without a number is greyed with the reason.
   - Part: a part or a cell, placed or searched. An unplaced one is not a target (it has no place to be beside); the
     page says why. A target that depends on the subject, directly or through a chain of relations, is not offered;
     the dependency graph comes from the plan's declared relations.
   - Pad: a pad of a placed or searched part, picked after zooming to the part (the page zooms when the Pad chip is
     active). A pad is written by net when the part has exactly one pad on that net, else by number, as the renderer
     does today.
3. **Choose the relation**: the server's offer for (subject, target) appears as a short menu, each entry a phrase and
   a preview of the statement. Choosing one shows the diff (Show: automatic, it is text only), and Place applies it.
   Preview (a Try resolve) is on a click, as the suggestions spec decided; it never runs on its own.
4. A side of a part is chosen by clicking the side of its box (north, east, south, west). That click picks an `Edge`
   value, not a point.

### The intents

A subject is a `Part("ref")` or a `Cell("name")`, written inline in the script's own spelling (a new script has no
spelling yet, so inline `Part("j1")`, as `api.md`'s examples write it; an existing script's spelling is found by
`script_edit.spelling`). Rotation is left out unless the user sets it or accepts the suggested turn (below); a
searched part tries all four, and edge and row placements turn the item by its outward side. Every statement below is a `board.place(...)` unless it says another
form; `item` is the subject.

| Intent | Subject, target | Statement |
|---|---|---|
| Searched from its links | any, none | `board.place(Part("c1"))` |
| On an edge, wherever there is room | part or cell, edge | `board.place(Part("j1"), at=OnEdge(Edge.NORTH))` |
| On an edge, at its start, middle or end | part or cell, edge | `at=OnEdge(Edge.NORTH, along=Along.MID)` |
| On a shaped board's run | part or cell, run | `north_edge = board.edge(facing=Edge.NORTH)` then `at=OnEdge(north_edge, along=Along.MID)` |
| On a disc's rim, facing out | part or cell, rim | `at=OnRim(Edge.EAST)`, or `at=OnRim()` for anywhere on it |
| At a disc's bore, facing in | part or cell, bore | `at=OnBore(Edge.NORTH)` |
| A row along an edge | several, edge | `board.row([Part("j1"), Part("j2")], Edge.WEST, align=Along.MID)` |
| A row along a part's side | several, part and side | `board.row(items, Edge.SOUTH, of=Part("u1"), align=Along.START)` |
| A ring round a disc | several, rim | `board.ring(items, radius=None, start=Edge.NORTH)` |
| Beside a part or cell | part or cell, part and side | `at=Beside(Part("u1"), Edge.EAST)` |
| Beside, flush to a corner of the side | same | `at=Beside(Part("u1"), Edge.EAST, align=Along.START)` |
| Beside, level with a pad | part, pad | `at=Beside(Part("u1"), Edge.WEST, align=PadRef(Part("u1"), "VDD"))` |
| Beside, on the side where a pad lands | part, pad | `at=Beside(Part("u1"), SideOf(PadRef(Part("u1"), "VDD")))` |
| Beside with a gap | any Beside | adds `gap=C1_GAP_MM`, a constant (below) |
| Close to a pad, searched | part, pad | `board.link(PadRef(own, ...), PadRef(Part("u1"), "VDD"), weight=LinkWeight.SHORT)` then `board.place(Part("c1"))` |
| Near a pad the netlist does not join | part, pad | `at=Near(PadRef(Part("u1"), "VDD"))` |
| In line with a pad, sliding along it | part, pad | `at=Centre(X(PadRef(Part("u1"), "VDD")), None)` |
| A quarter turn, suggested or picked | any placement with a decided spot | adds `rotation=90` (0, 90, 180 or 270) |
| Turned so a pad faces a side | any placement | adds `rotation=Facing(PadRef(Part("u1"), 3), Edge.NORTH)` |
| Turned with another part | any placement | adds `rotation=Turned(Part("u1"), 0)` |
| On the back, or either face | any placement | adds `face=Face.BACK` or `face=Face.EITHER` |
| Before the rest | any searched | adds `priority=Priority.HIGH` |
| Must place | any | adds `required=True` |
| A note | any | adds `why="..."` (the user's text) |

Notes on the table.

- **Close to a pad** is two statements, the link and the bare `place`, in that order (as `api.md`'s example writes
  them): the part stays searched, seeded from the link, and rides the target if the target is searched. `weight=` is
  `LinkWeight.SHORT`; a `limit_mm=` is offered only with a number the user typed, written as a constant. The own pad
  is the pad of the subject sharing a net with the target pad; where there are several or none the page asks the
  user to click one.
- **Near** is offered only where the subject and the target share no net, because `api.md` reserves it for what the
  netlist cannot say; where they share one, the offer is the link. `Near(Location(...))` is a coordinate hint and is
  never written. Its `radius=` is a constant when the user sets one.
- **Beside with a pad** writes the pad as a reference. If the subject's own pad is on a different net from the
  target pad, the page asks for the own pad and writes the tuple form `align=(own_pad, PadRef(...))`.
- **In line with a pad** (one axis a reference, the other `None`) is an intent `Centre`: no number is written. A
  two-axis `Centre` of references is not offered in the first version.
- **A row** takes the selection's order, which the dialog lets the user change; `gap=` is left out (courtyards
  touch, the default the skill sets) and a gap is a constant the user adds. A row on a shaped board's run is
  `board.row(items, north_edge)`. Binding the row to a name (`power = board.row(...)`) happens only when a second row
  asks to stand `behind=` it; the builder then adds the binding by an `insert_statement` with a `bind`.
- **Rotation, face, priority, required and why** are modifiers on a placement, edited by `set_kwarg` and
  `remove_kwarg` on its call. A priority is offered with a prompt for the reason, and the reason is written as
  `why=`.
- **Suggested turn.** For a placement that decides a spot without deciding the turn (`Beside`, an in-line `Centre`),
  the panel offers the four quarter turns, each with a measured figure, the number of ratsnest crossings the part's
  connections make with the connections among the components already placed, and marks the turn with the fewest.
  The user can pick another; with a tie the turn that is no `rotation=` at all wins. The count is taken on the plan:
  the part is held at its resolved place with its pads turned about its origin, and the ratsnest (`ratsnest.py`)
  is counted for each turn. That is a quick estimate that ignores the legality of the turned part at that spot; Try
  on a turn resolves it exactly and shows its own figure beside the estimate. The chosen turn is written as a literal
  quarter turn, as scripts write them, with the reason: `rotation=90, why="fewest ratsnest crossings of the four
  turns"`. The suggestion needs the part's place, so it is offered after the placement has been applied and resolved,
  as a second step (an edit of the same call, `set_kwarg(rotation, ...)`). Edge and row placements are already
  turned by their outward side and get no suggestion; a searched part tries every turn itself.
- **A cell** takes the same intents as a part. Its declared sides (`faces(outward=)`) are what the edge and row forms
  already use to turn it; there is no separate cell feature, and a cell's turn is suggested as a part's is.
- **Not offered**: `Location`, a numeric `Centre`, `Pin` on a point, `Polar` with a typed radius or bearing for a
  part, `Near(Location)`, a typed `along=` distance or `pitch=` (decided: intent only), a board-middle target (no form earns it), `board.figure`, `overhang=` (a
  distance past an edge, which needs a reason; a later increment writes it as a constant with a required `why=`).

### Numbers in intents

`gap=`, a link's `limit_mm=` and a `Near`'s `radius=` take a number the user types in the relation panel. Each is
written by `set_constant`:

```python
# The gap between C1 and U1, chosen in the studio's board builder.
C1_GAP_MM = 0.5
board.place(Part("c1"), at=Beside(Part("u1"), Edge.NORTH, gap=C1_GAP_MM))
```

Names follow the suggestions spec: the item and the keyword, upper case, the unit in the name (`C1_GAP_MM`), a counter
when the name is bound. The page requires a note for a gap, since the skill says every larger gap names what needs it,
and the note goes into the constant's comment as the user's words: `# The gap between C1 and U1: <note>. Chosen in
the studio's board builder.`

### The order of statements

Each region of the script has a rule, so the file reads the way a hand-written one does.

1. Docstring, imports, constants, the outline statement (and any edge bindings, `north_edge = ...`, which sit
   directly after it).
2. **Decided placements**, in the order the user made them. A statement is inserted after the last statement of this
   region (anchored on it, since `insert_statement` takes a target), so the file is a log of decisions and a
   `Beside` follows what it refers to. Firm items go down as declared, so this order is meaningful.
3. A blank line, then the **searched block**: `board.place(item)` for each item left to the search.
4. Other declarations a person adds (links, copper) stay where they are; the builder neither moves nor reads them
   beyond the links it wrote for a "close to" intent, which sit directly above their `place`.

Changing a searched item into a decided one is one multi-edit: remove its bare statement and insert the decided one
at the end of the decided region (decided with the user), so each region keeps its meaning. A decided statement can
be moved within its region later (`move_statement`, a new op below), since firm items go down as declared.

## Searching the rest

A button, "Search the rest", writes one plain `board.place(item)` per remaining unplaced item, and nothing else.

- **What is written.** `board.place(Part("r1"))`, with no `at=`: the placer seeds it from its links and, with none,
  takes a pocket (`api.md`, "The default is a bare `place()`"). There is no board-level search call; `[solve]` is a
  setting and is not the builder's. One statement per item, because a script declares one `place()` per item and the
  engine refuses loops.
- **Scope.** Every `unplaced` item by default, or the selection. Cells are placed as cells.
- **Order in the file.** Cells first in name order, then loose parts in natural order of reference (`C2` before
  `C10`). The order is for the reader: searched items are ordered by the placer (its rank, then link pull), so file
  order does not change the result. A single comment line above the block,
  `# Searched from their links.`, is the only text the builder writes there.
- **Face.** A checkbox, "either face", adds `face=Face.EITHER` to each. Default off (the front).
- **Priority.** None. `priority=` is a tier above the rank, the skill says to read the rank first, and a reason goes
  beside one; the builder offers it per item, after a resolve shows a part placed late (the step note says
  `rank 4/64`).
- **After it runs.** The resolve places everything it can. Items that did not place raise the ordinary `unplaced`
  findings, and their suggestions (the suggestions engine's) appear in the findings view; the builder's part list
  shows the item as `searched` with a mark, and selecting it offers the intents above to decide it.
- **One undo.** The edits apply together or not at all, as one applied-log entry.

Searching only some of the rest is the same button on a selection, and searching after fixing a few is the normal
order: decide the anchors, search, look, decide more.

## Editing an item the builder placed

The same panel opens on a placed item. The builder reads the item's declaration with `script_edit.read_intent` (a new
function: the inverse of the renderer, below) into a structured record, and shows it as a phrase with its parts
editable.

| Change | Edit |
|---|---|
| Another target or side | `set_kwarg(at, <new intent expression>)`; after phase 5, a nested `set_arg` on the `Beside` |
| The gap | `set_constant` (value) when the call uses a constant of its own, else a new one and `set_kwarg` |
| The alignment | `set_kwarg(at, ...)`; later a nested edit of `align=` |
| Another edge | `set_kwarg(at, ...)` for an `OnEdge`; `set_arg(1, ...)` for a row |
| Leave it to the search | `remove_kwarg(at)` (and its modifiers) |
| Take it off the board | `remove_statement`; the item is `unplaced` again |
| Take a member out of a row | `edit_list(remove, element)` on the row's members; a row of one stays a row |
| Reorder a row | `edit_list(move, ...)` |
| Add a member to a row | `edit_list(add, ...)` |
| Rotation, face, priority, why | `set_kwarg` or `remove_kwarg` |

- Until nested edits exist (suggestions phase 5), the builder rewrites the whole `at=` value from the record it read
  and the change. This preserves the rest of the call and loses only comments written inside the old `at=`
  expression, which the engine's masked check reports as part of the target; the diff shows it before it is applied.
- A constant the builder created and that no statement uses any longer is removed in the same multi-edit (a new
  `remove_constant` op below), so editing does not leave orphans.
- **A declaration the builder cannot read** (a form outside its vocabulary, a coordinate, a call in a loop or a
  helper) is shown as `by hand` with its source line, and the item offers only "replace by a relation", which is a
  `set_kwarg(at, ...)` toward intent. A change from a coordinate form to an intent form is allowed, never the reverse
  (suggestions spec, "`Centre` and `Location`").
- A hand edit made between two builder actions is not a conflict unless it touches a file the pending edit targets:
  the digest check refuses an edit made against a stale plan, the page marks the plan stale, and the user acts on the
  new plan.

## Undo and redo

- **Undo** is the suggestions spec's: the applied log is a stack, each undo restores the last apply's `before` text if
  the file still equals its `after`, otherwise it refuses and says so. The builder's actions are log entries of
  source `builder` with the intent's phrase as their label. Undo and redo are buttons in the Build header and keys.
- **Redo** is new. An undone entry stays in the log marked undone; Redo re-applies its `after` text if the file now
  equals its `before`. A new apply drops the redo entries. Redo lives in the apply module beside undo and is used by
  the page; the command line's `placemat apply --undo` is unchanged.
- **The first write is undoable** the same way: the file's creation is a log entry with `before: null`, and undoing it
  removes the file if it still has the text the creation wrote. Undo past it returns the board to "no layout".
- A multi-edit (a shape change, a search of the rest, a searched-to-decided move) is one entry, so one undo.

## Live feedback

Each applied edit changes the file, the watcher re-resolves, and the page shows the result as any edit's:

- The streamed steps place items as they settle; a replay of the unchanged steps makes an edit near the end cheap.
  Inserting an early decided placement changes the later searched ones, which is the visible effect of the decision.
- The part list's status updates from the plan as it settles.
- The **timeline** is the studio's resolve history, with each builder action as a row labelled by its phrase ("Place
  U1 beside J1, east"), its resolve time, and the findings it gained and lost (the existing compare). Selecting a row
  shows that resolve and the ghost-and-arrow compare against the one before. A timeline row is a view of a past
  resolve; undoing changes the file, and the timeline then gains the undo as a row.
- A resolve that fails (the script raised) leaves the last good plan, marked stale, with the error and its line, as
  the studio does. A builder action that produces one is flagged in the timeline and offered an undo.
- Show (the diff) is immediate; Try (a resolve in the overlay) is on a click. Neither writes.

## What it refuses

Each refusal is a message in the panel naming the rule, and nothing is written.

- A coordinate: a `Location`, a numeric `Centre`, `coordinates=True`, `.local()` or `.offset()`, an `X()`/`Y()` with
  an offset, `board.figure`, `Near(Location(...))`, `reach=` with a number. A request that would need one is not
  offered; the panel says which intent would, if the user's script is to write it by hand.
- A drag as a position. A drag on the board picks a target or a side, or changes a size in the outline editor; a
  dragged part is never a place. The page may offer "explore round here" (`preview --explore --focus-box`), as the
  studio spec already allows; that is a search, not an edit.
- A target that is unplaced, or that depends on the subject.
- A form the board refuses: `OnEdge` with a named `Edge` on a disc or a shaped board, `OnRim` on a rectangle, a
  `Beside` whose `align=` combination the form refuses, `Near` where the subject and target share a net (the link is
  offered instead).
- A target statement the engine cannot locate exactly once, a stale digest, a call that declares several items (a
  loop or helper), a value the script cannot import (suggestions spec, "The shared edit function").
- `coordinates=False`, `board.plane` for a pour, `Edge` or `Along` values that are not members of the enums.
- A fit-frame board (`board.rect(fit=True)`): its outline is derived from its content and the editor is read only.

## Existing scripts (phase B3)

The same panel, parts list and intents, on a script a person or agent wrote. The difference is that the script has
conventions to follow and statements the builder did not write.

- **Finding a declaration.** `declared_sites` gives `(file, line)` per item key. The engine's finder takes the call on
  that line whose function and first argument match; not found exactly once refuses. Sites for `rect`, `disc`,
  `outline`, `row` (key: its first member) and `block` (key: its anchor) arrive with suggestions phase 5.
- **Refusing loops and helpers.** A site shared by several items (`(file, line)` with more than one key) is `by
  hand`, as in the suggestions engine: an edit would move the others too. An unplaced part needs no declaration to
  find, so it is always addable; a placed one in a loop is not editable.
- **Adding a placement for an unplaced part.** An `insert_statement` after the right statement:
  1. after the statement that declares the target, when the intent has a target the script declares at module level
     (so a `Beside` follows what it names);
  2. else after the last module-level `place`, `row`, `ring` or `block` statement;
  3. else after the outline statement;
  4. never inside a function, loop or conditional: where the only placements are in a helper, the builder offers the
     placement as a suggestion to add at the end of the module and says why.
- **The script's own spelling.** The part is written as the script writes parts: a name the script binds (`U1 =
  Part("u1")`, even if unused) is used; a `Part("u1")` literal where the script writes literals; a script that mixes
  gets the literal. `script_edit.spelling` already does this for referenced items.
- **Following the file's habits.** Keywords on the line or on their own lines as the neighbouring calls do (the
  engine's layout rule for a new keyword), constants in the file's constants block or the shared module (the
  suggestions spec's scope rule).
- **Outline.** The editor works on `rect`, `disc` and `outline` calls whose arguments are numbers or one constant
  name each; a constant is changed in place (`set_constant`, which shows every use), and a computed size (`board.rect(
  width=A + B)`) is shown read only.
- **Coordinates already there.** An item placed by a `Location` or a numeric `Centre` is `by hand` and offers
  "replace by a relation". The builder never converts the other way.
- **A fragment or module script** (a cell's own layout with `fit=True`) has no outline to edit and its items are
  placed inside the cell's frame; B3 covers board scripts first.

## Dependencies on the suggestions engine

State as read on branch `suggestions-core` at d18f6a1: `script_edit.py` has `set_kwarg`, `remove_kwarg`, `set_arg`,
`edit_list`, `insert_statement` (a call after a target statement), `remove_statement`, `set_constant` and `toml_set`,
`spelling`, `undo` and a digest check. I read the module's function list and the two functions that matter here,
`_insert_statement` and `_render`; I did not run it.

| Needed by the builder | Where it stands |
|---|---|
| `set_constant` (board size, gaps, notes in comments) | built |
| `set_kwarg`, `remove_kwarg`, `set_arg` | built |
| `edit_list` (rows, holes) | built |
| `insert_statement` after a target statement | built |
| `remove_statement` | built |
| Digest check, atomic write, applied log, undo | built (`apply_suggestion`) |
| Studio endpoints: show, try, apply, undo | the studio branch's |
| Nested edits (a `Beside`'s `gap=` or `side`, a `Cutout`'s `at=`) | suggestions phase 5; the builder works without them by rewriting `at=` |
| Multi-edit (`edits` list, one entry, one undo) | suggestions phase 5; required, since a shape change, a searched-to-decided move, "close to a pad" and "search the rest" are multi-edit |
| Sites for `rect`, `disc`, `outline`, `row`, `block` | suggestions phase 5; required to edit the outline and rows |
| `Centre(coordinates=)` flag (4b) | needed so the builder can tell an intent `Centre` from a coordinate one (B3) |

New to the engine for this spec, each small and pure:

- **`create_file`**: the first write, from the skeleton, with the applied-log entry `before: null`; undo removes it.
- **`insert_statement` without a target statement**: an anchor that names a region (`after: {"region": "header"}`,
  `"constants"`, `"outline"`, `"decided"`, `"searched"`) found structurally (docstring, imports, the constants block
  the engine already finds, the outline call, the last placement), and a `bind` field so the inserted statement may
  be an assignment (`north_edge = board.edge(...)`, `MOUNT = Cutout(...)`).
- **`ensure_import(names)`**: adds names to the script's `from placemat import ...` line, `board` first and the rest
  alphabetical. The engine today refuses a form the file does not import; the builder needs to write the import
  with the statement, in the same edit.
- **`remove_constant`**: removes a constant assignment and its comment when no statement in the file uses it (or
  `remove_statement` extended to such an assignment).
- **`read_intent`**: `script_edit.read_intent(text, target) -> intent value | None`, the inverse of `_render` for the
  builder's closed vocabulary (the forms in the table above). `None` means "by hand".
- **Redo** in the apply module (above).
- **`move_statement`**: moves a statement within its region, for reordering decided placements.
- **Ratsnest count per turn**: a function returning the crossings for a part held at a place with each quarter turn,
  from the plan's ratsnest (`ratsnest.py`); a number per turn, no text.
- **`.zen` dialect** of the splicing editor: `ast`-located nested keywords and list elements in `Board(...)`,
  `BoardConfig(...)`, `Stackup(...)`, `NetClass(...)`, edits to the `load(...)` names, the masked check, and the digest
  and undo as for scripts. This needs the nested-edit pieces of suggestions phase 5, which the facts forms use from the
  first builder phase; they are therefore needed in B0, not later.
- **JSON dialect**: value-span splicing for `fab-profile.json` and the structural check by `json.loads`.
- **Confirm edit**: `facts.write_confirmed` split into a pure text function `confirmed_text(text, digest, key)` and the
  write, so the apply path logs the confirmation and undo can remove it.
- **Read-back**: after regeneration, `facts_of` compared with the requested facts; a mismatch is a refusal's report.
- **`skeleton(name, description, outline) -> text`**, the only generator of whole-file text, used by `create_file`.

`apply_suggestion` is split so the builder and the findings share its body: `apply_edits(edits, digests, dry_run,
label, source)` does the digest check, the edit and the write, and `apply_suggestion` calls it. This is a refactor of
the suggestions branch, not a second path.

## Settings

`[studio]` gains one setting, documented in `api.md`: `builder_grid_mm` (0.5), the snap of a dragged outline
dimension or vertex; `builder_max_fill` (0.33, measured as above), the most of a face the parts' courtyards may
fill in a suggested size; and `builder_aspect` (1.0), the width over height a suggested rectangle takes before the
user changes it. None is part of a run's id. Nothing else in the builder is a literal tunable; the offered gaps and
every fact are what the user types.

## Charter fit

- *Intent, not coordinates*: the builder writes relations, edges and references; the only positions it writes are
  the outline's own vertices for a polygon, named, commented and chosen by the user in the builder (decided). A drag never becomes a position.
- *A project-agnostic tool*: the builder, its tests and its golden scripts use generic names (`U1`, `J1`, `C1`,
  `SIG`). The comments it writes say "chosen in the studio's board builder", never a project's words.
- *Tunables are settings*: the grid, the maximum fill and the aspect are settings; no gap, radius, size or fact is
  defaulted in code.
- *Judged as KiCad judges*: the builder judges nothing; the resolve it triggers does. A Try shows what an intent does
  before it is written.
- *A new form must earn its place*: the builder adds no script form; it writes the existing ones.

## Phases

- **B0, engine prerequisites**: suggestions phase 5's multi-edit and sites, and the new engine pieces above
  (`create_file`, region anchors with `bind`, `ensure_import`, `remove_constant`, `read_intent`, redo,
  `apply_edits`, `move_statement`, the `.zen` and JSON dialects, the confirm edit). Independent of any UI; unit-tested on text.
- **B1, a new board, the first loop**: start from a `.zen` in the page, generate, the facts panel and the confirmation gate, the outline
  editor for rectangle and circle with the size suggestion, the parts list, the intents for edge, beside, searched and "search the rest", Show and Apply, undo and redo, the
  timeline.
- **B2, the rest of the vocabulary**: polygon and slot outlines, holes, rows and rings, links ("close to"), `Near`,
  in-line `Centre`, rotation with the suggested turn, `move_statement` to reorder decided items, face, priority, required, why, editing a placed item (whole `at=` first, nested edits
  once they exist).
- **B3, existing scripts**: reading a script written elsewhere, `by hand` items, inserting after the right statement,
  following the script's spelling and layout, the outline of an existing board.
- **B4, later**: keepouts (a region round a part, a clearance band on an edge), a row `behind=` another, `overhang=`
  with its reason, `Pin` against a pad's edge (a net tie), a two-axis `Centre` of references, between two pads.

Each phase is usable on its own; B1 alone writes a first script for a board.

## Testing

All tests use small synthetic boards and `.zen` fixtures with generic names, no project, board or part number. They
follow the suggestions tests' style (`tests/suggest_support.py`).

- **Golden scripts.** Each is a `.zen` fixture, a list of builder actions as data (a subject, a target, an intent,
  parameters), and the script text the builder must produce byte for byte: comments, blank lines, constant names,
  keyword layout and import order. Cases:
  - the skeleton for each outline kind (rectangle, chamfered, rounded, circle, bore, slot, polygon, with a hole);
  - one action per intent in the table, each on a fresh skeleton;
  - a sequence that builds a small board end to end (a connector on an edge, a regulator beside it, bypass capacitors
    "close to" its pads, a row, the rest searched), checked after every action: the text parses, `ast` outside the
    inserted node is unchanged, and the script resolves on the synthetic board with the expected status per part;
  - searched to decided (the move), decided to searched, removal, a row's reorder and member removal;
  - a gap, with its constant and comment, then changed, then removed with the relation (no orphan constant);
  - a shape change that invalidates an edge placement, with the listing and the choice.
- **No coordinates.** A property test over every golden script and every action the offer function can return,
  scanning the statements' `ast`: no `Location`, no numeric `Centre` axis, no `coordinates` keyword, no `.local`,
  `.offset`, `X`/`Y` with a second argument, `board.figure`, `Near(Location...)`. The only number literals allowed
  are inside constant assignments in the constants block, plus the quarter-turn literal of a chosen turn.
- **Size suggestion.** For a synthetic board with known footprint courtyards, the area, rectangle and disc sizes for 1
  and 2 faces, aspect ratios and fills equal the formula; sizes round up to the grid; a typed size replaces the
  suggestion; the written comment names the derivation.
- **Suggested turn.** On a synthetic board where one turn clearly cuts crossings, the four counts are as computed by
  hand and the lowest is marked; a tie offers no `rotation=`; the written call has `rotation=` and the `why=`.
- **Reorder.** `move_statement` within the decided region keeps every other byte; undo restores it.
- **Facts.** On a synthetic `.zen` (with a `Board`, a `BoardConfig`, netclasses and comments), each fact form's edit
  gives the expected text byte for byte, comments and layout outside the target untouched; a `.zen` with no `config=`
  gets the branch created and the `load` names added; a `config=` that is a name is refused; a `.zen` that does not
  parse is read only; after regeneration the read-back equals the request and a fact the generator ignores is reported.
  `fab-profile.json` edits keep the rest of the file byte for byte and refuse a file that does not parse; the rise goes
  through `toml_set`. The states (decided, undecided, flagged, changed) for each reason `unconfirmed_reasons` can
  give; the gate keeps placement and search disabled until nothing is undecided and each flag is acknowledged;
  confirm writes the digest `placemat facts --confirm` would write (the same function); a later fact edit makes rows
  "changed" and closes the gate; undo of the batch and of the confirmation restores the files and the gate.
- **Undo and redo.** Every action sequence, undone step by step, restores each earlier text byte for byte, the first
  undo removes the file; redo reapplies each; an edit made outside the builder between actions makes undo refuse and
  leave the file alone.
- **Offers.** `builder.intents` for pairs of (subject, target): an unplaced target gives none; a target that depends on
  the subject gives none; `Near` appears only for items sharing no net, the link only for items that do; edge intents
  differ per outline kind; a shaped board's ambiguous run is greyed with its reason.
- **One path.** The builder's apply goes through `apply_edits` (a test replaces it and sees both builder and findings
  call it); the four suggestion endpoints accept a builder suggestion; the client's request carries no source text and
  a body that names more than a resolve, an id or the documented params is refused.
- **Start.** A `.zen` with no script starts the builder; one with a script does not; the file is created in one
  write; a generation failure shows the log tail and writes nothing; several boards in one `.zen` folder start the
  named one.
- **Existing scripts (B3).** A hand-written fixture script with a loop, a helper, a numeric `Centre`, named parts and
  literal parts: an unplaced part is inserted after the right statement in the script's spelling; the loop's items are
  `by hand` and refuse edits; a coordinate item offers a relation and never the reverse.
- **Page.** The part list's status for each state, the chip-driven target selection, the menu for a pair, Show marking
  the changed lines, a drag changing a size by one edit at drag end, the timeline's rows.
- The suites for findings, the studio, reuse and the suggestions engine pass; the bench is unchanged (nothing here
  moves a placement).

## Out of scope

- A free-text script editor in the page; typing stays with the user's editor and agents.
- Dragging a part to a position, in any form.
- Arcs in the outline, and outlines from DXF or other files.
- Copper: tracks, vias, pours and planes. The builder places parts and the board; copper stays in the script.
- Net classes other than differential pairs (track widths, clearances), and `plane()` declarations; the builder edits
  only the facts `placemat facts` reports.
- A "fix all" or a generated whole layout. The search places the rest; the user decides the anchors.
- Several users at once. Digest conflicts are refused, not merged.

## Decided with the user

- Built on the suggestions edit engine: every builder action is a structured script edit through the same apply
  path; the watcher re-resolves.
- New boards first; editing existing scripts later.
- The script stays the source of truth and must read as if written by hand.
- No coordinates: the builder writes intent forms only (relations, edges, references), never a `Location` or a
  numeric `Centre`; `coordinates=True` is the escape hatch, which the builder never sets; `coordinates=False` is never
  written.
- Numbers the builder writes are named constants with a comment saying where they came from (measured, or chosen by
  the user in the UI).
- Structured data inside, text only at the edge.

Decided with the user, 2026-10-03 (the answers to the first version's questions):

- Polygon vertices are numbers and are fine (the board's own shape), as a named constant list with the builder comment.
- No typed distances: intent only (`Along.START/MID/END` and relations).
- Quarter-turn rotations are offered, and the builder suggests the turn with the fewest ratsnest crossings against the
  components already placed, showing the counts; the user can pick another.
- Searched to decided moves the statement into the decided region; decided items can be reordered later.
- "No declaration places it" findings fold into the unplaced count.
- No board-middle target.
- A suggested board size from the total courtyard area, one or two faces and a maximum fill (a setting, default from a
  measurement; overridable in the dialog), written as a named constant whose comment says how it was derived.
- A cell's frame means its declared sides, used to turn it on an edge or row; no separate feature.
- No separate command and no command-line entry: the whole flow is in the web UI; `placemat studio` only starts the
  server, and a new board is started in the page from the project's `.zen` files.
- A declaration the builder cannot read is `by hand`, and the rest of the builder works.
- The builder lets the user state the board's facts in the page (layer roles and copper weights, pair nets, via types
  and tiers, fab minimums, the rise), writes each to its home, regenerates and confirms; nothing proceeds on a default.
- The edit engine is the shared splicing editor (`script_edit.py`), not LibCST.

## Open questions

1. The size suggestion's default fill (0.33 per face) comes from one fixture board, the only one with an outline and
   placed parts. Is that enough to start from, or should it be measured on more boards first?
2. A chosen turn is written as a literal (`rotation=90`) with a `why=`, as scripts write turns, though the number is
   a measured choice. Should it be a named constant with a comment like other numbers?
3. A new `fab-profile.json` goes beside the nearest `placemat.toml` above the board, else beside the `.zen`. Is that
   the right home, or should it always be at the project root?
4. In a `.zen` the builder writes literals with a trailing comment saying where they came from, following the file's own
   convention (its netclass numbers are literals), not the layout script's named constants. Is that the right
   reading of the numbers rule for a `.zen`?
5. Copper weight is entered in oz and written as a thickness in mm. Should the `.zen` also carry the oz as a comment, or
   is the placemat mapping to mm enough?
