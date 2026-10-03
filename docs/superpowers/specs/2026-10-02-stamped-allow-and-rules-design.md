# A stamped cell's keepout allow= and clearance rules

## Problem

A module declares two things for KiCad's DRC that did not reach the board
that stamps it.

1. A keepout's `allow=` nets. A module's keepout excludes tracks, vias and
   pads on some layers and lets GND through. The module's own run set the
   allowed vias aside (`permitted by their keepout 8`), because KiCad's
   rule area has no list of nets and flagged them as `items_not_allowed`. The
   board that stamps the cell read the region with no allow list, counted the
   same vias as `items_not_allowed`, and KiCad's DRC flagged them when the
   board was opened. The rule area was written `(vias not_allowed)` either way.
2. A module's `board.rule(clearance=..., between=...)`. The rules are written
   to a `.kicad_dru` beside the module's board, which pcb layout does not
   stamp, so the parent's DRC judged the cell's copper at the net class
   clearance and reported violations the module had declared acceptable.

CHARTER, "Judged as KiCad judges": the parent's checks and the .kicad_dru it
writes must give the verdict KiCad gives on the cell's copper.

## Design

### A stamped cell brings its own

A stamped cell already brings its regions and labels. By the same rule it
brings its keepouts' `allow=` nets and its clearance rules. Both travel in the
fragment board, as the layer declaration of a keepout and the faces note do,
because the fragment's `.kicad_dru` is not reachable from the board that
stamps it (pcb layout copies the module's board, and the parent does not know
where the module's layout folder is).

### Keepout allow=

A rule area is written allowing the types the allowed nets keep (the
intersection of `excludes` with tracks, vias, pads), and a custom rule forbids
those types to every other net:

    (rule "keepout antenna allows GND"
      (constraint disallow track via pad)
      (condition "A.intersectsArea('<zone name>') && A.NetName != 'GND'"))

KiCad judges the area's own layers, so the rule needs no layer clause.
Fill stays excluded: `allow=` is for copper the script draws.

The zone name carries what the rule needs: after the layer marker,
` {allow GND,SIG | tracks,vias,pads}` (net names percent-escaped for `,` `|`
`}` `]` `%`). pcb layout appends its `_1` after it. `split_marker` strips the
allow marker too, so a name's base is unchanged.

The parent reads the marker for each rule area in a cell's group. The
nets are mapped to the parent's names: the most particular of
`<cell>.<net>`, `<parent sheet>.<net>`, ... and `<net>` that the board has.
`RuleArea.allow` holds the mapped nets and `RuleArea.relaxed` the types;
`excludes` includes the relaxed types, so the region still forbids them to
other nets everywhere placemat reads it (via sites, the router's breach check,
queries). Those readers skip a copper item whose net is in `allow`.

The parent writes an `AllowRule` for each stamped area with `relaxed` types,
and for each of its own keepouts with `allow=` nets, into its `.kicad_dru`.
A region whose nets could not be mapped forbids the types to all nets.

A fragment run before this change has no marker; it reads as before. Running
the module again writes it.

Parts named in `allow=` are not carried.

### Clearance rules

A fragment run writes its clearance rules as User.Comments texts, one per
rule: `placemat rule clearance=0.1 between=A,B why=<escaped>`. Only a
fragment writes them (`board.rect(..., draw=False)`), and never the rules of a
part's `Pm.KeepOut` (`of=`), which the parent derives from the part. The
parent drops the stamped notes when it writes its board, as it does the faces
note.

The parent reads each note in a cell's group as a `Rule` on the cell
(`CellGeom.rules`) and, when a `Board` is built, adds the rules to its own,
before any it declares:

- `within=` the cell, in addition to `between=` or `on=`. `Rule` takes both
  scopes (the script's `board.rule` still takes one). KiCad condition:
  `A.memberOf(cell) && B.memberOf(cell) && (<nets>)`. placemat's
  `ClearanceRules.match` and the native `ClearanceRule` require both.
- nets mapped as for `allow=`. A module's `within=` its own cell takes that
  cell's stamped group (`<cell>.<name>`).
- the rule's name is `<why> [<cell>]`.
- a rule whose net or cell the parent lacks is not carried, and the run says
  so as a setup finding.

Precedence: the last rule that matches a pair decides, in KiCad and in
placemat. The stamped rules come first, so a parent's `board.rule` on the same
pair decides. Between two stamped cells' rules, cells in name order.

A parent's `board.rule(..., within=Cell(...))` that repeats a module's rule
can be removed once the module is run again.

## Verification

- Pure tests: marker round trip through pcb's `_1` and for escaped names;
  net mapping; `AllowRule` text; rule note round trip; stamped rules scoped to
  the cell and ordered before the parent's; unmapped net and cell findings;
  `ClearanceRules.match` and the native rule with both scopes (Rust unit test;
  the native conflict fuzz includes one).
- kicad-cli on a board with the rule area and the .kicad_dru: the allowed
  net's via, track and pad pass; another net's via, track and pad are
  `items_not_allowed`; items outside the region, or on a layer it does not
  cover, are not flagged. Without the rule the area allows every net; with no
  allow list it flags the allowed net as before.
- A stamped region (a rule area in a group, the marker in its name) read by
  `read_board`, written by `apply_plan`: the parent's .kicad_dru has the rule
  over the parent's net names, and kicad-cli flags only the net that is not
  allowed.
- A cell of two pads 0.12 mm apart with the module's 0.10 rule in its group:
  the parent's .kicad_dru holds the rule, kicad-cli reports no clearance
  violation; with no note it reports one.
- A real board (fixtures/fairing/core, its antenna cell) and a real module
  (fixtures/fairing/modules/gnss_antenna): recorded in the commit message.
