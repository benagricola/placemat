# Stitching vias outside a region's edge, and points in a datasheet figure

Status: approved (2026-10-01).

Source: the owner, through a board's session (2026-10-01): two chip antennas'
datasheet layouts.

## Part 1: stitching vias outside a region's edge

### Problem

An antenna's datasheet asks for ground vias outside its ground clearance:
holes 0.35 mm off the clearance's edge, at most 2 mm apart, along two named
sides. `board.stitch(net, region, edge=True)` rows vias along the region's
own outline, a via's clearance INSIDE it. A script says the outside row as
seven computed `Location` vias.

### Design

`board.stitch(net, region, edge=True, outside=True, hole_to_edge=, pitch=,
sides=)`:

- `outside=True` puts the row outside the region: each via's hole edge
  `hole_to_edge` mm off the region's edge (the via's centre `hole_to_edge`
  plus half its drill out along the edge's outward normal). Default
  `hole_to_edge`: the via's own clearance from the region (half its size,
  so its copper touches the edge from outside).
- `pitch=` is the most the vias stand apart along each edge: a side `L` long
  gets `ceil(L / pitch) + 1` vias, evenly spread from end to end, so no gap
  exceeds `pitch` (the datasheet's "at most"). Without `outside=`, `pitch`
  keeps today's meaning.
- `sides=[Edge.EAST, Edge.SOUTH]` keeps only the region's edges whose
  outward normal faces those sides as the region is turned (a keepout
  placed with `rotation=Turned(part, 0)` reads its sides in the part's
  frame); an edge counts for the side its normal is nearest, within 45
  degrees. Default: every edge.
- At a corner between two kept sides, one via stands at the corner's
  outside, shared by both rows.
- Each via is judged as a stitching via is today (clear of other nets'
  copper, holes, keepouts, the board edge); one that cannot stand is left
  out and named in the step's note, and a row left with a gap over `pitch`
  is a finding naming the side and the gap.
- `outside=True` without `edge=True` is refused.

```python
board.stitch(Net("GND"), "antenna clearance", edge=True, outside=True, hole_to_edge=0.35,
             pitch=2.0, sides=[Edge.EAST, Edge.SOUTH], why="the datasheet's vias outside the clearance")
```

### Verification

- A rectangular keepout, `outside=True, hole_to_edge=0.35, pitch=2.0,
  sides=[Edge.EAST, Edge.SOUTH]`: holes 0.35 off the two sides, none on the
  others, no gap over 2.0, one shared corner via.
- The keepout turned with a part (90 degrees): `sides` read in its frame.
- A via blocked by another net's pad: left out, named; the gap over `pitch`
  a finding.
- `outside=True` alone: refused.
- KiCad's DRC on the written board: no clearance or hole violation.

## Part 2: points in a datasheet figure's frame

### Problem

An antenna's datasheet dimensions its whole pattern from one origin (the
chip's centre). A keepout already takes the figure: `Path(FIGURE,
anchor=...)` placed `at=Mid(PadRef(ant, 1), PadRef(ant, 4))` with
`rotation=Turned(ant, 0)`. But the feed pad's position, a back-face strip's
ends and its three vias at 0.9, 1.9 and 2.9 mm are points in that same
figure, and have no form; they stay as computed coordinates.

### Design

`fig = board.figure(at=, rotation=, anchor=(0, 0))` is a datasheet figure's
frame on the board: its point `anchor` (in the figure's own coordinates)
lands on `at` (any point: a pad, a `Mid`, an origin), turned by `rotation`
(a number or `Turned(part, degrees)`) as a keepout's `Path` is. It places
nothing.

`fig.point(x, y)` is the figure's point (x, y), in the datasheet's own
coordinates and units (mm), as a point reference: a `Pin` target, a track,
finger or via point, `Polar(about=)`, `X()`/`Y()`, `Mid`. It resolves when
`at` and the rotation's part do.

`board.keepout(Path(FIGURE, anchor=A), name, at=fig.at, rotation=fig.rotation)`
stays as it is; `board.keepout(Path(FIGURE), name, frame=fig)` places the
path in the figure's frame directly (its points read as the figure's, no
box-centre move), so the keepout and the points share one frame by
construction.

```python
fig = board.figure(at=Mid(PadRef(Part("ant"), 1), PadRef(Part("ant"), 4)), rotation=Turned(Part("ant"), 0))
board.keepout(Path(CLEARANCE), "antenna clearance", frame=fig, why="datasheet p7")
board.place(Part("c_match"), at=Pin(1, fig.point(-2.1, 3.4)), rotation=Turned(Part("ant"), 90), why="...")
for y in (0.9, 1.9, 2.9):
    board.via(Net("GND"), at=fig.point(4.2, y), why="datasheet p7: the strip's vias")
```

### Verification

- A figure at a pad, unturned: `fig.point(x, y)` is the pad plus (x, y).
- At a `Mid`, turned with a part at 90 and 180 degrees, and on the back
  face: points turn and mirror as the part's frame does, matching a
  `Path` keepout placed the old way.
- `keepout(..., frame=fig)` and the old `Path(anchor=)` form give the same
  polygon.
- As a `Pin` target, a track point, a via `at=` and `Polar(about=)`.
- Digest parity: a script without these forms digests as before.
