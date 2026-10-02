# Backlog

Open work, newest source first. Other projects' agents send placemat
requests by message; the placemat session files them here and owns this
file. An item cites its source as "a board's session, <date>".

## In progress

- **An emitter placed first leaves its limit partner no room** (a board's
  session, 2026-10-02): a `Pm.Emits` source searched before its `Pm.Limit`
  partner can take a spot that leaves the partner nothing at the limit
  distance; neither the search, the solve nor explore sees it. Being built.

## Open

- **Current shared between a load's pins** (a board's session, 2026-10-01):
  `current-path` judges a load by the widest route to any one of its pins at
  the full current. Where the routes to two pins have separate necks, the
  current splits between them and neither neck need carry it all; a pour has
  no per-route width to flow over the route graph. Wanted: a flow with a
  width per neck, only where the routes share no neck.

- **A per-pad keep floor for drops** (the same): `place.drops_keep` is
  global; a script cannot say one pad needs N vias.

- **A plug on another board against a receptacle here** (owner: spec later,
  2026-09-30; a board's session, 2026-09-27, twice): pad-to-pad nets
  across two board files and a turn. Needed: for a receptacle on one board
  and the plug it mates with on another (laid on its back face, turned 180
  degrees), which pad lands on which, and which nets differ; also which
  parts of the other board stand over the receptacle and how far they hang
  (needs part heights from a 3D model's box). Done instead: pcbnew
  `FootprintLoad` and `Flip` in a scratch board, the other board's
  `.kicad_pcb` read with `LoadBoard`, its STEP read with build123d. Forms
  tried: `placemat measure` reads a part on a board it has placed or a bare
  `.kicad_mod` in its own frame, not a part on another board turned onto
  this one. Could offer: a mating check taking two footprints, or a part on
  each of two board files, the faces they meet on and the turn between
  them, listing each pad pair and flagging any whose nets differ.

- **A board's interface to its enclosure, written on every run** (a board's
  session, 2026-09-19, 2026-09-20): the enclosure model needed mechanical
  anchors off each board (a connector mouth's centre against the outline,
  how far a receptacle stands off the board, the tallest part on each face,
  a sensor's and an antenna connector's positions). The only channel was a
  STEP export measured by a separate tool; it is gitignored and went stale
  silently, and a massing model ran 2.94 mm out for a day. A related miss:
  an `OnEdge` overhang worked out from a courtyard put a receptacle's mouth
  4.0 mm further out than the script's printed anchor for thirty rounds,
  and nothing compared the placed pad against the stated position. Could
  offer: a machine-readable file (TOML or JSON) written on each run, in
  board coordinates, with each part's origin, rotation, copper box,
  courtyard box, 3D model box and height; the outline's box and routed
  slots; and anchors the script declares (`anchor("name", part=, offset=)`),
  so a git diff shows a moved connector. An anchor check would compare a
  named pad's placed box with a stated position. `measure --pads` and
  `--copper` already give the placed numbers on request; the file and the
  check are what is missing.

- **Reports a datasheet review asked for** (a board's session, 2026-09-20,
  twice): checking a routed six-layer board against each part's datasheet
  needed numbers `placemat nets` and `occupancy` do not give. Done
  instead: pcbnew `LoadBoard` with per-layer copper built from
  `ConvertBrdLayerToPolygonalContours`, and a small graph over track ends,
  vias and pours. Could offer: per net, length by layer, a width histogram,
  via positions, the bottleneck width between two named pads, and the vias
  whose removal disconnects it (stubs of 42 to 60 mm of a thin track on
  three test-point nets were invisible in a run); an island report per
  pour and layer (pieces carrying no same-net pad or via, with area and
  box) and, per plane, the drops its fill does not reach once routed
  tracks cut it (four vias were found on cut-off islands); a distance
  report from a named decoupling or sense part's live pad to the pin it
  serves; and, for a round board, each part's courtyard minimum and maximum
  radius, the zone it lands in and its height against that zone's limit,
  the height read from a part property.

- **Small gaps in a large board's script** (a board's session, 2026-09-20):
  `board.both_faces` and `refs_on_fab` are read by `getattr` on the Board,
  but the `board` proxy a script imports has no `__setattr__`, so setting
  either sets it on the proxy (worked round through
  `placemat.context._active`), and neither is in api.md. A cell's whole box
  is held inside the outline, including a corner of the box that holds no
  member, so a cell whose box reaches over a notch its parts do not was
  moved by asking for a change elsewhere. A finger to a pad ends with a cap
  the pad's width, so a finger into a pad 0.08 mm from its neighbour
  reports a clearance the footprint already has; a track into the same pad
  does not. Could offer: a documented setting for both flags, a cell's
  extent from its members and copper rather than its box, and the finger's
  cap judged as the track's is.

- **An overhang on a fixed placement** (a board's session, 2026-09-21): a
  receptacle's mouth had to reach a board arm's tip, so its body stands
  about 2.3 mm past the edge. `overhang=` is documented on `OnEdge` and
  `OnRim` only, and the part's spot was a decided coordinate
  (`at=Location(...)`), so every run reports "body box ... is past the
  board's keep-in (0.40 mm)". Could offer: `overhang=` on `Location` and
  `Centre`, or a way to say a part's reach may leave the board here.

- **A ring shape** (a board's session, 2026-09-21): a seal band round a
  disc was a hand-traced `Path` of 360 points with a radial cut. Could
  offer: `Ring(inner, outer)` as a shape for a keepout or a cutout.

- **Naming what blocks a part, and a net with no plane** (a board's
  session, 2026-09-21; may be resolved in part by 0.50.0's "No legal
  location" naming drawn things; check with the requester): `no legal
  location` counted obstructions as `courtyard xN` without saying which face
  or which owners, so a via field of plated thermal vias on the other face
  read as something wrong. With no `board.plane()` declared for the two
  planes' nets, 155 of 220 parts reported no legal location, all seeded
  within a few millimetres of the board's centre, because every part
  sharing a net with that many pads is pulled to their centroid; declaring
  the planes took the findings from 165 to 71. Could offer: the top few
  blocking owners named in the finding, and a warning when a net with a
  large share of the board's pads has no plane.

- **Symbol-to-pad identity and electrical types** (a board's session,
  2026-09-21, twice; 2026-09-26): before writing a part's schematic wrapper,
  a session needed each manufacturer symbol pin's name, number and
  electrical type joined to the footprint's pad, with source hashes, and
  proof that a KiCad 10 symbol conversion kept the pin map. Done instead:
  downloaded symbol and footprint assets read by hand against the
  manufacturer's pin table, and a parsed inventory around `kicad-cli sym
  upgrade` (43 pairs agreed). A standalone footprint capture also showed
  nine unnumbered plated through-hole objects inside an exposed pad and
  incomplete courtyards, which nothing flagged. Could offer: a standalone
  part report joining symbol pin, pad number, electrical type, footprint
  identity and source hash; a warning for unnamed conductive through-hole
  objects inside an exposed pad.

- **Source-to-schematic equivalence and circuit assertions** (a board's
  session, 2026-09-21, 2026-09-26, 2026-09-27): placemat reports pads and
  nets on a generated board but compares nothing between the source circuit
  and the schematic, so a project carries its own audit comparing the
  evaluated netlist JSON with `kicad-cli sch export netlist` (139 net
  partitions and 568 pins at one point, 194 nets and 772 pins later), and
  tests that read the same JSON to assert isolation between nets. Could
  offer: a verification command for source/schematic equivalence, and a
  circuit-level connectivity query and assertion interface, so safety
  requirements (two nets isolated, an enable pin held) live with placemat.
  The rest of that session's schematic notes (ERC findings, no-connect
  markers, hierarchy label aliases, orphan labels after a part swap, a
  KiCad project's library tables) concern a schematic generator, not
  placemat.

- **Package-specific datasheet pages** (a board's session, 2026-09-26): for
  a converter in one of two package variants, `placemat datasheet` indexed
  the multi-package PDF and selected the page for the other variant, so the
  land drawing for the variant in use was found by rendering the vendor's
  current PDF by hand, and the pin table in the importer's PDF was
  incomplete. Could offer: page selection by package code, and a warning
  when the PDF the importer fetched lacks the drawing for the package named
  in the footprint.

- **Datasheet land, body and model comparison** (a board's session,
  2026-09-26, 2026-09-27): five imported footprints disagreed with the
  datasheet in ways `measure` showed only as a size: custom pads whose
  polygons carry a 0.1 mm stroke that enlarges each edge by 0.05 mm (two
  converter packages and a connector's four 0.6 x 1.3 mm lands drawn as
  polygons, where the stroke shrank clearances to 0.1501 mm), a coil whose
  lands were 2.15 x 3.32 mm at 5.82 mm pitch against 2.35 x 3.50 mm at
  6.05 mm and whose fab outline was 6.6 x 6.6 against a 7.0 x 6.6 body,
  and a capacitor whose STEP model measured 4.25 mm high with a negative
  minimum Z against a 3.0 mm maximum. Done instead: the `.kicad_mod`
  primitives read by hand, the model measured with build123d, adapted
  footprints written. Could offer: `measure --pads` printing a custom pad's
  stroke and its un-stroked bounds beside the copper outline (`--pads` now
  gives the copper outline, which may already answer part of this; check
  with the requester), `placemat datasheet check` accepting nominal and
  maximum body bounds and a custom pad's outline, and a model report with
  bounding box, seating plane and the datasheet's maximum height.

- **A cell's declared frame and a named edge datum** (a board's session,
  2026-09-26): `board.cell().box` is the union of parts and copper in the
  generated parent's coordinates, not the fragment's declared frame or its
  RF keepout's extent: an antenna fragment's frame is 9.885 x 6.45 mm while
  its stamped cell reports 8.360 x 2.935 mm. The parent derived the edge
  datum from a member's location relative to the cell's centre and the
  datasheet's pad inset, with a keepout depth typed as a number. Could
  offer: a cell's declared frame and a named edge datum in the public API.

- **Editing a library footprint** (a board's session, 2026-09-26,
  2026-09-27, four times): a silk circle or corner mark over its own part's
  pad (three LEDs, a coil, an inductor's SW pad, a protection part's mask
  openings) needed moving to the fab layer, and a QFN's land pattern needed
  correcting (exposed land 2.8 mm to 2.45 mm, perimeter lands 0.28 x 0.70
  mm to 0.24 x 0.60 mm, row centres 3.8 mm, four 1.08 mm paste apertures).
  Placemat has no library editor, so the source `.kicad_mod` was edited and
  the board regenerated through placemat. Could offer: a way to move a
  library graphic between layers by index or by overlap with a pad, and to
  edit lands and paste apertures, from the project rather than the source
  file.

- **Run history for fragments that share a directory** (a board's session,
  2026-09-26; may be resolved by 0.38.0's per-board last run; check with the
  requester): a first run of one fragment compared against another's
  because both stand in one directory and share `.placemat` history, so its
  impact was not a before/after. Could offer: best and history chosen per
  board.

- **Compare a run with a KiCad file** (a board's session, 2026-09-27, three
  times): a hand layout of a fragment was folded into its script by reading
  both boards' part positions with `placemat parts` and their copper
  (tracks, vias, zone outlines by net) with a pcbnew `LoadBoard` dump and
  `kicad-cli pcb export svg`, diffed as text or by eye. Nothing compares
  copper. Could offer: `placemat impact` between a run and a KiCad file:
  parts moved and turned, tracks, vias and zones changed, by net.

- **Searching a cell that has a cutout attached** (a board's session,
  2026-09-27): a protection fragment collides with fixed geometry in two
  faces, so its parent needs to search it, but a vent anchored to the cell
  is refused because cutout placement accepts only fixed or edge
  dependencies (the error names a part in the cell). A fixed-rotation
  diagnostic worsened the collisions. Could offer: a cutout placed from a
  searched cell or part, riding it as a firm placement does.

- **A position that is a sum of an x and a y** (a board's session,
  2026-09-29; may be resolved in part by `Past(..., Corner.X, lane=)` in a
  `Beside` align, 0.57.0; check with the requester): a comb of three
  resistors fed by parallel 45-degree tracks, each 45 a clearance off the
  next pad's corner, so each position is one reference's x plus another's
  y. `X(ref, dx)` and `Y(ref, dy)` take a number offset only, and
  `X(Part(...), dx)` is measured from the part's box centre, which on one
  controller is 0.1 mm from the footprint origin that `pad_from_origin`
  measures from; the comb landed 0.1 mm off until the numbers were
  anchored on a pad, and nothing in the run said the two frames differ.
  Done instead: numbers worked out from the controller's pads. Could offer:
  arithmetic on references (`X(a) + Y(b) - k`), or a `Diagonal(ref,
  clearance)` lane for 45-degree copper; and `X(Part)` documented as the
  box centre, or an `Origin(part)` reference.

- **A part's own centre level with another part's pad** (a board's session,
  2026-09-29): a SOT-23-5 regulator centred under a microcontroller's
  exposed pad. Its pads stand in two columns, so none lies on its centre
  line. `Beside(..., align=)` takes the placed part's pad, a pad pair, or an
  `Along` of the item's side; `Along.MID` of a chip lopsided by its pin-1
  mark stood the regulator 0.3 mm off the exposed pad, which closed the gap
  a ground pin reached the front ground through. Could offer:
  `align=(Along.MID, PadRef(...))`, the placed part's own centre level with
  a pad.

## Housekeeping (left for the owner: outside this repository)

- A downstream project's `pyproject.toml` points placemat at the stale
  `~/work/placemat-greenfield`; the `placemat-check` and
  `placemat-greenfield` worktrees are stale.

## Done

- **Either face with tangent turns** (0.77.0; a board's session,
  2026-10-02): `face=Face.EITHER` with `Tangent` scans each face with its
  own tangent turns, the back's derived for the mirrored item.

- **Tangent turns in a band of radii** (0.76.0; spec
  `2026-10-01-tangent-turns-design.md`): `rotations=Turns.TANGENT` turns a
  searched item to the tangent at its bearing about a centre (two turns a
  spot, binned by `place.tangent_bin`); `Polar((r_min, r_max), None,
  about=)` searches a band of radii, on a disc or an outline board.

- **board.vias() grids give way; stamped faces notes left out** (0.75.0;
  spec `2026-10-01-carried-via-grids-design.md`): a part's pad grid is
  carried with its part and gives way as a cell's field does (a signal-net
  grid with no room refuses the other item's spot, the user's choice); a
  stamped cell's faces note is read, then deleted from the written board.

- **Via fields re-laid, routed vias moved, Pm.KeepOut fixed** (0.74.0;
  specs `2026-10-01-via-field-relay-design.md`,
  `2026-10-01-routed-via-moves-design.md`): a cell's via field meeting
  another item is re-laid (vias moved, a row shifted, the pitch closed or
  uneven, rows removed) keeping its count where it can; a cell's via with
  two or more tracks moves with its tracks rebuilt; `Pm.KeepOut` exempts the
  part's own escapes, judges at its distance, and `conflict_gap` follows the
  largest rule; copper is never drawn through another net's copper.

- **Neck length, a part's keep-out, the ring cell, per-layer corners,
  facts per board, a row end's side** (0.73.0; spec
  `2026-10-01-neck-length-and-part-keep-out-design.md`): current-path credits
  a short neck by a cited conduction rule and prints its length;
  `Pm.KeepOut` on a part sets its keep-out limit and a planning clearance
  from its sensitive pads; a decided cell's copper corners allow for arc
  flattening, so an arc-sector cell at the keep-in places; the corner-45
  check judges only the track's own layer; `facts --confirm` writes the
  nearest placemat.toml, one digest per script; `SideOf(pad, along=True)`.

- **Pours to their current, Facing everywhere, either face, KiCad's edge
  rule, labels that never cost a place** (0.72.0; specs
  `2026-10-01-fitted-pour-reach-design.md`, `2026-10-01-pour-to-current-design.md`,
  `2026-10-01-facing-grids-rows-sides-design.md`, `2026-10-01-either-face-design.md`,
  `2026-10-01-labels-yield-to-searches-design.md`): `reach=Reach.CURRENT`
  widens a fitted pour to its net's current need (`reach=mm` an escape
  hatch); a pour holds the part of a pad outside a neighbour's clearance;
  `Facing` on grids and in rows, `SideOf`, `toward=`, `row(over=)`;
  `face=Face.EITHER` with `score.back_face`; copper to the keep-in,
  courtyard and body to the edge; searched items do not see labels, and a
  label stays on the board.

- **The net-tie stall, labels give way, an in-pad via leaves its pad**
  (0.71.0; specs `2026-10-01-labels-give-way-design.md`,
  `2026-10-01-in-pad-via-leaves-its-pad-design.md`): an item that owns or
  meets a net tie searches natively again (a run back from over an hour to
  minutes); a user label moves for a firm part, never the reverse; an
  in-pad via with no room inside leaves its pad on a tail; a refusal names
  the shorter via that would clear it; vias that could not give way are
  tallied.

- **Fitted only, a cell's turn searched, settings for literals** (0.70.0;
  spec `2026-10-01-cell-bearing-search-design.md`): `board.pour(grow=,
  within=)` refused, a pour is fitted; `rotations=` on a point place searches
  the turn (`Turns.ANY`, `place.bearing_step`); a fixed cell's arc-shaped
  member judged at the rim by its corners; thirteen literals made settings;
  project names taken out of docs, specs, plans and tests.

- **Fitted pours on vias, hole clearance, origins and turns, stitch row
  ends** (0.69.0; specs `2026-10-01-fitted-pour-on-vias-design.md`,
  `2026-10-01-origins-mids-and-turns-design.md`): a fitted pour takes vias
  as members; a plated hole keeps the hole clearance from other nets'
  copper; `Origin`, `at=Mid`, `Pin(Mid(...))`, `Parallel`, `Bearing`,
  `Facing`, `copper.straight_tolerance`; an outside stitch row is inset
  where it meets a side not kept, and the run names the board side each row
  landed on; the skill's rules for planes, joins, sense lines and cited
  datasheet decisions; requests go to the placemat agent, not a gaps file.

- **Vias, flips and lanes** (0.57.0): a carried via shares, moves or is
  dropped to clear a far-face part, and a placed item's vias give way to a
  later one (spec `2026-09-30-plane-drops-and-the-far-face-design.md`); a
  via's layer span, `drops=` on place(), and micro, blind and buried vias
  refused unless the fab profile allows them; a flipped cell keeps its
  inner copper on its layers; `Past(items, Corner.X)`; a zone fill's width
  in `check current-path`, which no longer judges a lone carrier; a link
  wait never outranks priority (spec
  `2026-09-30-diagonal-lane-zone-width-link-priority-design.md`); `Pin` on
  a member's origin; `measure --models`; `parts --fragments`.
- **A test board's 0.56.1 bugs** (0.56.2): an overhang on a shaped
  board's run; a run's point at its own end; a copper finding measuring a
  via as its circle; findings naming the board's own layers; a refusal's
  copper count naming whose copper and which net.
- **Riders, Inside, one land, explicit router pairs; the skill rewritten**
  (0.56.1; spec `2026-09-29-remaining-backlog-design.md`): a firm placement
  on a searched item rides its search; `keepout(Inside(Part))`;
  `PadRef(..., land=)`; `route.diff_pairs` "NET_A/NET_B"; a region on an
  east or west edge flush with it; SKILL.md without a gaps list.
- **Zone fills by net and tracks across a zone outline** (0.56.0;
  PLACEMAT_GAPS 2026-09-28, two entries): `placemat layer <board> <LAYER>`;
  the router has kept out of a left-out net's partial inner pour since
  0.50's pour guards. A routed copy's copper per net is `measure --copper`
  on it, and its layers `placemat layer`.
- **Lanes as intent** (0.55.0; a board's PLACEMAT_GAPS 2026-09-29; spec
  `2026-09-29-past-copper-and-row-pitch-design.md`): `Past` over vias and
  tracks with `across=`; a via at a `Past` point; `Beside` aligning a pad a
  lane past other pads; `row(of=, centre=PadRef, pitch=)`; `plane(over=)`.
  Also: copper in one batch judged against the rest of the batch; net-tie
  footprint copper per KiCad's exclusion; a nested cell written where the
  plan put it; `measure --copper`, `--envelope`, models; `parts` joint
  counts; `drc` instance paths.
- **Fixes from a board's 0.54 conversion** (0.54.1; a board's reports
  2026-09-29): swallow pours settle by draw order as KiCad's zone priority
  does; a pad is joined when the pour's copper overlaps it; `vias(along=)`
  joined to its pad by a tail and a track may end on it; `Beside` aligns to
  any firmly placed part's pad; a keepout shaped by a part covers its own
  copper graphics.
- **The intent relations** (0.54.0; audits 2026-09-29, spec
  `2026-09-29-missing-intent-relations-design.md`): Beside, a row along a
  part, Between/Past track waypoints, the 45 end of a leg, via rows and
  stitching, a cell placed by a member's pad, a keepout shaped by an item,
  one-axis fit, a two-pad pour, a finger as wide as a pad; a pour grown over
  pads pulls back from other nets' copper when written; Turned regions turn
  with their part; the placemat-design skill folded into
  `references/capture.md`.
- **Intent first** (0.53.0; the owner, 2026-09-29; audits
  `docs/audits/2026-09-29-*.md`): the skill leads with declaring by intent,
  api.md opens with an intent index, the check line counts computed offsets;
  the documented forms that were broken fixed; fixed-set arguments as enums.
- **Written groups one level; board.group** (0.53.0; PLACEMAT_GAPS
  2026-09-29 "groups a hand placement can move").
- **A keepout's allowed net admits no part** (0.53.0; the docs' rule).
- **placemat nets; parts without an order number; findings naming copper;
  corridors on one layer** (0.53.0; PLACEMAT_GAPS 2026-09-28/29).

- **Staircase routes** (0.52.0; PLACEMAT_GAPS 2026-09-29 "how jagged the kept
  routes are"; spec `2026-09-29-router-turn-cost-design.md`): the router's
  turn cost at 20000 on every pass (the whole test board: turns per 10 mm 12.6 -> 5.8,
  copper -10%, closure 66.0% -> 66.8%); its smoothing on; router_args;
  routes --release-all.
- **A cell against a keepout, member by member** (0.52.0; PLACEMAT_GAPS
  2026-09-29 "a cell whose tall member must stay out of a height band"; spec
  `2026-09-29-cell-members-in-reservations-design.md`).

- **Routing a pour net's taps the pours do not reach** (0.51.0; the
  a board's session, 2026-09-28; spec
  `2026-09-28-pour-net-islands-design.md`): `[route] islands`, routed first
  and alone. Breakout, a partial In2 pour over half of a net's pads: 3 pieces
  apart before, 0 after, its pour kept clear in the main pass.
- **`lock --current` all-or-nothing** (0.51.0; a board's
  session, 2026-09-28; spec `2026-09-28-lock-current-partial-design.md`):
  `--partial` locks what stands and lists the rest.

- **A plated lead against a neighbour's courtyard under the physical
  envelope** (0.50.0; PLACEMAT_GAPS 2026-09-26; spec
  `2026-09-28-lead-courtyard-drawn-design.md`): a drawn part's courtyard is
  kept as a yard, judged only against another part's plated lead, both ways.
- **A cell's solid ground pour under a thermal-relief plane; a cell's zone at
  the board edge** (0.50.0; PLACEMAT_GAPS 2026-09-28): a zone whose pads
  join otherwise than the plane's is kept; one reaching past the plane's
  keep-in merges by the part inside it.
- **placemat route routed a pour's net with thin tracks** (0.50.0; a
  board's report, 2026-09-28): it leaves nets with a zone or filled pour to
  their pours, as `run --route` does.
- **The router cut through an inner-layer pour** (0.50.0; a board's
  layout work, 2026-09-28; spec `2026-09-28-route-and-pours-design.md`): the
  input copy keeps other nets' tracks out of a partial inner-layer pour of an
  excluded net. Measured on the breakout: without the guard 6 other-net track
  ends inside a GND pour on In2, with it none.
- **"No legal location" named nothing under a drawn envelope; the link wait
  hid a priority set aside** (0.50.0; PLACEMAT_GAPS 2026-09-27 and
  2026-09-28).

- **A later route --adopt kept no earlier entry of a net it routed again**
  (0.49.2; PLACEMAT_GAPS 2026-09-28 "a second --adopt-all --partial pass
  drops kept routes"): the resolve that says which entries held did not draw
  the routes file, so none held and every one was replaced; the adopt line
  now names what it replaced.
- **Checked 2026-09-28 and closed:** a part seeded deep inside a parts
  keepout now takes the pocket nearest its seed; a re-laid cell's extent is
  read on every run (`board.extent`, `board.size(fit=True)`), so a room
  derived from it follows it.
- **check current-path between the parts that carry it** (0.49.2; a
  board's layout work, 2026-09-28; spec
  `2026-09-28-current-path-terminals-design.md`).
- **placemat route with the board's own settings; a kept end on a zone**
  (0.49.1; a board's layout work, 2026-09-28): `[route] layers` was ignored
  by the route command; a kept route ending on its net's zone dropped every
  run.
- **A cell's lock digest independent of member order; a stroked pour read
  as one piece** (0.49.0; a board's layout work, 2026-09-28).
- **Keeping the closed parts of an open net** (0.49.0; a board's layout
  work, 2026-09-28): `route --adopt ... --partial` (spec
  `2026-09-28-adopt-partial-design.md`).
- **A via at a pad goes with its part through the search** (0.49.0;
  PLACEMAT_GAPS 2026-09-27 "a plane drop through the board lands on the
  other face's pads"; spec `2026-09-27-pad-vias-in-search-design.md`).
- **Two drawn courtyards sharing only a vertex, and stroked polygons**
  (0.48.0; a board's layout work, 2026-09-27): polygons that share only
  a vertex do not overlap whichever way wound; a stroked copper polygon is
  read with its stroke on every edge; `lock --current` follows a run that
  kept going.
- **A courtyard that is not a rectangle, claimed as drawn** (0.48.0;
  PLACEMAT_GAPS 2026-09-27 "a turned part judged by its body's box against
  a round outline"; spec `2026-09-27-courtyard-polygons-design.md`).
- **A via's copper judged as its whole circle** (0.48.0; a board's
  layout work, 2026-09-27: a FreeSpot via 0.1575 mm from a pad against a
  0.16 rule).
- **Locking the placement a board stands in** (0.47.0; a board's
  layout work, 2026-09-27 "adopted routes move the placement they were
  routed on"): `placemat lock --current`, and `route --adopt` locks what it
  adopts (spec `2026-09-27-lock-current-design.md`).
- **The lock and adopted routes name parts by instance** (0.47.0; a
  board's layout work, 2026-09-27 "adopted routes are keyed by reference
  designator").
- **A custom pad's outline in `measure --pads`** (0.47.0; PLACEMAT_GAPS
  2026-09-27 "a custom pad's outline").
- **`placemat drc` lists each violation** (0.47.0; PLACEMAT_GAPS
  2026-09-27 "reading a routed board's layers and DRC items"): with its
  description, items and positions.
- **Footprint copper through the router** (0.46.0; PLACEMAT_GAPS
  2026-09-27 "the router moves a net-tie footprint's outer copper to silk"):
  rule areas keep the router off footprint copper graphics, and the routed
  copy gets them back before its DRC.
- **3D model paths that resolve from any project depth** (0.45.0; a
  board's layout work, 2026-09-27): the write re-anchors a model path that
  does not resolve to the nearest folder above that holds it
  (spec `2026-09-27-model-paths-design.md`).
- **Hole spacing when placing** (0.44.0; a board's layout work,
  2026-09-27): drilled holes of different owners keep hole_to_hole whatever
  their nets; copper keeps hole_clearance from an unplated hole; the via
  planner sees a stamped cell's vias (spec `2026-09-27-hole-spacing-design.md`).
- **Keeping routed copper** (0.43.0; PLACEMAT_GAPS 2026-09-27 "router
  output cannot be kept in the script"): `placemat route <script> --adopt
  NET ...` keeps the router's copper in `<script stem>.routes.json`,
  relative to its pads; runs draw it while its parts stand, and drop a net
  whose part moved. `placemat routes` lists and releases.
- **A script imports from the folders above it** (0.43.0; a board's
  layout work, 2026-09-27): up to the nearest placemat.toml, and those modules
  count in the run id.
- **A block that fits nowhere, found before the search** (0.43.0;
  PLACEMAT_GAPS 2026-09-26): a searched block is laid out alone at each of
  its rotations first.
- **A failed run leaves the last good board** (0.43.0; PLACEMAT_GAPS
  2026-09-26): a run that fails before writing the board puts the layout
  folder back as the last run left it.
- **A run keeps files it did not write; round track ends** (0.42.0; a
  board's layout work, 2026-09-27): the layout folder's other files and a
  hand-edited board survive a run; a track's end is round, so a clean
  board no longer reads 0.13 mm against a 0.16 rule.
- **A keepout by part height** (0.42.0; a board's layout work,
  2026-09-27): `Pm.Height` and `board.keepout(..., max_height=)`
  (spec `2026-09-27-part-height-design.md`).
- **`measure --labels` with text size, angle, mirroring and silk graphics**
  (0.42.0; PLACEMAT_GAPS 2026-09-27).
- **The 2026-09-27 evening gaps entries** (0.41.0): `placemat drc` takes a
  relative path; the routed copy is saved with its zones refilled; a
  footprint's copper graphics are copper to the placer; `placemat parts`
  lists each part's footprint and `--field NAME` columns; a part facing a
  curved edge gets a clean rotation.
- **Several vias in one pad** (0.41.0; PLACEMAT_GAPS 2026-09-27):
  `board.vias(net, PadRef(...), pitch=)` (spec `2026-09-27-pad-vias-design.md`).
- **A one-face parts keepout and a cell's vias** (0.41.0; a board's layout
  work, 2026-09-27): a cell's vias no longer make it two-faced to a parts
  keepout; plated leads and unplated holes still do.
- **`check current-path` judges the load's route** (0.41.0; PLACEMAT_GAPS
  2026-09-27; the owner chose dead-end branches skipped): the widest route between
  carrying parts, or from the one carrying part to another part.
- **A fragment's extent, and `measure --outline`** (0.41.0; PLACEMAT_GAPS
  2026-09-27): the run's extent line measures parts as the envelope claims
  them, so a physical-envelope fragment has one; `measure --outline` prints
  a board's Edge.Cuts items, box and thickness.
- **The 2026-09-27 afternoon gaps bugs and `board.parts()`** (0.41.0):
  FreeSpot and `--via-near` keep off unplated holes; the router runs with
  `--keep-input-copper` so declared copper survives its cleanup;
  `board.pair()` needs two centreline points and says so; a decided part
  turned near a round rim is judged by its corners; `board.parts(net=)`.
- **`board.envelope(item, rotation=)`** (0.41.0; a board's layout work,
  2026-09-27): what the placer keeps under `[place] envelope`, documented,
  so a hand-built row stops calling the internal `drawn_envelope`.
- **`pitch()` on split lands** (0.41.0; PLACEMAT_GAPS 2026-09-27): a
  pin drawn as several lands is one pin, and `pitch(part, pins=(a, b))`
  measures two named pins.
- **`reach()` smaller than the envelope** (PLACEMAT_GAPS 2026-09-27): not
  reproduced on 0.40 (0.88 mm, as the envelope); the board's layout work confirmed
  the reading came from before 0.39.
- **A frame sized to its content** (0.40.0; PLACEMAT_GAPS 2026-09-27):
  `board.size(fit=True, margin=)`, planes following the fitted frame
  (spec `2026-09-27-fit-frame-design.md`).
- **Freeze keeps intent** (0.40.0; spec
  `2026-09-27-freeze-intent-design.md`): freeze writes `PadRef.local` and
  `Turned` from the lock's own numbers, with a `why=` naming the explore
  run and score the lock now records.
- **A via found near a pad, joined to it** (0.39.0; PLACEMAT_GAPS
  2026-09-26 twice and 2026-09-27): a FreeSpot via draws its tail, and a
  via intent is a track end (spec `2026-09-27-via-tail-design.md`).
- **Route layers from the declared planes** (0.39.0; a board agent's
  router A/B, 2026-09-25): the route step used to give the router every
  copper layer unless `[route] layers` said otherwise, so on a board whose
  inner layers are planes the router ran signals (and a differential
  pair's reference side) through them, and KiCad flagged every such track
  and via against the plane zones. Left to itself, the default now leaves
  out an inner layer whose own outline a `board.plane()` zone covers at
  least `route.plane_share` of, never F.Cu or B.Cu; the route step prints
  what it left out and why.
- **Five PLACEMAT_GAPS bugs, 2026-09-26** (0.38.0): cleanup leaves a
  decided block's satellites alone (cf9f1cd); `--via-near` keeps out of
  every land of a split pin (7a299af); `datasheet` reads text with a
  character reference XML forbids (8ed7488); a run compares with and
  reuses its own board's last run (9278996); a searched `Near` on another
  searched item's pad waits for it (f55c17b).
- **A cell's zones under the board's own plane** (0.37.0, from the owner on
  2026-09-27; a whole test board had 17 cell zones on nets and layers its own
  planes cover): merged into the plane at write, `copper.cell_zones_under_planes`.
- **A class clearance that does not fit a pad pitch** (0.36.0, from a
  board agent's request): a setup finding naming the part, its tightest
  escape lane and the clearance that fits (32131a1).
- **Pair crossings weighed at placement** (0.36.0): a differential
  pair's own crossing costs `score.pair_crossing`; a crossed pair is a
  `pair_crossed` finding (spec `2026-09-25-pair-crossing-design.md`).

- **Explore, the lock and freeze** (0.32.0): `--explore SECONDS` on run and
  preview varies the focused items' spots, rotations and order in parallel
  variants and reports the best; `--accept` keeps it in a lock file of
  anchor-relative entries that later runs apply, drifting or releasing
  with a note; `placemat freeze` moves entries into the script. Measured
  with `bench.py --explore 64`: better on 26 of 32 modules, worse on none.
  Next: large neighbourhood search (spec
  `docs/superpowers/specs/2026-09-25-explore-design.md`, Phase two).
- **Packaging the native module** (0.31.0): the `native` extra builds it on
  install with the machine's Rust toolchain (uv, from `native/`); a tag
  `v*` runs `.github/workflows/release.yml`: the suite without and with
  native, abi3 wheels for Linux x86_64/aarch64 and Apple Silicon, and
  placemat's wheel and sdist, attached to the GitHub Release. A native
  module from another release is not used.
- **A native core** (0.30.0): an optional Rust module (`native/`, built with
  maturin; `PLACEMAT_NATIVE=0` forces Python) takes the geometry
  predicates, the near-obstacle conflict search inside `legal()` with each
  candidate's shapes held natively, and the pocket raster's largest
  rectangle; reasons are formatted once per rejection bucket. Sequential
  timing on the merged code, Python then native, CPU time, whole bench
  corpus: default 62.3 -> 25.0 s (2.49x), solve 59.3 -> 22.0 s (2.70x),
  physical 136.2 -> 30.6 s (4.45x); a whole test board's resolve 224.1 ->
  48.3 s (4.64x). All 102 bench results and all 174 whole-board steps identical;
  the suite passes both ways. Spec:
  `docs/superpowers/specs/2026-09-24-native-core-design.md`. Open: how the
  compiled module is packaged for a release.
- **PLACEMAT_GAPS "placemat 0.28"** (after 0.29.0): item 1, a stamped keepout
  costing the parent: the cell's step now says how much board its regions
  take beyond its members, and `board.fanout()` is the band that follows
  the pad rows. Item 2, the via-in-pad chip on the back: fixed in 0.29.0
  (checked on a whole test board: the MCU's 9 exposed-pad vias read as vias,
  0 leads). Source: a board's `PLACEMAT_GAPS.md`,
  "2026-09-23: placemat 0.28".
- **The solve's default: stays off** (decided 2026-09-24): re-measured on the
  current code (rotations, pockets, neighbour swaps), the solve against the
  sequential seed is 11 better, 17 worse, median HPWL x1.058. `[solve]
  enabled` remains opt-in.
- **Stdlib passive courtyards under a 0.2 mm silk clearance: not placemat's**
  (closed 2026-09-24): the library's courtyards are its own to fix. On the
  placemat side a courtyard-envelope run lists each footprint whose silk
  passes its courtyard (`metrics.footprints`), the physical envelope spaces
  by silk, and a label keeps the silk clearance. Source: a board's `PLACEMAT_GAPS.md`, "a panel cell", item 6.
- **A fanout band** (0.29.0): `board.fanout(part, depth=, sides=)` reserves
  the strip outside each pad row on the part's face for its satellites and
  SHORT-linked parts. Spec: `docs/superpowers/specs/2026-09-24-fanout-band-design.md`.
  Source: a board's `PLACEMAT_GAPS.md`, "passive
  orientation", items 2 and 5.
- **Pin names for pads** (0.29.0): read from the symbols the .zen files
  use (through the component's footprint, else the netlist's name);
  `PadRef(part, pin=)` and pin names in `measure --pads`. 53 parts named on
  a whole test board, the MCU's 57 pins among them. Spec:
  `docs/superpowers/specs/2026-09-24-pin-names-design.md`. Source:
  a board's `PLACEMAT_GAPS.md`, "2026-09-22: which pad
  is the supply pin", "the power cells" item 4.
- **Neighbours trade places in the cleanup pass** (0.29.0): two
  neighbouring two-pad parts of any size are tried in each other's places,
  in any rotation each may take. Bench: 6 better, 0 worse. Source:
  a board's `PLACEMAT_GAPS.md`, "passive orientation",
  item 5.
- **A line item starts across from its links** (0.29.0): `Location(x, None)`
  and `Centre(None, y)` slide from the point across from what they connect
  to when that is placed. Source: a board's `PLACEMAT_GAPS.md`, "passive orientation", item 4.
- **Label boxes in `measure`; a fragment framed** (0.29.0): `measure
  --labels` gives every board silk text's drawn box; `placemat preview`
  frames on the board outline and the placed parts, so parts left at the
  generator's positions do not shrink the view. Source: a board's `PLACEMAT_GAPS.md`, "the MCU cell", item 5.
- **Per-net airwire and part coordinates** (0.29.0): `metrics.airwire_per_net`,
  the impact's `airwire by net:`, and origin, rotation and centre in `parts`.
  Source: a board's `PLACEMAT_GAPS.md`, "a panel
  cell", item 5.
- **`[drc.severities]`** (0.29.0): KiCad rule severities written into the
  board's project each run. Source: a board's `PLACEMAT_GAPS.md`, "the MCU cell", item 1.
- **A fragment laid out by default rules is named** (0.29.0): the rules
  come from the generator (`pcb`); a run notes a board whose silk clearance
  is 0 and the skill says to give a fragment the parent's config. Source:
  a board's `PLACEMAT_GAPS.md`, "the MCU cell", item 3.
- **Courtyards judged as KiCad judges them** (0.29.0): measured, KiCad's
  DRC counts touching courtyards as overlapping and its polygon lies inside
  the drawn box (by 0.03 for a 0.05 stroke). Each footprint's margin is
  read from KiCad's polygon; two courtyards may overlap by the two margins
  less 0.001. Bench: default 14 better, 4 worse, median 0.99. Source:
  a board's `PLACEMAT_GAPS.md`, "seven things", item 6.
- **A stamped cell's labels are reserved in the parent** (0.29.0): each
  silk text in a cell's group is read as a parts-excluding region of the
  cell on its face. Source: a board's `PLACEMAT_GAPS.md`,
  "a panel cell", item 2.
- **A label keeps the silk clearance from its part** (0.29.0): the label
  gap is at least the board's silk clearance. Reproduced with the flag tab
  footprint and KiCad's DRC: at gap 0 every side touched the tab's silk on
  the front; on the back and with the fix, DRC is clean at every rotation.
  Source: a board's `PLACEMAT_GAPS.md`, "seven
  things", item 7.
- **Rows in a drawn envelope keep the envelope's gaps** (0.29.0): a row's
  or ring's gap is at least the widest gap the envelope enforces. Source:
  a board's `PLACEMAT_GAPS.md`, "the MCU cell", item 4.
- **Parts a keepout allows are not DRC violations** (0.29.0): KiCad's
  `items_not_allowed` for an allowed part or net is counted as permitted.
  Source: a board's `PLACEMAT_GAPS.md`, "the power
  cells", item 3.
- **"Wholly off the board" by area** (0.29.0): a region is off the board
  only when it shares no area with it or lies inside a hole. Source:
  a board's `PLACEMAT_GAPS.md`, "seven things", item 4.
- **The far face under a through-hole part** (0.29.0): only its holes
  claim it; a lead keeps courtyards off, a via in the part's own pad does
  not. Source: a board's `PLACEMAT_GAPS.md`, "seven
  things" item 5, "the power cells" item 1.
- **What a run is made from** (0.29.0): the cached generation records
  its inputs and regenerates when one changes; the script's directory is
  importable and its sibling modules count in the run id. Source:
  a board's `PLACEMAT_GAPS.md`, "seven things" items
  2 and 3, "a panel cell" item 3.
- **Three gaps bugs** (0.28.0): the pocket search takes the largest room
  the item fits, and the check before a search rounds toward room; a parts
  keepout or stamped rule area keeps parts off only the faces its layers
  name; an undeclared part is a finding. Source: a board's `PLACEMAT_GAPS.md`, "the MCU cell" item 2, "the power cells"
  item 2, "seven things" item 1, "passive orientation" item 3, "a
  panel cell" item 4.
- **Rotations for searched parts** (0.28.0): all four for a part with none
  declared, in the search, the pocket fallback and the cleanup pass;
  `[place] rotations = "declared"` for the old behaviour. Bench: +13 placed,
  median HPWL 0.84 (default). Whole-board copy (its script already lists
  four rotations on searched parts): 126 placed either way, wire cost
  1385.1 -> 1383.7, 589 -> 676 CPU s under power save. Blocks keep one
  rotation (the bench has none to measure). Source: a board's `PLACEMAT_GAPS.md`,
  "passive orientation", items 1 and 5.
- **legal() faster** (0.28.0): shapes turned once per rotation, rectangles
  by their boxes; the same placements, about a third less resolve time in
  the courtyard envelope.
- **Coinciding outlines** (0.28.0): `polys_overlap` finds shared
  interior when every vertex lies on the other's boundary; two satellites on
  one pad are refused with the reason, not stacked. Source: a board's `PLACEMAT_GAPS.md`, "a panel cell", item 1.
- **placemat preview** (0.27.0): the plan drawn without building the board,
  with links, pockets, unplaced parts, copper and a congestion heat map;
  whole test board unchanged preview 5.3 s. A part not yet placed no longer blocks
  pockets, copper checks or cutouts; RUDY without pad blockage.
- **Code quality pass** (0.26.x): dead code, helpers for repeated code,
  stale docstrings, reuse keys without memory addresses.

- **Run reuse** (0.26.0): replay up to the first changed step, exact. Whole
  test board: unchanged rerun 125 s -> 7 s; a late part changed 118 s -> 24 s.
- **Speed** (0.26.0): block satellites from cached shapes, a raster for
  reservations, links by pad pair: whole-board resolve 298 s -> 106 s, placing the
  same.
- **RUDY reported** (0.26.0): worst cell per run. Validation strategy - many
  complete placement pairs routed by KRT (full run), >= 70% pairwise
  agreement on >= 100 pairs, the unrouted connections near the hot cell, a
  second router on a subset, then 5-10 whole-board placements - is the next step
  before it steers placement.

- **Cleanup pass** (0.25.0): moves and swaps after the searched tier.
  Benchmark: 23 better, 0 worse in default and physical, 26 better with the
  solve; whole test board (mid-normalisation snapshot): findings 26 -> 22, link
  length 831 -> 774 mm.
- **Improving the solve** (measured 2026-09-23 as patches, not shipped).
  Against no solve, better / worse of 32, before the cleanup pass:
  - Bound2Bound net model (Kraftwerk2, SimPL) instead of the chain: 15 / 13,
    and 9 / 2 on the 11 largest modules.
  - SimPL anchor weights (linear growth, divided by distance to the spread
    cell): 16 / 11.
  - Bound2Bound and a re-solve every 3 placements with what is placed as
    anchors: 17 / 11.
  - The solve only for items nothing placed pulls yet: 16 / 10, 11 / 4 on the
    21 smaller modules.
  - Worse: hints from the spread positions (11 / 17 with Bound2Bound), and
    more rounds (10 / 18 at 16 or 30). The spread ignores fixed parts,
    keepouts and a non-rectangular outline, which is the likely reason; a
    spread into the free area is the untested next step.
  - With the cleanup prototype after each, none beat default plus cleanup
    (best 16 better / 10 worse).

- **PLACEMAT_GAPS 2026-09-23** (0.24.0): `measure` box edges, pad outlines,
  mask/paste layers and courtyard findings; a block satellite aimed at an
  anchor pad by number; the fab profile in the run id.

- **Placement envelopes** (0.23.0): `[place] envelope = "physical"` claims
  pads, mask openings, silk and body at the board's own gaps. On the whole test board
  board (2026-09-23 snapshot, mid footprint normalisation): no silk items
  between different parts; resolve 284 s against 239 s in courtyard mode;
  221 placed against 224; 199 `courtyards_overlap` from KiCad's courtyard
  check, which the mode does not honour.

- **Three PLACEMAT_GAPS items** (0.22.0): `find_board` skips `layout =
  False`; `board.edge(facing, outermost=True)`; of two linked items neither
  placed, the one with less pull waits (on the whole test board's pre-block RF
  chain: one pocket fewer, 13.5 mm less link length; the current script is
  unchanged).

- **Run time on large boards** (0.21.1). A 220-part board's resolve went
  from 945-1167 s to 110 s with identical placements: prepared many-vertex
  outlines, bounding-box pruning in `polys_overlap`, a block's obstacles
  gathered once, a grid over a scan's obstacles, and the board raster mask
  kept. What remains is spread over transforms and box building.

- **Pocket fallback for a seeded item with no room**, and the module
  benchmark that measured it (0.21.0). Spec
  `docs/superpowers/specs/2026-09-22-bench-and-pocket-fallback-design.md`.

- **The solve crashed on a board with a keepout** (`51fd482`). Source:
  a board's `PLACEMAT_GAPS.md`, "2026-09-22: `[solve]
  enabled = true` crashes on a board with a keepout".
