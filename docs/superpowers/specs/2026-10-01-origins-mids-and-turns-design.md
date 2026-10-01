# Origins, a part's own pad midpoint, and turns said by pads

Status: approved (2026-10-01).

Source: the owner, through a board's session (2026-10-01): an inductive ring
sensor cell (two windings drawn about a disc centre, two LC tanks, a
four-channel inductance-to-digital converter).

## Problem

Four things the cell says today with numbers or asserts:

1. The two windings are drawn about the disc's centre, which is each
   footprint's origin and not a pad. A part has no way to stand its origin
   on another part's origin: cells take `Pin(Part(member), x, y)` for a
   member's origin, but a point that *is* another part's origin does not
   exist (`X(Part(...))` is its body centre).
2. The converter's coil inputs are two pins; their midpoint should sit on
   a line through the windings' terminals. `Pin(key, ...)` and `Beside`'s
   `align=(own_pad, ...)` take one pad, not the midpoint of two of the
   part's own pads. `Pin`'s key cannot name one land of a pin drawn as
   several.
3. Each tank should lie parallel to its winding's terminal pair, 3.96
   degrees off the axes, standing off along that line's normal. Rotations
   are numbers or `Turned(part, degrees)`; nothing turns a part parallel
   to a line through two pads. Separately, a pad-to-pad track whose pitches
   differ by 0.001 mm gets a 1 um jog, which `measure --copper` flags as off
   0/45/90 (KiCad does not).
4. A part's turn is chosen so named pads face a side; today it is a
   constant, checked by an assert on pad positions after the fact.

## Design

### 1. `Origin(item)`: a part's footprint origin as a point

`Origin(Part(...))` is that part's footprint origin as placed (a cell's:
its frame origin), a point reference wherever a point is taken: `at=`,
`X()`/`Y()`, `Mid`, `Polar(about=)`, `Pin(key, point)`. A part placed
`at=Origin(Part("l_ring0"))` stands its own origin there (as `at=Location`
does), and waits for that part.

```python
board.place(Part("l_ring1"), at=Origin(Part("l_ring0")), rotation=Turned(Part("l_ring0"), 0))
```

### 2. A part's own pad midpoint as its anchor; a land in `Pin`

`Pin(Mid(10, 11), x, y)` (or one point) puts the midpoint of the part's own
pads 10 and 11 on the point; `Beside(item, side, align=(Mid(10, 11), ...))`
lines that midpoint up as an own pad is today. Keys are as `Pin` takes them
(number, net, `PinName`). `Pin(key, ..., land=)` names one land of a pin
drawn as several (`Land.LARGEST` or its index), as `PadRef(land=)` does.

```python
board.place(Part("ldc"), at=Beside(Part("tank0"), Edge.SOUTH,
                                   align=(Mid(10, 11), X(Mid(PadRef(Part("l_ring0"), "B"),
                                                             PadRef(Part("l_ring1"), "A"))))),
            rotation=..., why="the coil inputs centred between the windings' terminals")
```

### 3. Turns and bearings said by two pads; sub-micron legs

- `rotation=Parallel(a, b, degrees=0)`: the part turned so its own x axis
  (its footprint's 0 degree axis) lies along the line from point `a` to
  point `b` (pads, origins, any point reference), plus `degrees`. Any
  angle, not only the right angles; it waits for both points.
- `Bearing(a, b, degrees=0)`: the compass bearing of the line from `a` to
  `b`, plus `degrees`, usable as `Polar`'s bearing. `Polar(gap, Bearing(a,
  b, 90), about=PadRef(...))` is a point `gap` off a pad along the line's
  normal.

```python
line = (PadRef(Part("l_ring0"), "A"), PadRef(Part("l_ring0"), "B"))
board.place(Part("c_tank0"), at=Pin(1, Polar(TANK_GAP, Bearing(*line, 90), about=line[0])),
            rotation=Parallel(*line), why="the tank parallel to its winding's terminals, off along the normal")
```

`Beside` stays on the board's axes; a stand off along a turned line is said
with `Polar` and `Bearing` from a pad, as above. (Beside on a turned line
is not proposed.)

- A track leg whose ends differ by less than `copper.straight_tolerance`
  (a new setting, default 0.002 mm) on one axis is drawn straight between
  them, not as a straight plus a sub-micron jog; `measure --copper` judges
  0/45/90 with the same tolerance.

### 4. `Facing`: a turn chosen by a pad facing a side

`rotation=Facing(PadRef(Part("ldc"), 9), Edge.NORTH)` turns the part (of
its four right-angle turns) so that pad's way out (its row's outward axis,
as fanouts and escapes read it) points at `Edge.NORTH`. A list of pads
(`Facing([pads...], edge)`) means their row. Refused where no right-angle
turn does it (a pad whose way out is ambiguous, a corner pad, pads of two
rows), naming the pads; on the back face, the turn is the one that faces
the side as seen from the front.

## Verification

- `at=Origin(Part(a))` puts the part's origin on `a`'s; `X(Origin(...))`
  reads the origin, not the body centre; a cell's origin.
- `Pin(Mid(10, 11), x, y)`: the midpoint of the two pads lands on the point
  at any turn and face; in `Beside`'s align; `Pin(key, ..., land=2)`.
- `Parallel(a, b)`: a part turned 3.96 degrees when the line is; with
  `degrees=90`; on the back face.
- `Bearing(a, b, 90)` in `Polar`: the point lies on the normal, `gap` off.
- A pad-to-pad track 0.001 mm off axis is one straight segment; `measure
  --copper` does not flag it; one 0.01 mm off still takes its jog.
- `Facing(pad, Edge.NORTH)` on each of a QFN's four sides; a list of pads;
  refused for a corner pad; on the back face.
- Digest parity: a script without these forms digests as before; the bench
  unchanged.
