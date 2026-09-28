# Keeping the closed parts of an open net

Date: 2026-09-28
Status: draft
Source: a board's layout work, 2026-09-28 (the core): "can route --adopt keep
the closed parts of a net that is still open"

## The problem

`route --adopt` keeps a net only whole: one still open after the route is
left out. On the core the router leaves GND (and V3V3 before it) two or
three connections short of whole on every pass, so every pass throws away
its ~30 GND plane drops and pad-to-pad joins - about a third of the board's
86 open connections - and the next pass routes them again, differently.

## The change

1. **`route --adopt NET ... --partial`** (and `--adopt-all --partial`)
   also keeps an open net's new copper in part: the router's new copper on
   the net is split into islands (tracks and vias that touch, directly or
   through a pad of the net), and an island is kept when it joins two or
   more of the net's pads, or a pad and a plane of the net (a via inside
   one of the net's zones on some layer). An island that reaches one pad or
   none is dropped. A shorted net is still not kept.
2. **An open net's kept copper is its own entry** in the routes file,
   marked partial, beside any the net already has: a later pass keeps what
   it closes next as another entry, and an earlier entry still held is not
   replaced (its copper is on the board the router was given, so it is not
   new copper). Each entry is drawn, and dropped when its parts move, on
   its own, as today.
3. **The lock** takes the items the kept islands join, as a whole net's do.
4. **Report:** the adopt lines say, per net, "N island(s) kept, joining M
   pads; K dropped (reaching one pad or none); still P open".
5. `placemat routes` lists partial entries with their net and "partial".

## Verification

- Pure tests (synthetic geometries): an open net whose new copper forms one
  island joining two pads, one joining a pad and a via inside a zone of the
  net, and one dangling track: the first two kept, the third dropped; a
  second adoption of the same net adds an entry and keeps the first; a
  shorted net keeps nothing.
- KiCad (no router): the breakout with a net's second track removed from a
  "routed" copy: `--partial` keeps the first.
- Bench unaffected.

## Not in scope

- Keeping copper the router laid on a net it shorted.
- Choosing among islands by length or quality: an island that joins two
  terminals is kept.
