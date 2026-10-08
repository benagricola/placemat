"""Complete candidate/setup timings, without adopting the new search.

Run sequentially under the reference-board lock. JSON lines distinguish score
calls from legality and setup. Resolve comparisons use fresh boards under the temporary measurement flag.
The clique default remains unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import importlib
import json
import pathlib
import shutil
import statistics
import subprocess
import time


def candidates(original, count=2000):
    from placemat.values import Location
    rotations = tuple((original.rotation + turn) % 360 for turn in (0, 90, 180, 270))
    points = [(x / 5, y / 5, turn) for x in range(-5, 6) for y in range(-5, 6)
              for turn in range(4)]
    return rotations, [(replace(original, location=Location(original.location.x + x, original.location.y + y),
                               rotation=rotations[turn]), turn)
                       for x, y, turn in (points[i % len(points)] for i in range(count))]


def timed(call, rows, repeats):
    """Median complete call time, including the Python/native boundary."""
    for row in rows[:min(8, len(rows))]:
        call(row)
    samples = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        for row in rows:
            call(row)
        samples.append((time.perf_counter_ns() - start) / len(rows))
    return statistics.median(samples) / 1000


def identity(paths):
    """Hash exact runtime/input bytes; git commit alone misses local edits."""
    return {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if p.is_file()}


def git_identity(path):
    def git(*args):
        result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    return {'root': git('rev-parse', '--show-toplevel'), 'commit': git('rev-parse', 'HEAD')}


def runtime_identity(paths, native_path):
    from placemat import geometry
    from placemat.kicad.route import router_dir
    from placemat.settings import Settings
    root = pathlib.Path(__file__).resolve().parents[1]
    krt = pathlib.Path(router_dir(Settings()))
    pcb = shutil.which('pcb')
    kicad = shutil.which('kicad-cli')
    binaries = [native_path] + [pathlib.Path(p).resolve() for p in (pcb, kicad) if p]
    router_binaries = [p for pattern in ('rust_router/target/release/*.so', '**/pcbnew*.so')
                       for p in krt.glob(pattern) if p.is_file()]
    binaries.extend(router_binaries)
    sources = list((root / 'src' / 'placemat').rglob('*.py')) + list((root / 'native' / 'src').rglob('*.rs'))
    excluded = {'tests', '__pycache__', '.venv', 'venv', 'target', 'build'}
    sources.extend(p for p in krt.rglob('*.py') if not excluded.intersection(p.relative_to(krt).parts))
    sources.extend([root / 'native' / 'Cargo.toml', root / 'native' / 'Cargo.lock', pathlib.Path(__file__),
                    root / 'native' / 'build.rs', root / 'pyproject.toml', root / 'fixtures' / 'bench.py'])
    def version(command):
        if command is None:
            return None
        result = subprocess.run([command, '--version'], capture_output=True, text=True, timeout=10)
        return {'exit': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}
    return {'placemat': git_identity(root), 'krt': git_identity(krt),
            'pcb': git_identity(pathlib.Path(pcb).resolve().parent) if pcb else None,
            'binaries': identity(binaries), 'sources': identity(sources), 'inputs': identity(paths),
            'krt_dir': str(krt), 'pcb_command': pcb, 'kicad_command': kicad,
            'versions': {'native': asdict(geometry.native_status()), 'pcb': version(pcb), 'kicad_cli': version(kicad)}}


def measure(board, plan, step, *, count, repeats):
    from placemat.board_geometry import Footprint, members_of
    from placemat.layout import Scorer
    from placemat.score_search import MSTScorer
    occ, item = plan.occupancy, plan._items[step.item]
    original = occ._geometry(item).reference
    owners = {fp.ref for fp in members_of(item)}
    lifted = occ._lift_owners(owners)
    if lifted & occ.pending:
        raise ValueError('timing requires the complete item to be active')
    rotations, rows = candidates(original, count)
    start = time.perf_counter_ns()
    occ.lift(lifted)
    lift_us = (time.perf_counter_ns() - start) / 1000
    try:
        start = time.perf_counter_ns()
        targets = board._targets(item, occ, set(occ.items) - occ.pending)
        old = Scorer(board.settings, item, occ, targets, prune=False)
        old_native = old.native(rotations, original.face)
        old_setup_us = (time.perf_counter_ns() - start) / 1000
        start = time.perf_counter_ns()
        common = MSTScorer(board, occ, item, plan=plan)
        delta = common.delta
        full = common.native(rotations, original.face)
        refusal = common.refusals.get((tuple(rotations), original.face))
        setup_us = (time.perf_counter_ns() - start) / 1000
        start = time.perf_counter_ns()
        legal = [row for row in rows if occ.legal(item, row[0], board.geometry.default_clearance) is None]
        legality_us = (time.perf_counter_ns() - start) / count / 1000
        if not legal:
            return {'item': step.item, 'kind': 'part' if isinstance(item, Footprint) else 'cell',
                    'legal': 0, 'attempted': count, 'refusal': 'no legal nudge candidates'}
        old_call = (lambda row: old_native.evaluate(row[0].location.x, row[0].location.y, row[1])) \
            if old_native is not None else (lambda row: old(row[0]))
        new_call = (lambda row: full.evaluate(row[0].location.x, row[0].location.y, row[1])) \
            if full is not None else (lambda row: common(row[0]))
        # First complete evaluation after preparation, before any warm-up.
        def first(call):
            start = time.perf_counter_ns()
            call(legal[0])
            return (time.perf_counter_ns() - start) / 1000
        old_first_us, delta_first_us = first(old_call), first(new_call)
        old_us, delta_us = timed(old_call, legal, repeats), timed(new_call, legal, repeats)
        kernel = delta.native(rotations, original.face)
        six_us = timed(lambda row: kernel.terms(row[0].location.x, row[0].location.y, row[1]), legal, repeats) \
            if kernel is not None else None
        return {'item': step.item, 'kind': 'part' if isinstance(item, Footprint) else 'cell',
                'attempted': count, 'legal': len(legal), 'lift_us': lift_us,
                'old_setup_us': old_setup_us, 'delta_setup_us': setup_us,
                'old_score_us': old_us, 'delta_score_us': delta_us,
                'old_first_evaluation_us': old_first_us, 'delta_first_evaluation_us': delta_first_us,
                'first_evaluation_scope': 'first scoring call after preparation; shared libraries and process may already be warm',
                'warm_evaluation_scope': 'eight warm-up calls then median complete corpus pass',
                'old_python_share': int(old_native is None), 'delta_python_share': int(full is None),
                'fallback_reason': refusal, 'python_legality_us_per_attempt': legality_us,
                'legal_per_second_python_legality': len(legal) / (count * legality_us + len(legal) * delta_us) * 1e6,
                'production_sweep_timing': 'actual resolve records separately',
                'six_term_us': six_us,
                'escape_increment_estimate_us': None if six_us is None else delta_us - six_us,
                'split_status': 'six-term combined; independent per-term instrumentation pending'}
    finally:
        start = time.perf_counter_ns()
        occ.unlift(lifted)
        restore_us = (time.perf_counter_ns() - start) / 1000
        # Emitted separately even if evaluation fails; restoration is mandatory.
        print(json.dumps({'type': 'restore', 'item': step.item, 'restore_us': restore_us,
                          'commit_timing': 'actual adoption commits recorded in resolve; this is snapshot unlift'}), flush=True)


def resolve_measure(board):
    """Time actual setup, production native passes and adoption commits.

    Wrappers observe existing calls and restore their class methods even on
    failure. Resolve wall time includes the observer overhead in both modes.
    """
    from placemat.layout import Scorer
    from placemat.score_search import MSTScorer
    from placemat.occupancy import Occupancy, NativeSweeper
    stats = {'commit_calls': 0, 'commit_us': 0.0, 'commit_events': [],
             'python_score_calls': {}, 'python_score_us': {}, 'native_passes': 0,
             'native_attempted': 0, 'native_legal': 0, 'native_sweep_us': 0.0,
             'native_passes_by_scorer': {},
             'scorer_setup_us': 0.0, 'scorer_setup_calls': 0,
             'native_setup_us': 0.0, 'native_setup_calls': 0, 'native_refusals': 0,
             'native_refusal_reasons': {}}
    originals = [(Occupancy, 'commit', Occupancy.commit), (NativeSweeper, 'run', NativeSweeper.run),
                 (type(board), '_scorer', type(board)._scorer),
                 (Scorer, 'native', Scorer.native), (MSTScorer, 'native', MSTScorer.native),
                 (Scorer, '__call__', Scorer.__call__), (MSTScorer, '__call__', MSTScorer.__call__)]
    def commit(self, *args, **kwargs):
        start = time.perf_counter_ns()
        try:
            return originals[0][2](self, *args, **kwargs)
        finally:
            stats['commit_calls'] += 1
            elapsed = (time.perf_counter_ns() - start) / 1000
            stats['commit_us'] += elapsed
            item = args[0] if args else kwargs.get('item')
            key = getattr(item, 'name', None) or getattr(item, 'ref', None)
            stats['commit_events'].append({'item': key if key is not None else str(item), 'us': elapsed})
    def run(self, triples, *args, **kwargs):
        start = time.perf_counter_ns()
        result = originals[1][2](self, triples, *args, **kwargs)
        stats['native_passes'] += 1
        stats['native_attempted'] += len(triples)
        stats['native_legal'] += len(result[0])
        elapsed = (time.perf_counter_ns() - start) / 1000
        stats['native_sweep_us'] += elapsed
        scoring = args[1] if len(args) > 1 else kwargs.get('scoring')
        kind = type(scoring).__name__ if scoring is not None else 'legality_only'
        row = stats['native_passes_by_scorer'].setdefault(kind, {'calls': 0, 'attempted': 0, 'legal': 0, 'us': 0.0})
        row['calls'] += 1
        row['attempted'] += len(triples)
        row['legal'] += len(result[0])
        row['us'] += elapsed
        return result
    def scorer(self, *args, **kwargs):
        start = time.perf_counter_ns()
        result = originals[2][2](self, *args, **kwargs)
        stats['scorer_setup_calls'] += 1
        stats['scorer_setup_us'] += (time.perf_counter_ns() - start) / 1000
        return result
    def native_wrapper(original):
        def native(self, *args, **kwargs):
            start = time.perf_counter_ns()
            result = original(self, *args, **kwargs)
            stats['native_setup_calls'] += 1
            stats['native_refusals'] += int(result is None)
            if result is None:
                reasons = getattr(self, 'refusals', {})
                reason = next(reversed(reasons.values()), 'clique native unavailable')
                counts = stats['native_refusal_reasons']
                counts[reason] = counts.get(reason, 0) + 1
            stats['native_setup_us'] += (time.perf_counter_ns() - start) / 1000
            return result
        return native
    def python_wrapper(original):
        def call(self, *args, **kwargs):
            start = time.perf_counter_ns()
            try:
                return original(self, *args, **kwargs)
            finally:
                kind = type(self).__name__
                counts, times = stats['python_score_calls'], stats['python_score_us']
                counts[kind] = counts.get(kind, 0) + 1
                times[kind] = times.get(kind, 0) + (time.perf_counter_ns() - start) / 1000
        return call
    replacements = [commit, run, scorer, native_wrapper(Scorer.native), native_wrapper(MSTScorer.native),
                    python_wrapper(Scorer.__call__), python_wrapper(MSTScorer.__call__)]
    start = time.perf_counter()
    try:
        for (cls, name, _), replacement in zip(originals, replacements):
            setattr(cls, name, replacement)
        plan = board.resolve()
    finally:
        for cls, name, original in originals:
            setattr(cls, name, original)
    stats['seconds'] = time.perf_counter() - start
    stats['native_pass_legal_per_second'] = (stats['native_legal'] * 1e6 / stats['native_sweep_us']) \
        if stats['native_sweep_us'] else None
    python_common = stats['python_score_calls'].get('MSTScorer', 0)
    native_common = stats['native_passes_by_scorer'].get('NativeDeltaScoring', {}).get('legal', 0)
    stats['common_python_evaluation_share'] = python_common / (python_common + native_common) \
        if python_common + native_common else None
    stats['evaluation_share_scope'] = 'common objective evaluation calls; repeated giveway candidates count again; clique pruning is not inferred from legal counts'
    stats['throughput_scope'] = 'native pass only; legality_only excludes later Python scoring; giveway phases can repeat candidates'
    return plan, stats


def run_fixture(label, make, args, mode):
    from placemat import score
    board = make()
    board.settings = replace(board.settings, place_search_wire=mode)
    start = time.perf_counter()
    plain = board.resolve()
    print(json.dumps({'type': 'resolve', 'fixture': label, 'search': mode,
                      'instrumented': False, 'seconds': time.perf_counter() - start,
                      'score': score.total(score.plan_measures(board, plain), board.settings),
                      'effective_settings': asdict(board.settings)}), flush=True)
    board = make()
    board.settings = replace(board.settings, place_search_wire=mode)
    plan, production = resolve_measure(board)
    print(json.dumps({'type': 'resolve', 'fixture': label, 'search': board.settings.place_search_wire,
                      'instrumented': True, **production,
                      'score': score.total(score.plan_measures(board, plan), board.settings),
                      'effective_settings': asdict(board.settings)}), flush=True)
    rows = []
    selected = [s for s in plan.steps if s.placement is not None and s.item in plan._items]
    if args.items:
        selected = selected[:args.items]
    for step in selected:
        print(json.dumps({'type': 'item_start', 'fixture': label, 'item': step.item}), flush=True)
        row = measure(board, plan, step, count=args.candidates, repeats=args.repeats)
        row['measurement_board_search'] = mode
        rows.append(row)
        print(json.dumps({'type': 'item', 'fixture': label, **row}, sort_keys=True), flush=True)
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('names', nargs='*', help='module labels; defaults to all modules')
    parser.add_argument('--items', type=int, default=0, help='limit per fixture, zero means all')
    parser.add_argument('--candidates', type=int, default=2000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--search', choices=('clique', 'mst', 'both'), default='both')
    parser.add_argument('--core', action='store_true', help='also time actual generated-core search')
    parser.add_argument('--core-fixed', action='store_true', help='also measure written-core fixed poses separately')
    args = parser.parse_args(argv)
    if args.items < 0 or args.candidates < 1 or args.repeats < 1:
        parser.error('items must be nonnegative; candidates and repeats must be positive')
    from fixtures import bench
    paths = [p for p in bench.boards() if not args.names or bench._name(p) in args.names]
    unknown = set(args.names) - {bench._name(p) for p in paths}
    if unknown:
        parser.error('unknown modules: ' + ', '.join(sorted(unknown)))
    from fixtures.reference.lock import realboard
    rows = []
    with realboard():
        from placemat import geometry
        from placemat.kicad.read import read_board
        if geometry._native is None or not hasattr(geometry._native.NativeScoring, 'evaluate'):
            parser.error('build native timing entry point before running')
        native_path = pathlib.Path(importlib.import_module('placemat_native.placemat_native').__file__)
        inputs = [f for p in paths for f in p.parent.glob('*') if f.is_file()]
        if args.core or args.core_fixed:
            inputs.extend((bench.BOARD_FIXTURE / 'layout').glob('*'))
        if args.core:
            inputs.extend((bench.BOARD_FIXTURE / 'generated').glob('*'))
        before = runtime_identity(inputs, native_path)
        print(json.dumps({'type': 'provenance_start', 'identity': before,
                          'candidates': args.candidates, 'repeats': args.repeats,
                          'timing': 'complete one-boundary calls; old inspection validates inputs and borrows mirrors'}), flush=True)
        for path in paths:
            g = read_board(path)
            for mode in ('clique', 'mst') if args.search == 'both' else (args.search,):
                make = bench.ModuleBoard(g, {}, bench._planes(g), bench._size(g, False))
                rows.extend(run_fixture(bench._name(path), make, args, mode))
        if args.core or args.core_fixed:
            from placemat.layout import Board
            from placemat.occupancy import Occupancy
            from placemat.values import Cell, Part
            written = read_board(bench.BOARD_FIXTURE / 'layout' / 'layout.kicad_pcb')
            def core_make(g, fixed):
                def make():
                    board = Board(g, keep_going=True)
                    board.outline(written.board_polygon[0], holes=written.board_polygon[1:])
                    for name, cell in sorted(g.cells.items()):
                        if cell.members:
                            if fixed:
                                pose = Occupancy(g)._geometry(cell).reference
                                board.place(Cell(name), at=pose.location, rotation=pose.rotation, face=pose.face)
                            else:
                                board.place(Cell(name))
                    for fp in sorted(g.footprints, key=lambda f: f.inst):
                        if fp.cell is None:
                            if fixed:
                                board.place(Part(fp.inst), at=fp.location, rotation=fp.rotation, face=fp.face)
                            else:
                                board.place(Part(fp.inst))
                    return board
                return make
            cases = []
            if args.core:
                generated = read_board(bench.BOARD_FIXTURE / 'generated' / 'layout.kicad_pcb')
                cases.append(('generated-core-search', core_make(generated, False)))
            if args.core_fixed:
                cases.append(('written-core-fixed-poses', core_make(written, True)))
            for label, make in cases:
                for mode in ('clique', 'mst') if args.search == 'both' else (args.search,):
                    rows.extend(run_fixture(label, make, args, mode))
        after = runtime_identity(inputs, native_path)
        print(json.dumps({'type': 'provenance_end', 'identity': after, 'unchanged': before == after}), flush=True)
        if before != after:
            raise RuntimeError('runtime or input bytes changed during timing; results are uncertified')
    for mode in ('clique', 'mst'):
        for kind in ('part', 'cell'):
            found = [r for r in rows if r['kind'] == kind and r['legal'] and r['measurement_board_search'] == mode]
            if found:
                print(json.dumps({'type': 'median', 'kind': kind, 'measurement_board_search': mode, 'items': len(found),
                                  'old_score_us': statistics.median(r['old_score_us'] for r in found),
                                  'delta_score_us': statistics.median(r['delta_score_us'] for r in found),
                                  'fallbacks': dict(Counter(r['fallback_reason'] for r in found if r['fallback_reason']))}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
