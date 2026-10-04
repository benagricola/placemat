"""A resolve's output does not depend on the interpreter's hash seed: the same board gives the same preview JSON
(findings in the same order) under any PYTHONHASHSEED."""
import os
import subprocess
import sys
from pathlib import Path

from placemat.ratsnest import Anchor, Ratsnest

ROOT = Path(__file__).resolve().parents[1]


def _preview(seed: int) -> str:
    env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]))
    done = subprocess.run([sys.executable, "-m", "tests.hash_seed_preview"], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return done.stdout


def test_the_preview_json_is_the_same_under_different_hash_seeds():
    docs = {seed: _preview(seed) for seed in (1, 3, 4, 7)}
    assert '"escape_crossed"' in docs[1]
    assert len(set(docs.values())) == 1


def _crossings(order):
    """Airwires of three nets from one part's pins, the middle net crossed by both others, nets set in `order`."""
    pins = {"NA": [Anchor("U", "3", 0.0, 0.0), Anchor("T1", "1", -5.0, 2.0)],
            "NB": [Anchor("U", "2", 0.0, -0.5), Anchor("T2", "1", -5.0, 3.5)],
            "NC": [Anchor("U", "4", 0.0, 0.5), Anchor("T3", "1", -5.0, -2.5)]}
    rn = Ratsnest()
    for net in order:
        rn.set_net(net, pins[net])
    return [(n, e.net, f.net) for n, e, f in rn.crossed_pair_list(depth=5.0)]


def test_the_crossed_escapes_do_not_depend_on_the_order_the_nets_were_set_in():
    got = {order: _crossings(order) for order in (("NA", "NB", "NC"), ("NC", "NB", "NA"), ("NB", "NC", "NA"), ("NA", "NC", "NB"))}
    assert len(got[("NA", "NB", "NC")]) >= 2
    assert len({tuple(v) for v in got.values()}) == 1
