# Standing a part a clearance off another part's copper

Status: approved (2026-10-01).

Source: Ben, through a board's session (2026-10-01): a net tie at a current
shunt's output pad.

## Problem

A two-pad net tie (pad 1 on the shunt's output net, pad 2 on the sense net)
stands north of the shunt's output pad, lying east-west: pad 1 on that pad's
centre line, its stub running straight down into the pad, and the tie's
sense pad a clearance (0.16 mm) off the output pad. KiCad exempts a net
tie's pads from clearance to the tie's own nets, so its DRC would not flag
the sense pad standing nearer; Ben wants it clear anyway.

- `Beside(Part("shunt"), Edge.NORTH, gap=, align=(1, PadRef(shunt, "VOUT")))`
  lines pad 1 up on the pad's centre line, but `gap=` counts from the
  shunt's envelope, which sits about 0.1 mm inside its pads' ends, so no
  `gap=` says "a clearance off the pad".
- `Pin(2, Past([PadRef(shunt, "VOUT")], Edge.NORTH, across=...))` is
  refused (`Pin` takes no `Past`), and would put pad 2, not pad 1, on the
  centre line.

## Design

`Beside(item, side, *, copper=True, gap=0.0, align=...)` measures the stand
off from copper, not from envelopes: the part stands as near `item` on
`side` as its pads allow, every pad of the part keeping, from every pad of
`item` of another net, the clearance the pair needs (by net pair, the
script's `board.rule` clearances included) plus `gap`. Pads of the same net
set no distance (they may meet, as a stub's pad meets its target).
`align=` lines the part up across the side as today.

```python
board.place(Part("nt_isp"), at=Beside(Part("shunt"), Edge.NORTH, copper=True,
                                      align=(1, PadRef(Part("shunt"), "VOUT"))),
            rotation=..., why="the sense tie a clearance off the output pad, pad 1 on its centre line")
```

- The distance is set by the pads alone; the part's body, courtyard and
  silk are judged afterwards as for any placement (a part whose body would
  then overlap `item`'s is refused, naming both, as a `Beside` that
  collides is today).
- A net tie's own-net exemption (KiCad's, which placemat follows when
  judging copper) does not shorten the distance: the clearance is set here
  by net pair, whatever the footprint is.
- `copper=True` with `item` a `Cell`: its members' pads.
- Without `copper=`, `Beside` measures from envelopes as today.

The alternative asked for, `Pin(key, Past(...))`, is not proposed: `Past`
holds a point a clearance off copper for a track's or via's own width,
while a part's distance is set by whichever of its pads comes nearest,
which `Beside` already knows and `Pin` does not.

## Verification

- The case above: the tie's sense pad stands exactly the clearance (0.16)
  off the output pad, measured copper to copper; pad 1 on the pad's centre
  line; no finding; KiCad's DRC clean.
- `gap=0.1`: 0.26 copper to copper.
- A part whose nearest pad to `item` is of the same net as the facing pad:
  set by its nearest pad of another net, not the same-net one.
- A `board.rule` clearance for the pair is kept.
- A part whose body would overlap `item`'s at the copper distance: refused,
  naming both.
- Without `copper=`: placements unchanged (digest parity, bench unchanged).
