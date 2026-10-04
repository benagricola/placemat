"""The `.pmm` mesh file, vertex-clustering decimation, and the shared model cache."""
import os
from array import array

import pytest

from placemat import model_cache as mc
from placemat import model_mesh as mm


def quad_grid(n, size=10.0, colour=(200, 100, 50)):
    """An n x n grid of quads in the x-y plane (2 n n triangles), one material."""
    pos, nor, idx = array("f"), array("f"), array("I")
    for j in range(n + 1):
        for i in range(n + 1):
            pos.extend((size * i / n, size * j / n, 0.0))
            nor.extend((0.0, 0.0, 1.0))
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            idx.extend((a, a + 1, a + n + 2, a, a + n + 2, a + n + 1))
    return mm.Mesh([mm.Material(colour, 1.0, pos, nor, idx)])


def test_a_mesh_round_trips_through_the_file_with_its_header():
    mesh = quad_grid(4)
    data = mm.write_pmm(mesh)
    assert data[:6] == b"PMMESH"
    back = mm.read_pmm(data)
    assert len(back.materials) == 1 and list(back.materials[0].indices) == list(mesh.materials[0].indices)
    assert list(back.materials[0].positions) == pytest.approx(list(mesh.materials[0].positions))
    assert back.header["tris"] == 32 and back.header["tris_in"] == 32 and back.header["converter"] == mm.CONVERTER_VERSION
    assert back.header["bbox"] == pytest.approx([0, 0, 0, 10, 10, 0])
    assert back.header["materials"][0]["colour"] == [200, 100, 50] and back.header["materials"][0]["index_bytes"] == 2


def test_indices_are_sixteen_bit_under_65536_vertices_and_thirty_two_over():
    big = mm.Mesh([mm.Material((1, 2, 3), 1.0, array("f", [0.0] * 3 * 70000), array("f", [0.0] * 3 * 70000), array("I", [0, 1, 69999]))])
    data = mm.write_pmm(big)
    assert mm.read_pmm(data).header["materials"][0]["index_bytes"] == 4 and list(mm.read_pmm(data).materials[0].indices) == [0, 1, 69999]


def test_a_file_that_is_not_a_mesh_or_is_cut_short_is_refused():
    data = mm.write_pmm(quad_grid(3))
    for bad in (b"", b"NOTAMESH" + data[8:], data[:20], data[:-5]):
        with pytest.raises(mm.MeshError):
            mm.read_pmm(bad)


def test_decimation_ends_under_the_cap_keeps_the_box_and_drops_nothing_it_need_not():
    mesh = quad_grid(100)                                        # 20000 triangles
    small, cell = mm.decimate(mesh, 5000)
    assert mm.triangles(small) <= 5000 and mm.triangles(small) > 500
    x0, y0, z0, x1, y1, z1 = mm.bbox(small)
    assert x0 <= cell and x1 >= 10 - cell and y0 <= cell and y1 >= 10 - cell
    same, _ = mm.decimate(quad_grid(10), 5000)                   # under the cap: untouched
    assert mm.triangles(same) == 200
    assert mm.decimate(mesh, 5000)[0].materials[0].positions == small.materials[0].positions         # deterministic


def test_the_header_keeps_the_count_before_decimation():
    small, _ = mm.decimate(quad_grid(100), 5000)
    small.tris_in = 20000
    assert mm.read_pmm(mm.write_pmm(small)).header["tris_in"] == 20000


# ---------------------------------------------------------------- the cache
@pytest.fixture
def cache(tmp_path):
    return mc.Cache(tmp_path / "models", mb=1)


def test_a_write_is_atomic_and_a_read_touches_the_file(cache):
    cache.put("a" * 32, b"hello")
    assert cache.get("a" * 32).read_bytes() == b"hello" and not [p for p in cache.dir.iterdir() if p.suffix == ".tmp"]
    p = cache.get("a" * 32)
    os.utime(p, (1000, 1000))
    cache.get("a" * 32)
    assert p.stat().st_mtime > 1000
    assert cache.get("b" * 32) is None
    assert cache.name("a" * 32).startswith("v%d-" % mm.CONVERTER_VERSION)


def test_a_failure_is_kept_until_retry_or_a_new_version(cache):
    cache.put_failure("c" * 32, {"code": "export_failed", "returncode": 1, "detail": "kicad-cli said no"})
    assert cache.failure("c" * 32) == {"code": "export_failed", "returncode": 1, "detail": "kicad-cli said no"}
    cache.retry("c" * 32)
    assert cache.failure("c" * 32) is None
    cache.put_failure("c" * 32, {"code": "no_mesh"})
    cache.put_failure("d" * 32, {"code": "no_mesh"})
    cache.retry(None)
    assert cache.failure("c" * 32) is None and cache.failure("d" * 32) is None


def test_files_of_another_converter_version_are_ignored_and_removed_at_start(tmp_path):
    d = tmp_path / "models"
    d.mkdir()
    (d / ("v%d-%s.pmm" % (mm.CONVERTER_VERSION + 1, "e" * 32))).write_bytes(b"newer")
    (d / ("v0-%s.pmm" % ("f" * 32))).write_bytes(b"older")
    (d / "notes.txt").write_text("someone's file")
    c = mc.Cache(d, mb=1)
    assert c.get("e" * 32) is None and c.sweep_versions() == 2
    assert sorted(p.name for p in d.iterdir()) == ["notes.txt"]


def test_over_the_bound_the_least_recently_used_go_first_and_never_one_in_use(tmp_path):
    c = mc.Cache(tmp_path / "models", mb=1)
    ids = [("%032x" % i) for i in range(6)]
    for n, i in enumerate(ids):
        c.put(i, b"x" * 300_000)
        os.utime(c.get(i), (1000 + n, 1000 + n))                  # oldest first; get() has touched them, so set after
    for n, i in enumerate(ids):
        os.utime(c.dir / c.name(i), (1000 + n, 1000 + n))
    gone = c.trim(in_use={ids[0]})
    left = {i for i in ids if (c.dir / c.name(i)).exists()}
    assert ids[0] in left and ids[-1] in left and gone >= 1
    assert sum(p.stat().st_size for p in c.dir.iterdir()) <= 0.8 * 1024 * 1024
    assert ids[1] not in left                                    # the oldest one not in use went first


def test_two_caches_on_one_folder_share_what_either_wrote(tmp_path):
    a, b = mc.Cache(tmp_path / "m", mb=1), mc.Cache(tmp_path / "m", mb=1)
    a.put("1" * 32, b"from a")
    assert b.get("1" * 32).read_bytes() == b"from a"


def test_the_default_folder_is_the_users_cache_and_a_setting_overrides_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert mc.default_dir("") == tmp_path / "xdg" / "placemat" / "models"
    assert mc.default_dir(str(tmp_path / "mine")) == tmp_path / "mine"
