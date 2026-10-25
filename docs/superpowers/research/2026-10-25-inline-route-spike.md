# Inline route spike: routing a bus phase between placement steps

The idea: place a bus's ends (an MCU, a display connector and its terminations),
route the bus on a nearly empty board, then place everything else around that
copper. The spike was throwaway work on a copy of a real board with about 40
placed items, one full route per arm. Shelved: no gain was measured, and doing it
properly needs a new form.

## Arms

- **A.** Full placement, then a full route.
- **B.** Placement up to the bus ends, then route only the bus phase. The bus
  tracks are declared as copper, and the run continues with full placement and a
  full route.
- **B'.** As B, plus keepout rectangles along the tracks, standing in for room.

## Results

| | A | B | B' |
|---|---|---|---|
| Closure after full route | 93.2% (8 open) | 90.2% (11 open) | 91.9% (9 open) |
| Bus phase | 7 of 8, then 100% | 7 of 8 early, 100% at the end | 7 of 8 early, 1 open at the end |
| DRC clearance or shorts | 0 | 0 | 0 |

- **Bus phase.** On the nearly empty board the bus phase joined the same 7 of 8
  nets as on the full board.
- **Connector pins.** The early bus walled in three other pins of the display
  connector, giving 3 critical findings in B and B'.
- **Noise.** The 1-3 point closure gaps are within run-to-run variation for a
  single route.

## Why placement did not react

- **No room without owner pads.** A track declared only by its points has no
  owner pads, so placement does not plan it as room. In B, 35 of 40 items landed
  within 0.05 mm of their positions in A.
- **Declared with pad ends.** Declaring the tracks with pad ends does make them
  room, but then a firm Beside cell collides: its through via sits under a
  planned track.
- **Keepout stand-in.** In B', the keepouts moved 12 small parts and cells by up
  to 10 mm. Closure did not improve.

## What a real implementation needs

- **Routed copper as room.** It needs owner pads, and is planned once those pads
  are placed.
- **A firm Beside item that holds.** It must be able to hold its position against
  that room, including its own vias.
- **Tracks stored whole.** Router polylines are stored as routed. Snapping ends
  to pad centres and re-bending each leg distorts them.
- **Lanes for a dense connector.** Its other pins keep lanes reserved, so an early
  bus cannot wall them in.
- **Repeat runs per arm.** These measure the noise before any gain is claimed.
