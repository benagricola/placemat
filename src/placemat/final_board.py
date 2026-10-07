"""Authoritative design and escape checks on a routed PCB.

The placement measures remain useful diagnostics. A final judgement replaces
only the checks and escape evidence whose copper the router could change.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace

from . import checks
from .occupancy import Occupancy


@dataclass(frozen=True)
class Judgement:
    verdicts: list
    outcomes: list
    findings: list
    measures: dict

    def evidence(self) -> dict:
        return {'critical_checks': self.measures['critical_checks'],
                'critical_unknown': list(self.measures['critical_unknown']),
                'final_findings': dict(self.measures['findings'])}


def judge(board, plan, pcb, measures) -> Judgement:
    """Read and judge `pcb`; a failed read/check propagates, never certifies.

    Fixed-placement and declared-copper findings survive: routing does not
    release their placement obligations. Escape and electrical evidence is
    recomputed from the final copper, with the same acceptance/settings rules.
    """
    from .settings import bind
    with bind(board.settings):
        return _judge(board, plan, pcb, measures)


def _judge(board, plan, pcb, measures) -> Judgement:
    from .kicad.read import read_board
    geometry = read_board(pcb)
    actual = {fp.ref: fp.fields for fp in geometry.footprints}
    intents = {fp.ref: {k: v for k, v in fp.fields.items() if k.startswith('Pm.')}
               for fp in plan.geometry.footprints
               if fp.ref not in plan.occupancy.pending and fp.ref in plan.occupancy.items}
    # Judge the source obligations on final copper even if the writer changed
    # a captured property. Keep that provenance failure separately below.
    geometry = replace(geometry,
                       footprints=tuple(replace(fp, fields={**fp.fields, **intents.get(fp.ref, {})})
                                        for fp in geometry.footprints),
                       _by_ref={}, _by_inst={})
    kwargs = checks.kwargs_from(board.settings)
    verdicts, outcomes = checks.judge(checks.run_checks(geometry, **kwargs), plan.acceptances)
    findings = checks.findings_of(outcomes) + checks.keep_out_findings(geometry, kwargs['keep_out_mm'])
    occ = Occupancy(geometry, board.edge_margin, board_shape=plan.occupancy.board_shape,
                    board_cutouts=plan.occupancy.board_cutouts, settings=board.settings,
                    component_spacing=board.component_spacing, rules=board._rules)
    occ.quiet_nets = plan.occupancy.quiet_nets
    occ.plane_nets = plan.occupancy.plane_nets
    occ.pending = set(plan.occupancy.pending)
    final = copy.copy(plan)
    final.findings = []
    found = board._report_escapes(occ, final, final=True)
    findings += final.findings
    m = dict(measures)
    m['findings'] = dict(measures.get('findings') or {})
    m['findings'].update({kind: len(records) for kind, records in found.items()})
    m['findings']['escape_lane'] = board._declared_lanes_blocked(occ, final)
    # Critical check verdicts are separate from the escape/placement findings;
    # accepted verdicts have no severity and are not counted twice.
    m['critical_checks'] = sum(v.severity == 'critical' for v in verdicts)
    unknown = [{'check': v.check, 'subject': v.subject, 'reason': 'not judged'} for v in verdicts
               if v.ok is None and not v.accepted and checks.CHECK_SEVERITY.get(v.check) == 'critical']
    for fp in plan.geometry.footprints:
        if fp.ref in plan.occupancy.pending or fp.ref not in plan.occupancy.items:
            continue
        for key, value in fp.fields.items():
            if key.startswith('Pm.') and actual.get(fp.ref, {}).get(key) != value:
                unknown.append({'check': 'captured-intent', 'subject': fp.ref, 'field': key,
                                'expected': value, 'actual': actual.get(fp.ref, {}).get(key)})
    m['critical_unknown'] = unknown
    return Judgement(verdicts, outcomes, findings, m)
