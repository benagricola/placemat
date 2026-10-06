# Migrating a layout script

Sections are per release, newest first. Read the ones between the version a
script was written against and the version in use; `SKILL.md`'s check line says
whether any of it applies. "Patterns in older scripts", at the end, names the
section for each hand-written pattern a newer form replaces.

## Unreleased

### Fixed

- **Turned lanes leave room for the router's grid snap.** The router starts a route from the point of its 0.1 mm grid
  nearest a lane's end and refuses a leg from there that comes nearer the next lane than the clearance. Turned lanes
  stood exactly a track and a clearance apart, so the leg from a lane end that did not lie on the grid was refused
  ("grazes foreign copper"), and the route could leave the lane only along its own line. Two lanes of an escape with
  `turn=` that are not a pair's now stand the router's grid step over the square root of 2 further apart (0.0707 mm;
  `--grid-step` in `route.router_args` sets the step), and each riser of a fan at 45 is that much times the square root
  of 2 (0.1 mm) further out than the one before. A turned fan is wider by that much per lane: a script that stands a
  part beside a turned fan at exactly the lanes' old pitch (a bypass a lane's width off the row, say) may now see the
  outer lanes blocked by it (`escape_lane`, `copper` findings); stand the part that much further off.

## To 0.99.21

### New

- **Past passes any obstacle.** `Past(items, edge)` and `Past(items,
  Corner.X)` take cutouts, stretches of the board edge, parts and cells,
  and labels, as well as pads, vias and tracks. The point keeps the
  board's copper-to-edge clearance off a hole or the edge, and stands on
  an envelope's or a label's outline. A track that had to pass a cutout
  with a hand-placed point can name the cutout. Past over pads, vias and
  tracks alone resolves as before. `board.label()` returns a `LabelKey`,
  a `str`, so scripts that use the key as text need no change. A
  `CutoutEdge` taken from another board is refused.

- **Copper near a hole or the edge is a finding.** Declared copper nearer
  the outline or a cutout than the board's copper-to-edge clearance is a
  critical `copper.edge` finding when it is planned, and copper wholly
  inside a hole or off the board is one at gap 0; KiCad's DRC does not
  report the latter. Copper nearer a part's drilled hole, plated or not,
  than the hole clearance is `copper.meets`. The nearer cases were DRC
  failures before and still are; a run now reports them itself, naming
  the declaration, so a board that passed its findings may now show
  these, and they count in the run score as copper findings do. The
  copper is still drawn. A module fragment's frame is not judged.

- **A pad whose one way toward its target is pinched is an `escape.pinched` warning.** Its airwire toward its nearest
  target is followed out to `place.approach_reach` (8 mm) on the pad's own layer. When it passes between two other
  parts' copper (pads, planned tracks or vias) closer than the net class's track width and two clearances, every
  other way within `place.approach_detour` (2 mm) of the airwire is closed by copper or crosses another net's airwire,
  and widening that gap alone would open one, the finding names the pad, the two neighbours, the gap and what the
  track needs. A termination row straddling a connector contact is the case it was made for. It is judged once on the
  finished board and does not enter the score, so placements do not change. Scripts need no change.

- **Lines whose pins stand in reverse order are a `pins.reversed` notice.** Two parts joined by `pins.reversed_min`
  (3) or more lines, directly or through a series termination, where a run of a part's pins lands on the other part
  (or on the terminations) in the reverse of its order: the notice gives the nets in each order and the crossings
  among their straight airwires, as they stand and with the run mirrored. It says when a `Pm.PinGroup` or
  `Pm.PinPool` holds the pins, and when the pin map study looked at the part and gave no map. A part the study gives a
  `pins.remap` for gets no `pins.reversed`. Scripts need no change.

### Changed

- **`past_off_board` applies to a copper-only `Past`.** A `Past` whose
  point lands off the board or in a cutout is a `copper.not_drawn`
  finding (`past_off_board`) for a `Past` over pads, vias and tracks too,
  whose point was not checked against the board before. It is not judged on a
  module fragment.

- **A finding names a `Past`'s items as records.** The `names` fact of
  `copper.corner` and of a `copper.not_drawn` finding's `past` variant
  holds one record per item: `{"kind": "pad", "ref", "number"}`,
  `{"kind": "copper", "key"}`, `{"kind": "cutout", "name"}`, `{"kind":
  "part" | "cell", "name"}`, `{"kind": "label", "key"}` or `{"kind":
  "edge", "facing"}`. They were text. The messages read as before.

### Fixed

- **Copper that stands on copper planned after the search is drawn.** A
  track ending on a via, or a track or via whose `Past` names a via, a
  track or a field of vias (`board.vias(net, pad)`), was planned before
  the search when its own ends were fixed. Where that via or field was
  planned after the search (a field always is, a via past a label is), the
  copper was not drawn, with a `copper.not_drawn` finding saying the via
  found no spot or was not planned by then. It now waits for the copper it
  names.

- **A stamped cell's clearance rules are read in the order its module declared them.** They were read in the
  order KiCad gave the cell's group items, which changes between loads of the same board. Two effects:
  - a run or a studio resolve could refuse the previous record ("the script's board-wide declarations changed")
    and replay none of its steps, though nothing had changed;
  - where two of a module's rules both match one pair of items (an `on=` rule and a `between=` rule over that
    net, say), the last one decides, in placemat and in the `.kicad_dru` KiCad's DRC reads. The rule that decided
    could be the earlier one. A module whose rules never match the same pair was judged the same either way.

  The notes are now taken in the order the fragment wrote them, one under another, which a turn or a flip of the
  cell keeps.

- **Nets of a wider clearance class route in their own stage, so the other nets route at the Default clearance.** The
  router spaces every net of one call at the largest clearance among the nets it routes. The main pass routed a 0.2 mm
  class (a 50 ohm feed, say) with the Default nets, so every net kept 0.2 mm from everything, and a lane end closer
  than 0.2 mm plus half a track to a neighbour was refused ("only a narrower track clears it"). The nets whose
  clearance is above the Default class's now route first, a router call per clearance, widest first; a halo net
  routes in the stage of its halo. A net such a stage leaves open is not routed again in the main pass. The report and
  `route.json` have `class_stages`, and `route_stage` events a `classes` stage. The `setup.net_halo` finding with
  `variant` `open` (a halo net routed with the others) is no longer said. Scripts need no change.

- **The pin map study starts a soft group reversed when its targets lie in reverse.** The first map laid a soft
  `Pm.PinGroup` whole on a run of pins only in its written order, though an intact group costs the same either way.
  Where the order that does not cross was the reverse (a part turned 45 degrees, say), the default search seldom
  undid the crossings, and the advised map could score worse than the uncrossed one by the study's own total. The
  first map now tries each run in both orders and takes the cheaper; at equal cost the written order wins, so a part
  whose groups are all hard, or whose soft groups gain nothing reversed, gets the map it got before. A hard group
  (`name!`) keeps its written order. A part with a soft group may now be advised a different map.
  Scripts need no change.

## To 0.99.20

### Fixed

- **The studio no longer stops on a pin map finding.** A `pins.remap` finding's poses carry `turns` as records, which the
  page's presenter took for a placement's refusal at each rotation and failed on (`KeyError: 2` in the channel thread), so
  the studio stopped updating. Scripts need no change.

## To 0.99.19

### New

- **The studio's replay has a speed and steps one at a time.** A select beside the slider sets play's speed to 0.1x,
  0.25x, 0.5x, 1x, 2x or 4x of the usual pace (the whole placement in about 8 seconds), kept per browser; a change
  during play keeps the position. Buttons either side of Play, and the Left and Right arrow keys outside a field,
  pause play and move one step; each is disabled at its end.

- **The studio shows every pose a pin map study searched.** A `pins.remap` finding's panel has a row per pose in
  its `rotations`: the turn, or the cell's turn for a part in a cell, weighted crossings, length, bends, total and
  the saving against the present map, with the best and the present marked. Clicking a row draws its airwires and
  lists its map, as Try does for the best; a second click or a new selection clears it.

- **The studio's explore view shows the pin map study.** Each studied variant's crossings after remapping sit
  beside its score, with `slow` or `error` when its study had one; on the variant shown, Map draws a group's
  airwires and lists its map. The explore record and its `explore_done` event now carry `pin_maps`, and each of
  its groups carries `before` and `paths`, its airwires under the present map and the best.

### Fixed

- **A named cutout on a disc with a bore reads its own edge.** `board.cutout(name).edge(side=)` and the
  `label.cell_edge` warning took the loop of the bore (or of the previous hole) for a cutout fixed at declaration, and
  the web check against the other holes compared the cutout with itself. A script that placed against such a cutout
  sat against the bore; it now sits against the cutout. A disc without a bore and the other board shapes were not
  affected.

- **The studio lists every copper layer of the board while a resolve runs.** The board's first frame carried no
  layer list, so a layer nothing is planned on (an inner layer only the router uses) was missing from the layer list
  until the resolve finished, and the page's stand-in, the layers that carry planned copper, left it out. The frame
  now names the stackup's copper layers, as the finished plan does.

- **The pin map study no longer keeps nets on pins their own rules bar.** At the present pose the study offered the
  present map as a candidate, so a map was never worse than the present one, even when the present map broke a
  `Pm.PinAllow` or `Pm.PinDeny`. That map, being the cheapest, won, and the barred nets stayed where they were. The
  present map is now a candidate only when every net on it stands on a pin it may take. A part whose present map
  breaks a rule always gets a `pins.remap` finding, whatever `[pins] gain_min` asks, with the cheapest map that keeps
  the rules, and its sentence names what that map costs ("a pin map that keeps the pin rules the present one breaks
  exists at its present rotation, at ..."). A hard `Pm.PinGroup` whose nets stand on barred pins and that has no
  window its nets may take is a `setup.pins` `no_legal_map` warning, and the part is not studied; before, it was
  left where it stood. Boards whose present maps keep their rules get the same maps as before. Scripts need no
  change.

- **The studio's replay draws copper at the step that laid it.** A plan's replay hid all the copper until its last
  step, then showed it at once; each track, via and pour now shows from its own step on, in 2D and 3D, as a route's
  replay already did.

- **Solid works on the studio's spread 3D layers.** With the layers spread, Solid and See-through drew the same faint
  layer sheets; Solid now fills each layer's sheet opaque, as it draws the closed board.

- **A suggestion of a past run or explore can be shown, tried and applied in the studio.** Show, Try and Apply on a
  finding of a run, explore, route or command opened from the Runs list (or shown by Latest) answered "no such
  resolve (the last 10 are kept)": they looked the suggestion up among the studio's own resolves. The page now names
  the view it shows, and the studio finds the suggestion in that view's plan, as `placemat apply` finds one in the plan
  its run kept. A try is compared with that plan. When the script has changed since, the request is refused with
  "this run's script has changed since; re-run to act on its suggestions". Scripts need no change.

## To 0.99.18

### New

- **A ring takes `rotations=Turns.TANGENT`.** `board.place(item, at=Polar(r, None, about=centre),
  rotations=Turns.TANGENT)` puts the item's body centre at exactly `r` from `centre`, at the bearing the search
  settles on, turned to face out there (exactly, not in a bin). `Tangent(about=)` measures the bearing from another
  point; `Tangent(quarters=True)` is refused on a ring. `Polar((r, r), None)` is still refused, and its message
  names `Polar(r, None)`; a script that used a narrow band for this can use the ring.

### Changed

- **The pin map study's budget is a count of steps, not a time.** `[pins] budget_ms` and `probe_budget_ms` are
  retired: a placemat.toml or flag that sets either is a settings error naming its replacement. Set
  `[pins] budget_steps` (default 3000 a part, about what 100 ms took on the native core: 0.077-0.09 s for the
  reference board's MCU searched to 3000 steps, `fixtures/pinmap_bench.py --repeat 5 --set pins_anneal_moves=750`) and `probe_budget_steps`
  (default 150000) instead; a step is one move of a local search. The same board now gives the same map on any
  machine, at any load, on either core; the Python fallback takes longer to get there. `[pins] guard_ms` (default
  10000 ms a part, 0 is off) is a safety net on the time: a study past it gives no map and a `setup.pins` warning
  with code `study_slow`. The `pins.remap` facts carry `steps` and `budget_steps` in place of `budget_ms`.

### Fixed

- **A route no longer leaves the router's dangling tails.** The router left short segments (0.01-0.11 mm) whose ends
  both land on one other item of their net, the net's copper polygon or another track's body, and copper ending in
  nothing; KiCad reports them as `track_dangling` and `via_dangling`. The routed copy now has the router's dangling
  tracks and vias deleted, repeatedly, and its collinear pieces merged, as KiCad's cleanup does. Copper the router was
  given (declared tracks, escape stubs, a module's or cell's own copper, also where the router wrote it again) is not
  touched. A net whose pads the route left unjoined keeps its router copper, as progress to build on, and so does a
  net whose pads the deletion would part. The route's console line says how many went and which nets kept theirs, and
  `route.json` and the route record carry them under `dangling_removed` (`kept_unrouted` and `refused_nets` for the
  nets kept). Scripts need no change; a route's closure is unchanged, and adopted routes lose the tails.

## To 0.99.17

### New

- **Units with options, and exclusions.** `board.unit(name, Part(...), Part(...), why=)` declares parts that move as one
  unit, and `board.alternative(unit, option, Alt(Part(...), **keywords), ..., why=)` gives it each option
  (`unit.option`); `run.json`'s arrangement entries list the reason of every choice they hold, an item's option or a
  unit's (`why`), and the console row shows them.
  `board.exclude(choice, choice, ..., why=)` leaves out every combination holding all the choices; `run.json`'s
  `arrangements` lists each with its `why`. `arrangement.option_dead` (warning) names an option refused in every
  combination that holds it.

### Changed

- **A `Pm.PinGroup` is soft unless marked hard.** A group's nets now move one by one, each under its own
  `Pm.PinAllow` and `Pm.PinDeny`, and the pin map study charges `[pins] group_weight` (default 4 weighted crossings
  a mm) for how far its neighbouring nets stand apart beyond the part's pin pitch, so a group stays together unless
  splitting it saves clearly more. A group that must stay one block on consecutive pins, as before, is written with
  a `!` after its name: `"pio0!:GPIO0-GPIO3"`. Consecutive means consecutive in the order `Pm.PinPool` lists the
  pins. Other names read as written; `!!` is a `setup.pins` warning (`bad_marker`), as is a second group of one name
  (`same_name`). Captures whose groups a datasheet ties to
  consecutive pins need the `!`. Each pose's facts carry `groups`, and the sentence says when a soft group ends
  split.
- **A controlled impedance's airwire length counts `[pins] impedance_weight` times over.** A studied net whose net
  class names a tuning profile (a differential pair's half too) counts its length `impedance_weight` times
  `length_weight` a mm, whether its pin may move or not, so a cell turn that lengthens an RF net loses more than
  before. The facts add `impedance_length_mm`. A board with no such net scores as before.
- **A part standing off the axes is studied in its own frame.** A part or cell at 45 degrees, say, is studied with
  its body as its courtyard (envelope) turned with it, not the larger box round it, and its pins face that body's
  sides. Parts on a quarter turn are studied as before. Nothing in a layout script changes; a run after updating
  studies its pins again (the findings' schemas changed).
- **A module's units combine with its other items and units.** A module's arrangements are the default and every
  combination of its items' options and its units' options (`c_in.east+pair.upright`), in product order, the first
  declared changing slowest. A module of items' options alone makes the same arrangements, ids and order as before. The
  default of `place.arrangements_max` is now 16, up from 8, since a unit multiplies the count; a project that sets its
  own value keeps it, and a module over the limit lays out the default only (`arrangement.limit`), which `board.exclude`
  brings back under. A part in a unit may not have its own `board.alternative`, nor be in a second unit.
- **`only=` matches by the choices an arrangement holds.** An entry names a choice (`pair.upright`) or several joined by
  `+`, and the copper exists in every arrangement that holds all of them, so copper on one option is laid in each
  combination with it. An entry that is a full id still names that arrangement; `only=("default",)` is still the
  module's own layout alone. An `only=` whose every arrangement an exclusion leaves out is refused where the script
  finishes declaring.

### Removed

- **`board.arrangement(name, Alt(...), ...)` is gone.** A module script that calls it now fails at the call with a
  `TypeError`. Declare the parts as a unit with one option, which does what it did and also combines with the module's
  other items and units:
  `unit = board.unit("name", Part("a"), Part("b"))` and
  `board.alternative(unit, "option", Alt(Part("a"), ...), Alt(Part("b"), ...))`.
  Its id becomes `name.option`, so change an `only=` naming the old id, and a board's `arrangements=` naming it, to the
  new one; a lock entry naming the old id is released (`arrangement.missing`, warning) and the cell searched again. Re-run
  the module after the change.

### Fixed

- **A searched cell keeps its labels the silk clearance off the board edge.** A stamped cell's label texts (the silk
  texts in its group) were judged against placed parts while the cell was searched, but not against Edge.Cuts, so a
  cell could land with a label over a cutout or past the outline (KiCad's `silk_edge_clearance`). A searched spot now
  keeps each text's box the board's silk clearance inside the outline and off every cutout, on either face and under
  any envelope; the scan counts the refusal as `label silk to edge: box ...`. A cell whose place the script decided
  stays where it is put, and each of its labels nearer the outline or a cutout than the silk clearance is a new
  `label.cell_edge` warning (the cell, the text, the edge, the gap, the clearance). Scripts need no change; a board whose cell labels stood by a cutout or the outline may see those cells
  move. The native module changed: `uv pip install -e ".[native]"` after updating.

## To 0.99.16

### New

- **The pin map study.** A part whose capture annotates its general-purpose pins (`Pm.PinPool`, with `Pm.PinFixed`,
  `Pm.PinAllow`, `Pm.PinDeny` and `Pm.PinGroup`; capture.md, "Pin pools") is studied at the end of every run and
  preview: placemat looks for an assignment of its nets to those pins, at its present rotation and at each turn in
  `[pins] rotations`, that saves weighted ratsnest crossings, airwire and turning, and says so in a `pins.remap` notice
  whose suggestion carries the map and the turn. Nothing is written: the map is a capture change and the turn a layout
  one. An annotation entry naming a pin or a net the part lacks, and a net that stands on a pin its own `Pm.PinAllow` or
  `Pm.PinDeny` bars, are `setup.pins` warnings; so is a study that raised, which leaves the run standing with its error
  on `metrics.pin_study`. An explore studies its best `[pins] explore_top` variants and reports the maps beside their
  scores; `placemat apply <id> --search` studies a suggestion again with `[pins] probe_budget_ms` a part. Settings:
  `[pins]`. The study runs in the native module when it is in use (`uv pip install -e ".[native]"` after updating), else
  in Python, with the same results. A part in a cell (a stamped module instance) is studied as its cell: each pose
  turns the whole cell, and a winning turn is taken by turning the cell on the board or re-laying the module with the
  part turned in its frame. A net whose far end is on a part not placed keeps its pin, and below `[pins]
  placed_share_min` of placed ends the study gives no map and says it waits on placement. Nothing in a layout script
  changes; the first run after updating replays no steps (the findings' schemas changed).

### Changed

- **A bypass capacitor's alternative is a turn at its pin.** The skill no longer offers another side of the IC for a
  bypass capacitor. A module gives each bypass capacitor a turn that keeps its pad at the pin, or a `# fixed: <part>
  <reason>` line when no turn fits between its neighbours; a turn that fits only when a neighbour moves is a named
  group with that neighbour. Scripts need no change; a module laid out under 0.99.15 may want a bypass alternative
  dropped or turned.

## To 0.99.15

### New

- **A module declares alternative arrangements.** `board.alternative(item, name, ...)`, `board.arrangement(name,
  Alt(...), ...)` and `only=` on the copper forms; the module run proves each and writes the offered ones into the
  fragment, so a script that wants them runs its module again. The word is "arrangement": a `.zen`'s per-variant
  `Layout` and explore's variants are other things. A module that declares none lays out as before, and its run may now
  give `arrangement.extent_fixed` notices for members standing more than `place.extent_notice_mm` past the next.
  New settings: `place.arrangements`, `place.arrangement_options_max`, `place.arrangements_max`,
  `place.arrangement_note_chars`, `place.extent_notice_mm`, `score.arrangement`.
- **A board searches the arrangements of the modules it stamps.** `arrangements=` on a cell's `board.place()` is an id
  or a list of ids; with none, the search tries the module's own layout (`"default"`) and every arrangement the module
  offers, and takes another only when it beats the default by `place.arrangement_margin` (0.5 mm). A board that stamps a
  module with offered arrangements therefore searches them by default, and its placements can change.
  `arrangements="default"` holds the module's own layout, and `place.arrangements = false` turns the search off for the
  board. A module offers arrangements only once it has been run again (a re-run writes its notes into the fragment); a
  module run before this keeps its default alone. A firm cell tries its arrangements at its spot; with none legal it
  stands in its default with a `fixed.part` finding listing each refusal, and one whose choice does not settle between
  firm passes raises `fixed.room_unsettled`. The lock and `placemat freeze` hold the arrangement a cell stood in; freeze
  writes `arrangements="default"` for a cell locked in its default that offers any, and a lock entry whose arrangement
  is gone is released with an `arrangement.missing` warning. An explore draws among arrangements as it does among spots.
  `reuse.VERSION` is 5, so the first run after upgrading replays nothing. New setting: `place.arrangement_margin`.

## To 0.99.14

### New

- **A via on a lane that has a way out is a finding in a module.** A module puts a via on an escape lane only when the
  lane is walled in within the module. In a module run (a frame not drawn), a via on a lane, from `vias=` on
  `board.escape` or a `board.via` on the lane's copper, whose lane reaches the frame's edge on its own layer without it
  is an `escape.via_unneeded` warning naming the net, the pin and the via. Take the pin out of `vias=`, or remove the
  `board.via` (and the track point that ends on it), so the lane ends as a stub and the parent board's router decides
  whether it changes layer. A plane or free net's via is not one. Placements do not change.

## To 0.99.13

### Fixed

- **A past explore opens on its best variant's board in the studio.** Picking a finished explore in the Runs list, or a
  past run that explored, left the board empty unless the studio was resolving the same script. It now opens on the
  board of the best variant, in 2D and 3D, and the header names the explore, its best variant and its score; the
  variant stepper draws the other variants from there. An explore now keeps the best variant's plan beside its record
  (`.placemat/views/explore/best/`), and the record names its run. For an explore recorded before this, the studio
  takes the board its run wrote: when the run kept the best (`--accept`), that board as it is, or its build when it
  routed; otherwise the focused items moved to where the best put them, the other items as the run placed them, and
  the header says so. Nothing in a layout script changes.

## To 0.99.12

### New

- **A halo round a net while routing.** `[route] net_halos = {"SW" = 2.0}` gives a net a halo in mm: every router
  pass keeps other nets' new copper that far from its copper, to keep coupling off a switch node. placemat now writes
  the router's per-net clearance map itself, so `--net-clearances` in `[route] router_args` or `pair_router_args` is
  refused when the settings load; drop it, and name a net that needs more room in `net_halos`. Before the route, a pad
  of another net inside a halo whose own copper ends inside it is a `setup.net_halo` finding: draw that pad's escape out
  past the halo in its module (a longer `run=` on its `board.escape`), or give the node a smaller halo. Draw the halo
  net whole in its module, or name it in `[route] islands`: routed with the other nets, it would space them all at its
  halo, which is a `setup.net_halo` finding too.

## To 0.99.11

### Fixed

- **A pad is measured as KiCad measures it.** A copper finding measured a part's pad by its outline, which rounds a
  rounded rectangle's corners with straight edges standing up to a few micrometres outside the copper. A 0.127 mm track
  passing a 0402 pad's rounded corner at 45 degrees read 0.126 mm from it where KiCad's DRC measured 0.129 mm, a finding
  on a board KiCad passed. A pad, and a part's own copper drawing, read from KiCad are now measured as the shape KiCad's
  DRC collides. Nothing in a layout script changes.

## To 0.99.10

### Fixed

- **A placed cell's copper is measured as KiCad measures it.** A cell's own pour, straight tracks and vias lost the
  shapes a copper finding measures them by (the drawn polygon and its stroke, the track's segment, the via's circle)
  once the cell was placed, so a finding measured their outlines, which stand a few micrometres outside the copper. A
  track beside a stamped cell's stroked pour read 0.125 mm from it where KiCad's DRC measured 0.132 mm, a finding on a
  board KiCad passed. They now move and mirror with the cell. Nothing in a layout script changes.

## To 0.99.9

### New

- **A differential pair can be given its own layers.** `[route] pair_layers` maps a pair, by its two nets `"P/N"` or by
  its net class, to the copper layers the pair router may route it on, e.g. `pair_layers = {"USB_D_P/USB_D_N" =
  ["In2.Cu", "B.Cu"]}`; every other pair keeps the route's own layers. The pair stage runs the router once per distinct
  list, the named pairs first. A pair whose escape lanes end in vias on F.Cu, with F.Cu left out of its list, starts from
  the vias and lays nothing on F.Cu. An unknown layer name is refused when the settings load; a key that names no pair on
  the board, or a layer the board lacks, is a `setup.pair_layers` finding and the entry is not used. The route report has
  `pair_layers` (the lists applied) and `pair_layers_refused`. Nothing in a layout script changes.

### Fixed

- **A net list passed as one argument is refused.** `placemat route --exclude` and `placemat run --route-exclude` took an
  argument holding several names separated by spaces (a shell variable left unsplit, as zsh leaves `$list`) as one net
  name, so the router was told to leave out a net no board has and routed every net. Such an argument now stops the
  command, saying to pass each net as its own argument.

## To 0.99.8

### New

- **The studio's 3D view draws the copper.** Each copper layer is drawn at its height in the board, from the board file's
  stackup (evenly spaced when the board declares none): tracks as ribbons, planes and pours as filled outlines, pads on
  their layers and vias as cylinders through the layers they join, in the 2D view's layer colours, the router's copper
  lighter. Solid | See-through on the 3D bar makes the board body translucent so the inner layers show. The legend's
  copper layer, zone, pad, via and Copper origin rows (and their only buttons) act on both views at once. Findings are
  markers at their place and layer in their severity's colour, selected by a click as in 2D, and congestion is a
  translucent sheet on the top layer; the Marks rows switch both. Spread on the 3D bar pulls the layers apart
  (`[studio] 3d_spread_mm`, `3d_spread_ms`), the parts riding on the outer layers and the vias stretching. The plan
  document's `stackup` has `layers` (each copper layer's `z`) and `declared`. Nothing in a layout script changes.

### Fixed

- **The studio's 3D Play brings a back part up from below.** Each part dropped onto the board from above, so a part on the
  back face fell through the board to its underside. A part whose model stands under the board's mid-plane now rises to
  the underside.
- **The board outline, the declared groups and a relayed via also take a free UUID.** 0.99.6 gave written copper and
  rule areas a UUID no item on the board has; the outline's Edge.Cuts items, the groups a script declares and a via a
  via field relays were still added without the check, so on a board placemat had written before they could take the
  UUID of an item from the last write and pull it out of its group on reload.

## To 0.99.7

### Fixed

- **Each stamp of a module allows its nets in its own keepout only.** pcb names every stamp's copy of a module's keepout
  alike (`<name>_1`), so the `.kicad_dru` rule written for one cell's `allow=` area (`intersectsArea('<name>_1')`) also
  covered every other stamp's copy: a net one cell allowed was forbidden in its own area by the other cell's rule, and
  KiCad flagged it there. A board that stamps the module now renames each copy that lets nets through for its cell
  (`<name>_1 @<cell>`) when it writes, and builds that cell's rule from the new name. Write the parent board again;
  the module and its script need no change.
- **A plane's saved fill is the fill of the saved board.** The write filled its zones on the connectivity KiCad built
  when it loaded the board, before the plan moved the parts and drew its copper, so a fill could keep isolated islands
  that a refill of the saved board removes (a module's ground fill read 97.74 mm2 saved and 96.96 mm2 refilled). The
  write now builds the board's connectivity again before it fills. A module run once more saves its fill without those
  islands, and a board that stamps it gets them through the stamped cell; a parent board whose script draws a plane
  refills every zone, its cells' included, as before.

### Changed

- **`current-path` adds copper on parallel layers.** A route was judged by one layer's narrowest point, so a load
  carried by two planes joined at the same vias or through-hole pads failed at one plane's neck. The route is now cut at
  its plated holes, and where fills or pours of the net on other layers touch the same two holes as a stretch of the
  route, the stretch is judged by the layers' widths added, each scaled to the route's layer by the ratio of the two
  layers' IPC-2221 needs. The note names the layers and their widths, and the verdict carries them as `facts["layers"]`
  (`layer`, `width_mm`, `scale`, `at`, `route`). A net that failed on one of two parallel planes reads wider and may
  pass; a check script that read the verdict's width as one layer's reads `facts["layers"]` instead.

## To 0.99.6

### Fixed

- **Written copper and rule areas take a UUID no item on the board has.** A board placemat already wrote once carries
  items at UUIDs from the same seeded sequence a later write draws from; a track, via, text, pour, zone or keepout rule
  area written there could take one, and after a reload a group keyed by UUID read the other item as its own. Each is now
  given a free UUID before it joins the board. A board with no clash writes the same file.
- **The studio's 3D view draws a past run's parts.** A run opened from its records (what `placemat studio` shows when it follows the latest
  run, or a run picked in the Runs tab) carried no 3D models, so no model was converted and every part was a hatched plate, most of them a
  small marker at their cell, since a run's plan keeps few courtyards. The studio now reads the models from the board the run wrote and
  queues them for the converter, as it does for a live resolve; a part with no model is a plate of its courtyard, else its body. The
  converter also failed to start in a project whose `.placemat/views/studio` folder did not exist yet, with every model "the model
  converter could not start"; it now makes the folder first.
- **A run that routed is shown routed.** Following the latest run, or opening a past run that routed, showed the placement the run kept
  (`plan.json`) with only the copper the script declared. Such a run now opens as its build: the placement, then the route, ending on the
  board the router left, with the route's routed and failed counts in the strip. The router's tracks are drawn hollow, and the legend's
  "Copper origin" rows (planned, kept, routed) count each kind and hide, show or isolate it. Nothing to change in a script.

## To 0.99.5

### Fixed

- **Silk keeps `place.silk_margin` past the silk clearance.** Placement let two parts' silk stand at exactly the board's
  silk clearance. KiCad compares silk at the clearance itself, with no DRC epsilon, on geometry rounded to the nanometre,
  so a module whose silk was packed at the clearance and then stamped as a cell turned off the quarter turns (or a part
  searched with tangent turns) could be reported as `silk_overlap` at 0.199999 mm against 0.2. Where placement chooses
  the place (a search, `Beside`, a row), it now keeps silk `place.silk_margin` (0.001 mm) further from another part's
  silk and mask openings; a refusal at the clearance reads "silk is 0.200 mm from ... (needs 0.201)". A place the script
  decided, and a rider's place in its group, are judged at the clearance itself as before. A module whose parts were
  placed at the silk clearance gets them up to a micrometre further apart, and a search may take another spot where
  one stood exactly at it; lay the module out again and stamp the new fragment to clear the board's report.
- **A searched cutout keeps the silk clearance from parts' silk.** A `Cutout` whose place is searched (`at=Near(...)`, a
  free axis, a `Polar` with a free bearing or radius) was refused only where its box met a placed part's pads and drawn
  graphics, so it could be cut nearer a part's silk than the board's silk clearance, and KiCad reported `silk_edge_clearance`
  against the hole's Edge.Cuts. The search now also refuses a spot where the hole would stand nearer than the board's
  silk clearance to a placed part's silk on either face (`cutout_silk`: "would stand 0.15 mm from U1's silk (the silk
  clearance is 0.20)"). Such a cutout moves to the next spot of its search, a step or two further from its hint. A
  cutout whose place the script decided is cut where it was put, as before. A part placed after a cutout is still judged
  against it by its courtyard, body and copper only, not its silk.
- **Text on a back layer is written mirrored.** A keepout's name drawn on B.Fab (`write.keepout_drawings`), and a text
  given a back layer by name, were written unmirrored, which KiCad's DRC reports as `nonmirrored_text_on_back_layer`.
  Every text placemat writes on B.Cu, B.Silkscreen, B.Mask or B.Fab is now mirrored, and one on their front twins is not.
  A stamped cell's texts are put right as the cell is moved, so a fragment written before this fix needs no new layout.
- **`current-path` takes the plane over a sliver of another fill.** The search for the load's widest route read every zone
  fill and pour as passing any width, and measured only the fills on the route it happened to find first, so a route
  through a sliver where two fills of the net meet on one layer could be judged while a plane joined the same pads: a
  through-hole pad pair joined by inner planes read as a 0.05 mm neck. The search now reads an unmeasured fill no wider
  than the widest disc anywhere in it, and where the route it found narrows in a fill it searches again with that crossing
  at its measured width (`check.route_tries`, default 4). A net that failed on such a sliver is judged on its planes; the
  verdict can still fail there, at the plane's own narrowest point between the holes of other nets.
- **A copper finding measures a straight track and a pour as KiCad's DRC does.** It measured a track by its polygon, whose
  round ends stand up to 1.6 micrometres outside the copper, and a pour by its outline grown by half its stroke, mitred at
  each corner; read from the board, both by an outline KiCad grew by its arc error. Copper KiCad passes at its rule read 1
  to 3 micrometres short of it, past the DRC epsilon, and was reported (`copper ... is 0.158 mm from ... (needs 0.160)`). A
  finding now collides a straight track as its centreline and width and a pour as its outline and a stroke along each
  edge, as KiCad's DRC does. An arc track is still measured by its polygon.
- **A stamped cell's own labels are judged while the cell is searched.** The silk texts a module fragment's `board.label()`
  stamps with its cell kept parts off their boxes only once the cell had landed, so the search could set the cell where a
  label lay on a part already placed: KiCad then reported `silk_over_copper` and `silk_overlap`. Each text's box is now the
  cell's silk during the search: under the `physical` or `union` envelope a spot within the silk clearance of another
  part's silk or mask opening is refused. A cell that landed with a label on another part looks for another spot; one
  with no room left for its labels is reported unplaced as any other.

## To 0.99.4

### Fixed

- **A row placed by a reference is laid again in each firm pass.** When `place.copper_room` ran the firm items again (a
  `Beside` part moved out of declared copper's way, or placed before the part that refused it), the run was put back as it
  stood before the first pass except for its rows: a row whose start is a reference (`of=`, `centre=`, `end=`, `start=` a
  reference, `before=`/`after=` such a row, `align=Along.MID/END` on an unsized board) kept the start the first pass found.
  Its items were laid against where the anchor stood then, so a row `of=` a part that moved between the passes stood off to
  one side of it. Such a row now finds its start again in each pass; a script with one anchored on a part the copper room
  moves gets that row level with where the part ends up.

## To 0.99.3

### Fixed

- **The `keep-out` check judges only copper that shares a layer.** It measured a part's `Pm.KeepOut` distance between `away`
  copper and `pads` copper whatever their layers, so a back-layer pad with a plane between it and a front-layer pad failed at
  a distance KiCad's DRC, which judges clearance between items on one copper layer (a through-hole pad or a via spans its
  layers), passes. A pair on different layers inside the distance with no plane between them is now a notice finding
  (`keep_out.cross_layer`, in `run.json` and printed by `placemat check`), not a failure; one with a plane between is not reported.
- **The skill's pin-swap example is corrected.** It said a microcontroller's SPI pins must be consecutive; a hardware SPI's
  signals sit on fixed pins of one instance, not necessarily adjacent. The rule that must be consecutive is a programmable-IO
  block's pin ranges (a base pin and the next ones in number).
- **`Between()` asks no clearance to a pad of the track's own net.** The gap check added the clearance to each pad's net
  even when that net was the track's own, so a gap between two pads of the track's net raised a false "not enough for a ...
  track" note; the copper itself was drawn right.

## To 0.99.2

### Changed

- **The skill makes pin swaps a layout lever.** Where an IC's pins are general purpose, the agent moves a net to another pin
  the datasheet confirms for that function (and no restriction forbids: contiguous groups, one peripheral instance, boot or
  strapping pins, voltage domains), in the capture, naming each move and its datasheet basis. Nothing a script says changes.
- **`row(of=)` stands against the shapes of `of`'s envelope, as `Beside` does, at one distance for the row.** The row's distance from `of`
  was taken from the box round its envelope, so a pin 1 dot or any silk mark outside the body held every item of the row off the whole
  side by the mark's reach. It is now taken from the envelope's own shapes (pads, mask, silk and body under a physical envelope, the
  courtyard under a courtyard one): the row stands at the nearest distance at which every item clears the shapes it faces, applied to
  all its items so the row keeps its line, and a mark holds the whole row off only if an item stands over it. An item that then stands
  nearer than the box put it, and would be in the way of something already placed, is moved on out along its side to the first place the
  collision rule allows (`place.beside_step`, up to `place.beside_reach`), and the row is taken back to the box's distance where
  declared copper meets, as a `Beside` part is (`place.copper_room`). A row with `overhang=` and a row of items riding a searched `of`
  are laid by the box as before. A script with a row beside a part that draws a mark outside its body gets that row nearer.
- **Findings take KiCad's DRC epsilon; placement can with `place.drc_epsilon`.** KiCad takes the DRC epsilon (`BoardGeometry.drc_epsilon`,
  0.0005 mm on a fresh board, read from the board) off a copper or hole clearance before comparing, and relaxes hole to hole by it; a gap
  short of its rule by no more than that is clear. The plan's own copper (the `copper.meets` finding, "track X is 0.1596 mm from Y
  copper (needs 0.1600)") and the escape walls now judge so always: a declared track 0.4 micrometre short of a clearance is no longer
  reported as critical. Placement's legality (the search, the give-way quick test, the native judge, the net-tie exclusion's epsilon) keeps
  the nanometre and the fixed 500 nm unless `[place] drc_epsilon = true`, which lets a part, lane or via stand up to the epsilon closer,
  and so can move a layout. Silk and courtyard gaps are unchanged: KiCad takes no epsilon off those. Rebuild the native module.

### Fixed

- **A part nothing placed pulls is no longer left unplaced by room the pocket raster cannot see.** An item with no placed neighbour and no
  hint took one of a few free rectangles of a raster, and was reported "no pocket fits its envelope" where a legal spot existed in room
  that is not a free rectangle (an L, an arm narrower than the raster's cells resolve, a spot between keepouts). When no pocket takes it,
  the item is now scanned over each face it may take, nearest the board's centre, within the step budget and the time limits; the pockets
  stay the fast first try. A step that took a spot this way says so (`pocket_scan` note) and a finding that still fails says the scan found
  nothing either. A board that placed every part by a pocket is unchanged. Scripts change nothing.

## To 0.99.1

### New

- **The studio follows the latest command of the project by default.** `placemat studio` with no script now opens on the most recent
  command: a running preview, full run, explore or route followed live, else the one that finished last with its board and findings. A
  command that starts switches the view to it. Choosing a command, run or script in the "Open" dialog (the header title; "Follow latest" is
  its first entry, under "Runs") pins it; a "latest" chip in the header shows the mode. While you have selected an item, opened a finding or
  moved the view within `[studio] follow_hold_s` seconds (default 10, 0 never holds) a newer command is offered ("A newer run started",
  "Go to it") instead of shown. The address hash `#latest` names the mode. A project with nothing run opens on the dialog as before.

### Changed

- **A resolve with the native module is about 20% faster, an explore variant about 15%, and nothing in a result changes.** Hashing, the
  near-obstacle query, routed vias' spots, cutout gaps and a scan's lattice moved to or were tightened in the native module; an explore
  variant no longer binds suggestions it never shows. Rebuild the native module (`uv pip install -e ".[native]"`) to get it.

### Fixed

- **A fitted pour kept from its pads by the board edge no longer crashes the run.** The board edge's clearance outline carried a
  sentence where every other blocker carries a record, so rendering the pour's "not drawn" finding raised a TypeError. It is a
  record now (`{"form": "edge"}`), and the finding reads "the board edge leaves no way between ...".
- **A fitted pour between searched parts keeps its room during the search.** Declared-copper room (`place.copper_room`, on since 0.95.0)
  held tracks, pairs and vias whose ends are searched parts as soon as those parts were placed, but a pour joining searched parts was
  planned only after the whole search, so a later small part could land between them ("pad ... leaves no way between pads ...; the pour is
  not drawn"). A fitted pour is now planned when the last of its members is placed (dry, without `reach=`) and its outline is held clear
  of other nets for the items placed after it; same-net copper and its members are let in. Copper that `reach=` grows beyond the outline
  is still cut back by whatever stands there. Placements of scripts with such a pour can move; `place.copper_room = false` restores the
  old behaviour. Nothing to change in a script.
- **"Track not drawn, it would run through X" names every piece of copper on the leg, in order along it.** The finding named the first
  piece in the occupancy's iteration order, which could be a part placed after the ones that actually stood in the way. Its facts now
  have `blockers` (each as `met` is: form, who, label, net, plus `at_mm` along the leg from its start, and `placed_when_plannable`,
  whether the part was already placed when the room planning first tried the track, `null` where it did not try), `leg` (its
  `start` and `end`), and `met` is the first of them. The sentence adds "and N more". Nothing to change in a script.
- **A run's findings and preview JSON no longer depend on the hash seed.** Crossed escapes from one part (`escape_crossed`) could come out
  in a different order from one run to the next, and the placement search's crossing sums were added in a different order. The ratsnest now
  reports crossings in airwire order, and the nets of a moved part are refreshed in name order. A run's placement is unchanged; the order
  of findings in `run.json` and the preview can change once, for a board with several crossed escapes on one part.

## To 0.99.0

### New

- **`place.order = "room"` orders a tier by how many legal spots each item has left.** The default, `"freedoms"`, is the order as before
  (a slide before an item searched in two, then the rank). With `"room"` the item whose declaration leaves it the fewest spots goes first
  (a slide's length, a `Near` disc, a `Polar` band or the board's free area, less the item's size, hard-limit push discs and the keepouts that
  bar it; counted at `place.room_pitch`, items within `place.room_ratio` of each other level and ordered by rank). Each step carries a `room`
  note; `placemat preview` and the studio show it. Set it in `placemat.toml` (`[place] order = "room"`) or for one script
  (`[scripts."path.py".place]`). No layout changes unless it is set.

### Changed

- **A number on a `Centre` axis without `coordinates=True` is refused.** `Centre(30, 12)` and `Centre(30, None)` raise a `ValueError` where
  they are written (it was the `setup.centre_coordinates` warning since 0.91). A script must change each one: place by a relation
  (`Beside(part, Edge.X)`, `OnEdge(...)`, a pad's reference such as `Centre(X(pad), Y(pad))` or `Centre(X(pad), None)`), or, for a
  deliberate coordinate, write `Centre(30, 12, coordinates=True)`. This includes the `at=` of a `Cutout` or a keepout. The
  `setup.centre_coordinates` finding and its suggestion no longer exist; `coordinates=False` beside a reference is still the
  `setup.centre_flag_default` notice.
- **The names of settings renamed in 0.90.0 no longer load.** `rank.area`, `place.via_share`, `copper.arc_radius_widths` and the rest of
  that list are now unknown settings, an error naming the key (`placemat settings` lists the current names; the 0.90.0 entry below has the
  old and new names). The `setup.setting_renamed` notice is gone.
- **A lock entry written by 0.43-0.46 is released once.** Its declaration digest named parts by refdes; a run no longer accepts that form,
  so such an entry is released with "declaration changed" and the item is placed afresh (accept the run to write it again). Entries from
  0.47 on are unaffected.
- **The route replay is closer to what the router did.** The pair router's pairs are nets of the route events (`net_begin`, `net_end`, a pair named "P/N"), so they count as routed or failed. Ripped copper is shown until the step that rips it, not left out of the whole replay. The "net N of M" line counts within the stage, not over every launch's queue. Route records carry `complete` (the route finished), each stage carries `complete` and `dropped` (events the router's full queue turned away, or lines it could not finish), and a stopped route is listed as stopped and replayed with a note that it is partial. `route_events.install` takes `pairs=`, and `RouteEvents.end` takes `complete=`; a record written before this has neither flag and reads as complete.
- **A through-hole pad in the studio follows the layer rows of the legend.** It is hidden when the rows of every copper layer it spans are off and shown while any one is on; before, only the pads row switched it.
- **The studio's opening dialog is titled "Open".** Its button and the header's tooltip say the same; the half-sentence title is gone.

## To 0.98.0

### Changed

- **The studio opens on a choice of what to look at and resolves nothing until a script is chosen.** `placemat studio` with no script shows the
  usual interface with no board selected, over which a dialog offers a command running now in the project (followed live, as a
  background run), a past run (every board's `run.json` records: its board and findings, resolved by nothing) or a layout script to
  resolve here, the only choice that starts the studio's own preview. The header title opens the dialog again. A script given to the
  command, or named in the address (`#s=`), is opened as before; `#run=ID` opens a past run and `#cmd=ID` follows a running command. The
  Runs tab is the default tab (opening a script no longer jumps to Build) and lists past runs of every board beside the commands.
- **Every command says what it is.** The runs list, the header and the dialog show a chip for preview, full run, explore or route, with the
  script, label and pid in its tooltip. A command summary carries `kind` (a run or a preview given `--explore`, or one that has sent
  `explore` events, is an explore; a run that routes is a full run) and `label`. `placemat studio` serves `/projectruns`, `/runview?run=ID`
  and `/explores`.
- **Following an explore shows what it is doing.** Its focus, the variants landed (of its seeds when it has a fixed number), the seed that
  landed last, the baseline, the best so far with its distance from it, the time and each variant's score as it lands; the board shows
  the best variant so far, the focused parts moved to where it put them, and changes when a better one lands. The "live" control that did
  nothing when the explore was already followed is "Follow best", a toggle: picking a variant stops following, and the control follows the
  best again. The explore sat at the foot of the Runs tab; it is now at the top.
- **The findings layer on the board starts off.** It is on while the Findings tab is open and off again when the tab is left. Turning it on
  in the legend keeps it on until it is turned off there; that choice is kept in the browser. A past run places its findings from the
  facts its `run.json` keeps.
- **The colour of a chip or pill means something.** Blue is running or informational, green done, yellow a warning, red an error. A kind of
  step or command (preview, full run, explore, route, searched, decided, copper, cutout, escape) has a hue of its own and no chip is grey.

## To 0.97.7

### Changed

- **The studio draws findings as areas.** A marker per finding piled up where many sat together. Findings that are close on the screen at
  the current zoom now make one cluster (clusters whose areas touch are joined, up to a size), drawn as a light rounded area outlined in the worst severity's colour, with a small count where it holds
  more than one. Zooming in separates them (the areas are made again a moment after the view stops changing). Hovering an area lists its
  findings, worst first; clicking one lists them in the Findings panel, and a lone finding opens its card as before.
- **The studio's stale generation notice can be resolved or hidden.** "Regenerate" starts a run (which generates the board again when its
  inputs changed) and resolves again when it ends; the status bar says "regenerating" with the step. The cross hides the notice for that
  board in this browser until the set of changed files changes. The notice names the cause in plain words, the files in a tooltip.

### Fixed

- **A route says when the router laid an island net narrower than its width.** The router retries a blocked wide route at its default
  track width and ships the net under the width asked; the route report said nothing (a net asked 1.37 mm shipped 16.6 of 17.2 mm under
  it, narrowest 0.16 mm, and the closure read 84.3%). The router's per-stage measurement is now read: `route.json` has `widths` (net,
  stage, `requested_mm`, `delivered_min_mm`, `length_under_mm`, `length_mm`, `share`, and the router's `max_a` for the narrowest
  copper), the summary line ends `UNDER WIDTH: ...`, `route_summary.json` has `under_width`, `placemat watch` shows a `route_width`
  event, and each is a `route.width` finding in the console and `run.json`. Critical when the net has a width in `[route] islands`
  or its ampacity is under the current the parts state (`Pm.I`), warning otherwise. Nothing to change in a script; a route that
  reports one is a route whose widths were not delivered.
- **The studio showed the stale generation notice after a run had regenerated the board.** The notice belonged to the last resolve and
  stayed until the next one; a run that ends well now starts a resolve when the one shown was on an out of date generation.

## To 0.97.6

### Changed

- **The native legality pass of a search is faster on a board with a shaped outline and large rule areas.** The board edge is judged through
  an index over the outline's segments, a rule area of many points is tested through an index over its edges (and cleared by its raster
  where the courtyard is far from it), the reservations a pass can reach are binned, and the obstacle grid is a dense array. The same
  placements, refusal counts, blockers and SVG: a large board's preview takes 44 s where it took 72 s, the native pass in it 9 s where it
  took 37 s. Nothing to change in a script.

### Fixed

- **The studio's "native off" pill shows only when native is off.** The pill's own style overrode the page hiding it, so it showed on
  every studio, with no tooltip, whatever the native module's state; any element the page hides now stays hidden.

## To 0.97.5

### Fixed

- **A module fragment's DRC no longer counts its missing outline.** Since 0.97.2 every KiCad error counts in the DRC headline, and a
  fragment's fit frame (`board.rect(fit=True)`) is never drawn on Edge.Cuts, so KiCad's `invalid_outline` counted against every
  fragment run (200 on its score, "worse than best" with nothing moved). On a frame-only board it is now expected: kept in the
  report (`expected`, and a summary note), not in the headline or the score.
- **The studio's running step shows its time where a finished step's stands.** The live timer sat in the row's second line and jumped
  to the right end of the first line when the step finished; the running row's first line is now laid out as a finished one (the item,
  what is being done, its time at the right end).

## To 0.97.4

### Changed

- **A carried via's give way is judged faster.** The native polygon clearance test stops at the first pair under the limit, a via's move
  search judges the board last, at the few spots that pass the cheaper tests (nearly all spots fail the pad, the copper it first met or the
  item's own copper), and a via's judgment against the board is one native call. The same placements, give-way actions and SVG: a core
  board's preview takes 72 s where it took 120 s, the give way in it 16 s where it took 61 s. Nothing to change in a script.
- **A candidate whose vias give way is charged what the give way judged against the step budget (`place.step_budget`).** It was charged
  one candidate however many spots and tails the vias' search put to the board (about 3300 on average in a core board's preview). A step
  with many carried vias reaches its budget sooner, and the `judged` its finding reports is larger. `place.via_clear_cache` now serves only
  a routed via's search.

## To 0.97.3

### Changed

- **A carried via's move or leave search stops at the nearest window with a spot.** The search judged every offset of its reach on the
  `place.via_move_step` grid before it took the nearest clear one, so a longer `place.via_leave_distance` cost the square of the reach: 3 mm
  instead of 1 mm is nine times the offsets for each via at each candidate, and on a cell with net ties each of them in Python. The offsets
  are now judged nearest first in windows (`place.via_search_chunk`, 64, each window twice the last) and the search ends at the first
  window that holds a spot; a net tie within reach no longer sends the whole search to Python, the native call judges the move without the
  ties' copper and Python judges each spot it accepts. The spot taken is the same: a core board's preview at the default reach gives the same
  placements, give-way actions and SVG, in 190 s against 290 s, and a 3 mm leave reach with `drops_keep_share` 0.25 runs in 262 s where it ran
  past twenty minutes. Nothing to change in a script.

## To 0.97.2

### New

- **A native module that is not in use is said on every run.** When `placemat_native` is not installed, would not import, or is from
  another release than placemat, placement falls back to pure Python (the same results, 5-10x slower on a large board), which was only a
  line on stderr at import. Every run, preview and explore now carries a `setup` warning (`setup.native`: `reason`, `placemat_version`,
  `native_version`, `detail`), `placemat run`, `preview`, `route` and `studio` print it first with the command to rebuild, and the record
  (`native`) is in `run.json`, the preview JSON, the channel's `hello` event (`placemat watch` shows it) and the studio's hello and header.
  `PLACEMAT_NATIVE=0` stays a silent, deliberate switch. A tool that read the stderr line reads `native`. Nothing to change in a script.

### Changed

- **Severity decides the DRC headline.** Every kind KiCad reports at severity `error` is in `real` (the `DRC ...` part of the summary,
  `drc_real` in `run.json`, `real` in `placemat drc --json`), not only the kinds in `[drc] real_kinds`; a kind such as `zones_intersect` no
  longer sits in `other`. `real_kinds` stays the kinds counted whatever their severity, and the footprint and outstanding kinds keep their own
  lines. The report carries each kind's severity (`DrcReport.severities`; `severities` in `placemat drc --json`). A run's score counts these
  as real violations, so a board with such errors scores worse than before and a run compared with an older record can read as a regression.
- **A board outside its project tree says so.** `placemat drc` on a run's `layout.kicad_pcb` reports `lib_footprint_issues` for every
  footprint when the folder has no `fp-lib-table`, or its `${KIPRJMOD}` entries do not resolve from there. The count and the violations are
  kept; the report records it (`DrcReport.libraries`: `state` `missing`, `unresolved` or `resolved`, the `unresolved` names; `libraries` in
  `--json`) and the summary says the library issues come from where the board sits, not from the board.
- **Child processes do not inherit KIPRJMOD.** pcbnew sets `KIPRJMOD` to an empty string in the C environment of a process that creates
  or saves a board, and a child started without an explicit environment inherits it. `kicad-cli` (DRC, the 3D export, the version query),
  the router and the studio's and builder's workers and runs now start with `placemat.childenv.child_env()`, as `pcb layout` already did.

### Fixed

- **A plane is written above the same-net zone it overlaps.** A plane the script declares on a layer where the board already has a zone
  of that net (a board-wide ground zone under a plane bounded to a fit frame) was written at priority 0 beside it, which KiCad's DRC
  reports as `zones_intersect`. The plane now takes a priority one above the zones it overlaps, and a plane overlapping an earlier one of
  the script does the same. The board's own zone stays and fills what the plane does not cover. Nothing to change in a script.

## To 0.97.1

### New

- **A preview or run can be bounded in time.** `--max-time SECONDS` on `placemat preview` and `run` (and so on `--explore`) stops the
  placement at the next point it can resume from, through the same stop path as SIGTERM (exit 143, `run.json` `stopped`, an explore keeps its
  variants and checkpoint), says how many steps it finished, the step and pass it was in and the findings so far, and the rerun replays the
  finished steps. A preview now keeps its finished steps in `.placemat/views/preview/reuse.partial.jsonl` for that, as a run always did.
  `--step-warn SECONDS` sends a live `step_warn` event and adds a notice finding (`time.step_slow`: item, seconds, pass) to a step that runs
  past it; `--step-limit SECONDS` makes the step give up (`time.step_limit`): unplaced, or at the best spot its scan had found, and the
  resolve goes on; such a step is searched again by the next run. Settings `[run] max_time_s`, `step_warn_s`, `step_limit_s` (all 0, off); a
  flag wins. The times are wall-clock and depend on machine load; the `[run]` settings are not part of a run's id. A new finding kind,
  `time`. Nothing to change in a script.

### Changed

- **A phase event is data, not a sentence.** The channel's `begin` events of kind `phase` carried a `text` ("refining around the best
  spots: 2 of 5"); they now carry `stage` (`declared`, `seeding`, `scan`, `coarse`, `coarse_half`, `fine`, `refine`, `give_way`) and its
  numbers (`within`, `face`, `hint`, `radius`), with the `item` and `elapsed_s` of the step they belong to and `firm_pass`. The studio makes
  its status pill from them, and `placemat watch` its line. A tool that read `text` reads `stage` and `within`. The scan also reports its fine
  pass, the coarse pass at half the stride and the give-way pass as phases now.
- **`placemat watch` lines read naturally.** `begin begin ble searched` and a bare `begin phase` are gone: `ble: searching, rank 3 of 12`,
  `ble: refining around the best spots, 2 of 3, 12.4 s`, `ble part, 1.2 s: note`; the total reads `40 items to place (12 searched), 3
  copper declared`.
- **Cell scans that meet another item's net tie are judged natively.** A candidate the native pass accepted was judged and
  scored again in Python whenever the scan met a net tie; one that also passes the native pass with the ties in is now legal without
  it, and scored natively. A real module's resolve took 49.8 s and now 12.6 s, with identical placements and findings. Nothing to change in
  a script.

### Fixed

- **`keep-out` allows KiCad's DRC epsilon.** A distance a hair under its limit from float noise (1.2599985 mm against 1.26 mm, a stamped
  pour's edge at the package's own pad gap, rotated and flipped) failed the check, where KiCad's DRC passes it. The check now accepts a
  distance within the board's DRC epsilon of the limit (500 nm on a fresh board, read from its design settings as
  `BoardGeometry.drc_epsilon`), in place of a fixed 1 nm. A distance 0.6 um short still fails.
- **Two stamped cells' zones of one net that overlap no longer fail KiCad DRC with `zones_intersect`.** Each cell arrives with its zone at
  the module's priority, and cells a keep-in apart have frames, so their zones, which the board's plane does not wholly cover,
  overlapped at one priority. Written, the later zone (in cell-name order) is now raised past the priority of every same-net zone it
  overlaps on a shared layer. A script is not affected.

## To 0.97.0

### New

- **A step's search has a budget.** `place.step_budget` is the most candidates one searched item's step may judge, counted over all its
  passes, both faces and the carried vias' giving way (candidates, not seconds: it does not depend on how busy the machine is), and
  `board.place(item, ..., budget=N)` sets one item's. A step that spends it takes the best legal spot found so far and says so
  (`setup.step_budget`, a notice), or, finding none, leaves the item unplaced: the `unplaced.search` finding carries
  `facts["budget"]` (`judged`, `share` of the search area covered, `limit`) and offers a higher `budget=` for the item, a searched
  suggestion. The default is high enough that no benchmark module or the core board reaches it, so nothing a script says changes.

### Changed

- **A scan with carried vias that may give way judges each refused candidate once.** A full pass judged every candidate as the item is
  and again, where that refused it, less its carried vias; it now judges less the vias first and the item as it is only where that was
  legal, which gives the same spots, counts, tallies and sentences. A failing search on a board with such vias takes about half the
  time in its native passes. Nothing a script says changes.

- **The live channel, `placemat watch --json`, the studio worker's events and the router's events carry records, not sentences** (event
  `format` 2; `hello` carries it, and a reader that finds none reads format 1; plan JSON `version` 3). A reader outside the repository
  that parsed the old text needs the new fields:
  - `item` events: the item has `notes`, a list of `{"kind", ...facts}` records (61 kinds, `step_text.py`: `rank`, `slid`,
    `moved_off_hint`, `vias`, `push`, `pocket`, `lock_held`, ...), and `unplaced` (the reasons, refusal records, for an item that
    found no place), where it had `note`, one "; "-joined sentence. `placemat watch` renders them; so does `Step.note` in a script's
    own checks (a read-only property of `Step.notes`).
  - `error` events: `kind` says which (`run_failure` with `failure` and the free text `detail`, `exception` with `type` and
    `detail`, `probe_refused` with `code` and its facts, `stopped`, and from `watch` itself `lost`, `died`, `cannot_follow`), with
    `file` and `line`; the `message` sentence is gone.
  - `route_off` events: `reason`, `{"code", ...}` (`no_function`, `no_parameter`, `no_field`, `import_failed`, `pipe_closed`), where
    `why` was a sentence. The router-side hooks (`kicad/route_events.py`) are version 2.
  - `probe` events lose `text` (the suggestion's sentence; its `id` and `figure.finding` say which), `probe_done` has `refusal` (a
    record) where it had `message`, and a `candidate`'s `error` is `{"kind": "timeout" | "exception", ...}`.
  - Plan JSON (`done` and `plan` events, a run's `plan.json`): steps and items have `notes` and `unplaced`, an `unplaced` entry has
    `reasons`, a finding has no `text` and its `facts` carry no rendered `text` fields, a reservation has `by` (a record) where it
    had `why`, a model entry's `why` is a word (`not_found`, `vrml_only`, `no_checksum`, `unreadable`, `no_model`) with `text` and
    `detail`. The studio server makes the sentences for its page (`present.py`) with the same renderers the console uses.
  - The studio worker's `done` has `reused` as a record (`{"form": "none" | "all" | "some", ...}`) and `stale` where it had two
    sentences, and its `error` and `try_error` events have `kind`, `type`/`failure` and `detail` where they had `message`.
  - The reuse record is version 4: the first resolve after the upgrade replays nothing. `run.json`'s steps keep `note` and gain
    `notes`.
  - The 3D converter's events (studio only): a `model` event has `failure`, a record `{"code", ...}` (`no_cli`, `no_mesh`,
    `timeout` with `limit_s`, `export_failed` with `returncode` and kicad-cli's own last line as `detail`, ...), where it had
    `message`; the ready event's `selftest` has `failure` (`planes_differ` carries `version`, `front` and `back`, the prism's boxes)
    where it had `message`. The studio page's own `message` is made from them (`model_convert.failure_text`). A failure kept in the
    model cache is a JSON record; one an earlier release kept as text still reads.
  - `placemat preview --json` gains fields, none changes meaning: `reuse` (what was reused, `{"form": "none" | "all" | "some", ...}`
    beside the `reused` sentence), `png_failure` (`{"code": "not_installed" | "timeout" | "failed" | "no_png", "tool", ...}`
    beside `png_problem`), and each of `notes` has `data`, the values its `text` says (a link's pads, length, limit and state; a
    pocket; the worst congestion cell; a finding's cause, severity and facts).
  - `placemat apply --json` gains `action` (`applied`, `would write`, `undone`), `edits` (the suggestion's edits as fields; none for
    an undo) and each file's `created` and `removed`; `text` stays the suggestion's sentence.
  A script is not affected.

### Fixed

- **A run folder keeps the board's rules.** A run folder held `layout.kicad_pcb` alone, so `placemat drc` or `placemat route` on
  `<run>/layout.kicad_pcb` judged it by KiCad's default rules and reported false clearance, width and short violations. The
  run folder now keeps `layout.kicad_pro` and `layout.kicad_dru` beside its board, and `drc` and `route` warn when a board has
  neither beside it (`drc --json` and `route --json` give `missing_rules`).
- **Generation ignores an inherited `KIPRJMOD`.** A process that had saved a board with pcbnew (or a placemat started from
  KiCad) passed `KIPRJMOD` on to `pcb layout`, which then resolved the stdlib footprint libraries against the wrong folder and
  failed with "Failed to load footprint". Generation now runs without it.
- **No `escape_walled` finding on a pin the capture leaves unconnected.** A `NotConnected()` pin whose footprint draws its pad
  as two elements (one number, two shapes) was counted as two pads on its net, so it kept escape corridors and was reported
  walled off like a pin with something to join. A pad is now counted once per footprint and number, and a pad the capture
  marks `no_connect` (KiCad pin type, read as `PadGeom.no_connect`) gets no escape judgment whatever its net is called. The
  net-name pattern (`NC_`, `unconnected-(`, a dot) is kept only as the fallback for a pad without the marker.

## To 0.96.1

### Removed

- **`check.neck_band` is gone.** It has not been read since 0.72.0 (`check.neck_end_share` and the neck length replaced it). A
  `placemat.toml` that still names it now fails as an unknown setting: delete the line.

### Fixed

- **A push on a member of a stamped cell fences that member alone.** An annotated pair (`Pm.Emits` / `Pm.Limit`) or a
  `board.push` whose item is a cell member reserved its disc against every member of the cell, so the whole cell had to stand
  outside it; and a source placed first looked ahead for room for the whole cell. Both now take the member the push measures,
  as api.md, "Push", says: the cell's other members may stand inside the disc. A cell holding a sensitive part can now stand
  with that part outermost; nothing a script says changes.

## To 0.96.0

### New

- **The studio has a 3D view.** A 2D | 3D switch draws the board built from the parts' real models (STEP converted with `kicad-cli`, VRML read
  by placemat), with the replay and live resolves following. The plan JSON is `version` 2: each member has `models` with a placement matrix, and the
  plan has `stackup` and `models`. A model entry now also carries its hide flag and opacity (`Footprint.models` has six fields where it had four;
  `describe.model_check` reads either), and `models.resolve_model` is the one resolver of a model path. Converted models are cached in
  `~/.cache/placemat/models` (shared by projects, 512 MB); the new `[studio] 3d_*` settings are in `placemat settings --example`. Needs `kicad-cli`
  for STEP models; nothing a script says changes.
- **Every step records how long it took.** `Step.seconds`, and for a replayed step `first_seconds` (the time it took when it was first
  resolved, from the reuse record), are in the plan JSON, the live `item` events and `run.json`'s steps; `metrics.resolve_seconds` is the
  whole resolve's. The studio's step rows, the card's Placement section and the Steps heading show them. The studio's Run button and menu
  entry read "Full run"; the endpoint is the same. Nothing a script says changes.
- **The studio's running status is one bar.** The step, its phase and the info icon sit together, with a progress bar of the steps
  done and, in a second colour, how far the step under way has got where its phase counts (`begin` phase events carry `within`, `[k, n]`;
  a phase with no count does not move the bar). The legend and the right panel each fold away (a handle on each edge, kept per
  viewer), and the source dialog's full-screen view fills the page below the header with no canvas showing under it.

### Changed

- **Searching a big cell is faster.** A searched cell's member boxes are moved when read, far reservations are rejected before
  rounding, the empty occupancy is built once and reservations are judged once per cell: a large board's preview took about a third
  less CPU, with identical placements and findings.
- **`placemat watch` finds a board's command from the workspace root.** The project root is the outermost folder with a
  `placemat.toml` or a workspace `pcb.toml`, so every command of a project registers in one sockets folder.

## To 0.95.0

### New

- **The studio has a board builder.** In the page: pick a `.zen` that has no layout script (a second group in the start view), state its
  facts in forms (stackup roles and weights, pair net classes, via types and fab minimums, the rise), draw its outline from a size
  suggested from the parts, and click parts into place by intent; the script is written as it goes and every step is an undo. See `api.md`,
  "Studio builder". Settings `[studio] builder_grid_mm`, `builder_max_fill`, `builder_aspect`. Nothing to change in a script.
- Engine: `script_edit` gains the ops `zen_stackup`, `zen_netclasses` and `json_set` (a `.zen` dialect and a JSON dialect of the splicing
  editor), a `{"block": [...]}` value and a `comment` for inserted statements, `set_constant` of a list of (x, y) pairs and with
  `replace_comment`, and `read_call`; `remove_statement` and `remove_constant` no longer leave a doubled blank line, and an edit's later
  targets and references follow lines an earlier edit inserted directly above them.

### Changed

- **A part stands tighter beside a part that draws a mark outside its body, and keeps room for declared copper.**
  `Beside(item, side)` took the distance from the box round everything `item`'s envelope is made of, so a pin 1 dot or any
  silk mark outside the body held the part off the whole side by the mark's reach. It now measures against the envelope's own
  shapes (pads, mask, silk and body under a physical envelope, the courtyard under a courtyard one): the part stands the gap
  off the nearest shape it faces, and a mark holds it off only where it stands over the mark. Where the nearer standoff would
  put the part in the way of something else already placed (another part's silk, a reservation, the edge), the part is moved
  on out along its side to the first place the collision rule allows (`place.beside_step`, up to `place.beside_reach`); with
  none within reach it stays at the standoff and the collision is reported as before. A rider and `copper=True` are laid as
  before, and so are a keepout or an escape item, a `Past` that turns a corner, and `row(of=)`.
  Placement also allows for the copper a script declares (`place.copper_room`, on): the firm items are placed again, as many
  times as it takes (`place.firm_passes`), against where the tracks and vias declared between them are planned to go, so a
  `Beside` part stands where there is room for them; a track or via whose end is a searched part is planned as soon as that
  part is placed, for the parts placed after it. A part that stands nearer than the box put it and is an end of copper that
  then meets other copper goes back to the box's distance. A `Beside` part that a firm `Beside` part placed before it kept
  from standing is placed before that part (its step says so). A track still moving at the last pass is `fixed.room_unsettled`;
  a part for which no place within reach keeps the copper's room is `fixed.room`. `place.copper_room = false` places as before.
  A script placing a part `Beside` one with a corner mark gets that part nearer; a later part aligned level with it follows. A
  searched part can land elsewhere than it did, with what it is linked to at another distance.

## To 0.94.1

### New

- **The studio's "Search options" runs a searched suggestion.** The button under a searched suggestion (finding rows, the card and the step
  rows) starts the probe, asks first where every candidate resolves the whole board, draws each candidate on the figure's range as it
  arrives, can Stop it and Continue it, and shows the outcome and what it found (`<id>.1`) with Show, Try and Apply. `GET /suggest/found?id=`
  returns a found suggestion; `/suggest/show`, `/try` and `/apply` accept its id.

## To 0.94.0

### New

- **The skill's loop starts with: iterate with `placemat preview`, run only at checkpoints** (the first look at a
  board, a change to keep, before committing), with what each stage of a run costs. Scripts change nothing.

- **A route streams per-net progress and keeps a record that replays.** `placemat route` owns a socket like the other commands, and
  `placemat watch` prints a line per net as the router finishes it. The events come from hooks on the router's per-net functions
  (`route_*` events, `api.md`, "Live progress"); if the router's functions are not as the hooks expect, the route runs with no
  progress and says why (`route_off`), and `PLACEMAT_ROUTE_EVENTS=off` leaves it unhooked. `route/route_record.json` keeps the copper
  in the order it was laid, per net; `RouteReport.record` and `run.json`'s `metrics.route.record` name it. A run that routes also
  writes `plan.json` in its run folder. Nothing a script says changes.
- **The studio replays a route and a whole build.** The Runs view draws a route net by net while it runs and lists the recorded
  routes of the board; one opens as a replay, and a run that placed and then routed replays from the first placement to the last
  routed net. `GET /routes`, `/route?f=` and `/build?run=` serve them.

## To 0.93.0

### New

- **Some suggestions are searched: the value is found by trying.** A suggestion with `how: "searched"` has a `figure` (what is
  varied and between which bounds, derived from the finding's own measurement) and no value, and is worded as a question
  ("Changing the chamfer of the A track might fix this: search options?"). `placemat apply <id> --search` resolves the
  edited script with each candidate value, in memory, and keeps the best as a new suggestion `<id>.1` with its value as a named
  constant; apply that. `--yes` skips the question asked before a probe that resolves the whole board for each candidate. A probe
  that is stopped keeps its results (`.placemat/probes/`) and the next `--search` continues from them. Settings
  `[studio] probe_budget_s` (120) and `probe_candidates` (12). This release offers it for the chamfer of a corner or cut
  (`copper.corner`, `copper.meets`), the arc radius of a cut (`copper.meets`) and which end of a leg takes its 45 (`bend=`, `copper.corner`).
  Apply refuses a searched suggestion. `POST /suggest/probe` and `/suggest/probe/stop` start and stop one from the studio; its
  events are `probe`, `candidate` and `probe_done` on the live channel.

## To 0.92.0

### New

- **Suggestions can edit inside a call and in several places at once.** An edit may go into an argument that is a call (a
  `Beside`'s `gap=` or side, a `Past`'s `across=`, a `Cutout`'s `at=`, one axis of an intent `Centre`) and a suggestion
  carries `edits`, a list made together or not at all, with one applied-log entry and one undo; its `how` says how it was
  found. `run.json`'s and `preview --json`'s suggestions have `edits` and `how` where they had `edit`; a record that has
  `edit` still reads. The outline (`rect`, `disc`, `outline`), a `row` and a `block` are declarations a suggestion can edit.
- **The editing engine has the operations a board builder needs.** `apply_edits` (the body of `apply_suggestion`, for
  edits that come from a person), `redo_last`, and the ops `create_file`, `ensure_import`, `remove_constant`,
  `move_statement`, `confirm_facts` and region inserts; `script_edit.read_intent` and `script_edit.skeleton`;
  `facts.confirmed_text`. An applied-log entry may have `before: null` (a created file) and a `source`.
- **`Centre(..., coordinates=True)` marks a coordinate.** `coordinates=False` is the default and is never written. A number on
  a `Centre` axis without the flag is still accepted in this release and gives a `setup` warning
  (`setup.centre_coordinates`); the next release refuses it. Writing `coordinates=False` is a `setup` notice.
- **The studio page reads findings' facts, not their sentences.** An unplaced item's card, row and finding show why, the radius searched,
  what refused it (a count per kind and the parts that did most of it) from the finding's `cause` and `facts`; a step's rank and the pocket
  it took come as data (`rank`, `rank_of`, `pocket`, `lock` on steps and items); the engine's own words for a refusal, an owner, a slide or
  a turn come with the facts as `text`. What a step's note alone says (seeds, slides, vias, pushes, the rank's measures) is still read from
  the note until the engine records it as data.
- **Findings carry suggestions: changes to the layout script that may clear them.** `run` and `preview` print the
  best one under each critical or warning finding (`try s3a: Place c4 beside c1, on its north side`) and the ids of
  the others; `run.json`'s `finding_details[i]` and `preview --json` give each finding its `cause`, its `facts` and its `suggestions`
  (`id`, `text`, `rank`, `lever`, the `edit` as data, and the `digests` of the files it writes). Every suggestion is a
  relation, a keyword or a setting, never a coordinate; a number it writes is a named constant with a comment. A
  record without the fields reads as none. `api.md`, "Findings and severities", has the shape and the causes.
- **A finding is data and its sentence is rendered from it.** A finding has a `kind`, a `cause`, the `facts` its site
  measured and `facts_v`, the version of that cause's facts; `run.json`'s `finding_details[i]` and `preview --json` carry
  all of them beside the `text`, which reads the same as before. The reuse record stores findings as facts and is under
  a digest of every cause's facts version, so a release that changes a cause's facts replays nothing. A refusal (why a
  spot was refused) is data too: `refusals.Refusal`, with a code and facts. Suggestions that multiplied a limit by a
  factor (a wider search radius, `place.via_move`, a finer step) are gone with `[studio] suggest_factor`: a number a
  suggestion writes is a figure the finding measured.
- **`placemat apply <id> [--script PATH] [--dry-run] [--undo]`** makes a suggestion's edit: `--dry-run` prints the
  diff and writes nothing; otherwise the file is written atomically and logged in `.placemat/applied.jsonl`, and
  `--undo` puts back the last apply that has not been undone, if the files are still as it left them. It refuses,
  and writes nothing, when the script changed since the run or preview that made the suggestion. `run` and `preview`
  keep the plan's suggestions in `.placemat/suggestions.json` for it.
- Settings `[studio] suggestions_per_lever` (3), `try_timeout_s` (60), and `apply` (true),
  none part of a run's id. Scripts change nothing.
- **The studio redoes an undone apply, and Show lists every file a suggestion edits.** `POST /suggest/redo` (token-guarded, allowed over
  `--host`, refused with `[studio] apply = false`) makes again the apply the last undo took back; the page offers Redo beside Undo. A
  suggestion with several edits shows its diff across all its files, each under its name. The page reads a suggestion's `edits` and `how`
  (instant, or searched: its "Search options" button is not built yet).
- **The studio shows, tries, applies and undoes a finding's suggestions.** Each finding row, the card and the step rows show
  the best suggestion with "more (n)"; Show opens its diff in the script dialog, Try resolves the edited script in the
  worker (read from an overlay, nothing written) and shows it as a compare marked "try, not written" - whether the
  finding cleared, findings gained and lost, items moved, the score change - Apply writes the file and the watcher
  resolves again, and Undo puts the last apply back, refusing when the file moved on. `POST /suggest/show|try|apply|undo`
  take `{resolve, id}`; apply and undo are allowed over `--host` and `[studio] apply = false` refuses writing. A
  history row of a resolve that followed an apply reads "applied from a suggestion: ...".
- **`libcst` is a runtime dependency** (`libcst>=1.0`), for the script edits. A board project's environment installs
  it with placemat.

### Changed

- **A pad on an escape lane needs a track's way out, not a via's.** The way on from the end of a pad's own copper (an
  escape lane, or a stub drawn from it) is looked for on the layer the copper is on; a spot a via fits at no longer counts, so
  a pin whose stub ends in a pocket only a via could leave is now `escape_walled`. Pads with no copper of their own keep
  the via rule. `place.escape_lane_via_exit = true` restores the earlier rule (a via spot at the end of the copper is a way
  out). Runs of a script with fanned pins can gain `escape_walled` findings and score; nothing in a script changes.

## To 0.91.1

### Fixed

- **A pin whose copper ends against another part is reported walled off.** A pad that copper of its own net left counted as
  having its way out, so a pin on a net with other pads, fanned out on an escape lane or a track that ends in the air, was
  never walled whatever stood at the end of that copper, a through-hole pad of another cell included. The way out is now looked
  for from where the pad's own copper ends (a track or lane that reaches another pad of the net, a via or a pour still counts
  as made), among what the clearance check refuses: other nets' pads on the layers they span, a through-hole pad on every layer,
  unplated holes (the `hole_clearance`), copper, and for a via the rule areas that forbid vias. Unplated holes also close a
  pad's corridors in the search now, as pads do. `escape_walled` appears where it did not, and the run score and the search move
  with it. A script that drew a track to nowhere from a pad (a stub the core's router takes up) may now get the finding.
- **A part searched in a pocket is no longer refused room under a through via it may sit over.** The free-rectangle raster
  that places an item nothing pulls toward, and the check before a search, blocked every through via on both faces. A via
  now blocks only an item that has something a via may not overlap (pads, copper, holes; its courtyard too under
  `vias_block_courtyards`), the rule a scan applies. A part that draws nothing but a courtyard or a body, over a board
  with vias spread across it, is placed where it was reported unplaced ("no pocket fits"). Scripts change nothing.

## To 0.91.0

### Changed

- **The router moves to a new checkout.** The built-in router is `~/work/KRT-upstream` (the router brought up to its
  current upstream, with filled copper graphics and pad-corner guards), where it was `~/work/KiCadRoutingTools`. `$KRT_DIR` and
  `[route] router_dir` still override it. A machine with `KRT_DIR` or `router_dir` set keeps the router it names:
  to move, point it at the new checkout (its `.venv` and `rust_router/grid_router.so` must be built there), or unset it. Routes
  differ from the old router's: pad corners are guarded exactly instead of by a half-cell buffer, so fine-pitch rows escape
  where they sealed, and a filled copper graphic (footprint ones too) is copper over its whole area.
- **A route no longer puts footprint copper graphics back.** The new router keeps a footprint's copper graphics on every
  layer, so the step that restored them is gone, and `restored_graphics` is no longer in the route report or its JSON. The rule
  areas that keep tracks off a footprint's copper (a net tie's winding, a coil) stay in the router's input copy and are deleted
  from the routed copy. Scripts change nothing.

## To 0.90.1

### Changed

- **The studio's running status shows one counter**, "step n of ~N", with the kind and phase pills and an info tooltip; the
  search rank stays on the card. On desktop the status gives way (subtitle, phase, kind, name) before it can reach the buttons.
  Scripts change nothing.

## To 0.90.0

### New

- **Studio board drawing.** A finding is a badge on a stem at one screen size (a triangle with ! for critical and warning, a circle with i
  for notice) with a white halo, a dark rim and a slow pulse, larger when it is the one looked at; tapping it opens the finding.
  Vias are drawn above the parts with their drill cut through (they were hidden under pads, and ringed white at high zoom), a
  through pad shows both layers' colours and its drill, and an SMD pad is the colour of its copper layer and goes with that layer's row in
  the legend. "Why it moved" in a card says what moved the part (the slide's stop, a refusal, a score gain) beside the distance, and
  "no cause recorded" where the step's note has none. The plan JSON gives pads their `layers` and adds `hole` and `npth` shapes.
- **Every setting is documented as data, and `placemat settings --example` writes a complete `placemat.toml`.** Each
  setting carries its unit and its meaning in `settings.py` (`Settings` field metadata, `settings.meta`,
  `settings.SECTIONS`); the api.md table is generated from them (`placemat settings --markdown`) and a test checks it.
  `placemat settings --example [--output FILE]` writes every section and setting with its default, unit and meaning,
  grouped by section, as valid TOML that loads to the defaults.

### Changed

- **Settings renamed to say what they are.** The old name still loads for one release, as the new setting, with a
  `setup` notice on the plan (and in `placemat settings`) naming the new one. Using both names for one setting in a
  table is an error. A run's id includes the settings by name, so the first run after upgrading is a new run.

  | old | new |
  |---|---|
| `rank.area` | `rank.area_weight` |
| `rank.pins` | `rank.pins_weight` |
| `place.coarse_steps` | `place.coarse_stride` |
| `place.coarse_from` | `place.coarse_min_radius_steps` |
| `place.refine_around` | `place.refine_spots` |
| `place.conflict_gap` | `place.conflict_reach` |
| `place.via_share` | `place.via_share_distance` |
| `place.via_move` | `place.via_move_distance` |
| `place.via_leave` | `place.via_leave_distance` |
| `place.via_route` | `place.via_route_distance` |
| `place.drops_keep` | `place.drops_keep_share` |
| `place.escape_pads` | `place.escape_min_pads` |
| `copper.arc_radius_widths` | `copper.arc_radius_track_widths` |
| `copper.bridge_half` | `copper.bridge_half_gap` |
| `copper.pair_via_step` | `copper.pair_via_offset` |
| `copper.pour_stroke` | `copper.pour_outline_width` |
| `copper.plane_min_thickness` | `copper.plane_min_width` |
| `write.keepout_line` | `write.keepout_line_width` |
| `write.keepout_text` | `write.keepout_text_height` |
| `label.size` | `label.text_height` |
| `explore.slack` | `explore.spot_slack` |
| `explore.swap` | `explore.swap_chance` |
| `route.iterations` | `route.max_iterations` |
| `solve.pull` | `solve.centre_pull` |
| `cleanup.radius` | `cleanup.search_radius` |
| `cleanup.step` | `cleanup.search_step` |
| `preview.model_edge` | `preview.model_edge_px` |
| `score.priority_high` | `score.unplaced_high` |
| `score.priority_default` | `score.unplaced_default` |
| `score.priority_low` | `score.unplaced_low` |

## To 0.89.0

### New

- **An explore keeps its curve and says when the best was found.** Every finished variant is on the curve: its index
  (the order it finished in, the plain placement 0), its seed, the seconds since the explore began (over every
  session of a resumed one) and its score, with `best` set when it beat every variant before it. `metrics.explore`
  in `run.json` and the explore record in `.placemat/views/explore/` have `curve`, `found` (`{i, seed, t, score,
  of_variants, of_seconds}`: the last improvement) and `ended`; the channel's `variant` events carry `i`, `t`, `score`
  and `best`, and `explore_done` carries `found` and `ended`. The checkpoint is deleted on completion, the record is
  not. The console line says `best found at variant 7 of 34, 5 min 12 s in (of 43 min)`. A curve past 2000 variants is
  kept as every improvement and an even sample.
- **`[explore]` stopping rules**, all off by default: `stall_variants` (stop after that many variants without an
  improvement), `stall_seconds` (or that many seconds since the last one), `stop_hard_clear` (or when a variant has
  none of the hard terms the plain placement had). `ended.rule` says which ended it: `budget`, `stall_count`,
  `stall_time`, `hard_clear` or `signal`. An explore ended by a rule is complete, not stopped: `--accept` applies and
  its checkpoint is cleared as for a finished one. The hard terms are parts left unplaced and the findings whose kind
  is critical by default that a plan's measures count (`fixed`, `copper`, `escape_walled`; `score.hard_clear`).
  The three settings are not part of a checkpoint's digest.

- **`placemat studio note "<text>" [--at X,Y | --item NAME | --pad REF.N]`** leaves a note where the user is looking at the studio:
  a record appended to `.placemat/views/studio/notes.jsonl`, shown on the page as a pin that follows its item or pad, a line in a
  Notes list (dismissable per browser), and a toast. Settings `[studio] note_age_s` (3600; 0 keeps notes) and `notes_keep` (100),
  neither part of a run's id. A point is a place to look at, never a placement. Scripts change nothing.

### Changed

- **`board.size(...)` is refused.** It was renamed `board.rect(...)` in 0.85.0 and has given a `setup` notice since;
  now it raises `AttributeError: board.size(...) is board.rect(...) since 0.85.0`. Rename the call, arguments
  unchanged:

  ```python
  board.size(width=60, height=40, chamfer=2.0)    # before: refused
  board.rect(width=60, height=40, chamfer=2.0)    # now
  ```

- **An arc corner's default radius is 3 track widths** (`copper.arc_radius_widths`, was 4): a `bend=Bend.ARC` corner
  with no `radius=` and no stackup bend rule is tighter than before. A script that relied on the old default sets
  `[copper] arc_radius_widths = 4.0` in `placemat.toml`, or `radius=` on the call.

## To 0.88.0

### New

- **A stopped command says so and keeps its work.** `placemat run`, `preview` and `route` handle SIGTERM, SIGHUP and
  Ctrl-C: the explore workers are ended, the layout folder is put back as the last run left it, `run.json` is saved
  with `status: "stopped"` and `failure: {kind: "stopped", signal, stage, elapsed_s, explore}`, a last line names the
  stage and the signal on stdout and stderr (stderr only with `-q`/`--json`), and the exit status is 128 + the signal.
  A second signal exits at once. A run's `run.json` is written as `status: "running"` with the `pid` as soon as its id
  is taken, so a record whose process is gone is reported as having died (`placemat impact` and the commands that read
  a run say so).
- **A stopped explore keeps its best and offers it.** `explore stopped by SIGTERM after N variants in T s; best seed S:
  a -> b mm; nothing accepted; accept it with: placemat lock <script> --accept-seed S`. Nothing is written to the lock
  on a stop, even with `--accept`. `placemat lock <script> --accept-seed N` writes the saved best (kept in
  `<board>/.placemat/explore/<script stem>/best.json`) to the lock without searching; it refuses when the lock or the
  script changed since the explore began.
- **An explore resumes.** The parent appends a line per finished variant to
  `<board>/.placemat/explore/<script stem>/checkpoint.jsonl` as it goes (the header holds the baseline, the budget and a
  digest of the script, generated board, settings, fab profile, placemat version, lock and focus). A rerun of the same
  explore (`placemat run|preview <script> --explore SECONDS ...`) finds it, says `resuming a saved explore: N variants
  in T s so far`, reuses the baseline, tries only the untried seeds and spends SECONDS less the time already spent.
  `--resume` insists on it and refuses, naming what changed ("the script and the lock changed since it began"), when the
  saved explore is not this one; without `--resume` such a checkpoint is dropped with a note and the explore starts
  over; `--no-resume` starts over regardless. The checkpoint is removed when the run that explored is recorded;
  `best.json` stays, so `placemat lock <script> --accept-seed N` works after a finished explore too (the explore's
  report ends with the command). `[explore] checkpoint_max_variants` (default 100000) bounds the file.
- **A resolve that died is replayed as far as it got.** Each completed step's record is appended to
  `<run dir>/reuse.partial.jsonl` as the resolve goes, and removed once `reuse.json` is written. A rerun of the same
  inputs replays those steps by their chained keys (a step that changed since is not replayed, nor any after it) and
  says `reused N of M steps from run <id> (interrupted)`.
- **A route keeps the stages it finished.** `run --route` and `placemat route` no longer empty the route work
  folder: `state.json` there names each finished stage (pairs, islands, main) with a digest of its inputs (the board
  and its project files, the nets left out, the islands, the layers, the router and its version, the `[route]`
  settings, chained from the stage before). A route that is stopped or fails leaves them; a rerun of the same inputs
  takes them (`took islands, main from an earlier route of the same inputs`, `report.resumed`) and only routes what is
  left. A stage that does not match is routed again with every one after it. `--no-resume` routes every stage again.
  A rerun of a run with the same id (same inputs) therefore no longer routes again unless `--no-resume` is given. The
  router's own pass is not resumable inside (its `KICAD_STOP_AFTER` / `KICAD_STOP_FILE` checkpoint stop could be
  used for that later). The raw router output is kept as `router_out.kicad_pcb`; `routed.kicad_pcb` is made from it
  each time.
- **An explore's workers are watched.** A worker that is killed from outside (the out-of-memory killer) or raises is
  reported with its exit signal or traceback, and the explore carries on with the others instead of waiting for it. A
  worker ends when its parent does.

## To 0.87.0

### New

- **A running command streams what it does on a socket it owns, and `placemat watch` and the studio follow it.** A
  command that resolves a board (`run`, `preview`, an explore, whoever started it) listens from its first resolve on
  `<project root>/.placemat/sockets/<pid>.sock`, with `<pid>.json` beside it (pid, command, script, arguments, started,
  label, progress file); both go when it exits, and readers remove the entries of dead pids. A reader that connects
  mid-run is first sent a catch-up (`hello`, the board, the steps and plan so far), then newline JSON as it happens:
  the steps and phases the studio's own worker sends, the finished plan, and for an explore the plain placement, each
  variant (seed, score, measures, the focused items' placements and order) and the end; then `done` with the record's
  path, or `error`. A command is never slowed by a reader: each has a bounded queue that drops what does not fit, and
  one that goes away is dropped. A board resolved with no script (a bench, a test) listens on nothing. Linux and macOS only.
- **A crash trail.** A command also mirrors its events, in short form, into an append-only `progress.jsonl`
  (`.placemat/runs/<id>/progress.jsonl` for a run, else `.placemat/views/<command>/progress-<pid>.jsonl`), flushed as it
  goes, so a command that dies leaves its last state. A command that starts deletes the progress files that earlier
  commands of its script left once those are no longer running. It is read only for a command that has ended or died.
- **`placemat watch [pid|label] [--json]`** follows one command of the project, or every running one: a line per step,
  per variant, until it ends. Exit 0 done, 1 error, 2 died (its last state is printed from its progress file) or not
  found.
- **The studio shows every placemat command of its project, live.** It reads every socket in the project's folder.
  The page's new Runs view lists the commands (command, script, pid, elapsed, state), a toast announces a new one,
  and opening one draws its steps on the board in place of the studio's own plan; a command found dead is listed
  as lost with its last state. An explore is shown with a plot of score against time and the best so far, the latest
  variant (at most `[studio] explore_fps` times a second, default 2) and the best drawn over the plain placement,
  thumbnails, a step through the variants by order or score, and where each item landed across them.
- **Studio page.** On a wide layout the running status is one line in the header (the strip above the timeline stays on
  narrow ones), and between two steps the step that just settled stays, dimmed, with its time. Unplaced items are shown
  as sections in the steps list, the card and the findings list: why, the radius searched around a point, and what
  refused it as counts per kind with the parts that did most of it as pills that select them. The legend's keepouts,
  reserved areas and a layer's zones start collapsed when there are more than three; the choice is kept in the browser.
- **An explore keeps its variants.** `.placemat/views/explore/<time>-<pid>.json` holds every variant (seed, score,
  measures, the focused items' placements and the order they were placed in) and which was kept; the studio lists and
  replays finished explores from it. `run.json`'s `metrics.explore` names it as `record`.
- **The studio's own Run is a command like the rest**: it reports over the channel and the page shows its live steps
  instead of its printed lines (the studio reads no printed text). A resolve worker that crashes is reported as a
  lost connection and the step it was on; the traceback is detail where there is one.

## To 0.86.4

### Fixed

- **The skill matches the code.** SKILL.md and the references were checked against every command, flag, script
  form and setting: the studio's address, buttons and endpoints, `board.keepout`'s and `board.rule`'s required
  `why=`, finding severities in the loop and the gate (no critical findings; every warning fixed or judged),
  `place.drops_keep` as a share, net-class differential pairs, and the `impact` and `occupancy` options. Scripts
  change nothing.
- `placemat studio --host` says what its QR code is for and sets it off from the log lines.

## To 0.86.3

### New

- **Open a studio view on another device.** The page keeps its view in the address's hash (script, face, visible box,
  selection, finding, tab), so an address copied or scanned opens the same view. A "Share" button shows a QR code of the
  current view's address on the studio's LAN address, with the address to copy and the system share sheet where the
  browser has one; a studio listening on 127.0.0.1 says to start it with `--host 0.0.0.0` instead. With `--host`, the
  terminal prints the same QR code under the address. The code is drawn by a small encoder inside placemat
  (`placemat/qr.py`, checked against an independent encoder in the tests), so nothing is fetched and no dependency is
  added; the server draws it at `GET /qr?u=ADDRESS` for the studio's own addresses only.
- **The studio's times are the server's.** The time since a resolve began, and on the step in hand, come from the
  server's clock, so they are right after a reload, a reconnect or in a second window (`hello` has `now` and the
  resolve under way as `work`; `begin` events carry `at`). A port already in use ends `placemat studio` with a plain
  message, naming another studio when it is one.

## To 0.86.2

### New

- **`POST /resolve` on the studio**: cancels a resolve in progress and starts another now, without a file having
  changed. `{"fresh": true}` resolves every step again instead of replaying the steps an earlier resolve did the same.
  Token required, like `/switch` and `/run`. The page has it as "Resolve" (a menu: again, or from scratch) beside Run and
  as "Again" in the strip shown while a resolve runs. `previewer.resolved` takes `fresh=` for it.
- Fit, and zooming to an item or a finding, frame the board in the part of the view the buttons, the card, the status
  strip and the slider do not cover.

## To 0.86.1

### Changed

- **The studio's running status sits above the timeline** as fields that stay on one line (the step, its kind,
  rank k of n, its phase, the time on it), and during a resolve Play reads Restart: it replays the steps so far,
  then follows the live end. Scripts change nothing.

## To 0.86.0

### Changed

- **Findings and docs say "cell" for a placed module.** Finding and note text, CLI help and the skill's docs used
  "module" for a stamped cell in places; they say "cell" now (for example the `split` finding ends "may be split into
  cells of their own"). "Module" stays for the source on disk: a module's layout script, its fragment, the
  `modules/` folder. A script or tool that matches finding text containing "module" should match "cell".

### New

- **The studio shows what a resolve is doing now.** Besides the steps that have settled, the page shows a spinner
  with the elapsed time and the steps so far out of about as many as are queued, a pending row for the step being
  worked on (searching, rank k of n, scanning the front, refining ...), a ring where an item is being tried, and
  replayed unchanged steps as one progress row. The stream has a new `begin` event for it: `{kind: "total", items,
  searched, copper, replay}` once, `{kind: "begin", item, what, rank, of, replaying, n}` as each item or copper batch
  starts, and `{kind: "phase", text, hint, radius}` a few times a second inside a long step. `Board.resolve` takes
  an `on_begin(plan, info)` callback beside `on_step`; with none, nothing is reported and nothing is slower.
- The studio's findings are marked on the board at the pad or part they name when they give no position, zones are
  rows under their copper layer in the legend, and every keepout is hidden by its own row.

## To 0.85.0

### Changed

- **`board.size(...)` is `board.rect(...)`.** The rectangular board form is named for its shape, beside
  `board.disc(...)` and `board.outline(...)`. The signature and behaviour are the same. `board.size(...)` still
  works and raises one `setup` notice saying so; the old name will be removed.

  ```python
  board.size(width=60, height=40, chamfer=2.0)    # before
  board.rect(width=60, height=40, chamfer=2.0)    # now
  ```

## To 0.84.0

### Changed

- **The run score prices what the placement search prices.** Three things the search weighs now count in a run's
  score, at the same weights, so a run and its search agree: the carried vias that gave way (the sum of the
  costs of the actions, `score.via_share`, `via_move`, `via_leave`, `via_route`, `via_shorten`, `via_drop`, and a
  field relay's `score.via_relay*` once), each push (`score.push` times its value over its limit, the whole value
  as the search prices it, at the final placement), and each item a `face=Face.EITHER` search put on the back
  (`score.back_face`). New terms `giveway`, `push` and `back_face` show in the `score` line; a run record from
  before has none of the three measures, which read as 0. A layout that gave way vias, was pushed or took the
  back face scores higher than before, so a recorded best of such a family may now lose to a later run
  that is no better. Finding severity is a display concern and does not enter the score. Scripts
  change nothing. `api.md`, "run score".

- **A track left out because it may not bridge is one finding, not two.** Where two tracks cross and the one that
  must yield may not bridge, the track is left out and the crossing finding says so (`A and B cross
  on F.Cu at (20.00, 30.00) and neither may bridge; track B is not drawn`); the separate `track X: not
  drawn, it crosses another net's track and may not bridge` finding is gone, so the `copper` count and score for
  such a layout fall by one per track left out.

- **A copper plan's own notes are scored under their own kind.** Each note a declared track, via, pour, plane or
  stitch raises is made as a finding of its own kind and severity where it is raised, instead of all being
  counted as `copper` warnings afterwards. They stay `copper` warnings, except that a pour whose `reach=` needs
  KiCad's pcbnew where it is absent is a `setup` finding.

## To 0.83.0

### New

- **`placemat studio` with no script.** The command lists the layout scripts under the current directory's project (the
  folder of the outermost `placemat.toml` above it, else the current directory), and the page opens on that list: title,
  subtitle and path of each, nothing resolving until one is chosen. The header's board name is the same list as a menu,
  so a studio can move between scripts in place. With no layout script found it exits naming the folder it searched.
- **The studio's Run button.** A checked run (`placemat run --no-render`: the design checks, KiCad's DRC and the score, a
  run record) from the page, with its progress and result shown; the runs recorded for the script (this one's or
  another's, from `.placemat/runs`) are listed with their score, DRC, checks and findings and can be compared with the
  newest resolve. `/runs`, `/runcompare?run=ID` and `POST /run` serve it.
- **The studio shows what happens to its worker.** A worker stopped by a signal is reported by name ("stopped by
  SIGTERM"), a crash with the signal and the line of the script or module that was running (from faulthandler), and a
  script's exception with its type and its own innermost line, including a line in a module it imports. Nothing is
  reported when the studio itself is stopping.
- **The studio streams copper and cutout steps** as they settle, so the timeline and the steps list grow during a
  resolve and the slider can be used; a footprint's own copper graphics (a printed winding) are drawn, planes are
  visible and congestion is a colour ramp with a scale.

### Fixed

- **A stamped cell's drawn track or via no longer leaves a pad reported
  walled off.** The escape check kept a stamped cell's copper where the
  cell stood before it was placed, so a pad joined by a track (to a pad
  holding a plane via, for one) read as unjoined and was reported
  `escape_walled`, a finding the module alone did not give. The check now
  holds the cell's copper where the cell stands. A pad is also no longer
  reported walled off or closed when only the boxes of a diagonal track or
  pour leave it no room: the path search falls back to their shapes before a
  finding is made. Findings that went away
  with it need no script change; a board whose cells were placed with these
  findings in the score may place them differently.

## To 0.82.0

### New

- **`placemat studio --host ADDR`**: listen on another address than
  127.0.0.1 (0.0.0.0 for every one), so a phone or another machine on the
  network can open the page; the printed address carries the token, which
  every request still needs.

- **`placemat studio <script>`: the layout live in a browser.** A local page
  (127.0.0.1, a token in the address) that watches the script, its imports,
  its lock and the board's `placemat.toml` files, re-resolves a moment after
  each change with a warm worker (replaying what the edit did not change, as
  `preview` does), and shows each step as it settles, the findings, the
  script beside the board linked both ways, and a compare with the resolve
  before: the changed lines and the items they moved, ghosts and arrows,
  copper and findings gained and lost. The page lists the layout scripts in
  the script's folder and switches between them. Read only; edit the script
  elsewhere.
  New settings `[studio] port`, `debounce_ms`, `open`, `keep`, `poll_ms` and
  `cancel_grace_ms`. Scripts change nothing. `api.md`, "Studio".

- **Every finding has a severity: `notice`, `warning` or `critical`.** `run` and `preview` print `[critical] U1
  pin 8 (GND): walled off by R2, U1` and `[notice] vias environment: 1 GND via shared, 1 moved 0.35 mm under cell
  X's U2`, the most serious first, and the finding count says how many of each. A notice is placemat doing what it
  is built to do, a warning a quality issue to judge, a critical finding a board that cannot be built or fully routed
  as it is (an unplaced item, copper that conflicts, a pad walled in, a rule below the fab's minimum). The kinds with
  mixed cases (`vias`, `copper`, `setup`, `label`) set it per case. `run.json` gains `finding_details` (`kind`,
  `severity`, `text`), and a record without it reads as warnings; `preview --format json` has `finding_details`, the
  studio's plan JSON a `severity` on each finding and `counts.severities`, and a failed check verdict has a severity
  (`critical` for `keep-out` and `current-path`). Scores do not change. `api.md`, "Findings and severities".

## To 0.81.2

### Fixed

- **An escape's lanes started at the row where a bypass stood beside it, with `run=` or a track from a pin beside the
  row.** A lane's start was judged only over the copper `run=` leaves it (a short stub), so a lane whose track goes
  on into a part did not see a bypass past the stub and stood at the row, through the bypass's pad. A lane is now
  judged out to the row's depth and a track and a clearance, whatever `run=` is, and starts past what stands beside
  the row. The firm tracks declared from a pad of the escape's part that is not one of its pins to placed pads (a
  bypass's track from the pin between the fans) stand in the occupancy as planned while the lanes are laid out, so the
  lanes leave room for them; before, such a track found the lanes across its way ("not drawn, it would run through a
  track") or ran 0.14 mm from one. Scripts change nothing; a lane that had no clear start now keeps clear of the
  bypass, where it was reported blocked or drawn through it. A bypass whose pad stands level with pin 46 (a 0402 pad
  turned 135 reaches 0.36 mm across) overlaps pin 47's riser by 0.04 mm, whatever the offset: that lane cannot leave
  west and is still reported blocked; the pad level with pin 45 leaves it. `api.md`, "An escape".

## To 0.81.1

### Fixed

- **A handoff pin reported walled in when its own lane gets out.** The
  `escape_walled` finding judged the way out on a grid of cells, which cannot
  follow a 45 laid between neighbours at the least pitch (the lanes of
  `escape(..., turn=Corner.X)` are): a pin whose lane could be carried on
  between its neighbours' lanes, or past their ends, was reported walled off
  by them. The search now also walks octilinear paths from where the pin's
  own copper ends (each end of its tracks, and its pad), on a lattice through
  that point, and a gap short of the clearance by under a nanometre is a tie,
  as it is for the occupancy's clearance. The finding is raised for fewer
  pins; a pin that really is closed in is still reported. Scripts change
  nothing.

- **An escape's lanes ran through a part placed beside its own part.** The
  lanes were laid out when the part was placed, before a bypass or similar
  placed beside it, so one escape over a row with such a part at its middle
  laid the lanes under it through the part (the way round was two escapes
  with a typed `depth=`). An escape is now laid out after the firm parts
  placed relative to its part, so its lanes keep clear of them and the lower
  ones start past them. A part placed relative to the escape (`Beside(esc,
  ...)`, a lane's end or via) still waits for the lanes. Scripts change
  nothing; a run whose firm parts stood where the lanes were reserved reports
  the lane as blocked (`escape_lane`) where it reported the part as colliding
  with the lane. `api.md`, "An escape".

## To 0.81.0

### Fixed

- **A carried via's track is held to the board's edge, and a move is not taken at a tail width that is not
  clear.** The search judges an item less its carried vias, and the give-way judged a via's ring against the
  board's edge but not its track, so a stamped cell could land with a via's track across a cutout or inside the
  edge keep-in (KiCad: `copper_edge_clearance`). A via's own track, and any track giving way draws (a tail, a moved
  via's redrawn tail, a routed via's rebuilt tracks), now keeps the edge keep-in as the item's own copper does, so
  the via moves, shares or leaves its pad as for any other conflict, or the spot is refused. A move whose
  narrowest tail the native search found clear but that no width clears in the full judgement was taken at the
  narrowest width anyway; it now goes on to the next spot. Placements can move.

- **A tail giving way draws joins the cell's group.** A cell's clearance rule (`A.memberOf('cell') &&
  B.memberOf('cell')`) holds in KiCad for the items of the cell's group. The tail a via's giving way drew was
  written outside the group, so placemat judged it against the cell's rule and KiCad's DRC against the netclass
  figure (`clearance`, 0.147 mm against 0.16 mm on one board). The tails and rebuilt tracks join the group of the
  cell the via belongs to.

- **A carried via is held out of a keepout that excludes vias.** A keepout
  that excludes vias but not parts, a rule area on the generated board that
  forbids vias, and one a placed cell brings were not tested against a part's
  or a cell's carried vias, so a via could be placed inside one and KiCad
  reported `items_not_allowed` (one board had three). A via whose ring meets
  such a region on a layer it covers, and whose net is not in `allow=`, now
  counts as meeting copper: it shares, moves, leaves its pad or is dropped as
  for any other conflict, and where none of those clears it the spot is
  refused ("keepout 'name' forbids vias: the GND via at ... is inside it").
  A via placed earlier that a cell's region covers gives way when the cell
  lands. Scripts change nothing; placements next to such a region can move.
  `api.md`, "Carried vias give way".

- **A line of labels gives way as one.** A list of labels, or `line=`, was
  left out of the labels that give way (0.71, 0.72): a part placed after it
  could land on a text, the line neither moved nor was avoided, and KiCad
  reported `silk_over_copper` ("Silkscreen clipped by solder mask") for a pad
  under the text. A text of the line that a firm item, or a searched item once
  it is down, would stand on or within the silk clearance of now moves the whole
  line: along its side, then to another side of its items, the texts keeping
  their spacing and order and each staying beside its own item, every text on
  the board and clear. With no clear spot the line stays, a `label` finding
  names it, and the part is placed all the same. Scripts change nothing; a
  board with a line of labels can place a later item, or end with the line, in
  a different spot. `api.md`, "Labels", which now also says a searched item does
  not see a declared label.

- **A keepout that excludes parts is judged on the courtyard KiCad tests.**
  KiCad's DRC tests each footprint's courtyard polygon against a rule area
  (`items_not_allowed`), never the body; placemat judged the part's body box
  (its courtyard less `courtyard_excess`, with its pads), so a part could stand
  up to 0.1 mm into a keepout and KiCad flagged it, under any `[place]
  envelope`. A keepout, a rule area on a generated board and one a stamped
  cell brings now refuse a part by its courtyard polygon, and a part that draws
  no courtyard by its claimed courtyard box. The envelope does not change it.
  Placements next to a keepout that excludes parts can move, by up to the
  courtyard excess and more where a courtyard is not a box. `api.md`,
  "Keepouts".

## To 0.80.1

### Fixed

- **Vias of an escape without a turn at a fine pitch.** `board.escape(part,
  pins, vias=[...])` on neighbouring pins at 0.4 mm pitch with a 0.45 mm via
  stopped the run ("no legal spot ... pad 9 of its own part, 0.075 mm off"):
  a lane beside another pin's via needs 0.465 mm between the via's middle
  and the lane (track 0.16, clearance 0.16), and straight lanes are 0.4 mm
  apart. A lane that finds no spot straight out of its pin now runs out to
  the least depth at which a 45 clears the row's pads and jogs along the row
  to either side (the nearer via wins), its via where that 45 first clears
  everything. A lane without a via no longer holds off the vias of the
  escape as a line five millimetres long: it is its stub, so a via beside it
  stands as near the row as the stub's end lets it (it was pushed out by the
  full search reach). A lane's own copper is judged against the vias placed
  before it. The message of a via with no spot names what stands in the way
  at the spot nearest to legal, with its true distance (it named the pad the
  search began at, 0.000 mm off for a via bigger than the pitch lets, whatever
  stopped it). A track that begins with a jogged lane draws the jog. A via
  size is the board's `via_size` (default 0.6) unless `via_size=` is
  given. Scripts change nothing. `api.md`, "An escape", "No turn".

## To 0.80.0

### New

- **A setting can differ per script.** A `placemat.toml` shared by a board
  and its module scripts takes `[scripts."modules/m/M_layout.py".solve]
  enabled = true`: any base section, keyed by the script's path relative to
  the file, applied over the base for that script only and shown by
  `placemat settings <script>`. `api.md`, "Per-script settings".
- **A `placemat.toml` beside a module no longer hides the folders above it
  from its imports.** A script's importable folders now run up to the
  outermost `placemat.toml`, not the nearest, so a module folder with its own
  file still reaches a helper in the board's folder. A project with a
  `placemat.toml` above a script and a same-named module in a folder between
  gets the nearer one first, as before.

- **A track's corners as tangent arcs: `bend=Bend.ARC`.** `board.track(net,
  points, layer=, bend=Bend.ARC)` draws every corner as a circular arc
  tangent to both legs (the legs planned as for an unset `bend`), written as
  KiCad arc tracks; `Bend.ARC_FREE` draws the straight line between the points
  at any angle with arcs at the corners. The radius is `radius=` mm on the call,
  else `copper.arc_radius_widths` (default 4) times the track's width. A corner
  an arc does not fit is a finding and the track is not drawn. `chamfer=` and
  `bridge=` are refused with an arc bend. Scripts change nothing. `api.md`,
  "Arc corners".

- **A turned escape's 45 lanes keep clear and stagger from the row's end.**
  `board.escape(part, pins, turn=Corner.NW)` (and the other corners) no longer
  stands the first lane a track and a clearance past the pad tips. A 45 moves
  away from its row, so the risers are staggered from the row's turn-side end:
  the pad there at the tips, each next pad of the row, named or not, one
  stagger further out (0.0526 mm at 0.4 mm pitch and a 0.32 mm step), and a
  named lane no nearer than where its riser and 45 keep the clearance from the
  row's other pads and from the copper placed when it is laid out. A lane does
  not move when another pin is named, and two escapes of one row lay their
  lanes parallel. A lane that cannot keep clear is an `escape_lane` finding.
  `depth=` is as before. `api.md`, "An escape".
- **A track that begins with a lane draws the lane.** A leg of the lane is not
  rerouted round copper that stands too near it (the reroute ran over the lane
  beside it); a leg that runs through another net's copper is not drawn, and
  the track's finding says what it would run through.
- **A handoff pin boxed in is a finding.** A pad whose net has no other pad on
  the board (a pin a module hands off to the parent board; not a no-connect
  net) that no track or via gets out of is an `escape_walled` finding naming
  what closes it, judged from the end of its own net's copper on it where it
  has some (a stub, an escape's lane). `api.md`, `score.escape_walled`.
- **A scored scan seeds its fine pass from the spots a rider takes too.** A
  searched part with riders (parts placed beside it) could miss a legal,
  better spot a fine step from a coarse spot the riders refuse; the fine pass
  now also refines round the best coarse spots by score, not only those the
  riders take. Placements of such parts can move to a better spot.

### Migration steps

- **Hand-staggered or coordinate fan lanes.** A fan of 45 lanes written as risers
  `depth=` values, or as `Past(...)` waypoints and coordinates that stagger each
  pin's riser by hand, is one `board.escape(part, pins, turn=Corner.X)`: the
  stagger from the row's end and the least depth that clears the row and the
  parts beside it are the escape's. Delete the arithmetic (a riser length
  `0.32 * sqrt(2) - pitch` per pin, a depth counted off the pad tips), name the
  pins, and draw each pin's track from `esc[pin]` to its part (a pad-to-pad
  track with one `Past(...)` waypoint and `bend=Bend.START` where the 45 must
  pass a corner). A pin the module hands off keeps its lane in an escape; one
  that is not named is only reported when it is boxed in.

### Fixed

- **A stamped fragment's notes never show on the board that stamps it.**
  A fragment's faces and clearance rules reach the parent as User.Comments
  texts (`placemat faces ...`, `placemat rule ...`). The parent's run read them
  and took them off its written board only when they were members of a
  group; one that was not stayed on the board. And while a run works, the
  layout folder holds the generated board: a run stopped before it wrote
  showed every note, each a few millimetres from its cell, stretching the
  cell's group box. Now the written board has none of them whichever way they
  sit, and a run takes them off the generated board as soon as it has read the
  facts they carry. A fragment run alone keeps the faces text it was stamped
  with and writes its own faces and rules afresh each run. A board the last
  run left in its layout folder from an older release still holds them: run
  it again. Scripts change nothing. `api.md`, "Faces" and "A stamped cell
  brings its own".
## To 0.79.0

### New

- **A dropped `Pm.Emits` / `Pm.Limit` look-ahead is a finding.** When no
  spot of the part placed first leaves its partner room at the limit
  distance, the part is placed as before and now a finding (kind `setup`) at
  its step names both parts, the limit distance and how far short the best
  spot fell. The partner's refusal ends "see: no room was left for it when
  M1 was placed", or says what was placed since took the room the look-ahead
  had left. Scripts change nothing. `api.md`, "Look-ahead".

### Fixed

- **A slide goes down before an item searched in two, within a tier.** A
  `Centre(x, None, toward=Edge.SOUTH)`, an `OnEdge(edge)` with no `along=`, a
  `Polar` ring or spoke, an `OnRim()` with no bearing, a stretch of
  `board.edge(facing=)` with no `along=`, and a point whose turn is searched
  have one freedom left. Such an item was ordered by courtyard area with the
  fully searched items of its tier, so a larger item searched first could take
  the line the slide runs along and stop it short of its end. Within a
  priority tier the slides now go first, by rank among themselves, then the
  items searched in two (`Near`, a `Polar` band, nothing). Tiers keep their
  order, and a script with no slide places as before. Placements can move on
  a board that has slides. `api.md`, "Degrees of freedom".

- **A `FreeSpot` via keeps clear of the tracks declared before it, whenever
  those are planned.** A track that waits for a searched part is drawn after a
  via decided early, and a via placed just clear of a pad stood where that
  pad's track (wider than the pad) could not leave: the leg ended 0.0986 mm
  from the via under a 0.10 mm rule, a finding and a KiCad clearance error. A
  `FreeSpot` via declared after a track of another net is now planned with
  that track (after it, in declaration order) instead of before the search.
  A script that declares the via first is planned as before. Declare the
  track first where the via should give way to it.
- **A finding never prints a shortfall as equal to the limit.** "is 0.10 mm
  from GND copper (needs 0.10)" for a gap of 0.0986 now reads "is 0.099 mm
  ... (needs 0.100)": more decimals, as many as it takes, when the gap is
  under the limit. The same for the via-site, tail and lane reasons. A via's
  drill is measured as its circle against a planned track or pour (it was an
  inscribed polygon, up to 2 um short).

- **A stamped cell's keepout `allow=` is carried to the parent and to
  KiCad.** A module's keepout that lets a net's copper through (`allow=(Net("GND"),)`
  with `vias`, `tracks` or `pads` excluded) was written as a rule area that
  forbids them to every net, so the module's own run set the allowed copper
  aside as `permitted by their keepout N`, and the board that stamped it
  counted the same copper as `items_not_allowed`, as did KiCad's DRC when the
  board was opened. The area is now written allowing what the nets keep, with a
  custom rule in `layout.kicad_dru` forbidding it to every other net, and its
  name carries the nets: the parent reads them, writes the same rule, and its
  vias, tracks and routes of those nets stand in the region. Run a module again
  to put the nets in its fragment. `api.md`, "Keepouts".
- **A stamped cell brings its module's `board.rule` clearances.** The parent's
  DRC judged a cell's copper at the net class clearance even where the module
  declared a lower one. A fragment now carries its rules and the parent adds
  them to its own, held to the cell, ahead of its own rules. Run a module
  again to put its rules in its fragment. `api.md`, "Rules".

### Migration steps

- A parent's `board.rule(..., within=Cell(...))` that repeats the clearance a
  module declares for that cell can be removed once the module has been run
  again; keep one that asks for something different, which stands after the
  module's and decides.


## To 0.78.0

### New

- **A `Pm.Emits` / `Pm.Limit` pair is not lost to the order its parts are
  searched in.** A source placed first could take the spot nearest the middle
  of a small round board and leave its limit partner no spot at the limit
  distance, the pair then fitting or not by where an unrelated hint landed.
  The part searched first is now refused the candidates that leave the other
  no legal spot (and the source is placed as before where none does). Scripts
  change nothing. New settings `place.lookahead` (true) and
  `place.lookahead_step` (1.0 mm). `api.md`, "Push, annotated".

## To 0.77.0

### New

- **`Face.EITHER` with tangent turns.** `board.place(item, face=Face.EITHER,
  at=Polar((r_min, r_max), None, about=c), rotations=Tangent(about=c))` was
  refused; each face the search scans now takes its own tangent turns, the
  outward side away from the centre on the back as on the front (the back's
  turn follows the mirrored item, so a declared east or west side swaps). The
  back costs `score.back_face` as for any `Face.EITHER` search. A cell
  pinned to a face only to turn it to a curve can drop the pin. `api.md`,
  "Round boards" and "Either face".

## To 0.76.0

### New

- **A turn taken from the spot's bearing, and a band of radii.**
  `rotations=Turns.TANGENT` (or `Tangent(about=, quarters=)`) turns a
  searched part or cell, at each spot, so its outward side points away from
  a centre, and also tries the half turn: two turns a spot, not the 72 of
  `Turns.ANY`, and the one that is tangent preferred. `Polar((r_min, r_max),
  None, about=centre)` searches the ground between two radii about a point,
  on a disc or a `board.outline()` board, so items stand inboard of a rim
  keepout. The bearing is binned by the new setting `place.tangent_bin`
  (10.0 degrees). `api.md`, "Round boards".

### Migration steps

**A cell or part turned by hand to follow a circle becomes a tangent turn in
a band.** A script that spread items round a circle and typed each one's turn
(45 degrees because it packed better than the right angles) has the search
take it.

```python
# before: a turn picked by hand, each cell in a ring of its own
board.place(Cell("<CELL>"), at=Pin(Part("<CELL>.<MEMBER>"), Location(<X>, <Y>)), rotation=45)

# after: searched in a radial band about the centre of the round part, turned to the tangent where it lands
board.place(Cell("<CELL>"), at=Polar((<R_MIN>, <R_MAX>), None, about=Location(<CX>, <CY>)),
            rotations=Turns.TANGENT)
```

On an outline board `about=` is the round part's centre, not `board.centre`.
Items that nothing pulls share the band's turn, and a link decides between
the outward turn and the half turn.

## To 0.75.0

### New

- **A part's `board.vias()` grid gives way.** A pad filled with vias used
  to be laid after its part landed and judged as copper afterwards, so
  another item's pad over a row of it either refused a searched item or
  left the row out of the grid. The grid is now carried with its part,
  placed firmly or searched, and gives way as a stamped cell's field does:
  a via moves, the field is re-laid (moved, a row shifted, the pitch closed
  or uneven, a row out, keeping the count), a via leaves its pad, a plane
  net's vias are dropped down to `place.drops_keep`. Same settings, costs
  and findings ("GND field in U1 pad 1 re-laid by uneven pitch, 8 vias
  before, 8 after under R6"); `inset=` is kept by a relay, and no two vias
  come closer than the floor `pitch=` is refused under. The grid is drawn
  after the search, so a pour that names it is planned after the search too.
  The row form, `vias(net, along=, count=)`, is unchanged. A grid on a net
  that is no plane, with no room, now refuses the other item's spot (a firm
  item: a collision) where the grid used to skip the site silently: a script
  that placed before may now see that refusal, and the item goes elsewhere. `api.md`,
  "Carried vias give way".


### Fixed

- **A stamped cell's faces note is left out of the written board.** A
  fragment's `board.faces(...)` note (a `placemat faces ...` text on
  User.Comments, 1 mm below its content) was stamped with the cell as a
  member of its group and stayed where it was when the cell was turned and
  placed, so a group's box spanned the gap (99 to 110 mm in one parent) and
  hand-placing it in KiCad was painful. The parent still reads the faces
  from it; the run now deletes the note from the written board. A fragment
  opened on its own keeps its note. Nothing in a script changes.

## To 0.74.0

### New

- **A routed via of a stamped cell moves with its tracks.** A via that two
  or more of a cell's tracks end on used to stay as drawn, so a cell whose
  routed via met the other face's copper was refused at every spot. It now
  gives way as a unit: it moves up to `place.via_route` (0.5 mm), and each
  track that ends on it is rebuilt from its far end to the new spot by
  octilinear legs, each clear of other nets, the whole move refused where
  any part is. Costs `score.via_route` (3). `place.via_route = 0` keeps the
  old behaviour. Nothing in a script changes; a placement a script had
  worked round by moving the cell may now find a spot. `api.md`, "Carried
  vias give way".

- **A via field is re-laid round a conflict, not only thinned.** Where
  another item's copper meets some vias of a field (a stamped cell's vias
  of one net in one pad: an exposed pad's grid, a plane net's drops),
  give-way took them out one at a time down to `place.drops_keep`, and
  refused the spot for a net that is no plane. It now re-lays the field
  first: the vias that meet it move to free sites of the field's lattice, a
  row or column shifts, the pitch closes toward one end or goes uneven, or
  whole rows are taken out, whichever is the cheapest legal layout inside
  the pad, new vias added where the pad has room so the count holds. Costs
  `score.via_relay` (3) once, `score.via_relay_moved` (0.5) per via moved or
  added, `score.via_relay_gap` (1) and `score.via_relay_pitch` (4) for an
  irregular grid. The finding names the way and the count, "GND field in U1
  pad 1 re-laid by shift vias, 9 vias before, 9 after". `place.via_relay =
  false` keeps the old behaviour. Nothing in a script changes; a spot that
  was refused or cost drops may now keep its vias, and a search may take a
  spot it had passed over. `api.md`, "Carried vias give way".

### Fixed

- A part's `Pm.KeepOut` no longer holds the part's own pad escapes. The rule
  written to the `.kicad_dru` and held by the planner applied to every track
  and via of the `away=` nets, so the track leaving a boot or switch pin,
  nearer a feedback pin than the package's own gap, was a KiCad clearance
  error and a planner finding, and the planner bent it round the part, once
  through another net's pad. The rule now holds a fitted pour and another
  part's pad against the part's pads on `pads=`, and no track or via of the
  `away=` nets (`api.md`, "A part's keep-out").
- `keep-out` judges the nets a `Pm.KeepOut` names as a pair at its distance:
  the feedback track and pour leaving the part's pad are held at it, not at
  the board-wide `check.keep_out_mm`. A track or via joined to the part's own
  pad on an `away=` net is its pad escape and is not judged, and a net of the
  part's other pads that `away=` does not name is not judged against its
  `pads=` nets: the package's gap to them is not the layout's. Another part's
  pad on a `pads=` net is held at the cited distance too, where it was held at
  the board-wide one.
- `[place] conflict_gap` is a floor. A conflict reaches as far as the largest
  clearance a rule asks, so a script or a `placemat.toml` that copied a rule's
  figure into it can drop the setting; a run no longer refuses to start where
  the setting is under a rule.
- A track or a via is not drawn through another net's copper. Where a declared
  track would run through a pad, a via, a track or a pour of another net, or a
  via stand on one, it is left out whole and a finding says which copper it met;
  before, it was drawn and the finding named the overlap, which KiCad reports as
  a short. Two tracks that cross where neither may bridge leave the one that
  should yield out. Copper nearer than its clearance but not touching is still a
  finding and drawn. A script that declared such copper and lived with the
  finding loses that copper: route it clear, or let it bridge (`bridge=True`).
- A part with a `Pm.KeepOut` no longer widens `Beside`'s gap to every neighbour
  on the nets it names: the keep-out holds pads and pours where they stand,
  and `Beside(copper=True)` reads it for the pad pairs it faces.

## To 0.73.0

### New

- **`SideOf(pad, along=True)`**: the side where a pad lies along its row,
  the row's end it is nearer, for `Beside`'s side and for `Facing`'s
  `toward=`. `SideOf(pad)` is the row's outward normal; `along=True` is the
  row's end, for a part standing past the end of a package, on the side where
  pin 1 or a supply pin lands, whichever way the package is turned or
  flipped. It names one pad, and refuses a pad exactly mid-row (neither end
  is nearer) and a pad with no row. `Facing(pads, toward=SideOf(pad,
  along=True))` turns the pads to face the part whose row end that is.
  `api.md`, "`Beside`" and "`Facing`".

### Migration steps

**A side picked by which end of a pin row a pad lies at becomes `SideOf(..., along=True)`.**

```python
# before: a flag for which end pin 1 lands at, kept in step with the part's turn
PIN1_END = +1                                   # +1: pin 1 at the south end, -1: the north end
board.place(Part("u"), at=Location(X, Y), rotation=TURN)
board.place(Part("bypass"), at=Beside(Part("u"), Edge.SOUTH if PIN1_END > 0 else Edge.NORTH))

# after: the side is where the pad lies along its row
board.place(Part("bypass"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), 1), along=True)),
            rotation=Facing(PadRef(Part("bypass"), "SUPPLY"), toward=SideOf(PadRef(Part("u"), 1), along=True)))
```

### Fixed

- `placemat facts --confirm` writes into the nearest `placemat.toml` that
  already exists above the board, the one the run uses, and creates one
  beside the script only when none exists. A new one beside a module script
  became the project root, so the runner stopped adding the board's folder to
  the import path and the module's imports of the board's shared helpers
  failed. The digest is recorded per script, in `[facts.boards]`, keyed by the
  script's path relative to that file (`"modules/m/M_layout.py" = "..."`), so a
  module and its parent board each keep their own. A file with the old single
  `[facts] confirmed = "..."` still reads, for every script with no entry of
  its own; the next `--confirm` of a script whose digest it holds moves it
  into the table. Nothing in a script changes; a `placemat.toml` made beside
  a module by the old `--confirm` can be deleted, and the module confirmed
  again.

- The "allow no 45" finding for a `Past(..., Corner.X)` waypoint is judged
  against copper on the track's own layer only: pads on that layer, vias whose
  span includes it, tracks on it. A track on an inner layer past a corner of
  front-only pads no longer gets the finding for them, and the finding names
  only the items it was judged against. The waypoint's place is unchanged:
  the lane still runs off every item the `Past` names, on whatever face.

- A cell placed by a member's origin (`Pin(Part(...), point)`) whose members are
  arcs on a round board, with copper at the keep-in, was refused "body box ...
  is past the board's keep-in (0.00 mm)" although its courtyard, body and
  copper were inside. Judged by its shapes, a corner of copper drawn as an arc
  stood a few microns past the keep-in: copper is read as a polygon the arc
  error (`[geometry] arc_error_nm`) outside the arc it is drawn as, and a
  board drawn with `board.outline` is flattened with chords inside its curves
  (`[geometry] arc_sag`) where `board.disc` is exact. A decided place's copper
  corners are now eased by those errors against the keep-in; copper further
  past it, and a courtyard or body that crosses the edge, are still refused.
  A refusal of a courtyard or body names the edge ("is past the board
  edge", "crosses the board edge") where it read "keep-in (0.00 mm)".

## To 0.72.0

### New

- **`reach=` on a fitted pour**: `board.pour(net, pads, layer=,
  swallow_pads=True, reach=mm)` grows the pour's copper into the room round
  it. The fitted outline is grown by `reach`, cut back by the clearance
  outline of every other net's copper planned before the pour, and of what is
  left the part joined to the members is drawn, as graphic polygon(s).
  `reach=` is a distance in place of a fact, so it is an escape hatch, as a
  coordinate is: a script uses it only on the user's yes for that one
  declaration, where the design does not yet hold the facts the intent form
  needs (no current known for the net, a pour wanted thick to route round by
  hand). Where the net's current is known, the form is `reach=Reach.CURRENT`
  (next entry). `reach=` needs pcbnew at plan time (KiCad's polygon
  booleans) and is refused with `width=` or without `swallow_pads=True`.

- **`reach=Reach.CURRENT` on a fitted pour**: `board.pour(net, pads,
  layer=, swallow_pads=True, reach=Reach.CURRENT)` grows the pour into the
  room round its pads only as far as its net's `current-path` width needs,
  cut back by other nets' clearance as `reach=mm` is. The need is the
  check's: the parts' `Pm.I`, `[check] rise_c`, the copper weight from the
  stackup. The distance is the smallest multiple of `[copper]
  pour_reach_step` (default 0.05 mm) that passes, up to `[copper]
  pour_reach_max` (default 5 mm); where another net's copper leaves no more
  room, a finding names the neck, the width reached and the width needed.
  It is refused where fewer than two parts carry current on the net. A pour
  without it is unchanged. `api.md`, "Reach.CURRENT".

- **`Facing` on a part with no pad rows**: a ball in a grid, a square pad at
  a corner of the pad field or a lone pad has the direction from the pad
  field's centre through the named pads' centroid, snapped to an axis, as
  its way out. Name the outermost row or column of a grid:
  `Facing([PadRef(p, "B2"), PadRef(p, "A2")], Edge.SOUTH)`. It is refused,
  saying why, where that direction is none or a diagonal (one corner ball
  alone). Pads that have a row behave as before.

- **`Facing` in a row**: `Facing(pad_key, edge)` names a pad by a bare key
  that each member resolves for itself, and `rotation=` of `row()`, `ring()`
  and a run row takes a number, a `Facing`, or a list of either, one per item
  (a list of the wrong length is now refused).

- **`SideOf(pads)`** as `Beside`'s side: the board side where the pads'
  way out points once their part is placed, its turn and face applied.

- **`Facing(pads, toward=PadRef(other, key))`**: the pads face another part's
  pad, whichever side it lands on; settled when the part is placed.

- **`board.row(items, edge, over=[PadRef, ...])`**: the row ordered by where
  the pads its items serve lie along it, once they are placed.

- **A searched item on either face**: `board.place(item, face=Face.EITHER)`
  on a part or cell with no position, or a `Near`, searches the front, then
  the back, and keeps the better spot, each judged and scored as spots are
  (legality, links, crossings, escapes, `board.push` and `Pm` limits, the
  flip rules). A back spot costs `score.back_face` (2.0) more, so the front
  wins an equal spot, and an item with no spot on the front takes the back;
  the step note says which. The default stays `Face.FRONT`: no existing
  script moves. It is refused with a decided position, an edge, a ring, a
  block and `rotation=Facing(...)`, which keep a fixed face. `api.md`,
  "Either face".

- **`current-path` weighs how long a neck is.** A stretch of the route
  narrower than the width its current needs is credited as short when
  conduction to the copper at each end holds its rise (`rho I^2 L^2 /
  (8 k (w t)^2)`) inside the neck's share of `check.rise_c`, and fails as
  "too long" when it does not. The note says "a 0.40 mm long neck at 1.03 mm,
  credited as short: ..." or "too long: ...". The neck's length is measured
  along the route: the run of track segments narrower than the need, or, in
  a pour or zone fill, the raster path between where the copper at each end
  reaches fill the need wide. New settings `check.neck_end_share` (0.6; 1
  turns the credit off), `check.neck_resistivity` and `check.neck_conductivity`;
  `check.neck_band` is no longer read (a config naming it still loads). A
  pour that necked between a package's pads and failed `current-path` may now
  pass; a neck that passed does not change. `api.md`, "check".

- **`Pm.KeepOut` on a part: a cited keep-out distance.**
  `Pm.KeepOut: 0.7mm pads=FB,COMP away=SW,BOOT; <datasheet, section>` on a
  part (capture, `references/capture.md`) is that part's keep-out limit: the
  `keep-out` check judges a pair with one of its `pads=` pads against copper
  on an `away=` net at that distance in place of `check.keep_out_mm`, and the
  planner holds it as a clearance between exactly those (a fitted pour, a
  track, a via and another part's pad keep the distance from that part's pads;
  its own pads, other copper on the same nets and other parts' pads do not).
  A citation is required: an annotation without one, a distance that does not
  read or a net no pad of the part carries refuses the run, naming the part.
  `pads=` defaults to the part's `Pm.Sensitive` net and `away=` to the switch
  nodes it is on. It is held in every module that carries the part and every
  parent that stamps it, with nothing repeated in a script. A datasheet
  distance never lowers a clearance below the netclass's or a `board.rule`'s.
  `board.accept` stays for a one-off verdict. `api.md`, "A part's keep-out".

- **A clearance rule can be a part's** (`rules.Rule.of`): between two nets, only
  where the copper on the second is a pad of one part and the copper on the
  first is not its own pad, written to the `.kicad_dru` as a
  `B.Reference == '<ref>'` condition and carried natively. Derived from
  `Pm.KeepOut`; not a script call.

### Migration steps

**A fitted pour that replaced a 0.70.0 `grow=` pour and lost current width
gets `reach=Reach.CURRENT`.** The 0.70.0 step turned `grow=mm` into a fitted
pour, which is the hull of its pads where the grown pour was the hull grown by
`mm`. Where `placemat check current-path` reports the net narrower than its
current needs, the pour widens to the current instead of carrying the old
distance; the parts that carry the net's current need their `Pm.I`.

```python
# before (0.70.0): the hull alone; current-path reports a neck narrower than the net needs
board.pour(Net("<NET>"), [PadRef(Part("a"), "<PAD>"), PadRef(Part("b"), "<PAD>")], layer=CopperLayer.F, swallow_pads=True)
# after: grown into the room round it as far as the net's current needs, cut back from other nets
board.pour(Net("<NET>"), [PadRef(Part("a"), "<PAD>"), PadRef(Part("b"), "<PAD>")], layer=CopperLayer.F, swallow_pads=True,
           reach=Reach.CURRENT)
```

**A `reach=mm` picked by trial for current width becomes `reach=Reach.CURRENT`.**

```python
# before: a distance found by trial, standing in for "carry the net's current"
board.pour(Net("<NET>"), [PadRef(Part("a"), "<PAD>"), PadRef(Part("b"), "<PAD>")], layer=CopperLayer.F, swallow_pads=True,
           reach=0.4)
# after: the width the current needs, from Pm.I, the rise and the copper weight
board.pour(Net("<NET>"), [PadRef(Part("a"), "<PAD>"), PadRef(Part("b"), "<PAD>")], layer=CopperLayer.F, swallow_pads=True,
           reach=Reach.CURRENT)
```

**A turn computed to read where a pad lands becomes `SideOf`.**

```python
# before: a numeric turn, read back to pick the side
TURN = 0 if PIN1_AT_WEST else 180
board.place(Part("u"), at=Location(X, Y), rotation=TURN)
VCC_EAST = (TURN == 0)
board.place(Part("pullup"), at=Beside(Part("u"), Edge.EAST if VCC_EAST else Edge.WEST))

# after: the side is where the pad lands
board.place(Part("u"), at=Location(X, Y), rotation=Facing(PadRef(Part("u"), 1), Edge.WEST))
board.place(Part("pullup"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))))
```

**A turn picked by a side flag becomes `toward=`.**

```python
# before
board.place(Part("c"), at=Beside(Part("u"), Edge.EAST if VCC_EAST else Edge.WEST),
            rotation=Facing(PadRef(Part("c"), "SUPPLY"), Edge.WEST if VCC_EAST else Edge.EAST))

# after
board.place(Part("c"), at=Beside(Part("u"), SideOf(PadRef(Part("u"), "VCC"))),
            rotation=Facing(PadRef(Part("c"), "SUPPLY"), toward=PadRef(Part("u"), "VCC")))
```

**A row's order picked by a flag becomes `over=`.**

```python
# before
order = [r_sda, r_scl] if SDA_WEST else [r_scl, r_sda]
board.row(order, Edge.NORTH, of=Part("u"), centre=PadRef(Part("u"), "SDA"), rotation=0)

# after
board.row([r_sda, r_scl], Edge.NORTH, of=Part("u"), centre=PadRef(Part("u"), "SDA"), rotation=0,
          over=[PadRef(Part("u"), "SDA"), PadRef(Part("u"), "SCL")])
```

**A row's rotation list computed per member becomes a `Facing`.**

```python
# before
board.row(caps, Edge.NORTH, rotation=[0 if PAD1_WEST[c] else 180 for c in caps])

# after
board.row(caps, Edge.NORTH, rotation=Facing(1, Edge.WEST))
```

**A cell pinned to a face by hand becomes `face=Face.EITHER`.** When the face
was picked by trying both, or by hand because the front was full, and nothing
makes it face something, let the search choose.

```python
# before: the back, because the front had no room beside its links
board.place(Cell("c"), face=Face.BACK)
# after: the front when it fits and costs no more, else the back
board.place(Cell("c"), face=Face.EITHER)
```

A cell that must stand on one face (a connector that faces out, a part that
must be on the side a user touches) keeps `face=`. `Face.EITHER` with a
decided position or an edge is refused, naming what decided it.

**A per-net `board.accept("keep-out", ...)` for a datasheet distance becomes
`Pm.KeepOut` on the part.** An acceptance taken because a regulator's own
datasheet draws the feedback or compensation pin nearer the switch node than
`check.keep_out_mm`, repeated in each script (and in each module stamped into
a parent), is the part's fact. Put it on the part in the capture, with the
datasheet cited, and delete the acceptance: the check judges the part at its
distance, and the planner keeps the copper that far from those pads.

```python
# before: in every script that places the part, per net, and again in each module stamped into a parent
board.accept("keep-out", "SW", at_least=0.7, why="the datasheet's reference layout puts FB 0.7 mm from SW")
```
```
# after: once, on the part (the capture's annotations; the citation is required)
Pm.KeepOut: 0.7mm pads=FB away=SW; datasheet rev B, section 10.2, layout example
```

An acceptance for a layout fact (a pour that cannot be pulled back, a pad pair
no distance fixes) stays `board.accept`. An acceptance for `current-path` on a
short neck can go once `current-path` credits the neck: run the check, and
keep the acceptance only where the note says "too long".

### Fixed

- A fitted pour over a pad that stands nearer another net's copper than the
  clearance (two pins whose footprint gap is under it) is drawn, holding the
  part of the pad that is clear of that copper, where it was refused with "so
  no pour can hold the pad clear". The pour's added copper keeps the full
  clearance from the other pad; the pad pair's own gap is the footprint's. A
  pad wholly inside the clearance outline is still refused.
- A graphic polygon with a hole (a pour with `reach=` round a pad it cannot
  touch) is read back with the hole, as a zone fill's are, so the pad in it is
  not taken for copper under the pour.
- The board edge is judged as KiCad judges it. Copper (pads, and the copper
  a cell carries) stays `board.keep_in` inside the edge and out of cutouts by
  the same, as before; a courtyard and a body only have to stay inside the
  edge itself and out of cutouts. A part's body and courtyard were held the
  keep-in inside the edge too, which KiCad has no rule for. A searched part
  or cell may now stand nearer the edge by the margin its courtyard has past
  its copper (up to `board.keep_in`), and a cell of arc-shaped members whose
  courtyards reach past the keep-in on a round board, with the copper inside
  it, is placed where it was refused with "past the board's keep-in". A
  courtyard that crosses the edge itself, and copper nearer the edge than the
  keep-in, are still refused. Where an item is placed at the edge (an edge
  row, `OnEdge`, `OnRim`, a ring at the rim) its reach still lands at the
  keep-in. A refusal of a courtyard or body now reads "body box ... (0.00
  mm)", and of copper "copper to edge: box ...".

- A user label could cost a searched item its place: the label's reserved
  box and silk stood as obstacles, so a cell or part searched later was
  refused "its member ... sits in the reservation for label ..." (or "...
  mask opening is ... from label ... silk") where the label held the only
  room, and a run could end with no room along it. A search no longer sees
  labels (other items' silk and pads still count); once the item is down,
  the labels it lands on give way as they do for a firm part, and a label
  with no clear spot is a `label` finding while the item is placed. A block
  is still searched with labels in view.

- **A label stays on the board.** A `board.label()` that moved for a firm part
  could land past the board edge, where silk is not printed, and a label's
  first spot was not checked against the outline either. A label's spot is
  now inside the board's outline and outside its cutouts, the board's silk
  clearance from the edge (round and shaped boards included). A label that is
  declared off the board moves to another spot beside its item; with none on
  the board it is a `label` finding.

## To 0.71.0

### New

- **A label gives way to a firm part**: a `board.label()` is a user's mark,
  so a part placed firmly (`Location`, `Pin`, `Beside`, `OnEdge`, `row`)
  within the silk clearance of its text, or on its box, no longer collides
  with it: the part stays where it was put and the label moves, along its
  declared side, then to the item's other sides, always next to its item.
  The label's step note says where it moved from and to; with no clear spot
  it stays and a `label` finding names it. `label.slide_step` (0.25 mm) is
  the step along a side. A `Location` or `Beside` that was nudged off a
  label to clear it can go back to where it belongs, and a label's declared
  `side=` and `align=` are now where it prefers to stand, not where it
  must.

- **A via in its pad may leave it.** A carried via inside a pad of its own
  net, with no tail and no spot inside the pad clear of another net's
  copper, moves to the nearest clear spot within `place.via_leave` (1.0 mm;
  0 never leaves) and is joined to its pad by a new tail on its own face, at
  the net's track width or narrower down to the board's minimum. It is tried
  after move and before shorten, priced at `score.via_leave` (4). A part that
  was refused for "no spot within 0.50 mm inside its pad is clear" may now
  place. `api.md`, "Carried vias give way".
- **The run's refusal tally counts vias that could not give way.** A
  refusal ending "cannot give way" is counted as "vias that could not give
  way xN" in the no-legal-location note, not under the copper, through or
  hole word its sentence begins with.

### Fixed

- A searched item that owns or meets a net tie ran the slow Python search
  for every candidate since 0.66.0, about forty times slower than the native
  one, so a cell with a net tie and no legal spot could take an hour where it
  took minutes. The native search now leaves the tie's shapes out and judges
  the candidates it accepts in full, with KiCad's net-tie exclusion. The
  spots chosen are the same.

- A refusal for a carried drop whose fab profile tier for a shorter via is
  `"no"` now says when that via would have cleared the spot ("a blind via
  from B.Cu to In3.Cu would clear this; the fab profile does not allow blind
  vias"), where it said nothing of it.

- A `Beside` (or any firm placement) next to a cell with a labelled member
  stopped the run with "silk is 0.17 mm from label ... silk (needs 0.20)"
  when the label's text stood slightly past the member's end. The label now
  slides clear of the placed part.

## To 0.70.0

### New

- **Settings for what were literals**: `place.edge_step`, `place.pocket_step`,
  `place.freedom_min_step`, `place.cutout_step`, `place.cutout_angle_step`,
  `place.escape_cell`, `copper.finger_min_piece`, `copper.tap_overlap`,
  `geometry.cap_steps`, `check.neck_band`, `solve.pull`, `solve.spread_pull`
  and `solve.spread_growth`. Each defaults to the value it had, so nothing
  moves.

- **A turn searched about a fixed point**: `rotations=` on a place that is a
  point (`Pin` on a part's pad, a cell's member pad or a member's origin,
  `Location`, `Centre`, `Origin`, `Mid`) keeps the item on the point and
  searches its turn. Each turn is judged as a decided place is (the board's
  keep-in, keepouts, other items) and scored as any search is (links,
  `Pm.Emits`/`Pm.Limit` pairs, `board.push`, escape lanes); the cheapest
  wins, and a tie goes to the `rotation=` given. A bearing to avoid is a
  keepout over what stands there. `rotations=` also takes a step in degrees
  (`rotations=5`) or `Turns.ANY`, every `place.bearing_step` degrees
  (default 5.0). Before, `rotations=` on such a place was read and ignored.

### Migration steps

**A pour with `grow=` becomes a fitted pour.** `board.pour(net, pads, layer=,
grow=mm, within=)` is refused: it wrote a KiCad zone grown from the pads, which
copper planned later could cut through. A fitted pour is a static polygon
joining the pads, drawn at its place in the batch; copper planned after it
keeps clear. A pour of a plane net (ground) that used `grow=` becomes
`board.plane(net, layers, over=[...])`. A `board.stitch` over the pour works
as before, over the fitted pour's outline.

```python
# before: a KiCad zone grown from the pads, which copper planned later can cut through
board.pour(Net("<NET>"), [PadRef(Part("a"), "<PAD>"), PadRef(Part("b"), "<PAD>")], layer=CopperLayer.F, grow=<mm>)
# after: a fitted polygon joining the pads; copper planned later keeps clear of it
board.pour(Net("<NET>"), [PadRef(Part("a"), "<PAD>"), PadRef(Part("b"), "<PAD>")], layer=CopperLayer.F, swallow_pads=True,
           why="...")
```

**A cell turned about a fixed point at a bearing picked by hand becomes a
searched bearing.**

```python
# before: the bearing is a constant, chosen by trying turns until the links looked right
board.place(Cell("c"), rotation=FIXED_DEG, at=Pin(Part("c.member"), POINT))

# after: the turn is searched about the point, scored by the links, pushes and keepouts
board.place(Cell("c"), at=Pin(Part("c.member"), POINT), rotations=Turns.ANY)
board.keepout(Circle(4.0), "arms", at=..., why="where the arms join")   # a bearing to avoid is a region
```

A script that already passes `rotations=` with a `Pin`, `Location` or `Centre`
that names a point now has its turn searched; before, the item was laid once
at `rotation=` (0 if none) and `rotations=` was ignored. Drop `rotations=` to
keep that one turn.

### Fixed

- A fixed cell whose member is drawn as an arc along a round rim is no longer
  refused "body box ... is past the board's keep-in" when the member's box
  corner passes the rim but its pads, courtyard and copper do not. A fixed
  part turned off the axes was already judged by what it is; a cell now falls
  back to its shapes when its members' boxes fail, as a part does. A searched
  item is still judged by boxes, natively and in Python alike.

## To 0.69.0

### New

- **A part's origin as a point**: `Origin(Part(...))` is a part's footprint
  origin as placed (a cell's `Origin(Cell(...))`: its frame origin), a point
  wherever a point is taken: `at=`, `X()`/`Y()`, `Mid`, `Polar(about=)`,
  `Pin(key, point)`. `at=Origin(Part("a"))` stands a part's own origin on
  a's, and waits for a. It replaces coordinates worked out to put one part
  on another's origin (`X(Part(...))` is the body centre, not the origin).

- **A part on a midpoint**: `at=Mid(a, b)` places a part's origin (a cell's
  box centre) on the midpoint of two references, as `at=Location` does, and
  waits for them. It was refused ("at= takes a Location, a Centre, a Pin,
  ..."). Before: `at=(X(Mid(a, b)), Y(a))`; after: `at=Mid(a, b)`.

- **A pair of a part's own pads on a point**: `Pin(Mid(10, 11), x, y)` puts
  the midpoint of two of a part's own pads on a point, and `Beside(item,
  side, align=(Mid(10, 11), point))` lines it up across the side; `align=`
  also takes `X(...)`, `Y(...)`, `Mid` and `Origin` as the other part's
  point. `Pin(key, ..., land=Land.LARGEST)` (or a land's number) puts one
  land of a pin drawn as several on the point. These replace an offset
  worked out from the pads' spacing to centre a pair of pads on a
  coordinate.

- **Turns by intent**: `rotation=Parallel(a, b, degrees=0)` turns a part so
  its own x axis lies along the line between two points, at any angle;
  `Bearing(a, b, degrees=0)` is that line's compass bearing for `Polar`.
  `rotation=Facing(PadRef(part, n), Edge.NORTH)` (or a list of pads) is the
  right-angle turn where a pad's row points at an edge, refused where no
  turn does. A rotation typed as a constant (3.96, 270) that is right only
  because of where pads happen to be, and an `assert` on pad positions after
  the place to check it, are these forms.

- **Near-straight legs drawn straight**: a track leg whose ends differ by
  less than `copper.straight_tolerance` (default 0.002 mm) on one axis is
  drawn straight; before, a pad-to-pad track between pads 0.001 mm out of
  line got a 1 micron jog, which `measure --copper` flagged as off 0/45/90.
  `measure --copper` judges by the same tolerance.

- **A fitted pour joins vias**: `board.pour(net, members, layer=,
  swallow_pads=True)` takes the vias `board.via()` and `board.vias()` return
  (all of a `vias()` result) and a lane's `.via` as members, with or without
  pads. A via counts on the pour's layer when its span includes it; one that
  does not span it is a finding naming it, as is a pad without copper there.
  The pour is planned after its vias.

### Migration steps

- SKILL.md, "Placement and copper practice", gains three rules: a plane
  net is a zone and a power join is a fitted pour; a sense line leaving
  power copper is its own net with a net tie at the tap; a decision taken
  from a datasheet cites it in `why=`. A script that draws ground as a
  pour, or runs a sense track on the power net, changes to match.

- A board no longer keeps a placemat gaps file. When no form says a
  relation, send it as a request to the agent working on placemat itself;
  it files the request in placemat's `BACKLOG.md` and replies (SKILL.md,
  "When no form says it"). A comment beside an approved coordinate names
  the request's backlog title instead of a gap entry.

**An inner-layer area over vias, written as a plane over their parts, becomes
a fitted pour of the vias.** `board.plane(over=)` is a KiCad zone: it fills the
whole box round the parts and lets copper planned later be drawn across it. A
fitted pour is drawn at its place in the batch and copper planned after it
keeps clear.

```python
# before: a zone over the converter and its capacitors, standing in for the area
board.plane(Net("VOUT"), layers=(CopperLayer.IN2,), over=[Part("u_conv"), Part("c_out")])

# after: the area is the outline round the vias dropped from the output pads
drops = board.vias(Net("VOUT"), along=PadRef(Part("c_out"), "VOUT"), count=3)
board.pour(Net("VOUT"), [drops, board.via(Net("VOUT"), FreeSpot(PadRef(Part("u_conv"), "VOUT")))],
           layer=CopperLayer.IN2, swallow_pads=True, why="the output area on In2, joining the drops")
```

**A part on another part's origin, a midpoint or a turn read off pad
positions becomes `Origin`, `Mid`, `Parallel` or `Facing`.**

```python
# before: coordinates and turns worked out from the footprints
board.place(Part("b"), at=Location(A_X + ORIGIN_DX, A_Y + ORIGIN_DY))  # a's origin, worked out
board.place(Part("c"), at=(X(Mid(PadRef(Part("a"), 1), PadRef(Part("b"), 1))), Y(PadRef(Part("a"), 1))))
board.place(Part("d"), rotation=3.96, ...)        # parallel to a's pads 1 and 2, read off their positions
board.place(Part("e"), rotation=270, ...)         # so pins 9 to 12 face north, with an assert on pad positions

# after: the relations themselves
board.place(Part("b"), at=Origin(Part("a")))
board.place(Part("c"), at=Mid(PadRef(Part("a"), 1), PadRef(Part("b"), 1)))
board.place(Part("d"), rotation=Parallel(PadRef(Part("a"), 1), PadRef(Part("a"), 2)), ...)
board.place(Part("e"), rotation=Facing([PadRef(Part("e"), n) for n in (9, 10, 11, 12)], Edge.NORTH), ...)
```

### Fixed

- `board.stitch(..., edge=True, outside=True, sides=)`: a row that meets a
  side not kept now ends `hole_to_edge` plus the via's radius in from that
  side, as a shared corner's via already stood off both its sides. In 0.68.0
  the row began at the corner itself, so its end via could land on the board
  edge when the unkept side lay on it. A run with `sides=` also gets a finding
  naming the board side each row landed on ("east side -> board north"; the
  sides are read in the keepout's own frame as turned). Rows that ended at an
  unkept side are shorter by that inset, so their via positions move.

- A plated hole keeps the board's hole clearance from the copper of another
  net, a net tie's own copper bar included (KiCad's `hole_clearance`). A via
  from `FreeSpot` could land with its drill 0.15 mm from a net tie's bar,
  which KiCad's DRC flags and placemat did not; the search now steps past it,
  and a part, via or track left too near a drilled hole is a copper finding.

## To 0.68.0

### New

- **`board.stitch(net, region, edge=True, outside=True, hole_to_edge=,
  pitch=, sides=)`**: ground vias in a row outside a region's edge, each
  hole edge `hole_to_edge` off it along the edge's outward normal (by default the via's
  copper touches the edge), at most `pitch` apart (a side `L` long gets
  `ceil(L / pitch) + 1`, spread evenly), along the sides named
  (`sides=[Edge.EAST, Edge.SOUTH]`, read in a keepout's own frame when it is
  placed with `rotation=Turned(part, ...)`), one via shared at the outside of a
  corner between two kept sides. It replaces a row of computed `Location` vias
  typed out for a datasheet's "vias outside the clearance". A via that cannot
  stand is left out and noted, and a gap over `pitch` is a finding.

- **Regenerable output goes under `.placemat/views/`**: `preview`, `show`
  and `layer` write there (`views/preview/`, `views/show/`, `views/layer/`),
  and placemat writes a `.gitignore` of `*` into `.placemat/views/` so none of
  it is tracked. Run records under `.placemat/runs/` are unchanged.
- **`placemat datasheet` writes no file by default**: `--show` prints the
  page's text (and says so when the page has none); `--png` or
  `--out FILE.png` also render it. `placemat drc` no longer leaves a
  `drc.json` beside the board.

- **`board.figure(at=, rotation=, anchor=, why=)`**: a datasheet figure's
  frame, for a dimensioned reference layout only (`why=` names the datasheet
  and figure, and is required); `fig.point(x, y)` is a point of it in the
  datasheet's own coordinates, usable as a `Pin` target, a track, finger or
  via point, `Polar(about=)` or inside a `Mid`; `board.keepout(Path(FIGURE),
  name, frame=fig)` puts the figure's keepout in the same frame.

### Migration steps

**Ground vias typed out along a region's edge become a stitched row
outside it.**

```python
# before: the datasheet's vias outside the clearance, each a computed point
for x, y in ((1.20, -3.55), (3.20, -3.55), (5.20, -3.55), (5.75, -1.60), (5.75, 0.40)):
    board.via(Net("GND"), at=Location(x, y))

# after: the row the datasheet asks for, read off the region itself
board.stitch(Net("GND"), "antenna clearance", edge=True, outside=True, hole_to_edge=0.35,
             pitch=2.0, sides=[Edge.EAST, Edge.SOUTH], why="datasheet: vias outside the clearance")
```

**A script or agent that reads a datasheet page PNG from beside the PDF, or a
preview, show or layer image from the old folders, reads the printed path
instead.** `.placemat/preview/`, `.placemat/show/` and
`<layout>/.placemat/layer-*.svg` are now under `.placemat/views/<command>/`;
each command prints where it wrote. A script that read `drc.json` beside the
board runs `placemat drc --json`.

```
# before: the PNG appeared beside the PDF
placemat datasheet d.pdf --show p3
cat d-p3.png

# after: ask for the PNG; the command prints its path
placemat datasheet d.pdf --show p3 --png      # <project>/.placemat/views/datasheet/d-p3.png
placemat datasheet d.pdf --show p3 --out page.png
```

`--out DIR` still takes a directory.

**Points of a datasheet's dimensioned layout typed as board coordinates
become points of the figure.**

```python
# before: the keepout in the datasheet's frame, its feed pad and vias worked out by hand
board.keepout(Path(CLEARANCE, anchor=(0, 0)), "antenna clearance",
              at=Mid(PadRef(Part("ant"), 1), PadRef(Part("ant"), 4)), rotation=Turned(Part("ant"), 0))
board.via(Net("GND"), at=Location(12.43, -3.08))

# after: one frame, the datasheet's numbers as printed
fig = board.figure(at=Mid(PadRef(Part("ant"), 1), PadRef(Part("ant"), 4)), rotation=Turned(Part("ant"), 0),
                   why="antenna datasheet p7, recommended layout")
board.keepout(Path(CLEARANCE), "antenna clearance", frame=fig)
board.via(Net("GND"), at=fig.point(4.2, 0.9))
```

### Fixed

- A via laid after a fitted pour of another net in the same batch (a
  `board.stitch` grid, a `FreeSpot` via) keeps its clearance from the pour.
  In 0.67.0 it could land inside the pour: a stitch over a grown pour beside
  a fitted one put its vias in the fitted pour ("via VBUS ... is 0.00 mm from
  PP5V copper").

## To 0.67.0

### New

- **Fitted pours** (replace pull-back): a pour over pads is fitted when it
  is planned, the shortest straight-edged outline that holds its pads and
  keeps every other net's copper its clearance, written as a graphic copper
  polygon, never a zone. `api.md`, "A fitted pour".
- **`Beside(..., copper=True)`**: a part stands a clearance (by net pair,
  `board.rule` included) plus `gap` off another part's pads, measured copper
  to copper.
- **`Pin(key, Polar(radius, bearing, about=...))`**: a pad a mechanical
  pitch from another pad along a bearing (0 north, 90 east).
- **Graphic copper polygons in the read commands**: `placemat measure
  --copper` lists each one (net, layer, stroke, filled, vertices, and per
  edge the nearest other-net copper, the gap, the clearance and `under`);
  `--json` adds `polygons`; `placemat layer` draws and counts them. Fingers
  are such polygons.

### Migration steps

**A pour drawn as points, or as a hull cut back from other copper, becomes a
fitted pour.** Pull-back is gone, and `cover=` or a plain point on a
swallowing pour is refused, so these scripts stop at the declaration until
they are moved.

```python
# before: corners as points, or a hull/box, cut back from other copper when written
board.pour(Net("SW"), [PadRef(Part("q1"), "SW"), (2.4, -1.1), PadRef(Part("l1"), "SW"), (0.8, 0.6)],
           layer=CopperLayer.F, swallow_pads=True, cover=Cover.CENTRES)

# after: the pads it joins; the outline is fitted round every other net's clearance
board.pour(Net("SW"), [PadRef(Part("q1"), "SW"), PadRef(Part("l1"), "SW"), PadRef(Part("c_boot"), "SW")],
           layer=CopperLayer.F, swallow_pads=True)
```

What changes in a script:

- `board.pour(net, pads, swallow_pads=True)` over three or more pads changes
  shape, from a hull cut by other copper to the fitted outline. Where nothing
  stands inside the hull, the outline is the hull.
- `cover=` with `swallow_pads=True` and a plain point (a `Location`, an
  `(x, y)`) among its points are refused at the declaration. Name the pads
  the pour joins and drop `cover=` and the points. A pour that needs a
  hand-drawn shape goes without `swallow_pads` and is drawn as declared
  (`cover=Cover.HULL`, `Cover.BOX`, or its points).
- `board.pour(net, [pad_a, pad_b], swallow_pads=True)` with exactly two pads
  and no `width=` is fitted too (the outline round the two pads). With
  `width=` it is the neck, drawn as declared, as is a two-pad pour without
  `swallow_pads`.
- A pour without `swallow_pads`, and a declared neck, are drawn as
  declared and nothing is cut from them: another net's copper inside one,
  or within the clearance of its copper (its outline plus half its stroke),
  is a copper finding. Before, a declared pour was held at its outline, so a
  pour too close to another net's pad or pour raised no finding.
- A pour that cannot be fitted (other copper where the outline cannot go
  round it, or two pads that cannot be joined) is not drawn, and a copper
  finding names the copper and the pads. A pour whose outline narrows under
  its net's track width is drawn, with a finding where.
- A pour sees the copper planned before it. Declare it after the tracks and
  vias it has to go round, or the later copper meets it as a finding.
- A pad of another net among a swallowing pour's pads, or one with no copper
  on the pour's layer, is a finding and the pour is not drawn.

**A `Beside` gap worked out so a pad lands a clearance off another part's
pad becomes `copper=True`.** `gap=` counts from the envelope, which sits
inside the pads by a footprint's own amount, so the worked-out number was
right only for that footprint.

```python
# before: the gap tuned by hand until the sense pad read 0.16 mm off the pad
board.place(Part("nt_sense"), at=Beside(Part("shunt"), Edge.NORTH, gap=0.26,
                                        align=(1, PadRef(Part("shunt"), "VOUT"))), rotation=0)

# after: the clearance by net pair, copper to copper
board.place(Part("nt_sense"), at=Beside(Part("shunt"), Edge.NORTH, copper=True,
                                        align=(1, PadRef(Part("shunt"), "VOUT"))), rotation=0)
```

**A pad placed at an offset coordinate from another pad, at a mechanical
pitch, becomes a `Polar` about that pad.**

```python
# before: an offset typed into X()
board.place(Part("j_b"), at=Location(X(PadRef(Part("j_a"), 1), PITCH), Y(PadRef(Part("j_a"), 1))), rotation=0)

# after: the pitch along a bearing from the pad
board.place(Part("j_b"), at=Pin(1, Polar(PITCH, 90, about=PadRef(Part("j_a"), 1))), rotation=0)
```


### Fixed

- `Beside(keepout, side, align=PadRef(part, pad))` is taken, as the pair
  form `align=(own_pad, PadRef(part, pad))` already was. It was refused ("a
  keepout has no pads to align on").
- `board.stitch(net, keepout_name)` over a keepout that excludes vias but
  lets the net in (`allow=(Net("GND"),)`) stitches it. It was refused
  ("excludes vias ... add 'GND' to its allow="), and past that check no via
  was let stand in it.
- `Pin(key, Polar(...))` was refused ("float() argument ... not 'Polar'").
- A declared pour too near another net's pad or pour now raises a copper
  finding; it was judged at its outline without its stroke and passed.
## To 0.66.1

A net tie placed so it stands out from a pad of its net (`Pin(1, PadRef(...,
edge=...))`, turned so pad 2 lies further out) is no longer refused for its
copper bar's clearance to that pad: KiCad's DRC gives a net tie's copper
drawing no clearance to the nets of the group's pads it overlaps
(`DRC_ENGINE::EvalRules`, "Net tie"), wherever they meet, and placemat now
judges the same. A datum part with such a tie riding it is placed where it
was refused at every turn. Where a pad meets a net tie's pad, the exclusion
(`DRC_ENGINE::IsNetTieExclusion`) is judged at the position KiCad's own shape
collision gives, read from the pad's and the graphic's effective shapes, and
holds only if it holds whichever item KiCad tests first. No script change.

## To 0.66.0

`Pin(key, point)` places a part's pad on one point (a `Location`, a
`PadRef`, a `Mid`); `Pin(key, x, y)` is unchanged. A `PadRef` with `edge=`
(and `along=`) is now accepted as that point, or through `X()`/`Y()`: the
part's pad lies against that edge of the target pad, outside it, flush with
the pad's side at `START`/`END`. Its size across the edge is the part's at
its rotation. `edge=` is still refused for a via's `at=` and the like.

A net tie (a footprint with KiCad net-tie pad groups) that draws no
courtyard, silk or fab claims its pads and its copper graphics only, under
every `[place] envelope`: another part's body or courtyard may stand over
it, and another net's pad or copper keeps the clearance from it. Before,
its courtyard (falling back to the box round its pads and bar) was claimed,
and under `physical` a shunt's body kept it out of the shunt's own gap. A
net tie that draws a courtyard is unchanged.

`placemat run --no-render` keeps the layout folder's last renders
(`layout.png`, `layout-iso.png`, `layout-bottom.png`) instead of deleting
them. They show the board as an earlier run placed it: the run log says
which ("not rendered: layout.png kept from run <id>"), and `run.json`'s
metrics carry `renders_from`, the run that made them.

`board.accept(check, subject, at_least= | at_most=, why=)` takes one failed
check verdict as it is, with the reason, instead of a board-wide limit
loosened for it. Within the bound the run reads "accepted" for that verdict
and counts it under `checks_accepted`; past the bound it fails as before. An
acceptance that matches no verdict, or whose verdict passes, is a `setup`
finding. A script without `board.accept` runs, digests and locks as it did.
`api.md`, "Accepting a check verdict".

## To 0.65.2

A track from a net tie's pad across the tie's own copper is judged where
KiCad's DRC judges it: at the track's collision position as KiCad computes
it for a segment against a polygon (its start, when the copper holds it,
else the nearest point of the copper's edges to its centreline), not where
the two outlines first cross. A track leaving a round net-tie pad over the
tie's bar was a clearance finding KiCad's DRC does not report.

## To 0.65.1

`check crossings-under` no longer counts another net's copper behind a
plane: copper on another layer under a sensitive track counts unless a
plane fill on a layer between them covers the crossing. An inner trunk
under an outer RF track, with a ground plane between, was a failing
crossing.

`board.escape` takes `chamfer=` (default `copper.chamfer`), `via_size=` and
`via_drill=` (default the board's, as `board.via()`'s `size=` and `drill=`).
The lanes are laid out, reserved and, for a track that begins with a lane,
drawn with that chamfer; the track's own `chamfer=` still wins, and the lane
is then laid out with it. A script that gave a lane's track a smaller
`chamfer=` to keep its 45 off another lane's via, or gave each lane's via a
`size=` the escape's did not have, can say it once on the escape and drop it
from the tracks.

The via search now judges every lane still to be placed as it will be drawn:
square and cut at its chamfer. A chamfer's 45 runs across the inside of the
turn, so an outer lane's corner could stand inside the clearance of an inner
lane's via; the via now moves along its lane instead, and a script whose
lanes' vias stood where the square corner allowed may see them a little
farther along. `chamfer=0` gives the square layout back.

A lane's reservation no longer stays in the occupancy once a track begins
with the lane: the track's own copper is judged in its place, so a clearance
finding against a lane's reserved copper that the drawn track clears is gone.

An escape may name a pin drawn as two lands, one in each of two rows (a
QFN's corner pin): it stands in the row by the land that leads out the way the
other pins do, and its lane starts at that land. An escape whose pins have no
way out in common is refused at the declaration with the ways named, and an
escape that cannot be laid out where the part stands (a via with no legal
spot) fails the run with that message, not a traceback.

A pad that copper of its own net already leaves (a track from it, a via in
it, a pour over it, a grown pour's hull) is no longer an `escape_walled` or
`escape_closed` finding; one that is still walled names the copper by owner
("track NET", "via NET", "pour NET", "the escape lane of U1 pin 53"), no
longer by an empty name.

## To 0.65.0

The router and the copper findings keep `board.rule` clearances. The
clearance between two items is now that of the last rule declared that
matches them (higher or lower than the net class pair's), else the net
class's, as KiCad's DRC reads the written `.kicad_dru`; before, only the
DRC did. A swallowing pour's pull-back reads the rules too. A script that
held a track off a net a rule names with a waypoint can drop the waypoint;
a script whose rule lowered a clearance no longer gets findings KiCad does
not report. A rule above `[place] conflict_gap` stops the run with a
message naming both.

`board.pour(net, pads, layer=, grow=mm, within=None)` grows a pour from its
pads up to the copper round them. A script that drew a pour as a polygon
bounded by the neighbouring lanes, vias and parts (a column over two pins,
its edge a clearance off another pin's lane, widening into a capacitor's
pad) can name the pads and a `grow=` instead; the polygon's arithmetic goes.
The pour is a KiCad zone: its outline is the pads' hull grown by `grow`,
clipped to `within=` (a keepout's name, a `Cell`, or `Part`s), and KiCad's
fill keeps it off every other net's copper and applies the board's
clearance rules. Removed in 0.70.0: see its migration step.

A plane's fill keeps the script's `board.rule` clearances. KiCad reads the
rules file beside a board as it loads it, and the file was written after
the fill and the save, so a plane filled to the net class's clearance
where a rule asked for more; KiCad's DRC then flagged it.

`board.escape(part, pins, turn=, vias=, ...)` declares a pin row's routes
out (a riser and a lane for each pin, a via where it ends in one) and keeps
them clear from the moment the part is placed: another net's pads, holes
and copper keep the clearance from them, a searched part's lanes are priced
in its search (`score.escape_lane`, 400), and a lane something blocks is an
`escape_lane` finding. Its handles stand in for what a script worked out by
hand: `board.track(net, [esc[pin]])` draws a pin's riser, lane and via;
`esc[pin].via` is a via a track, a `Past` or a `Beside` can name;
`Beside(item, side, align=(own_pad, esc[pin]))` puts a pad on a lane's line;
`X(esc[pin].end)`/`Y(esc[pin].end)` give a lane's end. A script that has a
lane line as the pin tips plus a track width and a clearance, a via at that
plus half a via, or a part stood a pad's width past a via can say the lanes
once and refer to them. `board.fanout()`
stays: it keeps bodies off a part's pad rows, which an escape does not.

## To 0.64.1

A track declared `bridge=True` that passed under another among the copper
planned before the search no longer stops the run ("'Via' object has no
attribute 'layer'") when copper is planned after it.

A track leg whose every way conflicts (a pin at a fine pitch whose leg
crosses the pin beside it) now also tries a short straight along the other
axis before or after its 45, and a leg already one 45 tries the L shapes
too; it had no other way to go and was drawn across what stood on it.
Where none of those clears either, the leg is drawn as before and the
finding stands.

## To 0.64.0

A carried via's move, and a share's tail, are judged by one native call
each instead of offset by offset in Python: the same placements, steps and
findings, faster where vias give way. Near a net tie the move is still
judged in Python, as before.

`board.keepout(..., bars=(Part(...), Cell(...)))` names the parts a region
keeps out and lets every other part in. A script that lists every other
part in `allow=` to bar a few (hundreds of references, stale when a part
is added) can give `bars=` the few instead. `bars=` and `allow=` of parts
or cells are refused together; `allow=` of nets is unchanged, and
`max_height=` still judges the parts `bars=` does not name.

`check current-path` measures a drawn pour along the load's route, as it
does a zone fill, instead of at the pour's narrowest section anywhere. A
sliver off the route (where a pad's rounded corner meets the pour's edge)
no longer fails a wide pour. A pour's width reads within one
`check.zone_step` of its true width.

A label at `rotation=90` is boxed where it reads: up the page from its
anchor, as long as the text. Its box ran down over its own item and off to
one side, so its reservation and its "sits on" findings were in the wrong
place; a script that moved parts to clear a vertical label's finding can
drop the move. Under `[place] envelope = "physical"` a label sits on a part
when it overlaps one of the part's shapes (its body, pads, mask, silk, or
the courtyard an undrawn part claims), not the box round them: a label in
the corner of a round part's box no longer sits on it.

`PadRef(part, pad, edge=Edge.SOUTH, along=Along.END)` is a track point on
that edge of the pad, touching it: a Kelvin tap. A script that placed a
sense track's first point from `placed_size()` coordinates, half a track
off a pad's inner edge, can name the edge instead, and give the lane that
follows as `Past([pad], Edge.EAST, across=tap)`.

## To 0.63.1

A keepout's drawn label is its name and its height limit, never a list
of parts or nets: the rule area and its `.kicad_dru` rule say what it
admits. A label listing every admitted part made KiCad slow to click. A
board that set `write.keepout_drawings = "none"` to avoid the long labels
can drop that line.

Under `[place] envelope = "physical"`, a part whose fab layer holds one
closed shape (a circle, a polygon, a rectangle) claims that shape, stroke
included, as its body; several graphics (four lines round a body) still
claim the box round them. A round or chamfered body no longer claims its
square, so placements under that envelope can move.

A label on an item that found no place is a `label` finding ("not drawn:
U8 found no place"), and the run goes on. It stopped the run, even under
`--keep-going`.

## To 0.63.0

Under `[place] envelope = "physical"`, a footprint that draws neither silk
nor fab claims its courtyard as the part itself: another part's body or
pads standing in it is now refused. It kept only other courtyards out,
which that envelope never claims, so such a courtyard blocked nothing.

`Centre(x, None, toward=Edge.SOUTH)` puts an item on a line as far toward
that end as it is legal, instead of across from what it connects to. A cell
is judged member by member, so a height band stops its tall members while
its low ones may cross into it; the step names what stopped it. A cell
placed by offsets worked out from its members' own frame, so that its
tall members stop at a band's edge, can be said this way.

The skill now asks the user before any coordinate escape hatch, and its
"An existing script" section migrates each gap-commented coordinate to the
form that now says it.

## To 0.62.0

A cell's members are read in reference order. KiCad returns a group's
items in no fixed order, so the refusal tallies and a `split` finding's
member lists could differ between two runs of the same board.

A scan searches a placed via's clear moves once, not once per candidate
(`place.via_clear_cache`): the same placements, faster where vias give
way.

A `board.push` between two footprints, where the capture could say what the
source emits and what the other tolerates, is now said on the parts instead:
`Pm.Emits` (`magnetic:3.2mT@13.5mm^3 heat:15C@5mm^1`) and `Pm.EmitsAt` on the
source, `Pm.Limit` (`magnetic:0.5mT heat:5C`) and `Pm.SensesAt` on the part
that is sensitive to it (`references/capture.md`). Every pair of a kind acts
as a push, judged by whichever part is placed second, so no order dependency
is added; a source that is a footprint moves its push with it. `board.push`
stays for a source no footprint carries, and adds to annotated pushes on the
same item. `placemat check` gains an `exposure` check.

A board whose parts carry none of the four keys places as before.

## To 0.61.0

A keepout that admits something (`allow=` or `max_height=`) is now also
drawn on the board: its outline and a label naming what it admits, on the
Fab layer of its face or `User.Comments`, in its own group `keepout
drawings`. `write.keepout_drawings = "none"` turns it off; `"all"` draws
every keepout, admitting or not.

A keepout that admits parts (`allow=` parts or cells, or `max_height=`) is
written as a KiCad rule area that allows footprints, with a `.kicad_dru`
rule forbidding the parts it does not admit. Parts it admits are no longer
KiCad DRC errors when placed by hand; a part it would refuse still is.

`board.push(item, from_=, falloff=, reference=(r_ref, v_ref), limit=)`
holds an item back from a source by a physical falloff model: illegal
inside a disc round the source, priced by how close it stands within
that. Where a script used `Near` on a hand-picked far point for a
requirement the netlist cannot say, and the real requirement is a
distance a field or a temperature falls off over, `push` replaces the
hand-picked point with the physics.

## To 0.60.0

`board.outward_rotation(item, edge, face=Face.BACK)` answers for an item on
the back. A flip mirrors the item before it turns, so the front's answer
turned a cell's declared east or west side the wrong way. An edge, a run,
a rim and a block now turn a back-face cell from its mirrored side on
their own. A script that negated the turn for the back by hand passes
`face=` instead.

**A cell of several jobs.** `placemat run` now reports a `split` finding
for a cell whose members form two or more groups
(`place.split_min_group`, default 2) joined only by nets that are not
local to it - a board-level net, or any `board.plane()` net whatever its
pads - and names the parts no net inside the cell joins to another, to be
judged each by what places it: a bypass capacitor stays with the IC it
serves, a sensing part at what it senses. It carries no run-score weight.

A net class makes pairs only when it sets its own `diff_pair_width` and
`diff_pair_gap`. In 0.58 every class but Default did, because KiCad reports
its default pair figures on every class: a two-net class of control lines
at their own width was paired and routed coupled.

`placemat facts` reads a `via` section naming every type `"no"` as decided
(through vias only), where 0.58 read it as missing. A section that leaves a
type out stays unconfirmed, and the reason names the types.

## To 0.59.1

`placemat facts` reads the board as generated, as `run` does. It failed on
a board run before whose script names a keepout, reading the last run's
written layout and its rule areas.

## To 0.59.0

Faster, with the same results:
- `check current-path` measures a zone fill's width from rasters in the
  native module. It is about six times faster on a whole six-layer board.
- The search's own bookkeeping round the native sweep is lighter.
- A carried via's move is searched natively.

No verdict, placement or refusal sentence changes. Nothing to do in a
script.

## To 0.58.0

Board facts come from the board, not placemat.toml. Three keys are
retired: `[check] copper_oz`, `[route] layers`, `[route] diff_pairs`. A
placemat.toml still setting one is refused, naming its replacement.

**The stackup.** Give the board's `BoardConfig` a `stackup`, with a
`CopperLayer` for each copper layer, top to bottom, and a `DielectricLayer`
between each pair:

```python
load("@stdlib/board_config.zen", "BoardConfig", "CopperLayer", "DielectricLayer",
     "Material", "Stackup")

STACKUP = Stackup(
    thickness = <board mm>,
    materials = [<the fab's prepreg and core, as Material(...)>],
    layers = [
        CopperLayer(thickness = <mm>, role = "<signal|mixed|power|ground>"),   # F.Cu
        DielectricLayer(thickness = <mm>, material = "<name>", form = "<prepreg|core>"),
        # ... each inner copper layer, with a dielectric after it ...
        CopperLayer(thickness = <mm>, role = "<signal|mixed|power|ground>"),   # B.Cu
    ],
)
CONFIG = BoardConfig(stackup = STACKUP, design_rules = ...)
```

A layer's role is what it carries: `signal` tracks, `ground` or `power` a
plane, `mixed` both. The route step now routes on `signal` and `mixed`
layers (was: every layer minus one a plane happened to fill whole);
inner-layer current paths are now judged by the inner IPC-2221 constant
and the layer's own weight (was: every layer as outer copper of `[check]
copper_oz`). A board's route and current-path verdicts can change on this
release.

**Pair classes.** A differential pair class takes `nets = ["<NET>_P",
"<NET>_N"]` (names or KiCad wildcard patterns), with its `diff_pair_width`
and `diff_pair_gap`. A class of exactly two nets pairs them whatever they
are called; more than two pair by the router's own suffix convention
within the class. The Default class never makes pairs. Pairs now come
from net classes (was: `[route] diff_pairs`, default every net named like
a pair).

**fab-profile.json.** `via`'s types take `"yes"`, `"no"` or `"if-needed"`
(the 0.57 `allow_*` booleans still read: `true` -> `"yes"`, `false` or
absent -> `"no"`). An `"if-needed"` type is never drawn for a script's own
`layers=`; give way's new "shorten" way may still use it, judged but never
applied, and an item it would have placed is a `needs` finding. A `min` section (`track_mm`, `clearance_mm`, `drill_mm`,
`annular_mm`, `via_size_mm`) is checked against the board's net classes at
the start of every run.

**`placemat facts`.** Run it, then `placemat facts --confirm` once the
printed facts are right. A run whose facts do not match the last
confirmation says so on its own line and records a finding, but still
runs.

## To 0.57.2

A keepout that excludes parts only no longer judges a cell's own tracks
and pours: a cell whose members are let in or stand outside it, with its
own copper inside, is placed where it was refused.

## To 0.57.1

A carried via shares only another item's via, and a via another shares
no longer gives way itself: in 0.57.0 a cell's vias could share one
another in a chain until none was left where the tails ended. A spot where
a later item meets a shared via is refused, naming the via that shares it.

The write no longer fails with "'SwigPyObject' object has no attribute
'Cast'" (or "... no attribute 'x'") where a cell's vias gave way.

## To 0.57.0

A cell flipped to the other face keeps its own inner copper on the layer
it was drawn on: F and B swap, In1..In4 stay, where 0.56.2 mirrored them
through the stack as KiCad does. The writer puts them back after KiCad's
flip. A via that reaches a face still mirrors (F-In1 becomes B-In4), and the
cell's step says when its inner end may no longer join its net. A
footprint's own copper mirrors as before. A script that kept a cell on its
own face to hold its inner layers' roles may flip it.

A micro, blind or buried via (`layers=` on a via) is refused unless
`fab-profile.json` allows its type (`"via": {"allow_micro": true}` and
so on); a stamped fragment carrying one fails the run the same way.

`placemat measure --models` says when a part's 3D model sits off its pads
or looks turned 90 against its fab outline.

`placemat parts --fragments` names the fragment each part was stamped from.

`board.place(Cell(...), at=Pin(Part(member), x, y))` puts a member's
footprint origin on the point: a cell placed by a point that is no pad (a
winding's arc centre on a disc's centre), not by an offset worked out in
its own frame.

`check current-path` no longer judges a net only one part carries: it
judged the route to the widest-joined other pad at the full current, often
a capacitor carrying ripple, and failed it. Give the part that takes the
load its own `Pm.I` and the route between the two is judged.

`Past(items, Corner.NE)` is a waypoint for a 45 held the clearance off a
corner of the items' copper box, and `(own_pad, Past(pads, Corner.NE,
lane=Net(...)))` in `Beside`'s align stands a pad off that 45. A waypoint
on a 45 worked out by hand - a constant x - y (or x + y) from the pad's
corner plus the clearance and half the width times root 2 - can be said
this way; the drawn 45 lies on the same line.

`check current-path` measures a zone fill's width along the load's route,
at `check.zone_step` (default 0.05 mm): two carriers only a fill joins are
judged, where they read "not judged", and a route through a fill names the
fill's narrowest point when that is its neck. A verdict can newly fail on
a fill lane that is narrower than the current needs.

A linked item never waits for a partner of a lower `priority=` tier: a
`HIGH` item linked to a `DEFAULT` one goes down with the `HIGH` tier, where
it waited for its partner and its step said its priority was set aside for
the link. Between items of one tier the wait is unchanged. Placements where
such a link crossed tiers can move.

A carried via - one at a searched part's pad, or a stamped cell's own - that
meets another net's copper no longer refuses the spot outright: it shares a
same-net via within `place.via_share`, moves up to `place.via_move`, or, a
plane drop, is dropped while its pad keeps `place.drops_keep` of its drops
(api.md, "Carried vias give way"). The search prices each at
`score.via_share`, `score.via_move` and `score.via_drop`. A via already
placed gives way to a later item on the other face the same way. A cell
that found no spot on a face under another's vias may now place; what gave
way is a `vias` finding and a note on the owner's step. `place.via_share =
0`, `place.via_move = 0` and `place.drops_keep = 1` turn each off.

## To 0.56.2

`layers=(CopperLayer.B, CopperLayer.IN4)` on `board.via()`, `board.vias()`
and `board.stitch()`: a via of that span only, judged on its layers alone
and written as KiCad's micro via (one layer from an outer face, drill
`copper.microvia_drill`) or a blind or buried one. Without `layers=` a via
is a through via, as before.

A cell flipped to the other face is judged with its inner-layer copper
mirrored through the stack, In1 with the last inner layer, which is where
KiCad's flip writes it: a track on In1 of a six-layer cell placed on the
back is judged on In4. It was judged on In1. Copper on every layer (a
through via, a plated pad) is unchanged.

`board.place(Cell(...), drops=Drops.HALF)` or `Drops.MIN` thins the
cell's via fields where it is placed: the vias of a `plane()` net inside
one of its members' pads. HALF keeps a checkerboard of each field; MIN
keeps `place.drops_keep` of it (0.5, rounded up, at least one). The
default, `Drops.ALL`, keeps them as stamped, and a script that does not
say `drops=` digests as before.

A copper finding measures a via as the circle it is, as KiCad's DRC does:
a via just over the clearance from a track read as just under it ("0.16 mm
... needs 0.16") from its polygon, a few microns outside the circle. The
placement search still judges the polygon.

A refusal's copper count names whose copper it met and its net ("copper
x363: cell logic's U3 GND front face x120, via GND ..."); a copper finding
names only the layers the board has.

An item `OnEdge(run, overhang=)` on a stretch of a shaped board's edge
overhangs it by exactly `overhang`, as on a named edge; it stood with its
centre on the edge whatever the overhang.

## To 0.56.1

A cutout or keepout `OnEdge` an east or west edge is held back by half its
depth as turned along the edge, not half its length: a long slot there
stood off the edge by the difference, and now sits flush as on the north
and south edges.

`PadRef(part, n, land=Land.LARGEST)` or `land=2`: one land of a pin drawn
as several. A track or via that had to end at hand-typed coordinates on the
exposed land can name the land instead.

`board.keepout(Inside(Part(...), margin=), name, ...)`: the box inside a
part's pads, between its two pad columns or inside its pad ring, moving and
turning with the part. A region worked out by hand from pad coordinates can
be declared this way.

`route.diff_pairs` takes an entry `"NET_A/NET_B"` naming two nets as a
differential pair (P first), for nets without a `_P`/`_N`, `P`/`N` or
`+`/`-` suffix. The route step routes them under a suffix name in its copy
and names them back; placement weighs their crossings as a pair's. An
existing entry with one `/` that is not leading and has no glob character
now reads as a pair.

The skill no longer keeps a list of relations placemat cannot say. A session
looks for the form first - api.md's intent index, the relations, a
composition of forms, the newest sections here - and writes a relation up in
the board's `PLACEMAT_GAPS.md` only when that search finds none. api.md gains
a "Read the board" index from a question to the command that answers it.
`references/capture.md` no longer lists `Pm.Role` or `Pm.Creepage`: no check
reads them, and a capture that carries them is unaffected.

A firm placement (`Pin`, `Beside`, `row(of=)`, a point said in pads) whose
reference is a searched part or cell rides it, where it used to be refused
with "only FIXED and EDGE items may be referred to". The reference is
searched with its riders placed at each candidate, and they commit together;
each rider's step says `rides <key>`. A part fixed only so another could be
placed off its pads can be searched again. A rider keeps the rotation it
declares: `rotation=Turned(Part(...))` and a `.local()` offset turn it with
its reference. A relation to a second searched item, and a keepout or
cutout at a searched part's pad, are still refused.

## To 0.56.0

`Past(pads, Edge.X, lane=Net(...), width=)` in `Beside`'s align: the lane
as wide as the copper its current needs, so a part stands clear of a power
pour's width rather than a track's.

A `swallow_pads` pour whose corners are all pads (three or more) covers the
convex hull of the pads' copper, not the polygon through their centres,
which over pads in a row was as thin as its stroke and failed a
current-path check. `cover=Cover.BOX` takes the box round the pads' copper;
`cover=Cover.CENTRES` keeps the old shape. A power pour drawn by hand from
pad edges can be declared over its pads.

`placemat layer <board> <LAYER>` draws one copper layer by net and lists
tracks inside another net's zone outline.

`board.pair(p, n, [(padP, padN), (padP2, padN2)], layer=)` - the two pad
pairs alone - finds its own centreline; a centreline typed as coordinates
between two placed parts can go.

`placemat measure --keepouts [NAME ...] [--near MM]` reports each part's
physical and courtyard gap to each rule area near it.

Escape findings, and so the run score, are measured at `score.escape_depth`
(1.5 mm), not at the search's `place.escape_depth` (still 1.0 mm): a
shallower search depth no longer scores better by checking less. A best run
recorded by 0.55.0 or earlier may give way to the next run.

## To 0.55.0

A block satellite that slid along its anchor's pin row says so in its step:
how far off its pin's axis, and which of the anchor's pins its body now
stands in front of.

A `FreeSpot` via's tail runs at 0, 45 or 90 degrees - a 45 from the pad,
then straight - not as one leg at whatever angle the spot lay; a spot that
tail cannot reach is passed over for the next. A script that drew its own
track to a `FreeSpot` via with `tail=False` for that reason can drop it.

Copper planned in one batch is judged against the rest of that batch too,
not only against what was on the board before it: a track of one net run
through a via of another, both with nothing to wait on, is a finding now
(it was a DRC failure behind a clean report).

`board.row(items, Edge.X, of=Part(...))` takes `centre=PadRef(...)` and
`pitch=`: the row's middle on a pad's centre line (a pad of `of` or of any
firmly placed part), its items' centres `pitch` apart. Two parts at a
mechanical pitch centred on a driver's pin no longer need their positions
worked out from the pin by hand.

`board.plane(net, layers, over=[Part(...), Cell(...)], margin=)` bounds a
plane to the box round those items' drawn envelopes, where they were
placed, clipped to the frame. A plane outline built by hand from a group's
box, which left off a part placed by `Beside` outside that box, can go.

`placemat measure` prints each 3D model's file, offset, rotation and scale,
and `--envelope` names the item that sets each side of a part's drawn
envelope; `--json` adds `models`, `envelope_items` and a `fab` box.
`measure --copper [NET ...]` lists the track segments a board carries, what
each end lands on and any leg off 0/45/90.
`placemat parts` ends with the board's part, pad and solder-joint counts;
`placemat drc` names each item's part by instance path beside its refdes.

A cell nested in another cell's group (a module sheet's child) is written
where the plan puts it: placing the parent moved the child group with it,
after the child had been placed, off its spot with no finding. The parent
carries only its own parts and copper, as the plan already judged it; a
child that should travel with its parent is placed relative to it.

A net-tie footprint's own copper (a winding joined to its pads) no longer
reads as a conflict with a track or pad of one of its net-tie pads' nets
where the two meet inside that pad, as KiCad's DRC allows: a track ending on
a winding's terminal pad was reported 0.00 mm from the footprint's copper.

`Past(items, Edge.X)` takes vias (what `board.via()` or `board.vias()`
returns) and tracks (what `board.track()` returns) as well as pads, in any
mix, each held off by the clearance of its own net. `across=` puts the
point on a pad's or a via's centre line, or at an `Along` of the items'
side, in place of the middle. A track waypoint computed by hand from a
via's centre, its size and the clearance - a track's U-turn under a row of
vias - is `Past([vias], Edge.SOUTH)`.

`board.via(net, at=Past(items, Edge.X, across=PadRef(...)))` stands a via
its radius plus its clearance off the items' side, on the pad's axis. A via
placed at a pad tip's coordinate plus the clearance plus half the via's
size, computed by hand, can be said this way.

`Beside(item, Edge.X, align=(own_pad, Past(pads, Edge.Y, lane=Net(...))))`
stands a part's pad a lane past other pads - the clearance to the lane's
net, its track width, and the clearance to the pad - while `Beside` decides
the other axis. Without `lane=` the pad stands the clearance off. A part
placed with its pad offset by hand from another part's pad by half pad
widths and a lane can be said this way. The Past takes pads only: a
placement is decided before copper is planned.

## To 0.54.1

Two `swallow_pads` pours of different nets now keep the netclass clearance
from each other as written, not only from each other's declared outline:
two pours over the two ends of a small part no longer meet. They settle as
KiCad's zone priority does: the pour the plan draws first (the one declared
first, when both wait on the same placements) keeps its fill and the later one pulls back
from it, so pours over neighbouring fine-pitch pins each keep a piece over
their own pin. A script that dropped one of two neighbouring pours, or swapped it
for a plain pour and a track, can declare both again.

A swallowed or named pad counts as joined when the pour's copper (its fill
and half its stroke) overlaps the pad, not only when the fill covers the
pad's centre: a pull-back that cut a pour short of a pad's centre reported
"joined to nothing" for a pad KiCad's connectivity saw joined.

`board.vias(net, along=PadRef(...), count=N)` now draws a tail at the net's
width from the pad to the farthest via: a via standing just clear of the
pad's tip was unconnected. A track may end on the value it returns (the
farthest via); a hand-drawn track joining the row to its pad can go.

`Beside(item, Edge.X, align=PadRef(...))` takes any firmly placed part's
pad, not only `item`'s: a part beside one part, level with another part's
pin, no longer needs its position from that pin by hand.

A keepout shaped by a part (`board.keepout(Part(...), name)`) now covers the
part's own copper graphics too, not only its pads, mask, silk and body: a
fill it excludes stays off a winding drawn as copper past the pads.

## To 0.54.0

The capture material - the `Pm.*` annotations, how wrappers forward them,
what `placemat check` reads - is `references/capture.md`, signposted at the
top of SKILL.md.

Nothing to change in a script that works. New intent forms replace the
coordinates the scripts audit found (see SKILL.md's "Declare by intent" and
the intent index): `at=Beside(item, Edge.X, align=...)` for a part beside
another part, a cell or a keepout at the envelope's own gap;
`board.row(items, Edge.X, of=Part(...))` for a row along a part's side
(also in a fit frame); `Pin` with a cell's member pad; `board.keepout(item,
name, margin=)` for a region shaped by a part's or a cell's drawn envelope,
moving and turning with it; `board.size(fit=Axis.X, height=...)` (or
`Axis.Y`) for a frame fitted in one axis. For copper: `Between(pad, pad)`
and `Past([pads], Edge.X)` as track waypoints (a lane through the gap
between two pads, or held off their side); `board.track(..., bend=Bend.START
| Bend.END | Bend.BOTH)` for the end of a leg that takes its 45;
`board.pour(net, [pad, pad], swallow_pads=True)` for a neck between two
pads; `board.finger(..., width=PadRef(...))` as wide as a pad;
`board.vias(net, along=PadRef(...), count=N)` for a row of vias out from a
pad; `board.stitch(net, region)`. A helper that computed any of these from
pad boxes or envelopes can go.

A pour grown over pads (`swallow_pads=True`) now pulls back from every other
net's copper on its layer to the netclass clearance, as a zone fill does,
and keeps only the pieces touching its pads: one that came within clearance
of a pad beside the pads it covers is clean now. The pull-back now also
reaches a pad with no net, or on a net this board's geometry does not know
(the board's own default clearance for either), reads each pad's real
shape rather than its bounding box, and reaches copper already on the
board before this run (a stamped cell's own tracks, vias and pours), not
only what this run itself plans; a piece the pull-back splits off keeps
every one now, not just the first, once the board is saved and reloaded.
Only a same-net pad among a pour's declared
points is one of its own pads - a corner given as another net's pad shapes
the outline near it and is never swallowed or checked as joined. The plan
report does not check a `swallow_pads` pour's clearance to other nets
either (placemat has no polygon subtract to compute the write-time
pull-back at plan time, so a finding there would be wrong once the pour is
written); the pour still occupies the board at its declared shape, so it
remains an obstacle for copper planned after it.

`board.stitch(net, region, pitch=None, size=None, drill=None, edge=False)`
now refuses at declaration, rather than planning nothing and saying no via
fit: a keepout region whose `excludes` forbids vias (the default) and does
not `allow` the stitching net; a pour region of a different net.
`edge=True` rows the vias along the region's own outline instead of
filling its inside.

`Between`/`Past` no longer raise a `KeyError` naming an empty net when the
gap or the side they measure sits next to a pad with no net; they fall
back to the board's default clearance for it, as the occupancy's own
conflict check already did.

A keepout or cutout with `rotation=Turned(part, degrees)` now turns the
way its part does: an asymmetric one turned the opposite way at 90 and 270
(a symmetric one, a slot or a circle, is unchanged). `degrees` turns the
same way a part's own rotation does - anticlockwise on screen - not as a
bare bearing would; the region's stored rotation is still its own bearing,
clockwise from the top, so a quarter turn with the part (`degrees=0`)
reads 270.

## To 0.53.0

Read `SKILL.md`'s "Declare by intent" section first: a script says where a
part goes relative to what, and placemat computes the numbers. The check
line now counts `X()`/`Y()` with offsets, `.local(`/`.offset(` and
measurements read into numbers; each is a place to use an intent form (the
index at the top of api.md) or, where none fits, a gap to record.

Documented forms that were broken now work: a block placed on an edge, a
run, a rim or a bore, or with one axis given, lands there (it was centred);
`OnEdge(..., along=<reference>)` on a board's or a cutout's edge; a cutout
or keepout `at=Near(...)`; `Polar(about=)` and `ring(about=)` a part or a
pad; a keepout or cutout `rotation=Turned(...)`, one at fixed numbers
included. `row(align=)` and `label(align=)` take `Along` (the strings still
work, and `row(align="centre")`/`"end"` now do what they say: they acted as
"start"). `row(align=..., centre=/end=/start=<reference>)` now refuses,
whatever align's spelling: the two say different things about where the row
starts, and only `"center"` with one of them was refused before. `row(line=)`
takes `Line`; `keepout(excludes=)` takes `Forbid`;
`place(face=)` refuses anything but a `Face` or its name. A finger's copper
is exactly `width` wide (it was 0.2 mm wider): a script that narrowed its
width to make up for it can use the width it means.

A keepout's `allow=Net(...)` lets that net's copper through and no longer
admits the parts that carry it, as the docs always said: a part that stood
in a keepout only because it carried an allowed net is refused there now
(the finding names the keepout); name it with `Part(...)` or `Cell(...)`.

Each stamped cell's KiCad group is lifted out of its module sheet's group to
the top level on the written board (groups are one level), so moving a
sub-module by hand in pcbnew no longer drags its module; a module keeps its
own parts. `[write] split_groups = "split"` also takes the parts a script
places one by one out of their module's group; `"keep"` writes the groups as
generated. `board.group(name, parts)` writes a top-level group of the parts
named: a script that rewrote the board's groups with pcbnew afterwards can
declare them instead.

New reports: `placemat nets` (each net's pads, span, routed length, detour,
vias, layers); `placemat parts` warns for a placed part with no order number
(`[parts] order_fields`); `placemat occupancy --corridor A B --layer L
--width W` gives the clear paths on one layer between two pads, or the
blockers. The keep-out verdict names the copper it measured (a part's own
pins, which it does not judge, said after it when nearer), a current-path
verdict gives its neck's point and length, and a copper finding against a
declared track names its segment, and its chamfer when that is what came
within clearance.

## To 0.52.0

Nothing to change in a script. Every route is laid with the router's turn
cost at 20000 (`[route] turn_cost`; the router's own default is 1000) and
its smoothing on: routes come out with fewer than half the kinks and less
copper, closure no worse on the boards measured. Routes already kept stay as
they were laid; to lay them again, `placemat routes <script> --release-all`
then `placemat route <script> --adopt-all` (with `--partial` if wanted).
`[route] router_args` passes more of the router's own flags through.

A cell meets a keepout member by member: a member named in `allow=`, or
carrying a net it names, no longer admits the rest of its cell, and one tall
member no longer keeps the low ones out of a height band. A cell that stood
in a keepout because one member was named may be refused there now (the
finding names the member); name the others, or `Cell(...)`, to admit it.
The same goes for a fanout's band, which admits the parts it names: a cell
with one of them no longer enters it whole. A cell's own tracks have no
height, so a height band leaves them be.

## To 0.51.1

A keepout whose shape has no area (a computed rectangle whose two sides
came out equal) is refused where it is declared: it kept nothing out, and
KiCad reads its rule area as malformed. Fix the shape or drop the keepout.

## To 0.51.0

Nothing to change in a script. `placemat lock <script> --current --partial`
locks the items that stand and lists the rest, where `--current` alone
writes nothing unless every item stands.

A pour net with pads its pours do not reach (a rail's taps behind a cell)
can be routed for those: `[route] islands = ["VSENSE", "VRAIL=0.5"]` in
`placemat.toml`, or `placemat route --islands NET[=WIDTH]`. Hand-drawn
track legs kept only because 0.50 left such nets unrouted can go.

## To 0.50.0

Nothing to change in a script. Under the `physical` envelope a part's
courtyard keeps off another part's plated lead, both ways, as KiCad's DRC
judges it: a part that stood with its courtyard over a lead moves clear, and
a refusal names the pad (in every envelope). A stamped cell's zone whose pads
join otherwise than the board's plane is kept (it was merged, and its pads
lost their solid connection); one reaching nearer the board edge than the
plane's keep-in merges. `placemat route` leaves nets with a zone or a filled
pour to their pours, as `run --route` did, and keeps other nets' tracks
out of a partial inner-layer pour of those nets (the refill split it round
them); a board-wide fill need not be switched off for routing, the router
routes through it and the refill carves round the tracks. "No legal location" names the
parts whose silk, mask or body were in the way under a drawn envelope (a
round board's rim or a cutout is counted as the edge), and a link's wait
says when it set the item's `priority=` aside. A cell placed on the back
with a member read at 90 or 270 degrees records that member's turn as its
shapes stand: its airwire ends, a via declared at its pad, a part `turned=`
from it and a lock entry anchored on it followed the mirror image before; a
lock entry so anchored may land elsewhere; `placemat lock <script>
--current` writes it again. `placemat route` leaves a stamped cell's own zone net to the
router (only the board's own pours are left out, as `run --route` does).

## To 0.49.2

Nothing to change in a script. A later `route --adopt` keeps the entries of
a net that held on the board it routed (it replaced them all, and the new
islands resting on their copper dropped on the next run), and says which
it replaced. `check current-path` judges each pair of
parts carrying a net's current at the lesser of their two currents, through
zone fills as well as tracks and pours (a fill's own width is not measured:
a route through a fill alone is not judged), and does not judge carriers no
copper joins yet. A controller that senses a load's net should give that
net its own current in a per-net `Pm.I`, or leave it out: its sense pin is
then judged at what it draws. Verdicts that were a pin lead, a boot track or
a sense line become the load's own route.

## To 0.49.1

Nothing to change in a script. `placemat route` routes with the board's own
settings (`[route] layers` was ignored). A kept route whose end rests on a
zone of its net no longer drops on every run; entries kept by 0.49 with
such an end are replaced by the next `route --adopt`.

## To 0.49

Nothing to change in a script. A via declared at a searched part's pad
travels with the part through its search, so plane drops at pads
(`board.via(net, PadRef(...))`) no longer land over the other face's pads;
a part with such drops may land a little further from where it did. A
copper finding against a via says "via NET at (x, y)" rather than "pad".
A stroked pour reads as one piece of copper again (0.48 read its strokes
apart, and `check current-path` took a pour for a 0.3 mm strip). A cell's
lock entry no longer releases when its fragment is stamped again; entries
0.48 released are written again by `placemat lock <script> --current`.

`route --adopt ... --partial` keeps the closed parts of a net the route
left open (each island joining two pads, or a pad and a plane), so a plane
net the router never finishes keeps its drops and joins from pass to pass.

## To 0.48

Nothing to change in a script. A courtyard that is not a rectangle (a
slice of a disc, a part generated at a turn off the axes) is claimed as
KiCad draws it rather than as the box round it: parts that collided by
their boxes, or crossed a round board's keep-in by a box corner, may now
stand. A via's copper is judged as the whole circle, so a via planned a
hair inside a clearance (0.1575 against 0.16) moves off, and a stroked
copper polygon (a pour) is read with its stroke along every edge, which a
polygon that doubles back on itself had partly lost. `placemat lock
--current` works on a board a `--keep-going` run wrote.

## To 0.47

Nothing to change in a script. `placemat lock <script> --current` locks
every searched item where the board stands (a hand-written wrapper round
the lock API can go); `route --adopt` locks the items the kept nets join,
and adopts nothing when the placement it was given would not come back.
The lock and the routes file name parts by instance path: a refdes
renumbering no longer releases lock entries or drops kept routes once they
are written by 0.47 (`lock --current` rewrites a lock; routing again
rewrites the routes file). Files written by 0.43-0.46 still read, by
refdes. `placemat drc` names each failing violation
and where it is; `--json` lists every violation and open connection with
its items' positions. `measure --pads` prints a custom pad's outline.

## To 0.46

Nothing to change in a script. Routing keeps off footprint copper graphics
(a winding drawn on copper layers) and the routed copy keeps them on their
copper layers: a routed copy judged clean while its windings' outer copper
had been moved to silk is now judged with it.

## To 0.45

Nothing to change in a script. A written board's 3D model paths that did
not resolve from its own folder are re-anchored to where the file is, so a
module deeper in the tree renders with its bodies; a fixed-depth
`${KIPRJMOD}/../..` prefix no longer needs a per-depth copy.

## To 0.44

Nothing to change in a script. Placing keeps the board's hole-to-hole rule
between the drilled holes of different parts and cells whatever their nets
(two cells' ground vias could land closer than the rule), and copper keeps
the hole clearance from an unplated hole whichever of the two moved (a
block could lay a pad over its anchor's peg hole). A searched part or cell
that stood too close before now lands a little further off; a fixed one
that does is refused as any collision is, naming the two holes.

## To 0.43

Nothing to change in a script. A run that fails before it writes the board
(the generator, the script, a firm-placement collision) now leaves the
layout folder as the last run left it, not the unplaced generation; a
critical part left unplaced still writes the board as it stood.

A script can import modules from the folders above it, up to the nearest
`placemat.toml`, and a change to one is a new run. A `sys.path.insert(...)`
a script added to reach shared geometry above it can go.

Routed copper can be kept: `placemat route <script> --adopt NET ...` (or
`--adopt-all`) stores the router's copper on those nets in `<script
stem>.routes.json`, relative to their pads, and every run draws it while the
parts it joins stand as they did. A hand-written fold-back that turns a
routed board into `board.track()` / `board.via()` calls with board
coordinates can go: delete those calls, route, and adopt the nets instead.

## To 0.42

Nothing to change in a script. A parts keepout whose `allow=` names the
parts short enough for the room a case leaves over it can say
`max_height=` instead, once the capture gives each part `Pm.Height`.

`placemat run` no longer deletes files in the layout folder that it did
not write, and copies a board edited in KiCad since its last run to the
run's `kept/` before writing over it. A track's end is now round, as KiCad
draws it, so a clearance finding between a track's end and a pad corner
that KiCad did not report goes away.

## To 0.41

Nothing to change in a script. A grid of vias typed into a pad (offsets from
its centre at a pitch) can become `board.vias(net, PadRef(...), pitch=)`.
`board.pitch()` now measures between pins, a pin drawn as several lands
counting once, so on such a part it answers the row's pitch where it gave the
gap between two lands of one pin. `check current-path` judges the route the
load takes, so a power net that failed on a thin sense or bootstrap branch
can pass. FreeSpot and `--via-near` now keep off unplated holes, and a route
keeps the script's own copper (the router's `--keep-input-copper`).

## To 0.40

Nothing to change in a script. `placemat freeze` now writes an entry as
`Near(PadRef(...).local(dx, dy), radius=0)` with `rotation=Turned(Part(...),
r)`, in the anchor's own frame, and adds to its `why=` the explore run and
score it came from; a frozen item turns with its anchor. Entries frozen by
0.39 or earlier wrote `.offset(...)` in board directions and an absolute
rotation: they stay put only while the anchor keeps its rotation. To move
one to the new form, remove its frozen `at=` and `rotation=` (a `radius=0`
spot gives explore nothing to try), let the search place it with its links,
then `--explore ... --accept` and freeze it again. A lock accepted by 0.39
still holds.

Optional: a fragment that computes its frame from its parts - a helper
that adds up where each body lands when its pad sits at a point, then sizes
the frame and places the main part at the numbers - can use
`board.size(fit=True)`: place the main part at the origin and the rest from
its pads, and drop the arithmetic. Planes with no `outline=` follow the
fitted frame.

## To 0.39

Scripts that place by typed positions - `Location(...)` of numbers or of
named constants, `PadRef(...).offset(...)` copied from a query, `radius=0` -
move to intent as they are touched: a part with its links, searched, its
spot found by `--explore` and kept in the lock; a via by `FreeSpot`, joined
by its tail; a track ending on the via `board.via()` returns. A number from
outside the board (an enclosure or datasheet dimension) stays, as a named
constant citing its source. A position placemat cannot say any other way is
a placemat gap: keep the number with a `why=` naming the gap, and report
it. SKILL.md's check line counts them.

Every `FreeSpot` via now draws its tail to the pad; say `tail=False` for a
via that should stand alone. A via typed as
a pad offset copied from `occupancy --via-near` can become
`board.via(net, FreeSpot(near=PadRef(...)))`, and a track that ran on from it
can end on the via `board.via()` returns. The tail is judged as the drawn
track is, round ends included, and is no wider than its pad (a wide power
class necks down to it), so `--via-near` and a FreeSpot can answer a little
differently from 0.38 beside small pads.

Routing (`placemat route`, `run --route`) left to itself (no `--layers` and
no `route.layers`) no longer hands the router every copper layer: an inner
layer whose own outline a `board.plane()` zone covers at least
`route.plane_share` (0.9) of is left out, so a signal, or a differential
pair's reference side, stops running straight through a plane and getting
flagged against it in DRC. A stamped cell's own zone never counts toward
this, and F.Cu and B.Cu are never left out. The route step prints which
layers it left out and why, and `route.json`'s `plane_layers` names them
too. A board that wants the old behaviour back sets `route.layers` to the
board's full copper stack.

## To 0.38

Nothing to change in a script. A FIXED or EDGE block's satellites no longer
move in the cleanup pass, so a board with such a block can place them where
the block put them rather than where cleanup moved them; copper planned
against them now meets their pads. A board that turned `[cleanup] enabled`
off for this can turn it back on.

A searched item whose `Near` names another searched item's pad is now
placed after that item, block members included, whatever
their tiers: it used to be able to go first and search round the pad's
parked position off the board. A script that gave such items tiers or a
link to force the order can drop them.

Boards run from one directory now each compare with, and reuse, their own
last run: `.placemat/runs/latest-<board>.json` beside `latest.json`, which
still names the last run of any board.

## To 0.37

Nothing to change in a script; placements are the same as 0.36's. A board
that stamps a cell with its own copper zone, on a net and layer the board's
`board.plane()` covers, is written without that zone: the plane fills the
area, and the run prints a `zones` line per cell. Set
`copper.cell_zones_under_planes = "keep"` for 0.36's board.

## To 0.36

Nothing to change in a script. Placements with a differential pair (nets
named as KiCad pairs them, among those `route.diff_pairs` selects; name
only the real pairs there, e.g. `["DATA_*"]`, so a crystal's `XTAL_P`/`XTAL_N`
is not weighed as one) can change: a crossing between a pair's two
halves now costs `score.pair_crossing` (100 mm) instead of `score.crossing`,
so the search and cleanup uncross a pair by a swap or a turn where they
can, and each crossed pair left is a `pair_crossed` finding. Set
`score.pair_crossing` to the value of `score.crossing` for 0.35's weighting.

A net class whose clearance does not fit the pitch of pads its nets land on
(the lane out of a pad, past the next pad of another net, under the
clearance) is a new setup finding, naming the part and the clearance that
fits. It is the same on every run of a board.

## To 0.35

Nothing to change in a script; placements are the same as 0.34's, but for
the first point below.

- A cell is judged against keepouts and the board's edge by its members'
  bodies, not by the box round the whole cell, so a cell whose box crosses a
  keepout or the edge while its parts do not can now be placed there.
- Routing (`placemat route`, `run --route`) routes differential pairs as
  pairs: the router's pair router routes every pair named as KiCad pairs them
  (`_P`/`_N`, `P`/`N`, `+`/`-`) first, at the net class's diff pair width and
  gap, then the router routes the rest around them. Give a pair its class in
  the board's project (a pattern in `netclass_patterns` does), or set
  `route.diff_pair_gap` and `route.diff_pair_width`. A pair the pair router
  cannot route coupled is routed single-ended and listed in the report's
  `pairs`. `route.diff_pairs = []` in `placemat.toml` routes as 0.34 did.

## To 0.34

0.34.0 was tagged but never published (its release checks failed); 0.34.1 is
the release.

Nothing to change; placements are the same as 0.33's, but for the block
below. With the native module, the candidate search weighs whole sweeps
natively (legality, wire, crossings and escapes), so runs and explore are
several times faster. Rebuild the native module after upgrading.

- A block's satellite that has no legal spot on its pin's normal slides
  along the pin row, up to `place.block_gap_reach`, instead of failing the
  block: 0.33 left a block unplaced where two satellites wider than the
  pitch sat on neighbouring pins. Blocks that placed under 0.33 place the
  same.

## To 0.33

Nothing to change in a script. Placements move, and lock entries can
drift: accept again (`--explore ... --accept`) where the lock reports
entries drifted, and check the run's link findings.

- Runs are judged by the run score, one weighted number in millimetres (the
  `[score]` settings), in place of the fixed order placed, DRC, findings,
  airwire. A best recorded by 0.32 has no score and gives way to the next
  run. Explore variants and the bench are judged by it too. Each run prints
  a `score` line by term.
- The search weighs the ratsnest crossings a spot would add
  (`score.crossing`, 4 mm each) and keeps pads' escapes open
  (`score.escape_*`, `place.escape_depth`).
- A block's satellite sits on the normal of its pin's pad row; before, it
  sat on the ray from the anchor's centre through the pin, which near a
  corner put it in front of the next pins.
- The cleanup pass weighs crossings and escapes, may move a satellite off
  its pin's normal within its link's limit or `place.block_gap_reach`, and
  swaps any two neighbouring parts (`cleanup.swap_neighbours`,
  `cleanup.swap_radius`).
- New findings: escapes crossed at a pin row, closed toward what a pad
  joins, and walled off.
- New: `preview --no-tags`.

## To 0.32.2

Nothing to change. With `envelope = "physical"` or `"union"`, a reserved
label is silk to parts placed after it: their silk keeps the board's silk
clearance from the label's box, so a part packed against a label may move
by up to that clearance.

## To 0.32.1

Nothing to change. A lock written by 0.32.0 released every linked item on
the next run; accept again (`--explore ... --accept`) to rewrite it.

## To 0.32

Nothing to change. New: `--explore` on `run` and `preview`, the lock file
beside the script (`<script stem>.lock.json`, commit it with the script),
`placemat lock` and `placemat freeze`. A declaration's script line is
recorded; comments added above a declaration still replay.

## To 0.31

Nothing to change. placemat's version is its git tag now; an install from
a checkout needs the tags (`git fetch --tags`) to report it. The native module installs with placemat's `native`
extra (a Rust toolchain on the machine), and a native module built for
another placemat release is no longer used: rebuild it after upgrading.

## To 0.30

Nothing to change. An optional native module (`native/`, see its README)
makes placement 2.5-4.6x faster with identical results; placemat runs
without it, and `PLACEMAT_NATIVE=0` turns it off.

## To 0.29

- An item on a line (`Location(x, None)`, `Centre(None, y)`) with parts it
  connects to already placed now starts across from them rather than at an
  even share of the line; one with nothing placed to pull it is as before.
- `[place] courtyard_touch` defaults to 0 (was 0.02): each pair of parts may
  overlap by the margins read from KiCad's own courtyards instead, so
  placements pack as tightly as KiCad's DRC allows and no tighter. A part
  whose courtyard stroke is thin no longer produces a `courtyards_overlap`.
- A label stands at least the board's silk clearance off what it names,
  whatever `gap=` or `[label] gap` says; labels move out by that much.
- In the `physical` and `union` envelopes a row or ring gap below the widest
  gap the envelope enforces is raised to it; a script that set the netclass
  clearance as its row gap can drop it.
- A through-hole part no longer claims its whole courtyard on the far face:
  only its holes, and another part's courtyard may not sit over a lead. A
  chip with vias in its exposed pad claims only their copper on the far
  face. Parts can now sit on the back under through-hole parts.
- The first run after upgrading generates the board again: the cached
  generation has no record of its inputs yet. From then on a changed .zen,
  footprint, symbol or stamped fragment regenerates by itself; `--fresh`
  is only needed for something outside those (a toolchain update).
- A script may import a module beside it without touching `sys.path`; drop
  any `sys.path.insert` added for that. Such a module now counts in the run
  id, so the first run after upgrading has a new id.

## To 0.28

- A keepout (or a stamped cell's rule area) with `"parts"` and `layers=`
  naming one face keeps parts off that face only; before, it kept them off
  both. A script that relied on that should list both faces.
- A part in the netlist that no declaration places is now a finding.
- A part searched from its links or round a `Near()` hint, with neither
  `rotation=` nor `rotations=`, is now tried at all four rotations, so parts
  turn and a board re-runs to a different placement. A part whose turn
  matters says `rotation=`; `[place] rotations = "declared"` in
  `placemat.toml` keeps the old behaviour for the whole board. The
  pocket fallback follows the same rule.
- Two satellites aimed at the same anchor pad no longer both take the one
  spot on its axis: the second is refused, naming the first. Aim it at
  another pad carrying the net, or link it to the pad instead.
- Overlap tests catch outlines that coincide (the same courtyard twice, or
  one slid along a side), which some checks read as clear before.

## To 0.27

Nothing to change. `placemat preview` is new: the placement drawn in
seconds, without building the board (see the API reference). Pads no longer
take capacity in the congestion measure, so `metrics.rudy` reads lower where
large pads were; a part not yet placed no longer blocks a pocket, a planned
track or a cutout, which can let a board place parts it could not before.

## To 0.26

- The cleanup pass defaults to 2 passes at a 0.5 mm step (was 3 at 0.25): a
  board re-runs to a slightly different placement, about 1% more wire at the
  median, in about a third of the pass's time.
- A run replays the previous run up to the first changed step
  (`--no-reuse` to resolve everything); the board written is the same.
- Every run prints its most congested cell by RUDY (`congestion`,
  `metrics.rudy`). Nothing steers by it yet.
- Large boards resolve faster, placing the same.

## To 0.25

Searched parts may move after placement: a cleanup pass moves and swaps the
plain searched parts where that shortens their wire and declared links, so a
board re-runs to a different, shorter placement. Parts with a place of their
own, labelled parts and parts another declaration refers to stay where they
were. `[cleanup] enabled = false` gives the placement of 0.24.

## To 0.24

- A block satellite may name the anchor's pad by number - `(Part(...), 20)` -
  where a net would pick the first of several pads carrying it.
- The run id includes the fab profile's values, so every board's next run
  has a new id; the best-run gate goes by the parts, so it is unaffected.
- `measure` adds box edges, pad outlines and mask/paste layers, and flags a
  courtyard inside its own silk or equal to its body.

## To 0.23

Nothing changes in the default `[place] envelope = "courtyard"`, apart from a
new `footprints` line naming each footprint whose silk or pads pass its
courtyard (not a finding). `physical` and `union` are new; switching the mode
re-places every board. fab-profile.json may set
`courtyard.component_spacing_mm`.

## To 0.22

- A declaration with `layout = False` beside the board is no longer taken for
  a board, so a `.zen` with sub-circuits no longer needs the board declared
  first.
- `board.edge(facing, outermost=True)` takes the run lying furthest out that
  way when several face it; a script filtering `board.edges()` for that can
  use it.
- Of two linked items neither placed, the one with less pull toward what is
  placed now waits for the other, so a part is seeded on the one its link
  joins it to. A script whose linked items were each already pulled to placed
  parts is unchanged; a block made only to force that order can go back to
  links.

## To 0.21.1

Nothing to change. Placement is faster on large boards - a 220-part board's
resolve went from about 16 minutes to under 2 - and lands every part where
0.21 did. Two polygons whose bounding boxes only touch are never counted as
overlapping; before, a vertex lying exactly on the other's boundary could
make them so.

## To 0.21

A part or cell that was UNPLACED because its seeded scan found no legal spot
now takes the free pocket nearest what it connects to, and parts placed after
it can move. A board that placed every part is unchanged. `metrics.pocketed`
counts these, and the run prints them. A searched step's note gives its rank
once instead of twice.

The solve no longer crashes on a board that declares a keepout.

## To 0.20

Nothing changes unless you turn it on. `[solve] enabled = true` gives the
searched tier its starting points from a global solve of the whole netlist
instead of from the pads already placed. Off by default: on the board it was
measured on it did not beat the sequential seed on the best-run objective.

The API reference's account of the placement order was out of date: it still
described an item needing more than a quarter of the free board going first,
a rule the rank replaced in 0.6. It now says what the order is.

## To 0.19

Nothing to change. `placemat occupancy` is new: what copper is at a point or in
a box on each layer, and the nearest spot a via can stand and be reached near a
pad, with why every nearer spot failed. `FreeSpot` is new too: a via written as
`board.via(net, FreeSpot(near=PadRef(...)))` lands at the nearest legal spot
once its part is placed.

`polys_overlap` now finds one polygon inside another even when the first vertex
it tests lies on the other's edge. It could miss that case before; edges that
merely touch still do not count. A run that placed cleanly may, rarely, report
an overlap it used to miss - it is real.

## To 0.18

Nothing to change. Every route now checks the copper the router laid against
the keepouts on the board it was given, prints anything inside a region that
forbids it, and keeps it in `route.json` under `keepout_breaches`. The router
honours KiCad rule areas; this makes that a checked fact on every run, so a
region it ignored would be named instead of appearing as one more
`items_not_allowed` among the ones that are there by permission.

## To 0.17

**Keepout zone names gain a layer marker, and a module's keepout now holds on
the parent's inner layers.** A keepout on every copper layer is written
`keepout <name> [*.Cu]`, and one on layers its board lacks lists them. KiCad
saves a zone on the layers its board has, so a two-layer module could never
carry a keepout onto a four-layer parent's inner pours: one declared on every
layer arrived on F and B, and the parent's pours filled under it on the inner
layers.

To pick it up: re-run each module's placemat script so its keepouts carry the
marker, then regenerate and re-run the boards that stamp it. A parent that
restated a module's clearance by hand still works, and now duplicates a region
the module brings; the copy can come out.

A keepout on a layer its board does not have is now a finding rather than a
region that silently holds nothing.

## To 0.16

Nothing to change in a script. Two additions to every run, and a fix to 0.15:

**The design checks run on every board.** `placemat check` was the only way to
get hot-loop, switch-node, keep-out, crossing, current-path and heat verdicts;
`placemat run` now runs them on the board it wrote and prints a `checks` line.
`run.json` gains `verdicts`, and the metrics gain `checks_failed` and
`checks_unjudged`. A board with no `Pm.*` facts says so on that line. A failed
check does not change the exit code, as a DRC violation does not.

**A run made with `--no-drc` is not judged against the best.** 0.15.0 read its
missing airwire and violations as zeros, so such a run became the best
possible one and every measured run after it failed as a regression against
airwire 0. It now reads "not judged", and a `best.json` that already holds
such a run ignores it: the next measured run takes its place.

## To 0.15

**`placemat run` can now exit 1 on a board that placed.** Every finished run
is judged against the best earlier run of the same parts, and a run that comes
out worse is a finding naming the metric and a non-zero exit. A loop or a CI
job that treated exit 0 as "placed" should read the `best` line: exit 1 with
everything placed means worse than before, not broken.

Nothing in a script changes. The first run after upgrading is the first of its
family, so it becomes the best and passes. `best.json` sits beside
`latest.json` in `.placemat/runs/`; delete it to start the comparison afresh.

`[best] airwire_noise` (default 0.01) is how far airwire may move before it
counts. kicad-cli reports a different set of ratsnest edges each run for a
byte-identical board - four runs of the same inputs gave 2868.87 to 2873.11 mm
- so `airwire_mm` and `crossings` wobble slightly between
identical runs. Neither is exact; compare them across runs with that in mind.

## To 0.14

**A `board.link` on a plane net now pulls, so parts move.** It always measured
the distance and reported it against `limit_mm`; it just never contributed to
where the part went. A limit that is measured and reported reads as a
constraint in force and losing to something, not as one that never ran.

Planes stay excluded from seeding for everything nobody declared - a net with
two hundred pads gives a centroid that means nothing - but a declared link
names two specific pads, so that reason does not apply to it. A link is how
to say two parts belong together when the only net they share is a plane.

If a script worked around this with `at=Near(Part(<the other part>))`, the workaround
still wins - an explicit hint beats a seed - so nothing breaks, but the `Near`
is now redundant and can come out. Re-run and expect the parts that were
reported over their limits to have moved toward the pins they serve.

## To 0.13

Nothing to change. `placemat datasheet` gains `--read`, which lists the facts a
sheet could be made to yield with the page, position, channel and confidence
behind each, and `check`, which compares a `.kicad_mod` against values you
supply and says whether the sheet mentions them at all.

A page with almost no text of its own is now read off its render with
`tesseract` when that is installed. It is optional; `--no-ocr` turns it off.
OCR reads wrong as well as right - on one measured sheet it returns 4.95 for a
dimension the drawing gives as 4.55, at confidence 78 against 86 to 96 for its
correct neighbours - so a confidence travels with every sourced number and
`check` against a real footprint is what catches the rest.

placemat does not recover pad geometry from a drawing. On that same sheet the
pads are drawn as hatching: 276 of the land-pattern view's 453 paths are
two-point line segments, and the largest group of equal boxes on the page is
outlined text. Pad values are supplied, corroborated and compared, not parsed.

## To 0.12

Nothing to change. `placemat datasheet <pdf>` is new: it ranks the pages
against land pattern, package dimensions, layout rules and pin map, prints the
evidence behind each ranking, and `--show` renders the page you should look at.
It shells out to mupdf and poppler, which join kicad-cli as tools placemat
expects to find; `tesseract` is used when installed and skipped with a note
when not.

## To 0.11

**Re-run every board and expect it to move.** A footprint that draws no
courtyard now claims its physical extent - pads, silk and fab together -
where it used to claim exactly its pads. Nothing in a script changes, but the
layout a script produces does, and a script that placed cleanly on 0.10 can
report a collision on 0.11.

The old answer understated any part whose body overhangs its pads by the whole
of the overhang. On one measured board, 13 of 43 footprints draw no courtyard,
and the worst claimed 70 mm2 of the 334 mm2 they stand on: the body overhangs
the pads by about 9 mm on one side. Two things read that number, so two things
change:

- **The placement rank.** Searched items are ordered by courtyard area, so a
  large part with no courtyard used to rank as a small one and go down last,
  among the parts it should have been placed before. Expect a different order, and
  read the printed rank rather than reaching for `priority=`.
- **The collision check.** A part under such a body is now a finding rather
  than silence. Those findings are real: a part under another part's body
  does not assemble. Move the part; do not widen a clearance to silence it.

A collision on the first 0.11 run is therefore a defect the old envelope was
hiding, not a regression. `placemat measure <board> <part>` prints the
`courtyard` box a part now claims beside its `body` and `physical` boxes, which
is the quickest way to see what changed for one part.

## To 0.10

Nothing to change. Two commands are new and one has grown, and an agent that
does not know about them will keep grepping footprints by hand.

`placemat parts <board>` lists every part: instance, refdes, face, cell,
courtyard area, pin count, value.

`placemat measure <board> <part> --pads` prints its position, its `body`,
`courtyard` and `physical` boxes, how near it comes to the board edge, and
every pad's number, net, layers, drill, centre and **copper box**. The copper
box is the box round the pad's outlines: for a custom pad the anchor size is
not the copper, and reading the anchor is how a via ends up inside a pad.

`placemat measure <path>.kicad_mod` does the same for a footprint that is not
on a board, with its SHA-256.

Both take `--json`.

## To 0.9

Nothing to change in a script. Two behaviours are stricter and two reports say
more.

**`placemat drc` now refuses a board with no `.kicad_pro` beside it.** kicad-cli
substitutes its own design rules for a board without one, so the report
measured KiCad rather than the board: on a real four-layer board that is 1263
violations against a true 313, including 199 `track_width` items that do not
exist. If you review a board by copying it somewhere, copy the `.kicad_pro` and
any `.kicad_dru` with it.

**A rerun no longer destroys the previous run's route.** A run directory is
named by a hash of its inputs, so a rerun landing on the same id writes a
byte-identical board and the route taken on the old one is still a route of it.
It used to be deleted silently. A run that routes replaces it, as before.

**Footprint defects have their own bucket.** `lib_footprint_issues`,
`lib_footprint_mismatch`, `malformed_courtyard` and `padstack` now read as
`footprint issues N (extents for those parts are unreliable)` instead of going
into `other`. They do not block a board, but placemat's extent for an affected
part cannot be trusted. A reader of `run.json` will find them gone from
`other`; `[drc] footprint_kinds` sets the list.

**A cross-face courtyard finding says why.** `U9 courtyard overlaps R31
courtyard (U9 holds both faces: 4 through-hole pads, none with a net)`. A pad
with no net is usually a footprint defect rather than a real via field.

## To 0.8

**Back-face parts move. Cells do not.**

A flip to the back now mirrors about the vertical axis - KiCad's F key - for a
part and a cell alike, and `rotation=` is applied after it. Before, a lone part
mirrored top-to-bottom while a cell mirrored left-to-right, and the planner and
the writer disagreed about where a part's pads landed by `180 + 2r`, where `r`
is the rotation the generator left the part at.

**Drop any monkeypatch of `Occupancy._transform`.** It was masking the bug for
parts at generated rotation 0 and 180 and creating it for those at 90 and 270.
`grep -n "Occupancy._transform" <script>` finds it.

**A script that compensated by hand cannot be grepped for.** If a back-face
part carries `rotation=180` where the board wanted it upright, it will now be
upside down. Look for back-face parts whose rotation was chosen by trial rather
than from the mechanics, and read the render.

**KiCad's orientation field now reads `rotation + 180`** for a back-face part.
Nothing is wrong: that is what its own flip produces.

A board with no back-face parts is unaffected.

## To 0.7

Nothing to change in a script. Three things get stricter, and one report is new.

**A keepout's `layers=` is now honoured when copper is checked.** A board that
widened `allow=` to silence a complaint about copper on a layer the region does
not cover should take those nets back out: the `allow=` admits them on the
layers that DO matter. One downstream board's layout script is the known case.

**A region that hangs off the board edge now forbids.** It used to be discarded
whole, silently, so a script could read as though a rule were in force when it
was not. Expect new findings from a region that was never being applied - they
are the point. A region WHOLLY off the board is now an error, because it
forbids nothing while the script says otherwise.

**A stamped cell's rule areas are no longer deleted.** `pcb layout` copies a
module fragment's regions into the parent, inside the cell's group; placemat
used to delete every rule area on the board before writing its own. A parent
that stamps a module declaring a clearance will newly report parts and copper
inside it. On a board that filled a ground pour under an antenna, that is the
finding that was missing.

**New: the `seeded` line.** It says which nets pulled how many items into
place. One net seeding most of the board means a missing `board.plane()`.

## To 0.6

Read this only if the check in `SKILL.md` matched, or a script fails at import
with `AttributeError: type object 'Priority' has no attribute 'FIXED'`.

### What changed, in one paragraph

`Priority` used to carry four unrelated facts. It now carries one. Whether a
position is decided is `Freedom`, derived from the place you gave it and never
written by hand. Which searched item goes next is a **rank**, worked out from
the item's courtyard area and pin count. Whether failing to place something
stops the run is `required=`. `Priority` is left with `HIGH`, `DEFAULT` and
`LOW`, which a script sets and nothing else does.

### Find the script's legacy use

```sh
grep -nE "Priority\.(FIXED|EDGE)|priority=Priority\.HIGH|priority=Priority\.LOW" <script>
```

Each hit is one of the four cases below. A script with no hits needs no source
change, but read "What moves without you touching anything" at the end.

### 1. `Priority.FIXED` or `Priority.EDGE` on copper

```python
board.via(GND, Location(12.0, 30.0), priority=Priority.FIXED)
board.track(V48, [pad_a, pad_b], layer=F, priority=Priority.FIXED)
```

**Delete the argument.** When a piece of copper is planned is now derived from
its endpoints: copper whose every endpoint belongs to something nothing will
move - a decided part, a cell already down, or plain coordinates - is planned
before the search and becomes an obstacle to it. Copper naming a searched part
is planned after the search.

```python
board.via(GND, Location(12.0, 30.0))
board.track(V48, [pad_a, pad_b], layer=F)
```

The derivation gives the same answer wherever the endpoints were already
decided, which is every case that used to be legal: `priority=Priority.FIXED`
on copper naming a searched part was refused before, so no script has one.

If the intent was "this track wins at a crossing", that is still a priority and
still spelt the same way, but with a level that exists:
`priority=Priority.HIGH`.

### 2. `Priority.FIXED` or `Priority.EDGE` on a placement

```python
board.place(Part("j1"), at=Location(20, 20), priority=Priority.FIXED)
```

**Delete the argument.** This was already refused at declaration time ("the
declaration decided this position, so ... priority=fixed has nothing to
order"), so a working script cannot contain one. If you find one, the script
was never run.

### 3. `priority=Priority.HIGH` to get a big part down early

```python
board.place(Part("l_vbus"), priority=Priority.HIGH)   # a big inductor that kept getting stranded
```

**Delete the argument and run.** This is the workaround the rank exists to
remove. A large, sparsely connected part now goes down early on its own: the
rank scores courtyard area and pin count, so a 31 mm2 two-pin inductor outranks
a shelf of 0402s whatever their net fan-out.

Read the step line before deciding you still need the override:

```
power.l_in   part   rank 19/220   at (32.01, 18.37) rot 0 face back
```

Keep `priority=Priority.HIGH` only if the rank is demonstrably wrong for that
board, and write the reason beside it. It is now a tier **above** the rank,
not a replacement for it.

### 4. `priority=Priority.HIGH` to make a failure fatal

```python
board.place(Cell("mcu"), priority=Priority.HIGH)   # this MUST be placed
```

**Use `required=True`.**

```python
board.place(Cell("mcu"), required=True, why="the MCU has nowhere else it can go")
```

HIGH used to mean two things at once: go first, and stop the run if there is
nowhere to go. It now means only the first. `required=True` means only the
second, works on a decided placement as well as a searched one, and holds even
under `--keep-going`.

**placemat no longer decides on its own that a failure is fatal.** If a script
relied on the old auto-HIGH stopping a run, nothing stops it now: the item is
left off the board, reported as a finding, and the run carries on. Mark the
items that genuinely cannot be left off.

### What moves without you touching anything

**Every board re-places.** The rank replaces the tier, and link pull drops from
the primary sort key to a tie-break, so the order searched items go down in
changes on every board. Expect a large `impact` diff on the first run. Read the
DRC and crossing numbers, not the diff size.

**Copper at literal coordinates becomes an early obstacle.** A track or via
given plain coordinates is now planned before the search, so a searched part's
pads must clear it. This is the intended behaviour and the most likely source
of new findings on the first run. A part that can no longer find a spot is
telling you the copper was always in its way.

**Every run id changes**, because the tool version moved and the resolved
settings joined the hash. The first run after upgrading has nothing to compare
against; `placemat impact <old> <new>` across the boundary still works.

**A run record reader needs updating.** In `run.json`, a step's `priority` is
now `null` for a decided placement, because it has none:

| was | is |
|---|---|
| `steps[].priority == "fixed"` | `steps[].freedom == "fixed"` |
| `steps[].priority == "edge"` | `steps[].freedom == "edge"` |
| `steps[].priority == "high"` | `steps[].priority == "high"` (unchanged: a script said so) |
| nothing | `steps[].rank`, `steps[].rank_of` on a searched placement |
| nothing | `steps[].freedom` on a copper step: which batch planned it |

**A script that monkeypatched the placer.** `_weigh` and `_CRITICAL_SHARE` are
gone, replaced by `Board._rank` and `placemat.ranking`. A patch against either
name fails loudly rather than silently doing nothing.

### While you are here: placemat.toml

Nothing to migrate - a project with no `placemat.toml` behaves exactly as it
did. But the constants a script used to work around by editing placemat, or by
passing a flag every time, now have a home:

```toml
# electronics/placemat.toml
[place]
step = 0.1              # this board is laid out on a 0.1 grid

[check]
ambient_c = 85.0        # was --ambient 85 on every invocation

[drc]
real_kinds = ["clearance", "shorting_items", "hole_clearance"]
```

`placemat settings` prints every resolved value and the file it came from. The
full table is in `api.md`.

## Patterns in older scripts

What a script written for an earlier placemat may carry, and the section
that says what replaces it.

| found in the script | section |
|---|---|
| `priority=Priority.FIXED` or `EDGE`; `priority=Priority.HIGH` to go first or to make a failure fatal | To 0.6 |
| a monkeypatch of `Occupancy._transform` | To 0.8 |
| a `sys.path.insert` to import geometry beside the script | To 0.29, To 0.43 |
| a `Location` of typed numbers, a `.offset()` copied from a query, a via offset from `occupancy --via-near` | To 0.39 |
| a frozen `Near(PadRef(...).offset(...), radius=0)` with an absolute rotation | To 0.40 |
| a fragment frame or main-part position added up from its parts | To 0.40 |
| a grid of vias typed into a pad | To 0.41 |
| `board.track()`/`board.via()` calls with board coordinates folded back from a routed board | To 0.43 |
| a wrapper round the lock API to lock the current placement | To 0.47 |
| a helper computing a position from pad boxes or envelopes; `X()`/`Y()` with offsets | To 0.53.0, To 0.54.0 |
| a part's position worked out from a third part's pin | To 0.54.1 |
| a hand-drawn track from a via row to its pad | To 0.54.1 |
| a via or a waypoint at a pad tip plus the clearance plus half a via | To 0.55.0 |
| a pad offset from another part's pad by half pad widths and a lane | To 0.55.0 |
| a plane outline built from a group's box | To 0.55.0 |
| two parts' positions worked out from a driver's pin at a mechanical pitch | To 0.55.0 |
| `tail=False` on a `FreeSpot` via whose track the script draws itself | To 0.55.0 |
| a pair centreline typed as coordinates | To 0.56.0 |
| a power pour polygon built from pad edges | To 0.56.0 |
| a pour polygon bounded by neighbouring lanes, vias and parts | To 0.65.0 |
| a swallowing pour with `cover=` or corner points, relying on pull-back | To 0.67.0 |
| a waypoint on a 45 worked out as x - y or x + y off a pad's corner | To 0.57.0 |
| a cell stood as far toward an end as its tall members allow, by offsets worked out from its members' frame | To 0.63.0 |
| a sense track's first point placed from `placed_size()` half a track off a pad's edge | To 0.64.0 |
| a pad placed at `X(PadRef(...), PITCH)` to stand a mechanical pitch from another pad | To 0.67.0 |
| a `Beside` `gap=` worked out to put a pad a clearance off another part's pad | To 0.67.0 |
| ground vias outside a region typed as computed `Location` vias | To 0.68.0 |
| points of a datasheet figure typed as coordinates beside a `Path(anchor=)` keepout | To 0.68.0 |
| `board.plane(net, layers=(In2,), over=[parts])` standing in for an inner-layer area over vias | To 0.69.0 |
| a part placed at another part's origin through computed coordinates | To 0.69.0 |
| a part's pad midpoint aligned by arithmetic (half the pads' spacing in an `X()` or a `Beside` offset) | To 0.69.0 |
| a rotation constant for a part parallel to a line between pads | To 0.69.0 |
| a rotation constant checked by an `assert` on pad positions | To 0.69.0 |
| a pour with `grow=` reaching past its pads | To 0.70.0 |
| a computed `0 if ... else 180` turn or a `*_EAST` flag read back to pick a `Beside` side, a turn or a row order | To 0.72.0 |
| lane lines worked out as pin tips plus track, clearance and via steps | To 0.65.0 |
| parts placed at coordinates worked out from a lane or a via's position | To 0.65.0 |
| a searched cell or part pinned to `face=Face.BACK` (or `FRONT`) by hand only because one face was full | To 0.72.0 |
| a cell or part turned by a hand-picked constant (45 or similar) to follow a circle, at a typed point | To 0.76.0 |
| `board.size(...)`, the rectangular board form | To 0.85.0 |
| `board.arrangement(name, Alt(...), ...)` | To 0.99.17 |
