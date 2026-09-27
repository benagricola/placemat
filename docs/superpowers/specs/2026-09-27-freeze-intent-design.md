# Freeze keeps the lock's frame and says where the spot came from

Date: 2026-09-27
Status: approved 2026-09-27

## The problem

`placemat run --explore ... --accept` keeps what explore found in
`<script>.lock.json`. Each entry is stored relative to the placed pad the item
depends on most, in that pad's part's frame, with its rotation relative to
that part (`lock.entry_from_turn`). A locked item turns and moves with its
anchor. Every run re-checks it: held, drifted, or released when its
declaration changes.

`placemat freeze` writes an entry into the script, and loses three things on
the way:

- **The frame.** It writes `Near(PadRef(anchor).offset(dx, dy), radius=0)`
  with dx, dy in board directions and an absolute `rotation=`
  (`freeze.frozen_args`). `PadRef.offset` is a board-direction offset
  (`values.py`), and `rotation=` is absolute. When the anchor part turns, the
  locked item turns with it, but the frozen one keeps its board offset and
  angle and ends up somewhere else round the anchor.
- **The reason.** Nothing in the frozen call says the spot came from an
  explore run, which run, or what it scored. The next reader sees a hard
  position it can only keep or delete.
- **Items with no anchor.** They get an absolute `Near(Location(x, y),
  radius=0)`. That is the only way to write them, but it is still a bare
  coordinate.

SKILL.md tells an agent to freeze an entry "when it has become intent", but
freeze writes nothing that states an intent. The user's concern: agents end up
placing by coordinates instead of by intent.

## The change

1. **An offset in a part's own frame.** `PadRef.local(dx, dy)` is the pad's
   point plus (dx, dy) measured in its part's frame: turned by the part's
   rotation, exactly as the lock measures (`lock._turn`), and on the back
   face mirrored as the part's own pads are. (The lock releases an entry
   whose anchor has changed face; a frozen call follows the flip instead.)
   `PadRef.offset` stays as it is (board directions).
2. **A rotation relative to a part.** `rotation=Turned(Part("u1"), 90)` is
   the part's placed rotation plus 90. It is resolved when the item is
   placed, so the named part must be placed first; it joins the item's
   needs as a `Near` on its pad does (the 0.38 ordering applies).
3. **Freeze writes both.** A frozen entry becomes
   `at=Near(PadRef(anchor, n).local(dx, dy), radius=0),
   rotation=Turned(Part(anchor), r)` from the lock's own numbers, with no
   conversion. `--fixed` writes the same point as a firm place when the
   anchor is fixed, as today.
4. **Freeze says why.** The call's `why=` becomes `explore <run id>: <score>
   mm, frozen <date>`, appended to any `why` the call already had. The lock
   entry records the run id and score at `--accept`. An entry accepted before
   this change has neither, and freeze writes `explore: frozen <date>`.
5. **SKILL.md.** Explore's results stay in the lock, which re-checks them on
   every run. Freeze an entry only to hand the item to the decided tier.
   Never copy a lock's or a query's numbers into a script by hand. The
   migration note says the same.

## Verification

- Pure tests:
  - `PadRef.local` at rotations 0, 90, 180 and 270, and on the back face;
  - `Turned` resolving to the part's rotation plus the angle, and ordering
    after that part;
  - a frozen script re-resolving to the locked placements (freeze's own gate)
    with the anchor turned 90 degrees between accept and freeze: the frozen
    item follows the anchor as the lock does;
  - `why=` carrying the run id and score; an old lock entry without them
    freezing with the short form.
- The existing freeze tests pass with the new call form.
- Bench, as a placement change.

## Not in scope

- Turning an explore result into declarations of a different kind (a block
  satellite, a link limit). Freeze writes the position the lock holds.
- Changing what explore searches or how the lock holds, drifts or releases.
