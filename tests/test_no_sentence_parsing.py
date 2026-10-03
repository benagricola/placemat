"""Structured findings end to end: a finding is made from a cause and facts, a producer of a reason returns a record, and
nothing reads a sentence for data. Sentences are made in finding_text.py and refusals.py and nowhere else."""
import ast
import re
from pathlib import Path

from placemat import finding_text, refusals
from placemat.findings import Finding, FindingCause

SRC = Path(__file__).resolve().parents[1] / "src" / "placemat"
TREES = {p.name: ast.parse(p.read_text()) for p in sorted(SRC.glob("*.py"))}
TEXT = {p.name: p.read_text() for p in sorted(SRC.glob("*.py"))}

PRODUCERS = {
    # these return a record (a Refusal, an EdgeFault, facts) or None; none is annotated as returning a sentence
    "legal", "legal_giving_way", "legal_bucket", "_conflict", "_drawn_conflict", "_hole_conflict", "copper_conflicts",
    "hole_conflicts", "_edge_why", "_item_edge_why", "board_why", "refusal", "reservation_hit", "_via_site_why", "_tail_why",
    "_cutout_illegal", "_keepout_unusable", "_riders_alone", "_no_pocket_note", "_block_alone", "_via_why", "_pads_why",
    "resolve", "unconfirmed_reasons", "cell_facts", "name_copper", "blame_owner", "_past_unplanned", "layout_block",
    "_nearest_miss_facts", "stamped_rules", "report",
}


def _returns_text(fn: ast.FunctionDef) -> bool:
    ann = fn.returns
    if ann is None:
        return False
    names = {n.id for n in ast.walk(ann) if isinstance(n, ast.Name)}
    return "str" in names


def test_no_producer_of_a_reason_is_annotated_as_returning_a_sentence():
    bad = []
    for name, tree in TREES.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in PRODUCERS and _returns_text(node):
                bad.append("%s:%d %s" % (name, node.lineno, node.name))
    assert not bad, bad


def test_a_finding_is_made_from_a_cause_and_facts_never_a_sentence():
    bad = []
    for name, tree in TREES.items():
        if name in ("findings.py", "finding_text.py"):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if fn in ("Finding", "_finding", "note", "plain") and node.args:
                first = node.args[0]
                if isinstance(first, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                    bad.append("%s:%d" % (name, node.lineno))
    assert not bad, bad
    assert not hasattr(Finding, "plain")


def test_nothing_reads_a_sentence_for_data():
    """The places that used to take a finding's or a refusal's text apart are gone."""
    banned = {
        "preview.py": [r"_AT\b", r"finding_targets"],
        "preview_json.py": [r"_AT\b", r"finding_targets", r"_PIN_LIST", r'str\(f\)\.split'],
        "queries.py": [r"def _kind", r"_COPPER_REASON"],
        "layout.py": [r'f\.split\(" "\)', r'why\.split\(":"\)', r'startswith\("rider "\)', r"UNPLACED: \"\)", r'replace\("UNPLACED'],
        "placer.py": [r'why\.split\(":"\)'],
        "routes.py": [r'len\("dropped: "\)'],
        "suggestions.py": [r'text\.split\(" ", 1\)', r'\.split\(" ", 2\)'],
        "explore.py": [r'"held by lock" in', r'"lock: drifted" in', r'"lock: released" in'],
        "occupancy.py": [r"def _reason_key\(why: str\)", r"_edge_named", r"re\.sub"],
    }
    found = []
    for name, patterns in banned.items():
        for pat in patterns:
            for m in re.finditer(pat, TEXT[name]):
                found.append("%s: %s" % (name, pat))
    assert not found, found


def test_no_sentinel_string_stands_for_a_failure_where_a_record_is_expected():
    """`isinstance(x, str)` on what resolve, _past_point, _past_reach and the like return said "this is a reason": it is a Refusal."""
    for name in ("routes.py", "layout.py", "giveway.py", "queries.py"):
        for m in re.finditer(r"isinstance\((now\[i\]|got\[i\]|at|where|reach|copper), str\)", TEXT[name]):
            raise AssertionError("%s tests a reason by its type being str" % name)


def test_every_cause_has_a_renderer_and_a_version():
    for cause in FindingCause:
        assert cause in finding_text.RENDER and cause in finding_text.REQUIRED, cause
        assert finding_text.facts_version(cause) >= 1


def test_every_refusal_code_has_a_sentence_and_a_bucket():
    for code in refusals.Code:
        assert code in refusals.RENDER and code in refusals.BUCKET, code


def test_a_refusal_round_trips_through_json_and_says_the_same():
    r = refusals.Refusal(refusals.Code.RESERVATION, variant="member", member="C1",
                         by=refusals.ReservedBy("keepout", "ant", "a note", max_height_mm=2.0),
                         parts=[["C1", "tall", 3.0]])
    back = refusals.Refusal.from_json(r.to_json())
    assert back == r and str(back) == str(r)
    assert "C1 is 3 mm" in str(r)
