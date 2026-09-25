"""Differential pairs, named as the router pairs them.

`pair_key` is a port of KiCadRoutingTools' `net_queries.extract_diff_pair_base`
(the same conventions, in the same order, for the same reasons: its comments
cite the router's issues), so placemat and the router never disagree about
which nets form a pair. Two nets pair when their keys share a base and a
style and differ in polarity.
"""
from __future__ import annotations

import re


def pair_key(net_name: str):
    """(base, is_positive, style) for a net named as one half of a pair, else
    None. `style` is the suffix convention; halves pair only within one."""
    if not net_name:
        return None
    # KiCad auto-names a netless pin's net 'Net-(<ref>-<pin>)'; peel the wrapper
    is_auto_name = net_name.startswith('Net-(') and net_name.endswith(')')
    if is_auto_name:
        net_name = net_name[5:-1]
    # an auto-name's pin path encodes the chip's signal path: use its leaf
    if is_auto_name:
        path = net_name.replace('{slash}', '/')
        if '/' in path:
            net_name = path.rsplit('/', 1)[-1]

    # USB data lines: DPLUS / DMINUS, with no letter before the D
    m = re.match(r'^(.*?)D(PLUS|MINUS)$', net_name, re.IGNORECASE)
    if m and (not m.group(1) or not m.group(1)[-1].isalpha()):
        return (m.group(1) + 'D', m.group(2).upper() == 'PLUS', 'DP')
    # USB data lines: DP / DM / DN
    m = re.match(r'^(.*?)D([PMN])$', net_name, re.IGNORECASE)
    if m and (not m.group(1) or not m.group(1)[-1].isalpha()):
        return (m.group(1) + 'D', m.group(2).upper() == 'P', 'DP')
    # indexed: name_P0 / name_N0, each index with its own twin
    m = re.match(r'^(.+)_([PN])(\d+)$', net_name)
    if m:
        return (m.group(1) + '_X' + m.group(3), m.group(2) == 'P', '_P')
    # _P / _N
    if net_name.endswith('_P'):
        return (net_name[:-2], True, '_P')
    if net_name.endswith('_N'):
        return (net_name[:-2], False, '_P')
    # P / N after a digit, an underscore or an uppercase letter
    if net_name.endswith('P') and len(net_name) > 1:
        if net_name[-2] in '0123456789_' or net_name[-2].isupper():
            return (net_name[:-1], True, 'P')
    if net_name.endswith('N') and len(net_name) > 1:
        if net_name[-2] in '0123456789_' or net_name[-2].isupper():
            return (net_name[:-1], False, 'P')
    # + / -, but not a passive's terminal ('<ref>-+', '<ref>--')
    if net_name.endswith('+') and not net_name.endswith('-+'):
        return (net_name[:-1], True, '+')
    if net_name.endswith('-') and not net_name.endswith('--'):
        return (net_name[:-1], False, '+')
    # + / - followed by an underscore-led suffix (D+_L / D-_L)
    m = re.match(r'^(.+?)([+-])(_[A-Za-z0-9_]*)$', net_name)
    if m and m.group(1)[-1] not in '+-':
        return (m.group(1) + m.group(3), m.group(2) == '+', '+')
    # DDR true/complement, last so a mid-name _t_/_c_ never shadows the above
    m = re.match(r'^(.+)_([tc])_(.+)$', net_name, re.IGNORECASE)
    if m:
        return (m.group(1) + '_X_' + m.group(3), m.group(2).lower() == 't', '_t')
    m = re.match(r'^(.+)_([tc])([A-Za-z0-9])$', net_name, re.IGNORECASE)
    if m:
        return (m.group(1) + '_X' + m.group(3), m.group(2).lower() == 't', '_t')
    if net_name[-2:].lower() == '_t':
        return (net_name[:-2], True, '_t')
    if net_name[-2:].lower() == '_c':
        return (net_name[:-2], False, '_t')
    return None


def pairs_of(nets) -> dict:
    """{net: its partner} for every net of `nets` that has exactly one
    partner of the other polarity under the same base and style."""
    halves: dict = {}
    for net in nets:
        k = pair_key(net)
        if k is not None:
            halves.setdefault((k[0], k[2]), {}).setdefault(k[1], []).append(net)
    out = {}
    for sides in halves.values():
        pos, neg = sides.get(True, []), sides.get(False, [])
        if len(pos) == 1 and len(neg) == 1:
            out[pos[0]] = neg[0]
            out[neg[0]] = pos[0]
    return out
