"""Named JSON transport for a full final judgement; no comparison authority."""
from dataclasses import fields
import math

from placemat.kicad.final_call import ProofUnavailable, record_digest


def _refuse():
    raise ProofUnavailable('final_judgement_transport_unsupported')


def _classes():
    from placemat.checks import Verdict, Acceptance, Outcome
    from placemat.final_board import Judgement
    return {cls.__name__: cls for cls in (Verdict, Acceptance, Outcome, Judgement)}


def _enums():
    from placemat.findings import FindingCause, FindingKind
    from placemat.values import Face, CopperLayer
    return {name: cls for name, cls in (('FindingCause', FindingCause),
        ('FindingKind', FindingKind), ('Face', Face), ('CopperLayer', CopperLayer))}


def _finite(value, optional=False):
    if value is None and optional:
        return
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        _refuse()


def _validate(value):
    from placemat.checks import Verdict, Acceptance, Outcome, CHECK_SEVERITY
    from placemat.final_board import Judgement
    if type(value) is Verdict:
        if any(type(getattr(value, key)) is not str for key in ('check','subject','unit','note','accepted')):
            _refuse()
        _finite(value.value)
        _finite(value.limit, True)
        if value.ok is not None and type(value.ok) is not bool:
            _refuse()
        if type(value.facts) is not dict:
            _refuse()
    elif type(value) is Acceptance:
        if any(type(getattr(value,key)) is not str for key in ('check','subject','why')):
            _refuse()
        if (value.at_least is None) == (value.at_most is None):
            _refuse()
        _finite(value.at_least, True)
        _finite(value.at_most, True)
    elif type(value) is Outcome:
        if (type(value.acceptance) is not Acceptance or value.outcome not in
                ('accepted','past','unmatched','not needed') or type(value.why_not) is not str):
            _refuse()
        _finite(value.value, True)
    elif type(value) is Judgement:
        from placemat.findings import Finding
        if (type(value.verdicts) is not list or any(type(v) is not Verdict for v in value.verdicts)
                or type(value.outcomes) is not list or any(type(v) is not Outcome for v in value.outcomes)
                or type(value.findings) is not list or any(type(v) is not Finding for v in value.findings)
                or type(value.measures) is not dict):
            _refuse()
        measures=value.measures
        if (type(measures.get('critical_checks')) is not int or measures['critical_checks']<0
                or measures['critical_checks']!=sum(v.severity=='critical' for v in value.verdicts)
                or type(measures.get('critical_unknown')) is not list
                or type(measures.get('findings')) is not dict):
            _refuse()
        expected_unknown=[{'check':v.check,'subject':v.subject,'reason':'not judged'}
                          for v in value.verdicts if v.ok is None and not v.accepted
                          and CHECK_SEVERITY.get(v.check)=='critical']
        actual_unknown=measures['critical_unknown']
        if (record_digest(actual_unknown[:len(expected_unknown)])!=record_digest(expected_unknown)
                or any(type(r) is not dict or r.get('check')!='captured-intent'
                       for r in actual_unknown[len(expected_unknown):])):
            _refuse()
        for count in measures['findings'].values():
            if type(count) is not int or count<0:
                _refuse()
        for record in measures['critical_unknown']:
            if type(record) is not dict:
                _refuse()
            if set(record)=={'check','subject','reason'}:
                if any(type(record[k]) is not str for k in record):
                    _refuse()
            elif set(record)=={'check','subject','field','expected','actual'}:
                if (record['check']!='captured-intent' or
                        any(type(record[k]) is not str for k in ('check','subject','field','expected'))
                        or (record['actual'] is not None and type(record['actual']) is not str)):
                    _refuse()
            else:
                _refuse()



def encode(value):
    from placemat.findings import Finding
    for name, cls in _enums().items():
        if type(value) is cls:
            return {'type':'enum','name':name,'value':value.value}
    if type(value) is Finding:
        if value.suggestions:
            _refuse()  # The runner binds suggestions after final judgement.
        return {'type':'Finding','cause':encode(value.cause),'facts':encode(value.facts),
                'severity':value.severity,'kind':encode(value.kind),'text':str(value),'facts_v':value.facts_v}
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        _finite(value)
        return value
    if type(value) in (list,tuple):
        return {'type':'list' if type(value) is list else 'tuple','items':[encode(v) for v in value]}
    if type(value) is dict:
        if any(type(k) is not str and type(k) not in _enums().values() for k in value):
            _refuse()
        return {'type':'dict','items':[[encode(k),encode(v)] for k,v in value.items()]}
    for name,cls in _classes().items():
        if type(value) is cls:
            _validate(value)
            return {'type':name,'fields':{f.name:encode(getattr(value,f.name)) for f in fields(cls)}}
    _refuse()


def decode(record):
    from placemat.findings import Finding
    if record is None or type(record) in (str,bool,int):
        return record
    if type(record) is float:
        _finite(record)
        return record
    if type(record) is not dict or type(record.get('type')) is not str:
        _refuse()
    kind=record['type']
    if kind=='enum':
        if set(record)!={'type','name','value'} or type(record['name']) is not str or record['name'] not in _enums() or type(record['value']) is not str:
            _refuse()
        try:
            return _enums()[record['name']](record['value'])
        except ValueError:
            _refuse()
    if kind in ('list','tuple','dict'):
        if set(record)!={'type','items'} or type(record['items']) is not list:
            _refuse()
        if kind=='dict':
            result={}
            for pair in record['items']:
                if type(pair) is not list or len(pair)!=2:
                    _refuse()
                key=decode(pair[0])
                if (type(key) is not str and type(key) not in _enums().values()) or key in result:
                    _refuse()
                result[key]=decode(pair[1])
            return result
        result=[decode(v) for v in record['items']]
        return tuple(result) if kind=='tuple' else result
    if kind=='Finding':
        if set(record)!={'type','cause','facts','severity','kind','text','facts_v'}:
            _refuse()
        if (type(record['facts_v']) is not int or type(record['text']) is not str
                or type(record['severity']) is not str):
            _refuse()
        try:
            value=Finding(decode(record['cause']),decode(record['facts']),record['severity'])
        except (TypeError,ValueError,KeyError):
            _refuse()
        if record_digest(encode(value))!=record_digest(record):
            _refuse()
        return value
    classes=_classes()
    if kind not in classes or set(record)!={'type','fields'} or type(record['fields']) is not dict:
        _refuse()
    cls=classes[kind]
    if set(record['fields'])!={f.name for f in fields(cls)}:
        _refuse()
    try:
        value=cls(**{k:decode(v) for k,v in record['fields'].items()})
    except (TypeError,ValueError):
        _refuse()
    _validate(value)
    return value
