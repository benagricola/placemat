# A frame sized to its content

Date: 2026-09-27
Status: proposal, awaiting approval
Source: PLACEMAT_GAPS.md (a board's own), 2026-09-27 "a fragment's frame from its content"

## The problem

A module fragment's frame is what the board stamping it reserves: the parent
reads the stamped cell's box, and the fragment's planes are bounded to the
frame. A frame larger than the parts costs the parent board; a smaller one
cuts the parts off.

`board.size()` takes numbers, and nothing gives the extent of parts placed
from each other's pads before they are placed. `board.reach()` refuses a
block, and a searched part cannot be sized from at all. So the board's
fragments carry a helper module (`fragment_frame.py`: `Content`, `frame()`,
`bounded_planes()`) that redoes placemat's arithmetic by hand: where a part's
body lands when one of its pads sits at a point, a running box, and the
frame and anchor offset from it. Each fragment then places its main part at
the computed numbers. That is placement by coordinates, and it goes stale
whenever a footprint, a rotation or the envelope setting changes.

## The change

1. **`board.size(fit=True, margin=None, chamfer=0.0, radius=0.0, draw=False)`.**
   The frame is the box round everything placed, plus `margin` on every side
   (default: the board's keep-in, `edge_margin`). What counts is what the
   placer keeps: each part's envelope as `[place] envelope` claims it, labels,
   tracks, vias and pours. Planes and zones do not count: they are sized from
   the frame. `width` and `height` are not given.
2. **Placing without a frame.** Items the script decides (fixed, pinned to a
   pad, rows along parts) go down as they do now, with no board edge to
   judge them against. A searched item searches inside a provisional room:
   the box round the items decided so far, grown by `place.fit_room`
   (a setting, default 10 mm) on every side, or the whole room when nothing
   is decided yet. The first item of a fit board with nothing decided is
   placed at the origin.
3. **The frame is fitted once everything is placed**, before any copper that
   depends on it: `board.plane()` with no `outline=` is planned after
   placement on a fit board, inset from the fitted frame as it is from a
   sized one. The plan's outline is the fitted frame, so the run's extent,
   the written fragment and the stamped cell all use it.
4. **What cannot be said on a fit board is refused when declared.** A frame
   edge (`OnEdge`, `Edge.*` rows, `edge(facing=)`), a `Centre()` of the board
   and `board.width`/`board.height` before resolve have no meaning until the
   frame exists. Each raises a clear error naming fit.
5. **Docs.** api.md's `board.size` entry and the fragment section, a SKILL.md
   line under module fragments (size a fragment's frame with `fit=True`;
   never compute it by hand), and the migration note, which points at
   helpers that compute a frame and says they can go.

## Verification

- Pure tests:
  - a fit board with two parts, one pinned from the other's pad: the frame
    is their envelope box plus the margin, and moves with a changed footprint;
  - labels, tracks and vias count; a plane does not, and is inset from the
    fitted frame;
  - a searched part on a fit board lands inside the provisional room and the
    frame grows to include it;
  - `OnEdge` and a row on a frame edge are refused on a fit board.
- KiCad: a fit fragment stamped into a parent: the parent's cell box equals
  the fitted frame (planes included), and the fragment's own DRC is clean.
- Bench, as a placement change (no bench board uses fit, so same 32).

## Not in scope

- A frame shape other than a rectangle (fit fits a box, chamfered or rounded).
- Fitting a board that is not a fragment: a real board's outline is a
  mechanical fact, and `fit=True` on one with `draw=True` is refused.
