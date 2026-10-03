# Room for declared copper during placement

Follows `beside-shapes` (Beside stands against the shapes of its item's envelope and moves out to the first
place the collision rule allows). That change makes parts stand nearer, and in the fixture scripts it leaves
less room for copper the script declares later: a track drawn past a part that now stands nearer comes out
under its clearance, in the plan's findings and in KiCad's DRC. This spec has placement allow for that
copper. Design only; nothing is built.

## Problem

Placement of firm items (`Location`, `Beside`, `Pin`, edge forms) does not see copper the script declares
with `board.track`, `board.via` and `board.pour`. Order of a resolve today (`Board.resolve`, layout.py):

1. firm items are placed (`place_ranked(RANK_FIXED, RANK_EDGE)`), in dependency order;
2. escapes not yet laid are laid (`_place_escapes`); escape lanes and fanouts are reserved or committed
   as their part is placed, so a later part already keeps clear of them;
3. `fixed_copper` is planned (`_plan_copper`): the copper whose endpoints are all decided;
4. searched items are placed, with that copper in the occupancy as obstacles;
5. `other_copper`, the copper that depends on a searched item, is planned.

A firm part is therefore placed before the copper that must pass it exists. A searched part is placed after
step 3 and already keeps clear of `fixed_copper` (an obstacle like any other); it does not know copper of
step 5.

Evidence: with `beside-shapes`, 13 tests of the real-module fixtures fail that pass on main. Their causes, as
found by comparing each script's run with the shape fit off:

- a KiCad clearance violation, 0.068 mm against 0.16, between a script's declared track (a lane continued
  with `board.track`) and a pad that now stands 0.12 mm nearer (usbconverter, two tests);
- the same with a lane-continued track 0.13 mm from two other nets' copper (mcu, nine tests, in part);
- two firm collisions along a cross axis (mcu): a part aligned level with another cannot be moved along its
  own side to clear a neighbour that tightened on the other axis;
- a searched part landing elsewhere, so the script's fixed tracks cross (usb5v, two tests);
- a searched part's link over its limit (mcu).

This design covers the first two kinds and, partly, the last two; the third is a different problem (see
"Acceptance").

## Scope

Copper that reserves room during placement:

- tracks (`board.track`), with waypoints and with endpoints at pads, lanes or vias: yes;
- vias (`board.via`, at a pad or a spot): yes, where the dry plan gives a position (see "Derivation");
- pours: not in this change (open question 3). A pour is fitted to the copper it joins and kept clear of the
  rest, so it adapts to parts standing nearer; its failure is a finding "no way between pads", reported
  already;
- planes and stitching: no. A plane is a fill, a stitch is placed over what is there;
- escape lanes and fanouts: nothing to add, they reserve already.

Only copper that step 3 plans (`fixed_copper`) can be known before the firm parts are placed. Copper that
depends on a searched item (step 5) is not covered: its endpoint has no place yet (open question 2).

## Approach

Ask the copper planner where the copper goes, and keep firm parts off that.

The planner is the only place that knows how a declaration becomes copper: `Past`, `Between`, `Mid`, `X()`
and `Y()` points, lanes, `bend=`, chamfers, widths and layers. Re-deriving a corridor from the declared
points would be a second implementation of it (the charter's "intent, not coordinates" asks for one reading
of an intent, and a second would drift). So:

1. Pass 1: place the firm items as today.
2. Dry plan: for each intent in `fixed_copper`, call its `plan(ctx)` (`CopperIntent.plan`), which returns
   the ops, `Track` and `Via`, with their points, widths and layers, before crossing settlement and before
   anything is committed to the occupancy. Nothing is drawn.
3. Pass 2: place the firm items again from the start, with each dry-planned op present in the occupancy as a
   provisional obstacle (below).
4. Dry plan again from pass 2's positions. If every op is where it was (to `place.copper_room_tolerance`),
   the placement is settled; otherwise repeat from 3 with the new ops, up to `place.copper_room_passes`
   passes. A placement still moving at the last pass keeps that pass's result and says so (a finding).
5. The real planning (step 3 of the resolve) then runs on the settled placement as today. The provisional
   obstacles are removed first.

A provisional obstacle is a copper shape in the occupancy: a track as the track's polygon with its net,
width and layer; a via as its ring. It is judged by the one collision rule (`Occupancy._conflict`) exactly
as a planned track is: another net's pad, hole, via or copper must keep the pair's clearance (the board's
rules and the script's `board.rule`s, `Occupancy.pair_clearance`), the same net may touch, a net tie keeps
its exclusion. So there is no new rule and no corridor width to invent: the corridor is the track widened by
the clearance, because that is what KiCad checks. The Python and the native searches both read
`Occupancy.copper`, so both see it (as they see `viaban` shapes and cell copper).

The new part is bookkeeping: the shapes carry an owner `room:<intent key>` so a pass removes its own and a
resolve's reuse record can tell them from real copper.

## Derivation from what is known

- A track whose points are all resolvable at pass 1 (placed pads, lanes, literals) is planned as it will be
  drawn. This is every track of `fixed_copper` by definition.
- Waypoints given as `Past`, `Between` or `X()`/`Y()` of a reference resolve against pass 1's placed items;
  that is what `plan(ctx)` does. If pass 2 moves the item a waypoint is read from, the ops move with it, which
  the next dry plan sees. This is why the loop exists: the geometry is a fixed point of "place, then plan".
- A track with an endpoint on an item that is not placed in pass 1 (a firm item that depends on a searched
  one, or a searched one) is not in `fixed_copper` and is skipped.
- A track the planner cannot draw at pass 1 (it reports `copper.not_drawn` or `copper.corner`) reserves
  nothing; its finding appears as it does today.
- Crossing settlement and bridging (`bridge=`) are after the dry plan, so a bridging track reserves its
  whole path. A track that would yield to a higher-priority track also reserves its path; the real planning
  settles the crossing as now.

## Block or score

A provisional obstacle blocks. Firm placement is a refusal, not a search: `Beside`'s first legal contact (the
push in `beside-shapes`), `Location` collisions and `Pin` placements are all judged by `legal`, and a copper
obstacle is one of the shapes `legal` judges, so the first legal contact steps past the track as it steps
past a neighbour's silk. A search cost would leave a firm part standing in the room.

The search is unchanged: searched items already see `fixed_copper` as real obstacles after step 3, and
scoring is untouched. Provisional shapes exist only during the firm passes.

## Give-way

Vias carried by a cell or part give way to copper planned before them (`giveway.py`). A provisional track
must not move a carried via: the real copper is planned later and may differ. Provisional shapes are
excluded from the give-way's obstacle set, as `carried=False` obstacles are for the search. Open question 4:
whether a carried via should keep clear of a provisional via ring.

## Findings

When a firm item cannot stand clear of provisional copper within `place.beside_reach` (Beside) or at all
(a fixed place), it is the finding it is today, a firm collision, with a new cause `fixed.room`:

- facts, structured (the 0.92 finding facts, not text): the item, the intent key and net of the copper, the
  clearance it needs, the distance it has, the pass number;
- the text names the track the way `copper.meets` does, so a suggestion can offer a `gap=`, a different
  anchor, or moving the track's waypoint.

Passes exhausted is `fixed.room_unsettled`: the intents whose ops still moved at the last pass, and by how
much. It is not an error; the resolve goes on with the last pass.

A script that declared a track which is not drawable still gets its `copper.*` finding only.

## Native

No change to the native search: provisional shapes are ordinary obstacle shapes, and the native obstacle
cache is keyed by the skip set and cleared on commit; adding and removing them per pass goes through
`Occupancy._changed()`. `Beside`'s push calls `legal` and is not native. The dry plan is Python, once per
pass.

## Settings

New, in the generated table (`S()` form), under `place`:

- `place.copper_room` (bool, default true): firm placement keeps room for declared copper. False is the
  behaviour before this change;
- `place.copper_room_passes` (count, default 3): the most place-and-plan passes;
- `place.copper_room_tolerance` (mm, default 0.001): how far an op may move between passes and count as
  settled.

No literal in code; the width and clearance come from the board's rules.

## Cost

The firm phase is repeated, up to `passes` times, with one dry plan each. The firm phase is small beside the
search (the bench places with bare `place()` and has no firm items, so it cannot show this). To measure
before accepting:

- time `Board.resolve` on the six fixture scripts and on the whole-board fixture (`fixtures/bench.py
  --board`), with `place.copper_room` true and false, and report seconds and the pass count each took;
- the bench at `--jobs 2` must stay `same` on every module (nothing there has firm copper);
- budget: the scripts' resolve time up by no more than 10 percent, the pass count at most 2 on average.

If a script's passes are slow because the dry plan is, the first fix is to dry plan only the intents whose
endpoints or waypoints belong to items that moved since the last pass.

## Reuse record

A resolve's reuse record digests each step's inputs. The firm items' placements now depend on the copper
declarations, so the digest of a firm step includes the dry-planned ops it was judged against, and a pass
that changes them changes the digest. Replays (`reuse`, the lock, explore) place firm items from the same
passes, so the loop runs inside the firm phase and its result is what is recorded.

## Acceptance

With this change and `beside-shapes`, on the six fixture modules (usbtcpc, usbcells, logicsupply,
usbconverter, mcu, usb5v), run end to end against main with the harness used for the comparison:

1. KiCad clearance and short counts are no worse than main on every module;
2. findings and score are reported beside main's, and no module places fewer parts;
3. the 13 tests that fail with `beside-shapes` pass without changing a script, or each exception is
   explained.

What I expect, from reading the failures; the first step of the implementation is to confirm it, by listing
which of each module's declared tracks are in `fixed_copper`:

- usbconverter (2 tests): the track is a lane continued with `board.track` between firm parts: covered;
- mcu, the lane track (clearance 0.131 mm and the lane finding, most of nine tests): a track from an escape lane,
  covered if its far end is firm; it is a lane-only track (`board.track(net, [escape["pin"]])`)
  and the part that stands near it is placed by Beside: covered;
- mcu, two decoupling parts (firm collisions along a cross axis): not covered. They are a part aligned
  with another and a neighbour that tightened on the other axis. Open question 1;
- mcu, a searched inductor 1.61 mm from its pad (link over 1.5): a searched part, not covered; it may follow from
  the others;
- usb5v (2 tests: tracks cross): the searched buck lands turned 180 degrees where the script's fixed tracks
  cross; the tracks are `fixed_copper` only if every endpoint is firm; the buck is searched, so they are not.
  Not covered. Open question 2.

So acceptance item 3 is not met by this change alone for mcu's cross-axis collisions and for usb5v, unless the
user chooses one of the options in the questions below. Say so in the plan rather than retune the scripts.

## Open questions

1. A part aligned level with another along the cross axis (`Beside(x, side, align=pad of y)`) cannot move
   along its own side to clear a neighbour that tightened on the cross axis (mcu: two collisions). Options:
   (a) leave them as findings with the suggestion the 0.92 findings give; (b) let `Beside` try the other
   side's order, placing the neighbour after it; (c) when a firm part is refused after its push, re-place the
   part it is aligned with at its own first legal contact further out (a bounded backtrack). (c) changes more
   placements; which do you want?
2. Copper that depends on a searched item (usb5v's tracks, any track to a searched part) is planned after the
   search and is not covered. Two ways to cover it: reserve, for such a track, a straight corridor between
   its placed end and the searched item's search region (cheap, imprecise, a search cost), or run the search
   with the copper dry-planned at each candidate (the riders mechanism does this for riders; it is a large
   cost). Cover it now, later, or leave it to the 0.92 findings?
3. Pours (fitted polygons): reserve their dry-planned polygon (keeps a part from entering a pour's room,
   which is what makes a pour's "no way between pads" finding) or leave them? Reserving a pour's own polygon
   also keeps parts out of room a pour only needs because the script said `swallow_pads=True`.
4. Should a carried via (a stamped cell's) keep clear of a provisional via ring, or only of real copper?
   Giving way to a provisional one moves a via for copper that may change.
5. `place.copper_room` defaults true. It changes placements of scripts that declare tracks near firm parts
   (parts stand where there is room for the copper, not where the box or shape standoff put them). Is that
   a "breaking change" in the charter's sense, so asked first, or a bug fix? I treated it as a fix because
   those scripts get a KiCad clearance violation today and none gets worse by it, but it moves parts.
6. Passes: 3 and a tolerance of 0.001 mm are guesses. A script whose firm items and copper depend in a cycle
   (a track's waypoint is `Past` of a part that is itself placed by the track's lane) may not settle; is a
   finding the right outcome or should the pass count be a hard failure with `--keep-going`?
