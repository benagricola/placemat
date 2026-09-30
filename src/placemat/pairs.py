"""Differential pairs, named as the router pairs them.

`pair_key` is a port of KiCadRoutingTools' `net_queries.extract_diff_pair_base`
(the same conventions, in the same order, for the same reasons: its comments
cite the router's issues), so placemat and the router never disagree about
which nets form a pair. Two nets pair when their keys share a base and a
style and differ in polarity.

A `route.diff_pairs` entry "NET_A/NET_B" names a pair outright, whatever the
two are called (`explicit_pairs`). The router takes no such pair, so the
route step routes it under a suffix name (`pair_aliases`).
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


def selected(net: str, base: str, patterns) -> bool:
    """Whether a glob of `patterns` selects this pair half: matched against
    the net, its leaf (after the last '/'), the pair's base and the base's
    leaf, as the router's net_queries.matches_diff_pair_patterns does."""
    from fnmatch import fnmatch
    candidates = (net, net.rsplit('/', 1)[-1], base, base.rsplit('/', 1)[-1])
    return any(fnmatch(c, p) for p in patterns for c in candidates)


# The base of the suffix pair an explicit pair is routed under: <ALIAS><i>_P / _N.
ALIAS = "PMPAIR"


def _names_pair(entry: str) -> bool:
    """Whether a `route.diff_pairs` entry names a pair: one '/', with a net
    on each side and no glob character. A leading '/' is a hierarchical
    name's, so "/D_CK" stays a pattern."""
    a, slash, b = entry.partition("/")
    return bool(slash and a and b and "/" not in b and not any(c in entry for c in "*?["))


def explicit_pairs(entries) -> list:
    """The pairs `route.diff_pairs` names outright, "NET_A/NET_B", as
    (P net, N net) in order. A net in two of them, or twice in one, is a
    ValueError naming it."""
    out, seen = [], set()
    for entry in entries or ():
        if not _names_pair(str(entry)):
            continue
        a, _, b = str(entry).partition("/")
        for net in (a, b):
            if net in seen:
                raise ValueError("%s is named in more than one pair (%r)" % (net, entry))
            seen.add(net)
        out.append((a, b))
    return out


def globs(entries) -> tuple:
    """The entries of `route.diff_pairs` that are patterns, not named pairs."""
    return tuple(e for e in entries or () if not _names_pair(str(e)))


def pair_aliases(pairs, names) -> list:
    """(base, P net, N net) for each explicit pair: the base names the suffix
    pair <base>_P / <base>_N it is routed under, one that no net of `names`
    already is or that a pattern of the base would select."""
    def taken(base):
        for n in names:
            k = pair_key(n)
            if n in (base + "_P", base + "_N") or selected(n, k[0] if k else n, (base,)):
                return True
        return False
    out, i = [], 0
    for p, n in pairs:
        while taken("%s%d" % (ALIAS, i)):
            i += 1
        out.append(("%s%d" % (ALIAS, i), p, n))
        i += 1
    return out


def pairs_of(nets, patterns=("*",)) -> dict:
    """{net: its partner} for every net of `nets` that has exactly one
    partner of the other polarity under the same base and style, in a pair
    `patterns` selects (either half matching selects both), and for both
    nets of each pair `patterns` names outright ("NET_A/NET_B") when `nets`
    has the two. A named pair takes its nets from any suffix pair."""
    named = explicit_pairs(patterns)
    patterns = globs(patterns)
    halves: dict = {}
    for net in nets:
        k = pair_key(net)
        if k is not None:
            halves.setdefault((k[0], k[2]), {}).setdefault(k[1], []).append(net)
    out = {}
    for (base, _style), sides in halves.items():
        pos, neg = sides.get(True, []), sides.get(False, [])
        if len(pos) == 1 and len(neg) == 1 and \
                (selected(pos[0], base, patterns) or selected(neg[0], base, patterns)):
            out[pos[0]] = neg[0]
            out[neg[0]] = pos[0]
    present = set(nets)
    for p, n in named:
        if p in present and n in present:
            for net in (p, n):
                out.pop(out.pop(net, None), None)
            out[p], out[n] = n, p
    return out


def board_pairs(netclasses: dict) -> dict:
    """{net: its partner} from the board's own net classes: a class other
    than "Default" that sets diff_pair_width and diff_pair_gap groups its
    nets into pairs - exactly two nets pair whatever they are named; more
    than two pair within the class by pair_key, the same rule a suffix pair
    uses elsewhere. A board whose classes declare no pair class has none.

    A net class's diff_pair_width/gap are not reliably null for a class
    that was never meant as a pair (KiCad's own default netclass and an
    untouched one both report the project's default diff-pair figure, not
    None) - only the class name "Default" is excluded here, per the design
    this ports."""
    by_class: dict = {}
    for net, nc in netclasses.items():
        if nc.name == "Default" or nc.diff_pair_width is None or nc.diff_pair_gap is None:
            continue
        by_class.setdefault(nc.name, []).append(net)
    out = {}
    for nets in by_class.values():
        if len(nets) == 2:
            a, b = sorted(nets)
            out[a], out[b] = b, a
        elif len(nets) > 2:
            out.update(pairs_of(nets))
    return out


def board_pair_list(netclasses: dict) -> list:
    """[(p_net, n_net), ...] from board_pairs(), each pair once: P first
    when pair_key says which half is positive, else the alphabetically
    first net (a two-net class with no suffix meaning has no real P/N)."""
    d = board_pairs(netclasses)
    seen, out = set(), []
    for net in sorted(d):
        if net in seen:
            continue
        other = d[net]
        seen.add(net)
        seen.add(other)
        k = pair_key(net)
        out.append((net, other) if k is None or k[1] else (other, net))
    return out
