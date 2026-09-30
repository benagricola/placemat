# Clearance rules the router keeps, and a track that leaves its pin straight

Status: draft, for approval.

Source: a board's session (2026-09-30), two requests from routing a QFN's
crystal pins at 0.4 mm pitch.

1. Keep a track clear of a named group of pads or nets while the router
   still chooses its path. `Past()` fixes one point; the legs either side
   are the router's, and may pass nearer something than the script wants.
2. Make a track's first leg leave its pin along the pin row's outward axis,
   for at least the clearance, before it turns.

## What placemat does today

- The leg router (`route_leg`) takes the fewest-turn, shortest octilinear
  way between two points whose legs keep the clearance from every pad and
  planned copper of another net. Where none does, it draws the fewest-turn
  way and the run reports the conflict. Since 0.64.1 it tries more ways
  first: a short straight along the other axis before or after the 45.
- The clearance it keeps is the netclass figure for the pair of nets
  (`occupancy.py`, `_conflict`: `geometry.clearance(s.net, o.net)`).
- `board.rule(clearance=, between=(net, net) | on=net | within=cell, why=)`
  writes a custom rule to the board's `.kicad_dru`, which KiCad's DRC
  judges. **Placemat's own router and copper findings ignore it.** A script
  that says "keep XTAL_N 0.3 mm from STRAP_DOWNLOAD" as a rule gets a track
  routed at the netclass clearance and a KiCad DRC violation; one that
  lowers a pair's clearance for an 0201's own lands gets placemat findings
  KiCad does not report.

In the case that prompted both requests, no way out of pin 53 clears: the
crystal's series inductor stands 0.2 mm off the pin row's outer end, in the
pin's own row. Neither change below routes that pin; moving the inductor
does. Both requests still stand for the next pin that has room.

## Design

### 1. The router keeps the script's clearance rules

Placemat judges copper clearance as KiCad does, with the script's rules in
it. Checked against KiCad's own DRC (kicad-cli, 2026-10-01):

- A rule whose condition matches a pair of items replaces the netclass
  clearance for them, higher or lower: a 0.3 mm rule is enforced over a
  0.2 mm netclass, and a 0.1 mm rule lets 0.15 mm pass under it.
- Where several rules match, the one later in the file wins.

So the clearance between two items is that of the last declared rule that
matches them, else the netclass figure. A rule matches as its written
condition does:

- `between=(a, b)`: one item on net a, the other on net b;
- `on=n`: either item on net n;
- `within=cell`: both items members of the cell (its members' pads, and
  the copper its declarations draw, which is written into its group).

This clearance is the one used by the leg router's test (`clear` in
`board.track`'s plan), by `Past` and `Between` (which hold a point the
clearance off copper), by `FreeSpot` via sites, and by the copper findings
a run reports. Placement conflicts (bodies, courtyards) are unchanged:
the rules are copper clearances.

With this, request 1 is a rule, and no new keyword:

```python
board.rule(clearance=0.3, between=("XTAL_N", "STRAP_DOWNLOAD"),
           why="the crystal's pins kept off the strap pin's edges")
board.track(Net("XTAL_N"), [PadRef(Part("mcu"), "XTAL_N"), PadRef(Part("xtal"), "XTAL_N")],
            layer=CopperLayer.F)            # the router keeps 0.3 mm from STRAP_DOWNLOAD
```

A group of pads that are not one net is named net by net, one rule each.
Where no way keeps a rule's clearance the leg is drawn as today, and the
finding quotes the rule by its `why`, as KiCad's violation does.

### 2. A track that leaves its pin along the row's axis

`PadRef(part, pin, escape=True)`, as a track's end point, starts or ends
the track with a straight along the pad's outward axis, then routes on as
before.

- The axis is the pin's row's outward normal, as a fanout and a block's
  satellites read it (`_escape_axis`): off a QFN's west side, west.
- The straight ends where the track's copper is the clearance past the
  row's outer edge: the outermost reach, along the axis, of the pad and
  the pads beside it in its row, plus the clearance by net pair to them,
  plus half the track's width. From there a 45 or a right angle toward
  either neighbour keeps that clearance from it.
- The rest of the track routes from that point as from any waypoint;
  where the straight itself does not clear (another part stands in the
  row's way, as the inductor does at pin 53), it is drawn and the finding
  names what it meets.
- `escape=True` on a pad with no row (a lone pad, a square one at a
  corner) uses the ray from the body's centre, as `_escape_axis` does.

**Refused** at declaration: `escape=True` with `edge=` (a tap meets its
pad at an edge; an escape leaves from its centre), and `escape=` anywhere
but a track's first or last point.

`escape` is left out of a declaration's digest when unset.

## Decision for approval

- Part 1 changes routing and findings on every board that declares a
  clearance rule, toward what KiCad's DRC already says. Scripts that
  worked round the router's ignoring a rule (a waypoint to hold a track
  off a net a rule names) can drop the waypoint.
- Part 2 is opt-in. Making every fine-pitch pin escape by default is a
  larger change to routing and is not proposed here.

## Verification

1. Rules:
   - a raising `between=` rule: the router's leg keeps the rule's
     clearance where the netclass one would have let it pass nearer, and
     KiCad's DRC reports nothing on the written board;
   - a lowering rule: a leg the netclass clearance refuses is taken, no
     placemat finding, and KiCad's DRC is clean;
   - `on=` then `between=` in that order, and the reverse: the later rule
     is kept, as KiCad keeps it;
   - `within=` a cell: its members' pads and its own copper judged by it,
     another part's pads not;
   - `Past` and `FreeSpot` hold their points off by the rule's clearance;
   - a finding under a rule quotes its `why`.
2. Escape:
   - a QFN pin at 0.4 mm pitch, its track to a point up the row: the
     first leg runs along the outward axis to the clearance past the row's
     outer edge, then turns, and keeps the clearance from both neighbours;
   - at a track's last point, the last leg arrives along the axis;
   - a turned part and one on the back: the axis turns with the part;
   - a part standing in the row's way: the straight is drawn and the
     finding names it;
   - refusals as above;
   - digest parity: a script without `escape=` digests as before.
3. Bench: unchanged (the corpus declares no clearance rules and no
   `escape=`).
