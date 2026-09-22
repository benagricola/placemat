# Adapted local assets

`parts/` contains KiCad 10 symbols and Zener wrappers. The original downloaded
symbols, footprints and provenance under `../parts/` remain unchanged.

Generate with `python3 modular/tools/upgrade_symbols.py` from the repository
root. It invokes KiCad's supported upgrader, verifies pin identity and geometry,
then writes `symbol-conversion.json` with source/output hashes and pin tables.
Regeneration refuses to overwrite an output that differs from the manifest.

The converted libraries retain vendor electrical pin types, including
`unspecified`. Conversion makes the files readable by Zener's exporter; it does
not qualify electrical pin types, footprints or component models. Footprint
references still resolve to original assets until separately qualified.

Core sheets use these wrappers. The reference Main circuit continues to use
its preserved source wrappers. `boards/core/GnssAntenna.zen` is an independent
copy of the reference antenna cell with schematic generation enabled and
imports changed to adapted wrappers; its component connectivity is unchanged.
