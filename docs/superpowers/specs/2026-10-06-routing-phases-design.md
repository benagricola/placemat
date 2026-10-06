# Routing phases

Status: draft for review, 2026-10-06; release line 0.100.x.

## Problem

A route today runs four fixed stages in a fixed order: differential pairs, the `[route] islands` pour joins, one pass per
clearance above the Default class, and everything else (`kicad/route.py` `_route_board` 1006-1283). The project cannot
choose what is routed first, at what width, or on which layers, except through the few settings each stage reads.

On the fairing core this has two costs:

- **Power legs.** VBIKE's 4.6 A legs and its microamp taps are one net. `islands` gives a net one width, so the legs and
  the taps cannot be routed differently: with neck-down off the taps strand, with it on the legs narrow. The project
  therefore declared the legs as copper in the script, and declared copper reserves its lane during placement. That
  over-constrained the power cells: in the organic-vs-clean experiment (scratchpad/exp/REPORT.md) a script without the
  hand-placed power blocks could draw none of its four legs.
- **Buses and other groups** (the display SPI, the other SPI buses) have no way to be routed before the rest, together,
  on a chosen layer.

## Goal

The project states its routing as named phases in `placemat.toml`. Each phase routes a chosen set at its own width,
layers and router settings; its copper is fixed for the phases after it. Closure is reported per phase, and explore can
rank variants by named phases, so placement serves the legs and the buses by being judged on them rather than by
reserving their lanes.

## Decisions taken with the user

- Phases are required. There are no implicit stages; placemat writes an example `placemat.toml` with default phases
  for a project to start from.
- Connections are structured tables, never strings to parse.
- Running one phase uses the earlier phases' copper when it still matches the board and routes any missing or stale
  earlier phase first, saying so. A flag routes it against whatever copper the board has.
- A phase's copper lasts for one route of one placement. A new placement routes every phase again. Keeping copper
  across placements stays the explicit `--adopt`.
- Placement serves the phases through explore's ranking by phase closure, with no lane reserved.
- Routing some, not all, connections of a net is done in our KRT fork (https://github.com/benagricola/KiCadRoutingTools),
  not by a placemat workaround.
- Phase names are the project's. The built-in stage names (pairs, islands, classes, main) go.

## The form

```toml
[[route.phase]]
name = "power-legs"
current_paths = true           # each carrier-to-carrier pair the current-path check knows from Pm.I
width = "current"              # or a number in mm
layers = ["F", "B"]            # default: every copper layer
neckdown = false               # the router's pad neck-down; default true
router_args = []               # extra KRT flags for this phase only

[[route.phase]]
name = "vbike-leg"             # the same, stated one connection at a time
width = "current"
[[route.phase.connections]]
from = { part = "inputpower.j_vin", pad = "2" }
to   = { part = "protect.q_revpol", pad = "VBIKE" }

[[route.phase]]
name = "diff-pairs"
pairs = true                   # the differential pairs the net classes declare

[[route.phase]]
name = "buses"
interfaces = ["Spi", "I2c"]    # every instance in the capture, each routed together as one bus
layers = ["F"]

[[route.phase]]
name = "power"
net_types = ["Power"]
width = "current"

[[route.phase]]
name = "wide-clearance"
net_classes = ["50Ohm SE", "VCONN"]

[[route.phase]]
name = "power-taps"
nets = ["VBIKE", "VSHUNT", "VBUS"]
width = 0.3

[[route.phase]]
name = "signals"               # with no selector: every connection still open, at the net classes' widths
```

### Selectors

A phase has at most one selector. A phase with none takes every connection still open.

| Key | Selects | Source |
|---|---|---|
| `nets` | nets by name or glob (`DISP_*`); `!NAME` excludes | the board's nets |
| `net_classes` | every net in these KiCad net classes | the capture's `board_rules.zen` net classes, which reach `layout.kicad_pro` |
| `pairs = true` | the differential pairs: the capture's `DiffPair` interface instances | the capture, through the Zener fork (below) |
| `buses` | a list of buses, each a list of net names or globs | the board's nets |
| `connections` | pad-to-pad connections, each `{from = {part, pad}, to = {part, pad}}`; a pad by number or by net, as `PadRef` takes it | the capture |
| `current_paths = true` | every pair of carriers on each net with a `Pm.I`, pad to pad (`checks._pairs(by_pad=True)`) | the capture's `Pm.I` |

A phase selects only connections still open when it runs. A connection an earlier phase joined is not routed again.

| `interfaces` | every instance of these Zener interface types (`Spi`, `I2c`, ...), each instance one bus; or instances by path (`"DISP"`) | the capture, through the Zener fork (below) |
| `net_types` | every net of these Zener net types (`Power`, `Ground`, `Gpio`, a custom type) | the capture, through the Zener fork (below) |

**The capture's grouping.** The capture already knows each bus and each power net: Zener's interface instances
(`DISP = Spi(...)`) and net types (`Power`, `Ground`). Today the generated `default.net` and `snapshot.layout.json`
carry only net names and pins. We maintain the Zener toolchain's fork (https://github.com/benagricola/pcb, ~/work/pcb),
and it gains a sidecar the layout writes beside the board.

`nets.layout.json` holds one record per net:
- its flat name;
- its type, from `pcb_sch::Net.kind`;
- the type's fields (voltage, impedance), from `properties`;
- the interface instances it belongs to: a list, since a net can sit in several. Each entry holds the instance path, the
  interface type name and the member name.

It is written from the full schematic in `pcb-layout/src/lib.rs` beside the netlist write (scratchpad/zener-net-export.md,
file:line there). It comes in two stages:
1. **Type and fields:** about 40 lines, Rust only. The type survives evaluation today.
2. **Interface membership:** about 120-180 lines. It does not survive evaluation today. The instance, its type and its
   field-to-net map are recorded where the instance is created and carried to the schematic's nets. One case must be
   checked before this is sized: an instance whose name is inferred from its assignment (`DISP = Spi(...)`) has no root
   name recorded.

The first version also moves two circuit facts out of placemat's config and into the capture (decided with the user):

- **Differential pairs:** each `DiffPair` interface instance in the file is a pair, its `P` and `N` members the two
  nets. `pairs = true` selects them. Today pairing is derived from net-class patterns (`pairs.board_pair_list`), which
  duplicates what the capture states. The net classes still give a pair's width, gap and impedance.
- **Net clearance:** a clearance a net needs for electrical reasons, such as a high-voltage net, is stated on the net in
  the capture. The fork adds a `clearance` field to the stdlib net types, written to the file per net. It replaces
  `[route] net_halos` in `placemat.toml`. That setting is removed with a migration entry, and a `placemat.toml` that
  still has it is refused, naming the capture field.

The file is versioned (`"version": 1`) and keyed by net name, so later fields can be added without breaking a reader.

placemat reads the sidecar into the board geometry. A board generated without it, by an older toolchain, has no
`interfaces` or `net_types` to select by: a phase that uses them is refused, saying the generator does not export them.

### Width

- A number: that width on every layer.
- `"current"`: each connection is sized from the lesser current of its two carriers, by IPC-2221 at `[check] rise_c`,
  per layer, with the inner constant on an inner layer. This is the sizing `check current-path` uses (`checks._need_mm`).
  A connection with no stated current is refused when the phase starts, naming it.
- Omitted: the net classes' widths.

### Other keys

- `layers`: the copper layers its tracks may use. Vias still pass through the others.
- `neckdown`: the router's pad neck-down, on by default.
- `router_args`: extra KRT flags for this phase. The flags placemat owns are refused, as `[route] router_args` refuses
  them today (`settings._ROUTER_OWNED`).
- `clearance`: not a key. A phase's nets keep their net classes' clearances. When a phase holds nets of different
  clearances, it is routed in one call per clearance, widest first, as the class stage does today, because KRT spaces a
  call at its widest clearance.

### Settings that go

`[route] islands`, `[route] pair_layers` and the fixed stage order are removed, with migration entries:

- an island becomes a phase with `nets = [...]` and `width`;
- a pair-layer list becomes a phase with `pairs = true` and `layers`.

A `placemat.toml` that still carries them is refused, naming the phase that replaces each. `[route] router_args` stays
and applies to every phase.

### No phases

A route of a project with no `[[route.phase]]` is refused:

    route: no routing phases in placemat.toml; `placemat route --example-phases` prints a starting set

`placemat route <script> --example-phases` prints a `[[route.phase]]` block for the board. It lists the differential
pairs if the board has any, the net classes above Default, and the nets with a stated current, with `width = "current"`.
It ends with a final phase that takes the rest. These defaults reproduce today's stages with today's behaviour.

## Routing only some connections of a net (KRT fork)

KRT always closes a whole net: it groups the net's pads by existing copper and joins the groups (connectivity.py
`find_connected_groups`). The fork gains:

- `--connections FILE`: a JSON list of `{net, from: "REF.PAD", to: "REF.PAD", widths: {layer: mm}}`. The router routes
  only these pad pairs, each as a two-terminal task on its net, at the given width per layer, and leaves the net's
  other pads alone. The tasks may use the net's existing copper. A task whose ends are already joined is skipped and
  reported as such.
- Each task's outcome goes in the `--json-out` summary: joined or not, its length and its narrowest width per layer.

placemat writes the file from the phase's `connections` or `current_paths`. The change is made in the fork, on a branch
off `placemat/upstream-2026-10`, with its own tests in KRT's suite, and pushed to the fork. It is never offered upstream.

Buses use the router's bus mode (`--bus`, py_router/route.py:7139), one call per bus with only that bus's nets, so
detection groups just that bus. If detection does not group a declared bus (fewer than its minimum nets, or the
geometric filter), the fork gains a flag that takes the bus's nets as one group as given.

## Running

- `placemat route <script>` routes every phase in order. `run --route` and explore's `--route-best` do the same.
- `placemat route <script> --phase NAME` routes up to and including NAME. Earlier phases whose kept result still
  matches are reused; any other earlier phase is routed first. The output says which were reused and which routed.
- `--only` routes just that phase against the copper the board has now, and names the earlier phases that have no
  copper on it.
- **The kept result of a phase.** Its key is the digest of:
  - the board's placement and declared copper;
  - the keys of the phases before it;
  - the phase's own definition;
  - the router version and placemat version.

  It is the stage digest chain of `route_state.py`, with the phases as the stages. A phase whose key changed is routed
  again, and every phase after it is dropped.
- A phase's copper is locked (`lock_copper`) before the next phase runs, as stages are today.

## What is reported

Per phase, in `route.json` (`phases`), the summary line, the studio's route view and `watch --summary`:

- the name, the selector and the number of connections asked;
- connections joined, connections left open (each named), and the phase's closure (joined over asked);
- for a phase with a width, the width judgement on the routed board, per layer. This is the 0.99.29 rule: against the
  asked width, or against the current for `width = "current"`. Under it is a critical `route.width` finding naming the
  phase.
- seconds, and whether the phase was reused.

The board-wide closure and DRC stay as today and are computed once after the last phase.

## Explore

`--route-best` routes each candidate variant through every phase. `--route-rank PHASE[,PHASE...]` ranks the routed
variants by those phases' closure, in order, then by the board-wide clean closure, then by the run score. Without it,
the board-wide clean closure ranks, as today.

## What this replaces

| Today | With phases |
|---|---|
| Fixed stages pairs, islands, classes, main | Named phases in the project's order |
| `[route] islands` (one width per net) | a phase with `nets` or `connections` and its own width |
| `[route] pair_layers` | a phase with `pairs = true` and `layers` |
| Declared power-leg copper reserving lanes | a phase with `current_paths` or `connections`, `width = "current"`; explore ranks by it |
| `--exclude` plus `--adopt --partial` per pass, by hand | `--phase NAME` |

Declared copper stays a script feature, for a lane that must be fixed: a feed, a guard, a pour. The skill teaches phases
for power legs and buses, and declared copper only for fixed geometry.

## Testing

- Zener fork:
  - `nets.layout.json` carries each net's type, fields and interface instances, including an instance whose name is
    inferred and an interface passed into a module (the fork's own tests);
  - a `DiffPair` instance arrives as a pair, and a net's `clearance` field arrives as its clearance;
  - `[route] net_halos` is refused, naming the capture field;
  - placemat reads it, and a phase using `interfaces` on a board without it is refused.
- Settings:
  - parsing and validation of `[[route.phase]]`: each selector, a phase with two selectors refused, a duplicate name
    refused, a removed setting refused with its replacement named;
  - `--example-phases` on a board with pairs, classes and currents.
- Phase engine:
  - order;
  - copper locked between phases;
  - the kept-result chain: an edit to phase 3 reroutes phases 3 and later and reuses 1-2;
  - `--phase` routes stale earlier phases first;
  - `--only`.
- Widths: `"current"` per layer, inner and outer; a connection with no current refused.
- KRT fork: `--connections` routes two of a net's three pads and leaves the third, at per-layer widths, with a summary
  per task (KRT's own tests).
- A real board: the fairing core's power legs as a `current_paths` phase, against the declared-copper run, for closure
  and for the current-path check on the routed board.
- Explore: `--route-rank` orders variants by a named phase.

## Out of scope

- Length matching and tuning per phase.
- Keeping phase copper across placements, beyond `--adopt`.
