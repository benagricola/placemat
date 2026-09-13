# Placemat Greenfield

A clean-room prototype for deterministic PCB layout intent and offline position scanning.

The script describes placement and copper intent. The scanner resolves locations and rotations deterministically, records the decision, and leaves source intent unchanged.

```sh
uv run pytest
uv run placemat scan --width 126.5 --height 229.925 --json scan.json
```
