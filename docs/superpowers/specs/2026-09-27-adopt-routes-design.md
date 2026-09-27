# Keeping routed copper

Date: 2026-09-27
Status: proposal, awaiting approval
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "router output cannot
be kept in the script"

## The problem

`placemat route` (and `run --route`) routes a copy of the board and reports
closure. Nothing reads the routed copy back: the next `placemat run`
regenerates the board without it. A module fragment whose remaining nets the
router closes cannot keep that copper, so it cannot be stamped into its
parent already routed.

The board worked round it with a tool of its own (`fold_routes.py`): it
diffs the placed and routed boards with pcbnew and prints `board.track()` /
`board.via()` calls in absolute board coordinates, pasted into the script.
Those coordinates go stale as soon as a part moves or turns, and they fill
the script with numbers - what the skill now tells agents to avoid.

## The change

1. **`placemat route <script> --adopt NET [NET ...]`** (or `--adopt-all`):
   after the route, the named nets' new copper - the tracks and vias the
   router added on those nets - is kept in `<script stem>.routes.json`
   beside the script, as the lock keeps explore's spots. Each point is stored
   relative to the pad it belongs to: a track's end on a pad is that pad; any
   other point, and a via, is an offset from the net's nearest pad in that
   pad's part's frame (it moves and turns with the part).
2. **Every run draws the adopted copper** as fixed copper of its net, after
   placement, while the parts whose pads it joins stand as they did when it
   was adopted relative to each other (within a tolerance, a setting). When
   one has moved or turned relative to the others, or a declaration of the
   net changed, that net's adopted copper is dropped with a finding naming
   the part, and the route routes the net again.
3. **The route counts adopted nets as closed by declared copper**, and does
   not hand them to the router again.
4. **`placemat routes <script>`** lists the adopted nets (net, tracks, vias,
   the parts they join, when adopted) and `--release NET` drops one.
5. **Docs:** api.md (route and the file placemat writes), SKILL.md (keep a
   fragment's routed nets with `--adopt`, never paste routed coordinates into
   a script), the migration note (a hand-written fold-back can go).

## Verification

- Pure tests: a routed copy's new copper read into entries; entries drawn
  on the next resolve; a moved part drops its net with the finding; a
  released net is gone; the file round-trips.
- KiCad: route the breakout (quick), adopt one net, run again: the net's
  copper is on the written board and DRC finds nothing new; move a part it
  joins: the net's copper is dropped and the finding says why.
- Bench, as a placement change (no bench board adopts routes: same 32).

## Not in scope

- Freezing adopted copper into the script as declarations: a later step,
  as `freeze` is for the lock.
- Adopting part of a net: a net is adopted whole.
