"""The studio page: one static file, nothing fetched from outside, script that parses."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

import placemat
from placemat.cli import parser

PAGE = Path(placemat.__file__).with_name("studio_page.html")


def test_the_page_ships_in_the_package_and_loads_nothing_from_outside():
    text = PAGE.read_text()
    assert text.lstrip().lower().startswith("<!doctype html>")
    assert not re.search(r'(?:src|href)\s*=\s*"(?:https?:)?//', text) and "@import" not in text
    assert "https://" not in text and "cdn" not in text.lower()
    assert text.count("<script") == 1                  # one inline script, no external one


def test_the_page_names_every_event_the_server_sends():
    text = PAGE.read_text()
    server = (Path(placemat.__file__).with_name("studio.py")).read_text()
    sent = set(re.findall(r'emit\("(\w+)"', server)) | {"hello", "state"}
    heard = set(re.findall(r'\bon\("(\w+)"', text))
    assert sent <= heard, sent - heard


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_parses(tmp_path):
    text = PAGE.read_text()
    js = text[text.index("<script>") + 8:text.index("</script>")]
    f = tmp_path / "page.js"
    f.write_text(js)
    done = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_command_takes_a_script_a_port_and_no_open():
    args = parser().parse_args(["studio", "layout.py", "--port", "8123", "--no-open"])
    assert (args.command, args.script, args.port, args.no_open) == ("studio", "layout.py", 8123, True)
    assert parser().parse_args(["studio", "layout.py"]).port is None
