"""`explore.rank_remapped` (`--rank-remapped`): every variant an explore keeps gets the pin map study, and the variants
are ranked, and the best chosen, on the run score less what its best remap saves (its weighted crossings removed, at
`score.crossing` each). Both scores are kept. With `--route-best` a variant is routed on its board with the remap made
on its pads (kicad.remap). A board with no `Pm.PinPool` part explores as it would without the setting."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from placemat import channel, checkpoint, explore
from placemat.layout import Board
from placemat.values import Location, Part
from tests import explore_boards as eb
from tests.fixtures import board_geometry, footprint
from tests.pinmap_boards import quad_footprint, settings

NETS = ["A", "B", "C", "D", "E", "F"]
FOCUS = frozenset("r%d" % k for k in range(1, 7))
# seeds of PoolBoard: 29 has the best run score, 28 the best after its remap (one weighted crossing, 4 mm, removed)
PLAIN_BEST, REMAPPED_BEST = 29, 28
SEEDS = [0, REMAPPED_BEST, PLAIN_BEST]


class PoolBoard:
    """A part whose six east pins are a pin pool, and six searched resistors on its nets in the reverse order.
    Picklable: explore workers are spawned."""

    def __init__(self, rank: bool = False):
        self.rank = rank

    def __call__(self):
        fps = [quad_footprint("U1", 10, 10, {"E": NETS}, {"Pm.PinPool": "1-6"})]
        for i, net in enumerate(reversed(NETS)):
            fps.append(footprint("R%d" % (i + 1), 60, 60 + 2 * i, w=2, h=1, inst="r%d" % (i + 1), nets=(net, "G%d" % i)))
        b = Board(board_geometry(fps, width=30, height=30), edge_margin=1.0,
                  settings=settings(pins_rotations=(0.0,), explore_rank_remapped=self.rank))
        b.place(Part("u1"), at=Location(10, 10))
        for k in sorted(FOCUS):
            b.place(Part(k))
        return b


@pytest.fixture
def events(monkeypatch, tmp_path):
    from placemat import project
    sent = []

    class Rep:
        def send(self, ev):
            sent.append(ev)
    monkeypatch.setattr(channel, "current", lambda: Rep())
    monkeypatch.setattr(project, "find_board", lambda p: SimpleNamespace(board_dir=tmp_path))
    return sent


def _search(tmp_path, make, **kw):
    return explore.search(make, tmp_path / "Board_layout.py", seconds=120, jobs=1, seeds=SEEDS, **kw)


def test_the_seeds_score_as_the_tests_say():
    """The premise: seed 28 is worse than 29 by run score, better after its remap."""
    got = {}
    for seed in SEEDS[1:]:
        b = PoolBoard(rank=True)()
        p = b.resolve(explore=explore.Explore(seed, FOCUS))
        total = explore.score(b, p)
        got[seed] = (total, explore.ranked(b, p, total))
    (plain28, r28), (plain29, r29) = got[REMAPPED_BEST], got[PLAIN_BEST]
    assert plain28 > plain29 and r28["score_remapped"] < r29["score_remapped"]
    assert r28["remap"]["crossings"] == 1.0 and r28["remap"]["saving"] == 4.0          # score.crossing's 4 mm
    (g,) = r28["remap"]["groups"]
    assert g["refs"] == ["U1"] and g["map"] and g["best"] < g["present"]


def test_without_the_setting_the_run_score_ranks_and_nothing_is_studied_per_variant(tmp_path, events):
    report, _ = _search(tmp_path, PoolBoard())
    assert report["best_seed"] == PLAIN_BEST and "best_remapped" not in report
    record = json.loads(open(report["record"]).read())
    assert all("score_remapped" not in v and "remap" not in v for v in record["variants"])
    assert "best_remapped" not in record


def test_with_the_setting_a_variant_better_after_its_remap_wins(tmp_path, events):
    report, _ = _search(tmp_path, PoolBoard(rank=True))
    assert report["best_seed"] == REMAPPED_BEST
    assert report["best_remapped"] == pytest.approx(report["best"] - 4.0, abs=1e-3)
    assert report["baseline_remapped"] <= report["baseline"]
    lines = explore.report_lines(report)
    assert any(l.startswith("  ranked after each variant's pin remap: ") and l.endswith("the best's remap saving 4.0 mm")
               for l in lines)
    record = json.loads(open(report["record"]).read())
    by_seed = {v["seed"]: v for v in record["variants"]}
    assert set(by_seed) == set(SEEDS)
    best = by_seed[REMAPPED_BEST]
    assert best["score_remapped"] == pytest.approx(best["score"] - 4.0, abs=1e-3)
    assert best["remap"]["saving"] == 4.0 and best["remap"]["groups"][0]["map"] and best["remap"]["seconds"] >= 0
    assert record["best_remapped"] == report["best_remapped"]
    assert [c["seed"] for c in record["curve"] if c["best"]][-1] == REMAPPED_BEST
    assert all("score_remapped" in c for c in record["curve"])
    sent = [e for e in events if e["ev"] == "variant"]
    assert {e["seed"]: e["score_remapped"] for e in sent}[REMAPPED_BEST] == best["score_remapped"]
    (done,) = [e for e in events if e["ev"] == "explore_done"]
    assert done["best_remapped"] == report["best_remapped"]
    maps = {m["seed"]: m for m in report["pin_maps"]}
    assert report["pin_maps"][0]["seed"] == REMAPPED_BEST and "score_remapped" in maps[REMAPPED_BEST]


def test_accept_writes_the_variants_placement_and_says_the_remap_is_the_users_to_make(tmp_path, events):
    from placemat import lock
    script = tmp_path / "Board_layout.py"
    report, entries = _search(tmp_path, PoolBoard(rank=True), accept=True)
    assert report["accepted"] and lock.path_for(script).exists()
    plan = PoolBoard()().resolve(explore=explore.Explore(REMAPPED_BEST, FOCUS))
    held = PoolBoard()().resolve(lock=lock.read(lock.path_for(script)))
    for key in FOCUS:
        assert held.placement(key).location.distance(plan.placement(key).location) < 1e-6, key
    assert explore.report_lines(report)[-1] == \
        "accepted: written to the lock; its pin remap is not, make it in the capture (the pin map lines above)"


def test_a_board_with_no_pin_pool_explores_as_without_the_setting(tmp_path, events):
    seeds = [0] + eb.improving(3)
    off, _ = explore.search(eb.Settled(), tmp_path / "A_layout.py", seconds=120, jobs=1, seeds=seeds)
    on, _ = explore.search(eb.Settled(explore_rank_remapped=True), tmp_path / "B_layout.py", seconds=120, jobs=1,
                           seeds=seeds)
    assert (on["best_seed"], on["best"], on["baseline"]) == (off["best_seed"], off["best"], off["baseline"])
    assert "best_remapped" not in on and on["moves"] == off["moves"]
    assert explore.report_lines(on)[1:] == explore.report_lines(off)[1:]         # the first line has the time it took
    record = json.loads(open(on["record"]).read())
    assert all("score_remapped" not in v for v in record["variants"])
    assert all("score_remapped" not in c for c in record["curve"])


def test_the_routing_worker_makes_the_remap_on_the_board_it_routes(tmp_path, events):
    report, _ = _search(tmp_path, PoolBoard(rank=True), route_best=True, variants_dir=tmp_path / "explore",
                        router=RemapRouter(tmp_path / "routes.log"))
    log = [json.loads(l) for l in (tmp_path / "routes.log").read_text().splitlines()]
    remaps = [r for r in log if r.get("kind") == "remap"]
    assert remaps and all(r["groups"][0]["refs"] == ["U1"] for r in remaps)
    routed = {r["seed"]: r for r in report["routes"]}
    assert routed[REMAPPED_BEST]["remapped"]["saving"] == 4.0 and routed[REMAPPED_BEST]["remapped"]["pads"] >= 2
    assert routed[REMAPPED_BEST]["score_remapped"] == round(report["best_remapped"], 1)
    line = explore.route_line(routed[REMAPPED_BEST])
    assert line.startswith("  route, seed %d at %.1f mm, %.1f mm after its pin remap: " % (
        REMAPPED_BEST, routed[REMAPPED_BEST]["score"], routed[REMAPPED_BEST]["score_remapped"]))
    assert line.endswith("; routed with its pin remap made on its pads")


class RemapRouter(eb.StandInRouter):
    """The stand-in router, with the remap logged as a line of its own (`kind` "remap") and counted as kicad.remap's."""

    def remap(self, pcb, groups):
        from pathlib import Path
        with open(self.log, "a") as f:
            f.write(json.dumps({"kind": "remap", "seed": int(Path(pcb).parent.name.split("-")[1]), "groups": groups}) + "\n")
        return {"pads": sum(len(g["map"]) for g in groups), "tracks": 0, "deleted": 0, "turned": [], "not_turned": []}


def test_the_checkpoint_ranks_by_the_remapped_score_and_a_resume_keeps_it(tmp_path):
    ck = checkpoint.Checkpoint(tmp_path, {"script": "s", "lock": "l"}, ["r1"])
    ck.start(100.0, {}, 10.0, None, rank=96.0)
    payload = {"entries": [], "orders": {}}
    ck.variant(1, 98.0, {"m": 1}, 1.0, payload, rank=98.0)       # better by run score, worse ranked
    ck.variant(2, 99.0, {"m": 2}, 2.0, payload, rank=91.0)
    ck.close()
    assert checkpoint.read_best(tmp_path)["seed"] == 2 and checkpoint.read_best(tmp_path)["score_remapped"] == 91.0
    prior = checkpoint.Checkpoint(tmp_path, {"script": "s", "lock": "l"}, ["r1"]).load()
    assert prior.best_seed == 2 and prior.ranks == {0: 96.0, 1: 98.0, 2: 91.0}


def test_the_cli_flag_sets_the_setting_and_goes_with_explore():
    from placemat import cli
    args = cli.parser().parse_args(["run", "Board_layout.py", "--explore", "60", "--rank-remapped"])
    assert cli.overrides_from(args)["explore_rank_remapped"] is True
    assert "explore_rank_remapped" not in cli.overrides_from(cli.parser().parse_args(["run", "Board_layout.py"]))
    with pytest.raises(SystemExit, match="--rank-remapped"):
        cli._explore_options(cli.parser().parse_args(["run", "Board_layout.py", "--rank-remapped"]))
