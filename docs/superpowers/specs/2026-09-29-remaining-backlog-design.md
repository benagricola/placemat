# Riders on a searched item, a keepout inside a pad ring, one land of a pin, explicit router pairs

Status: approved (2026-09-29).

These four are the backlog items that change an interface. The rest of the
open backlog is listed at the end, with why each waits.

## 1. A firm relation to a searched item: a rider

**Problem.** A `Pin`, `Beside`, `row(of=)`, or a cutout or keepout at a
`PadRef`, whose reference is a searched part is refused: "only FIXED and
EDGE items may be referred to". One board's bypasses at the ends of an
eFuse's long power lands needed their eFuse fixed first, which turned an
electrical relation into fixed cell spacing (PLACEMAT_GAPS 2026-09-26).

**Design.** A firm placement whose reference is a searched item rides it:
- the searched item is scanned with its riders attached, each at the spot
  its relation gives for that candidate (turning with the candidate's
  rotation);
- a candidate is legal only if every rider is legal there, the same test a
  block's satellites get;
- the item and its riders commit together;
- a rider may have riders of its own.

The refusal stays for a relation to an item that is still searched and is
not the rider's reference. An example is a `Beside` whose `align=` pad is on
a third, searched part: that pad has no position until its part lands.

A rider that no candidate fits makes its reference's search fail. The
finding names the rider and why it did not fit.

**Cost.** The search runs the riders' legality test at each candidate that
survives the reference's own test. The bench measures it: riders are new, so
the corpus has none, and a test board with riders measures the added time.

## 2. A keepout inside a part's pad ring

**Problem.** The region between a receiver's two pad columns, or inside a
QFN's ring, is computed by hand (PLACEMAT_GAPS 2026-09-29, "a plane bounded
to a group of parts").

**Design.** `board.keepout(Inside(Part("u1"), margin=0.0), name, ...)`: the
box bounded by the inner edges of the part's pads.
- On each side that has pads, the edge is the innermost edge of the pads on
  that side of the body centre.
- On a side with none (two columns and no rows), it is the pads' outer
  extent on that axis.
- It is grown by `margin` (negative shrinks it).
- It moves, turns and mirrors with the part, as `keepout(Part)` does.

## 3. One land of a multi-land pin

**Problem.** A pin drawn as a side tab, small pads and an exposed pad is one
`PadRef`. It locates at the centre of all its lands, which can be bare board
between them, so a track or via cannot end on one land (PLACEMAT_GAPS
2026-09-29, "the exposed land of a pin drawn as several lands"). A pour over
the whole pin already works with `Cover.HULL`.

**Design.** `PadRef(part, 1, land=Land.LARGEST)`, or `land=2` for the
footprint's second land of that number:
- the reference locates at that land's centre;
- wherever a pad's shapes are read (a track's end, a via grid, `Past`, a
  pour's corners), only that land counts.
- `land=` carries `omit_default`, so every existing digest is unchanged.

## 4. Explicit pairs for the router

**Problem.** The router pairs nets only by a `_P`/`_N`, `P`/`N` or `+`/`-`
suffix and takes no explicit pair (read in `py_router/route_diff.py`). Nets
named otherwise cannot be pair-routed, for example a tank's two leads
(PLACEMAT_GAPS 2026-09-27). KRT stays unchanged; this is local to placemat.

**Design.** A `route.diff_pairs` entry `"NET_A/NET_B"` names a pair:
- In the routing copy only, placemat renames the two nets
  `PMPAIR<i>_P`/`PMPAIR<i>_N` and passes that pattern to the pair router.
- It renames them back in the routed copy before its copper is taken.
- `pairs_of` (the crossing and score code's partner lookup) reads the same
  explicit pairs, so placement treats them as a pair too.
- A name in the entry that the board does not have is refused before
  routing.

## Waiting, and why

- **The current-path check following the load path**
  (PLACEMAT_GAPS 2026-09-29): the entry says the check measured the input
  tab to an input capacitor, while the load leaves through the tab's leads
  into the whole test board's pour. The input module's only `Pm.I` carriers are its two
  tabs, so which pair the check judged there is not yet traced. That trace
  comes first; a form for the script to name a path waits on what it shows.
- **Reference arithmetic, or a 45-degree lane off a pad's corner**
  (2026-09-29): a comb of parallel 45s each a clearance off the next pad's
  corner. It needs a form chosen with the owner (`Diagonal(ref,
  clearance)` against arithmetic on `X`/`Y`), and arithmetic reopens the
  coordinates the intent work closed.
- **A plug on another board against a receptacle here** (2026-09-27): nets
  across two board files. It needs its own spec.
- **A zone fill's width along a load's route**: a raster and a widest-path
  search. It needs its own spec.
- **`placemat impact` between a run and a KiCad file**; **a finding when a
  3D model's box misses the pads** (it needs the STEP file's extents); **the
  fragment each stamped part came from** (the generator's log, not the
  board): each is a read-side addition, done after these.

## Verification

- TDD per item:
  - a rider on a searched part, including one that cannot fit and a rider
    of a rider;
  - `Inside` on a two-column part and on a four-side ring, turned and on
    the back;
  - `land=` by `LARGEST` and by index, for a track end and a via;
  - an explicit pair renamed, routed and restored, with an unknown name
    refused.
- Digest parity tests unchanged.
- The full suite, a release, then the bench (riders are a placement change).
