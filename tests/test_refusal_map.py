"""The refusal map (scanmap.py, `place.refusal_map`): the candidates of a pass that a shape of the item lying across a shape
of the board is certain to refuse, found from the shapes and left out of what is judged. It is conservative: over random
boards and items, a scan with the map finds every spot the full sweep finds, in the same order, natively and in Python,
and refuses as many candidates, the edge's and the reservations' among them as counted."""
import dataclasses
import math
import random

import pytest

from placemat import giveway, placer, scanmap
from placemat.geometry import point_in_polygon
from placemat.occupancy import Blocker
from placemat.refusals import Code, Refusal
from placemat.settings import Settings
from placemat.values import Box
from tests.scan_scenes import scene

NATIVE = placer._geometry_module._native is not None
_ON = dataclasses.replace(Settings(), place_refusal_map=True, place_refusal_map_after=30, place_coarse_min_radius_steps=1e9)
_OFF = dataclasses.replace(_ON, place_refusal_map=False)


def _resolve(occ, item, placement, clearance=None, others=None):
    k = int(placement.location.x * 8) + int(placement.location.y * 8)
    if k % 3 == 0:
        return giveway.Resolution(why=Refusal(Code.HOLE_TO_HOLE), blocker=Blocker("hole", "viacell", frozenset()))
    return giveway.Resolution(cost=0.25 * (k % 4))


def _score(cand):
    return round(cand.location.x * 0.013 + cand.location.y * 0.007 + cand.rotation * 1e-4, 6)


def _scan(occ, item, hint, rots, settings, radius=6.0):
    occ.settings = settings
    seen = []

    def pick(ranked):
        seen.extend(ranked)
        return ranked[0]
    r = placer.scan(occ, item, hint, radius, 0.25, rots, None, score=_score, pick=pick)
    for why in r.reasons.values():
        if why.facts:
            str(why)                # every sentence the map's tallies stand on is one the judge can say
    return r, seen


class _Named:
    """How many candidates the maps of a run name, and in how many scans."""

    def __init__(self, monkeypatch):
        self.named = self.scans = 0
        real = scanmap.RefusalMap.split

        def split(rm, triples, after):
            kept, stood, named = real(rm, triples, after)
            self.named += len(named)
            return kept, stood, named
        monkeypatch.setattr(scanmap.RefusalMap, "split", split)
        witness = scanmap.RefusalMap.witness_at

        def witness_at(rm, t, x, y):
            w = witness(rm, t, x, y)
            if w >= 0:
                self.named += 1
            return w
        monkeypatch.setattr(scanmap.RefusalMap, "witness_at", witness_at)
        built = scanmap.RefusalMap.__init__

        def init(rm, *a, **k):
            built(rm, *a, **k)
            self.scans += 1
        monkeypatch.setattr(scanmap.RefusalMap, "__init__", init)


def _compare(native, envelope, cell, scenes, monkeypatch, seed=0):
    monkeypatch.setattr(placer, "NATIVE_SWEEP", native)
    monkeypatch.setattr(giveway, "resolve", _resolve)
    named = _Named(monkeypatch)
    rnd = random.Random({"courtyard": 31, "physical": 47}[envelope] + 5 * cell + seed)
    for n in range(scenes):
        occ, item, hint, rots = scene(rnd, envelope=envelope, cell=cell, vias=rnd.random() < 0.4, reserve=rnd.random() < 0.5,
                                      parts=rnd.randint(10, 24), ties=rnd.random() < 0.5)
        full, full_ranked = _scan(occ, item, hint, rots, _OFF)
        mapped, mapped_ranked = _scan(occ, item, hint, rots, _ON)
        assert mapped_ranked == full_ranked, "scene %d" % n
        assert (mapped.chosen, mapped.tried, mapped.score) == (full.chosen, full.tried, full.score), "scene %d" % n
        assert sum(mapped.rejected.values()) == sum(full.rejected.values()), "scene %d" % n
        for bucket in ("edge", "reservation") + (("body",) if envelope == "physical" else ()):   # the board's own say is the judge's, as ever
            assert mapped.rejected.get(bucket, 0) == full.rejected.get(bucket, 0), (n, bucket)
    return named


@pytest.mark.parametrize("native", [True, False] if NATIVE else [False], ids=lambda n: "native" if n else "python")
@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
@pytest.mark.parametrize("cell", [False, True], ids=["part", "cell"])
def test_a_scan_with_the_map_finds_what_the_full_sweep_finds(native, envelope, cell, monkeypatch):
    named = _compare(native, envelope, cell, 36 if native else 14, monkeypatch)
    assert named.scans >= 6 and named.named >= 2000, (named.scans, named.named)


def test_a_few_scans_with_the_map_find_what_the_full_sweep_finds(monkeypatch):
    named = _compare(NATIVE, "courtyard", True, 5, monkeypatch, seed=100)
    assert named.scans >= 1 and named.named > 0, (named.scans, named.named)


def test_a_core_is_the_largest_box_the_shape_is_known_to_hold():
    rnd = random.Random(8)
    from placemat.occupancy import Shape
    from placemat.values import Face
    checked = 0
    for _ in range(300):
        k = rnd.randint(3, 14)
        cx, cy, r = rnd.uniform(-5, 5), rnd.uniform(-5, 5), rnd.uniform(0.3, 3.0)
        stretch = rnd.uniform(0.3, 1.0)
        angles = sorted(rnd.uniform(0, 2 * math.pi) for _ in range(k))
        poly = tuple((cx + r * math.cos(a), cy + stretch * r * math.sin(a)) for a in angles)
        shape = Shape("u", "courtyard", frozenset([Face.FRONT]), frozenset(), "", poly, Box.of_points(poly))
        core = scanmap.core_of(shape)
        if core is None:
            continue
        checked += 1
        inside = [(core.left + f * core.width, core.top + g * core.height) for f in (0.0, 0.25, 0.5, 0.75, 1.0)
                  for g in (0.0, 0.25, 0.5, 0.75, 1.0)]
        assert all(point_in_polygon(p, poly) for p in inside), poly
    assert checked >= 100


def test_a_rectangle_is_its_own_core_and_a_concave_outline_has_none():
    from placemat.occupancy import Shape
    from placemat.values import Face
    rect = ((0, 0), (4, 0), (4, 2), (0, 2))
    ell = ((0, 0), (4, 0), (4, 1), (1, 1), (1, 3), (0, 3))
    make = lambda poly: Shape("u", "courtyard", frozenset([Face.FRONT]), frozenset(), "", poly, Box.of_points(poly))
    assert scanmap.core_of(make(rect)) == Box(0, 0, 4, 2)
    assert scanmap.core_of(make(ell)) is None


def test_the_map_is_off_unless_asked_for():
    assert Settings().place_refusal_map is False
