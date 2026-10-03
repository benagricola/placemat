"""The JSON dialect of the splicing editor (json_edit.py) and the fab-profile.json it edits: values replaced or added in the
file's own layout, every other byte kept, a file that does not parse refused."""
import json

import pytest

from placemat import json_edit as je, script_edit as se
from placemat.suggestions import Edit

PROFILE = '''{
  "via": {
    "micro": "no",
    "default_drill_mm": 0.3,
    "default_size_mm": 0.6
  },
  "track_width_presets_mm": {"min": 0.15, "max": 1.0, "step": 0.05},
  "courtyard": {"excess_mm": 0.1}
}
'''


def test_a_value_is_replaced_and_nothing_else_changes():
    out = je.set_values(PROFILE, [(["via", "default_drill_mm"], 0.25)])
    assert out == PROFILE.replace('"default_drill_mm": 0.3', '"default_drill_mm": 0.25')


def test_a_key_is_added_in_the_files_indentation_and_an_object_is_made_where_missing():
    out = je.set_values(PROFILE, [(["via", "blind"], "if-needed"), (["min", "track_mm"], 0.09), (["min", "clearance_mm"], 0.09)])
    assert out == PROFILE.replace('    "default_size_mm": 0.6\n', '    "default_size_mm": 0.6,\n    "blind": "if-needed"\n').replace(
        '  "courtyard": {"excess_mm": 0.1}\n', '  "courtyard": {"excess_mm": 0.1},\n  "min": {\n    "track_mm": 0.09,\n    "clearance_mm": 0.09\n  }\n')
    assert json.loads(out)["min"] == {"track_mm": 0.09, "clearance_mm": 0.09}


def test_a_compact_file_stays_compact_and_an_empty_object_is_filled():
    assert je.set_values('{"via": {"micro": "no"}}', [(["via", "blind"], "no")]) == '{"via": {"micro": "no", "blind": "no"}}'
    out = je.set_values("{}\n", [(["min", "track_mm"], 0.1)])
    assert json.loads(out) == {"min": {"track_mm": 0.1}} and out.endswith("\n")


def test_tabs_and_crlf_are_kept():
    text = '{\r\n\t"via": {\r\n\t\t"micro": "no"\r\n\t}\r\n}\r\n'
    out = je.set_values(text, [(["via", "buried"], "no")])
    assert out == text.replace('"micro": "no"\r\n', '"micro": "no",\r\n\t\t"buried": "no"\r\n')


def test_a_value_equal_to_the_file_changes_nothing():
    assert je.set_values(PROFILE, [(["via", "micro"], "no")]) == PROFILE


def test_a_file_that_does_not_parse_or_is_not_an_object_is_refused():
    with pytest.raises(se.EditRefused, match="not valid JSON"):
        je.set_values('{"via": ', [(["via", "micro"], "no")])
    with pytest.raises(se.EditRefused, match="not an object"):
        je.set_values("[1]", [(["via"], 1)])
    with pytest.raises(se.EditRefused, match="not an object, so"):
        je.set_values('{"via": 3}', [(["via", "micro"], "no")])


def test_a_string_with_brackets_and_arrays_do_not_confuse_the_scanner():
    text = '{"note": "a ] } [ {", "list": [1, "}", [2]], "via": {"micro": "no"}}'
    out = je.set_values(text, [(["via", "blind"], "yes")])
    assert out == text.replace('"micro": "no"}', '"micro": "no", "blind": "yes"}')


def test_the_edit_is_an_op_of_apply_edits(tmp_path):
    p = tmp_path / "fab-profile.json"
    p.write_text(PROFILE)
    e = Edit("json_set", None, {"sets": [{"path": ["via", "buried"], "value": "no"}]}, None, {}, str(p))
    before, after = se.apply_edits([e], lambda path: p.read_text())[str(p)]
    assert before == PROFILE and json.loads(after)["via"]["buried"] == "no"
