# The read surface: what placemat already knows, said out loud

Date: 2026-09-22
Status: design, awaiting approval

Nine entries in `PLACEMAT_GAPS.md` are the same entry: an agent needed a number
about a part or a pad, placemat could not say it, and the answer was got by
grepping a `.kicad_mod` or loading pcbnew in a scratch script. Every one of
those numbers is already in `BoardGeometry`. None of them is printed.

## What is missing today

`cmd_measure` (`cli.py:216-228`) is the whole geometry surface:

```python
console.say("measure", "part %-16s %s  %.3f x %.3f  pads %s" % (
    fp.inst, fp.ref, fp.body_box.width, fp.body_box.height,
    " ".join("%s:%s" % (p.number, p.net) for p in fp.pads)))
```

An instance, a refdes, a body size, and pad number to net. No position, no
rotation, no face, no pad geometry, no courtyard, no value. There is no `parts`
listing, so naming a part requires already knowing its name - which is circular
when the question is "what are the parts called". And nothing reads a
footprint that is not on a board, so a part cannot be measured before it is
placed.

The nine entries, and what each actually needed:

| entry | needed | where it is today |
|---|---|---|
| 2026-09-19 USB-C receptacle | how far its copper reaches from the origin | `Box.union(pad outlines)` |
| 2026-09-19 port on the placed board | position, rotation, copper's distance to the board edge | placement + a board polygon placemat does not read |
| 2026-09-19 FFC hold-down tabs | are pads 11 and 12 real pads, and how big | `fp.pads` |
| 2026-09-20 Keystone terminals | do the two legs share a pad number | `fp.pads` |
| 2026-09-20 display fan, USB pair | placed pad centres and boxes | `PadGeom.box` after placement |
| 2026-09-20 board read back as a table | pads, vias and tracks per part in the board frame | `BoardGeometry.copper` |
| 2026-09-20 footprint pad identity | each pad's net and true copper box | `outlines_of` |
| 2026-09-21 unplaced envelopes | pads, body, courtyard with no board | nothing reads a bare `.kicad_mod` |
| 2026-09-21 WROOM comparison | the same, for a library footprint | nothing |

**The numbers are already right.** Two checks worth recording, because they are
the two the gaps file says are hard:

The TPS55288's four custom corner pads report `GetSize()` as `0.005 x 0.005` -
the anchor the gaps file warns "lies for a custom pad" - and placemat's
`outlines_of` returns their real copper box, `0.920 x 0.720`. The correction the
entry asks for is already made; it is simply never printed.

And entry 1's answer, derived by hand from greps over `(pad`, `(size`, `(drill`
and `(at` plus rotation arithmetic - "copper edge 2.43 in front of the origin
along the board once the part is rotated 90" - is
`Box.union(pad outlines).right == 2.43` on that footprint, read in one call.

## What this adds

### `placemat measure` becomes the geometry query

```
placemat measure <pcb | script | footprint.kicad_mod> [item ...] [--pads] [--json]
```

Without `--pads`, one block per item: instance, refdes, value, face, rotation,
origin, and three boxes named for the fields they come from - `body`
(`Footprint.body_box`, the courtyard deflated by the fab's excess and unioned
with the pads), `courtyard` (`courtyard_box`, what the part claims for
assembly) and `physical` (`phys_box`, pads and drawn graphics with the
courtyard excluded). Three, not one, because they answer different questions
and the gaps file uses all three. With `--pads`, each pad's
number, net, layers, through-ness and drill, its centre in the board frame, and
its **effective copper box** - the box round `outlines_of`, not the anchor
`size`, because for a custom pad the anchor is not the copper.

```
part  usbconnector.j_usb   U36   TYPE-C-31-M-15
  face front  rotation 90  origin (25.50, 68.10)
  body 8.70 x 3.00   courtyard 8.95 x 4.86   physical 8.86 x 4.86
  nearest board edge: copper 2.35 mm, courtyard 1.05 mm
  pad  A1   GND      F.Cu/B.Cu  through  drill 0.50   at (21.45, 66.17)  0.70 x 0.30
  pad  A4   VBUS     F.Cu/B.Cu  through  drill 0.50   at (22.15, 66.17)  0.70 x 0.30
  copper on its pads: 4 tracks, 2 vias
```

`measure` with no items keeps listing the board's cells, as it does now.

### `placemat parts` answers "what are the parts called"

```
placemat parts <pcb | script> [--json]
```

One line per footprint: instance path, refdes, face, value, cell, courtyard
area, pin count and pad nets. Area and pins are there because they are what the
placement rank is computed from, so the listing also explains the order things
went down in.

```
instance                 ref   face   cell      mm2   pins  value
logic.mcu                U18   front  logic    56.0     57  ESP32-S3R8
usbconverter.l_vbus      U37   back   usbconv  31.5      2  4.7uH
```

### A footprint with no board

`measure` given a path ending `.kicad_mod` loads it with
`pcbnew.FootprintLoad(dir, name)` - verified to work with no board at all - and
prints the same blocks in the footprint's own frame, plus the file's SHA-256, so
two variants of a part can be told apart. That is what the WROOM comparison
needed.

**Layers are reported differently with no board**, and this is not cosmetic. An
empty board has all 32 copper layers enabled, so a through-hole pad read
standalone reports `In1.Cu` through `In30.Cu` - true of the empty board and
false of any real one. A standalone pad therefore reports its **attribute** -
`through`, `smd front`, `smd back`, `npth` - and never a layer list. On a
placed board the layer list comes from that board's own stackup and is printed.

### The board's real outline

`BoardGeometry` gains `board_polygon: tuple[Polygon, ...]` - the outline first,
then its holes - read with `GetBoardPolygonOutlines(ps, False)`. Measured: 8
points for the Breakout, 191 points and one hole for the fairing disc.

`BoardGeometry.outline` is **left exactly as it is**. It holds one bounding box
per Edge.Cuts drawing, which is wrong for a disc but is what `outline_box` and
every placement path already consume; replacing it is a separate change with
its own blast radius.

**Distance to the edge is to the boundary, not into the interior.**
`poly_distance` returns 0 for two polygons that overlap, and every pad on a
board overlaps the board outline, so it would report 0 for all of them. The
measure is the shortest distance from any pad point to any outline *segment*:

```python
def distance_to_boundary(poly, boundary) -> float:
    return min(point_segment_distance(p, a, b)
               for p in poly for a, b in _edges(boundary))
```

taken over the outline and every hole, since a cutout edge is a board edge.

### Copper that belongs to a part

With `--pads`, `measure` also counts the tracks and vias whose copper touches
that part's pads, from `BoardGeometry.copper`. "What is at this coordinate" and
"where may a via go" are not here: they belong with the occupancy work, where
the obstacle machinery already lives.

### `--json`

Every command takes it, and prints the same content as a document rather than a
table. This is the form a review script consumes, and the reason those scripts
currently reach for pcbnew.

## What this does NOT do

**A symbol's pin name.** Entry 2026-09-20 wants "pad 13 of `vbus_conv` is ISN".
It is not reachable: `pinfunction` appears zero times in the generated board,
and the netlist beside it writes every pin's name as its own number
(`(pin (num "13") (name "13"))`). placemat can say pad 13 carries net `VBUS`;
naming it ISN is the datasheet's job and the reader's. The spec says so rather
than implying otherwise.

**Point and region queries**, `board.free_spot`, and the island report. Those
are the occupancy work.

**The interface export.** A machine-readable anchor file for the enclosure is a
consumer of this surface, not part of it.

**Replacing `BoardGeometry.outline`.** Noted above.

## Errors

- `measure` on a name that is neither a cell nor a part: the existing
  `KeyError` gains the nearest few names, because the usual cause is not
  knowing what the parts are called - and `placemat parts` is now the answer.
- `measure` on a `.kicad_mod` that pcbnew will not load: the path and what
  pcbnew said.
- `parts` on a board with no footprints: one line saying so, not an empty
  table. A part that belongs to no cell prints `-` in that column rather than
  a blank, so the columns stay readable.

## Test plan

Without KiCad, over synthetic geometry:

1. a part block carries instance, refdes, value, face, rotation, origin and the
   body, courtyard and physical boxes, each equal to the `Footprint` field it
   is named for;
2. `--pads` prints each pad's number, net, centre and copper box;
3. a pad whose anchor size differs from its outline reports the OUTLINE box;
4. `parts` lists every footprint with its cell, courtyard area and pin count;
5. pin count in the listing matches `ranking.pin_count`, so the listing and the
   placement order cannot disagree;
6. `distance_to_boundary` returns the distance to the edge, not 0, for a
   polygon inside another;
7. it takes the nearest of the outline and the holes;
8. `--json` round-trips to the same numbers as the table;
9. an unknown item name raises with the nearest names in the message.

With KiCad:

10. `FootprintLoad` reads a `.kicad_mod` with no board and reports its pads,
    body and courtyard;
11. a standalone pad reports an attribute and no layer list, and a placed one
    reports layers from the board's stackup;
12. the standalone block carries the file's SHA-256, and two different files
    give two different hashes;
13. `board_polygon` is 1 outline and 0 holes for a rectangular board, and more
    than one hundred points with a hole for a disc with a bore;
14. against the committed Breakout, a known part's measured pad centres equal
    `Occupancy.pad_location` for the same part - the two readers agree;
15. the TPS55288's custom corner pads report a copper box near 0.92 x 0.72 and
    not 0.005;
16. for a part the generator left at rotation 0 and a script places at
    rotation 0 on the front, `measure` on its `.kicad_mod` and `measure` on the
    placed board give the same pad offsets from the part's origin - the
    standalone reader and the board reader are the same reader.

## Documentation

- `api.md`, Commands: the new `measure` signature and `parts`, with an example
  of each.
- `api.md`, Questions: `board.part(...)` already answers much of this inside a
  script; a line saying `measure` and `parts` are the same answers from the
  command line, for when there is no script running.
- `SKILL.md`: before grepping a `.kicad_mod` or reaching for pcbnew, run
  `placemat parts` then `placemat measure <part> --pads`. This is the
  instruction that stops the habit the gaps file records nine times.
- `references/migration.md`: nothing to migrate; a `## To 0.10` note that the
  commands exist, because an agent that does not know will keep grepping.

## Migration

Purely additive. `measure`'s existing output for a cell is unchanged; its
part output gains lines. No script changes, no placement changes, no run-record
changes.
