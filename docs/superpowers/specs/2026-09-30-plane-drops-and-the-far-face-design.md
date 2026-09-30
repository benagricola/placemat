# Vias that give way: sharing, moving, dropping, and a layer span

Status: draft, for approval.

Source:
- The fairing's `PLACEMAT_GAPS.md` 2026-09-29, "plane drops that share the
  far face".
- The owner, 2026-09-30:
  - "reusing vias ... will help a lot";
  - "dropping vias from one module or part to allow another to place on the
    opposite side";
  - "Can we set the density of those fields as well?";
  - "Some fabs can't do blind vias ... allowing vias from both front and back
    modules if they are on the same net and land within a particular
    circumference of each other and don't cause a short. Similarly for non
    plane vias they can usually be moved slightly to avoid a pad on either
    face".

## Problem

A module cell carries its vias in its fragment's copper:
- the protection cell carries 27 vias, all plane drops;
- the 5 V cell carries 35 of 42;
- the logic cell carries 61 of 63.

Most are fields under an IC's exposed pad. A through via is copper on every
layer, so wherever one meets another net's copper on the far face the
placement is refused. The protection cell (208 mm2) found no spot on a
mostly empty back face: 363 copper refusals from the front's parts.

Today a carried via is fixed: kept exactly where its fragment drew it, or
the whole placement is refused. The design lets it give way. It works on
fabs that make only through vias, and it adds a blind via for fabs that
make them.

## Terms

- **A carried via**: a via a part or cell brings with it (a stamped
  fragment's vias, a via at a pad).
- **A drop**: a carried via of a plane net, a net the board declares a
  `plane()` for. Every other carried via is a signal via.
- **Its tail**: the copper that joins a carried via to its pad. A via inside
  its pad has none.

## Design

### 1. Giving way at a candidate spot

When an item is tried at a candidate, each of its carried vias that meets
another net's copper, on either face, tries in turn:

1. **Share.** A via of the same net on the board, from any item on either
   face, within `place.via_share` (default 1.0 mm) of the carried via:
   - the carried via is removed;
   - its tail, or its pad if it has none, is joined to that via by a
     straight tail at the net's width on the via's own face;
   - that tail must clear every other net's copper.

   A via of the same net landing on the carried via's spot needs nothing:
   it is already shared.
2. **Move.** The via moves, up to `place.via_move` (default 0.5 mm, searched
   on a 0.05 mm grid), to the nearest spot clear of every other net's copper
   on every layer and of every hole. Its tail is redrawn from its pad to the
   new spot and must clear too. A via inside its pad moves only within that
   pad.
3. **Drop** (drops only). The via is removed if each of the item's pads
   still keeps at least `place.drops_keep` of its drops (default 0.5,
   rounded up, never fewer than one), counting shared drops as kept.

If none of these work, the candidate is refused, as now, and the refusal
names the via.

- **Cost.** Each give-way has a score: `score.via_share` (default 1 mm),
  `score.via_move` (2 mm) and `score.via_drop` (10 mm). The search prefers
  spots where the item's vias stay as drawn.
- **Items already placed.** The same steps apply to a via already on the
  board that a later item on the other face meets:
  - its owner's via shares, moves or drops;
  - its owner is otherwise untouched;
  - its owner's keep share still holds.
- **Report.** The run reports, per owner, what gave way and why, for
  example: "protect: 6 GND drops shared with bench's vias, 2 moved 0.25 mm,
  1 dropped under U3".

### 2. A via's layer span

For fabs that make blind or micro vias, `layers=(CopperLayer.B,
CopperLayer.IN4)` can be given on `board.via()`, `board.vias()` (both forms)
and `board.stitch()`:
- The via is copper, and its hole, on those layers only, and it is judged
  there alone.
- It is written as KiCad's micro via when the span is one layer from an
  outer face, and as a blind or buried via otherwise. The board's design
  settings are set to allow that type.
- The default is every layer, the through via, as now.
- A span naming a layer the board does not have is refused.
- The laser via's drill is a setting, `copper.microvia_drill`.

A fragment built with spans carries them into the parent, since the reader
already reads each via's layers. A cell whose drops are one-layer micro
vias meets nothing on the far face.

### 3. A field's density

In the module script, `board.vias(net, PadRef(...), pitch=)` already sets an
exposed-pad field's pitch. Its default is the densest pitch the hole-to-hole
rule allows.

When the cell is placed in the parent, `board.place(Cell(...), ...,
drops=Drops.ALL)` changes the density of its fields:
- `Drops.ALL`, the default, keeps the fields as stamped.
- `Drops.HALF` keeps every other via of each field, in a checkerboard over
  its grid.
- `Drops.MIN` keeps each field at the `drops_keep` share from the start.
- A field is the drops inside one pad.
- The fragment itself is untouched.

## Out of scope

- Re-routing a tail round an obstacle. A moved or shared via's tail is
  straight, and a spot whose tail is not clear is passed over.
- Buried vias between two inner layers for plane-to-plane stitching.

## Order

1. Giving way (1), since it works on every fab: sharing first, then
   moving, then dropping.
2. The density on `place()` (3).
3. The layer span (2).

## Verification

- Sharing:
  - a back cell's GND drop within `via_share` of a front cell's GND via,
    with the drop removed and the joining tail drawn and clear;
  - one farther away is not shared;
  - one whose joining tail would short is not shared.
- Moving:
  - a signal via 0.2 mm onto a far-face pad of another net moves clear, its
    tail redrawn;
  - one with no clear spot within `via_move` is refused and named.
- Dropping:
  - a pad at its keep share refusing the candidate;
  - a pad above it dropping.
- Items already placed: a front cell's via gives way to a back part placed
  later.
- The report of what gave way.
- The layer span:
  - written and read back with its type and layers;
  - judged only on its layers;
  - a span on a layer the board lacks refused.
- Density: `HALF` and `MIN` on a stamped field.
- The full suite, a release, then the bench. This is a placement change,
  and the bench's fragments carry via fields.
