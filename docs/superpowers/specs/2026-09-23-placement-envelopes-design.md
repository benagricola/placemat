# Placement envelopes from pads, silk and body

Date: 2026-09-23
Status: design (from the board agent; decisions below added on review)

Setting: `[place] envelope = "courtyard" | "physical" | "union"`, in
placemat.toml.

- `courtyard` is the default and today's behaviour: courtyard box plus pads.
- `physical` ignores the drawn courtyard.
- `union` claims both the courtyard and the physical shapes.

A footprint with none of the physical layers falls back to its courtyard,
then to its pads.

## What a part claims in physical

These are shapes, not one box, and each sits on the faces it occupies.
Through-hole parts claim both faces, as now.

- Copper: every pad's outline, as today.
- Mask: each pad's mask aperture, meaning the pad plus its mask expansion
  (pad-level, else board-level).
- Silk: every F/B.SilkS graphic, drawn as its stroked outline with the line
  width included. The Reference and Value fields are excluded, because that
  text can be moved or hidden. `board.label()` text stays a reservation, as
  now.
- Body: the F/B.Fab outline where one is drawn.

## Legality between two different parts

Every gap comes from the board's own design rules, so a legal placement
cannot produce the matching DRC item. Pairs within one footprint are never
tested; those are footprint findings.

|        | copper (other net) | mask aperture | silk | body |
|--------|--------------------|---------------|------|------|
| copper | netclass clearance (existing, with board.rule overrides) | none | none | assembly gap |
| silk   | none | silk clearance (DRC `silk_over_copper`) | silk clearance (DRC `silk_overlap`) | 0 |
| body   | assembly gap | none | 0 | assembly gap |

- The netclass clearance comes from the project, as now.
- The silk clearance is the board's `silkscreen.minimum_item_clearance`
  (0.1 mm on the core board).
- The assembly gap is a new fab-profile.json key, `component_spacing`. Its
  default is twice `courtyard_excess`, which reproduces today's touching
  courtyards on a well-drawn footprint.

## What else follows the setting

- Rank: area is measured from the envelope in physical and union, so the
  placement order reflects the real size.
- Rows and edges: in physical a row's claim is the reach alone, without the
  courtyard.
- Cells: a cell's envelope is the union of its members' envelopes, as reach
  already is (`occupancy.py`, `_geometry` for a `CellGeom`).

## Reporting

- `placemat measure` prints the envelope and which layers set it.
- In courtyard mode, a footprint whose silk or pads pass its courtyard by more
  than the silk clearance is reported, e.g. `U21: courtyard understates the
  part by 0.42 mm (silk)`. On the core board that names 46.
- The mode is part of the run id through the settings hash.

## Acceptance

- With physical, placed parts produce no `silk_overlap` or `silk_over_copper`
  items between different footprints. The core's 124 go to 0, apart from any
  that come from Reference/Value text.
- A unit test places two footprints whose silk passes their courtyards and
  cannot make their silk overlap.
- A footprint with only pads places exactly as in courtyard mode.
- The resolve on the 220-part core stays within 20% of its current 137 s.
- The migration note says that switching the mode re-places every board.

## Out of scope

- Moving or hiding colliding refdes text, which is a separate step.
- Routing channels: a separate `[place] pad_gap` minimum between different
  parts' pads. The module layouts and `--route` closure cover routability for
  now.
- Repairing footprints, which is a library job. placemat only reports them.

## Decisions on review

- **The courtyard report is not a finding.** Findings count in the best-run
  objective, so 46 new ones would make the first run after upgrading a
  regression against its stored best. They are a `footprints` line in the run
  output and `metrics.footprints` in the run record, outside `plan.findings`.
- **Every footprint field is excluded from silk**, not only Reference and
  Value: all fields are text placemat or the generator can move or hide, and
  on the generated boards the other fields sit hidden on F.Silkscreen. Graphic
  text drawn on silk (`PCB_TEXT`) is included.
- **The body is the box of the Fab graphics** (text excluded), per face.
  Footprints often draw the fab outline as separate lines, whose stroked
  outlines are thin strips that two bodies could interpenetrate; the box is
  what the outline encloses.
- **Faces.** A through-hole part's body and plated-hole mask apertures claim
  both faces, as its courtyard does now; its silk stays on the face it is
  drawn on.
- **The edge margin** still judges the body box, unchanged by the mode.
