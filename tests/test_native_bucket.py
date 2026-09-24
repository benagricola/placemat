"""Occupancy.legal_bucket: a scan's sweep only ever keeps one example
sentence per rejection bucket (ScanResult.reasons), however many candidates
land in it, so on the native near-obstacle path it defers _conflict's own
formatting (who()'s cell lookups, _cross_face_note, the %-formatting) until
a bucket is asked for a second time. This is a real saving only because
Occupancy._native_bucket derives the SAME bucket _reason_key would from the
formatted sentence, without formatting one - see that method's own doc in
occupancy.py for the reasoning per conflict kind, and
docs/superpowers/specs/2026-09-24-native-core-design.md for the profile that
motivated it.

Two levels of test, matching this project's own established pattern
(test_native_conflict.py, test_native_legal.py):
1. _native_bucket agrees with _reason_key(the real sentence) on every
   conflicting pair a rich synthetic occupancy can produce - the bucket
   derivation in isolation, independent of native being built at all.
2. legal_bucket agrees with legal() end to end - same bucket-or-None, same
   sentence (once formatted), same blame - on randomised candidates against
   real fixture boards, with native on and with PLACEMAT_NATIVE=0.
"""
import pathlib
import random

import pytest

from placemat.occupancy import Occupancy, _reason_key
from placemat.placement import Placement
from placemat.values import Location
from tests.test_native_conflict import _all_shapes, _rich_occupancy


@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_native_bucket_agrees_with_reason_key_on_every_conflicting_pair(envelope):
    occ = _rich_occupancy(envelope=envelope, vias_block_courtyards=True)
    shapes = [s for s, *_ in _all_shapes(occ)]
    assert len(shapes) >= 8
    rnd = random.Random(20260924)
    checked = 0
    mismatches = []
    for _ in range(20000):
        a = rnd.choice(shapes)
        b = rnd.choice(shapes)
        why = occ._conflict(a, b, None)
        if why is None:
            continue
        checked += 1
        want = _reason_key(why)
        got = occ._native_bucket(a, b)
        if want != got:
            mismatches.append((a.kind, b.kind, why, want, got))
    assert checked > 200, "fuzz found too few actual conflicts to be a meaningful check"
    assert not mismatches, mismatches[:10]


@pytest.mark.parametrize("board_name,envelope", [
    ("fairing/modules/SlotControl/layout/layout.kicad_pcb", "physical"),
    ("fairing/modules/SlotControl/layout/layout.kicad_pcb", "courtyard"),
    ("mnb/modules/MCU_RP2350B/layout/layout.kicad_pcb", "union"),
])
def test_legal_bucket_agrees_with_legal_end_to_end(board_name, envelope):
    pytest.importorskip("pcbnew")
    from placemat.kicad.read import read_board
    board = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / board_name
    if not board.exists():
        pytest.skip("fixture board not found")
    from placemat.settings import Settings
    import dataclasses
    g = read_board(board)
    settings = dataclasses.replace(Settings(), place_envelope=envelope)
    occ = Occupancy(g, edge_margin=0.2, settings=settings, component_spacing=0.2)
    rnd = random.Random(hash(("bucket", board_name, envelope)) & 0xFFFFFFFF)
    fps = list(g.footprints)
    mismatches = []
    checked_conflicts = 0
    for _ in range(600):
        item = rnd.choice(fps)
        cx, cy = item.location.x, item.location.y
        x, y = cx + rnd.uniform(-8, 8), cy + rnd.uniform(-8, 8)
        rot = rnd.choice([0, 90, 180, 270])
        placement = Placement(Location(x, y), rot, item.face)
        clearance = rnd.choice([None, None, None, 0.1, 0.3])
        geom = occ._geometry(item)
        others = occ.obstacles(geom)

        blame_legal = []
        why = occ.legal(item, placement, clearance, others=others, blame=blame_legal)

        blame_bucket = []
        hit = occ.legal_bucket(item, placement, clearance, others, blame_bucket)

        if why is None:
            if hit is not None:
                mismatches.append(("legal says fine, bucket says rejected", placement, hit))
            continue
        if hit is None:
            mismatches.append(("legal rejects, bucket says fine", placement, why))
            continue
        checked_conflicts += 1
        bucket, get_reason = hit
        if bucket != _reason_key(why):
            mismatches.append(("bucket mismatch", placement, why, bucket, _reason_key(why)))
        reason = get_reason()
        if reason != why:
            mismatches.append(("reason mismatch", placement, why, reason))
        bl = [(b.kind, b.owner, b.faces) for b in blame_legal]
        bb = [(b.kind, b.owner, b.faces) for b in blame_bucket]
        if bl != bb:
            mismatches.append(("blame mismatch", placement, bl, bb))
    assert checked_conflicts > 20, "fuzz found too few rejections to be a meaningful check"
    assert not mismatches, mismatches[:10]
