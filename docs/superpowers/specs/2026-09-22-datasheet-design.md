# Reading a datasheet without deciding how

Date: 2026-09-22
Status: design, awaiting approval

An agent laying out a board needs four things from a datasheet: the recommended
land pattern, the package dimensions, the layout rules, and the pin map. Today
it invents a way to get them each time - extract the images and look, or
extract the text and guess what relates to what - and the way it picks is not
recorded, not repeatable, and usually wrong for the part that matters most.

This is the command that removes the decision.

## What the corpus actually contains

Measured over the 67 datasheets in `fairing-instrument/electronics/datasheets`,
because the design turns on what is really in these files rather than what a
PDF can hold in principle.

| fact | number |
|---|---|
| datasheets | 67 |
| with usable extractable text | 60 |
| text-poor (under 200 chars per page) | 7 |
| pages: median / p90 / max | 16 / 61 / 114 |
| under 12 pages | 31 (46%) |
| embedded raster images | essentially none |
| `tesseract` on this machine | installed (apt `tesseract-ocr` 5.3.4) |

**The 7 text-poor files are the connectors and the inductors.** The TYPE-C
receptacles used on the fairing board carry 0 to 55 characters of text between
them: every dimension is an outlined curve. These are exactly the parts whose
land pattern is most worth checking, so any design that depends on text
extraction fails where it is needed most.

**The geometry is there even when the text is not.** The TYPE-C 31-M-12 page
holds 5724 paths, 870 of them axis-aligned boxes, the largest equal-sized group
being 183 of 3 x 5 pt. That group is NOT the contact array: those boxes sit on
42 evenly spaced rows in the notes column and are glyph strokes in outlined
text. The signal is real but modest - it separates a page of drawing from a
page of prose, which is what the index needs - and it is not a pad finder.
What the drawing cannot supply on its own is scale: with no text there is no
dimension to anchor against, so the geometry gives topology and ratios, not
millimetres, and picking the pads out of 870 boxes is the open problem.

**Vendors do not share a vocabulary.** A keyword list matching "land pattern",
"recommended pad", "PCB layout" and five more finds a land pattern in 34 of 67.
The 26 misses that are not text-poor call it something else: the W3011 says
"MECHANICAL DRAWING" and "PWB Layout", Abracon says "MECHANICAL DIMENSIONS
(mm)" and "Layout", TI buries it in an appendix of mostly numbers. A fixed
keyword list is not a mechanism; it is one signal among several.

## The four channels

In the order the command tries them:

1. **Positioned text** - `mutool draw -F stext` gives every text run with a
   bounding box. This is not string matching: because each number carries
   coordinates, a dimension can be tied to the feature it labels by proximity,
   and a statement like `[ Unit : mm ]` or `Antenna keep out area (All Layer
   GND off)` comes out as a fact with a place on the page. Works on 60 of 67.
2. **Vector geometry** - `mutool draw -F trace` gives every path with
   coordinates. Present on all 67. Supplies pad count, topology and ratios;
   supplies millimetres only once something anchors the scale.
3. **Page render** - `pdftoppm -r 300`. Always works. This is what puts the
   drawing in front of a human or a vision-capable agent, and it is the reason
   the command is useful on a datasheet it cannot parse at all.
4. **OCR** - `tesseract` over the 300 dpi render, used when it is installed
   and skipped with a printed note when it is not. Outlined dimension text
   renders crisply, and measured on the TYPE-C 31-M-12 it recovers the
   dimension stack, the pin labels, `UNIT: mm`, `SCALE: 1:1` and the
   `RECOMMEND P.C.B LAYOUT` heading that moves that page's `land` from `fair`
   to `strong`. Two details decide whether it works: tesseract's TSV is
   word-level, so runs are grouped by its block/paragraph/line columns or a
   heading arrives in fragments, and each word carries a confidence that
   travels into the provenance. It reads wrong as well as right - 4.55 came
   back as 4.95 at confidence 78 against 86-96 for its correct neighbours - so
   a confidence floor removes noise but not every misread, and `check` against
   the real footprint is what catches the rest. Optional rather than required,
   because placemat depends on no service that must be installed for the
   ordinary path to work.

## The command

```
placemat datasheet <pdf>                           # the index: what is in it, and where
placemat datasheet <pdf> --show <page|topic> [--out DIR]
placemat datasheet <pdf> --read <topic> [--json]
placemat datasheet check <pdf> <footprint.kicad_mod> [overrides] [--json]
```

### The index

Ranks every page against the four topics and prints the ranking. Each row
carries the page, the topic, the score and **the evidence that produced it** -
the keyword that hit, the rectangle cluster, the numeric density - so a ranking
can be judged rather than trusted.

```
datasheet TDK-ANT016008LCS2442MA1  11 pages, text 41 KB
datasheet   p7   land pattern    strong   "RECOMMENDED LAND PATTERN", 32 rects, 11 dims, unit mm
datasheet   p6   package         strong   62 rects, 55 dims, unit mm
datasheet   p7   rules           fair     "Antenna keep out area (All Layer GND off)"
datasheet   p2   pins            weak     38 rects, no pin table found
datasheet   look: placemat datasheet <pdf> --show p7
```

A topic with no candidate says so on its own line rather than being absent,
because "placemat found nothing" and "placemat did not look" are different
facts and only one of them means go and read it yourself.

### `--show`

Renders the page to PNG at 300 dpi into the run's directory (or `--out`), and
prints the path plus the positioned text on that page. `--show land` resolves
the topic through the index and renders the best candidate; `--show p7` takes
the page directly. This is the whole of the user's ask on its own: the agent
stops choosing how to extract and just looks at the right page.

### `--read`

The facts the command could source, each with its provenance. **A value it
cannot source is absent, never guessed**: every number carries the page, the
bounding box and the text or path it came from, so a reader can check it
against the render in one step.

```
datasheet read land TDK-ANT016008LCS2442MA1
datasheet   unit        mm            p7 "[ Unit : mm ]"          bbox 344,571
datasheet   pads        2             p7 rectangle cluster        2 repeated 12 x 8 pt
datasheet   pitch       -             not sourced
datasheet   keepout     all layers    p7 "Antenna keep out area (All Layer GND off)"
```

### `check`

Compares a `.kicad_mod` against the datasheet and names every disagreement.
What `--read` sourced is used automatically; anything it could not source, or
got wrong, is supplied as a flag.

**An override is an anchor, not a retype.** For a drawing with no text, one
supplied dimension scales the recovered geometry: given `--pitch 0.5`, the
boxes picked out as the pad row become millimetres, and the pad size, span and
count follow without being typed. This is what makes the text-poor 7 tractable
rather than hopeless. Which boxes are the pad row is the open problem named
above: 870 of the TYPE-C page's paths are axis-aligned and the largest equal
group is outlined text, so the pads are found by their own regularity - equal
boxes on one line at one pitch - not by being the commonest shape.

```
placemat datasheet check TYPE_C_31_M_12.pdf TYPE-C-31-M-12.kicad_mod --pitch 0.5

check  scale     anchored on pitch 0.5 (supplied); 24 boxes on p1 -> mm
check  pitch     0.500 datasheet   0.500 footprint   ok
check  pad       0.30 x 1.30       0.30 x 1.30       ok
check  pads      24                26                MISMATCH (2 extra: A1B12, B1A12)
check  span      8.340             8.380             MISMATCH (+0.040)
check  2 of 4 checks disagree; --show p1 to look
```

## What this does NOT do

**Claim a number it cannot source.** The measurements above say plainly that
automatic extraction will miss often: half the corpus does not name its land
pattern in words placemat can match, and a seventh carries no text at all. The
command is built so that a miss costs a flag, not a wrong answer.

**Build a footprint.** It checks one that exists. Generating a `.kicad_mod`
from a recovered land pattern is a much larger claim and would be wrong more
often than it is right.

**Read a schematic symbol's pin names.** The read-surface spec records why that
is not reachable from the board; a datasheet pin table is a different source
and `--read pins` covers it, but the two are not joined up here.

**Install anything.** `tesseract` is used when present. poppler and mupdf are
already on this machine and join `kicad-cli` as shelled-out tools; placemat's
runtime dependency list stays empty.

## Errors

- A path that is not a PDF, or that poppler will not open: the path and what
  poppler said.
- `--show` for a topic with no candidate: the topic, and the index's advice to
  name a page directly.
- `check` on a datasheet where nothing anchored the scale: says so and names
  the flags that would anchor it, rather than reporting millimetres it guessed.
- `check` with an override that contradicts a sourced value: both values, the
  provenance of the sourced one, and the override winning. A flag beats a
  parse, and the report says it happened.

## Test plan

Without any datasheet, over synthetic input:

1. the index ranks a page carrying a keyword above one carrying none;
2. a rectangle cluster raises a page's land-pattern score;
3. a topic with no candidate prints its own line;
4. a sourced value carries page, bbox and the text it came from;
5. an unsourced value is absent rather than zero;
6. an override contradicting a sourced value wins, and the report says so;
7. one anchor dimension converts recovered geometry to millimetres;
8. `check` names every disagreement and exits non-zero when any remain;
9. `--json` carries the same values as the tables.

Against the committed corpus:

10. the TDK antenna's land pattern ranks page 7 first for `land`;
11. the TYPE-C 31-M-12 yields 36 rectangles from page 1 with no text at all;
12. `[ Unit : mm ]` is read as the unit on the TDK page;
13. a datasheet with no tesseract and no text reports what it could not do,
    and still renders.

## Documentation

- `api.md`, Commands: the four forms, with an example of the index and of
  `check`.
- `SKILL.md`: before extracting images from a datasheet or grepping its text,
  run `placemat datasheet <pdf>` and then `--show`. This is the instruction
  that removes the per-agent decision the user asked about.
- `references/migration.md`: a `## To 0.12` note that the command exists.
  Nothing to migrate.

## Delivery

One design, two plans, because the first is useful alone and the second is
where the uncertainty lives:

- **Plan 1, the index and `--show`.** Channels 1-3, the ranking with its
  evidence, and the render. Works on all 67 and delivers the user's stated ask.
- **Plan 2, `--read` and `check`.** Provenance-carrying extraction, the anchor
  override, and the footprint comparison.

## Migration

Purely additive. No script changes, no placement changes, no run-record
changes.
