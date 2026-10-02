# Finding suggestions

Date: 2026-10-02
Status: design, for the user's answers to the open questions
Source: the user, 2026-10-02: "suggestions for resolving findings would be
great". Follows `findings.py` (kinds and severities) and the studio's Findings
tab, whose rows already hold an empty `fixslot`.

## Problem

A finding says what placemat could not do as declared. It rarely says what
to change in the script. A person or an agent reading `[critical] U1 pin 8
(GND): walled off by R2, U1` has to know that the neighbours' declarations,
`board.fanout`, or the escape settings are the levers, and which of them is
cheapest. Some findings already carry advice inside the sentence (a keepout
crossing: "move it, reshape it, or name its net in the keepout's allow=";
a pair crossing: "swap two interchangeable parts ... or turn a part"; a
pitch: "a clearance of 0.15 mm or less fits"; a chamfer: "a smaller chamfer=
there keeps clear"), and most carry none. The advice that exists is prose in
one sentence, so no page or agent can use it apart from the text.

What exists to build on:

- `Finding(kind, text, severity)`, a `str` that says where it was made
  (`findings.py`), pickled and stored in the reuse cache as `[kind, text,
  severity]` (`reuse.py`).
- `run.json` `finding_details` (`kind`, `severity`, `text`), `preview
  --format json` `finding_details`, and the studio plan JSON, where each
  finding has `text`, `kind`, `severity`, `at` and `item`
  (`preview_json._findings`).
- The studio page: a `fixslot` span in each finding row, hidden while empty,
  and a map from an item to the script line that declared it (`sites`) that
  the linked script view already uses.
- The script surface in `api.md`: the forms, keyword arguments and settings a
  suggestion would name.

## Design

### What a suggestion is

A suggestion is one change to try, naming the real form it is made with.

```
Suggestion
  text        one sentence, imperative, saying what to change and why it helps
  ref         what it names, as a machine-checkable reference (below)
  owner       where the change is made: script | setting | capture | fab | command
  on          the item key whose declaration changes, when it is not the
              finding's own item (a neighbour that blocks, a rider)
  rank        1 is tried first
  checked     true when the place that raised the finding measured that the
              change clears it (the waypoint dropped, the clearance that fits)
  asks_user   true when the change is a fact or an exception the agent does
              not decide alone (CHARTER.md, "Decide alone / ask first")
  see         an item key whose own finding is the fault, for a finding that
              is a consequence (a rider of an unplaced item, a label whose
              item found no place); such a suggestion has no ref
```

`ref` is one of:

| ref | names | example |
|---|---|---|
| `call:board.X#kw` | a keyword of a `board` method | `call:board.keepout#allow` |
| `form:Name` | a script value or class | `form:Face.EITHER`, `form:Past` |
| `setting:section.key` | a `placemat.toml` key | `setting:place.via_move` |
| `command:...` | a placemat command and flags | `command:facts --confirm` |
| `file:path#key` | a key in a project file that is a board fact | `file:fab-profile.json#min.track_mm` |

`text` is what is shown. `ref` is what is checked (see Testing): a suggestion
whose ref does not resolve is a failing test, so the table cannot name a form
that does not exist or has been renamed. The script line is not stored. It is
the declaring line of the finding's item, or of `on`, and the output layer
fills it from the same `sites` map the studio already builds.

**Ordering, not confidence.** There is no probability. A number would be
invented, and the charter keeps tunables in settings. `rank` is the order to
try, from the change that touches the least intent to the one that touches the
most:

1. remove something placemat flagged as the likely cause (a waypoint that
   steers into a pad);
2. change a declaration of the finding's own item;
3. change a declaration of a neighbour the finding names;
4. change a tuning setting;
5. change a board fact, accept a verdict, or run an explore.

`checked` is the only claim of certainty, and only where the code that made
the finding measured it. `asks_user` is true for rank 5 forms that change a
fact (`web=`, a net class value, `fab-profile.json`, `board.size` numbers, a
link's `limit_mm=`, `board.rule(clearance=)`, `board.accept`).

**What a suggestion never is.** A coordinate, an offset, a `Location`, a
`reach=` distance with no fact behind it, a zone standing in for a pour, or a
loosened board-wide check limit. The numbers a suggestion quotes are
measurements the finding already has (the clearance that fits, the gap left),
never a value for the user to type in.

### Where they are produced

Two ways to get from a finding to its suggestions:

- **A table keyed by kind.** One place, easy to read, but a kind holds several
  cases (the severity design found the same for `vias`, `copper`, `setup` and
  `label`), and what helps depends on facts only the raising site holds: which
  bucket refused a search, which neighbour walled a pad, whether pad to pad
  would clear. Recovering them by matching the sentence is brittle;
  `preview_json` already regexes `(x, y)` out of text, and it should not grow.
- **At the raising site.** The facts are in hand, but the wording is then
  spread over forty call sites in `layout.py`, which is where the advice
  clauses already live and are hard to find or keep consistent.

The design takes both halves: the **site names the case and passes the facts;
the wording and the ordering live in one module.**

```python
Finding("unplaced", text, case="unplaced.search",
        facts={"dominant": "courtyard", "blockers": ["R2", "C4"], "radius": 3.0,
               "faces": "front"})
```

- `Finding` gains `case` (a dotted id, `kind.case`, "" for none) and `facts` (a
  JSON-safe dict, empty for none). Neither changes the sentence, its equality
  or its severity.
- `suggestions.py` holds `CASES`, a table from case id to an ordered list of
  rules. A rule is a function from `facts` to a `Suggestion` or `None`, so a
  rule that depends on a fact (`dominant == "reservation"`) returns nothing
  when it does not apply. `suggestions_for(finding)` runs them, drops the
  `None`s, numbers `rank` in order, and returns the list.
- A site passes `case=` and `facts=` where it is made, which is where the
  severity is already passed for mixed kinds. A site that passes nothing gets
  no suggestions, and that is allowed: a kind or case with no known lever is
  listed as a gap in the table below, not given a vague one.
- The facts are only what a rule reads: the bucket counts and owners
  `_blame_text` already computes, the pad and the blockers `escapes` returns,
  the net class and figure in `fab_min_findings`. No fact is computed only for
  a suggestion that the raising code did not already have.

Suggestions are computed when read, not when the finding is raised. The reuse
cache then stores `[kind, text, severity, case, facts]`; an entry without the
last two (a cache from before this) loads with none and gives no suggestions,
as an entry without a severity took the kind's. A change to the wording in
`suggestions.py` shows on the next run without invalidating any reuse entry.

Plain-string copper notes. About thirty `ctx.notes.append("...")` sites in
`layout.py` (a track not drawn, a pour not drawn, a via with no spot, a
stitch with no room) are plain strings that `_plan_copper` turns into
`Finding("copper", n, "warning")`. They have no case. Each is converted to a
`Finding` with its case when its suggestions are written (phase 2); until then
those findings show none.

### How they reach the outputs

- **Console** (`run`, `preview`): the `[severity] sentence` lines do not change.
  Under each printed `critical` finding, one more line, `    try: <text>
  (<form>)`, for the rank 1 suggestion (open question 2).
- **`run.json`**: `finding_details[i]` gains `suggestions`, a list of
  `{text, ref, owner, on, rank, checked, asks_user, see}` in rank order. A
  record without the field reads as none. `RunRecord.findings_with_severity()`
  passes it through.
- **`preview --format json`**: the same `finding_details`.
- **Studio plan JSON**: each finding in `findings` gains `suggestions`, with
  `line` added to each (the declaring line of the finding's item or of `on`,
  from `sites`), and the `findings` event carries them. The studio keeps its
  rule of drawing the plan's JSON, so the page adds no logic about kinds.
- **The studio page's fix slot**: `fixslot` shows the rank 1 suggestion's text
  and its `ref` as code, a badge "asks you" when `asks_user`, a badge
  "checked" when `checked`, and a "more (n)" control that opens the rest in
  rank order. A suggestion with a `line` has a "show line" control that
  selects that line in the script view, the same selection a click on an item
  makes. A suggestion with `see` has a "go to" control that selects that
  item's finding. A finding with no suggestions keeps its slot hidden. The slot
  is read only: nothing in the page edits the script.

### How the skill documents use them

- `api.md`, "Findings and severities", gains a "Suggestions" subsection: the
  shape above, `owner` and `asks_user`, and the table of cases, kept in step
  with `suggestions.py` by a test (every case id appears in `api.md`).
- `SKILL.md`, "When a track or a placement fails", gains a short paragraph:
  read `finding_details[i].suggestions` after reading the finding as a claim
  about the script; try them in rank order; take `script` before `setting`;
  a suggestion with `asks_user` goes to the user with the reason and is not
  applied alone; a suggestion is a candidate, and the run decides whether the
  finding cleared. The paragraph says what to do with a `checked` suggestion
  (apply it, run) and with a finding that has none (the old advice stands:
  read the claim, remove waypoints, look at the placement, then the tool).
- The migration note names the new field and the studio slot.

## Cases and suggestions

Forms are those in `api.md` at this version. "Owner" is where the change is
made. Rank follows the order of the list. A row with "gap" names a case with
no form that resolves it; those give no suggestion. `on` is the blocker or
neighbour the finding names.

### unplaced (critical)

| Case | Facts at the site | Suggestions in order | Owner |
|---|---|---|---|
| `unplaced.search`, no legal location within R of the hint | refusal buckets and owners (`_blame_text`), radius, faces, whether seeded | 1. when `dominant` is `reservation`: the reservation's source decides: a keepout, `board.keepout(..., allow=(Part(..),))` or a narrower `excludes=`; a user label, `reserve=False` on `board.label`; a fanout, a smaller `depth=` on `board.fanout`; an escape lane, see `escape_lane`. 2. `priority=Priority.HIGH` on the item, so it is searched before what crowds it. 3. `face=Face.EITHER` where either face is allowed. 4. `rotations=` with more turns (`Turns.ANY` for an item on a point). 5. `on` a blocker: its `at=` relation or gap (`Beside(..., gap=)`). 6. `radius=` larger, or `place.radius`. 7. `place.envelope = "courtyard"` when `dominant` is a drawn envelope (silk, mask, body). 8. a larger frame: `board.size` (asks the user; on a fit frame `place.fit_room`). 9. `command:preview --explore SECONDS --focus ITEM` | script, setting, command |
| `unplaced.search`, `dominant` is `copper` | the copper's net and owner | 1. move or reshape the declared track, via or pour the refusals name (its `Past`/`Between` points). 2. `priority=Priority.HIGH` on the item. 3. the items above | script |
| `unplaced.search`, `dominant` is `through`, `npth` or `hole-to-hole` | the holes' owners | 1. `rotations=`. 2. `face=Face.EITHER`. 3. gap: the holes are the part's own; moving the other part is the only lever, as `on` | script |
| `unplaced.search`, `dominant` is a via that could not give way | steps tried, per `giveway.py` | 1. `drops=Drops.HALF` on a cell. 2. `place.via_move`, `place.via_share`, `place.via_leave`, `place.via_relay`, `place.via_route`, `place.drops_keep`. 3. the fab profile's micro, blind or buried tier when the refusal says one would have cleared it (see `needs`) | script, setting |
| `unplaced.search`, a rider refuses | the rider's key and reason | 1. loosen the rider's own firm `at=` (`on` = the rider). 2. let the rider be searched (drop its `at=`) | script |
| `unplaced.pocket`, no pocket fits its envelope | face, pockets tried | 1. seed it: a link (`board.link(a, b)`) or a relation (`at=Beside(...)`, `at=Near(PadRef(...))`). 2. `face=Face.EITHER`. 3. `step=` smaller (`place.pocket_step` is the floor). 4. a larger frame (asks the user) | script, setting |
| `unplaced.slide`, no room anywhere along an edge, line, row, run or ring | rejected buckets | 1. another edge: `OnEdge(other)`. 2. `rotation=`/`rotations=`. 3. on a row, fewer or smaller members or another `board.row(..., behind=)`. 4. gap: no form widens the range, which the edge or line itself fixes | script |
| `unplaced.block`, cannot be laid out on its own / no legal spot | `_block_alone` reasons per rotation, radius | 1. `rotations=` with more turns. 2. place a satellite on its own (`board.place`) instead of in `board.block(anchor, satellites=)`. 3. `place.block_gap_reach`. 4. the items of `unplaced.search` | script, setting |
| `unplaced.bearing`, no bearing leaves it legal on its point | bearings tried | 1. `place.bearing_step` smaller. 2. gap: the point is the user's mechanical fact; moving what blocks it is the lever (`on`) | setting |
| `unplaced.rides` | the parent's key | `see` the parent; no ref | - |

`place(required=True)` stops the run at the first such failure; it is not a
suggestion.

### fixed (critical)

| Case | Facts | Suggestions | Owner |
|---|---|---|---|
| `fixed.part`, a decided part not legal where its relation put it | the refusal bucket, the other item | 1. make it searched: replace the firm `at=` by a relation that leaves a freedom (`Centre(None, y)`) or by none. 2. `on` the other item: its `at=` or `gap=`. 3. `rotation=`. 4. `face=`. 5. gap: where the place is a mechanical point the user gave, only the user can change it | script |
| `fixed.cutout`, web under the minimum or touches the outline | the gap, the minimum | 1. `Cutout(shape, name, at=)`: place it by another relation. 2. `web=` on `board.size`, `board.outline` or `board.disc` (asks the user). 3. a notch belongs in `board.outline(path)` | script |
| `fixed.keepout`, a decided keepout not legal | the reason | the same as `fixed.part` for the keepout's own `at=` and `margin=` | script |

### copper

| Case | Facts | Suggestions | Owner |
|---|---|---|---|
| `copper.meets` (critical): a track, via or pour meets another net's copper, pad or hole | the item kind, the net, the other owner, whether the leg is a chamfer or an arc | 1. track with waypoints that steer it into the pad: drop them (`checked` when pad to pad clears; this is the `copper` notice's case). 2. a chamfer or an arc corner: a smaller `chamfer=` or `radius=` (the site says where; `checked`). 3. a lane waypoint: `Past([...], Edge)`, `Between(PadRef, PadRef)`. 4. another `layer=`. 5. a via: `board.via(net, FreeSpot(near=PadRef(...)))`. 6. a pour of exact points: reshape the points, or `swallow_pads=True` for one fitted to the pads. 7. `on` the other owner: its placement relation. 8. `board.rule(clearance=, within=/between=/on=)` lowers a clearance, a net class `track` or `width=` narrower (asks the user) | script |
| `copper.keepout` (critical): copper crosses a keepout | keepout name, its `excludes`, `allow`, `layers` | 1. reshape or move the copper. 2. `board.keepout(..., allow=(Net(...),))` for a net that may cross. 3. `layers=` on the keepout when it should not cover the layer. 4. `excludes=` narrower | script |
| `copper.cross` (critical): two tracks cross and neither may bridge, or one crosses a fixed track | the two nets, the layer, which yields | 1. `bridge=True` on the track that should pass under. 2. `priority=` to choose which yields. 3. `layer=` another layer for one, with a via as a track point (`board.via(net, ...)`). 4. a lane waypoint to route round | script |
| `copper.corner` (critical): the 45 past a corner leaves no 45 | the corner, the clearance | 1. move the points either side (`Past(..., across=)`). 2. `bend=`. 3. a smaller `chamfer=` | script |
| `copper.not_drawn` (warning): a declared track, via, pour or stitch not drawn | the cause the note names: a via found no spot, a point past an item cannot be placed, an arc does not fit, runs through an item, a pour with no way, a stitch with no room | the cause decides: a via with no spot, see `copper.meets` for the via; an arc that does not fit, a smaller `radius=` or `copper.arc_radius_widths` (the sentence names it); a track through an item, `copper.meets`; a pour with no way round, `on` the item that blocks it, or fewer pads in the pour; a stitch with no room, a smaller `pitch=` or `size=` on `board.stitch`. Gap: a pour has no looser fit, because a fitted pour is never a zone | script |
| `copper.note` (notice): a waypoint drawn pad to pad, stitch vias left out, the side a stitch row took, a track left out whose crossing is a finding | - | the waypoint note: drop the waypoint (`checked`). Stitch vias outside the region: `board.stitch(net, region, edge=, outside=)`. The others: none; the crossing's own finding is the fault | script |

### escape, pair and link

| Case | Facts | Suggestions | Owner |
|---|---|---|---|
| `escape_walled` (critical), `escape_closed` (warning): a pad closed or walled in | the part, pin, net, the blockers (`by`), what it joins | 1. `on` a blocker: a larger gap in its relation (`Beside(..., gap=)`) or another side. 2. `board.fanout(part, depth=, sides=)` so the sides stay clear before the neighbours are placed. 3. `rotation=` for the part. 4. `board.escape(part, pins, turn=)` to reserve the lanes. 5. `place.escape_depth`, `place.escape_pads`, `score.escape_*` so the search weighs it. The off-board handoff case (no other pad on the net) takes 1 and 2 | script, setting |
| `escape_crossed` (warning) | the part, the two pins, the two targets | 1. `rotation=` of the part, so the order of the pins matches the order of their targets. 2. place the two targets on the sides that match the pin order (`on`). 3. `place.escape_depth`. Gap: the pin order is a part and capture fact | script, setting |
| `escape_lane` (warning): a declared lane is blocked | the part, pin, net, the blockers | 1. `on` a blocker: move it. 2. `board.escape(..., vias=, depth=, via_size=, via_drill=)`: another via spot or depth. 3. `place.escape_via_reach` when its via has no legal spot | script, setting |
| `pair_crossed` (warning) | the two nets, the parts | 1. swap two interchangeable parts on the pair: their order in `board.row(items, ...)` or `over=`. 2. `rotation=Turned(part, 180)` for a part whose pinout is mirrored | script |
| `link_over` (warning) | the two pads, achieved and limit, the link's `why` | 1. place the part by a relation that keeps it near (`Beside`, `Near(PadRef)`). 2. `board.link(a, b, weight=LinkWeight.X)` heavier. 3. `priority=Priority.HIGH` so it is placed before what crowds it. 4. a `board.push` that holds it away: its `falloff=`. 5. `command:preview --explore SECONDS --focus ITEM`. 6. `limit_mm=` raised (asks the user; the limit is a fact) | script, command |

### label

| Case | Facts | Suggestions | Owner |
|---|---|---|---|
| `label.sits_on` (warning): a label on a part | the label, what it sits on | 1. `side=` another edge, `align=`. 2. `size=` smaller (`label.size`). 3. `gap=` | script |
| `label.no_spot` (warning), no clear spot to move to | the label, what is in the way | the same as `label.sits_on`; gap: none that places text by a coordinate | script |
| `label.not_drawn` (notice) | the item | `see` the item | - |

### setup, fab, facts, split, route, vias, needs

| Case | Facts | Suggestions | Owner |
|---|---|---|---|
| `setup.undeclared` (warning): no declaration places a part | the part | `board.place(Part("ref"))`, or put it in a `board.row`, `board.block` or `Cell` (`checked`: the exact ref) | script |
| `setup.web` (critical) | the gap, the minimum | `web=` on the outline form, or the cutout's place (asks the user) | script |
| `setup.pitch` (critical): a net class does not fit the pads' pitch | the part, the class, the clearance that fits | 1. `board.rule(clearance=, within=Part(..)/Cell(..), why=)` where the figure that fits is accepted (`checked`; asks the user). 2. the class's clearance in the board's `.zen` (asks the user) | script, capture |
| `setup.lane_unused` (warning) | the part, pin | 1. `board.track(net, [esc[pin], ...])` from the lane. 2. drop the pin from `board.escape(part, pins)` | script |
| `setup.frame_reach` (warning): a part outside a fitted frame's declared axis | the item, its extent, the frame | 1. the declared number in `board.size(fit=Axis.X, height=)` (asks the user). 2. the item's place (`on`) | script |
| `setup.accept` (warning, unmatched; notice, not needed) | the check, subject | correct the check or subject in `board.accept(...)`, or remove the call | script |
| `setup.layer_lost`, `setup.rule_lost`, `setup.lookahead_dropped` (notice) | - | none: placemat carried on; `layers=` or the lookahead can be left as they are | - |
| `fab` (critical) | the class, the figure, the minimum, the key | 1. the class's value in the board's `.zen`, to the minimum (`checked`). 2. `file:fab-profile.json#min.<key>` when the profile, not the class, is wrong. Both ask the user | capture, fab |
| `facts` (warning) | the reasons | review the change, then `command:facts --confirm` (asks the user) | command |
| `split` (warning) | the groups | gap: the remedy is to split the cell in capture; no script form. `place.split_min_group` changes what counts | capture, setting |
| `route` (notice) | the net, why it dropped | `command:route SCRIPT --adopt NET` after the parts settle | command |
| `vias` notices (shared, moved, re-routed, left, shortened, re-laid) | - | none | - |
| `vias` warnings (a via dropped, fewer than declared) | the step that failed | the `place.via_*` settings and `drops=` of `unplaced.search` | setting, script |
| `needs` (notice) | the fab option said | 1. `file:fab-profile.json#via.micro` (or blind, buried) `"yes"` (`checked`: the site found it clears the spot; asks the user). 2. `see` the item | fab |

## Charter fit

- *Intent, not coordinates*: no suggestion has a coordinate. Every script
  suggestion is a relation, a keyword or a priority. A case whose only lever
  is a coordinate is a gap.
- *Judged as KiCad judges*: a suggestion never loosens a rule to make a
  finding go. Lowering a clearance or a minimum is rank 5 and `asks_user`.
- *Project-agnostic*: the table and the tests name forms, never a part,
  board, net or project.
- *Tunables are settings*: there is no weight, threshold or share in
  `suggestions.py`. The dominant bucket is the one with the most refusals,
  with ties broken by the order `_blame_text` already lists them.
- *Fitted, never zones*: no suggestion turns a pour into a zone or a plane.
- *Decide alone / ask first*: `asks_user` marks the suggestions that change a
  fact or accept a verdict; the skill tells the agent not to apply them alone.

## Phases

1. `Finding.case` and `facts`; `suggestions.py` with the cases of `unplaced`,
   `fixed`, `copper.meets`, `copper.keepout`, `copper.cross`, `link_over`,
   `escape_*`, `label`; reuse cache, `run.json`, `preview --format json`,
   plan JSON, the studio slot; the `api.md` and `SKILL.md` text. These are the
   kinds with the most findings on a real run.
2. The remaining kinds; the plain-string copper notes converted to Findings
   with a case; the advice clauses removed from the sentences that a
   suggestion now carries (open question 3).
3. An apply step, only if the user wants one (open question 5).

## Out of scope

- Applying a suggestion. Nothing in this design edits a script or a
  `placemat.toml`; the studio does not edit.
- Design-check verdicts (`keep-out`, `current-path`, `heat`, ...) and DRC
  violations. They are not findings. Their levers (`board.accept`, `Pm.KeepOut`,
  net class widths) are a later table of the same shape.
- Ordering by what worked before, learning from runs, or any estimate of how
  likely a change is to clear a finding.
- Changing a finding's kind, severity or sentence in phase 1, or the run score.
- A suggestion that needs placemat to grow a form. Where none exists the table
  says "gap"; a gap is a candidate for `BACKLOG.md`, not a suggestion.

## Testing

All tests use small synthetic boards and scripts, in the style of the
existing findings and severity tests, with generic names (`U1`, `R2`, a net
`SIG`); no project or board name appears in a test, a table row or a fixture.

- `tests/test_finding_suggestions.py`:
  - every `case=` id raised in `src/placemat` is a key of `CASES`, and every
    key of `CASES` is raised somewhere (found by scanning the source, so a new
    site cannot skip the table);
  - every `ref` resolves: `call:board.X#kw` against `inspect.signature` of the
    board method, `form:` against `placemat`'s exports, `setting:` against the
    settings table, `command:` against the CLI parser, `file:` against the
    fab-profile schema. A renamed keyword or setting fails here;
  - a rule given facts returns what the table says: the bucket decides the
    first suggestion of `unplaced.search`; a rule returns `None` when its
    fact is absent; `rank` is 1..n in order;
  - `asks_user` is set on every `file:` ref, on `board.accept`, `web=`,
    `limit_mm=`, `board.rule` and `board.size` suggestions;
  - no `text` contains a digit sequence that is a coordinate, and no ref names
    `Location`, `reach=` with a number, `board.figure` or `board.plane` for a
    pour.
- Synthetic scripts per case, run through `resolve`: a board too small for
  one part (`unplaced.search`, courtyard), a track crossing a keepout
  (`copper.keepout`), two crossing tracks (`copper.cross`), a link over its
  limit, a label on a part, a part walled by a neighbour, a net class under a
  fab minimum. Each finding carries the expected case and its suggestions
  name `on` items that exist in the plan.
- `checked` is true only if it works: for a waypoint note and a chamfer, a
  second script applies the suggestion and the finding is gone.
- Persistence: a pickle and the reuse cache round trip `case` and `facts`; a
  cache entry of three fields loads with none; `run.json` and `preview
  --format json` carry `suggestions`; a record without them reads as none;
  `RunRecord.findings_with_severity()` passes them through.
- Plan JSON: `line` is present when the item's declaration is known and absent
  when it is not; the `findings` event carries suggestions.
- Studio page: the `fixslot` is empty and hidden for a finding with none, shows
  rank 1 and a "more" control for one with several, and the "show line" control
  selects the line the item's step selects.
- The existing suites for findings, severity, reuse, the studio and the report
  pass. `fixtures/bench.py --jobs 2`: no score moves (no placement or finding
  sentence changes in phase 1).

## Open questions

1. Do suggestions that change a board fact (a net class value, `fab-profile.json`, `web=`, a `board.size` number, a link's `limit_mm=`, `board.rule(clearance=)`, `board.accept`) appear at all, flagged "asks you", or are they left out so only script and tuning suggestions show?
2. Should `run` print the top suggestion under each critical finding (more console lines, and the printed list is already cut at eight), or keep the console as it is and show suggestions only in `run.json`, `preview --format json` and the studio?
3. Once a suggestion carries the advice already inside some finding sentences (keepout crossing, pair crossed, pitch, chamfer and arc notes), should the sentence lose that clause (changing those sentences and their tests), or stay as it is and repeat in the studio?
4. Is `preview --explore SECONDS --focus ITEM` acceptable as the last-ranked suggestion for `unplaced`, `link_over` and `escape_*` findings, given it takes seconds to minutes of CPU, or should suggestions name only changes to the script and settings?
5. Is an apply step wanted at all? If so, for which owners: only `setting` (writing `placemat.toml`) and keyword-level script edits, or none until the studio can edit the script?
6. Is the `checked` flag worth having, or is rank alone enough? It is only set where the raising code measured that the change clears the finding, and the tests apply those suggestions to prove it.
