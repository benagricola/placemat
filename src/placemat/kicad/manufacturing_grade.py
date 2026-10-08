"""Exact ordinary manufacturing grade domain; shared before interpretation."""
import math

class GradeUnproved(ValueError):
    pass


def typed_grade(grade):
    if (type(grade) is not dict
            or set(grade) != {'known','unproved','drc','undersized','widths_unknown','open','quality'}
            or type(grade['known']) is not bool or type(grade['widths_unknown']) is not bool
            or type(grade['unproved']) is not list
            or any(type(r) is not str for r in grade['unproved'])
            or any(type(grade[k]) is not int or grade[k]<0 for k in ('drc','undersized','open'))
            or type(grade['quality']) is not list or len(grade['quality']) != 3):
        raise GradeUnproved('ordinary_grade_malformed')
    for value in grade['quality']:
        try:
            valid = type(value) in (int, float) and value >= 0 and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            raise GradeUnproved('ordinary_grade_malformed')
    if (grade['known'] and grade['unproved']) or (not grade['known'] and not grade['unproved']):
        raise GradeUnproved('ordinary_grade_contradictory')
