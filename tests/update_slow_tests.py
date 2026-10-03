"""Write tests/slow_tests.txt from a full run's JUnit XML: every test whose
setup and call took longer than SLOW_S. Those are left out of a plain
`pytest` and run by `pytest --full` (conftest.py).

    pytest --full --junitxml=run.xml
    python tests/update_slow_tests.py run.xml
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SLOW_S = 2.0        # a test slower than this, on the machine that ran the full suite, is "slow"
OUT = Path(__file__).with_name("slow_tests.txt")


def node_id(classname: str, name: str) -> str:
    """JUnit's "tests.test_x" (or "tests.test_x.TestCase") and the test's
    name, as pytest's node id "tests/test_x.py::name"."""
    parts = classname.split(".")
    mod = [p for p in parts if not p[:1].isupper()]
    cls = [p for p in parts if p[:1].isupper()]
    return "/".join(mod) + ".py::" + "::".join(cls + [name])


def main(xml_path: str) -> None:
    root = ET.parse(xml_path).getroot()
    slow = sorted({node_id(c.get("classname") or "", c.get("name"))
                   for c in root.iter("testcase") if float(c.get("time") or 0) > SLOW_S})
    OUT.write_text("# tests slower than %.1f s in a full run; written by tests/update_slow_tests.py\n" % SLOW_S
                   + "".join(s + "\n" for s in slow))
    print("%d slow tests written to %s" % (len(slow), OUT))


if __name__ == "__main__":
    main(sys.argv[1])
