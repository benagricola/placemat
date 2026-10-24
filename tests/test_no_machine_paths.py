"""The code, tests and settings name no path on one machine: a file outside the checkout comes from an environment
variable or a setting, a scratch file from the system's temporary directory, so the suite runs wherever its
prerequisites are installed."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("src", "tests", "fixtures")
SUFFIXES = (".py", ".toml")
# a home folder or a per-user temporary folder, spelled in parts so this file does not match itself
MACHINE_PATH = re.compile("/" + "home/[a-z][a-z0-9_-]*/|/" + "Users/[A-Za-z][A-Za-z0-9_-]*/|/" + r"tmp/claude-\d+")


def test_no_source_file_names_a_path_on_one_machine():
    found = []
    for top in SCANNED:
        for f in sorted((ROOT / top).rglob("*")):
            if f.suffix not in SUFFIXES or not f.is_file() or ".venv" in f.parts:
                continue
            for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if MACHINE_PATH.search(line):
                    found.append("%s:%d" % (f.relative_to(ROOT), n))
    assert not found, found
