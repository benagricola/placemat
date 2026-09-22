# Shared Zener modules — instantiated, never copied

Cross-board building blocks. Each module is a SELF-CONTAINED folder:

    modules/<Name>/
      <Name>.zen           the circuit (the reviewable schematic)
      <Name>_layout.py     the layout script; its docstring is the module's
                           layout intent (datasheet layout section, as-built
                           structure, copper contract, accepted exceptions)
                           (regenerates the fragment; the artifact - hand
                           edits get folded back into it)
      layout/              the KiCad fragment stamped per-instance, its
                           layout.kicad_pro (required for stamping) + renders
                           (layout.png top-down, layout-iso.png isometric)

A new module ships all of these in its first commit. Board-specific facts
belong in the board's layout script, never here or in the root rules.

Boards instantiate with `Module("../modules/<Name>/<Name>.zen")` and pass
per-instance `config()` values (e.g. `Buck_SY8513FCC(rfb_top_value=...)`).
If a board needs a change to a shared module, STOP and ask - a divergent copy
defeats the consolidation strategy. Part wrappers shared across boards live in
the repo-root `parts/`.

Layout flow: the global `pcb-layout` skill governs; per-module electrical
rules live in each module's layout script; verify with real `kicad-cli pcb drc` +
both renders; commit the fragment once the cell's work verifies (the committed
fragment is the baseline a hand edit diffs against), not after every pass.

Shared library (not modules - one implementation of each mechanic, never a
private copy in a script):

| file | what it is |
|---|---|
| `board_layout.py` | `BoardLayout`: the board-level placement primitives on real geometry: stamp a cell (with plane-via stripping and re-drop), place_free for loose parts against the far face's holes, courtyards, silk and live copper, cell_clash with a spatial hash, settle_cell / settle_shift, compact, grid_align (fine-pitch pad rows onto the routing grid), plane (a filled zone on a net: the whole layer for a dedicated plane, or a vertex list for a shaped power region), edge_align, hard_edge / group_hard_edge, place_knob, rows (place_row, row_clear_of, tp_row), knockout labels, board pours with the foreign-pad check, outlines (chamfered, rounded) and mounting fixes/keepouts. Every board script uses it; a board script never carries a private placement primitive |
| `layout_helpers.py` | `ModuleLayout` (place, poly, track, via, stitch, save) plus the box/group/silk mechanics every layout script calls |
| `geometry.py` | the exact-polygon primitives: outline extraction at `ERROR_OUTSIDE`, `poly_dist`, the `ps_*` SHAPE_POLY_SET helpers, `inst_of`/`cell_of`, and a bbox-binned `SpatialIndex`. Used by `tools/module_clearance.py` and `tools/board_occupancy.py` as well, so a proposed shape and a committed one are measured by the same code |
| `layout_oracle.py` | `Oracle(board)`: what a proposed segment clears (`clear`, `corridor`), whether a pose collides (`fits`, `fit_in`), which nets are open (`connected`, `unrouted`), the ratsnest as a number (`airwires`: count, length, crossings, per net and per cell, internal vs external; `cell_nets`), the resolved net class (`netclass`, `clearance`) and a cell's handoff stubs (`frontier`, `facing`). Reached from a script as `L.oracle`; `L.check(allow_open=...)` fails a script that leaves a net open |

Roster (per-module layout rules: `<Module>/LAYOUT-INTENT.md`; the middleweight-local cells HalfBridgeLeg, PhaseSense and Tmc2160Cell live under middleweight/modules/):

| Module | Function | Used by |
|---|---|---|
| Buck_SY8513FCC | 48V async HV buck (rfb_top sets 5V/24V/servo rails) | Featherweight, Middleweight, Flyweight, Expansion |
| Buck_TPS563201 | 5V -> 3.3V sync buck | all MCU boards |
| IdealDiodeInput | LM5050-1 + 100V N-FET input ORing/reverse protection. BLOCKS reverse current (it is an ORing controller) - right for the Featherweight's control rail, wrong for a regen-capable node | Featherweight, Flyweight |
| ReversePolarityFet | Return-path N-FET reverse-polarity guard for NODE inputs: conducts both ways once polarity is right, so motor regen flows back to the trunk; blocks a reversed cable. Bus TVS + input cap included. (2026-09-03) | Middleweight |
| BrakeChopper | The machine's ONE regen brake chopper: LM393/TL431 comparator with hysteresis (trip ~57.3V / release ~55.3V at the trunk), gate driver on a zener 12V off the bus, 100V FET; external 22R/50W resistor at a board-level terminal. (moved off the nodes) | Featherweight |
| CanFrontendNative | MCP2542-only front end for native FDCAN | Featherweight |
| CanFrontendDiscrete | MCP2518FD + MCP2542 + CAN-MODE jumper. `jumper_style` as OptoSense (solder: CAN-TERM = 2-pad bridge, CAN-MODE = two 3-pad bridges) | Middleweight, Flyweight |
| the MCU cell | RP2350B + flash + crystal + USB 27R terminators + 1V1 LDO. Exposes QSPI_SS/RUN (McuButtons) and SWCLK/SWDIO (SwdHeader) as OPTIONAL io - a board fits either, both or neither | Middleweight, Flyweight, future BLDC |
| UsbC | USB-C port: connector + ESD + CC pulldowns + VBUS bypass (chip-side 27Rs stay in the MCU cell) | Middleweight, Flyweight, future BLDC |
| McuButtons | BOOT + RUN/reset buttons + MCU status LED, aligned on one access edge with knockout silk. Serves BOTH MCU families: `boot_com` picks the BOOT switch's rail (gnd = RP2350 BOOTSEL, v3v3 = STM32 BOOT0) and `fit_reset_cap` fits the DNF NRST cap | Middleweight, Flyweight, future BLDC, Featherweight (candidate) |
| SwdHeader | 1x4 2.54mm SWD debug header (GND/SWCLK/SWDIO/3V3) with knockout pin labels. Split from the MCU cell for OPTIONALITY: mates VERTICALLY (plug volume above, no board edge claimed), so a board decides whether to expose SWD at all and where | Flyweight, future BLDC (Middleweight omits it - sealed, see its BOARD-INTENT) |
| OptoSense | 24V opto field input. `jumper_style` config: "header" (2mm pin headers, default) or "solder" (open solder bridges - Middleweight only) | Featherweight, Middleweight, Flyweight, Expansion |
| PermitReceiver | 24V active-high PERMIT channel (energize-to-run). `jumper_style` as OptoSense | Middleweight, Flyweight |
| ProtectionCell | freewheel + drain TVS for low-side inductive outputs | Middleweight, Flyweight, Expansion |
| RelayDriver | ULN2003A low-side driver array | Featherweight, Expansion |
| Buck_LM5164 | 100 V **synchronous** buck, 1 A, LM5164 in SO-8-EP. The compact-rail alternative for footprint- and height-limited boards: no catch diode, 1 MHz switching with a 50 ns on-time floor, so the inductor drops to 4 x 4 x 1.65 and the cell to ~240 mm2 against the SY8513 cell's 256 with 95 mm2 of parts against 182. Its 1 A ceiling rules it out for the Flyweight's servo rails and the Expansion's 2 A IO rail - those keep `Buck_SY8513FCC`. | Middleweight (24 V and 5 V rails, under evaluation) |

Board-local modules (single-board use) stay under the board's own `modules/`
(a single-board interface cell, say) and move here on second use.

## Layout rules for every module

The cross-module rules the layout scripts and fragments must meet. A module's own intent (datasheet rules, as-built structure, copper contract, floor, accepted exceptions) is in its folder's `LAYOUT-INTENT.md`.

### Clearance floors: derived from the boards that stamp the cell

A fragment is generated with the workspace default in its own `.kicad_pro`,
but every board stamps it under that board's net classes. The floor a fragment
must meet is the strictest clearance any consuming board applies to its nets,
never the fragment's own default. Skipping this check is how three power cells
once shipped module-internal violations that only surfaced at board level.

Nobody maintains that number. `modules/clearance_floors.py` derives it: a
stamped footprint's `Path` is `<instance>.<path inside the fragment>`, so every
pad on a board traces back to the pad that produced it, and the board's net
class for that pad gives the clearance its net must hold - keyed by the net's
name inside the module. A cell on the 48 V bus comes back at 0.25 because a
board's HV class says so; the Breakout's own trunk classes put `PowerDrop.vin`
and `.gnd` at 0.40. Add a board, change a class, or stamp a cell somewhere new,
and the floors follow with no edit anywhere.

Two things a net class cannot express stay hand-written, in the module's own
`clearance.json`:

- **`floor` / `nets` RAISE the derived floor.** `IdealDiodeInput` holds 0.25
  across the whole cell: its `vin_raw`/`vout` derive that on their own, but the
  internal pass copper sits at the same potential under module-local net names
  that every board puts on its Default class. Only the schematic knows that.
- **`accept` excuses one named pair BELOW it**, with the arithmetic showing the
  part forbids the floor, and what the gap actually stands off.

Part-forced cases, all 0.200 mm pad-to-pad by construction: RP2350B QFN-80 at
0.40 mm pitch with 0.20 mm pads (the MCU cell, and every escape lane inherits it);
USB-C TYPE-C-31-M-12 at 0.5 mm pitch with 0.3 mm pads, whose fan-out lanes
measure 0.225 with floor-width traces (UsbC); MCP2542 TDFN-8 at 0.50 mm, plus a
2.00 mm THT header whose 0.600 mm inter-pad corridor leaves 0.200 each side of
a floor-width lane (CanFrontendDiscrete).

There is no margin target above the floor. The fab minimum is 0.09 mm
trace/space on multilayer boards (0.10 on 2-layer; JLCPCB) and the N17 was
built at a 0.10 mm design clearance, so a pair at exactly 0.20 carries more
than twice the manufacturing margin. Scripts land pairs exactly on the floor
(0.01 mm grids), never by eye.

How to check: `tools/module_clearance.py` (all root fragments, about 15 s; name
a board-local cell to include it). It measures the true minimum gap between
every different-net copper pair (pours, tracks, pads, vias) from real polygons,
judges each against the derived floor plus the module's own `clearance.json`,
and ignores same-footprint pad pairs as part geometry. Do not rely on
`kicad-cli pcb drc` alone: it collapses some pairs; use `--drc` to cross-check.
Every new or re-worked fragment comes back clean before it is committed. The
`<0.25` column is information, not a failure.

### Courtyards: every footprint carries one; it is an ASSEMBLY margin, not a body

Every `parts/` footprint carries exactly one `F.CrtYd` rectangle =
union(pad extents, 3D body) + `courtyard.excess_mm` from `fab-profile.json`
(0.10 mm, IPC-7351 "Least"), drawn by `tools/courtyard_audit.py --fix`
(idempotent; re-run it after adding a part; `tools/courtyard_audit.py` alone in
review, non-zero exit = a footprint is missing one). The body comes from the
part's own STEP/WRL model.

The excess is calibrated so the bucket means something. At 0.25 mm/side two
parts need 0.50 mm of pad gap to keep their courtyards clear, while this
ecosystem packs to a 0.20-0.25 mm floor, so a correctly packed board reports
overlaps by construction. At 0.10 mm `courtyards_overlap` fires at roughly the
house floor, so it is a HARD GATE: a hit means check the pad gap and fix it,
and the only acceptable survivors are same-net bbox interleaves (an inductor
beside its output cap), each recorded in that module's LAYOUT-INTENT.md. The knob is
`courtyard.excess_mm` in `fab-profile.json`; changing it must not move any
board (see the measures below).

Courtyard vs envelope: never measure a board with a keepout. `pcbnew`'s
`FOOTPRINT.GetBoundingBox()` unions every graphic layer including the
courtyard, so it answers "what does this part keep clear", not "how big is
this part". The three measures, and which one a layout script may use:

- `fp_bbox_mm()` / `fp_body_box_mm()`: the house placement box, pads +
  F.Fab + (courtyard deflated by `courtyard.excess_mm`). Everything that
  sizes an outline, an envelope, a pitch, an edge placement or a collision
  test uses this. Deflating by the same excess the audit added recovers
  union(pads, body), so the answer, and therefore every board, is invariant
  when the excess is retuned (verified by regenerating every design at 0.25
  and at 0.10: identical placements).
- `fp_phys_box_mm()`: pads + all drawn graphics, courtyard excluded. The
  DRAWN extent, not the on-board one: an edge connector draws its off-board
  half on silk (a CAZN M12's silk runs 17 mm past its pads; a USB-C's mouth
  1.9 mm past the board edge), so placing from it shoves the part inboard.
  Use it for silk questions and as the no-courtyard fallback.
- `fp_courtyard_box_mm()`: the raw keepout. For asking what a part claims,
  and even then prefer DRC's `courtyards_overlap`. Never for geometry.
- `silk_box_mm()`: silk graphics only, no ref/value text: what a
  `silk_overlap` gate is about.

Recorded survivors at the 0.10 excess, ecosystem-wide: "body-close" pairs
(bodies 0 to 0.2 mm apart, what a board packed to the house floor looks like),
same-net pad interleaves, and box interpenetrations under 0.2 mm with healthy
pad gaps (the `Buck_TPS563201` cell's `L1`/`C1` at 0.040 mm pad gap, both on
SW, is the canonical same-net interleave). Not one different-net pad gap under
the 0.20 mm house floor.

### Layout scripts must be REGENERABLE: impose the iteration order

`pcb layout` emits footprints in a different order every generation. A
script that iterates `board.GetFootprints()` / `GetTracks()` /
`PCB_GROUP.GetItems()` and then places, measures or first-matches on
encounter order is not regenerable from its own source. Rules:

- resolve every ref from the fresh netlist by NET SET (`find_by_nets`) and
  assert the hit is unique; a bare `next(fp for fp in board.GetFootprints()
  if ...)` is a bug even when it happens to work today. Where two parts share
  a net signature (two identical caps on the same nets) they are
  interchangeable by construction, so an assert that cannot order them is
  still complete; where a value distinguishes them, assert pad-net set plus
  a value fragment;
- sort any collection you iterate (`key=GetReference`), and give every `min` /
  `max` / `sorted` over measured geometry a tie-break key;
- a group's side or representative member is the lowest-ref member, never
  the first one the group yields;
- adding ANY component whose prefix already has instances in a module can
  renumber existing refs unpredictably; re-verify every ref against a fresh
  generation before trusting old ref strings.

Proof procedure: generate twice from clean, run the script on each, compare
placements + copper as `Counter` multisets at 0.001 mm; 0 differences
required.

### What belongs in a module

**Enclosure-driven parts are a BOARD concern, not a module's**: anything whose placement is dictated by the case rather than the circuit - switches, USB/edge connectors, anything needing finger or tool access - must NOT live inside a functional module, or it dictates that module's (and the MCU's) board position. Split it into its own placeable cell (`modules/UsbC`, `modules/McuButtons`). The converse holds: parts with no enclosure demand stay with their circuit (OptoSense keeps its own NPN/PNP jumpers and series LED). **Switches and LEDs cluster together when they control or indicate the same IC or behaviour** (BOOT + RUN + MCU status), aligned, with knockout silk labels.

### The module boundary: io nets are the board's, everything else is the cell's

A cell's `io()` list in its `.zen` is the boundary. Every net on that list
is handed to the board at a pad or an escape via (the copper contract in the
cell's intent file); every other net is the cell's own to close before it
saves. `ModuleLayout.io_nets()` reads the list from the .zen beside the
fragment, `ModuleLayout.airwires()` splits the fragment's open nets by it,
and `tools/airwires.py` prints both for any fragment. On a consuming board
the oracle derives the same boundary from the stamped group (`cell_nets`).
An open internal net in a saved fragment is a defect, not a handoff.

### Verification: what runs after every generation

- `kicad-cli pcb drc` in the layout dir (with the `.kicad_pro` beside the
  board, or the check runs against KiCad defaults instead of the classes).
  Allowed buckets for a standalone fragment, per net: `invalid_outline` (no
  board edge), `via_dangling` on plane-drop vias of nets that have a board
  plane or a documented strap landing, the library self-clips listed in the
  module's LAYOUT-INTENT.md. Anything else is a defect.
- `tools/module_clearance.py`: the per-net copper sweep (the primary
  clearance check; DRC is the cross-check).
- `tools/courtyard_sweep.py <fragment> 0.10 [ox oy]`: all-pairs footprint
  courtyard sweep (real F.Courtyard polys, convex-hulled, SAT-separated).
  Cross-check against DRC's `courtyards_overlap` on first use; if they
  disagree the sweep is wrong. A 0.000 mm gap is a defect, not a pass: sweep
  with a margin (0.05-0.10) and treat any zero-margin pair as work.
- `tools/poly_audit.py <fragment>`: every copper polygon's narrowest section
  against the net class width, and ground pours flagged (a module never
  pours ground).
- Cap-to-cap: adjacent 0402s need 0.97 mm centre spacing (courtyard), not the
  0.86 mm a pin-pitch-derived slot chain hands you; opening a pair by 0.11 mm
  pushes both caps into their neighbouring fan lanes, so re-verify the lanes
  after any spread.
- Renders: `pcb render` ignores the board's stackup colours unless
  `--use-board-stackup-colors` is passed, and generated fragments carry no
  `(stackup)` block. The shared helper's `patch_stackup_colors()` inserts a
  default 2-layer stackup when none exists and `ModuleLayout._render()`
  passes the flag, so every fragment renders green mask / white silk.

N17 reference blocks worth lifting (`mnb-ultralight-n17/`): the routed CAN-FD
front end (MCP2518FD + MCP2542 + PESD2CAN + split term + common-mode ferrite,
transceiver stacked directly above controller at board edge), and the buck
placement pattern (inductor hard against the SW pins, input caps
via-stitched). N17 has no ideal-diode cell and no optocoupler; those come from
datasheets only.

---
