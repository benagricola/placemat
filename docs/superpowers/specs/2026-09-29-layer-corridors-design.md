# Clear corridors on one layer between two pads

Date: 2026-09-29
Status: approved 2026-09-29 (the owner: implement unless a decision is needed)
Source: a board's PLACEMAT_GAPS.md, 2026-09-29 "a clear column on one inner
layer"

## The problem

To find where one LDO_3V3 run could cross the whole test board on In3, a board session
listed, for each 0.5 mm column, every In3-facing pad, via, track, cutout and
foreign zone, using pcbnew.
- `placemat occupancy` answers one point or box at a time, about 2 s each.
- `--via-near` searched for minutes with kept routes standing.
- Nothing reports the free corridors on a layer between two pads.

## The change

1. **`placemat occupancy <board|script> --corridor A B --layer L --width W [--net N] [--ignore-kept] [--json]`**
   (A and B as `PART.PAD`):
   - It finds the clear paths on layer L from pad A to pad B for a track of
     width W on net N (default: A's net). "Clear" means the netclass
     clearance to every other net's copper on L: pads that reach L, vias,
     tracks, foreign zones and cutouts.
   - It reports the shortest octilinear path as its corner points, with
     length and turn count, and up to two more paths that share no cell with
     the first.
   - With no path it reports the blockers across the narrowest cut between
     A and B, each named: a part's pad, a via, a track of a net, a zone, a
     cutout.
   - `--ignore-kept` leaves out the tracks and vias of kept routes
     (`routes.json` entries), to see the room a re-route would have.
2. The search is one grid pass on the query's own clearance map, at the
   router's default grid of 0.1 mm, bounded to the box round A and B grown
   by `--margin` (default 10 mm). The occupancy is built once per query.
   The target is under 10 s on a whole test board.
3. **Docs**: api.md's `occupancy` section.

## Verification

- A synthetic board with two pads and a wall of foreign copper with one
  gap: the path passes the gap. With the gap closed, no path, and the
  blockers named are the wall's pieces.
- A foreign pad on another layer does not block, a through pad does, and
  foreign zones and cutouts block.
- `--ignore-kept` on a board with a kept route across the only gap: a
  path.
- A timing check on the breakout under 5 s.
