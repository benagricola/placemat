"""A pytest plugin that records every finding the tests build: (kind, severity, sentence), once each.

    PLACEMAT_FINDING_CORPUS=/tmp/corpus.json pytest -p tests.finding_corpus

writes the sorted list at exit. tests/finding_text_golden.json is such a list, made from main before findings were
converted to structured facts; a run after the conversion must give the same list (`tests/finding_corpus_diff.py`
prints the difference). A sentence a finding renders is pinned by this, whichever test builds it."""
import atexit
import json
import os
import re

_seen = set()
_TMP = re.compile(r"/tmp/pytest-of-[^/]+/pytest-\d+/")


def _name(x) -> str:
    return getattr(x, "value", x)


def pytest_configure(config):
    out = os.environ.get("PLACEMAT_FINDING_CORPUS")
    if not out:
        return
    from placemat import findings
    original = findings.Finding.__new__

    def new(cls, *args, **kwargs):
        self = original(cls, *args, **kwargs)
        _seen.add((str(_name(self.kind)), self.severity, _TMP.sub("/tmp/pytest/", str(self))))
        return self
    findings.Finding.__new__ = new

    def write():
        with open(out, "w") as f:
            json.dump(sorted(_seen), f, indent=0)
    atexit.register(write)
