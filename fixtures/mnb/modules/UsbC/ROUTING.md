# Capture-based pair selection

`USB_CONN` binds the existing connector-to-ESD P/N nets as a named `DiffPair`.
The binding preserves the net names, footprint identities, pad-net partition,
classes, project dimensions and physical rules. The module routes that pair
phase before the family's signal phase. Width and gap remain in the project.

The generated identity/phase proof found both pair legs already joined by
declared copper, so its pair phase made zero router calls. The separate
`partly_joined_pair` fixture exercises an actual one-leg-open call.

The module's original placed board and the captured input/final board all
reported the same missing outline and two connector hole-clearance violations
(0.235 mm against the original 0.25 mm rule). No manufacturing success or
reference pin is implied by this capture/config migration.
