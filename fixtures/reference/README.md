# Reference set

Eight open KiCad boards that humans routed. They measure placemat against a known-good result: each is pinned to a
commit in its upstream repository, and each file to a sha256, in `manifest.json`. The files are downloaded to
`~/.cache/placemat-reference/` (override with `$PLACEMAT_REFERENCE_CACHE`) and are not kept in this repo.

## The two tests

**Test (a), route the human placement:**
1. Strip the copper, keeping the zone definitions.
2. Record the stripped board's DRC as the baseline: several originals already fail DRC once stripped.
3. Route with the board's own layer count, net-class rules and via sizes.

Pass is 100% clean closure, with no copper DRC error beyond the baseline. Closure is also recorded at the widths the
human actually used (`human_track_mm` in the manifest). Vias and track length are compared with the human board.

**Test (b), place and route:**
1. The board's mechanical parts (connectors, holes, edge parts) are held where the original put them (`fixed` in the
   manifest).
2. placemat places everything else and routes it.
3. The result is compared with the regenerated reference, and with placemat's test (a) route of the original placement.

Test (b) regenerates its reference with `pcb import` followed by `pcb layout`, using the pinned source project.
Its vias, track length and stripped DRC are judged against that regenerated board. Both reference and placement
run use the imported capture's library footprints. The original human placement remains test (a)'s reference.

Test (a) runs on all eight boards. Test (b) needs the board to import with `pcb import`, so it runs on the boards
listed with `b` in `tests`.

Reference subprocesses share a bounded router deadline and own their process groups. A timeout or interruption
reaps that group; an earlier inherited router deadline is retained. The ordinary wait is bounded by the configured
timeout; shutdown can add five seconds of TERM grace and a one-second pipe drain after KILL. Placement results require exit code zero and a
new or rewritten `run.json` from that invocation. A stale or malformed record cannot supply a successful result.
Full placement stdout/stderr, argv, working directory, deadline and record digest are retained under the copied script's
`.placemat/reference-runs/`. Regenerated references retain each import/layout/legacy-upgrade command and its full
stdout/stderr beside their output, including failed commands.

## Fetching

    .venv/bin/python fixtures/reference/fetch.py [name ...] [--offline]

Prints one line per board (fetched, cached, or the error) and exits 1 on any error. A cached file is used when its
sha256 matches the manifest; any other is downloaded from the raw URL of the pinned commit and checked.
`--offline` fails instead of downloading.

From Python, `fetch.load_manifest()` returns the boards and `fetch.fetch(board)` returns the folder holding a board's
files.

## Manifest keys

| Key | Meaning |
|---|---|
| `name` | Board name, and its folder in the cache |
| `repo`, `commit` | `github:owner/repo` or `gitlab:kicad/code/kicad`, and the commit SHA |
| `files` | Path in the repo -> sha256: the `.kicad_pcb`, `.kicad_pro`, `.kicad_dru` where present, and every schematic sheet (`.pro` and `.sch` for KiCad 5) |
| `board` | Path of the `.kicad_pcb` |
| `licence` | SPDX identifier |
| `tests` | `a` and/or `b` |
| `phases` | Named routing phases before the board defaults: explicit nets, pairs and buses |
| `fixed` | References held at the human board's coordinates in test (b) |
| `human_track_mm` | The human board's most-used track width |
| `kicad5` | The board is a KiCad 5 file |
| `notes` | Optional free text |

## The rules for a reference script

A reference script is as simple as the board allows, so the set measures
placemat rather than the quirks of a script.
- **Fixed parts:** only those a human layout engineer fixes for mechanical reasons. These are connectors, mounting
  holes, switches and buttons, displays, LEDs at enclosure windows, antennas and their keepouts, and edge parts. They
  are held at the human board's coordinates, which is allowed for the reference set only (decided with the user).
- **Everything else is intent:** relations from the circuit (a bypass capacitor at its pin, a crystal at its MCU, a
  link with a worked number), or searched. Each declaration has a `why=` naming its basis: mechanical, datasheet,
  physics or capture (a fact read from the capture's own annotations). No steering: no priority, order, `Near` or
  link added to improve a result.
- **Routing phases:** the default set from `placemat settings --example`, plus only phases the capture's interfaces and currents
  call for.
- **A check:** a script lint in the runner lists every declaration by its basis. A reviewer checks each new or changed
  reference script against these rules before it is accepted.

## Using the set in a step

`results.json` holds the recorded baseline: test (a) at class and human widths, test (b) on the two open boards, and
the module runs. Each entry carries the placemat, router and zener versions it was made with.

Before a release, run `route_ref.py`, `place_ref.py` and `place_ref.py --modules`, and put each board's and module's
tally in the release commit. A run compares each entry with the recorded one and prints new, same, better, worse or
not comparable. An entry is not comparable when a component not named in `--changing` has another version; the line
then also gives what the values alone say. `--changing` takes one or more of `placemat`, `krt` and `pcb` (default
`placemat`) and goes after the board names: a step that changes the router and placemat together passes
`--changing placemat krt`.

A board or module whose preparation or run raises is a failed result, with the exception's type as its failure, and the
run goes on to the next. A failure where the recorded entry had none is worse.

The ratchet: no board or module may get worse without the user's approval. `--update` writes the entries that are
new, same, better or not comparable, and holds back an entry that is worse, and one that is not comparable but worse
on its values. `--accept-worse` writes them anyway and records that the user approved the loss; it is never passed
without that approval. `--update` writes after each board or module, so a run that stops keeps the ones it finished.

## The script lint

    .venv/bin/python fixtures/reference/lint.py <board name>

Reads the script in `fixtures/reference/boards/<name>/` with `ast`, never running it. It prints every declaration (a
placement, a link or a piece of copper) grouped by its basis, then the problems, and exits 1 on any problem.

Basis prefixes: a `why=` starts with `mechanical:`, `datasheet:`, `physics:` or `capture:`.

| Rule | Problem |
|---|---|
| `coordinate` | A typed position on a part the manifest does not list in `fixed`, or in the points of copper (`track`, `via`, `pour`, ...), a keepout or a `push`, where nothing is fixed: `Location(...)`, a numeric `Centre` or `coordinates=True`, `Pin(key, x, y)`, an `X()`/`Y()` with an offset, `OnEdge(along=<number>)`, `.point()`, `.local()`, `.offset()`, a bare `(x, y)` |
| `no_why` | A placement, link or copper call with no `why=` |
| `basis` | A `why=` that starts with none of the prefixes (a `board.figure`: not `datasheet:`), or cannot be read without running the script |
| `steering` | `priority=`, `Priority`, `Near(` or an order call (`board.order`, `before`, `after`), whatever its basis |
| `syntax` | The script does not parse |

A coordinate on a fixed part is listed with the declaration (`[coordinate]`) and is not a problem.

## Boards

| Name | Licence | Source | Tests |
|---|---|---|---|
| pic_programmer | CC-BY-SA-4.0 | https://gitlab.com/kicad/code/kicad, tag 10.0.6, `demos/pic_programmer` | a, b |
| usb-c-power-adapter | Apache-2.0 | https://github.com/antmicro/usb-c-power-adapter | a, b |
| lora-v3 | MIT | https://github.com/Strooom/LoRa-V3-PCB | a |
| ir-irradiance-probe | Apache-2.0 | https://github.com/antmicro/infrared-irradiance-probe | a |
| esp-rust-board | CERN-OHL-P-2.0 | https://github.com/esp-rs/esp-rust-board | a |
| watchy | MIT | https://github.com/sqfmi/watchy-hardware | a |
| spimux | MPL-2.0 | https://github.com/oxidecomputer/hw-spimux | a |
| chainlinkDriver | Apache-2.0 | https://github.com/scottbez1/splitflap, `electronics/chainlinkDriver` | a |

pic_programmer uses a `vcc` phase for VCC: its pour does not reach its pads.

## Local fixtures

The `fixtures` key in results.json records each local fixture's phase requests,
joins, final clean closure and open connections, including router diagnoses and
blocker names. These comparisons say `same` or `changed`; an intentional failed
connection can be the behavior the fixture verifies.

`obstructed-route` is the local two-layer current-path fixture in
`fixtures/obstructed_route`. U1 blocks the requested wide route between J1 and
J2; a later class-width route joins the net while the original width remains
unfulfilled. Run it with `route_ref.py obstructed-route`; a default route_ref
run includes all local fixtures alongside the manifest boards under the same
shared real-board lock.


### Hand-placed modules

A family may keep `hand/<Name>.kicad_pcb` beside `modules/*/<Name>_layout.py`.
The module runner strips and routes the hand reference with the same family
settings, and records clean closure, open joins, airwire crossings and length.
Both the hand board and the generated placement use the box around KiCad's
cached front/back courtyard polygons (footprint bounds when absent). Cached
polygons include KiCad's stroke extent; they can extend beyond the drawing's
centreline. The same method applies to both boards, including side and rotation.
These facts accompany the existing module closure/area comparison. A failed
hand preparation or route remains visible as a failed reference fact.
The hand runner retains the full family configuration and script context in its
owned copy, checks effective settings against the source, and refuses ambiguous
module-specific routing overrides. A completed invalid route stays failed;
`route_diagnostic` separately records its electrical closure and manufacturing
findings, with fresh report, board and completion-record hashes.

`fairing_hand` holds eleven historical module references. Its source manifest
records original hand/project/helper hashes and the required API migrations.
The fitted-pour migrations change geometry and are shared by the old-source and
feature comparisons. These hand boards have no physical outline, and Mcu also
has an inherited clearance violation; their diagnostics do not certify finished
boards. See the family's notes for the migrated placements' additional findings.
