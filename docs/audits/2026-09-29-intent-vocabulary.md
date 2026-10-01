# placemat intent audit

Repository: /home/ben/work/placemat, branch main at 8d8a9da (as committed; the
only uncommitted change is cave.db). Read-only. Line numbers are for that
commit. "Probed" means I ran a small snippet with .venv/bin/python against the
synthetic fixtures in tests/fixtures.py (scripts kept in the scratchpad as
probe*.py); everything else is from reading the code.

## 0. Findings in brief

1. The intent vocabulary is larger than what agents use. It exists mainly as
   `at=` types in values.py and Board verbs in layout.py. api.md documents
   most of it, but the forms are scattered through 1527 lines of prose that
   also covers settings, routing and the run record. There is no single table
   from "what I mean" to "the form that says it". The import line at the top
   of api.md (api.md:4) leaves out `Mid`, `Along`, `Fraction`, `FreeSpot`,
   `LinkWeight`, `Turned`, `Polar`, `OnRim`, `OnBore`, `Cutout` and the
   shapes.
2. The prevalent coordinate pattern is not `Location(x, y)`. It is
   `X(ref, <arithmetic>)` / `Y(ref, <arithmetic>)` inside `Centre`/`Pin`,
   fed by `board.claim()`/`board.pad().box` measurements. The only placemat
   scripts in the repo (18 fixture modules, fixtures/mnb and
   fixtures/fairing, committed d1917a8 2026-09-22) contain 344 `X(`/`Y(`
   calls. The SKILL's "count typed positions" grep (SKILL.md:29) reports 0 or
   1 for 17 of the 18, because it excludes `Location(X(` and ignores X/Y
   offsets.
3. The SKILL permits the pattern in so many words: "Arithmetic on named
   values is fine; a bare scalar inside a `place()`, `track()` or `X()` is
   not" (SKILL.md:193-194). "Measure, do not type: `board.extent(...)`,
   `board.pitch(part)`, `board.pad(part, n).box`" (SKILL.md:224-227) points
   agents at measurements to do arithmetic with. api.md describes
   `board.envelope` as "what a row or stack built by hand spaces by"
   (api.md:26).
4. `placemat freeze` itself writes numeric offsets into scripts:
   `Near(PadRef(...).local(dx, dy), radius=0)`, `Location(X(pad, dx), Y(pad,
   dy))` and `Near(Location(x, y), radius=0)` (freeze.py:172-184). The SKILL
   sanctions freeze (SKILL.md:247-250) and in the same file counts
   `radius=0` as a typed position that "is not a style to follow"
   (SKILL.md:29-35).
5. Real gaps exist, and several are already specified but not built.
   docs/superpowers/specs/2026-09-29-pad-references-design.md ("approved,
   implement unless a decision is needed") specifies pad edges,
   `Origin(part)`, `Envelope(item, side)`, `at=Beside(...)`, `board.lane()`
   and `board.pour_pads()`. None of them is in src (I grepped). Gaps not
   covered by that spec:
   - a row or column that is not along a board edge;
   - "turn this part so its pad X faces Y";
   - a keepout or cutout that turns with its part;
   - `Polar`/`ring` about a part or pad;
   - a keepout shaped by a part.
6. Defects found while checking the docs against the code (probed). Each
   silently or noisily breaks a documented intent form, which pushes an
   agent back to numbers:
   - a block placed `at=OnEdge(...)` (or on a line) ignores the place;
   - `OnEdge(run, along=<reference>)` crashes;
   - a cutout or keepout `at=Near(...)` crashes;
   - `row(align="centre")` is silently the same as `"start"`;
   - `Polar(about=<pad>)` and `ring(about=<part>)` are refused.
   Details are in section 6.

## 1. The intent vocabulary in the code

Exports: src/placemat/__init__.py:21-28. `Keepout`, `CutoutEdge`, `PinName`,
`Freedom`, `Row`, `Ring`, `RunRow` and `BlockSpec` are not exported; scripts
get them from Board verbs.

"api.md" column: OK = documented accurately. PARTIAL / WRONG / MISSING are
explained. api.md lines are cited.

### 1a. Placing a part

| form | intent | signature / defined | api.md | example |
|---|---|---|---|---|
| bare `place(item)` | searched, seeded from what it is wired to (links, nets); pocket if nothing wired is placed | `Board.place(item, at=None, *, rotation=None, face=Face.FRONT, radius=None, step=None, rotations=(), priority=None, required=False, why="")` layout.py:1496; seed layout.py:4050-4071 | OK api.md:56, 133, 246-260 | `board.place(Part("c1"))` |
| `Location(x, y)` | a mechanical fact: the footprint ORIGIN at a point (a cell: its box centre, layout.py:1641) | values.py:215 | PARTIAL: api.md:62 says "the origin" and omits the cell case. That axes may be references (`Location(X(pad), Y(pad))`, resolved by `_locate` layout.py:4222-4225) is said only in the freeze section (api.md:1328) | `at=Location(3.2, 4.0)  # M3 hole per enclosure dwg` |
| `Location(x, None)` / `Centre(None, y)` | a line: one axis pinned (number or reference), slides along it from across what it connects to; items pinned to the same value share the line | values.py:215, 80; `_settle_along_line` layout.py:3496 | OK api.md:60, 80-84 | `at=Centre(None, Y(PadRef(U, "SDA")))` |
| `(x, y)` tuple in `at=` | the same as Location (a "point of references") | layout.py:1591-1603 | OK api.md:216 | `at=(X(pad), Y(pad, 1.0))` |
| `Centre(x, y)` | the body-box centre at a point; each axis a number or a reference | values.py:80-95; layout.py:1602 | OK api.md:63, 216-223 | `at=Centre(X(Mid(a, b)), Y(a))` |
| `Pin(key, x, y)` | the item's own pad `key` (int number or net name) lands on the point | values.py:97-110; `pad_anchored_placement` placer.py:320; refused for a cell or block, layout.py:1541-1545 | OK api.md:64, 76-80 | `at=Pin("VIN", X(u_vin), Y(u_vin))` |
| `OnEdge(Edge, along=)` | reach at the keep-in on a board side, at a distance along it | values.py:112-135; `edge_placement` placer.py:194 | PARTIAL: api.md:85 says "a number in mm, a reference". On an `Edge` a number is an absolute board coordinate (layout.py:4024 `_coord`, api.md:646-647 does say so). A bare `PadRef` is rejected, values.py:132; it must be wrapped in `X()`/`Y()`/`Mid` | `at=OnEdge(Edge.WEST, along=Along.MID)` |
| `OnEdge(Edge)` | furniture: slides along the edge to the room left; free items share it at (k+1)/(n+1) | layout.py:3527 `_edge_slot` | OK api.md:59, 87-93 | `at=OnEdge(Edge.SOUTH)` |
| `OnEdge(overhang=)` | a face proud of the edge | values.py:125; layout.py:1650 | OK api.md:183 | `OnEdge(Edge.NORTH, overhang=0.5)` |
| `Along.START/MID/END`, `Fraction(f)` | a named or fractional distance along the usable edge; START/END put the near/far end flush | values.py:69, 165; `_EdgeFraction` layout.py:139 | OK api.md:85-86 | `along=Fraction(0.3)` |
| `OnEdge(board.edge(facing=...))` | an item on a stretch of a shaped board's edge, turned to it | layout.py:1553; `Run` outline.py:20 | WRONG for `along=<reference>`: api.md:645-646 says a reference "lands at the nearest place on the run". Probed: `X()`/`Y()` crash, and `Mid` works only with `rotation=` given (section 6) | `at=OnEdge(top, along=Along.MID)` |
| `OnEdge(board.cutout(n).edge(side=))` | against a hole's boundary, waiting for the hole | `CutoutHandle.edge` layout.py:366 returns `CutoutEdge` values.py:571 | OK api.md:409, 435-443 | `at=OnEdge(board.cutout("ffc").edge(side=Edge.NORTH), along=Along.MID)` |
| `OnRim(angle=None, overhang=0)` / `OnBore(angle=None)` | disc rim or bore, facing out or in; with no angle it slides round | values.py:655, 668; layout.py:1570 | OK api.md:671-674 | `at=OnRim(Edge.EAST)` |
| `Polar(radius, angle=None, about=None)` | body centre at a radius and bearing; either may be None to leave that freedom | values.py:632-653; layout.py:1578 | MISSING `about=`: api.md:717 says "about `board.centre`". `about` accepts only a Location or numeric pair (`_as_point` layout.py:4209), so it cannot be a part or pad (probed) | `at=Polar(16.0, 30.0)` |
| `Near(location, radius, step, rotations)` | a hint to search round, for a need the netlist cannot say | values.py:137-146; layout.py:1585 | OK api.md:65, 172-178 | `at=Near(PadRef(Q1, "D"))` |
| `Near(..., radius=0)` + `PadRef.local` + `Turned` | a spot pinned in an anchor's frame, written by `freeze` | freeze.py:172-184 | OK api.md:66, 1321-1333 | `at=Near(PadRef(u1,3).local(0.4,-1.2), radius=0), rotation=Turned(u1, 90)` |
| `rotation=Turned(part, deg)` | turn with another part | values.py:395; layout.py:1624-1649 | OK api.md:151 | `rotation=Turned(Part("u1"), 90)` |
| `rotation=` / `rotations=` / default | fix one turn / a set / let the search try all four | layout.py:1629; settings `place.rotations` | OK api.md:98-104 | `rotations=(0, 180)` |
| `face=Face.BACK` | mirror about the vertical axis, then rotate | values.py:53 | OK api.md:127-131. A string `"back"` is not validated and fails later with `AttributeError: 'str' object has no attribute 'value'` (probed) | `face=Face.BACK` |
| `priority=Priority.HIGH/LOW` | a tier above the rank, for searched items only; refused on a decided place | values.py:194; layout.py:1618-1621 | OK api.md:57, 113-119 | `priority=Priority.HIGH` |
| `required=True` | failing to place stops the run | layout.py:1521-1525 | OK api.md:58, 121-125 | `required=True` |
| `Freedom` (FIXED / EDGE / SEARCHED) | derived from `at=`, never given | values.py:179; layout.py:1613-1617 | OK api.md:93-96 | (derived) |
| `Cell(name)` as item | a stamped module placed rigidly | values.py:325; layout.py:762 | OK api.md:68 | `board.place(Cell("mcu"), at=OnEdge(Edge.NORTH))` |
| `board.label(item, text, side=, gap=, align=, size=, thickness=, knockout=, rotation=, reserve=, line=, why=)` | silk text on a part, cell or pad, reserving its box | layout.py:2132 | OK api.md:920-945 | `board.label(J, "CAN", side=Edge.EAST)` |

### 1b. Placing a set of parts

| form | intent | signature / defined | api.md | example |
|---|---|---|---|---|
| `board.row(items, edge, ...)` | items down a board edge in order, courtyards touching, outward sides out, aligned across on a line | `row(items, edge, *, gap=0.0, start=None, align="start", rotation=None, line="centre", behind=None, inboard=None, overhang=0.0, centre=None, end=None, before=None, after=None, why="")` layout.py:1659; `Row` layout.py:52 | PARTIAL: `align` values other than "center" are not validated (section 6); `.inner`/`.outer` as copper coordinates OK api.md:212-214 | `board.row(LEDS, Edge.NORTH, line="outer", after=pwr)` |
| row `behind=`, `inboard=` | a row inboard of another edge row | layout.py:1696-1701 | OK api.md:190-192 | `behind=trunk` |
| row `centre=`/`end=`/`start=<ref>`/`before=`/`after=` | where the row sits along the edge, by reference | layout.py:1712-1725, `Row.begin_from` layout.py:73 | OK api.md:206-209 | `centre=X(Mid(pin_n, pin_p))` |
| row on a `Run` | along a shaped board's edge; only `gap/start/align/rotation/overhang` | `_row_on_run` layout.py:1796; returns `RunRow` layout.py:494 | OK api.md:624, 650-654 | `board.row([L1, L2], top, align="center")` |
| `board.ring(items, *, radius=None, start=Edge.NORTH, gap=0.0, spread=False, rotation=None, about=None, why="")` | items round a centre, facing out; `spread` shares the turn evenly | layout.py:1745; `Ring` layout.py:515 | PARTIAL: `about=` undocumented, and it takes numbers only (probed) | `board.ring(HOLES, radius=18.0, spread=True)` |
| `board.block(anchor, satellites, gap=None)` | a part and the parts at its pins: each satellite's pad on the named net lands on that pin's axis, courtyards touching, body outward; searched as one | layout.py:1470; `BlockSpec` placer.py:499; `layout_block` placer.py:525 | PARTIAL: accurate for a searched block (api.md:766-787). Not documented: a block takes only `Location`/`Centre`/`Polar(r, a)`/`Near`/nothing. `OnEdge`, a line, `OnRim` are silently dropped (`_settle_block` layout.py:3843 reads only `at`/`center`/`near`; probed). `Pin` is refused (layout.py:1542) | `board.place(board.block(U, [(Part("cin"), "VIN")]))` |
| items pinned to one line value | several parts sharing a line, spread evenly then slid | layout.py:3504-3510 | OK api.md:82-84 | `at=Centre(None, Y(PadRef(U, 1)))` for each |
| `board.size(fit=True, margin=None)` | a module frame that is what is placed plus the margin | layout.py:1301-1318 | OK api.md:35-38, 236-244 | `board.size(fit=True)` |
| `board.group(name, items, why="")` | a KiCad group of parts for hand moves; places nothing | layout.py:2871 | OK api.md:542-553. migration.md:18-21 ("Unreleased") says it takes "the parts and cells named"; the code refuses a Cell (layout.py:2884-2886) | `board.group("led_bank", LEDS)` |
| pockets | fallback for a searched item with nothing placed that it connects to | `placer.pockets` placer.py:431 (internal) | OK api.md:257, 373-376 | (not a script form) |

### 1c. Relating parts to each other

| form | intent | defined | api.md | example |
|---|---|---|---|---|
| `PadRef(part, key, dx=0, dy=0, pin=None)` | a pad by number (int), net (str) or symbol pin name, resolved after placement | values.py:361-393 | OK api.md:146-150, 838-843 | `PadRef(U, pin="VDD3P3")` |
| `CellPadRef(cell, net=, number=, ref_prefix=, dx=, dy=)` | a pad inside a cell | values.py:407-420 | OK api.md:19, 838 | `CellPadRef(Cell("bd0"), net="CANH")` |
| `X(ref, dx=0)` / `Y(ref, dy=0)` | one coordinate of a pad, a part's body centre, a point, a Mid (plus an offset) | values.py:422-435; `_coord` layout.py:4248 | OK api.md:216-223 | `X(Part("sw_run"))` |
| `Mid(a, b)` | midpoint of two references (pad centres or body centres) | values.py:437-443; layout.py:4226-4228 | OK api.md:60, 218 (missing from the api.md:4 import line) | `Centre(X(Mid(pa, pb)), Y(pa))` |
| `Part`/`Cell` as a point | its placed body-box centre | layout.py:4232-4235 | OK api.md:219-222 | `X(Part("u1"))` |
| `PadRef.offset(dx, dy)` / `.local(dx, dy)` | a point off a pad in board directions / in the part's own frame | values.py:385-392 | OK api.md:148-151 | `PadRef(U, 3).local(0.4, 0)` |
| `board.link(a, b, weight=, limit_mm=, why=)` | price one connection; the search and cleanup pull by it; a limit is reported | layout.py:1868; `LinkWeight` values.py:445 | OK api.md:726-736 | `board.link(PadRef(C, "VIN"), PadRef(U, "VIN"), weight=LinkWeight.SHORT, limit_mm=2)` |
| `board.free_net(net)` | this net's length does not matter | layout.py:1880 | OK api.md:730 | `board.free_net(Net("ENDSTOP"))` |
| `board.fanout(part, depth=2.0, sides=None, why="")` | reserve the escape band outside a part's pad rows | layout.py:1855 | OK api.md:160-170 | `board.fanout(MCU, depth=1.5)` |
| `board.faces(outward=, quiet=, handoff=, why=)` | a module's sides, so edges and rows turn it | layout.py:2103 | OK api.md:738-753 | `board.faces(outward=Edge.NORTH)` |
| `board.outward_rotation(item, edge)` | the turn that faces an item's outward side to an edge or bearing | layout.py:2114 | MISSING from api.md | `board.outward_rotation(Cell("j"), Edge.WEST)` |
| `board.rule(clearance=, within=/between=/on=, why=)` | a local DRC clearance | layout.py:1885 | OK api.md:755-764 | `board.rule(clearance=0.6, between=(V48, GND), why="48 V")` |
| questions: `extent`, `envelope`, `claim`, `reach`, `pad`, `part`, `cell`, `cell_pad`, `pitch`, `netclass`, `height_of`, `parts(net=)`, `keep_in`, `centre`, `centroid`, `radius`, `bore`, `width`, `height`, `web` | measurements of the generated board | layout.py:707-836, 1431-1454, 635-652 | PARTIAL: `board.claim()` (layout.py:820), which rows space by and the fixtures use for hand stacks, is MISSING from api.md | `board.pitch(J)` |

### 1d. Copper

| form | intent | signature / defined | api.md | example |
|---|---|---|---|---|
| `board.track(net, points, *, layer, width=None, chamfer=None, priority=DEFAULT, bridge=False, why="")` | a trace through points; legs octilinear, up to three legs per pair of points, avoiding foreign pads | layout.py:2182; `octilinear` copper.py:475 | OK api.md:808-826, 846 | `board.track(EN, [PadRef(R, "EN"), PadRef(U, "EN")], layer=F)` |
| track point types | `Location`, `PadRef`, `CellPadRef`, `Mid`, `Part`/`Cell` (body centre), `(x, y)` of numbers, `X`/`Y`, `row.inner`/`row.outer` (+ number), a via returned by `board.via` | `_locate` layout.py:4218, `_coord` layout.py:4248, `RowCoord` layout.py:42, `_CopperContext.locate` layout.py:4275 | PARTIAL: api.md:838-839 lists Location, PadRef, CellPadRef, (x, y) with X/Y. Mid and Part-as-point are only in the placement text. Via ends OK api.md:881-885; RowCoord OK api.md:213 | `[v, PadRef(C, "GND")]` |
| `bridge=True`, `priority=` on copper | who passes under at a same-layer crossing | layout.py:2184; `resolve_bridges` copper.py:218 | OK api.md:821-826 | `bridge=True` |
| `board.pair(p, n, path, *, layer, width=, gap=, chamfer=, via_step=, priority=, bridge=, why=)` | a coupled differential pair along a centreline | layout.py:2235 | OK api.md:903-918. The centreline is numbers in its example (api.md:907) | `board.pair(P, N, [(pP, pN), (x, y), (x, y2), (qP, qN)], layer=B)` |
| `board.via(net, at, *, drill=, size=, priority=, why=)` | a via at a point, at a pad (carried with the part), or at a `FreeSpot` | layout.py:2330 | OK api.md:847-848, 856-865 | `v = board.via(GND, FreeSpot(near=PadRef(C, "GND")))` |
| `FreeSpot(near, radius=2.0, step=0.05, layer=None, in_pad=False, tail=True)` | the nearest legal via spot to a pad, with its tail | values.py:148-163; `_free_spot` layout.py:2431 | OK api.md:867-885 | `FreeSpot(near=PadRef(U, "GND"))` |
| `board.vias(net, pad, *, pitch=, size=, drill=, inset=0.0, priority=, why=)` | a pad filled with a via grid in the part's frame | layout.py:2273 | OK api.md:849, 887-901 | `board.vias(GND, PadRef(U, 9))` |
| `board.pour(net, points, *, layer, stroke=, swallow_pads=False, priority=, why=)` | a filled polygon of exactly that shape | layout.py:2484 | OK api.md:850 | `board.pour(SW, [pa, pb, pc], layer=F, swallow_pads=True)` |
| `board.plane(net, layers, *, outline=None, inset=, chamfer=, clearance=, min_thickness=, solid_pads=True, priority=, why=)` | KiCad zones, board-wide or an outline | layout.py:2499 | PARTIAL: `solid_pads`, `clearance`, `chamfer` not in the api.md:851 signature | `board.plane(GND, [CopperLayer.IN1])` |
| `board.finger(net, *, layer, from_, to, width, bridge_width=, priority=, why=)` | a rectangular pour along a centreline, cut and bridged at crossing tracks | layout.py:2529; `finger_ops` copper.py:276 | OK api.md:852 | `board.finger(VIN, layer=F, from_=PadRef(J, 1), to=PadRef(U, "VIN"), width=2.0)` |

### 1e. Regions and the board

| form | intent | signature / defined | api.md | example |
|---|---|---|---|---|
| `board.size(w, h, chamfer=, radius=, holes=, web=, draw=)` | a rectangular outline | layout.py:1301 | OK api.md:33 | `board.size(40, 30)` |
| `board.disc(diameter, hole=, holes=, web=, draw=)` | a round board | layout.py:1333 | OK api.md:39 | `board.disc(40.0, hole=6.0)` |
| `board.outline(path, holes=, web=, draw=)`, `Arc(to=, via=)` | a board of any shape | layout.py:1352; cutouts.py:26 | OK api.md:606-661 | `board.outline([(0,40),(0,20),Arc(to=(40,20),via=(20,0)),(40,40)])` |
| `board.edge(facing, within=45, outermost=False)` / `board.edges(...)` | a stretch of edge chosen by which way it faces | layout.py:1383, 1374 | OK api.md:620-640 | `top = board.edge(facing=Edge.NORTH)` |
| `Cutout(shape, name, at=, rotation=None, why="")` in `holes=` | a hole placed by the same places a part takes, settled with the firm items | values.py:581-600; layout.py:1271-1299, 2628-2654 | WRONG: api.md:417-418 and SKILL.md:307 list `Near`, which crashes (probed). `at=` also accepts `PadRef`, `Part`, `Mid`, a tuple (via `_locate`), which api.md:417 omits | `Cutout(Slot(13,3), "ffc", at=Centre(X(J), Y(J, 4.0)), why=...)` |
| `Slot(length, width, anchor=)`, `Circle(diameter, anchor=)`, `Path(points, anchor=)` | hole or region shapes | cutouts.py:157, 199, 224 | OK api.md:412-417 | `Path(FIGURE, anchor=(0, 0))` |
| `board.cutout(name)` -> `.edge(side=)`, `.edges()`, `.box`, `.centre`, `.area`, `.settled` | a hole's boundary to place against | layout.py:1262, 331-403 | OK api.md:435-443 | `board.cutout("ffc").edge(side=Edge.NORTH)` |
| `board.keepout(shape, name, *, at, rotation=None, excludes=None, allow=(), layers=None, max_height=None, why="")` | a region that forbids parts, fill, tracks, vias or pads | layout.py:1197; `Keepout` values.py:602 | WRONG for `Near` (as cutout). PARTIAL: SKILL.md:473 says a keepout at a PadRef "then follows the part". It follows the position only. A part turned 90 leaves the keepout at 0, and `rotation=Turned(...)` raises `TypeError: float() argument ... not 'Turned'` (probed) | `board.keepout(CLR, "ant", at=PadRef(ANT, "FEED"), allow=(ANT,), why=...)` |

## 2. Coordinate escape hatches

"Intent instead" is what normally should be written. "none" means placemat
has no form for that meaning today.

| hatch | where | intent instead |
|---|---|---|
| `Location(x, y)` of numbers (and `(x, y)` in `at=`) | values.py:215; layout.py:1591 | a mechanical fact stays (named constant with its source). Otherwise: bare `place` + `link`, `OnEdge`, `row`, `block`, `Pin`/`Centre` of references |
| `Location`/`Centre` with a numeric free-axis line | values.py:215, 80 | `X()`/`Y()` of the reference the line comes from |
| `Centre(x, y)` / `Pin(key, x, y)` of numbers | values.py:80, 97 | references; `block` for a part at a pin (placer.py:525) |
| `X(ref, dx)` / `Y(ref, dy)` with a numeric or arithmetic offset | values.py:422-435 | Partly none. `block` covers "satellite on a pin's axis, courtyards touching". `row` covers "neighbours along an edge". "Beside another part at the envelope gap", "column at courtyard pitch" and "flush with a pad edge" have no form (section 3) |
| `PadRef.offset(dx, dy)` / `CellPadRef.offset` | values.py:385, 418 | `FreeSpot` for a via; a searched part with a lock for a part |
| `PadRef.local(dx, dy)` | values.py:389 | the lock file (`--accept`), not the script; frozen lines are this form |
| `Near(Location(x, y))` | values.py:137 | links; `Near(PadRef(...))` for a need the netlist cannot say |
| `Near(..., radius=0)` | freeze.py:172-184 | the lock; this is a pinned spot dressed as a search |
| `Location.offset(dx, dy)` | values.py:231 | none needed for placement. It fails on a Location whose axes are references (it adds floats) |
| `OnEdge(Edge, along=<number>)` | values.py:112; layout.py:4024 | `Along`/`Fraction`, `X()/Y()` of a reference, or no `along` (slides). On an `Edge` the number is an absolute coordinate, not a distance |
| `row(start=<number>)`, `gap=`, `inboard=` | layout.py:1659-1661 | `align="center"`, `centre=`/`end=` a reference, `before=`/`after=`; gaps default to courtyards touching |
| `row.inner + d` / `row.outer + d` (`RowCoord.__add__`) | layout.py:48 | none for "one clearance inboard of the row" (a lane) |
| `Polar(r, a)`, `ring(radius=)` numbers | values.py:632; layout.py:1745 | a mechanical radius stays; `OnRim`/`ring(radius=None)` for "at the rim" |
| `board.size(w, h)` | layout.py:1301 | `size(fit=True)` for a module; rows plus named margins for a board |
| `rotation=<number>` on a fixed part | layout.py:1496 | `Turned(part, deg)`, the outward rule of an edge/row/ring, or the search's four turns. "Pad X faces Y" has no form (section 3) |
| `Cutout`/`keepout` `at=Location(...)`, `rotation=<number>` | values.py:581, 602 | `at=PadRef(...)`, `Centre(X(Part), Y(Part, d))`. A rotation that follows the part has no form |
| track points of numbers, `(x, Y(pad))` bus lines, `(X(pin, -2), Y(pin, 2))` taps | layout.py:2182; api.md:803-819 | pad-to-pad with no waypoints (SKILL.md:487-490). A lane beside pads has no form (specified: `board.lane`) |
| `pair` centreline points | layout.py:2235; api.md:907 | none (BACKLOG.md "board.pair() finding its own centreline") |
| `via(net, Location)` | layout.py:2330 | `FreeSpot`, `via(net, PadRef)`, `vias(net, PadRef)` |
| `pour(points)` of pad-box arithmetic | layout.py:2484 | `swallow_pads=True` grows an outline over touching pads, but an outline is still drawn. "A pour covering these pads" has no form (specified: `board.pour_pads`) |
| `plane(outline=points)` | layout.py:2499 | the default whole board |
| `board.extent/envelope/claim/reach`, `board.pad().box`, `board.part().location` | layout.py:787-836, 707-714 | these are questions. Scripts use them to feed the arithmetic above (fixtures/mnb/modules/Buck_LM5164/Buck_LM5164_layout.py:44-83) |
| `placemat.geometry.Transform` imported by a script | e.g. Buck_LM5164_layout.py:27, 44-47 | none: used to work out which way a pad faces at a rotation |

## 3. Intent that is missing

Evidence: fixtures/mnb/modules/Buck_LM5164/Buck_LM5164_layout.py (placement
lines 88-116, copper 118-175), which is typical of the 18 fixtures. Also the
pad-references spec, which cites a board project's frame helper
workaround helpers (`beside`, `drawn_from_pad`, `pour`, `pour_box`) and
a boost module's `pads_pour` and lanes. Items marked SPEC are in
docs/superpowers/specs/2026-09-29-pad-references-design.md and not built
(I grepped src for `Beside`, `pour_pads`, `def lane`, `Origin(`,
`Envelope(`: none).

1. **A part beside another part at the envelope's own gap, aligned to a
   pad.** The fixture writes
   `Pin(SW, X(u_sw, (u_claim.left - usx) - l_claim.right + lsx), Y(u_sw))`
   (line 94) and `Centre(X(C_IN_HF, -(c0603_flat.width + c0805_up.width) / 2), ...)`
   (line 96). Why existing forms do not cover it:
   - `block` puts a satellite only on the pin's own outward normal
     (placer.py:566-576), only for a pad on the same net, and cannot be
     aimed at a flank.
   - `Pin`/`Centre` take a point, so the touching distance is computed.
   - `row` needs a board `Edge` or `Run` (layout.py:1679-1693).

   SPEC item 5 (`at=Beside(ref, side, gap=, level=, pad=)`).
2. **A row or column relative to a part, not a board edge.** The fixture's
   small-signal column is five `Centre(X(R_FB_BOT), Y(prev, COL_PITCH))`
   calls with `COL_PITCH = r0402_up.height` (lines 83-107). `row()` rejects
   anything that is not an `Edge` or a `Run`, and `behind=` only stacks
   behind another edge row on the same edge (layout.py:1697). Not in the
   spec.
3. **Pad and part edges as references.** `X()`/`Y()` give a pad's centre
   or a part's body centre only (layout.py:4248-4261). The fixture's
   `pad_size()` plus `w / 2 + IN` arithmetic (lines 49-55, 119-162) exists
   to reach a pad edge. SPEC items 1, 3, 4 (`PadRef.edge(side)`,
   `.width()`, `Origin`, `Envelope`).
4. **A pour shaped by a set of pads.** Six `board.pour` calls of 4-8
   vertices, each vertex a pad centre plus or minus half its size
   (lines 131-155). `swallow_pads` grows a given outline over touching
   pads (layout.py:2487) but does not make the outline. SPEC item 7
   (`board.pour_pads`), which covers the box round the pads only. An
   L-shaped or necked pool (the fixture's SW and FB pools) still needs
   points.
5. **A track in a lane beside pads, or through the gap between pads.**
   `COL_LANE = X(R_FB_BOT, r0402_up.width / 2 + CLR + W / 2)`,
   `SW_LANE = Y(u_bst, fh / 2 + OVER + LIP + CLR + W / 2)`, and the vout
   sense "through the annulus between the exposed pad and the south pin
   row" (lines 158-171). `Mid(a, b)` is the midpoint of two pad CENTRES
   (layout.py:4226), which is the gap centre only for equal pads facing
   each other. `row.inner` is a lane only for edge rows. SPEC item 6
   (`board.lane`) covers "beside a set of pads" and "between two sets".
6. **Turn a part so a named pad faces a direction or another pad.** The
   fixture defines `upright(part, north_net)` and `flat(part, east_net)`
   with `placemat.geometry.Transform` (lines 44-62) and feeds numeric
   rotations to every fixed part. Existing:
   - `Turned` is relative to another part's rotation;
   - the outward rule needs `faces()`, which is for cells (layout.py:2119);
   - a searched part picks its turn from links, but a `Pin`/`Centre` part
     does not search its rotation.

   Not in the spec. A form such as `rotation=Facing(PadRef(C, "VIN"),
   Edge.NORTH)` or `Facing(PadRef(C, "VIN"), toward=PadRef(U, "VIN"))`
   would say it.
7. **A keepout or cutout that turns with the part it is anchored to.**
   Probed: a keepout at `PadRef` of a part at rotation 90 is placed at
   rotation 0. `rotation=Turned(...)` is a TypeError (layout.py:2669
   `float(k.rotation)`; cutout layout.py:2642). A datasheet clearance
   around a turned module is wrong or must be hand-rotated.
8. **A keepout shaped by a part.** "No copper under this crystal or
   inductor" needs a `Path`/`Slot` typed or built from `board.extent`.
   `keepout` takes only a shape (layout.py:1197-1229).
9. **`Polar`/`ring` about a part or pad.** LEDs round an encoder, a ring
   round a button: `_as_point` accepts only a Location or a numeric pair
   (layout.py:4209-4215). Probed: both refused.
10. **A block placed on an edge or a line.** A connector with its ESD parts
    at its pins, on the west edge, is not expressible. `at=OnEdge` on a
    block is accepted, marked EDGE and ignored (section 6).
11. **Placing relative to a searched item** is refused for a firm item
    ("only FIXED and EDGE items may be referred to", layout.py:2793-2795).
    Already in BACKLOG.md:47-49, "Needs a spec". It forces a module's
    parts to be all fixed if any of them is placed relative to another,
    which is why the fixtures are 100% firm arithmetic.
12. **Arithmetic resolved late** is SPEC item 2 (`X(a) + Y(b) - k`). It
    moves the arithmetic into placemat. It does not replace it with
    intent. It makes the pattern the owner wants to retire easier to
    write, so it is worth deciding whether it ships before or after
    `Beside`/lanes/`pour_pads`.

## 4. The skill

SKILL.md loads one reference by name, "Read `references/api.md` for the
script surface. Everything below is how to work, not what to call"
(SKILL.md:14-15), and migration.md conditionally (SKILL.md:17-26). It has
no vocabulary list by design.

Passages that steer to intent:
- description (SKILL.md:3): "declare placement and copper by intent".
- SKILL.md:32-36: "A number that says where a part, a via or a track goes
  is a decision typed by hand, and a script full of those is not a style
  to follow. ... the next agent copies it into the next line and the next
  file."
- SKILL.md:38-41: "Write every new declaration by intent, whatever the
  lines round it do: links, blocks, rows, `fanout()`, `Near(PadRef(...))`
  for a need the netlist cannot say, `FreeSpot` for a via, a track ending
  on the via `board.via()` returns."
- SKILL.md:47-52: "A coordinate you cannot remove is a placemat gap ...
  record the gap".
- SKILL.md:391-395: "No floorplan by coordinate".
- SKILL.md:426-431: "Rows and references before numbers ... a part between
  two pads sits at `Mid()` of them ... A number typed where a reference
  would do is a defect."
- SKILL.md:434-437: "Two firm things that must sit beside each other are
  placed relative to each other (`behind=`, `after=`, a pad reference),
  never by independent numbers from opposite edges".
- SKILL.md:470-474: datasheet clearances anchored at the pad.

Passages that work against it:
- SKILL.md:192-194: "Every design number is a named constant ...
  Arithmetic on named values is fine; a bare scalar inside a `place()`,
  `track()` or `X()` is not." This describes the fixture style exactly:
  every offset is arithmetic on named measurements.
- SKILL.md:224-227: "Measure, do not type: `board.extent(cell,
  rotation=)`, `board.pitch(part)`, `board.pad(part, n).box` ...". Right
  against typed numbers, but it names measurements as the alternative
  rather than references.
- SKILL.md:29: the check grep `Location\((?!\s*X\()|\.offset\(|radius=0\b`
  excludes `Location(X(` and does not see `Centre(X(ref, expr), ...)`,
  `Pin(..., X(ref, expr), ...)` or `.local(`. On the 18 fixtures it reports
  0-1 for 17 while they hold 2-108 `X(`/`Y(` calls each (section 0).
- SKILL.md:247-250 endorses `placemat freeze`, which writes `.local(dx, dy),
  radius=0` and `Location(X(pad, dx), Y(pad, dy))`. SKILL.md:29-35 calls
  `radius=0` a typed position not to follow.
- SKILL.md:280-281: "Copper is declared against pads and lanes (`PadRef`,
  `CellPadRef`, `X()`, `Y()`)". There is no lane type. "Lanes" in practice
  means `X(pad, clearance arithmetic)`.
- SKILL.md:282: "Typed values: `Net`, `Part`, `Cell`, `CopperLayer`,
  `Edge`, `Location`" lists `Location` and none of the place types.
- api.md:26 calls `board.envelope` "what a row or stack built by hand
  spaces by".
- api.md's canonical placement block (api.md:55-67) leads with numeric
  `Location(x, y)` and `Near(Location(x, y))`.
- api.md's row example sizes the board by arithmetic (api.md:204).
- api.md's copper examples use numeric bus lines and taps (api.md:803-819)
  and a numeric pair centreline (api.md:907).

What is missing from the skill:
1. An intent-to-form index at the top of SKILL.md or api.md: "at a
   mechanical point -> Location with a cited constant; on an edge ->
   OnEdge; at a pin -> block/Pin; between two pads -> Mid; beside a part ->
   (gap); a column -> (gap); via -> FreeSpot; pad full of vias -> vias ...".
   api.md:1-5 opens with a partial import line and a table of questions,
   not places.
2. Module-specific guidance. The module fragments are where the arithmetic
   is (all 18 fixtures). The SKILL's placement advice is for boards
   ("leave the rest searched with a bare `place(item)`", SKILL.md:353-354).
   For a dense module it does not say which parts should still be searched
   within the module, or how, given item 11 in section 3.
3. A list of the known gaps (section 3) with the sanctioned interim form
   for each. Without it, SKILL.md:47-52 has every agent rediscover them,
   and the "smallest number that works" becomes the next agent's template.
4. A check line that catches `X(`/`Y(` with an offset argument, `.local(`
   and arithmetic on `board.claim/extent/pad().box`. The rule at
   SKILL.md:193 also needs to be reconciled: arithmetic on named
   measurements that says where a part goes is a typed position.
5. Guidance that frozen lines are a record, not a pattern to copy. Or
   freeze could write a comment or form that marks them.
6. The defects in section 6. `Near` on a cutout is recommended at
   SKILL.md:307 and crashes, and a block on an edge is silently ignored.
   Each teaches an agent that the intent form "does not work".

## 5. Strings that should be enums

| argument | where | values | fit |
|---|---|---|---|
| `row(align=)` | layout.py:1659; checked only as `== "center"` at 1715, 1726, 1834 | "start" (default), "center"; anything else is silently "start" | `Along` (values.py:69): START, MID; END could mean flush to the far keep-in |
| `row(line=)` | layout.py:1660, validated 1734 | "centre", "outer", "inner" | new `Line` (CENTRE, OUTER, INNER). Note the British "centre" here beside the American "center" in `align=` of the same call |
| `label(align=)` | layout.py:2132, validated 2153 | "centre", "start", "end" | `Along` (START, MID, END) |
| `label(rotation=)` | layout.py:2155 | 0 or 90 (number) | small enum (ACROSS, UP), or keep numbers |
| `keepout(excludes=)` / `Keepout.excludes` | layout.py:1198; values.py:613, 627 | "parts", "fill", "tracks", "vias", "pads" | new `Forbid` (PARTS, FILL, TRACKS, VIAS, PADS) |
| `layer=`/`layers=` on track, pair, pour, plane, finger, keepout, `FreeSpot.layer` | via `CopperLayer.of` values.py:34 | "F.Cu", "In1.Cu"... accepted as strings; api.md:490 uses `layers=["F.Cu"]` | `CopperLayer` exists; the string path could be dropped or documented as an alias |
| `place(face=)` | layout.py:1496 | `Face` only, unvalidated; `"back"` fails late with AttributeError (probed) | `Face` exists; validate with `Face(face)` |
| `faces(outward=/quiet=/handoff=)`, `fanout(sides=)`, `label(side=)` | layout.py:2109, 1866, 2174 | `Edge(v)` also accepts "N"/"S"/"E"/"W" | `Edge` exists (fine) |
| `CellPadRef(ref_prefix=)` / `cell_pad(ref_prefix=)` | values.py:414 | a refdes prefix string | not a fixed set. A refdes selector, which goes stale when refdes change (the rest of the API names instances) |
| SPEC: `PadRef.edge(side)`, `Envelope(item, side)`, `Beside(ref, side)` | pad-references spec items 1, 4, 5 | "n", "s", "e", "w", "ne", "nw", "se", "sw" | `Edge` for sides plus a new `Corner` (NE, NW, SE, SW). Worth changing before it is built |
| internal: `RowCoord.what` | layout.py:46-49, 124-127 | "inner"/"outer" with the offset encoded in the string ("inner+1.5") and parsed back with `float` | an enum plus a float field |
| internal: `PlaceIntent.kind`, `.rim`, `.pinned_by`, `Row.anchor[0]`, `_EdgeFraction.anchor` | layout.py:171, 193, 191, 67, 144 | "part/cell/block", "rim/bore", "at/center", "centre/end/start/before/after/outline", "start/centre/end" | internal; `pinned_by` uses "center" and `_EdgeFraction` uses "centre" |
| settings (TOML, not script): `place.envelope`, `place.rotations`, `write.split_groups`, `copper.cell_zones_under_planes` | settings.py | fixed string sets | validated at load; strings are natural in TOML |

## 6. Defects found while checking (probed unless noted)

1. **A block placed `at=OnEdge(...)` ignores the edge.**
   - Probe: `place(block, at=OnEdge(Edge.WEST, along=Along.MID))` on a
     50x50 board.
   - Result: freedom EDGE, the block lands at (25, 25).
   - `Location(20, None)` and `Centre(None, 45)` on a block are ignored the
     same way.
   - Cause: `_settle_block` (layout.py:3843-3850) reads only `i.at`,
     `i.center` and (searched) `i.near`. By reading, `OnRim`, `OnBore`,
     `Polar` with a freedom, and a `Run` are ignored the same way.
2. **`OnEdge(run, along=<reference>)` crashes.**
   - With no `rotation=`, any reference raises
     `TypeError: float() argument ... not 'X'` (or `'Mid'`) at declaration
     (layout.py:1634 -> outline.py:60).
   - With `rotation=`, `X()`/`Y()` raise "not a pad reference" at resolve
     (`_run_along` layout.py:4194 -> `_locate`, which does not take X/Y).
   - `Mid` works in that case.
   - api.md:645-646 documents a reference as working.
3. **A cutout or keepout `at=Near(...)` crashes** with
   `AttributeError: 'Near' object has no attribute 'x'`.
   - `_cutout_free` returns True for Near (layout.py:952), and
     `_cutout_candidates` then reads `at.x` (layout.py:983).
   - The call is not inside the `except ValueError` (layout.py:2635-2639,
     2661-2665).
   - Documented at api.md:417, 475 and SKILL.md:307.
4. **`row(align="centre")` (or "end", or `Along.MID`) silently behaves as
   "start"**: row start 0.4 against 21.7 for "center" (layout.py:1715-1732).
5. **`Polar(..., about=PadRef)` and `ring(..., about=Part)` raise
   TypeError** "a centre is a Location or an (x, y) pair" (`_as_point`
   layout.py:4209).
6. **A keepout at a pad of a turned part is not turned**, and
   `rotation=Turned(...)` raises TypeError (section 3 item 7).
7. **Unreachable code (by reading).** `_cutout_centre` (layout.py:932) and
   `_cutout_candidates` (layout.py:968) handle a non-numeric `Polar.radius`
   via `_coord`. `Polar.__post_init__` rejects any non-numeric radius
   (values.py:650-652), so that branch is never reached. A radius from a
   reference is not supported.
8. **Doc mismatches (by reading).**
   - migration.md:18-21 says `board.group` takes cells; the code refuses
     them.
   - api.md:4's import line is incomplete.
   - `board.claim` and `board.outward_rotation` are undocumented.
