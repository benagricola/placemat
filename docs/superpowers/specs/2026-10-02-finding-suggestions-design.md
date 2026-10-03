# Finding suggestions

Date: 2026-10-02
Status: design, revised with the user's answers (2026-10-02); revised again 2026-10-03 after the core was built:
structured findings, instant and searched suggestions, a probe, more edit operations (see "Structured findings" and
the phases from 4)
Source: the user, 2026-10-02: "suggestions for resolving findings would be
great". Follows `findings.py` (kinds and severities) and the studio's Findings
tab, whose rows already hold an empty `fixslot`. The studio design's "no
editing in the page for now" is superseded for applying a suggestion; the
page still has no free-text editor.

## Problem

A finding says what placemat could not do as declared. It rarely says what
to change in the script. Someone reading `[critical] C4: no legal location
within 3.0 mm of (12.0, 8.5) (courtyard x41)` has to know which declaration
to edit and with what form. Some sentences carry advice in prose (a keepout
crossing: "move it, reshape it, or name its net in the keepout's allow="; a
chamfer: "a smaller chamfer= there keeps clear"), most carry none, and
nothing can act on the prose.

A suggestion is therefore a change to the layout script, worded in the
board's own terms ("Move C4 above C1"), that can be applied with one action
and shows whether it helps before it is written.

What exists to build on:

- `Finding(kind, text, severity)` (`findings.py`), pickled and stored in the
  reuse cache as `[kind, text, severity]` (`reuse.py`).
- Every declaration records the file and line it was declared on
  (`preview_json.declared_sites`), and `studio_diff.declaration_span` finds
  the statement that holds a line with `ast`.
- The studio: a watcher that re-resolves after every change to a file the
  script depends on (`studio_watch.py`), a warm worker (`studio_worker.py`)
  that resolves as `preview` does and replays unchanged steps, a `Record` per
  resolve with the text of each file at its start, a compare of any two
  records (`Studio.compare`: plan diff, line diff, trace, findings gained and
  lost, score change), and a script view linked to the board.
- Per-script settings in `placemat.toml` (`[scripts."path".section]`).

## Design

One suggestion engine, two surfaces, one application path. A suggestion is a
**structured script edit plus its wording**, made where the finding is
raised. Both surfaces read the same suggestion records (the structure
`run.json` carries) and apply them through one entry point,
`suggestions.apply_suggestion(suggestions, id, dry_run=False)`: the command
`placemat apply <id>` calls it, and so does the studio. The digest check, the
edit and the write are in that one function; the studio adds no second
method. The studio shows the diff first and offers a try, both built on the
same call with `dry_run=True`.

### What a suggestion is

```
Suggestion
  text      the wording, in the board's terms: "Move C4 above C1"
  edit      what to write (below)
  rank      1 is tried first
  id        short, per run or resolve: "s3a" (finding 3, suggestion a)
  digests   {file: digest} of each file the edit targets, at the plan
```

The same record, as JSON, is what `run.json`, `preview --format json` and the
studio's plan JSON carry.

There is no confidence and no flag that a suggestion is certain: rank is the
order to try, and the studio's try (below) measures the result. A finding with
no suggestion has none; there is no placeholder.

**Concrete, in intent forms.** `text` and `edit` name the parts, pads, nets,
faces and forms of the board. Every value an edit writes is a relation, a
keyword or a setting, never a coordinate or an offset:

| Wording | What the edit writes |
|---|---|
| "Place C4 beside C1, on its north side" | `at=Beside(c1, Edge.NORTH)` on C4's `board.place` |
| "Let C4 take the back face too" | `face=Face.EITHER` on C4's `board.place` |
| "Place C4 before the parts that crowd it" | `priority=Priority.HIGH` |
| "Let net SIG cross keepout `ant`" | `SIG` added to `allow=` of that `board.keepout` |
| "Let the SIG track under GND at the crossing" | `bridge=True` on that `board.track` |
| "Pull C1 pad 1 to U1 pad 3 harder" | `weight=LinkWeight.X` on that `board.link` |
| "Allow U1 to turn to any bearing" | `rotations=Turns.ANY` |
| "Move the label of J1 to its south side" | `side=Edge.SOUTH` on that `board.label` |
| "Let a via give way further: place.via_move 1.0" | a setting in that script's settings table |

A value taken from a measurement (the limit a link achieved, the clearance
that fits) is quoted in the wording and written as a named constant with a
comment (see "Numbers are named constants").

**An edit** is data, not text:

```
Edit
  file      the script, a module it imports, or placemat.toml, by name
  target    the declaration it changes: the item key (or the key of a link,
            track, keepout, label, escape, accept), the file and line it was
            declared on, and the file's digest when the plan was made
  op        one of the operations below
  value     an intent expression, not source: {"form": "Beside",
            "args": [{"item": "C1"}, {"enum": "Edge.NORTH"}]}
```

Operations, each a function of the file's text:

| op | does |
|---|---|
| `set_kwarg(name, value)` | adds or replaces a keyword on the target call |
| `remove_kwarg(name)` | removes one |
| `set_arg(index, value)` | replaces a positional argument |
| `edit_list(arg, add / remove / move, element, before / after)` | changes a list or tuple literal argument: add a net to `allow=`, reorder the members of a `board.row`, drop a waypoint from a track's points |
| `insert_statement(after, value)` | adds a declaration after the target's statement (a `board.place` for an undeclared part, a `board.fanout`, a `board.rule`); the value is any call written as an intent expression, so the same op inserts `board.rect`, `board.disc`, `board.outline`, a `board.place` with an intent, or a search over the remaining parts |
| `remove_statement` | removes a call that stands alone (an `accept` that matched nothing) |
| `set_constant(file, name, value, comment, scope)` | adds or changes a named constant, with a comment, in the shared module, the board's script, or the cell's constants block |
| `toml_set(table, key, value)` | sets a key in the script's own settings table of the nearest `placemat.toml`, by a line-level edit that keeps the rest of the file byte for byte |

Rendering a value to source reuses the script's own spelling. `{"item":
"C1"}` is written as the expression the script used where it declared C1
(the first argument of that call: `c1`, `Part("c1")`), found in the AST, never
a name made up. A form or enum the file does not import is not suggested.

An edit is offered only where it changes what it says it does. If the target
call also declares other items (a call in a loop or a helper that runs for
several parts), the suggestion is not offered, since the edit would move the
others too. The plan's sites tell how many items share a `(file, line)`. A
later phase may add edits that write into the loop or helper.

**Variants.** Where one lever has several variants (which side of C1 to place
C4 on), the finding gets up to 3 suggestions for that lever, best first. The
try tells them apart.

### Where they are produced

At the place a finding is raised, where the facts are known. The finding
carries what it needs:

```python
Finding("unplaced", text, case="unplaced.search",
        facts={"item": "C4", "dominant": "courtyard", "blockers": ["C1", "R2"],
               "free_sides": {"C1": ["NORTH", "EAST"]}, "faces": "front"},
        suggestions=[...])
```

- `Finding` gains `case` (a dotted id, `kind.case`) and `suggestions`, a list
  of `Suggestion`. Neither changes the sentence, its equality or its severity.
  The reuse cache stores them with the finding so a replayed step keeps them
  (`[kind, text, severity, case, suggestions]`; an older entry has none).
- The wording and the edit for a case are built by a function in one module,
  `suggestions.py`, that the raising site calls with its facts
  (`suggestions.unplaced_search(facts)`). The site decides nothing about
  wording; `suggestions.py` decides nothing about which finding it is. A case
  with several levers returns several suggestions in order; a lever that does
  not apply to these facts is not returned.
- A fact a suggestion needs that the site does not have (which sides of a
  neighbour are free, how a pad is walled) is measured at the site, from the
  occupancy the site already holds, not recomputed later.
- Findings made from plain-string copper notes (about thirty
  `ctx.notes.append("...")` sites that `_plan_copper` wraps as `copper`
  warnings) are converted to `Finding`s with a case as their suggestions are
  written. Until then those have none.

A suggestion is bound to a script by its target: the item key, the file and
line from `declared_sites`, and the digest of the file at the plan. Locating
the call uses the AST, not the line alone: the call on that line whose
function and first argument match the declaration. If it is not found
exactly once the edit is refused.

### The shared edit function

`script_edit.py`, pure: `apply(edit, text) -> new_text`, by splicing source
text with the standard library: `ast` for positions, `tokenize` for commas,
brackets and comments, `tomllib` for the TOML check.

**The dependency.** None. The engine uses the standard library only, so the
package keeps `dependencies = []` and the studio design's "no new Python
dependency" holds. The user's decision (2026-10-03, correcting the earlier
one to keep LibCST): splicing, as `freeze.py` already did.

**Finding the target.** The module is parsed with `ast`. The target call is the
`ast.Call` whose function is `board.<kind>` (`board.place`, `board.keepout`),
whose first argument matches the declaration, and whose start line is the
declared line from `declared_sites`. A constant to change is found the same way,
by its assignment at module level. A target not found exactly once refuses the
edit.

**Changing it.** `ast` gives every node its start and end (line and UTF-8
column), converted to character offsets into the text. An edit is a few
`(start, end, new text)` splices on the spans of the nodes it changes (a
keyword's value, an argument, a list element, a statement's lines), applied
together from the end of the text backwards; two splices that overlap are an
error. Everything outside the spans is the file's own bytes, so comments and
layout need no preserving. What needs care is the layout of what is written
next to what was there. `tokenize` gives the commas and comments between the
items of a call or a list, and the engine handles them as follows:

- Removing a keyword or an element keeps the comment on its line: it goes onto
  the previous item's line (after a comment already there) when there is one,
  else stays on a line of its own where the item stood. The closing bracket
  keeps its line and indent; the previous item's comma goes where the removed
  item had none, so the trailing-comma style stays.
- A new keyword in a multi-line call is written on its own line, at the indent
  of the line the last argument starts, after the last argument, in the call's
  trailing-comma style (a trailing comma after it where the call had one, none
  where it had none); in a call on one line it follows `, `.

The operations work on a call's arguments or a list's elements wherever they
are, not only on the target call, so an argument inside a nested call
(`Beside(...)`) and several edits to one suggestion are more splices of the same
kind, not a different engine.

**The check.** After the edit the text must parse, and the `ast` of everything
outside the target must equal the original's: the original and the edited
module with the target node replaced by a placeholder have equal `ast.dump`.
Either failing refuses the edit and writes nothing. The tests below pin
layout and comments byte for byte as well, which `ast` cannot see.

**One editor.** `freeze.py` edits a place() call's keywords through the same
engine (`script_edit.edit_keywords`); there is one script editor.

`toml_set` edits the one `key = value` line in the named table, or appends the
key to it, or the table, at its end, as lines, with the rest of the file left
byte for byte. The TOML is parsed with `tomllib` before and after to check the
value landed and nothing else moved.

`apply` returns the edit's before and after text, and `undo` restores the
before text (see Undo).

### Numbers are named constants

A number an edit writes is documented where it is written. The edit does not
put a bare figure in a call (`limit_mm=5.1`); it writes a named constant with
a comment saying where the value came from, and the call uses the name:

```python
# Measured by a run's finding: C1 pad 1 to U1 pad 3 was 5.10 mm.
C4_LINK_LIMIT_MM = 5.1
board.link(c1_pad, u1_pad3, limit_mm=C4_LINK_LIMIT_MM)
```

- **Op.** `set_constant(file, name, value, comment, scope)`. It adds the
  assignment, or changes the value and comment of an existing one. The
  `value` in an edit's intent expression may be `{"const": {...}}`, which the
  engine renders as the name and pairs with a `set_constant` for it.
- **Where it goes (`scope`).** A value that applies board-wide goes in the
  shared module the board's cells include: the module every layout script
  imports for the board's constants or geometry, found from the imports of the
  script (the module imported by the most scripts of the project, or by the
  script and its siblings); if none exists, the board's own layout script. A
  value for one cell goes in a constants block at the top of that cell's
  layout script, after its imports; the block is created if the script has
  none, and the constant is added at the end of an existing one. The edit's
  `file` names it, so the diff shows both the constant and the call.
- **Names** are made from the item and the keyword, upper case, with the unit
  where the keyword has one: `C4_LINK_LIMIT_MM`, `U1_ESCAPE_DEPTH_MM`,
  `SIG_CHAMFER_MM`. A name already bound in the file, or in a module it
  imports, is never reused or overwritten: a counter is added
  (`C4_LINK_LIMIT_MM_2`). The comment names the finding case and the measured
  figure, in placemat's words, never a project's.
- **Derivations.** A value derived from existing names by geometry (a
  diameter halved for a radius) is written inline as an expression of those
  names (`radius=PAD_DIAMETER_MM / 2`), with no new constant.
- **A value already from a constant.** If the call already takes its value
  from a name (`gap=GAP`), the suggestion comes in two variants: change the
  constant (the diff shows every use of it, so the reader sees what else
  moves), or add a new constant for this one use and point the call at it.
  The try tells them apart.
- Settings (`toml_set`) are numbers too; the TOML key is itself the name, and
  the line gets a comment in the same way where the file has comments.
- Intent forms with no number (`Beside(c1, Edge.NORTH)`, `Face.EITHER`,
  `Priority.HIGH`) need no constant.

### The studio

**Showing a suggestion.** A finding row's `fixslot` shows the rank 1
suggestion's text with a "more (n)" control for the rest. Each has Show,
Try and Apply. A suggestion whose edit targets another item (the neighbour
in "Move C4 above C1") names it, and Show selects that declaration's line.
The page reads the suggestions from the finding in the plan JSON, the same
records `run.json` holds.

**One path.** The three endpoints take `{resolve, id}`, look the suggestion up
in that resolve's findings, and call `apply_suggestion` on it. The client
never sends source text, so the endpoints cannot write arbitrary content.

**Show: the diff first.** `POST /suggest/show` is `apply_suggestion(...,
dry_run=True)`: it returns the unified diff and the lines changed, and writes
nothing. The page opens the script view at the file, marks the changed lines
as an overlay (old and new), and shows Apply and Cancel.

**Try: resolve the dry-run result.** `POST /suggest/try` takes the edited text
the dry run returns and asks the worker to resolve the script with it in
place of the file on disk. The worker's script loader takes an overlay
`{file: text}` and reads from it first, for the script and for any module it
imports, with the real path as the file name, so declaration lines and
relative paths are unchanged. The try replays unchanged steps from the last
real record's reuse and does not write its own back, so it cannot disturb the
next real resolve. It runs in the same warm worker only when no real resolve
is running or pending; a change to a watched file cancels it at its next
step, as it cancels a resolve. One try at a time, with a timeout,
`[studio] try_timeout_s`.

The result is a record that is not added to the history, compared with the
resolve the suggestion was made on by the existing `Studio.compare`. The page
shows it in the compare view, marked "try, not written":

- whether the finding cleared: the same `(kind, case, item)` is absent from
  the try's findings;
- findings gained and lost, with their severities;
- items that moved, ghosts and arrows;
- the score's change;
- the diff of the script.

**The try replaces a "checked" flag.** An earlier version of this design
marked suggestions `checked` where the raising code had measured that they
clear. A try measures the same thing for every suggestion, on the real
resolve, including what else the edit changes, and it needs no per-site
proof. The page offers the try on click, not automatically, because each is
a resolve. A try never runs on its own.

**Apply: written to the file.** `POST /suggest/apply` is
`apply_suggestion(..., dry_run=False)`, which:

1. checks that each target file's digest on disk equals the digest in the
   suggestion (the text the plan was made from). If a file changed, it
   refuses and writes nothing; the page has already been told the files
   changed and marked the plan stale, and shows the new plan's suggestions
   instead. No relocation is attempted: a refusal is cheaper than an edit to
   the wrong line;
2. applies the edit and writes the file atomically (a temporary file in the
   same directory, then `os.replace`, keeping the mode);
3. appends `{id, file, before, after, at}` to the applied log
   (`.placemat/applied.jsonl`, shared with the command line).

The watcher then sees the change as it sees any edit and re-resolves; the
compare with the previous resolve shows what the edit did, and the history
lists it as "applied from a suggestion: <text>".

Only files the studio already watches are written (the script, its modules,
`placemat.toml`), and only under the project root. Apply is allowed when the
studio listens on another address (`--host`); the token every request needs
guards it. `[studio] apply = false` still turns writing off.

**Undo.** The page shows "Undo" beside the applied edit and in the history
row. `POST /suggest/undo` calls the same undo function as `placemat apply --undo`: it restores the logged `before` text if the file's
current text equals the logged `after` (nothing else has touched it since);
otherwise it refuses and says so, and does not try to reverse its own lines.
Undo is a stack: each undo reverts the last apply that has not been undone,
only if the file still matches what that apply wrote. Undone edits are logged
as such. The same
log serves the command line's undo.

### The command line

The same suggestion records, through the same `apply_suggestion` the studio
calls: one edit, one digest check, one write.

- `run` (and `preview`) print, under each printed `critical` and `warning`
  finding, a line `    try s3a: Move C4 above C1`. The id is short and tied
  to the run that made it.
- `run.json` `finding_details[i]` gains `suggestions`: `[{id, text, rank,
  edit}]` with the edit as data, and the run record keeps the digest of each
  file an edit targets. A record without the field reads as none.
  `preview --format json` carries the same.
- `placemat apply <id> [--script PATH] [--dry-run]` finds the latest run
  record for the script, rebuilds the edit and prints the diff; without
  `--dry-run` it applies it. It checks each target file's digest against the
  record's: on a mismatch it refuses and says the script changed since the
  run, and does not touch any file. `--dry-run` is the same call with
  `dry_run=True`, which the studio's Show uses. `placemat apply --undo` reverts the last applied edit with the same
  rule as the studio's undo.
- The agent-facing skill documents the field and the command: read
  `finding_details[i].suggestions` after reading the finding as a claim about
  the script; `placemat apply <id> --dry-run` shows the diff; a suggestion is
  a candidate, and the run decides whether the finding cleared. `api.md`
  "Findings and severities" gains a "Suggestions" subsection with the shape
  and the table of cases; a test keeps the table and `api.md` in step.

### Outputs, summarised

| Surface | Carries |
|---|---|
| studio plan JSON, the `findings` event | each finding's `case` and `suggestions`, the same records as `run.json` |
| studio endpoints (token and host as the others) | `/suggest/show`, `/suggest/try`, `/suggest/apply`, `/suggest/undo`, each a call of the shared function |
| `run`, `preview` console | `try <id>: <text>` under critical and warning findings |
| `run.json`, `preview --format json` | `finding_details[i].suggestions` with the edit as data |
| `placemat apply` | applies or undoes by id |

Settings: `[studio] try_timeout_s` (default 60), `[studio] apply` (true;
false makes the studio show suggestions and diffs but refuse to write), and from phase 6 `[studio] probe_budget_s`
(120) and `probe_candidates` (12). All are studio settings and not part of a run's id.

## Structured findings

Terminology: the text above this section (including its Testing section), and the core as built, say `case` and `case=`; from here the field is `cause`
(an enum, below), so read "case" as "cause" in the older text and in `finding_details[i].case`, which becomes `.cause`.

Revision of 2026-10-03, after the core was built (branch `suggestions-core`) and its levers were checked against the
code. The core could not build many levers because the engine measures the figure a suggestion needs and then keeps
only a sentence: `Occupancy._conflict` returns text (occupancy.py:2024), `_reason_key` reduces it to a bucket name
(occupancy.py:2833), a scan keeps `Blocker(kind, owner, faces)` counts (occupancy.py:90), `ctx.note` and
`Finding(kind, text)` take a sentence (layout.py: 39 `ctx.note`/`notes.append` sites and 30 `Finding(` sites). A
suggestion builder then has to parse text or do without. The fix is in the finding, not in the suggestions.

**A finding is data; its sentence is rendered from it** (the rule below, applied to findings first). A finding has `kind`, `cause`, `severity` and `facts`: typed
values naming the items, pads, nets, owners and keepouts involved and the figures the site measured (the overlap depth,
the clearance shortfall and the clearance needed, the pitch tried, an extent, a side, a point). The sentence the console,
the logs, `run.json`'s `text` and the studio show is `finding_text.render(cause, facts)`. Nothing reads a sentence for
data: no builder, no studio code, no test.

### The rule

This is a rule for all of placemat's code, and the structured-findings phase is its first application.

- **A function returns data**: a scalar (a number with its unit in the name or the schema, an enum, a name), a record
  (a dataclass or a dict of JSON values), or a list of them. Text is returned only where the data is itself a description
  (a `why=` the script wrote, a part's value, a note the user typed).
- **Data becomes a sentence, a view or a graph only at the outer edge**: the console printer (`console.finding`), the log
  and progress writers, the studio page and `placemat watch`, the report and `impact` text. Each edge has a renderer; the
  renderers are the only code that formats a figure into words.
- **Nothing inside parses a sentence** to recover a number, a name, a side, an item or a point. A regular expression or
  `split` over text that a placemat function made is a bug in the producer: it returns the data instead, and the consumer
  reads the field. An identifier that has structure (a link, a track, a label, a keepout) is a record or an opaque key plus
  typed fields, never a string that is cut apart.
- A string that crosses a boundary and is read by a person (the finding sentence, a refusal's text) is made by a renderer
  from the record, and the record travels with it (the finding's `facts`, a run's `finding_details`).

The test of the rule is a search of the source: a `re.`, `.split(`, `startswith`, `in <sentence>` or slice applied to a
finding's text, a refusal's text, a note or a key built from several fields is a violation, and each one found is
listed below and removed in phase 4. A new one fails review.

### Producers and consumers the rule changes

The producers return data; the consumers read it. Grouped by what they return now.

| Now | Returns | Becomes | Consumers that parse it today |
|---|---|---|---|
| `Occupancy._conflict` (occupancy.py:2024), `_drawn_conflict` (1867), `refusal`, `reservation_hit` (956) | a sentence | a `Conflict` record (kind, owner, net, layer, faces, `gap_mm`, `need_mm`, point, pads, the reservation's source: keepout name, label key, fanout item); `.text()` is the renderer | `legal()` and `legal_giving_way()` pass the sentence up; `_reason_key` (2833) searches it for words; `_blame_text` (layout.py:10052) formats counts and owners; `suggest_facts.reservation_source` (mine) matches `keepout '...'`, `label ...`, `fanout of ...` in a blocker's owner text |
| `Occupancy.legal(...) -> str \| None`, `legal_giving_way -> (str, resolution)`, `legal_bucket` (1697) | the sentence, or a bucket word | a `Refusal \| None` record (a `Conflict` plus the bucket as an enum field); the sentence is `Refusal.text()` and is computed only by the printer or a test | placer scans count by `_reason_key(why)`; `ScanResult.reasons` keeps first sentences; `_slide` and `scan` key `rejected` by words; riders' `accept(...)` returns `"rider R3: why"` strings and callers split on `":"` (layout.py ~7615, 8565) |
| `Occupancy.copper_conflicts` (821) | a list of sentences | a list of `Conflict` | `_plan_copper_batch` (layout.py:7516) builds the note from the sentence and adds text; `_through` (5519) returns the sentence of what a track runs through |
| `Blocker`, `ScanResult.blockers/reasons` | owner as a formatted string (`blame_owner`, occupancy.py:890, "cell X's C4 GND", "pour NET"); a count | `Blocker` with `owner` (item key), `owner_cell`, `net`, `kind` fields and the sample `Conflict`; no formatted owner | `_blame_text` and `suggest_facts.owners_of` |
| `_cutout_illegal` (layout.py:1451), `_check_settled_cutouts` (1655) | a sentence or None | a `CutoutRefusal` record (`outside`, `notch`, `web`; the web measured and the minimum; the loop) or None | `_cutout_illegal`'s callers put the sentence in a finding and in `Step.note` |
| `ctx.note(text)` and the 39 note sites, `_check_pitch`, `_check_fit_content`, `_check_web`, `_report_*`, the pour, stitch and via notes | a `Finding(kind, text)` | `Finding(kind, cause, facts)` | `preview_json._findings` finds the item by the sentence's first word (preview_json.py:93, 209) and the points and pads by regular expressions (`_AT`, preview.py:310; `finding_targets`, preview_json.py:183); the studio page's `focusFinding`; `suggestions.finding_key` (mine) takes the first word |
| `_riders_alone`, `_no_pocket_note` (8045), `_room_lost_text` (4212), the hopeless-pocket text | sentences | records (`item`, `turns tried`, per-rider refusal, per-turn refusal, the room lost: pair, shortfall, asked distance) | `_settle` concatenates them into the finding and into `Step.note` |
| `Step.note` and `Step.why` | free text assembled from fragments | `Step.facts`: a list of typed notes (kind, fields); `note` is rendered for the console and the Steps view | the studio's step rows; `plan_json` |
| `giveway.report(occ)` (giveway.py:1091), the vias findings | `(home, text, severity)` tuples | records (via, what it did, the owner whose room it needed, the limits it hit) | `_report_...` sites make `Finding("vias", "%s: %s" % (key, text))` |
| `checks.Verdict.note`, `accepted`, `Outcome.why_not` (checks.py:95-110, 233) | strings assembled with figures | `Verdict` already has `value`, `unit`, `limit`: add `facts` (the loop, the net, the part and the distances) and render `note` at the edge; `findings_of` makes `setup.accept` findings from the outcome record | `checks.record`, the console's check lines, `RunRecord.verdicts` |
| `placer.py`'s placement notes (`chose`, `moved ...`, `seeded on ...`), `_label_hits` (layout.py:9027) | strings, a list of owner strings | records | label findings and notes |
| item and declaration keys that encode structure: a link `C1.1>U1.3`, a copper declaration `track SIG#12`, a label `label J1 text`, `"cell X's ..."`, `"%s (%s)"` | a string cut apart with `split(" ", 2)` (layout.py:7109, 7118, 7122, 7288, 7291; suggestions.py:652, 752) | a record: `LinkId(a, b)`, `CopperId(kind, net, index)`, `LabelId(item, index)`, each with an opaque `key` for lookup and typed fields for reading | the label, copper and link sites, `Board.sites_of`, the builders |
| my own core code: `suggest_facts.reservation_source`, `suggestions.finding_key`, `suggestions._label_picks`, `preview_json` additions | read a sentence or a key | read the record's fields | (removed with the producers above) |

Each row is a commit in phase 4, with its golden rows. A row is done when the search in the rule's test finds no parse of
its text in `src/placemat` and the studio page. Where the studio page (`studio_page.html`) formats a finding, it renders
from the finding's `facts` and `cause` and falls back to the server's rendered text for a cause it does not know, so the
client never parses the sentence either.

### Kind and cause are enums

A finding's category and its situation are enums, not strings. The field is `cause` (the core called it `case`; it read as
"the instance" and is renamed with the rest of phase 4).

```python
class FindingKind(Enum):         # the categories now in findings.KINDS
    UNPLACED = "unplaced"; LINK_OVER = "link_over"; FIXED = "fixed"; COPPER = "copper"; LABEL = "label"; ...

class FindingCause(Enum):
    UNPLACED_SEARCH = (FindingKind.UNPLACED, "unplaced.search")
    UNPLACED_POCKET = (FindingKind.UNPLACED, "unplaced.pocket")
    COPPER_MEETS    = (FindingKind.COPPER,   "copper.meets")
    LINK_OVER       = (FindingKind.LINK_OVER, "link_over")
    ...
    kind  -> the member's FindingKind        # a property; there is no way to pair a cause with another kind
    value -> the string form                  # "unplaced.search"
```

- **A member carries its kind**, so `Finding(cause, facts)` takes the cause alone and `finding.kind` is `cause.kind`. A
  cause with a kind other than its own cannot be written. A kind with a single situation (`link_over`, `pair_crossed`,
  `escape_walled`) has one cause of the same name.
- **Everything is keyed by the member**: the facts schema and the renderer (`finding_text.SCHEMA[cause]`,
  `RENDER[cause]`), the suggestion builder (`suggestions.BUILDERS[cause]`), the golden rows, the score and severity
  tables (severity is a property of the kind, with a per-cause override where a kind mixes situations, as
  `findings.SEVERITY` does now). A table missing a member fails a test that iterates the enum, which replaces the core's
  source scan of `case="..."` strings.
- **The string form exists only at the edge.** `cause.value` is what `run.json`, `preview --json`, the studio's plan JSON,
  the reuse cache and the console show. A reader calls `FindingCause.parse(text)`, which returns the member or `None` for
  a string this version does not have (a record from a later version): the finding then reads as a plain finding with its
  rendered text and its kind, and its facts are ignored (`facts_v` as now). `FindingKind.parse` likewise. Nothing inside
  compares a cause with a string or builds one from pieces.
- **Facts fields that name a kind of thing are enums too** where the set is closed: the op kind (`track`, `via`, `pour`),
  the refusal bucket (`courtyard`, `edge`, `reservation`, `copper`, `through`, `hole`, `via_give_way`, a rider), the side
  (`Edge`), the face (`Face`), the layer. Their string forms follow the same rule.
- **The existing `KINDS`, `SEVERITY`, `RANK` and `check_severity`** in `findings.py` are rebuilt on `FindingKind`; the
  `Finding` class keeps `.kind` (now the enum) and `.severity`. A `Finding("setup", text)` call (a plain, not yet converted
  finding) becomes `Finding.plain(FindingKind.SETUP, text)`, with `cause = None`, until its site is converted.

### The model

```python
Finding(kind, cause, facts, severity=None)      # a str: its value is render(cause, facts)
Finding(FindingCause.COPPER_MEETS, {"net": "SIG", "word": "via", "at": [152.68, 103.61], "other_net": "GND",
                                   "other_layer": "In3.Cu", "gap_mm": 0.0, "need_mm": 0.16, ...})
```

- `facts` is a dict of JSON values (no objects), one **schema per cause** in `finding_text.py`: field name, type, unit
  and which fields the sentence uses. A figure is a number in millimetres or degrees, a side is an `Edge` name, an item is
  the key a `place` declaration has, a pad is `[item, number]`, a point is `[x, y]` in board millimetres. Facts are
  about the board and the declaration, never a project's names (the charter's rule holds: they are whatever the
  script and the netlist name).
- **Facts are not suggestions' private input.** They go in `run.json` (`finding_details[i].facts`), `preview --json`, the
  reuse cache and the studio's plan JSON, with `facts_v` (the cause's schema version, an integer); the record's keys are `kind` and `cause`, both strings. A reader that does
  not know a `facts_v` ignores the facts and shows the text. A record without `facts` reads as before.
- **Rendering keeps every sentence byte for byte.** `render` has one template function per cause, written from the
  existing format strings. The existing tests pin sentences (the finding, severity and kind tests, the escape, copper and
  label tests); they stay unchanged and are the first check. Two more pins are added before any site is converted
  (phase 1, step 0): `tests/finding_text_golden.json`, the findings (kind, severity, text) of every fixture module under
  `fixtures/` and of the bench boards, written from main before the change; and a test that resolves them and compares.
  A cause converted without its golden rows matching is not converted.
- **Development converts cause by cause; a release converts them all.** On the branch a cause not yet converted keeps
  `Finding.plain(kind, text)` with `cause=None` and `facts={}`, so each commit builds. A release has none: a test
  (`tests/test_no_sentence_parsing.py`, with the rule's source search) fails if any `Finding` is built from text, if any
  `ctx.note`-style producer or any producer in "Producers and consumers the rule changes" returns a sentence where data is
  expected, or if a consumer parses one. No mixed state ships; `Finding.plain` is removed from the code before the release
  and the test asserts it is gone.
- **Reuse.** The cache stores `[kind, cause, severity, facts_v, facts]` (kind and cause in their string forms, parsed back on read) for a converted finding, and the suggestions are
  built from facts at the end of the resolve (`bind`), which is what the core already does for findings with facts. The
  reuse record's `VERSION` goes from 2 to 3 once (an older record replays nothing, one resolve). A changed facts schema also
  invalidates the record: its context holds a digest of every cause's `facts_v`, so a record made under another schema replays
  nothing, and stored facts are never read under a schema they were not made for. Suggestions are no longer
  stored in the cache at all: they are a function of facts and the script.
- **Conflicts become typed.** `Occupancy._conflict` is split: `_conflict_facts(...) -> Conflict | None` and
  `_conflict(...) = text of that`, so `legal()` and the native path (which only decides which pair conflicts and still gets
  its sentence from Python, occupancy.py:1640-1664) cost the same. `Conflict` is `(kind, owner, owner_net, net, layer,
  faces, gap_mm, need_mm, point, pads)`: the two shapes' kinds, whose they are, the distance between them and the
  distance the rule asks, where, and the pads concerned. `copper_conflicts` (occupancy.py:821) returns `Conflict`s;
  the copper finding is made from one. `Blocker` carries the same fields, and a scan keeps, per (bucket, owner), the first and
  the worst `Conflict` it met (`ScanResult.samples`), so a search that failed can say how far the dominant refusal was
  from legal (the worst `gap_mm` shortfall) and by whom, including the via-owner that `_reason_key`'s `VIA_BUCKET` loses now
  (occupancy.py:2837).

### Where each site records its facts

Every site below changes from "make a sentence" to "gather facts, render". The grouping is by file; "figures" are what
the site already computes.

| Site | Case | Facts it records (figures it already computes) |
|---|---|---|
| layout.py `_settle` (the search that found nothing, ~8774) and `_scan_faces` | `unplaced.search` | item, radius used, hint point, faces, the dominant bucket with its worst sample (owner, gap and need, point), the buckets with counts, partners and the free sides measured |
| `_settle_in_pocket` (6910), `_no_pocket_note` | `unplaced.pocket` | item, envelope size per turn and face, pockets tried, rider refusals |
| `_slide`, `_slide_block` (7624, 7700) | `unplaced.slide` | item, edge or run, slot range tried, buckets |
| `_settle_block` (8173), `_block_alone` | `unplaced.block` | item, anchor, satellites, the refusal per turn |
| `_settle_turns_on_point` (8930) | `unplaced.bearing` | item, point, turns tried, buckets |
| `_riders_alone`, `_settle_riders` (8543) | `unplaced.rides` | rider, parent, the refusing rider and its refusal |
| `_firm_placement` call sites (8200, 8642, 8610) | `fixed.part` | item, freedom, the `Conflict` that refused it (owner, gap, need, point) |
| `_check_settled_cutouts` (1655), `_cutout_illegal` (1451) | `fixed.cutout` | cutout, which test failed (outside, notch, web), the web measured and the minimum, the nearest loop |
| keepout settle (~6244) | `fixed.keepout` | keepout, item, `Conflict` |
| `_check_keepouts` (1683) | `copper.keepout` | net, op kind, layer, keepout, what it excludes (core already) |
| `_plan_copper_batch` hits (7516-7545) | `copper.meets` | declaration id, net, op kind, layer, the `Conflict` (other net, other owner and pad, gap, need, point), the declared leg the point falls on and its index, chamfer or radius if the cut is the part that meets |
| `resolve_bridges` (copper.py:402) | `copper.cross` | the two declaration ids, nets, layer, point, which yields and why (priority, length, order) |
| `track()` closure (layout.py ~4740-4800), `ctx.note` sites | `copper.not_drawn`, `copper.corner`, `copper.note` | declaration id, cause, the pad or item run through, arc radius and the misfit, the corner and the shortfall |
| pour sites (5836-5890) | `copper.not_drawn` | pour, pad (item, number), net, cause, the clearance shortfall, the neck width and the net's track width |
| stitch sites (5230-5260) | `copper.not_drawn` | stitch, region, pitch tried, via size, gaps measured |
| via sites (5447, 5611, 5078) | `copper.not_drawn` | via, net, spot tried and count, the `Conflict` that refused the best spot |
| `_report_links` (4471) | `link_over` | link, both pads, measured length, limit, weight (core already) |
| `_report_escapes`, `_report_lanes` (4428, 3666) | `escape_*`, `pair_crossed`, `setup.lane_unused` | part, pin, net, blockers with owners, side, the two pins and their targets for a cross, the lane and what blocks it |
| `_place_labels`, `_labels_give_way` (7076, 7256) | `label.*` | label key, side, size, what it sits on (owner and overlap box), the sides tried |
| `_check_pitch` (1732) | `setup.pitch` | part, net class, clearance, track width, the lane measured and the clearance that fits, short count |
| `_check_fit_content` (6753), `_check_web` (1718) | `setup.frame_reach` | item, its extent on the axis, the declared extent, the span all items need |
| `_report_undeclared` (4398), `checks.findings_of` (checks.py:233) | `setup.undeclared`, `setup.accept` | item; check and subject |
| giveway report (`giveway.report`, layout.py ~6540) | `vias.*` | item, via, what it did or why not (moved, left, dropped), the owner whose room it needed, the move and leave limits it hit |
| project.py:223, runner.py:471 | `fab`, `facts` | the rule and the minimum; the unconfirmed reasons |

About 70 sites in all (30 `Finding(` and 39 `ctx.note`/`notes.append` in layout.py, four elsewhere, and the occupancy
and scan plumbing above). The conversion goes by cause, each in its own commit with its golden rows.

## Instant and searched suggestions

A suggestion is one of two kinds. The kind is a field, `how`, on the record (`"instant"` or `"searched"`).

**Instant.** The edit is computed from the facts and is complete: the value is a number from a measurement, a name, an
enum or a relation. It is shown, tried, applied as now. Examples, each from facts the sites above record: the clearance
rule from the measured shortfall (`board.rule(clearance=<gap_mm floored>, between=(<net>, <net>))`, `setup.pitch` and
`copper.meets`); the via at a free spot near the named pad (`at=FreeSpot(near=PadRef(...))`); the frame size from the
extents (`setup.frame_reach`); the web from the measured gap (`fixed.cutout`); a pad taken out of a pour; a rider let be
searched; the drops thinned on the cell that owned the refused via.

**Searched.** The figure is not known from one measurement: it is where a condition flips, and finding it takes
resolves. The record has the lever and the figure but no value: `{"how": "searched", "figure": {...}}`. It is worded as
a question, "Changing the stitch pitch of GND might fix this: search options?", never as a fix. Nothing is applied or
tried from it. Running its probe (below) produces a concrete instant suggestion with a measured value, and the
searched one stays listed. A searched suggestion's `figure` says what is varied and over what:

```
{"edit": {...with the value left out...}, "figure": {"name": "gap", "unit": "mm", "kind": "bisect",
  "lo": 0.0, "hi": 1.2, "direction": "lower clears"}}      # a monotone figure between two bounds
{"figure": {"name": "side", "kind": "set", "values": ["NORTH", "EAST", "WEST"]}}   # a small set
```

The bounds come from the finding's own measurement (see "A suggested value comes from the finding's measurement"),
never from the board's extent, a pad's size or a multiplier. `studio.suggest_factor`, which the core added, is removed: no suggestion's number is a guessed multiple.
Every figure that was derived from it is either instant from facts or searched, and the table that follows gives the
kind; the bounds and facts each needs are in the rule's table after it, which governs where they differ:

| Figure | Kind | Bounds and how it is judged |
|---|---|---|
| a blocker's gap, side or relation (`unplaced.search`, `rider`) | searched: a first candidate from the worst `gap_mm` shortfall, then bisection; sides as a set of four | lower bound the declared gap, upper bound the board extent; judged by the item placing |
| search radius (`unplaced.search`) | searched, bisect | lower the radius used, upper the board's diagonal; judged by the item placing; the search goes up by bisection from the measured first-spot distance when a scan with a coarse step finds one |
| fanout depth | searched, bisect | 0 to the declared depth; judged by the item placing |
| turn of a part (`slide`, `escape_crossed`, `pair_crossed`) | searched, set (the four right-angle turns, or the declared `rotations`) | judged by the finding clearing |
| chamfer, arc radius (`copper.meets`, `not_drawn`, `corner`) | searched, bisect | 0 to the declared value; judged by `copper.meets` or `not_drawn` clearing for that declaration |
| label size, label side (`label.*`) | searched, bisect and set | size 0 to declared, judged by the label no longer sitting on anything |
| stitch pitch, via size (`stitch` not drawn) | searched, bisect | lower: via size plus the clearance the rules give; upper: the declared pitch |
| `place.bearing_step` | searched, set: the divisors of 90 below the current step | judged by `unplaced.bearing` clearing |
| `place.via_move`, `place.via_leave` | searched, bisect, upper bound the carried via's pad size (open question 3) | judged by the via giving way |
| `place.block_gap_reach`, `place.escape_via_reach` | searched, bisect, upper bound the board's extent (open question 3) | judged by the block laying out, the lane's via finding a spot |
| `bend=` (`copper.corner`) | searched, set: `START`, `END`, `BOTH` | judged by the corner finding clearing |

A figure whose search cannot be judged (the finding's clearing does not depend on it, or no bound can be given) is
dropped, not guessed.

### A suggested value comes from the finding's measurement

This is a rule for every suggestion that writes or searches a figure (an instant value, a probe's range, a tuning limit).

- **The measurement is in the finding.** A figure is derived from a number the finding's facts carry (the overlap depth, the
  clearance shortfall, a measured length, an extent, a pitch tried, a gap). It may be a ratio or multiple of that number (a
  probe range of up to 2x the measured shortfall, the shortfall itself, half of a measured overlap), and the suggestion says
  that it is derived: the text names the figure and the constant's comment records the derivation ("Derived from the measured
  shortfall of 0.07 mm of the clearance of 0.16 mm: range up to 2x it").
- **Never from a bound unrelated to the finding**: not the board's extent, not a pad's size standing in, not a global factor,
  not a setting's current value alone. `studio.suggest_factor` and the suggestions that used it are removed in phase 4.
- **No measurement, no suggestion.** If the finding carries no number that bears on the figure, the lever is not offered at
  all: not as a guess and not as a searched suggestion with a made-up range. A site that could measure one cheaply records it
  (phase 4); one that cannot, or whose measurement would be a new search of its own, offers nothing.
- A multiple used in a range is a constant of the derivation, written in the suggestion's `figure` (`"of": "gap_mm",
  "times": 2`), so it is visible and tested, and is not a tunable that moves a placement.

Each figure, and the facts it needs. A figure is offered only where its finding records them.

| Figure | Needs in the finding | Derivation |
|---|---|---|
| a blocker's gap (`unplaced.search`, a rider) | the worst `gap_mm` and `need_mm` of the dominant refusal, the blocker's declared gap | the shortfall `need_mm - gap_mm`; range declared gap up to declared gap + 2x shortfall |
| a blocker's side, a part's side (`Beside`) | the sides measured free (`free_sides`) | the set of sides measured |
| a turn (`unplaced.bearing`, `slide`, `escape_crossed`) | the turns tried and each one's refusal | the right-angle turns not tried |
| search radius (`unplaced.search`) | the distance to the nearest legal spot, measured by the site | that distance (range up to 2x); no suggestion until a site records it, and phase 4 does not add the measuring scan, so none |
| fanout depth | the overlap depth of the fanout's reservation with the candidate | declared depth minus the overlap, range down to depth minus 2x overlap |
| chamfer, arc radius (`copper.meets`, `not_drawn`, `corner`) | the shortfall of the clearance at the cut (`need_mm - gap_mm`) and the declared value | declared value reduced by the shortfall, range down by 2x it |
| label size, label side | the overlap box of the label with what it sits on, the label's size | size reduced by the overlap along its height or length, range down by 2x it; sides measured free |
| stitch pitch, via size | the gap measured between rows or vias against the pitch (the "row has a gap over its pitch" note), the rule's clearance | the measured gap as the pitch; none for "no via fits" (no measurement) |
| `place.via_move` | the move a via needed, measured by the give-way search with its limit lifted and recorded as `needed_move_mm` | that figure; none until the give-way site records it |
| `place.via_leave` | the distance the via would have to leave its pad, recorded as `needed_leave_mm` | likewise |
| `place.block_gap_reach` | the satellite's measured conflict (`gap_mm`, `need_mm`) at the nearest gap tried | the shortfall; none until the block site records it |
| `place.escape_via_reach` | the distance past the row's end to the first legal via spot, recorded as `via_spot_mm` | that figure; none until the lane site records it |
| `place.bearing_step` | the angular margin of legality around the best bearing tried (`margin_deg`) | that margin; none until the bearing site records it |
| `bend=` (`copper.corner`) | the shortfall at the corner and the end it is nearer | a set of the ends, judged by the probe; offered only where the shortfall is recorded |

Where the table says "none until the site records it", phase 4 does not record it, and the suggestion is removed from the
core's builders (`unplaced.search` radius, `place.via_move`, `via_leave`, `block_gap_reach`, `escape_via_reach`,
`bearing_step`, the label size and chamfer and radius reductions, the pocket step): those were derived from a factor.
They return when a site records the measurement, in the phase that adds it (phase 6, with the probe, which can measure by
resolving).

## The probe

`placemat apply <id> --search` (command line) and "search options" (studio) run the probe for a searched suggestion.

**What it is.** A sweep over one value of one script edit. Each candidate is the suggestion's edit with a value, applied as
a dry run (`apply_suggestion(..., dry_run=True)` with the value filled in) and resolved with the edited texts in place of
the files on disk: the try path of the studio ("Try: resolve the dry-run result"), which the studio's worker already
provides. It is not explore: explore varies seeds of the search among the focused items' spots
(`explore.explore`, `Explore(seed, focus)`, `explore.py:120-237`), and a probe varies a declared value. The code shared with
explore is the machinery around a resolve and not the search: `BoardFactory` and the spawned worker processes of
`explore._work` (a fresh board per candidate, `jobs` from `[explore] jobs`), the channel (`channel.py`), and the
resolve record and compare (`Studio.compare`) that the try uses to judge a candidate. A new module, `probe.py`, holds the
candidate generation (bisection, sets), the judging and the report.

**Judging a candidate.** After its resolve: the finding cleared (`suggestions.cleared`), the findings gained (by
`finding_key`, with severities), and the run score's change. A candidate is acceptable when the finding cleared and no
finding of a higher severity than the one cleared was gained. Of the acceptable ones the best is the one with the
smallest departure from the declared value (bisection finds the largest change that is not needed), ties by score.

**Bisection.** For a monotone figure between `lo` (does not clear) and `hi` (clears, checked first; if `hi` does not
clear the probe stops with "no value up to hi clears it") it halves up to `probe_steps` times. The monotonic assumption is
stated in the report, and the final value is resolved once more with a neighbour, so a non-monotone figure is reported as
"cleared at X, not at X-d": never presented as a threshold it is not. A set is every member, in order, up to the
candidate limit.

**Replay.** Each candidate resolves with the plain resolve's reuse record, so the steps before the first changed one are
replayed. How much that saves depends on the edit: a placement edit changes one step's key (reuse.py `step_key`) and the
steps before it replay; an edit to board-wide declarations (copper, labels, rules, keepouts, the outline, a setting) changes
`context_key` (reuse.py:108 `canonical([board._copper, board._labels, board._rules, ...])`), and nothing replays. So the
probes over a chamfer, a label, a stitch pitch or a setting resolve in full (a few seconds to about 25 s on the fixture
modules). A probe over a board-wide value is allowed. Before it starts it says so: "this resolves the whole board for each
candidate, up to n candidates, about s seconds each (the last resolve took s): about t in all", the estimate taken from the
last resolve's time (the run record's `timing_s["resolve"]`, the studio record's duration) times the candidate limit, and the
command line asks to confirm unless `--yes` is given; the studio shows it on the button's confirmation. A finer reuse key is
not part of this design.

**Budget and limits (settings).** `[studio] probe_budget_s` (default 120) and `probe_candidates` (default 12, bisection
steps included); one candidate is bounded by `try_timeout_s`. `jobs` is `[explore] jobs`, so a machine's CPU limit is one
setting. Both probe settings are studio settings, outside a run's id.

**Stop and resume.** The same rules as the other long commands. A probe never ends silently: it ends with one of
"found X", "no value in the range clears it", "stopped by you after n of m candidates: best so far X", "budget spent after n
candidates: best so far X", or an error, each said at once on the console and as a channel event. Stopping (Ctrl-C on the
command line, Stop in the studio) keeps what was found: every candidate result is appended to
`<board>/.placemat/probes/<suggestion digest>.jsonl` (the candidate value, whether it cleared, findings gained, the
score), keyed by the suggestion's id, its edit's digest and the digests of the files, and `--search` again continues from
those results (it does not resolve a value again) while the digests still match; a changed file starts fresh and says so.

**Reporting.** The probe is a long command and reports over the live channel (`channel.py`): `probe` (the suggestion, the
figure, its bounds, the budget), `candidate` per resolve (value, cleared, gained, score, seconds) and `probe_done` (the
outcome above and the best candidate). `placemat watch` and the studio read these like any other event; the studio draws
the candidates on the figure's range. The command line prints a line per candidate and a last line with the result.

**The result.** The best candidate becomes a new suggestion of the same finding: `how: "instant"`, id `s3a.1` (the
searched one's id and a counter), its value written under the constants rule (a named constant with a comment: "Found by
a probe of <figure> for <cause>: <value> clears it; <value + step> does not"). It is stored with the plan's suggestions
(`.placemat/suggestions.json`, so `placemat apply s3a.1` works) and shown in the studio under the searched one. It is
applied the usual way, with the digest check, so a script that changed since the probe is refused.

## Edit operations added

- **Coordinates and intent.** See "`Centre` and `Location`" below: a suggestion never writes a number into a `Centre` or
  a `Location` axis, never sets `coordinates=True`, and edits a `Centre` only when it is all intent; it may turn a
  coordinate placement into an intent one, never the reverse.
- **Nested edits.** The edit names the argument whose value is a call and the operation on that call: `into` is a path of
  a keyword or a positional index, repeated to go further, and any of `set_kwarg`, `set_arg`, `remove_kwarg` and
  `edit_list` then act on the inner call (a `Beside(...)` inside `at=`: its `gap=`; an intent relation inside a call;
  a `Past(...)` inside the points list: its `across=`; a `Cutout(...)` inside `holes=`: its `at=`; an intent `Centre(...)`: one axis's reference). Located the same way
  (exactly one inner call of that function name at that place), replaced as a node, checked by masking the inner call. About
  100 lines in `script_edit.py` and its tests.
- **Multi-edit suggestions.** A suggestion has `edits`, a list (of one for most), and `how`; there is no `edit` field: the
  core's single `edit` is dropped now and the studio branch follows. The edits apply together or not at all: every file is computed first (the edits to one file applied last line to
  first, so a line does not move under the next), each checked as now, then written atomically as now. One applied-log entry, so
  one undo. Needed for: a list removal plus an inserted statement (a satellite on its own), a layer change plus a via.
- **Sites.** `rect`, `disc`, `outline` (key: the board; refused where a script declares two), `row` (key: its first
  member; its members list is the argument), `block` (key: its anchor). Added to `layout._SITED`.

## `Centre` and `Location`

A small API change, and the rule suggestions follow about coordinates.

**The flag.** `Centre(...)` gains a keyword-only `coordinates=False` (values.py:207, `Centre.__post_init__`).

- With the default, each axis is a reference (`X()` or `Y()` of a pad, a `Part`, a `Mid`, ...) or `None`. A plain number is
  refused with a message that names the flag: "Centre(30, 12): an axis is a reference or None; a number is a coordinate:
  write `coordinates=True` to say so, or place by a relation (`Beside`, `OnEdge`, a pad's `X()`)".
- With `coordinates=True`, numbers are allowed. It is the marked escape hatch: the charter's "Intent, not coordinates"
  exception, visible at the site. The flag is part of the declaration's digest (`reuse.canonical` reads the dataclass
  fields), so adding it to an existing script changes nothing but the flag.
- `Location(...)` is coordinates only; it takes no flag and is the escape hatch by its name.

**Migration.** Scripts today write numeric `Centre` axes (the references show 68 uses across 21 test files; the fixture
scripts use none). A refusal at once would break board scripts without notice, so:

- *Release n* (the phase below): a numeric axis without the flag is accepted and gives a `setup` finding of severity
  `warning`, cause `setup.centre_coordinates`, facts `{item, axes: ["x"|"y"], values: [..]}`, rendered "c4: Centre(30, 12)
  places by coordinates: write coordinates=True, or place by a relation". The warning is made where `board.place` reads the
  declaration (not in `Centre.__post_init__`, which has no board). A suggestion for it (instant): `coordinates=True` is not
  offered (a suggestion never sets it); the offered suggestion is "Place C4 by a relation" where a relation can be measured
  (below), otherwise none.
- *Release n+1*: the refusal. `migration.md` gets a "To <n>" section under "### Changed" naming the warning and the flag with
  the before and after of one declaration, and a line in "Patterns in older scripts" ("a numeric `Centre`: write
  `coordinates=True`, or a relation"); the next release's section says the refusal. `api.md`'s `Centre` entry and the
  skill's placement text say the flag and the rule. The tests that use numeric `Centre` axes (21 files) take
  `coordinates=True` in the same commit as the refusal, and one test per behaviour covers the warning in release n.

**What a script writes.** `coordinates=False` is the default and is never written. An intent `Centre` is written with its
two axes, or one axis and `None`, and nothing else; `coordinates=True` appears only on a deliberate coordinate escape hatch.
`SKILL.md` and `api.md` say this plainly, in the placement text and at the `Centre` entry, and the migration text gives the
before and after of a declaration. Suggestions, and any code that writes scripts (`freeze.py`, the studio's edits, the
probe), never emit `coordinates=False`; removing the flag, when a placement moves to intent, removes the keyword entirely.
I would add a small notice: a script that writes `coordinates=False` explicitly gets a `setup` notice, cause
`setup.centre_flag_default`, facts `{item}`, rendered "c4: coordinates=False is the default: leave it out", with an instant
suggestion that removes the keyword (`remove_kwarg coordinates`). It costs one cause and a renderer, and it keeps scripts
and the skill's example from carrying a keyword that says nothing. It ships with the flag (phase 4b).

**What suggestions may do.**

- A suggestion edits a `Centre` only when it has no `coordinates=True`, that is, when every axis is already intent. It never
  sets `coordinates=True` and never writes a number into any `Centre` or `Location` axis. It never edits a `Location`.
- One direction is allowed, toward intent: a suggestion may turn a coordinate placement (a `Centre(..., coordinates=True)`
  or a `Location`) into an intent form: references to other items or pads (`Centre(X(pad), Y(pad))`), a `Mid`, the board's
  edges or middle, or a `Beside` / `OnEdge` relation, removing the flag. Never the reverse. The relation is chosen from
  facts the sites record (the item's nearest placed neighbour and the side it stands on, the edge it is nearest, the measured
  offset only if it is a clearance that a rule names), and where none can be measured the suggestion is not offered.
- **"Slide C4 along its line" is restored for an intent `Centre` only.** For `at=Centre(X(pad), Y(pad))` (or one axis a
  reference and the other `None`), the lever sets one axis to `None` (`set_arg` inside the `Centre`, value `None`), leaving
  the item free along that line, with the other axis's reference unchanged. It needs the nested edit (phase 5). It makes
  sense under this rule because it writes no number and removes a reference's pin rather than adding a coordinate; it is
  offered for `fixed.part` where the part is pinned on both axes by references. It is not offered for a `Centre` with the
  flag or for a `Location(x, y)`.

## Cases, instant and searched

The tables under "Cases and suggestions" keep their wording. Their levers are classified here by what they need. "Facts"
is phase 1; "ops" is phase 2; "search" is phase 3.

| Lever | Needs |
|---|---|
| `board.rule` clearance from the shortfall (`copper.meets`, `setup.pitch`); the via at a free spot near the met pad; a `Past`/`Between` waypoint on the declared leg; a pad out of a pour; a rider let be searched; thin the drops of the owning cell; `swallow_pads=True`; `fixed.keepout` and `fixed.cutout` figures | facts (instant), with the ops that exist |
| the frame's size (`setup.frame_reach`); the web from the measured gap; "Take R6 out of the row"; a satellite on its own; the back layer through a via; slide along its line (an intent `Centre` only) | facts, plus a site or a nested or multi-edit op |
| a blocker's gap or side; the search radius; a fanout depth; a turn; a chamfer or arc radius; a label size; a stitch pitch; `bend=`; the tuning limits | search |

## Charter fit, added

- *A project-agnostic tool*: facts name what the script and netlist name, never a project; the golden file holds fixture
  modules' own findings, which are fixtures.
- *Tunables are settings*: the probe's budget and candidate limit are settings; no multiplier remains.
- *Judged as KiCad judges*: a clearance rule from a measured shortfall lowers a rule, so it is a diff the user chooses; a
  probe resolves in memory and writes nothing.

## Cases and suggestions

Forms are those in `api.md` at this version. Each row's wording uses the
names from the finding. Rank follows the order of the list. A case or
circumstance not listed gives no suggestion. "on X" means the edit is to X's
declaration, where X is a blocker or neighbour the finding names.

### unplaced

| Case | Suggestions | Edit |
|---|---|---|
| `unplaced.search`: no legal spot within R of the hint | 1. "Place C4 beside C1, on its <free side> side": one per free side the site measured, up to 3 per lever. 2. "Place C4 before the parts that crowd it". 3. "Let C4 take the back face too". 4. "Let C4 turn to any bearing" for an item on a point; "Let C4 take all four turns" where it is restricted. 5. "Move R2 above C1" / "Place R2 beside U1 with a wider gap": `on` the blocker named by the dominant refusal. 6. "Search C4 within a larger radius". 7. when the dominant refusal is a drawn envelope: "Judge parts by their courtyards" | `set_kwarg at=Beside(...)`, `priority=Priority.HIGH`, `face=Face.EITHER`, `rotations=`, `set_kwarg` on the blocker, `radius=`, `toml_set place.envelope` |
| `unplaced.search`, dominant refusal a reservation | by the reservation's source: "Let C4 into keepout `ant`" (`Part` added to `allow=`); "Stop the label of J1 reserving room" (`reserve=False`); "Shorten the fanout of U1" (smaller `depth=` on `board.fanout`) | `edit_list allow`, `set_kwarg` |
| `unplaced.search`, dominant refusal copper | "Let the SIG track avoid C4's spot": a `Past` waypoint on the track, and the items above | `edit_list` on the track's points |
| `unplaced.search`, a via could not give way | "Thin the drops of cell X" (`drops=Drops.HALF`); "Let a via move further: place.via_move"; "Let a via leave its pad further: place.via_leave" | `set_kwarg`, `toml_set` |
| `unplaced.search`, a rider refuses | "Place R3 (rides C4) beside C4 with a wider gap", or "Let R3 be searched" | `set_kwarg at=` or `remove_kwarg at` on the rider |
| `unplaced.pocket`: no pocket fits | "Pull C4 toward U1 pad 3" (a `board.link`), "Place C4 beside U1", "Let C4 take the back face too", "Search C4 on a finer step" | `insert_statement board.link`, `set_kwarg` |
| `unplaced.slide`: no room along an edge, line, row, run or ring | "Put C4 on the <other> edge" (`OnEdge`), "Turn C4" (`rotation=`), "Take R6 out of the row" | `set_kwarg at=OnEdge(...)`, `edit_list` on the row's items |
| `unplaced.block`: cannot lay out / no legal spot | "Place satellite R3 on its own", "Let the block turn to any of its turns", "Let satellites stand further off: place.block_gap_reach" | `edit_list` on `satellites=`, `insert_statement board.place`, `set_kwarg`, `toml_set` |
| `unplaced.bearing` | "Step bearings finer: place.bearing_step" | `toml_set` |
| `unplaced.rides` | none; the parent's own finding is the fault | - |

### fixed

| Case | Suggestions | Edit |
|---|---|---|
| `fixed.part`: a decided part not legal | "Let C4 be searched" (drop its `at=`), "Move C1 above ...": on the other item named, "Take C4 on the back face" | `remove_kwarg at`, `set_kwarg`, on the other item |
| `fixed.cutout`: web under the minimum or touching the outline | "Place cutout `vent` against the connector's edge instead", "Make the web 1.0 mm" (the minimum, from the finding) | `set_kwarg at=` on `Cutout`, `set_kwarg web=` on the outline form |
| `fixed.keepout` | as `fixed.part`, on the keepout's `at=` and `margin=` | `set_kwarg` |

### copper

| Case | Suggestions | Edit |
|---|---|---|
| `copper.meets`: a track, via or pour meets another net's copper, pad or hole | 1. a track whose waypoints steer it into a pad: "Draw the SIG track pad to pad" (waypoints removed). 2. a chamfered or arc corner: "Cut the corner of the SIG track smaller" (`chamfer=`, `radius=` smaller, measured). 3. "Route the SIG track past U1 pad 4" (a `Past` or `Between` point). 4. "Put the SIG track on the back layer". 5. a via: "Put the via at the nearest free spot to U1 pad 4" (`FreeSpot(near=PadRef(...))`). 6. a pour of exact points: "Fit the GND pour to its pads" (`swallow_pads=True`). 7. "Lower the clearance between SIG and GND to 0.15 mm" (`board.rule`) | `edit_list`, `set_kwarg`, `insert_statement` |
| `copper.keepout`: copper crosses a keepout | "Let net SIG into keepout `ant`" (`allow=`), "Keep keepout `ant` off the back layer" (`layers=`), "Let keepout `ant` forbid parts and vias only" (`excludes=`) | `edit_list`, `set_kwarg` |
| `copper.cross`: two tracks cross and neither may bridge, or one crosses a fixed track | "Let the SIG track pass under GND" (`bridge=True`), "Let GND yield to SIG" (`priority=`), "Put the SIG track on the back layer, through a via" | `set_kwarg`, `edit_list` |
| `copper.corner`: the 45 past a corner leaves no 45 | "Take the SIG track's corner past U1 further out" (`across=`), "Bend the SIG track at its end" (`bend=`), "Cut its corner smaller" | `set_kwarg`, `edit_list` |
| `copper.not_drawn`: a declared track, via, pour or stitch not drawn | by the cause the note names. An arc that does not fit: "Use a smaller radius on the SIG track". A track through an item: as `copper.meets`. A pour with no way round: "Take pad 5 out of the GND pour". A stitch with no room: "Stitch GND at a smaller pitch" (`pitch=`, `size=`) | `set_kwarg`, `edit_list` |
| `copper.note` (notice): a waypoint drawn pad to pad | "Drop the waypoint" | `edit_list` remove |

### escape, pair, link

| Case | Suggestions | Edit |
|---|---|---|
| `escape_walled`, `escape_closed`: a pad closed or walled in by C1, R2 | "Move C1 further from U1" (a wider gap in its relation, or another side), "Keep U1's north side clear" (`board.fanout(u1, depth=, sides=)`), "Turn U1", "Keep the lanes of U1 pins 3 and 4 clear" (`board.escape`) | `set_kwarg`, `insert_statement` |
| `escape_crossed`: escapes of U1 pins 3 and 4 cross | "Turn U1 so the pins' targets match their order", "Place R2 on the side of U1's pin 4" | `set_kwarg rotation=`, `at=` |
| `escape_lane`: a declared lane blocked by C1 | "Move C1 off the lane", "Stand the lane's via further along" (`depth=`, `vias=`), "Allow the lane's via further: place.escape_via_reach" | `set_kwarg`, `toml_set` |
| `pair_crossed`: DP and DN cross between U1, U2 | "Swap R7 and R8 in the row" (the pair's parts), "Turn U2 by 180 degrees" (`rotation=Turned(u2, 180)`) | `edit_list` move, `set_kwarg` |
| `link_over`: C1 pad 1 to U1 pad 3 is 5.1 mm, over its 4.0 mm limit | 1. "Place C1 beside U1". 2. "Pull C1 to U1 pad 3 harder" (`weight=`). 3. "Place C1 before the parts that crowd it". 4. "Raise the limit to 5.1 mm" (a named constant holding the measured figure) | `set_constant`, `set_kwarg` on the link |

### label

| Case | Suggestions | Edit |
|---|---|---|
| `label.sits_on`, `label.no_spot` | "Move the label of J1 to its south side" (one per side not tried), "Make the label of J1 smaller" (`size=`) | `set_kwarg side=`, `size=` |
| `label.not_drawn` (notice) | none | - |

### setup, vias

| Case | Suggestions | Edit |
|---|---|---|
| `setup.undeclared`: no declaration places C9 | "Place C9 searched from its links" | `insert_statement board.place(c9)` |
| `setup.lane_unused`: U1 pin 3's lane reserved, no track | "Draw a track from U1 pin 3's lane", "Take pin 3 out of U1's escape" | `insert_statement board.track`, `edit_list` on `pins` |
| `setup.pitch`: net class does not fit the pads' pitch | "Lower the clearance within U1 to 0.15 mm" (`board.rule(..., within=)`, the figure that fits) | `insert_statement board.rule` |
| `setup.frame_reach`: an item outside a fitted frame's axis | "Make the frame 30 mm high" (the item's extent), "Place R6 inside it" | `set_kwarg height=` |
| `setup.accept`: an `accept` that matched nothing or was not needed | "Remove the accept for keep-out SIG" | `remove_statement` |
| `vias` warnings: a via dropped, fewer than declared | "Let a via move further: place.via_move", "Let a via leave its pad further", "Thin the drops of cell X" | `toml_set`, `set_kwarg drops=` |

The kinds `fab`, `facts`, `split`, `route`, `needs`, and the notices of
`vias` and `setup` (a layer the board lacks, a rule not carried, a look-ahead
dropped) have no script edit, so they have no suggestion.

## Charter fit

- *Intent, not coordinates*: an edit writes relations (`Beside`, `OnEdge`,
  `Past`, `Between`), keywords (`face=`, `priority=`, `bridge=`, `allow=`,
  `weight=`) and settings, never a `Location`, an offset or a `reach=`
  distance. A number in an edit is a measured fact from the finding (the limit
  a link achieved, the clearance that fits), written as a named constant
  with a comment saying where it came from, and the diff shows it before it
  is written.
- *Judged as KiCad judges*: lowering a clearance or a limit is a suggestion
  the user sees as a diff and chooses; nothing is applied without the click or
  the command.
- *Project-agnostic*: the module, the table and the tests name forms, never a
  project, board, part or net.
- *Tunables are settings*: no weight, threshold or share in `suggestions.py`.
  The dominant refusal is the one with most refusals, ties broken by the
  order `_blame_text` lists them; the limit of 3 suggestions per lever is a
  setting, `[studio] suggestions_per_lever`.
- *Fitted, never zones*: no suggestion turns a pour into a zone or a plane.
- *Decide alone / ask first*: placemat's agent builds this; applying a
  suggestion to a project's script is the user's act in the studio or the
  command line.

## Phases

The original phases 1 to 3 are built on branch `suggestions-core` (the engine, the studio-facing API, the command line;
the studio's slot, Try and endpoints are the studio branch's). The revision adds three, in this order, because each
unlocks the next.

**Phase 4: structured data (the rule, "The rule" above).** Step 0: the golden findings file and its test, written from main. Then the plumbing
(`Finding(kind, cause, facts)`, `finding_text.py` with a schema and a renderer per cause, `Conflict`, `Blocker` and
`ScanResult.samples`, the reuse record version, `facts` and `facts_v` in `run.json`, `preview --json` and the studio's
plan JSON), then the sites in the table above, one cause or area to a commit, each with its golden rows. Every producer in "Producers and consumers the rule changes" returns data, and every consumer in that table reads it; the
rule's source search is a test (`tests/test_no_sentence_parsing.py`). The core's
builders switch from their ad hoc facts dicts to the schemas (the facts they use already are fields). The core's
`suggestions` no longer enter the cache. Enables, as instant suggestions with ops that exist today: the clearance rule from
a measured shortfall (`copper.meets`, `setup.pitch`), the via at a free spot near the met pad, a waypoint on the declared
leg, a pad out of a pour, a rider let be searched, thin the drops of the owning cell, `swallow_pads`, and the `how` field
(all are `instant` here; the searched ones are listed but have no probe yet).

**Phase 4b: the `Centre` flag and its migration** (a small phase of its own, before phase 5). It is an API change with a
two-release migration, independent of the structured data and of the edit operations, so it ships as its own change and
can ship before phase 4 is finished; its release n is the warning, n+1 the refusal. Phase 5's rules about editing a
`Centre` need only that the flag exists (a suggestion tells an intent `Centre` from a coordinate one by the flag), so
phase 5 starts after release n. Contents: `Centre(coordinates=False)`, the `setup.centre_coordinates` warning, the refusal
in the following release, the migration text, the tests' flag, `api.md` and the skill.

**Phase 5: edit operations.** Nested edits, multi-edit suggestions, the sites for `rect`, `disc`, `outline`, `row` and
`block`. Enables: the frame size (`setup.frame_reach`), the web from the measured gap (`fixed.cutout`), slide along its line (an intent `Centre` only),
"Take R6 out of the row", a satellite on its own, the back layer through a via, and the nested figures the probe sets (a
`Beside`'s gap, a `Past`'s `across=`).

**Phase 6: searched suggestions.** `probe.py`, the `--search` flag, the studio's "search options", the channel events,
the probe settings, the results file and resume, and the removal of `studio.suggest_factor`. Enables the searched rows: a
blocker's gap or side, the search radius, a fanout depth, a turn, a chamfer or arc radius, a label size, a stitch pitch, `bend=`,
and the tuning limits (`via_move`, `via_leave`, `bearing_step`, `block_gap_reach`, `escape_via_reach`) where their bounds
can be given.

The core's `suggest_factor` suggestions are removed in phase 4, with the setting: a wider radius, a finer step, `via_move`,
`via_leave`, `block_gap_reach`, `escape_via_reach`, `bearing_step` and the smaller label, chamfer and arc radius are not
offered until phase 6 (or an instant lever) has a measurement behind them. The arc radius is offered where the misfit measures
it (the radius times the leg's length over what its arcs take).

### As built in phase 4

`refusals.py` holds `Refusal` (a code and JSON facts; `str()` renders its sentence, `bucket` is what a scan counts it under),
`Owner` (who a refusal blamed, hashable, so the scan's `blockers` counter keys on it) and `ReservedBy` (what a reservation was
made by); `blame.py` turns a scan's counts into the facts of a blame, and `finding_text.py` renders every cause, a blame and
the notes a step carries. Occupancy, the edge shapes (`EdgeWhy`, not a sentence), the give-way search, the lanes, the queries,
the adopted routes and the cutout checks return them. A `Step` has `unplaced`, `lock` and `pocket` fields where consumers read
the note. Not converted, because they are not findings and no consumer reads them: the `Step.note` log lines (rendered from
the same data where a finding shares them), the plane-mismatch lines of `placemat facts`, and exception messages for script
errors.

### As built in phase 6

`probe.py`; `Suggestion.figure` and `Pick.how`/`figure`; the builders; `placemat apply <id> --search [--yes]`; the channel events
`probe`, `candidate`, `probe_done` (`channel.paused` keeps the candidates' own resolves off the channel); `[studio] probe_budget_s`
and `probe_candidates`; the results file `.placemat/probes/<id>.<key>.jsonl`; `suggestions.add_found`/`keep`; the studio's
`POST /suggest/probe` and `/suggest/probe/stop` (`Studio.probe_start`, `probe_stop`, the command summary's `probe`). Details are in
`api.md`, "Findings and severities". Where it differs from the design above:

- The probe runs as its own command (`placemat apply <id> --search --yes`, started by the studio as it starts a run) and resolves in
  its own process through `previewer.resolved(..., overlay=)`, the same overlay as the worker's try, rather than inside the warm
  worker. The worker stays free and the events are the command's, read through the channel like an explore's.
- Searched rows with a measurement behind them today: the chamfer of a corner (`copper.corner`: `near_mm`, `need_mm`, the declared
  `chamfer_mm`) and of a cut (`copper.meets` with `chamfer_hit`: the refusal's `gap_mm` and `need_mm`), the arc radius of a cut,
  and `bend` (`copper.corner`). The range is the declared value down by twice the shortfall. The other rows of the table (a
  blocker's gap, search radius, fanout depth, turns, label size, stitch pitch, `bearing_step`, the five tuning limits) are not offered:
  their findings do not record the number that would bound them, and "no measurement, no suggestion" governs. They return with a site
  that records it.
- The judge compares findings by `finding_key`; the run score breaks ties. A set (`bend`) is every member in order.
- A probe is "board-wide" (it asks to confirm) when any edit is not to a `place` declaration.
- A bisection's resolution is the figure's `resolution` (0.01 mm) and its steps are bounded by `probe_candidates`, which is
  `probe_steps` plus the far end and the neighbour check.

### As built in the studio page (search options)

Under a searched suggestion's row (finding rows, the card, the step rows) the page draws what the probe command reports, from the channel's
`probe`, `candidate` and `probe_done` events kept in the command's summary: before it starts, the estimate's line on a confirmation
(only when the probe is board-wide); while it runs, "n of up to N candidates", Stop, a strip chart of the figure's range (the declared value
marked, each candidate a dot: cleared, not cleared, error) and a list of each candidate's value, result, findings gained, score and seconds
(`saved` for one taken from an earlier probe); when it ends, the outcome worded from `state` and `best` and, for a best, the found
suggestion `<id>.1` with Show, Try and Apply. The plan does not know `<id>.1`: the page reads it with `GET /suggest/found?id=`, and show, try
and apply find it in the store beside the plan's own suggestions. A stopped, budget- or limit-ended probe offers Continue (the same start,
confirmed). The probe is matched to its row by suggestion id and text, so a probe of an earlier plan is not shown on a new plan's row.

### The original phases

1. `Finding.case` and `suggestions`; `script_edit.py` with `set_kwarg`,
   `remove_kwarg`, `edit_list` and the undo; the cases of `unplaced`,
   `fixed`, `copper.keepout`, `copper.cross`, `link_over`, `label`; the
   `suggestions.apply_suggestion` with `dry_run`; the studio's slot, Show,
   Apply and Undo; the applied log.
2. Try (the worker's overlay and the compare of a try); `escape_*`,
   `pair_crossed`, `copper.meets`, `copper.not_drawn` and `setup`;
   `insert_statement`, `remove_statement`, `toml_set`.
3. The command line: `try` lines, `run.json`, `placemat apply`; `api.md` and
   `SKILL.md` text.

## Out of scope

- A free-text editor in the studio page. The script view applies edits that
  suggestions make, and shows them; typing in it stays with the user's editor
  and agents.
- Applying several suggestions at once, or a "fix all".
- Suggestions for design-check verdicts and DRC violations, which are not
  findings.
- Learning from what worked before, and any estimate of how likely a
  suggestion is to clear a finding. The try measures it.
- Changing a finding's kind, severity or sentence, or the run score.

## Testing

All tests use small synthetic boards and scripts, in the style of the
existing findings and studio tests, with generic names (`U1`, `C1`, `R2`, a
net `SIG`); no project or board name appears in a test, a table row or a
fixture.

- `tests/test_script_edit.py`, pure text in and out:
  - each op on a one-line call, a multi-line call with a trailing comma, one
    without, a call with a comment after an argument, a call with `*args` or
    `**kw`, and a keyword already present. Comments and layout outside the
    edited node are pinned byte for byte (the text before and after the node
    is compared as strings, not through `ast`); the result parses; the `ast`
    of everything outside the target is equal; an edit that would change
    anything else is refused;
  - removing a keyword whose line ends in a comment (`face=Face.FRONT,  #
    keep it on top`): the comment survives, on the previous argument's line or
    where the removed line stood, and the closing parenthesis keeps its indent
    and line;
  - a keyword added to a multi-line call goes on its own line at the call's
    argument indent, in the call's trailing-comma style, for a call with a
    trailing comma and one without, and the closing parenthesis is unmoved;
  - a script that spells an item as a variable, as `Part("c1")` and through
    an alias gets the script's own spelling in the value;
  - a target call that declares several items (a loop) is refused; a call not
    found exactly once is refused; a changed digest is refused;
  - `edit_list` add, remove and move (a comment on a removed element survives
    as for a keyword); `toml_set` into an existing table, a new key, a new
    table, and a table for another script left alone, with the rest of the
    file byte for byte; `undo` is the exact inverse, and refuses when the text
    is not the one the edit made;
  - `set_constant`: a script with no constants block gets one after its
    imports; one with a block gets the constant at its end; the comment is
    present; a name already bound in the file or an imported module gets a
    counter and nothing is overwritten; a board-wide value goes to the shared
    module when the script imports one and to the board's script when none is
    imported; a cell's value goes to the cell's script; a value from a
    constant gives both variants, and changing the constant changes every use
    in the diff; a geometric derivation is inline and adds no constant; no
    edit writes a bare figure into a call.
- `tests/test_finding_suggestions.py`:
  - every `case=` raised in `src/placemat` has a builder in `suggestions.py`
    and every builder is raised somewhere (by scanning the source);
  - for each case, a synthetic script that produces the finding: the
    suggestions name items and pads that exist in the plan, rank is 1..n, and
    each edit applied to the script gives a script that parses and whose call
    has the keyword written (checked against `inspect.signature` of the board
    method, the enum against `placemat`'s exports, a setting against the
    settings table);
  - the edits that claim to clear a finding do: for a waypoint, a chamfer, a
    bridge, an allow, a link weight and a priority, the edited script is
    resolved and the finding is gone;
  - no value an edit writes is a `Location`, a coordinate pair, `reach=` with a
    number, `board.figure`, or `board.plane` for a pour;
  - the cache and pickle keep `case` and `suggestions`; a three-field cache
    entry loads with none.
- One path: the studio's endpoints and `placemat apply` call
  `apply_suggestion` (a test replaces it and sees both call it); a suggestion
  read from a studio plan equals the one in `run.json` for the same script.
- Studio: `/suggest/show` returns the diff and writes nothing; `/suggest/apply`
  writes the file, appends the log, and the watcher resolves the result; a
  file changed between the plan and the apply gives a conflict and no write;
  `/suggest/undo` restores the text and refuses when the file has moved on;
  the endpoints refuse a request without the token and a body that names
  anything but a resolve, a finding and a suggestion; with `[studio] apply =
  false` apply is refused.
- Try: the worker resolves with an overlay and the file on disk is not read
  for the overlaid file or touched; a try does not change the next real
  resolve's reuse; a change to a watched file cancels a try; a try reports the
  finding cleared when the edit clears it and reports findings gained when it
  adds one.
- Page: the slot is empty and hidden for a finding with none, shows rank 1 and
  "more" for several, Show marks the changed lines, and the try result renders
  in the compare view marked as not written.
- `run` prints a `try` line under critical and
  warning findings only; `run.json` carries the suggestions and the digests;
  `placemat apply <id> --dry-run` prints the diff and writes nothing; apply
  refuses when the script changed since the run, and with an unknown id;
  `--undo` matches the studio's.
- The existing suites for findings, severity, reuse, the studio and the report
  pass. `fixtures/bench.py --jobs 2`: no score moves (no placement or finding
  sentence changes).

## Decided with the user (2026-10-03)

- Up to 3 suggestions per lever, best first; Try tells them apart.
- Try runs only on a click, never on its own.
- Edits whose target call places several items (a loop or helper) are not
  offered yet; a later phase may add them.
- Setting suggestions may edit the script's settings table in `placemat.toml`
  with a line-level edit that keeps the rest of the file byte for byte.
- Apply is allowed when the studio listens on a LAN address (`--host`); the
  token every request needs guards it.
- Undo is a stack: each undo reverts the last apply only if the file still
  matches what that apply wrote, otherwise it refuses and says so.

## Later work that builds on this

A later spec, a board builder in the studio (an outline from simple shapes,
parts placed by intent, the script written as it goes; first for new boards,
later for existing scripts), will use this engine's edit ops and its one
application path. The ops therefore cover inserting statements (`board.rect`,
`board.disc`, `board.outline`, `board.place` with an intent, a search over the
rest) as well as changing keywords. `board.rect` (renamed from `board.size` in
0.85.0) is the form the spec uses for a rectangular outline.

## Decided with the user (later on 2026-10-03)

- No suggestion edits `Centre(...)` or `Location(...)`, or writes any coordinate; nested edits are for intent forms
  (`Beside`, `Past`, a `Cutout`'s relation).
- A probe over a board-wide value is allowed, with an up-front warning and an estimate from the last resolve's time.
- The suggestion record has `edits` and `how` and no `edit`.
- Phase 4 converts every site before release; no mixed state ships, enforced by a test.
- Sentence templates in one `finding_text.py`; a changed facts schema invalidates the reuse record.
- `Centre(..., coordinates=False)`: a plain number is refused unless `coordinates=True`; a warning for one release, then the
  refusal; `Location` is coordinates only and never edited; suggestions never write a coordinate or set the flag, and may
  turn a coordinate placement into an intent one (see "`Centre` and `Location`"). "Slide along its line" returns for an
  intent `Centre` only.

## Open questions

None. Closed with the user: the tuning-limit values follow the rule above (derived from a measurement the finding carries,
else no suggestion); bisection checks the end value and a neighbour and reports a non-monotone result as such; one
`FindingCause` enum of `(kind, string)` members; the `Refusal` record is measured on the scan hot path in phase 4 (the bench's
resolve times, with and without, on the same machine) and kept only if the cost is negligible, otherwise the scan counts by an
enum bucket and builds the record only for the samples it keeps.
