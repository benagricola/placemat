# Hand-placed modules

Captures and scripts match each hand board by footprint reference/ID set and pad-net partition.
Each module retains its historical fragment_frame.py beside its script; helper versions are not merged.
The family uses the prescribed current board rules and non-routing settings for both hand and generated comparisons.
Routing phases are omitted for the pre-phase baseline.

| Module | Capture/script commit | Original hand file |
| --- | --- | --- |
| backlight | `e462b14a4bee648e98cf331dbee40d4da80906f3` | `backlight/layout_hand.kicad_pcb` |
| debug | `4deb0cfc8a7e28d6465093df42a4d98c105e7da2` | `debug/layout_hand-2026-09-30.kicad_pcb` |
| gnssreceiver | `c151a503f618c127a5d1e47e165004d97a5b6563` | `gnssreceiver/layout_hand-2026-09-30-2013.kicad_pcb` |
| mcu | `c151a503f618c127a5d1e47e165004d97a5b6563` | `mcu/2026-10-02/layout_hand.kicad_pcb` |
| protection | `444504a1d0a3b13c063e33d2efcd1a6ea0192c9c` | `protection/layout_hand-2026-09-30-2013.kicad_pcb` |
| supervisor | `c151a503f618c127a5d1e47e165004d97a5b6563` | `supervisor/layout_hand.kicad_pcb` |
| usb5v | `ca0c966534c82ddca7490d82b71c2b0734c5d0e4` | `usb5v/layout_hand.kicad_pcb` |
| usbconverter | `c151a503f618c127a5d1e47e165004d97a5b6563` | `usbconverter/layout_hand-2026-10-01-1009.kicad_pcb` |
| usbmoisture | `c151a503f618c127a5d1e47e165004d97a5b6563` | `usbmoisture/layout_hand.kicad_pcb` |
| usbpowerpath | `32e752c4f587abb52afb0c5ed7b88ff7de6305ae` | `usbpowerpath/layout_hand.kicad_pcb` |
| usbsink | `c151a503f618c127a5d1e47e165004d97a5b6563` | `usbsink/2026-10-03/layout_hand.kicad_pcb` |

Exact original file, project, helper and dependency digests and electrical-partition observations are in source-provenance.json.


The original hand PCB/project/custom-rule bytes are preserved. These are board
fragments with no Edge.Cuts: all eleven fail manufacturing validity on outline,
and Mcu also retains a VDD_RF/GND clearance violation. Their completed electrical
route reports are invalid diagnostics, not successful finished boards.

Four historical scripts use the documented 0.85 `board.size` to `board.rect`
rename with identical arguments. Protection and Usb5v additionally use the
0.67 fitted-pour migration: forbidden `cover` keywords and the unused Usb5v helper
parameter are removed. This changes pour geometry. Pad sets, nets, layers, widths
and placement intent are preserved; original and migrated hashes are recorded.
The old624 comparison runs the same migrated inputs as the feature. Its Protection
placement has nine clearance errors; Usb5v has two clearance and four shorting
errors plus two solder-mask-bridge findings. Electrical closure alone does not
certify these placements. Improvements must be attributed to the shared source
migration separately from changes to placement or routing.

The pre-phase baseline omitted routing phases. The checked-in family enables its
signal phase for current Placemat; common-contract comparisons grade saved old
and new copper under the same final obligations rather than trusting old closure
labels. Each historical helper remains module-local and is not modernized.
