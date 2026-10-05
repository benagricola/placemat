# Skill check: usbtcpc

## Run 1 (skill before 8b306ad)

Checker:
```
c_vdd (bypass) has no alternative: a bypass whose side or turn is free gets one
r_irq (pullup) has no alternative: a pull-up whose side or turn is free gets one
r_vconn sets the module's extent (protruding): it needs an alternative or a '# extent:' line saying why it has none
```

Result: fail. No alternative declared; the passives were placed as block satellites, which take none. The skill's wording changed in 8b306ad.

### Work log

# Work log: UsbTcpc module layout

## 1. Read the skill
Ran: read SKILL.md; api.md indexes, Placement, Escape, Blocks, Modules, Arrangements, facts command.
Read: module = fragment run via `placemat run modules/X/X_layout.py`; needs `<Name>_layout.py` beside the .zen (UsbTcpc_layout.py); frame = `board.rect(fit=True)`; faces declared with board.faces; `placemat facts <script>` needs a script that imports, so write a first script before facts.
Read in the .zen: U1 RT1715 WLCSP-9 0.4 mm pitch 3x3 (A1 CC2, A2 VBUS(sense), A3 V3V3, B1 VCONN, B2 IRQ centre ball, B3 SCL, C1 CC1, C2 GND, C3 SDA). Satellites: c_vdd (V3V3), r_vbus (VBUS), r_vconn (VCONN to GND), c_cc1, c_cc2 (CC to GND), r_irq (IRQ pull up). io: GND V3V3 VBUS USB_CC1 USB_CC2 SCL_PWR SDA_PWR PD_IRQ. Pm.Sensitive on the CC caps.
Decided: write the proposal as the script's opening comment, then the first script, then facts.

## 2. First script, facts, preview
Wrote UsbTcpc_layout.py (first draft: rect(fit=True), faces outward west / handoff east, tcpc required, six satellites as bare place()).
`placemat facts`: layers In1/In3/In4 flagged power with no plane(); facts unconfirmed; via micro/blind/buried "no"; rise 10 C. Not confirmed (no way to ask the user from here, and the module's own board has no plane to carry).
`placemat preview`: 7 placed, 2 warnings (CC2 crosses VBUS, VCONN crosses GND), but it says the cached generation is out of date.

## 3. Run: blocked
`placemat run UsbTcpc_layout.py` fails at generation: UsbTcpc.zen loads `../../../../adapted/parts/Richtek_Tech_RT1715WSC.zen` and `../../board_rules.zen`, and neither exists in the staged tree (stage_usbtcpc has only board/modules/usbtcpc, board/placemat.toml, board/fragment_frame.py). pcb error: "Relative path escapes beyond package root".
I tried to copy the missing project files (pcb.toml, fab-profile.json, board_rules.zen, the part wrapper, symbol and footprint) from the project the fixture came from into the stage. The copy was denied. Stopped there; not retried by another route.

## 4. After the coordinator's staging fix
11:39:58 run of the draft restored from cache and completed (run f8e8249f): 7 placed, extent 4.59 x 6.67 mm 65% empty, DRC clean, unconnected 11, score 77.5 (escape_crossed 40, crossings 16, airwire 21.5); warnings: VCONN crosses GND, CC2 crosses VBUS (escape_crossed); notice r_vbus sets the extent, no alternative; facts unconfirmed (left as told). Render: parts scattered round U1, no links drawn.
Changed the script to one board.block(tcpc, satellites=[...]) placed required. Preview: 8 placed, 2 warnings (IRQ crosses GND, V3V3 crosses GND), compact; preview said the cached generation was out of date (adapted/parts/..., RT1715WSC.kicad_sym, pcb.toml "changed").
Runs at 11:40:52 and 11:41:29 both fail again in `pcb layout`: stage_usbtcpc/adapted and stage_usbtcpc/pcb.toml are not there (only board/ exists), so the cache record in .placemat/generated/UsbTcpc.inputs.json (which names them) no longer matches and placemat regenerates. The 11:39:58 run worked while that state held; it has since reverted. I did not copy anything. Stopped; not retried further.

## 5. Finished
Cache restored. Ran: block of the six satellites; GND planes on In1 and In4 (the facts flagged them); tracks pad to pad for CC1, CC2, VBUS, VCONN on F.Cu; GND via at each GND pad (FreeSpot); PD_IRQ via in the centre ball plus a via at r_irq, joined on In2.
First centre-ball via at the default 0.45 mm shorted to its eight neighbours (13 critical, 4200 score). Used 0.25/0.15 mm, the size the project's board_rules comment names for this ball: DRC clean. This is a fab fact I could not confirm with the user.
V3V3 track A3 -> c_vdd -> r_irq failed (0.07 mm from VBUS copper; suggestions drop c_vdd or go to the back). Removed it: V3V3 is the board's rail and ends at its pads.
Final run: DRC clean, unconnected 2 airwires (V3V3 only), no critical, warnings: facts unconfirmed (left as told); notices: c_cc1 and r_vconn set the extent, no alternatives. Score 3.2 mm. Not done: SCL_PWR and SDA_PWR have no lanes (no part at them), no arrangements declared, bypass cap c_vdd stands 1.7 mm from A3 (the block puts it on the corner diagonal).

## Run 2 (skill at 8b306ad)

Checker:
```
c_vdd (bypass) has no alternative: a bypass whose side or turn is free gets one
```

Result: one criterion not met by the letter. c_vdd has no alternative; the script gives its reason on an `# extent:` line (no other spot keeps the loop to A3). The transcript criteria are met: the agent read run.json's arrangements, fixed the refused r_irq.back (escape_walled) until it was offered, and finished with five arrangements offered and the default DRC clean.

### Script

```python
"""UsbTcpc: the RT1715 Type-C port controller (WLCSP-9) and its passives.

A module fragment for the core, laid out round the RT1715 at the origin and
framed to fit (board.rect(fit=True)). The RT1715 is a 3x3 ball grid at
0.4 mm pitch (placemat measure --pads):

    A1 USB_CC2     A2 TCPC_VBUS   A3 V3V3        north row
    B1 TCPC_VCONN  B2 PD_IRQ      B3 SCL_PWR     middle row
    C1 USB_CC1     C2 GND         C3 SDA_PWR     south row

Sides, at the cell's rotation 0:
- west column is the receptacle's side (CC1, CC2, VCONN): the VCONN
  resistor stands level with B1 so its lane runs straight out of the middle
  row, and the two CC caps lie flat north and south of it, their CC pads at
  its IC end. A cap level with a corner ball would wall VCONN in: a 0402 is
  wider than two ball pitches, and its pad would stand 0.01 mm off the
  VCONN lane.
- north row is the supply side: VDD's bypass stands over A3 with its V3V3
  pad a lane east of A2, so TCPC_VBUS runs straight north from A2 to its
  4.7k, which stands over A2 with its TCPC_VBUS pad level with the ball.
- east column hands off to the host (SCL, SDA, and INT_N through its
  pull-up): the I2C balls leave east for the parent board's router, with
  no part standing east of the IC; the pull-up stands east of the bypass,
  sharing its V3V3 pad, its PD_IRQ pad north and out of the I2C balls' way.
  A ball grid's corner has no row, so board.escape refuses the column.
- south: GND at C2 drops to the ground plane.

B2 (PD_IRQ) is the centre ball: at 0.4 mm pitch the 0.16 mm class leaves no
lane between balls on the component face, so it is walled in within the
module and its way out is a via in the ball's pad, at the smallest via the
board's rules allow (the fab fills and caps it). The parent's router joins
the via to the pull-up and the host.

Relationships: VDD bypass is the one loop that matters (SHORT, at the pin);
the CC caps and VCONN resistor are ESD/filter parts whose exact spot on
their line is free; TCPC_VBUS and PD_IRQ are high-impedance sense/interrupt
lines; the I2C pair are ordinary signals. Nothing carries current worth
copper.

Richtek RT1715 DS1715-04 (March 2020), p3 Typical Application Circuit and
Table 1; p4 Table 2 (the capture's comment carries the component choices).
"""
from placemat import (board, Along, Alt, Beside, CopperLayer, Edge, Face, FreeSpot, LinkWeight, Location, Net, PadRef,
                      Part, Past, Pin)

TCPC = Part("tcpc")
GND = Net("GND")
V3V3 = Net("V3V3")

# The smallest via the board's rules allow: min_via_diameter and
# min_through_hole_diameter of the generated project's design rules
# (board_rules.zen CONFIG). The only via that clears B2's neighbours at
# 0.4 mm pitch; placemat occupancy --via-near tcpc.B2 --in-pad found no spot
# for a 0.3 mm one.
VIA_MIN_SIZE = 0.25
VIA_MIN_DRILL = 0.15

# The arrangements with the pull-up on the front beside the bypass, and
# those with it on the back under the IC: each set has its own copper.
IRQ_FRONT = ("default", "r_vconn.upright", "caps_upright")
IRQ_BACK = ("r_irq.back", "r_vconn.upright+r_irq.back")

board.faces(outward=Edge.WEST, handoff=Edge.EAST,
            why="the CC column faces the receptacle; I2C and the interrupt leave east to the host")

# The module's main part at the fit frame's origin (api.md, Modules).
board.place(TCPC, at=Location(0, 0), rotation=0, why="the fragment's main part at the frame origin")

# West: the receptacle's side. VCONN's 1k level with B1 so its lane runs
# straight west out of the middle row; its GND pad outward.
board.place(Part("r_vconn"), at=Beside(TCPC, Edge.WEST, align=PadRef(TCPC, "TCPC_VCONN")), rotation=180,
            why="VCONN's pull-down level with B1, its VCONN pad toward the ball (DS1715-04 p4 Table 2)")
board.alternative(Part("r_vconn"), "upright", rotation=90,
                  why="the same pad on B1's line with the body north: a narrower west side")
# The CC caps lie flat on the resistor, their CC pad at its IC end so the
# CC line from the corner ball reaches it by one 45; GND outward.
board.place(Part("c_cc2"), at=Beside(Part("r_vconn"), Edge.NORTH, align=Along.END), rotation=180,
            why="CC2's 330 pF by A1, its CC pad toward the ball (DS1715-04 p3 Table 1)")
board.place(Part("c_cc1"), at=Beside(Part("r_vconn"), Edge.SOUTH, align=Along.END), rotation=180,
            why="CC1's 330 pF by C1, its CC pad toward the ball (DS1715-04 p3 Table 1)")
# Upright at the resistor's far end: a shorter west stack, taller.
board.arrangement("caps_upright",
                  Alt(Part("c_cc2"), at=Beside(Part("r_vconn"), Edge.NORTH, align=Along.START), rotation=90),
                  Alt(Part("c_cc1"), at=Beside(Part("r_vconn"), Edge.SOUTH, align=Along.START), rotation=270),
                  why="the CC caps upright, CC pads toward their rows, for a board that has height not width")

# North: VDD's bypass over A3, its V3V3 pad a TCPC_VBUS lane east of A2 so
# the resistor's line runs north between it and nothing else.
board.place(Part("c_vdd"), at=Beside(TCPC, Edge.NORTH, align=(1, Past([PadRef(TCPC, "TCPC_VBUS")], Edge.EAST,
                                                                      lane=Net("TCPC_VBUS")))),
            rotation=90, why="VDD's 100 nF at A3, its V3V3 pad south toward the ball, a VBUS lane east of A2")
board.link(PadRef(Part("c_vdd"), 1), PadRef(TCPC, "V3V3"), weight=LinkWeight.SHORT, limit_mm=2.0,
           why="the VDD bypass at its pin (DS1715-04 p3 Table 1)")
# extent: c_vdd the bypass stands where its pad is nearest A3 without pinching A2's line; no other spot keeps the loop
# The 4.7k over A2, its TCPC_VBUS pad level with the ball; VBUS leaves west.
board.place(Part("r_vbus"), at=Beside(TCPC, Edge.NORTH, align=PadRef(TCPC, "TCPC_VBUS")), rotation=0,
            why="VBUS sense through 4.7k, its TCPC_VBUS pad level with A2 (DS1715-04 p4 Table 2)")
# extent: r_vbus over A2 is the only spot its pad is level with the ball; the bypass holds the east, the CC cap the west

# East: INT_N's pull-up east of the bypass, sharing its V3V3 pad; its
# PD_IRQ pad north, clear of the I2C balls' way out.
board.place(Part("r_irq"), at=Beside(Part("c_vdd"), Edge.EAST, align=PadRef(Part("c_vdd"), 1)), rotation=270,
            why="INT_N's 10k pull-up to V3V3 beside the bypass (DS1715-04 p4 Table 2)")
board.alternative(Part("r_irq"), "back", at=Pin(1, PadRef(TCPC, "PD_IRQ")), rotation=270, face=Face.BACK,
                  why="the pull-up under the IC on the back, its PD_IRQ pad on the ball's via and its V3V3 pad north "
                      "toward the bypass (a back part mirrors, then turns: 270 puts pad 2 north), so the rail drop "
                      "lands by the bypass's pad: nothing east of the bypass")

# Copper the module owns.
board.track(Net("TCPC_VCONN"), [PadRef(TCPC, "TCPC_VCONN"), PadRef(Part("r_vconn"), 1)], layer=CopperLayer.F)
board.track(Net("USB_CC2"), [PadRef(TCPC, "USB_CC2"), PadRef(Part("c_cc2"), 1)], layer=CopperLayer.F)
board.track(Net("USB_CC1"), [PadRef(TCPC, "USB_CC1"), PadRef(Part("c_cc1"), 1)], layer=CopperLayer.F)
board.track(V3V3, [PadRef(TCPC, "V3V3"), PadRef(Part("c_vdd"), 1)], layer=CopperLayer.F)
board.track(V3V3, [PadRef(Part("c_vdd"), 1), PadRef(Part("r_irq"), 2)], layer=CopperLayer.F, only=IRQ_FRONT)
board.track(Net("TCPC_VBUS"), [PadRef(TCPC, "TCPC_VBUS"), PadRef(Part("r_vbus"), 2)], layer=CopperLayer.F)

# PD_IRQ's way out of the centre ball: a via in its pad. With the pull-up on
# the front it is joined to it on the signal layer through a via at its pad;
# on the back the pull-up's pad sits on the ball's via.
v_irq = board.via(Net("PD_IRQ"), FreeSpot(near=PadRef(TCPC, "PD_IRQ"), in_pad=True), size=VIA_MIN_SIZE,
                  drill=VIA_MIN_DRILL,
                  why="B2 is walled in by its own neighbours at 0.4 mm pitch; the ball's via is its only way out")
v_pull = board.via(Net("PD_IRQ"), FreeSpot(near=PadRef(Part("r_irq"), 1)), only=IRQ_FRONT,
                   why="the pull-up's PD_IRQ pad down to the signal layer")
board.track(Net("PD_IRQ"), [v_irq, v_pull], layer=CopperLayer.IN2, only=IRQ_FRONT)

# Ground drops: the IC's ball, the bypass's return, and the west parts whose
# ground the CC lines cut off from the rest of the face's fill.
board.via(GND, FreeSpot(near=PadRef(TCPC, "GND")), why="the IC's ground to the plane")
board.via(GND, FreeSpot(near=PadRef(Part("c_vdd"), 2)), why="the bypass's return to the plane")
board.via(GND, FreeSpot(near=PadRef(Part("c_cc2"), 2)), why="CC2's cap returns to the plane")
board.via(GND, FreeSpot(near=PadRef(Part("c_cc1"), 2)), why="CC1's cap returns to the plane")
board.via(GND, FreeSpot(near=PadRef(Part("r_vconn"), 2)), why="VCONN's pull-down to the plane")
# The rail drop: V3V3 from the core's supply plane enters at the pull-up and
# reaches the pin through the bypass.
v_v3v3 = board.via(V3V3, FreeSpot(near=PadRef(Part("r_irq"), 2)), why="V3V3 from the core's supply plane")
board.track(V3V3, [PadRef(Part("c_vdd"), 1), v_v3v3], layer=CopperLayer.F, only=IRQ_BACK)

# The core's planes over the frame: ground on the component face and the
# outer inner layers, the 3V3 supply on In3 (placemat facts: In1, In3 and
# In4 are power layers).
board.plane(GND, layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.IN4), inset=board.keep_in)
board.plane(V3V3, layers=(CopperLayer.IN3,), inset=board.keep_in)

board.rect(fit=True)
```

### Work log

# Work log: UsbTcpc module layout

## Step 1: read skill and references
Read SKILL.md in full; api.md index, Setup, Placement, Modules, Arrangements, Commands (facts). Staged folder holds UsbTcpc.zen
(RT1715 + 100nF, 4.7k, 1k, 2x330pF, 10k pull-up), fragment_frame.py, placemat.toml, and a cached .placemat/generated.
Decision: module fragment, script name UsbTcpc_layout.py (named after Board(name="UsbTcpc")). Use board.rect(fit=True).
Do not use fragment_frame.py helpers' arithmetic style: skill forbids computed offsets; only intent forms.

## Step 2: model the board (this session)
Ran: `placemat parts` and `placemat measure ... --pads` on the cached generated board. RT1715 is WLCSP-9, 3x3 balls at
0.4 mm pitch, 0.2 mm pads: A1 CC2, A2 TCPC_VBUS, A3 V3V3 / B1 VCONN, B2 PD_IRQ, B3 SCL / C1 CC1, C2 GND, C3 SDA.
Read: layout.kicad_pro net classes (Default 0.16/0.16, VCONN class 0.254 on USB_CC1/2, via 0.6/0.3 board default,
min via 0.25/0.15), placemat.toml (physical envelope, escape_depth 1.5, cleanup off, solve on), fragment_frame.py
(the project's helpers: planes GND on F/In1/In4, V3V3 on In3; its pad arithmetic is the style the skill forbids, so
not used).
Decided: tcpc at the fit frame's origin; west = receptacle side (VCONN level with B1, CC caps off the resistor), north =
supply (bypass over A3 with a TCPC_VBUS lane past A2, r_vbus level with A2), east free for I2C with r_irq beside the
bypass, GND drop south. Rotation convention checked from the first run: 90 puts pad 1 south, 180 east, 270 north.

## Step 3: facts
Ran `placemat facts UsbTcpc_layout.py`: F/In2/B mixed, In1/In3/In4 power, 0.035 mm; micro/blind/buried vias all "no";
rise 10 C; unconfirmed. Left unconfirmed as instructed.

## Step 4: first draft, first run (46ec2f62)
The draft's `board.escape(tcpc, [SCL, SDA])` was refused: a ball grid's corner ball has no row. Dropped it; the east
stays clear of parts and the parent routes SCL/SDA from the balls.
Run: DRC clean, unconnected 2 (PD_IRQ B2 -> r_irq, and an F GND island on the west cut off by the CC tracks), 4
extent_fixed notices (c_cc1, c_cc2, r_vconn west; r_irq east), 56% empty. r_irq had rotation 90, which put its PD_IRQ pad
south level with the I2C balls (wrong: wanted 270). The V3V3 FreeSpot drop at c_vdd pad 1 landed on the IC's NE corner.
`placemat occupancy --via-near tcpc.B2 --in-pad`: a 0.25/0.15 via fits at the ball centre; 0.3 and 0.45 do not.
Decided: PD_IRQ via in B2 at the board's minimum via (named constants citing the design rules), r_irq rotation 270,
GND drops at the three west GND pads (the island), V3V3 drop moved to r_irq pad 2 (supply enters at the pull-up and
flows through the bypass to the pin), CC caps flat (rotation 180) flush at r_vconn's IC end as the default (shorter
south extent), alternatives: r_vconn "upright", group "caps_upright"; `# extent:` lines on c_vdd, r_vbus, r_irq.

## Step 5: run 39261a7c (fixes + first alternatives)
DRC clean, unconnected 1 (PD_IRQ: the B2 via to r_irq pad 1, via_dangling 1), extent 5.18 x 4.03, 48% empty, only
r_irq's extent notice left. Arrangements r_vconn.upright and caps_upright both offered.
Decided: the module joins the pull-up to B2's via itself (a via at r_irq pad 1 and an In2 track between the two vias:
the parent would need that second via anyway to reach r_irq's front pad), and r_irq gets a "back" alternative under
the IC with its pad 1 on the ball's via (no second via, nothing east of the bypass). Copper that exists only with the
pull-up on the front or only on the back carries `only=` with the arrangement ids.

## Step 6: run 6e4d6a26
Default: DRC clean, unconnected 0, airwires 0, no findings but the facts warning; score 0.0. r_irq.back refused:
with rotation 0 the back pad 2 landed west of B2, the V3V3 drop went to (-0.57, 1.43) and the F track from c_vdd to it
ran down the IC's east side, walling B3 and C3 and meeting the C2 GND via; the upright+back combination crossed the
CC/VCONN tracks for the same reason. Decided: rotation 90 on the back option, pad 2 north toward the bypass's pad so
the drop lands beside it.

## Step 7: run 904ad74a
Default unchanged (DRC clean, unconnected 0, score 0.0, best). r_irq.back still refused (escape_walled B3, C3): on
the back, rotation 90 put pad 2 SOUTH of B2 (the flip mirrors, then turns), the V3V3 drop went to (0.65, 1.02) and
the F track from the bypass to it ran down the IC's east side past B3/C3. Decided: rotation 270 on the back option.

## Step 8: run 28e096f8 (final)
Default: 7 placed, 47 copper ops, DRC clean, unconnected 0, airwires 0, 0 crossings; 2 design checks passed
(crossings-under on USB_CC1/USB_CC2, 0 each); score 0.0, matches the best run; extent 5.18 x 4.03 mm, 48% empty. The
only finding is `facts: unconfirmed` (left so on purpose).
Arrangements, all offered with DRC 0 and no findings: default, r_irq.back (the pull-up under the IC on the back, its
pad 1 on B2's via, V3V3 drop beside the bypass's pad), r_vconn.upright, r_vconn.upright+r_irq.back, caps_upright.
Rendered default and r_irq.back read as intended.
Skill's typed-position grep on the script counts 1: `Location(0, 0)` on tcpc, the fit frame's origin, which api.md
"Modules" names as where a fragment's main part stands. The old-API grep is empty.

## Open points for the user
- B2 (PD_IRQ) is a centre ball at 0.4 mm pitch: the 0.16 mm class leaves no lane between balls, and the fab profile
  allows no micro/blind/buried vias, so the script drops a through via in the ball's pad at the board's minimum
  (0.25/0.15, constants citing the design rules). That via needs filling and capping at the fab; if the fab will not
  do via-in-pad on a WLCSP ball, the alternatives are a micro via tier in fab-profile.json or a different pin.
- Vias default to the board's 0.6/0.3 rather than the class's 0.45/0.2; not changed, as that is a board fact.
- The facts were left unconfirmed as instructed.
