# `placemat nets`, and parts with no order number

Date: 2026-09-29
Status: approved 2026-09-29 (Ben: implement unless a decision is needed)
Source: a board's PLACEMAT_GAPS.md, 2026-09-29 "which nets span the core
furthest" and "which footprints carry an LCSC number"

## The problem

To choose which nets to declare as copper rather than leave to the router,
a board needed a table of every net. Placemat reports airwires,
crossings and congestion for the whole board, and closure for a route, but
nothing per net. A board session wrote pcbnew scripts to get it.

`placemat parts --field Lcsc --field Mpn` lists order numbers, but nothing
flags a placed part that has neither.

## The change

1. **`placemat nets <layout.kicad_pcb | script> [--sort COLUMN] [--net NET ...] [--json]`**
   gives one row per net with at least two pads:
   - its pad count and the parts it joins (refs, or instance paths with
     `--inst`);
   - its span, the minimum spanning tree over its pads' centres in mm;
   - its routed length, the sum of its track and arc segments;
   - its detour, routed length over span (`-` when unrouted);
   - its via count, and the copper layers its tracks use;
   - whether it is a pour net (`plane_nets_of`).
   - Rows are sorted by span, largest first, by default; `--sort` takes any
     column name.
   - A script is resolved to its board as `placemat parts` does.
2. **`placemat parts` warns for a placed part with no order number.** One
   line per part: "no order number: R40 (usbpd.r_wet)".
   - "No order number" means none of the fields in `[parts] order_fields`
     (default `["Lcsc", "LCSC", "Mpn", "MPN"]`) is present and non-empty.
   - A part carrying `dnp` is skipped.
3. **Docs**: api.md's command list and a paragraph for each.

## Verification

- `nets` on the breakout: the pad counts, spans (against a hand-computed
  MST for two nets), routed lengths and via counts match pcbnew's own
  counts. `--sort`, `--net` and `--json` work.
- `parts` warns for a synthetic part with neither field, not for one with
  either, and not for a `dnp` part. The setting changes which fields count.
