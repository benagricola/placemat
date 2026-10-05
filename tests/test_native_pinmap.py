"""The native pin map core is the Python twin: on the same arrays, seeds and step budget, the same present score, the
same best map per pose with the same tallies to the last bit, the same airwires, the same steps and budget outcome."""
import itertools
import json
import random
import struct
from types import SimpleNamespace

import pytest

from placemat.pinmap_core import native_core, params_of, poses_of, problem_of, search
from tests.conftest import needs_kicad
from tests.pinmap_boards import input_of, point_pad, quad, reversed_four, settings

pytestmark = pytest.mark.skipif(native_core() is None, reason="the native module is not in use or predates the pin map core")


def bits(x):
    """`x` with every float as its bit pattern, so a comparison is to the last bit."""
    if isinstance(x, float):
        return ("f", struct.pack("<d", x).hex())
    if isinstance(x, (list, tuple)):
        return [bits(v) for v in x]
    return x


def both(inp, refs, s, guard_ms=None):
    pb = problem_of(inp, s.pins_exit_mm)
    at = {p.ref: i for i, p in enumerate(inp.parts)}
    lists = [[(at[r], t, f) for t, f in poses_of(inp.part(r), s)] for r in refs]
    combos = [list(c) for c in itertools.islice(itertools.product(*lists), s.pins_joint_combinations)]
    pr = params_of(s, refs, guard_ms=guard_ms)
    norm = lambda x: bits(json.loads(json.dumps(x)))
    return (norm(search(pb, [at[r] for r in refs], combos, pr, native=True)),
            norm(search(pb, [at[r] for r in refs], combos, pr, native=False)))


def constrained():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D", "E", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinFixed": "1", "Pm.PinAllow": "B:2,3", "Pm.PinDeny": "C:3",
                     "Pm.PinGroup": "bus!:4-5"}, may_flip=True)
    for i, net in enumerate("ABCDE"):
        pads += point_pad("T%d" % i, net, 20, 12.5 - i)
    return input_of(pads, {"U1": u1})[0]


def joint():
    p1, a = quad("U1", 10, 10, {"W": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"}, may_flip=True)
    p2, b = quad("U2", 20, 10, {"E": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    return input_of(p1 + p2, {"U1": a, "U2": b})[0]


def held():
    """A bus on 2-4 whose middle net a rule holds on 3: its present place is a window, first."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "D", "E", "F", "", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinAllow": "E:3", "Pm.PinGroup": "bus!:2-4"}, may_flip=True)
    for i, net in enumerate("ADEF"):
        pads += point_pad("T%d" % i, net, 20, 7.5 + i)
    return input_of(pads, {"U1": u1})[0]


def gapped():
    """A bus on 1-3 with no net on 2, and a net whose target faces pin 2."""
    pads, u1 = quad("U1", 10, 10, {"E": ["D", "", "F", "S"], "S": ["G", ""]},
                    {"Pm.PinPool": "1-6", "Pm.PinGroup": "bus!:1-3"}, may_flip=True)
    pads += point_pad("T1", "D", 20, 8.5) + point_pad("T2", "S", 14, 9.5) + point_pad("T3", "F", 20, 10.5)
    pads += point_pad("T4", "G", 4, 18) + point_pad("Q1", "X", 16, 4) + point_pad("Q2", "X", 17, 20)
    return input_of(pads, {"U1": u1})[0]


def grounded():
    """A plane net on a studied pin, re-posed with the part, and a net crossing it at a half turn."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"], "N": ["GND", ""]}, {"Pm.PinPool": "1-2, 4"}, may_flip=True)
    pads += point_pad("T1", "A", -20, 10) + point_pad("T2", "B", 30, 4) + point_pad("J1", "GND", -20, 9)
    pads += point_pad("J2", "GND", 12, -5)
    return input_of(pads, {"U1": u1}, quiet={"GND"})[0]


def beside():
    """Two parts, each with its own nets: U1's group counts only its own. A board airwire crosses both."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"}, may_flip=True)
    pads += point_pad("T1", "A", 20, 10.5) + point_pad("T2", "B", 20, 9.5)
    p2, u2 = quad("U2", 30, 10, {"W": ["C", "D", "E", "F"]}, {"Pm.PinPool": "1-4"})
    for i, n in enumerate("CDEF"):
        p2 += point_pad("S%d" % i, n, 15, 8.5 + i)
    p2 += point_pad("Q1", "X", 18, 2) + point_pad("Q2", "X", 24, 18)
    return input_of(pads + p2, {"U1": u1, "U2": u2})[0]


def soft():
    """A soft bus of four on the east side round a net a rule holds, one net's target far south past a fence of board
    airwires, and free pins on the south side."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C", "D", "E"], "S": ["", "", "", ""]},
                    {"Pm.PinPool": "1-9", "Pm.PinAllow": "C:3", "Pm.PinGroup": "bus:1-5"}, body=6.0, may_flip=True)
    for i, net in enumerate("ABCD"):
        pads += point_pad("T%d" % i, net, 25, 8 + i)
    pads += point_pad("T4", "E", 12, 30)
    for k in range(3):
        pads += point_pad("Q%da" % k, "X%d" % k, 12.6, 20 + k) + point_pad("Q%db" % k, "X%d" % k, 20, 20 + k)
    return input_of(pads, {"U1": u1})[0]


def rf_cell():
    """U1 in a cell with C1, whose RF net (a controlled impedance) runs to an antenna far east, and a net inside the
    cell: their lengths turn with the cell."""
    from tests.pinmap_boards import in_cell, two_pad
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"], "S": ["IN"]}, {"Pm.PinPool": "1-2", "Pm.PinGroup": "ab:1-2"})
    pads += point_pad("TA", "A", -15, 12) + point_pad("TB", "B", -15, 8)
    pads += two_pad("C1", "RF", "IN", 15, 10) + point_pad("ANT", "RF", 40, 10)
    parts, cells = in_cell("logic", pads, {"U1": u1}, ["U1", "C1"])
    return input_of(pads, parts, cells=cells, netclasses={"RF": SimpleNamespace(tuning_profile="z50")})[0]


def laid_diagonal():
    """U1 laid at 45 degrees, a part that may flip, with a bus and a plane net: studied in its own frame."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C"], "S": ["", ""], "N": ["GND"]},
                    {"Pm.PinPool": "1-5", "Pm.PinGroup": "ab:1-2"}, rotation=45.0, may_flip=True)
    pads += point_pad("TA", "A", 30, -8) + point_pad("TB", "B", 28, -11) + point_pad("TC", "C", -6, 25)
    pads += point_pad("J1", "GND", 2, 2) + point_pad("Q1", "X", 12, -4) + point_pad("Q2", "X", 24, 6)
    return input_of(pads, {"U1": u1}, quiet={"GND"})[0]


def cell_at_30():
    """U1 and C1 in a cell standing at 30 degrees, C1's net a controlled impedance to an antenna."""
    from tests.pinmap_boards import in_cell, two_pad
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"], "W": ["", ""]}, {"Pm.PinPool": "1-4"}, rotation=30.0)
    pads += point_pad("TA", "A", -15, 12) + point_pad("TB", "B", 25, -8)
    pads += two_pad("C1", "RF", "", 15, 12) + point_pad("ANT", "RF", 40, 10)
    parts, cells = in_cell("logic", pads, {"U1": u1}, ["U1", "C1"], rotation=30.0)
    return input_of(pads, parts, cells=cells, netclasses={"RF": SimpleNamespace(tuning_profile="z50")})[0]


CASES = {"four": (lambda: input_of(*reversed_four())[0], ("U1",)), "constrained": (constrained, ("U1",)),
         "joint": (joint, ("U1", "U2")), "held": (held, ("U1",)), "gapped": (gapped, ("U1",)),
         "grounded": (grounded, ("U1",)), "beside": (beside, ("U1",)), "soft": (soft, ("U1",)),
         "rf_cell": (rf_cell, ("U1",)), "laid_diagonal": (laid_diagonal, ("U1",)), "cell_at_30": (cell_at_30, ("U1",))}


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("turns", [(0.0, 90.0, 180.0, 270.0), tuple(range(0, 360, 45))])
def test_the_native_core_is_the_twin_on_fixed_cases(case, turns):
    make, refs = CASES[case]
    native, python = both(make(), refs, settings(pins_rotations=turns, pins_faces=True, score_crossing_plane=0.7))
    assert native == python


@pytest.mark.parametrize("case", ["held", "gapped", "soft"])
def test_the_native_core_is_the_twin_at_the_present_pose_with_a_short_search(case):
    # one seed of 100 moves: the present map, or the first, is kept as the best where the search finds worse
    make, refs = CASES[case]
    for key in range(6):
        s = settings(pins_rotations=(0.0,), pins_anneal_moves=100, pins_seeds=1)
        inp = make()
        pb = problem_of(inp, s.pins_exit_mm)
        pr = dict(params_of(s, refs), seed_key=key * 0x9E3779B97F4A7C15 % (1 << 64))
        combos = [[(0, 0.0, False)]]
        native = bits(json.loads(json.dumps(search(pb, [0], combos, pr, native=True))))
        assert native == bits(json.loads(json.dumps(search(pb, [0], combos, pr, native=False))))


def test_the_native_core_is_the_twin_when_the_budget_is_spent():
    # spent part way through the third pose: a twin that counted its steps another way would stop elsewhere
    s = settings(pins_budget_steps=4500, pins_anneal_moves=500, pins_seeds=4)
    native, python = both(input_of(*reversed_four())[0], ("U1",), s)
    assert native == python and native[3] is True and len(native[2]) == 3 and native[6] == 4500 and native[7] is False


def test_both_cores_give_no_map_past_the_wall_clock_guard():
    for core in both(input_of(*reversed_four())[0], ("U1",), settings(), guard_ms=1e-9):
        assert core[2] == [] and core[7] is True


def random_board(seed):
    rng = random.Random(seed)
    nets = ["N%d" % i for i in range(rng.randint(3, 9))]
    sides = {s: [] for s in "ESWN"}
    for net in nets + [""] * rng.randint(1, 4):
        sides[rng.choice("ESWN")].append(net)
    quiet = rng.random() < 0.6
    if quiet:
        sides["N"].append("GND")
    n = sum(len(v) for v in sides.values())
    fields = {"Pm.PinPool": "1-%d" % (n - 1 if quiet else n)}
    if rng.random() < 0.6:
        size = rng.choice((3, 4))
        start = rng.randint(1, max(1, (n - 1 if quiet else n) - size + 1))
        fields["Pm.PinGroup"] = "bus%s:%d-%d" % (rng.choice(("", "!")), start, start + size - 1)
    if rng.random() < 0.4:
        fields["Pm.PinFixed"] = str(rng.randint(1, n - 1 if quiet else n))
    pads, u1 = quad("U1", 15, 15, sides, fields, body=rng.choice((4.0, 6.0)), rotation=rng.choice((0.0, 0.0, 90.0, 45.0)),
                    may_flip=True)
    for i, net in enumerate(nets):
        for k in range(rng.randint(1, 3)):
            pads += point_pad("T%d_%d" % (i, k), net, round(rng.uniform(0, 30), 2), round(rng.uniform(0, 30), 2))
    if quiet:
        for k in range(rng.randint(1, 3)):
            pads += point_pad("G%d" % k, "GND", round(rng.uniform(0, 30), 2), round(rng.uniform(0, 30), 2))
    for k in range(rng.randint(0, 6)):
        pads += point_pad("Q%da" % k, "X%d" % k, round(rng.uniform(0, 30), 2), round(rng.uniform(0, 30), 2))
        pads += point_pad("Q%db" % k, "X%d" % k, round(rng.uniform(0, 30), 2), round(rng.uniform(0, 30), 2))
    netclasses = {"N2": SimpleNamespace(tuning_profile="z50")} if rng.random() < 0.5 else {}
    partners = {"N0": "N1", "N1": "N0"} if rng.random() < 0.5 else {}
    return input_of(pads, {"U1": u1}, quiet={"GND"} if quiet else frozenset(), partners=partners, netclasses=netclasses)[0]


@pytest.mark.parametrize("seed", range(24))
def test_the_native_core_is_the_twin_on_random_boards(seed):
    inp = random_board(seed)
    if inp is None:
        pytest.skip("no net may move")
    s = settings(pins_anneal_moves=150, pins_seeds=2, pins_rotations=(0.0, 90.0, 135.0, 270.0), pins_faces=True,
                 score_crossing_plane=0.5)
    native, python = both(inp, ("U1",), s)
    assert native == python


@needs_kicad
def test_the_native_core_is_the_twin_on_the_reference_board():
    import importlib.util
    from pathlib import Path
    bench = Path(__file__).resolve().parents[1] / "fixtures" / "pinmap_bench.py"
    spec = importlib.util.spec_from_file_location("pinmap_bench", bench)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    case = mod.cases()[0]
    native, python = both(mod.input_of(case), tuple(case["parts"]), settings(pins_seeds=1, pins_anneal_moves=100,
                                                                            pins_faces=True))
    assert native == python and native[2]
