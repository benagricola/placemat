# Either face

## Problem

`board.place(item, face=...)` takes `Face.FRONT` or `Face.BACK` and defaults
to `FRONT`. Nothing lets the search choose, so a searched part or cell that
has no reason to be on one face is pinned to a face by hand, and whether the
other face would have given it a better spot is never asked. Source: a
board's session, 2026-10-01, the user's words relayed:

> For stuff that doesn't _need_ to be on the front face, we should be
> searching both faces anyway

## Design

### The form

`face=Face.EITHER` (or the string `"either"`) on `place()`. A searched part
or cell tries the front, then the back, and keeps the better spot.

The default stays `Face.FRONT`. Changing it would move placements on every
board whose scripts say nothing, and an item that must face something would
need `face=Face.FRONT` added everywhere. Scripts opt in per item.

`face=None` is refused with the other values `Face` does not take. "No face
given" and "either face" read alike in a script, and only one of them is the
default.

`Face.EITHER` is a declaration only. The declaration records `face=FRONT`
and an `either` flag (left out of the declaration's digest when false, so
existing locks and reuse records keep matching), and every placement,
step, lock entry and written board has a real face. `Face.EITHER.copper`
raises.

### Which declarations take it

Only an item whose spot the search finds: no position, or `Near(...)`; a
part or a cell. Refused at declaration, naming what decided the item:

- a decided position (`Location`, `Centre`, `Pin`, `Origin`, `Mid`,
  `Beside`), a line (`Location(x, None)`), an edge, a rim, a ring or a
  spoke (`OnEdge`, `OnRim`, `OnBore`, `Polar`), a row's member, a block;
- `rotation=Facing(...)`, which turns a part by the face it is on.

These items "must face something" or are placed by where they stand, so
they keep a fixed face. `rotation=Turned(...)`, `rotation=` as a number and
`rotations=` are allowed.

### Scoring

The search scans the front as it does now, then the back as a second scan,
each with the item's own turns and each judged and scored by the same code:

- legality is the occupancy's, per candidate face: courtyards and bodies
  are on their own face, plated leads and holes reach both ("The far face",
  api.md), keepouts and rule areas are judged by the layers they cover, the
  board's keep-in and edge, via conflicts with the other face's copper, and
  a cell's flip rules (a flipped cell keeps its inner copper on its layers,
  its face vias mirror);
- the score is the Scorer's: link lengths from the pads as they land on that
  face (a back-face part is mirrored about the vertical axis, so its pads
  fall on other sides of it), `score.crossing`, escape weights and lanes,
  `board.push` and `Pm.Emits`/`Pm.Limit` pairs (all distances in the board's
  plane), and a carried via giving way.

Links do not pull an item to the face its partners are on: the Scorer
measures lengths in the plane and has no per-face term for a link, for a
flipped item as for any other. A link between faces costs what its length
costs. A cost for a link that crosses faces is not part of this change.

A spot on the back costs `score.back_face` more (default 2.0, in the
score's own units, a millimetre of a link of weight 1). The back is taken
when its best score plus that is below the front's best, or when the front
has no legal spot. An equal spot is the front's. With `score.back_face = 0`
a tie still goes to the front.

When the search is unscored (nothing placed to link to, no push, no lane)
and the front has a legal spot, the front is taken and the back is not
scanned; the back costs more and nothing else tells them apart. When the
front has none, the back is scanned, and the step note says why it was
taken: "on the back face: the front has no legal spot (<refusals>)", or
"on the back face: <back score> and <cost> for the back face against
<front score> on the front".

An item with nothing to seed it takes a pocket: the front's pockets first,
then the back's. A seeded item whose scan found nothing takes the nearest
pocket it fits, the front's first. An item that fits on neither face is
unplaced, and the finding names both faces; a required item's stop report
lists the biggest free rectangles on both.

### Labels, keepouts, limits, declarations of a cell

- A label is on its item's face: it follows the face the search chose
  (mirrored on the back, as for an item placed there by hand).
- A keepout or rule area with `layers=` is judged against the candidate's
  face, so a part kept off the front by a rule area can take the back there.
  A through-hole lead is on both faces and is refused by either.
- `Pm.Emits`/`Pm.Limit` and `board.push` distances are in the plane, and
  an emission or sense point is turned and mirrored with the face the item
  lands on.
- A cell's `faces(outward=...)` and every outward turn belong to edge and
  ring placements, which are refused with `Face.EITHER`; a searched cell is
  turned by `rotations=` or its one rotation.
- Riders (items declared relative to the searched item) are judged with it
  at each candidate face.

### Native

`scan` is per face already: `native_sweeper(item, face, rots, ...)`,
`NativeScoring` (keyed by rotations and face), and the via give-way scan
take the hint's face. The EITHER search is two ordinary scans, so both are
swept natively when they can be, and nothing in `native/` changes. The
back's scorer starts with the front's best less `score.back_face` as its
floor, so it prunes the candidates that cannot win.

### Explore, lock, replay

- A step records its placement with its face; replay applies it, and a lock
  entry holds the face of the spot, so a locked item with `Face.EITHER`
  is held on the face it was accepted on. The declaration digest includes
  `either` only when set.
- Explore draws among the near-best spots of a focused item within each
  face's scan, then the faces are compared as above.

### Settings

`score.back_face` (default 2.0, at least 0): the cost of a back-face spot
in a search of `Face.EITHER`. It affects no item declared with a fixed
face, so every existing script places as before.

## Verification

Tests (`tests/test_either_face.py`):

- an item with no room on the front and room on the back lands on the back,
  the same item pinned to the front is unplaced; the step note says why;
- equal room, and `score.back_face = 0`, land on the front;
- a spot that saves wire on the back wins when `score.back_face` is small
  and loses when it is large; a pinned item is unaffected by the setting;
- a front-only keepout sends a surface part to the back;
- a cell with through-hole members is refused by the other face's parts,
  where a surface cell takes the back;
- a cell takes either face and its parts land flipped;
- `Face.EITHER` with a decided position, a line, an edge or `Facing` is
  refused; `face=None` is refused;
- a declaration without `either` digests as before;
- replay and a lock keep the face;
- native and Python sweeps give the same scans and plan for both faces.

Full suite, and `fixtures/bench.py --jobs 4`: every case is unchanged,
because nothing declares `Face.EITHER`.
