"""A footprint's model entry resolved to a file, an embedded file or a reason (models.resolve_model), and the ids that name a model by its
content."""
import hashlib
import os
from pathlib import Path


from placemat import models
from placemat.models import embedded_checksums, model_id, resolve_model


def _touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_a_declared_nothing_is_none_and_a_hidden_entry_is_hidden(tmp_path):
    assert resolve_model("", tmp_path).state == "none"
    _touch(tmp_path / "m.step")
    r = resolve_model("m.step", tmp_path, hidden=True)
    assert r.state == "hidden" and r.name == "m.step"


def test_an_embedded_model_is_named_and_has_no_path(tmp_path):
    r = resolve_model("kicad-embed://R_0402.step", tmp_path)
    assert (r.state, r.embedded, r.path, r.name) == ("ok", "R_0402.step", "", "R_0402.step")


def test_an_absolute_path_is_taken_as_it_is_and_a_missing_one_keeps_its_text(tmp_path):
    f = _touch(tmp_path / "lib" / "a.step")
    assert resolve_model(str(f), tmp_path / "elsewhere").path == str(f)
    r = resolve_model(str(tmp_path / "lib" / "gone.step"), tmp_path)
    assert r.state == "missing" and r.text == str(tmp_path / "lib" / "gone.step") and "not found" in r.why


def test_kiprjmod_is_the_projects_folder_and_is_reanchored_as_the_write_step_does(tmp_path):
    ws = tmp_path / "ws"
    (ws / "pcb.toml").parent.mkdir(parents=True)
    (ws / "pcb.toml").write_text("[workspace]\n")
    project = ws / "modules" / "m" / "layout"
    project.mkdir(parents=True)
    _touch(project / "here.step")
    assert resolve_model("${KIPRJMOD}/here.step", project).path == str(project / "here.step")
    assert resolve_model("$(KIPRJMOD)/here.step", project).path == str(project / "here.step")
    shared = _touch(ws / "adapted" / "parts" / "p.step")
    text = "${KIPRJMOD}/../../../../adapted/parts/p.step"           # right for a project at another depth
    assert not (project / "../../../../adapted/parts/p.step").exists()
    got = resolve_model(text, project, stop=ws)
    assert got.state == "ok" and Path(got.path).resolve() == shared.resolve()
    assert models.reanchor(text, project, ws)[0] is not None            # the same answer the write step gives
    assert resolve_model("${KIPRJMOD}/../../../../adapted/parts/none.step", project, stop=ws).state == "missing"


def test_another_variable_is_the_environment_then_the_model_folders(tmp_path, monkeypatch):
    env_dir = tmp_path / "envdir"
    _touch(env_dir / "e.step")
    monkeypatch.setenv("MY_3D", str(env_dir))
    assert resolve_model("${MY_3D}/e.step", tmp_path).path == str(env_dir / "e.step")
    extra = tmp_path / "extra"
    _touch(extra / "Pkg" / "k.step")
    monkeypatch.delenv("KICAD9_3DMODEL_DIR", raising=False)
    r = resolve_model("${KICAD9_3DMODEL_DIR}/Pkg/k.step", tmp_path, extra_dirs=(str(extra),))
    assert r.state == "ok" and r.path == str(extra / "Pkg" / "k.step")
    assert resolve_model("${NOT_A_VARIABLE}/k.step", tmp_path).state == "missing"


def test_a_relative_path_is_from_the_projects_folder(tmp_path):
    _touch(tmp_path / "sub" / "r.step")
    assert resolve_model("sub/r.step", tmp_path).path == str(tmp_path / "sub" / "r.step")
    assert resolve_model("sub\\r.step", tmp_path).path == str(tmp_path / "sub" / "r.step")


def test_a_vrml_model_takes_the_step_beside_it_and_is_vrml_without_one(tmp_path):
    _touch(tmp_path / "a.wrl")
    _touch(tmp_path / "b.wrl")
    _touch(tmp_path / "b.STEP")
    assert resolve_model("a.wrl", tmp_path).state == "vrml" and resolve_model("a.wrl", tmp_path).path == str(tmp_path / "a.wrl")
    r = resolve_model("b.wrl", tmp_path)
    assert r.state == "ok" and r.path == str(tmp_path / "b.STEP")


def test_a_model_is_named_by_its_content_and_a_renamed_file_keeps_its_id(tmp_path):
    a = _touch(tmp_path / "a.step", b"model bytes")
    b = _touch(tmp_path / "other" / "renamed.step", b"model bytes")
    c = _touch(tmp_path / "c.step", b"different")
    assert model_id(str(a)) == model_id(str(b)) == hashlib.sha256(b"model bytes").hexdigest()[:32] and model_id(str(c)) != model_id(str(a))
    a.write_bytes(b"changed")                                   # remembered by (path, mtime, size): a change is seen
    os.utime(a, ns=(a.stat().st_atime_ns, a.stat().st_mtime_ns + 5_000_000_000))
    assert model_id(str(a)) == hashlib.sha256(b"changed").hexdigest()[:32]


BOARD = '''(kicad_pcb
	(footprint "lib:R"
		(property "Reference" "R1"
		)
		(embedded_files
			(file
				(name "R.step")
				(type model)
				(checksum "AAAA1111")
			)
		)
	)
	(footprint "lib:C"
		(property "Reference" "C2"
		)
		(embedded_files
			(file
				(name "C.step")
				(type model)
				(data |abc|)
				(checksum "BBBB2222")
			)
		)
	)
	(footprint "lib:J"
		(property "Reference" "J3"
		)
	)
)
'''


def test_an_embedded_models_id_is_its_checksum_by_footprint(tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text(BOARD)
    sums = embedded_checksums(str(pcb))
    assert sums == {"R1": {"R.step": "AAAA1111"}, "C2": {"C.step": "BBBB2222"}}
    assert model_id("", embedded=("R.step", sums["R1"]["R.step"])) == "e-aaaa1111"
    assert model_id("", embedded=("C.step", "BBBB2222")) != model_id("", embedded=("R.step", "AAAA1111"))
