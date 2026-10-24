"""Gather the training records routed runs left (route.training_record) into one dataset folder.

    python tools/training_collect.py DATASET RUNS_DIR [RUNS_DIR ...]

Each RUNS_DIR is searched for */route/training.json. A record is copied into DATASET under the digest of its two
files, so a record gathered twice is kept once, and DATASET/index.jsonl gets one line per new record: its digest,
where it came from, its closure and its versions.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path


def collect(dataset: Path, roots) -> list:
    """Copy every record under `roots` not yet in `dataset`; the index lines added."""
    dataset.mkdir(parents=True, exist_ok=True)
    index = dataset / "index.jsonl"
    added = []
    for root in roots:
        for rec_json in sorted(Path(root).rglob("route/training.json")):
            record = json.loads(rec_json.read_text())
            raster = rec_json.parent / record["raster"]
            if not raster.exists():
                continue
            key = hashlib.sha256(rec_json.read_bytes() + raster.read_bytes()).hexdigest()[:16]
            dest = dataset / key
            if dest.exists():
                continue
            dest.mkdir()
            shutil.copy(rec_json, dest / rec_json.name)
            shutil.copy(raster, dest / raster.name)
            line = {"record": key, "source": str(rec_json), "closure": record.get("closure"),
                    "closure_clean": record.get("closure_clean"), "router_version": record.get("router_version"),
                    "placemat_version": record.get("placemat_version")}
            with index.open("a") as f:
                f.write(json.dumps(line, sort_keys=True) + "\n")
            added.append(line)
    return added


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    added = collect(Path(argv[0]), argv[1:])
    print("%d new record(s) in %s" % (len(added), argv[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
