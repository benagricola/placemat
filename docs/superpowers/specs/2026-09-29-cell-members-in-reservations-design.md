# A cell judged member by member against a reservation

Date: 2026-09-29
Status: approved 2026-09-29
Source: a board's PLACEMAT_GAPS.md, 2026-09-29 "a cell whose tall member must
stay out of a height band": the enclosure's rule that a front part over
1.5 mm keeps its whole body inside r 19.2, applied to a cell with a 1.8 mm
coil and low parts that may cross the band

## The problem

A reservation (a keepout that forbids parts, a label, a module's rule area)
lets an item in by `Occupancy.let_in` (`occupancy.py:607`):
- by name: `geom.owners & r.owners`;
- by net: `geom.nets & r.allow`;
- by height: every part of it no taller than `max_height`.

For a cell each of these is decided for the cell whole:
- **One member named in `allow` admits every member.** One board's coil was
  let in with the cell's low parts named, its corner at r 20.2.
- **One member's net in `allow` admits every member.**
- **One member too tall keeps every member out.** Without the names, the
  whole 19 x 10 mm cell had to sit inside r 19.2 and found no pocket.

A cell is rigid, but each member is a real part with its own name, nets and
height. The rule the enclosure states is about each part.

## The change

1. **A cell meets a reservation member by member.** Each member is let in
   by its own ref in `allow`, its own nets in `allow`, or its own height
   under `max_height`. The cell is refused when a member that is not let in
   has its body box over the region (the cell's own box first, as now).
   `Cell(...)` in `allow` names every member (`layout.py:2670`), so it
   still admits the cell whole.
2. **A cell's own copper** (tracks and pours among its parts' boxes) is let
   in when the cell is named or every member is let in, and judged
   otherwise. That is today's rule, less the any-member shortcut.
3. **The refusal names the member**: "cell psu's L1 sits in the reservation
   for ..." (with its height, or "no height", in a height-limited region, as
   now).
4. **The native sweep judges the same members.** It takes, per reservation,
   the member boxes that reservation judges, so it refuses the same spots
   (parity tests).
5. Footprints and blocks are unchanged: a block's members are already judged
   one by one as they are laid.

## Verification

Pure tests, each with the native sweep and the Python path agreeing:
- **Height:** a cell of a 1.8 mm part and two 0.5 mm parts, a `max_height`
  1.5 keepout over one side. The cell may stand with only its low parts in
  the region. With the tall one in it, it is refused, naming that part and
  its height.
- **Allow by part:** a keepout allowing one member by name. That member may
  sit in it; another member over it is refused.
- **Allow by net:** as above, by one member's net.
- **Cell named:** `Cell(...)` in `allow` admits every member.
- **Bench:** a change on a board whose cells meet a keepout is named in the
  commit.

## Not in scope

- A reservation that forbids part of a member's body box but not its
  polygon: members are judged by their body boxes, as today.
