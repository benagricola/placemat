"""Compare two finding corpora (tests/finding_corpus.py): `python tests/finding_corpus_diff.py BEFORE.json AFTER.json`.

Prints the (kind, severity, sentence) entries only the first has and only the second has, and exits 1 when there are any.
tests/finding_text_golden.json is the corpus made before findings were converted to structured facts."""
import json
import sys


def load(path):
    with open(path) as f:
        return {tuple(e) for e in json.load(f)}


def main(argv) -> int:
    before, after = load(argv[1]), load(argv[2])
    only_before, only_after = sorted(before - after), sorted(after - before)
    for tag, entries in (("only before", only_before), ("only after", only_after)):
        for kind, severity, text in entries:
            print("%-11s [%s] %s: %s" % (tag, severity, kind, text))
    print("%d before, %d after, %d only before, %d only after" % (len(before), len(after), len(only_before), len(only_after)))
    return 1 if only_before or only_after else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
