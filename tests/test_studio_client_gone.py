"""A page that goes away mid-response (a reload, a closed tab) breaks the pipe the studio writes to: that is the client's
doing and no fault of the studio, so nothing is printed. Any other error in a request is still reported."""
from placemat import studio


def _handled(exc):
    server = studio._Server.__new__(studio._Server)
    try:
        raise exc
    except BaseException:
        server.handle_error(None, ("127.0.0.1", 1))


def test_a_client_that_went_away_prints_nothing(capsys):
    for exc in (BrokenPipeError(32, "Broken pipe"), ConnectionResetError(104, "reset"), ConnectionAbortedError(103, "aborted")):
        _handled(exc)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_any_other_error_is_still_reported(capsys):
    _handled(ValueError("boom"))
    assert "ValueError" in capsys.readouterr().err
