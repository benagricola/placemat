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
3. The result is compared with the human board, and with placemat's own test (a) route of the human placement.

Test (a) runs on all eight boards. Test (b) needs the board to import with `pcb import`, so it runs on the boards
listed with `b` in `tests`.

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
| `islands` | Nets passed to `--islands` |
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
  link with a worked number), or searched. Each declaration has a `why=` naming its basis: mechanical, datasheet or
  physics. No steering: no priority, order, `Near` or link added to improve a result.
- **Routing phases:** the default set from `placemat settings --example`, plus only phases the capture's interfaces and currents
  call for.
- **A check:** a script lint in the runner lists every declaration by its basis. A reviewer checks each new or changed
  reference script against these rules before it is accepted.

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

pic_programmer needs `--islands VCC`: its pour does not reach its pads.
