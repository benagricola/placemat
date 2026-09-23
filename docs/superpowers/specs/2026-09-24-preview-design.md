# A preview: place and draw, without building the board

Date: 2026-09-24
Status: design

A run writes the board, runs DRC and renders it with kicad-cli. On the core
board the render is 25 s of every run, and with the previous run reused the
placement itself is 3-4 s, so a run that changes one late part spends 85% of
its time on the render (the board's own runs: 29 s, of which render 25 s,
resolve 3.5-4 s). An agent checking a placement needs a picture and the
reasons, not a written and checked board.

## The command

```
placemat preview <script> [--svg] [--face front|back|both] [--out DIR]
```

It prepares the board as a run does - the cached generation, the settings,
the fab profile, the script - resolves with reuse, and draws the plan
straight from placemat's own model: nothing is written to the board, no DRC,
no kicad-cli. It writes `preview.svg`, then converts it to `preview.png` by
running the converter; `--svg` stops at the SVG. Output goes to
`<board>/.placemat/preview/` unless `--out` says otherwise, and the command
prints the paths, the step summary the run prints (placed, findings,
reused), the congestion line and every finding.

## The converter

`[preview] converter` is the command, default
`rsvg-convert --width {width} -o {png} {svg}`; `{svg}`, `{png}` and `{width}`
are filled in. If the command is not found or fails, the SVG is kept, the
command says why and exits 0 - the SVG is the drawing, the PNG a
convenience. `[preview] width` (px, default 1600).

## What is drawn

One panel per face asked for, side by side, the back face mirrored as seen
from the front (x as on the front), a millimetre grid and axis labels, and a
legend. On each face:

- **Board**: the outline (rectangle, disc or shaped outline, with its
  cutouts), or a module fragment's frame dotted.
- **Keepouts and reservations**: filled pale, named.
- **Parts on this face**: pads (through pads on both faces, marked), the
  courtyard dashed, the body (fab box) outlined, silk as drawn, and the
  reference at the body's centre. Parts on the other face are drawn faint.
- **Copper planned**: tracks as lines of their width, vias as circles,
  planes and pours outlined.
- **Links**: a line pad to pad per declared link, green within its limit,
  red over it, grey with no limit, labelled with its length when limited.
- **Parts that took a pocket**: outlined orange, with a line to the nearest
  pad they connect to.
- **Unplaced parts**: listed in a box at the side, with the reason from
  their step.
- **Congestion**: the RUDY grid as a heat map under everything (utilisation
  over 1 red), the worst cell ringed and labelled with its value.

Each layer can be switched off: `--no-heat`, `--no-links`, `--no-copper`.
The drawing is deterministic: same plan, same SVG bytes.

## Reuse

The preview reads the newer of the latest run's record and its own last
record, replays what it can, and keeps its own record in
`.placemat/preview/reuse.json`; it never writes a run record, so the
best-run gate and `latest.json` are untouched.

## What this does NOT do

It does not replace a run: DRC, the written board, airwires and the best-run
gate stay with `placemat run`. It does not route.

## Test plan

Pure (no KiCad): the SVG for a synthetic board has the outline, a pad per
placed pad on its face, a courtyard per part, the back face mirrored, a
red link over its limit and a green one within, a pocketed part marked, an
unplaced part listed, the heat map's worst cell ringed; `--no-heat` etc.
remove their layers; the same plan gives the same bytes; a missing converter
keeps the SVG and says so; the converter command is built from the setting.
With KiCad: `placemat preview` on a fixture module writes both files, the PNG
decodes to the asked width; a second preview reuses every step.

## Documentation

`api.md` (the command, the layers, `[preview]`), `SKILL.md` (preview while
iterating, run to check), `migration.md` (new, nothing to change).
