# Cutouts a script places, and the material left around them

Date: 2026-09-17
Status: design, awaiting approval

## What is wrong today

A cutout is a literal path of absolute coordinates:

```python
board.disc(diameter=40.0, hole=6.0, holes=[slot((14.0, 28.0), (26.5, 28.0), 3.0)])
```

Three things follow from that, and all three are wrong for the same reason -
the script is holding numbers the tool should be working out.

1. **The position is typed, not derived.** A slot that exists so a cable can
   reach a connector has no relationship to that connector in the script. Move
   the connector and the slot stays where it was, silently.
2. **The position cannot flex.** Every other placement in placemat can be left
   a degree of freedom and settled against what is actually on the board. A
   cutout cannot, so it takes its space whether or not that space was the
   right space.
3. **Nothing holds the board together.** There is no way to say how much
   material must remain between a cutout and the board edge, or between two
   cutouts. A slot placed too near the rim of a round board leaves a sliver
   that snaps in depanelling or in the hand, and the tool has no opinion.

Separately, a cutout's boundary cannot be placed against. `board.edge(facing=)`
reads the board's own outline only, so there is no way to put a part against
the edge of a slot.

This design fixes all four together. They are one change: a cutout that can be
placed needs somewhere legal to go, legality needs the web, and a boundary
worth placing against is a boundary the tool resolved rather than one the
script typed.

## Vocabulary

### Shapes

A shape is a closed outline anchored at its own centre, with no position of
its own.

| shape | meaning |
|---|---|
| `Slot(length, width)` | a rounded-end slot, `length` measured **tip to tip**, running along +X before rotation |
| `Circle(diameter)` | a round hole |
| `Path(points)` | any closed path of points and `Arc(to=, via=)` |

A shape's anchor is the centre of its bounding box, and that is the point
`at=` places. For `Slot` and `Circle` that is also their geometric centre. A
`Path` is declared in whatever coordinates suit it and is translated so its
box centre lands on the anchor, so the same `Path` constant can be placed
twice in different spots.

`Slot(length, width)` requires `length >= width`; equal is a circle and is
accepted as one. Tip to tip is what a mechanical drawing dimensions and what
callipers measure: a 12.5 mm cable wants `Slot(13.0, 3.0)`, not a 13 mm centre
line. This differs from the existing `slot(start, end, width)` function, whose
arguments are the ends of the **centre line** - that form reads naturally when
you are saying where a cable runs, and it stays. `Slot(l, w)` is exactly
`slot((-(l - w) / 2, 0), ((l - w) / 2, 0), w)`.

### A cutout

```python
Cutout(shape, name, at=, rotation=None, why="")
```

`name` is unique on the board and is how the script refers to the cutout
later. `why` follows the script standard: every cutout exists for a reason and
the reason belongs beside it. `at=` is required - a hole with no declared
position is not something anyone means.

### The web

`board.web` is the least material that may remain between a cutout and the
board outline, or between two cutouts. It is a mechanical number, not an
electrical one: `board.keep_in` is copper-to-edge and says where a part may
sit, `board.web` is material-to-material and says where a hole may sit.

The word `neck` is already taken - `checks.py:167` `neck_mm` is a pour's
narrowest section, used to size copper against its current. `web` is the fab
term for what is left between two cut features and does not collide.

```python
board.web = 1.5              # or board.size(..., web=1.5) / board.disc(..., web=1.5)
```

The default is 0.0, which means unchecked: a board that never says `web` keeps
exactly today's behaviour.

## Declaring a cutout

```python
FFC = Cutout(Slot(13.0, 3.0), "ffc",
             at=Centre(X(Part("j_ffc")), Y(Part("j_ffc"), 4.0)),
             why="the FFC cable passes through to the panel behind")

VENT = Cutout(Slot(8.0, 2.0), "vent",
              at=Polar(14.0, Fraction(0.5)),
              why="airflow past the regulator")

board.disc(diameter=40.0, hole=6.0, web=1.5, holes=[FFC, VENT])
```

`holes=` keeps accepting a raw path, which means "this is already absolute,
place nothing". Both forms coexist and are told apart by type. Nothing built
so far breaks.

### Where a cutout may go

`at=` takes the same places a part does, with the same meaning:

| place | for a cutout |
|---|---|
| `Location(x, y)` | its centre, at that point |
| `Centre(x, y)` | its centre, each axis a number, a reference, or `None` for one freedom |
| `Polar(radius, bearing)` | its centre at that bearing and radius from `board.centre`; either may be `None` |
| `OnEdge(edge, along=)` | its nearest boundary held at `board.web` from that edge |
| `Near(location)` | searched round a hint |

A cutout with every axis decided is firm. A cutout with one axis left `None`
is searched within its phase, sliding the way a part does - along the line,
round the ring, along the run - using the existing `_slide` machinery.

### Rotation

`rotation=` is a bearing. Omitted, it is implied by the place:

- `Polar`, `OnEdge` and any place that carries a direction: **tangential** -
  the slot's length runs along the edge or around the circle. A vent follows
  the rim; a cable slot runs parallel to the connector it serves.
- `Location`, `Centre`, `Near`: 0, the shape as declared.

A `Circle` given a `rotation` is refused rather than silently ignored.

This tangential default is a judgement call. Radial is the other defensible
reading, and a script that wants it says `rotation=` with the bearing.

## Reaching a cutout's boundary

```python
ffc = board.cutout("ffc")
board.place(J, at=OnEdge(ffc.edge(side=Edge.NORTH), along=Along.MID))
board.row([TP1, TP2], ffc.edge(side=Edge.SOUTH))
```

`board.cutout(name)` is the only route to a cutout's runs. `board.edge()` and
`board.edges()` keep reading `loops[0]` and can never return one, so a script
asking for the board's edge cannot be handed a cutout's by accident. That is
structural; there is no flag to forget.

The handle's surface mirrors the board: `.edge(side=, within=45.0)`,
`.edges(side=, within=45.0)`, `.box`, `.centre`, `.area`, `.name`. Several
stretches facing one way raises from `.edge()` and comes back as a list from
`.edges()`, in the same words the board uses.

### `side=`, and why it is not `facing=`

A hole loop winds opposite to the board's, and a run's normal is taken from
its own loop's winding. Walking a hole loop with the sign flipped gives
normals that point **into** the cutout, which is what `run_placement` consumes
and what `OnBore` already does.

The consequence is a trap. On the board the two readings coincide:
`facing=Edge.NORTH` is the top edge *and* the item faces north. On a cutout
they invert - an item against a slot's northern boundary faces **south**, into
the slot. `facing=Edge.NORTH` on a cutout would therefore hand back its
*bottom* boundary: correct by the `Run.facing` invariant, and almost never
what anyone meant.

So a cutout takes `side=` and does not accept `facing=`. `side=Edge.NORTH` is
the northern boundary of the hole, which is how you think about a hole you are
placing around, and it matches `OnBore(Edge.NORTH)` meaning north of the bore.
`run.facing` keeps its one meaning everywhere - the bearing the item's outward
side points - so `OnEdge` and `row` work unchanged.

The cost is one inconsistency to document: you place *inside* a board and
*around* a cutout, so the board takes `facing=` and a cutout takes `side=`.
This must be stated in `SKILL.md` and in `references/api.md`. The CLI carries
no script-API documentation, only command help, so nothing goes there.

## Resolution order

Board geometry must be settled before parts are searched, because `why_not`
consults it. A cutout placed relative to a part needs that part's position
first. `PlaceIntent.needs` already resolves exactly this tension for parts and
cutouts join that queue rather than getting a phase of their own.

A cutout becomes a third kind of firm intent, ranked in the FIXED/EDGE band.
`place_ranked(RANK_FIXED, RANK_EDGE)` already walks its firm items in
dependency order, placing whichever has its `needs` satisfied and raising when
none does:

> `ffc is placed relative to j_ffc, which is not placed by then (only FIXED and EDGE items may be referred to)`

That gives, with no new machinery:

- a cutout may refer to any item whose position is decided, and to a cutout
  declared before it;
- a part may be placed against a cutout's edge, and waits for that cutout;
- a cutout referring to a searched part is refused, naming it;
- a cycle - a cutout that needs a part that needs that cutout - is refused by
  the same check, because neither ever becomes ready.

Searched cutouts fall into the same band's `pending` loop, which runs after
every firm item and before any searched part. So by the time the first part is
searched, every hole is in the board.

### The board shape grows as cutouts land

`Occupancy.board_shape` is built once today. Placing a cutout must add it, so
that every later legality test sees it. `Disc` and `Outline` are frozen
dataclasses, so each placed cutout replaces the shape with a new value
carrying the extra hole (`dataclasses.replace`), and the rectangle's
`board_cutouts` is replaced the same way. Immutability is kept; the spatial
index is rebuilt per cutout, which happens a handful of times per run, not per
probe.

## Legality of a placed cutout

A cutout may sit at a candidate position when all of these hold:

1. it lies wholly inside the board outline, and strictly so - a cutout that
   touches or crosses the outline is not a hole but a notch, which changes the
   board's shape rather than putting a hole in it, and belongs in the outline
   path. That is refused whatever `web` is set to;
2. no part of it is nearer than `board.web` to the board outline;
3. no part of it is nearer than `board.web` to another cutout;
4. it does not overlap the reach (body, pads, silk) of any placed item.

Courtyard overlap is allowed: a courtyard is assembly clearance, not material.
Rule 4 catches the real error, which is milling a hole through a part.

Rules 2 and 3 are measured as the shortest distance between boundaries. For a
cutout inside a board that distance is the local web, so no medial-axis work is
needed; `point_segment` in `cutouts.py` already does the arithmetic.

A cutout that finds no legal position stops the run the way an unplaceable
HIGH item does, with the free rectangles on its face and the board written as
it stood.

## The web check

A `Verdict` in the existing `checks.py` shape:

```
web   ffc   1.12 mm   need 1.50   FAIL   narrowest between the ffc slot and the rim
```

It reports the narrowest web on the board and the pair it occurs between,
whether the cutout was placed or given as an absolute path. A script that
asserted a position gets a finding; a placed cutout never reaches a failing
position in the first place.

`board.web` of 0.0 skips the check entirely.

## What changes, file by file

| file | change |
|---|---|
| `cutouts.py` | `Slot`, `Circle`, `Path` shapes; `path_at(centre, rotation)`; loop-to-loop minimum distance |
| `outline.py` | `runs()` takes a loop selector and negates the sign for a hole loop |
| `values.py` | `Cutout` value; `Disc` unchanged beyond already carrying `holes` |
| `layout.py` | `CutoutIntent` in the firm queue; `board.cutout(name)` handle; `web` on `size()`/`disc()`/`outline()`; deferred `CutoutEdge` reference |
| `occupancy.py` | shape replacement as cutouts land; rule 4 |
| `checks.py` | the web verdict |
| `kicad/write.py` | unchanged - it already draws whatever paths the shape carries |
| `placer.py` | `run_placement` unchanged; a searched cutout needs its own legality probe |

`run_placement` is shape-agnostic - it walks back along a run's normal until
`shape.why_not` clears - so a part placed against a cutout's edge needs
nothing new. A *searched cutout* is the one addition: it has no footprint, so
it cannot reuse `box_centered_placement`, and instead needs a small probe that
builds its path at a candidate centre and applies the four legality rules.
That probe is simpler than a part's, because there is no rotation-dependent
geometry to look up.

That `kicad/write.py` needs nothing at all is the check on this design: the
writer already draws whatever paths the shape carries, so if it had to change,
the abstraction would be in the wrong place.

## Errors

Each of these is a sentence naming what to do instead, never an exception from
inside the placer:

- a cutout name that is not declared, listing the names that are;
- `facing=` passed to a cutout handle, pointing at `side=`;
- a `rotation` on a `Circle`;
- `Slot(length, width)` with `length < width`;
- a cutout referring to a searched item;
- a cutout with no legal position, saying whether the web, the board or a part
  was what stopped it;
- a cutout that touches or crosses the board outline, pointing at the outline
  path as where a notch belongs;
- `board.cutout(name)` on a board whose cutouts were declared as raw paths,
  saying that only a named `Cutout` can be referred to.

## Test plan

Developed test-first, each slice red before green. The slices are ordered so
that every one of them is independently demonstrable.

1. **Shapes.** `Slot`, `Circle`, `Path` produce the right area, the right
   tip-to-tip length, and the right path under rotation. `Slot(l, w)` equals
   the existing `slot()` form for the same geometry.
2. **Cutout runs.** A hole loop walked with a flipped sign yields normals
   pointing into the hole. `side=Edge.NORTH` returns the northern boundary.
   `facing=` is refused. `within=` narrows a stretch off the end caps.
3. **Placing against a cutout.** `OnEdge(ffc.edge(side=), along=)` holds a part
   at `keep_in` from the slot, on the material side, turned to face into it, on
   a rectangle, a disc and a shaped board. `board.edge()` never returns a
   cutout run, on a board with several cutouts.
4. **The web.** Loop-to-loop minimum distance on known geometry. The verdict
   passes, fails, and names the pair. `web=0.0` skips it. A cutout touching
   the outline is refused even with `web=0.0`.
5. **Placed cutouts, decided.** `at=Location`, `at=Centre` with references,
   `at=Polar`. The resulting path is where the numbers say. A cutout that
   would break the web is refused with the web named.
6. **Placed cutouts, searched.** One freedom slides to where there is room.
   A cutout with nowhere legal stops the run readably.
7. **Ordering.** A cutout that needs a FIXED part waits for it. A part placed
   against a cutout waits for the cutout. A cutout needing a searched part is
   refused. A cycle is refused.
8. **The whole thing.** A round board with a bore, an FFC slot derived from a
   connector's position, and a vent on a ring: DRC clean, Edge.Cuts carries
   real arcs, the web verdict passes, and the run is reproducible.

## Out of scope

- **The bore as a cutout.** Folding `Disc.hole` into the named-cutout
  mechanism would unify `OnBore` with cutout edges. It is a tidy follow-up and
  it is not needed for any of the above.
- **Cutouts searched after the parts.** A cutout cannot settle against parts
  placed later, because those parts were placed against a board that did not
  yet have the hole. Lifting this needs a second placement pass and is a
  separate piece of work.
- **Web between a cutout and a plated feature.** Copper-to-edge is already
  DRC's job.

## Migration

Every form that works today keeps working. `holes=[path]` stays absolute and
unplaced; `board.edge(facing=)` is untouched; `board.web` defaults to 0.0 so no
existing board gains a check it did not ask for. The only behaviour any current
script could notice is the new web verdict, and only if it sets `web`.
