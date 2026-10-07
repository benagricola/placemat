import hashlib

import pytest

from fixtures.reference import fetch


def test_the_manifest_lists_eight_boards_each_pinned_with_a_licence():
    boards = fetch.load_manifest()
    assert len(boards) == 8 and len({b.name for b in boards}) == 8
    for b in boards:
        assert len(b.commit) == 40 and b.licence and b.board in b.files and set(b.tests) <= {"a", "b"}


def test_a_cached_file_whose_sha256_matches_is_used_without_the_network(tmp_path, monkeypatch):
    board = fetch.Board(name="tiny", repo="github:o/r", commit="0" * 40, files={"x.kicad_pcb": hashlib.sha256(b"pcb").hexdigest()},
                        board="x.kicad_pcb", licence="MIT", tests=("a",), islands=(), fixed=(), human_track_mm=None, kicad5=False)
    (tmp_path / "tiny").mkdir(); (tmp_path / "tiny" / "x.kicad_pcb").write_bytes(b"pcb")
    monkeypatch.setattr(fetch, "_download", lambda *a: pytest.fail("network used"))
    assert fetch.fetch(board, tmp_path, offline=True) == tmp_path / "tiny"


def test_a_sha256_mismatch_names_the_file(tmp_path):
    board = fetch.Board(name="tiny", repo="github:o/r", commit="0" * 40, files={"x.kicad_pcb": "f" * 64},
                        board="x.kicad_pcb", licence="MIT", tests=("a",), islands=(), fixed=(), human_track_mm=None, kicad5=False)
    (tmp_path / "tiny").mkdir(); (tmp_path / "tiny" / "x.kicad_pcb").write_bytes(b"pcb")
    with pytest.raises(fetch.FetchError, match="x.kicad_pcb"):
        fetch.fetch(board, tmp_path, offline=True)


def test_offline_with_an_empty_cache_names_the_board_and_url(tmp_path):
    board = fetch.load_manifest()[0]
    with pytest.raises(fetch.FetchError, match=board.name):
        fetch.fetch(board, tmp_path, offline=True)
    with pytest.raises(fetch.FetchError, match="gitlab.com"):
        fetch.fetch(board, tmp_path, offline=True)


def test_a_download_is_checked_and_written_through_the_cache(tmp_path, monkeypatch):
    board = fetch.Board(name="tiny", repo="github:o/r", commit="0" * 40, files={"d/x.kicad_pcb": hashlib.sha256(b"pcb").hexdigest()},
                        board="d/x.kicad_pcb", licence="MIT", tests=("a",), islands=(), fixed=(), human_track_mm=None, kicad5=False)
    seen = []
    monkeypatch.setattr(fetch, "_download", lambda u: seen.append(u) or b"pcb")
    folder = fetch.fetch(board, tmp_path)
    assert (folder / "d" / "x.kicad_pcb").read_bytes() == b"pcb"
    assert seen == ["https://raw.githubusercontent.com/o/r/" + "0" * 40 + "/d/x.kicad_pcb"]
    monkeypatch.setattr(fetch, "_download", lambda u: b"tampered")
    (folder / "d" / "x.kicad_pcb").unlink()
    with pytest.raises(fetch.FetchError, match="sha256"):
        fetch.fetch(board, tmp_path)
