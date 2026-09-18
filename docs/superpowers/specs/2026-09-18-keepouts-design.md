# A keepout: a region that forbids, declared like a cutout

Date: 2026-09-18
Status: design, awaiting approval

## What is missing today

A script cannot say "nothing goes here". There is no `board.keepout`, no
reservation and no rule area on the public surface.

The machinery is half built and unreachable. `Occupancy.reserve(box, why,
allow=, layer=)` at `occupancy.py:229` is a real placement keepout - it refuses
a part with `sits in the reservation for <why>` - but its only caller is
`_place_labels`, where a label reserves its own text box. For copper there is
nothing at all, and `write.py:265` hard-codes `z.SetIsRuleArea(False)`, so the
one KiCad primitive that does this job is switched off.

`SKILL.md` then tells an agent not to look for it:

> Keep a corridor open by not placing in it; reservations are for copper the
> script has not drawn yet, not for space you like.

The cost is visible on a real board. `fairing-instrument-pcb`'s front board
carries `plane_outline()`: twenty-five lines of trigonometry that walk a disc
rim at two degrees per chord to bite an antenna clearance out of the ground
plane, with a docstring explaining it has to be a notch rather than a hole
because `plane(outline=)` takes one polygon. That carve is repeated per plane,
nothing stops a part or a track landing in the region, and the clearance is a
number the script holds rather than one the tool holds. It is the same defect
the cutout work removed, in a different place.

## What a keepout is

Structurally it is a cutout that forbids instead of removing: a shape, a place,
a name, settled in the firm queue by `needs`, governing everything placed after
it. It reuses the vocabulary and the machinery the cutout work built.

```python
# the datasheet figure, in its own coordinates, anchored at the antenna's feed
ACAG0301_CLEARANCE = Path([...], anchor=(0.0, 0.0))

board.keepout(ACAG0301_CLEARANCE, "antenna",
              at=PadRef(Part("ant"), "ANT_FEED"),
              allow=(Part("ant"), Part("r_ant_series"), Part("c_ant_shunt1"),
                     Part("c_ant_shunt2"), Net("ANT_FEED")),
              why="ACAG0301 datasheet p1 Layout: copper-free on every layer")
```

Full signature:

```python
board.keepout(shape, name, *, at, rotation=None, excludes=None,
              allow=(), layers=None, why="")
```

It is its own verb, not an argument to the board declaration and not a value
threaded through one. A cutout lives in `holes=` because it *is* board shape; a
keepout is a rule about a region, so it reads like `board.rule()` and
`board.place()`, which are also verbs taking what they need. The thing worth
naming as a constant is the shape, which is reusable; the keepout itself is a
statement about one board.

`at=` takes what any placement takes, and `_locate` already resolves a `PadRef`
to where that pad now is, so anchoring a clearance on a real pad needs nothing
new.

### The shape

`Slot(length, width)`, `Circle(diameter)` and `Path(points)`, as for cutouts.
`Path` takes any closed polygon, concave included, with `Arc(to=, via=)` for
curved boundaries.

Verified against the real case: the ACAG0301 clearance transcribes to a
fourteen-vertex concave polygon with an arm down one side and a bite out of one
corner. `Cutouts` flattens it, `point_in_polygon` reads the bite as outside and
the arm as inside, and it rotates to any bearing. A separate C-shaped test
gives area 28.00 against an exact 28, and `polys_overlap` - the test the placer
will use - is correct for a part in the bite, on the arm and well clear.

Limits, which are real and should be documented: a `Path` is one closed loop,
so a keepout has no holes in it and two disjoint regions are two keepouts. A
self-intersecting path is undefined.

### The anchor

`anchor=` is the point in the shape's own coordinates that lands on `at=`. It
defaults to the bounding-box centre, which is right for a slot or a circle and
meaningless for a fourteen-vertex clearance whose box centre is in the middle
of nothing.

With it, a datasheet figure is transcribed in its own coordinates, anchored at
the feature the figure is organised around - for the ACAG0301, the antenna's
feed - and placed on the real pad. The clearance then follows the antenna
wherever the placer puts it, which is what a corridor declared in pad
references is for. Without it the script computes an offset into a polygon by
hand, which is the arithmetic this design exists to delete.

`anchor=` goes on the shared shape vocabulary, so cutouts gain it too.

### What it excludes

Default: parts, plane fill, tracks, vias and pads, on every copper layer the
board has. The antenna case needs no flags.

`excludes=` narrows it to any of five names, each one KiCad rule-area flag:

| name | flag |
|---|---|
| `"parts"` | `SetDoNotAllowFootprints` |
| `"fill"` | `SetDoNotAllowZoneFills` |
| `"tracks"` | `SetDoNotAllowTracks` |
| `"vias"` | `SetDoNotAllowVias` |
| `"pads"` | `SetDoNotAllowPads` |

`"parts"` is also what the placer enforces itself, before anything is written.

```python
board.keepout(Circle(6.0), "m3_head", at=Location(4.0, 4.0),
              excludes=("parts",), why="the screw head sweeps here")
```

### Layers

A keepout covers **every copper layer the board has**, whatever the count.
`LSET.AllCuMask(n)` is verified for 2, 6, 14 and 32 layers, so the writer asks
the board for its layer count and never enumerates.

This matters because `CopperLayer` has exactly four values (`F`, `IN1`, `IN2`,
`B`) and is therefore a hard four-layer ceiling everywhere else in placemat.
A keepout sidesteps it by not naming layers at all. The consequence, which is a
documented limit rather than something this work fixes: a keepout narrowed to
one named inner layer can only name `In1.Cu` or `In2.Cu`. Lifting the ceiling
is separate work that touches pads, tracks, planes and the reader.

### What may enter

`allow=` takes **parts and nets**, and they mean different things:

- a `Part` or `Cell` may sit inside the region;
- a `Net` may run through it.

Both are needed and neither substitutes for the other. The ACAG0301 figure puts
the antenna and its whole pi matching network inside the clearance, so the
parts must be named individually. `Reservation.allow` today is net names tested
as `geom.nets & r.allow`, so allowing `GND` in - which every one of those parts
carries - would let every decoupling capacitor on the board sit in the antenna
clearance.

## What it does, and what that costs

| target | mechanism | cost |
|---|---|---|
| parts | the existing `Reservation`, taking a polygon as well as a box | small |
| plane fill (`board.plane`) | KiCad rule area | none |
| router and DRC | the same rule area, on the written board | none |
| pours and fingers | a finding | small |
| tracks and vias the script drew | a finding | small |

`Reservation` gains a polygon beside its box; `legal()` becomes
`polys_overlap(r.poly, box_polygon(body))`, and `geometry.py` already has both.
The label reservation that is its only caller today keeps passing a box, which
`box_polygon` turns into the same thing, so nothing about labels changes.

**Plane fill is free, and this was verified.** A rule area with
`SetDoNotAllowZoneFills(True)` over a 12 x 12 corner of a 38 x 38 plane gives a
fill of exactly 1300 mm2 against 1444 whole. No polygon subtraction anywhere,
and `board.plane()` does not change.

**Pours are not governed, and this was also verified.** The same rule area over
the same region leaves a `SHAPE_T_POLY` pour at 1444 mm2, untouched. A `Pour`
is documented as keeping exactly the shape it is given, so it is reported
rather than silently reshaped:

```
pour GND on F.Cu crosses keepout 'antenna': a pour keeps exactly the shape it
is given, so move it, reshape it, or use board.plane(), which the keepout
clips for you
```

Tracks and vias the script drew are reported the same way, unless their net is
in `allow=`.

**The router and DRC come free.** `route.py` routes a copy of the written board
"under the board's own rules", so a rule area in the file is honoured by both
without placemat doing anything.

## Where it is settled

A keepout joins the intent queue beside the placements and the cutouts, ordered
by `needs`, exactly as a cutout is. A keepout placed from a part waits for that
part; anything placed afterwards is refused from the region. A keepout with a
freedom slides to where it fits, using the machinery cutouts already use.

### The filter must become positive

`Board._placements()` currently reads:

```python
return [i for i in self._intents if not isinstance(i, CutoutIntent)]
```

A `KeepoutIntent` would fall straight through that and reach the six places
that read what an item declared - which fellows share its rim, bore, ring,
edge, run or pinned axis - reintroducing the defect fixed in 0.4.18. The filter
becomes positive:

```python
return [i for i in self._intents if isinstance(i, PlaceIntent)]
```

so the next region type cannot bring it back.

## Errors

Each names what to use instead:

- a keepout whose `at=` refers to a searched item;
- a keepout with nowhere legal to go, saying what stopped it;
- `excludes=` naming something that is not one of the five;
- `allow=` given something that is neither a part, a cell nor a net;
- a keepout narrowed to a layer the board does not have;
- a `Path` that does not close, or has fewer than three points.

## Test plan

Test-first, each slice independently demonstrable.

1. **Anchor.** A shape with `anchor=` lands that point on `at=`; the default is
   still the box centre; cutouts get the same treatment and do not move.
2. **The region.** A concave `Path` is inside, outside and overlapping where it
   should be, at any rotation. The ACAG0301 clearance as a fixture.
3. **Parts.** A part in the region is refused, naming the keepout. A part in
   `allow=` sits there. A part outside is untouched. `excludes=("parts",)`
   forbids the part and nothing else.
4. **Planes.** A plane over a keepout writes a rule area and fills round it;
   the filled area matches the plane less the keepout. On a 2-layer and a
   6-layer board.
5. **Pours, tracks, vias.** Each crossing a keepout is a finding naming it; a
   net in `allow=` is not.
6. **Ordering.** A keepout placed from a fixed part waits for it; from a
   searched part it is refused; a free keepout slides. A keepout and a cutout
   and free placements coexist on one board - the 0.4.18 regression suite,
   extended.
7. **The whole thing.** The fairing front board's antenna: clearance placed
   from the antenna's feed pad, the matching network allowed inside, planes
   clipped on every layer, DRC clean, and `plane_outline()` deleted.

## Out of scope

- **Lifting the four-layer `CopperLayer` ceiling.** A keepout does not need it.
- **Clipping a `Pour`.** Reported, not reshaped, by decision.
- **Keepouts with holes, or disjoint keepouts.** One closed loop each.
- **Non-copper keepouts** (courtyard, silk). Nothing asks for them yet.

## Migration

Additive. No existing declaration changes, no board behaves differently until
it declares a keepout. The `SKILL.md` line telling agents that reservations are
"not for space you like" is replaced, because it is now wrong.
