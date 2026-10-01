# A turn taken from the spot's bearing, in a radial band

Date: 2026-10-01
Status: design
Source: a board's session, 2026-10-01 (cells hand-placed round a circle,
turned to the tangent; the search is wanted to do it)

## Problem

Items packed into a circle follow its curve: each is turned so its outward
side points away from the centre at whatever bearing it lands on, and a
rectangular one then lies with its long side tangent. The forms that exist do
not say this:

- `rotations=` the four right angles cannot follow the curve; a cell packed
  at 45 degrees fits better than at 0/90/180/270 but only roughly follows it.
- `Turns.ANY` or a 5 degree step is 72 turns at every spot scanned, and
  nothing prefers the turn that is tangent.
- `OnRim` and `OnBore` turn the item to its bearing but only on `board.disc`,
  and put its reach at the keep-in; a board drawn with `board.outline(...)`
  refuses them. `OnEdge(board.edge(facing=...))` works on an outline but
  holds the item at the keep-in, which is inside a seal keepout band where
  the items must stand inboard of it.
- `Polar` is a coordinate about a centre: fixed, or one freedom (a ring or a
  spoke). A search over the ground between two radii has no form.

What is wanted: a searched item whose turn at each candidate spot is derived
from the spot's bearing about a centre, searched in a band of radii about
that centre, on any board.

## Design

### The turn

`rotations=` takes, besides angles, a step and `Turns.ANY`:

- `Turns.TANGENT`: at each spot the item is turned so its outward side (its
  declared `faces(outward=)`, else local +Y, as `OnRim` reads it) points away
  from the centre, and the half turn is also tried (outward side toward the
  centre).
- `Tangent(about=None, quarters=False)`: the same as a value. `Turns.TANGENT`
  is `Tangent()`. `quarters=True` adds the two quarter turns, so a part
  whose long side is its local Y can lie either way.

`about` is, in order: the value's `about=`, the `about=` of the `Polar` the
item is placed in, the board's centre. It takes what `Polar(about=)` takes (a
`Location`, an (x, y) pair, a part, a pad, a `Mid`); a reference makes the item
wait for it.

The spot's bearing is that of the item's origin (a cell: its box centre) about
the centre, clockwise from the top. The turn at bearing b is the one
`board.outward_rotation(item, b)` gives, so the face and a declared outward
side are read the same way.

Tangent turns are for an item whose spot is searched: seeded from its links,
`Near`, or a band. A decided place, a point, a ring, a spoke, an edge, a rim,
a `Beside` and a block are refused with the form that says the same
(`board.outward_rotation()`), as is `rotation=` given with it.

### The band

`Polar((r_min, r_max), None, about=...)`: the item is searched on the ground
between two radii about a centre, any bearing. It is a searched item with two
freedoms, seeded from its links like any, and placed by a scan whose points
are the band's: the item's origin (a cell: its box centre) lies at a distance
in `[r_min, r_max]` from the centre. With nothing to seed it, a band's items
share the turn: the k-th of n sits at k/n of it from the top, at the band's
middle radius, and the scan walks out from there. A seed outside the band is
brought to the nearest radius in it before the scan. When nothing in the band
is legal the item is unplaced with the finding a scan gives, and no pocket
outside the band is tried.

`Polar((r_min, r_max), bearing)` is a spoke segment: one freedom, the radius,
within the range. The radius range is refused on a cutout or keepout and with
a `Bearing` of two points.

A band needs no round board; `about=` gives the centre on an outline.

### Searching a turn per spot

A scan walks a grid of origins and judges each at the item's turns. For a
tangent search the turns at a spot are two (four with quarters), not the
step's 72.

The bearing is quantised into bins of `place.tangent_bin` degrees (default
10.0; the circle is cut into round(360 / bin) equal bins). A spot's turns are
those of its bin's middle bearing, so an item lies within half a bin of the
tangent. The distinct turns over all bins are the turns the scan prepares
(one per bin, as the half turn of one bin is the outward turn of the opposite
one, when the count of bins is even), and each spot is judged at its own two
only. The native sweep takes (x, y, turn) triples, so the scan builds the
triples a spot's bin allows and no native change is needed; the Python sweep
walks the same turns. A spot's turns are tried outward first, so a
nearest-first scan with no score takes the outward turn, and among equal
scores the outward turn wins, then the quarters, then the half turn.

Cost against the four-turn search: the same number of spots, two turns each
(half the judgements), plus preparing one turn per bin where the four-turn
search prepares four. The timings are in the commit.

### Not covered

The global solve, the cleanup pass and explore leave a tangent or band item
where its scan puts it, as they do a point with turns to search: they move
items at a fixed set of turns.

### Settings

`place.tangent_bin`, default 10.0 degrees; above zero, at most 360.

## Verification

Pure tests, synthetic boards:

- a rectangular cell searched in a band on a disc lands with its long side
  tangent (outward side away from the centre) within half a bin of its
  bearing, and the turn is the outward one, not the half turn;
- the same on `board.outline(...)` with an arm, with `about=` the disc's
  centre, and not about the outline's box centre;
- a declared `faces(outward=)` side, and the back face, are turned out;
- quarters add two turns; `Tangent(about=)` and the `Polar` about agree;
- `place.tangent_bin` changes the bins; a bin that does not divide the circle
  is rounded to one that does;
- a band keeps the item between its radii and inboard of a keepout over the
  rim; with nothing to seed it items share the turn;
- a spoke segment slides within its range;
- a seeded item and a `Near` item with tangent turns are turned to their
  bearing;
- a point, a block, a ring, a decided place and `rotation=` with tangent turns
  are refused; a bad band is refused; a band on a cutout is refused;
- native and Python sweeps choose the same spot and turn, and try the same
  number of candidates;
- the candidates tried are at most half the four-turn search's per spot.

Real board: the core fixture's disc and cells, a few rim cells searched in a
band with tangent turns, against the same cells searched at the four right
angles: where they land, and the scan time.

Bench: no declaration in the corpus uses the new forms, so no placement is
expected to change; the tally goes in the commit.

## Documentation

`api.md` (round boards, `rotations=`, `Polar`, settings), `migration.md`
(new; cells turned by hand to follow a curve become `Turns.TANGENT` in a
band).
