# A slide goes before an item searched in two

Date: 2026-10-02
Status: design, built in the same change
Source: a board's session, 0.78.0 (a slide ended mid-board behind a larger
item searched first)

## Problem

Within one priority tier, searched items go down by rank: courtyard area
and pin count, largest first (`_next_to_place`, `ranking.py`). Two kinds of
item are both "searched" and are ranked alone:

- an item with one freedom left, a slide: `Centre(x, None, toward=Edge.SOUTH)`
  takes the legal spot farthest toward an end of a line;
- an item with two, searched in a region or from its links.

A large item of the second kind can rank first and take a spot on the line
the slide runs along. The slide then stops at the nearest legal spot short of
its end ("38.2 mm short of the south end by: cell debug's pad sits in cell
haptics's courtyard"), leaves it mid-board, and the cells that needed the
room it would have left go unplaced. The same board fits when the large item
happens to land beside the line, so the result depends on where an
unrelated search lands. Both items need the top tier (each has a small room
bigger cells would take), the script cannot order within a tier, and its
owner wants to say intent only.

## The rule

Freedom, not file order, decides what is decided and when (`SKILL.md`,
"Freedom is derived from `at=`, never declared, and file order never decides
execution"). `Freedom`'s own account (`values.py`): "A decided item goes
down first and nothing may move it; a searched one takes its turn in the
queue by rank." The placement-rank spec (2026-09-22) puts a one-freedom place
in the searched queue deliberately: `OnEdge(edge)` and `Location(30, None)`
are SEARCHED, "which is what api.md already says it is", and are ranked "so
a large edge connector claims its stretch before a small test point does".
The rank orders items that are alike; it was never asked whether a slide and
a two-freedom search are.

The ordering this rests on is the ordinary one: the more constrained item
first, because it has the fewest places to go and loses the most when
something else takes one.

## Options

1. **A one-freedom Centre with `toward=` is `Freedom.EDGE`.** It then goes
   down in `place_ranked(RANK_FIXED, RANK_EDGE)`, before the searched queue.
   Rejected: `decided` means the position is known without a search and
   nothing may push it. A slide is found by a search along the line (its
   spot depends on what is placed, what its keep-outs and height bands
   leave, and which fellows share the value), so it would need a search
   phase inside the decided phase; copper derivation, the collision filter
   and `required` read `decided` and would all change meaning. It also
   treats only `Centre(toward=)`: an `OnEdge(edge)`, a ring or a spoke with
   the same problem would need the same special case, and the placement-rank
   spec put them in the queue on purpose.
2. **Within a tier, fewer freedoms first, then rank.** The sort key of
   `_next_to_place` gains the number of freedoms between the tier and the
   rank. A slide stays a searched item, ranked and scored as before, and
   goes down ahead of an item searched in two of the same tier. Chosen.

## Design

`PlaceIntent.freedoms` (0, 1 or 2): 0 for a decided place; 1 when the
declaration leaves one for `_settle` to search along; 2 for anything else.
It is read in the order `_settle` dispatches, so it says what is searched:

| Declaration | Freedoms |
|---|---|
| `Location`/`Centre` with one axis `None` (with or without `toward=`) | 1 |
| `OnEdge(edge)` with no `along=`, on a side or on a stretch from `board.edge(facing=)` | 1 |
| `OnRim()`/`OnBore()` with no bearing | 1 |
| `Polar(r)` (a ring), `Polar(None, angle)` (a spoke), `Polar((r0, r1), angle)` (a spoke segment) | 1 |
| a point whose turn is searched (`rotations=` with `at=Pin(...)`) | 1 |
| `Polar((r0, r1), None)` (a band), `Near`, region-bounded searches, nothing | 2 |
| `Location(x, y)`, `Centre(x, y)`, `Pin`, `OnEdge(..., along=)`, `Beside` | 0 (decided, unchanged) |

`Pin(key, x, None)` is refused today, so a Pin has no one-axis form to
count. A row's items are decided.

`_next_to_place` sorts `(-tier, freedoms, -rank score, -pull, -area, key)`.
Two further changes keep that order from being undone:

- `_link_waits`: an item no longer waits for a linked partner searched in
  more freedoms (it would otherwise be filtered out of the candidates and
  placed after the partner). Waits among items of the same freedoms, and
  from the item with more to the item with fewer, are as before.
- a step that goes down ahead of a two-freedom item of its tier says so:
  "one freedom: before the items of its tier searched in two".

Not changed: the tier order (`HIGH`, default, `LOW`), items of one freedom
count among themselves (still by rank), holds (`needs`, held cell
references), the locked order, `--explore`'s swap of two focused neighbours,
and any board with no slide, whose queue is the same.

A DEFAULT-tier slide still goes after a HIGH item searched in two: the tier
is the script's word and a freedom count does not outrank it.

## Verification

Tests (`tests/test_slides_first.py`):

- a slide and a larger fully searched item of the same tier: the slide goes
  first, and reaches its end when the larger item is searched there;
- items of different tiers keep the tier order, in both directions;
- slides of one tier go by rank;
- with no slide the order is the rank;
- a linked slide does not wait for its partner searched in two;
- the number of freedoms of each form above, by declaration.

The bench (`fixtures/bench.py --jobs 4`): see the commit message for the
tally; the fixtures place bare, so no case has a slide.

A real board whose script has a searched cell and a `Centre(x, None,
toward=Edge.SOUTH)` cell, both HIGH, run on a copy against 0.78.0: where the
two land, what is unplaced, the score. Results are in the commit message.
