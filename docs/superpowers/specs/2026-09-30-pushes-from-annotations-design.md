# Pushes from part annotations

Status: approved (2026-09-30).

Source: Ben, through a board's session (2026-09-30).

## Problem

`board.push(item, from_=, falloff=, reference=, limit=)` holds one item
back from one source. A board has many such pairs:
- a magnet and the switchers' inductors against a field sensor;
- a converter's heat against a crystal, a temperature sensor or a
  thermistor that must not read it.

Each is a push written by hand. A source that is not a board part (a
magnet bonded to the case) is a hand-computed point in the script, which
stays put when the part it belongs with moves. The facts are the parts'
own (what a part emits, what another tolerates), and they belong on the
parts, in the capture.

## Design

**The source as a footprint.** placemat reads a source from any footprint
that carries `Pm.Emits`, wherever the footprint came from. A source that is
not an electrical part (a case-mounted magnet) is drawn by the board's own
project as a footprint: its outline, the pads it lands on, and its source
point in its own frame. Drawing it is the project's work, not placemat's.
Placed like any part, it carries its push as it moves or turns.

**Annotations.** Two new `Pm.*` keys, forwarded into footprint fields like
the others (capture.md):

| key | on | value | means |
|---|---|---|---|
| `Pm.Emits` | a source | `<kind>:<value><unit>@<r>mm^<falloff>`, several joined by spaces: `magnetic:3.2mT@13.5mm^3 heat:15C@5mm^1` | it emits `kind`, `value` at `r` mm, falling off as `r ** -falloff` |
| `Pm.EmitsAt` | a source | `x,y` in mm in the footprint's own frame, or `pad:<number>` | where the emission is centred (default: the footprint's origin) |
| `Pm.Limit` | a sensitive part | `<kind>:<value><unit>`, several joined by spaces: `magnetic:0.5mT heat:5C` | the most of each kind it tolerates |
| `Pm.SensesAt` | a sensitive part | `pad:<number>` | where it senses (default: its body centre) |

- `kind` is free text: `magnetic`, `heat`, or anything else. A source and a
  sensitive part pair when they name the same kind.
- A source's unit and a limit's unit for one kind must match. A mismatch
  is refused when the run starts, naming both parts.
- `Pm.Aggressor` and `Pm.Sensitive` keep their meanings (a switch node, a
  sense net, for the copper checks). The new keys are about fields and
  heat, not copper.

**Pairing.** At each run placemat pairs every part carrying a `Pm.Limit`
of a kind with every part carrying a `Pm.Emits` of that kind, in cells
and loose alike. Each pair acts as a push with the same model,
`value(r) = v_ref * (r_ref / r) ** falloff`:
- **Hard limit:** the later-placed part of a pair may not stand where the
  summed value of all its placed sources exceeds its limit.
- **Soft price:** `score.push` times value/limit, as board.push gives.

**Order.** Unlike board.push, an annotated pair is judged by whichever of
its two parts is placed second: the distance is mutual. So no order
dependency is added and no cycle can form. Two parts that each emit and
limit the same kind (heat) are judged the same way.

**A part that measures a source.** A temperature sensor placed to read a
converter carries no heat limit: it is not sensitive to that source, it
measures it. Any rule to keep it close is written as today (`Near`, a
link).

**board.push stays** for a source no footprint carries (a point in the
enclosure). It adds to annotated pushes on the same item.

**Report.**
- Each pushed item's step notes each kind's modelled value where it
  landed, its limit and the nearest source.
- `placemat check` gains an `exposure` check: each sensitive part's
  modelled value per kind at its final place against its limit, pass or
  fail, naming the sources that contribute.

## Verification

- Parsing:
  - `Pm.Emits` with two kinds, `Pm.EmitsAt` as a point and as a pad,
    `Pm.Limit` with two kinds and `Pm.SensesAt`, each read from footprint
    fields;
  - a unit mismatch within a kind is refused, naming both parts.
- Pairing:
  - one source and one sensitive part of a kind act as the equivalent
    board.push: same disc radius, same refusal and the same landing;
  - two sources of a kind add;
  - a source and a part of different kinds do not pair.
- The source point:
  - a source whose `Pm.EmitsAt` is off its origin pushes from that
    point, turned and flipped with the footprint;
  - moving the source moves the push.
- Order: the part placed second carries the disc, whichever it is; two
  parts that both emit and limit heat raise no cycle.
- `placemat check` reports `exposure` pass and fail with its contributors.
- board.push on an annotated item adds to the annotated pushes.
- The full suite, a release, then the bench (a placement change for any
  board that carries the annotations; none of the bench's modules do).
