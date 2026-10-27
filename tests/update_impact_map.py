"""Merge a recorded run into tests/impact_map.json: each test the run recorded gets the run's entry, the others keep
theirs, and tests no longer in tests/slow_tests.txt are dropped.

    PLACEMAT_IMPACT_RECORD=<dir> pytest --full -n 2
    python tests/update_impact_map.py <dir>
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from tests.impact import MAP, load_map, pack  # noqa: E402

SLOW = HERE / "slow_tests.txt"


def main(record_dir: str) -> None:
    doc = load_map()
    parts = sorted(Path(record_dir).glob("impact-*.json"))
    for part in parts:
        doc.update(json.loads(part.read_text()))
    slow = {l.strip() for l in SLOW.read_text().splitlines() if l.strip() and not l.startswith("#")}
    doc = {k: v for k, v in doc.items() if k in slow}
    MAP.write_text(json.dumps(pack(doc), separators=(",", ":")) + "\n")
    print("%d slow tests in %s, from %d recorded parts" % (len(doc), MAP, len(parts)))


if __name__ == "__main__":
    main(sys.argv[1])
