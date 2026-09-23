# A fanout band for a fine-pitch part

Date: 2026-09-24
Status: design

Bypass satellites sit at their pins, but a pull-up, strap or series resistor
linked to a GPIO lands in front of the neighbouring pins too, and nothing
keeps the band the GPIO must escape through. Source: fairing-instrument
`electronics/PLACEMAT_GAPS.md`, "passive orientation and the MCU's fanout",
items 2 and 5.

## Declaration

```python
board.fanout(Part("mcu"), depth=2.0, sides=None, why="the GPIO escape")
```

`depth` (mm) is how far the band reaches out from the pad rows; `sides` is
a list of `Edge`s (default every side that has pads); a side is judged on
the part as placed, so north is north of the board.

## Behaviour

- A pad belongs to the side of the part's body its box comes within 1 mm
  of; a pad no side is near (an exposed pad) belongs to none.
- Per side, the band is the rectangle from the side's pad row's outer edge
  outward by `depth`, spanning the row.
- Each band is reserved on the part's face as soon as the part is placed,
  before anything searched after it. It keeps out every part except the
  part itself, the satellites of a block the part anchors, and parts linked
  to one of its pads with a weight of `LinkWeight.SHORT` or more.
- Anything else seeded on one of its pins lands at the nearest legal spot,
  which is across the band from the pin.
- A fanout is part of the reuse context: changing it replays nothing.

## Test plan

A two-row part with a fanout: a resistor linked to a pin lands outside the
band; a capacitor linked SHORT to a pin may sit inside it; a satellite of
the part's block sits at its pin inside it; a part on the other face is not
kept out; `sides=` limits the bands.
