"""No reference doc names a removed command, option or setting outside the migration notes."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "skills/placemat/SKILL.md", ROOT / "skills/placemat/references/api.md",
        ROOT / "skills/placemat/references/capture.md", ROOT / "README.md"]
REMOVED = [l.strip() for l in (Path(__file__).with_name("surface") / "removed.txt").read_text().splitlines()
           if l.strip() and not l.startswith("#")]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_no_reference_doc_names_a_removed_form(doc):
    text = doc.read_text()
    named = [r for r in REMOVED if r in text]
    assert not named, "%s names removed forms: %s (only migration.md may)" % (doc.name, named)
