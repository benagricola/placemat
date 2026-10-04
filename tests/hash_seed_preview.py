"""Prints the preview JSON (durations removed) of a small board whose escapes cross at a pin row, for
tests/test_hash_seed_order.py to compare between interpreter runs with different hash seeds."""
import dataclasses
import json

from placemat.layout import Board
from placemat.preview_json import declared_sites, plan_json
from placemat.settings import Settings
from placemat.values import Part
from tests.fixtures import board_geometry
from tests.test_cleanup_swaps import two_pad, west_row

NETS = {2: "NB", 3: "NA", 4: "NC"}


def board():
    fps = [west_row("U2", "mcu", 30, 30, NETS),
           two_pad("R1", "r_a", 24.0, 31.5, ("GND", "NA")),
           two_pad("R2", "r_b", 24.0, 33.0, ("GND", "NB")),
           two_pad("R3", "r_c", 24.0, 27.0, ("GND", "NC"))]
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b


def untimed(doc):
    for k in ("seconds", "first_seconds"):
        doc.pop(k, None)
        for s in doc["steps"] + doc["items"]:
            s.pop(k, None)
    return doc


if __name__ == "__main__":
    b = board()
    print(json.dumps(untimed(plan_json(b.resolve(), declared_sites(b)))))
