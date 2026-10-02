"""The studio's watcher: modification times polled, changes debounced, a resolve cancelled."""
import os

from placemat.studio_watch import Debounce, Poller


def test_a_change_is_due_after_the_quiet_period_and_not_before():
    d = Debounce(0.3)
    assert d.due(0.0) is None
    d.changed(0.0, {"a"})
    assert d.due(0.29) is None
    assert d.due(0.31) == {"a"}
    assert d.due(0.4) is None                        # handed over once


def test_each_change_restarts_the_quiet_period_and_the_files_gather():
    d = Debounce(0.3)
    d.changed(0.0, {"a"})
    d.changed(0.25, {"b"})
    assert d.due(0.5) is None
    assert d.due(0.56) == {"a", "b"}


def test_a_change_during_a_resolve_asks_for_it_to_be_cancelled_and_waits_for_it_to_stop():
    d = Debounce(0.3)
    d.changed(0.0, {"a"})
    assert d.due(0.4) == {"a"}
    d.started()
    assert d.changed(1.0, {"b"}) is True              # the caller cancels the resolve
    assert d.due(5.0) is None                         # still stopping: nothing starts over it
    d.stopped()
    assert d.due(5.0) == {"b"}


def test_a_change_with_nothing_running_does_not_ask_for_a_cancel():
    d = Debounce(0.3)
    assert d.changed(0.0, {"a"}) is False


def test_zero_quiet_starts_at_once():
    d = Debounce(0.0)
    d.changed(1.0, {"a"})
    assert d.due(1.0) == {"a"}


def test_a_change_during_a_resolve_that_finishes_anyway_is_still_pending():
    d = Debounce(0.1)
    d.started()
    d.changed(0.0, {"a"})
    d.stopped()
    assert d.due(0.2) == {"a"}


def test_the_poller_names_files_whose_time_or_size_changed(tmp_path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("1")
    b.write_text("2")
    p = Poller(lambda: [a, b])
    assert p.scan() == set()
    st = a.stat()
    os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    assert p.scan() == {a}
    assert p.scan() == set()
    b.write_text("22")
    assert p.scan() == {b}


def test_a_file_that_appears_or_goes_is_a_change(tmp_path):
    a, lock = tmp_path / "a.py", tmp_path / "a.lock.json"
    a.write_text("1")
    p = Poller(lambda: [a, lock])
    assert p.scan() == set()
    lock.write_text("{}")
    assert p.scan() == {lock}
    lock.unlink()
    assert p.scan() == {lock}


def test_the_file_set_is_asked_again_each_scan(tmp_path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("1")
    b.write_text("2")
    names = [a]
    p = Poller(lambda: list(names))
    assert p.scan() == set()
    names.append(b)                                   # a new import: a file already there is not a change
    assert p.scan() == set()
    b.write_text("33")
    assert p.scan() == {b}
