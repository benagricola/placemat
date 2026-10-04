"""A native module that is not in use is never silent: one record says so and why, and the findings, the preview JSON,
the channel's hello and the console carry it."""
import argparse

import pytest

from placemat import cli, geometry
from placemat.channel import describe
from placemat.finding_text import render
from placemat.findings import FindingCause as C
from placemat.geometry import NativeStatus, _decide_native
from placemat.preview_json import declared_sites, plan_json
from placemat.values import Location, Part
from tests.test_finding_kinds import _board as _kinds_board

OFF = {
    "version_mismatch": NativeStatus(False, "version_mismatch", "0.98.0", "0.97.0"),
    "not_installed": NativeStatus(False, "not_installed", "0.98.0"),
    "import_error": NativeStatus(False, "import_error", "0.98.0", None, "ImportError: libfoo.so"),
}
ON = NativeStatus(True, "", "0.98.0", "0.98.0")


def _native_findings(plan):
    return [f for f in plan.findings if f.cause is C.SETUP_NATIVE]


def _board():
    b = _kinds_board()
    b.place(Part("u1"), at=Location(20, 20))
    return b


def test_the_decision_names_every_reason():
    class Module:
        __version__ = "0.97.0"
    assert _decide_native(Module(), None, "0.98.0", False)[1] == OFF["version_mismatch"]
    assert _decide_native(None, None, "0.98.0", False)[1] == OFF["not_installed"]
    assert _decide_native(None, "ImportError: libfoo.so", "0.98.0", False)[1] == OFF["import_error"]
    module, status = _decide_native(Module(), None, "0.97.0", False)
    assert module is not None and status == NativeStatus(True, "", "0.97.0", "0.97.0")
    module, status = _decide_native(Module(), None, "0.97.0", True)
    assert module is None and status.reason == "disabled_by_env" and not status.warns


@pytest.mark.parametrize("reason", sorted(OFF))
def test_a_resolve_with_native_off_carries_a_setup_warning_with_the_facts(monkeypatch, reason):
    monkeypatch.setattr(geometry, "NATIVE_STATUS", OFF[reason])
    found = _native_findings(_board().resolve())
    assert len(found) == 1
    f = found[0]
    assert f.severity == "warning" and f.kind == "setup"
    assert f.facts["reason"] == reason and f.facts["placemat_version"] == "0.98.0"
    assert f.facts["native_version"] == OFF[reason].native_version
    text = render(C.SETUP_NATIVE, f.facts)
    assert "pure Python" in text and "uv pip install -e" in text
    if reason == "version_mismatch":
        assert "0.97.0" in text and "0.98.0" in text
    if reason == "import_error":
        assert "libfoo.so" in text


def test_nothing_is_said_when_native_is_in_use_or_switched_off_on_purpose(monkeypatch):
    monkeypatch.setattr(geometry, "NATIVE_STATUS", ON)
    assert _native_findings(_board().resolve()) == []
    monkeypatch.setattr(geometry, "NATIVE_STATUS", NativeStatus(False, "disabled_by_env", "0.98.0", "0.98.0"))
    assert _native_findings(_board().resolve()) == []


def test_the_preview_json_and_the_hello_carry_the_record(monkeypatch):
    monkeypatch.setattr(geometry, "NATIVE_STATUS", OFF["version_mismatch"])
    b = _board()
    doc = plan_json(b.resolve(), declared_sites(b))
    assert doc["native"] == OFF["version_mismatch"].facts()
    assert any(f["cause"] == "setup.native" for f in doc["findings"])
    line = describe({"ev": "hello", "command": "run", "script": "a.py", "native": doc["native"]})
    assert "native off: version_mismatch" in line
    assert "native off" not in describe({"ev": "hello", "command": "run", "script": "a.py", "native": ON.facts()})


def test_the_console_line_is_said_when_native_is_off_and_not_when_it_is_in_use(monkeypatch, capsys):
    args = argparse.Namespace(json=False)
    monkeypatch.setattr(geometry, "NATIVE_STATUS", OFF["not_installed"])
    cli.say_native_off(args)
    out = capsys.readouterr().out
    assert "setup" in out and "not installed" in out and "uv pip install -e" in out
    cli.say_native_off(argparse.Namespace(json=True))
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(geometry, "NATIVE_STATUS", ON)
    cli.say_native_off(args)
    assert capsys.readouterr().out == ""
