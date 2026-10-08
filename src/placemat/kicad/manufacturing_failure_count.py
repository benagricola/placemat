"""Count original and stricter clearance failure domains without double counting.

A clearance domain is its unordered item UUID pair. Multiplicity is retained:
matching reports contribute their maximum count for a domain, not their sum.
This is a ranking count, not a claim of unique geometric violation locations.
"""
from collections import Counter
from .manufacturing_annular import Unproved


def failure_count(original_errors, mandatory_pairs):
    original = Counter()
    for finding in original_errors:
        if finding['severity'] != 'error':
            continue
        ids = tuple(sorted(item['uuid'] for item in finding['items']))
        original[(finding['type'], ids)] += 1
    mandatory = Counter()
    for pair in mandatory_pairs:
        ids = pair.get('uuids')
        if (type(ids) is not list or len(ids) != 2
                or any(type(uid) is not str for uid in ids)
                or len(set(ids)) != 2):
            raise Unproved('clearance_failure_identity')
        mandatory[('clearance', tuple(sorted(ids)))] += 1
    return sum((original | mandatory).values())
