# Escapes judged by the way out on the surface

Status: draft for review, 2026-10-07; release line 0.100.x, built inside step 2 (one score). Decided with the user:
the escape terms of the one score are a new judgement, specced here and built in step 2, rather than today's corridors
or today's confirmed findings.

## Problem

placemat judges a pad's escape twice, and neither judges what routing needs.

- **The search** (escapes.py `Escapes.closed`, native escapes.rs:151) keeps corridors `place.escape_depth` (1 mm) long
  out of each pad. A part 1-2 mm off an IC never closes one, though a track from the IC's pin has to get past it.
- **The run score** prices the findings `Escapes.confirmed` reports (escapes.py:364), at `score.escape_depth` (1.5 mm),
  confirmed by a path search on a 0.05 mm grid (`path_out`, escapes.py:675). It is too slow to run per candidate, so
  the search cannot use it.
- **Both** count a via spot at the pad as a way out "toward anything" (`Escapes._toward`, escapes.py:361-362). A pad
  that can leave only by a via scores the same as one that routes out on its own layer. A via costs a hole, a layer
  change and the room round it; a track on the surface costs none of that.

The `escape.pinched` check (approach.py) follows each pad's airwire toward its target for `place.approach_reach`
(8 mm) inside a band `place.approach_detour` (2 mm) to either side. It looks for a gap between two other parts that the
pad's track does not fit through. It is a finding only, judged once on the finished board.

## The rule

A pad's escape is the best way its track can leave it, priced by what that way costs routing:

| Way out | Price |
|---|---|
| a surface lane toward its target | 0 |
| no such lane, but a via fits near the pad | `score.escape_via` |
| no lane toward the target and no via, but a surface lane in another direction | `score.escape_closed` |
| none of these | `score.escape_walled` |

The price is the cheapest way the pad has. The run score sums it over every pad judged. A pad is judged when its net is
not quiet (a plane's or a free net's), it is not a no-connect pin (`is_no_connect`), and its net has another pad
placed. The pads of a quiet net are not judged: their via into the plane is their way out.

**A surface lane** is a straight track at the net's track width, kept the net's clearance (`Occupancy.pair_clearance`,
the script's rules included) from every other net's copper on one of the pad's own copper layers: pads, planned tracks
and vias, and unplated holes at the hole clearance. It runs in two legs:
1. **Out of the pin field:** from the pad, along its pin normal (`placer._pin_normal`), until it is clear of its own
   part's other pads. A part with two pads or one has no pin field: the first leg is empty.
2. **On:** straight in one of the eight compass directions, 0, 45, 90 ... 315 degrees in the board's frame, until it
   is `score.escape_reach` from the pad's centre.

A lane is **toward the target** when the second leg's direction is within 90 degrees of the direction to the pad's
nearest airwire neighbour (a positive dot product, as `_toward` judges now). A part's body does not block a lane, since
a track may run under it; its pads do.

**A via near the pad** is a via of the net's class, clear of every other net's copper on every layer and of via bans,
at one of the pad's via spots:
- touching the pad's edge in each direction a corridor takes now (escapes.py:121-147: the pin normal, and for a part
  of one or two pads its sides);
- at the end of the lane's first leg, where it leaves the pin field.

Why this shape:
- **The lanes' reach** is set past the parts that sit next to a pin. With a default of 3 mm, a capacitor 1-2 mm off an
  IC blocks the lanes it stands across, and a lane that passes beside it is still found.
- **Two straight legs**, not a path search, keep the judgement a fixed set of rectangle tests per pad. That set can be
  run per candidate natively, and the same code gives the whole board's value and a candidate's change. Routing that
  needs a dog-leg past two parts within the reach is not seen as a lane. That case is left to the routing phases.
- **A via is priced, not free.** That is the user's point: a pad that must drop a via is worse than one that routes out
  on the surface.

This judgement is placemat's own rule, not a KiCad rule (the charter's "Judged as KiCad judges"). Its finding kinds
say so.

## Crossed escapes

`escape_crossed` keeps its definition: two airwires of different nets, from pads of one part, cross within
`score.escape_depth` of that part's pads (`Ratsnest.crossed_pair_list`). It is a crossing count and already has an
incremental form on the ratsnest. The search's own depth (`place.escape_depth`) is removed. The search counts it at
`score.escape_depth`, as the run score does.

## Findings

The judgement replaces `Escapes.confirmed` as the source of the escape findings:
- `escape_closed` and `escape_walled` keep their kinds and facts, judged by the rule above;
- `escape_via` is a new kind, at severity `warning`, with facts `ref`, `pin`, `net` and `by` (the copper and parts that
  block its surface lanes, as `escape_closed` names them).

The findings and the run score count the same pads, so a finding and a priced term never disagree. `escape.pinched`
stays as it is: a finding on the finished board, not priced.

## Whole and incremental

- **Whole:** every judged pad's price, summed.
- **Incremental:** when items are lifted and put down elsewhere, the pads re-judged are:
  - the moved items' own pads;
  - every placed pad whose lanes or via spots the moved items' copper enters or leaves. Those lanes lie within
    `score.escape_reach` plus a lane's half width of the pad, so they are found from a grid of lanes by box;
  - every pad whose airwire neighbours change: the ends of the airwires the move adds to or drops from its nets' trees
    (the MST change). A pad's target is its nearest airwire neighbour, so a new pad of its net, however far away, can
    turn its open lane toward or away from the target.

  The change is the re-judged pads' new prices less their old. It is signed: a moved pad can become a nearer target
  and open another pad's escape.
- **Native:** the lanes are kept per pad in the native escapes index (escapes.rs) and judged there. The search calls
  the incremental form per candidate, after the cheaper terms.
- **Lower bound for pruning:** on the lifted board the moved items' copper only adds obstacles, and their own pads start
  unjudged, so only a pad whose target changes can get cheaper. The change is therefore at least minus the sum of the
  current prices of the pads whose airwire neighbours change. The search prunes on that bound, never on zero.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `score.escape_reach` | 3.0 mm | how far a surface lane runs from the pad's centre |
| `score.escape_via` | 10.0 mm | the price of a pad whose only way out is a via |
| `score.escape_closed`, `score.escape_walled` | unchanged (50, 400) | as now, judged by the new rule |
| `score.escape_depth` | unchanged (1.5) | crossed escapes only |

Removed: `place.escape_depth`, since the search counts crossed escapes at `score.escape_depth`. Its removal has a
migration entry.

## Gate

The judgement moves the run score, so it lands before the gate's baselines are re-recorded (the one-score plan's
order). Before it is adopted:
- **Agreement:** on the bench modules, the share of pads where the lanes agree with the exact path search
  (`path_out(exact=True, via_exit=False)` over a window `score.escape_reach` round the pad, toward the target) on
  "surface way out toward the target" is reported. Disagreements are listed by cause.
- **Speed:** the incremental form is inside the one-score speed gate.

## Testing

- A capacitor 1.5 mm in front of an IC pin, across the pin's normal: the pin has no surface lane through it. It has a
  lane past the capacitor at 45 degrees when there is room, and is priced 0; with no room it is priced as a via-only
  pad.
- A pad that can leave only by a via is priced `score.escape_via` and reported `escape_via`.
- Whole against incremental, per pad and in total, on the bench fixtures and on synthetic boards, including a move that
  makes a far pad of the same net a nearer target and opens its escape.
- A quiet net's pad and a no-connect pad are never judged.

## Out of scope

- Dog-leg lanes and paths round more than one part: routing judges those.
- Lane direction by the router's own preferred directions per layer.
