# Plane drops and the far face

Status: draft, for approval.

Source: fairing `PLACEMAT_GAPS.md` 2026-09-29, "plane drops that share the
far face", and the owner, 2026-09-30:
- "reusing vias ... will help a lot";
- "dropping vias from one module or part to allow another to place on the
  opposite side";
- "Can we set the density of those fields as well?".

## Problem

A module cell carries its plane drops, the through vias from its pads
into the ground and supply planes, in its fragment's copper:
- the protection cell carries 27 vias, all drops;
- the 5 V cell carries 35 of 42;
- the logic cell carries 61 of 63.

Most of these are via fields under an IC's exposed pad.

A through via is copper on every layer, so wherever it meets another net's
copper on the far face, the placement is refused. The protection cell (208
mm2) found no spot on a mostly empty back face: 363 copper refusals from the
front's parts. Three things would each open room:

1. A drop that reaches only the plane next to its own face (a laser blind
   via, one layer deep) touches nothing on the far face.
2. A drop that meets other copper can give way. The field thins where it
   collides and keeps enough vias to do its job, in either direction:
   - the cell being placed drops some of its own;
   - a cell already down gives up some of its drops to a part placed later
     on the far face.
3. A field's density can be set, in the module and when the cell is
   placed.

The density can already be set at the source, since `board.vias(net,
PadRef(...), pitch=)` gives a field's pitch. Its default is the densest
pitch the hole-to-hole rule allows, and nothing thins a stamped cell's
field from the parent.

## Design

### 1. A via's layer span

`layers=(CopperLayer.B, CopperLayer.IN4)` on:
- `board.via()`;
- `board.vias()`, both forms;
- `board.stitch()`.

- The via is copper, and its hole, on those layers only. The occupancy
  judges it only there, and it blocks a courtyard only on the face its
  span reaches.
- It is written as KiCad writes such a via:
  - a micro via when the span is one layer from an outer face (F to In1,
    B to In4);
  - blind or buried otherwise.
- The board's design settings are set to allow that via type.
- The default is every layer, the through via, as now.
- A span naming a layer the board does not have is refused.
- The span's own drill and size come from the net class unless given, the
  same as a through via's. The fab's limit for a laser via (JLCPCB: 0.1 mm
  drill, depth at most the drill) becomes a setting,
  `copper.microvia_drill`.

A module fragment built with spans carries them into the parent: the
reader already reads each via's layers. A cell whose drops are one-layer
micro vias places on either face with no far-face conflict from its drops.

### 2. Drops that give way

A drop is a via of a plane net that a part or cell carries. A plane net is
one the board declares a `plane()` for, on any layer.
- **Its own drops.** At a candidate spot, a drop of the item being placed
  that meets another net's copper is dropped instead of refusing the
  candidate. That holds only while each of the item's pads keeps at least
  `place.drops_keep` of its drops (default 0.5, rounded up, and never
  fewer than one per pad).
- **Drops already down.** When a searched item's copper or body on the
  far face meets a drop of a cell already placed, that drop is removed if
  its owner still keeps its `drops_keep` share. Nothing else of the owner
  changes.
- **Scoring.** A candidate costs `score.drop` (a setting, default 10 mm)
  per drop it removes, so the search prefers spots that remove none.
- **Sharing.** A drop that lands on the far face's copper of its own net
  (a pad or a via) costs nothing and is kept; the far face's copper joins
  it to the plane already. A drop removed next to a same-net via within
  `place.drop_share` (default 1 mm) is reported as served by that via.
- The run reports, per owner, the drops removed and why ("protect: 6 of 27
  GND drops removed under the bench panel's pads").
- A tail left pointing at a removed drop is removed with it.
- A drop inside a pad (an exposed-pad field) is removed with no tail to
  clear.

### 3. Thinning a field when a cell is placed

`board.place(Cell(...), ..., drops=Drops.HALF)`, or `drops=Drops.ALL`
(the default, as stamped) or `drops=Drops.MIN` (the `drops_keep` share
from the start):
- `HALF` keeps every other via of each field, in a checkerboard over the
  field's grid.
- A field is the drops inside one pad.
- `drops=` changes the cell's copper as placed; the fragment is untouched.

## Out of scope

- Moving a drop to a new spot (a via re-sited within its pad, or its tail
  re-routed). A drop is kept or removed, not moved.
- Buried vias between two inner layers for plane-to-plane stitching.

## Order

1 (the via span) first: it needs no change to how placement is judged, and
it removes the far-face conflict outright where the fab allows micro vias.
Then 2 and 3, which share the drop bookkeeping.

## Verification

- Via span:
  - written and read back with its type and layers;
  - judged only on its layers;
  - a cell carrying spans placed over far-face copper of another net;
  - a span on a layer the board lacks refused.
- Drops:
  - a cell placed where some of its drops meet far-face copper, with them
    removed and the keep share held;
  - a placed cell's drop removed for a later far-face part;
  - a pad at its minimum refusing the candidate;
  - a shared drop counted as shared;
  - the removal reported.
- Density: `HALF` and `MIN` on a stamped field.
- The full suite, a release, then the bench. Drops are a placement change;
  the bench corpus has via fields in its module fragments.
