import pytest
from placemat.checks import Verdict, Acceptance, Outcome
from placemat.final_board import Judgement
from placemat.findings import Finding, FindingCause, FindingKind
from placemat.kicad.final_call import ProofUnavailable

from placemat import final_check_judgement as codec

@pytest.fixture
def judgement():
    a=Acceptance('current-path','N',at_least=.2,why='fixed original allowance')
    v=Verdict('current-path','N',.1,'mm',.2,False,accepted='fixed original allowance',
              facts={'fill':None,'basis':None,'neck':[1.,2.],'apart':[('A','1')],'layers':[]})
    f=Finding(FindingCause.ESCAPE_VIA,{'ref':'U1','pin':'1','net':'N','by':[]})
    return Judgement([v,Verdict('current-path','M',0.,'mm',None,None)],
        [Outcome(a,'not needed',why_not='not_judged')],[f],
        {'vias':3,'length':2.5,'critical_checks':0,'critical_unknown':[{'check':'current-path','subject':'M','reason':'not judged'}],
         'findings':{FindingKind.ESCAPE_VIA:1}})


def test_exact_current_escape_and_metrics_round_trip(judgement):
    rebuilt=codec.decode(codec.encode(judgement))
    assert rebuilt==judgement and type(rebuilt) is Judgement
    assert rebuilt.verdicts[0].ok is False and rebuilt.verdicts[1].ok is None
    assert rebuilt.verdicts[0].facts['fill'] is None
    assert type(rebuilt.verdicts[0].facts['apart'][0]) is tuple
    assert rebuilt.outcomes[0].why_not=='not_judged'
    assert rebuilt.outcomes[0].acceptance.at_most is None
    assert rebuilt.findings[0].kind is FindingKind.ESCAPE_VIA
    assert type(next(iter(rebuilt.measures['findings']))) is FindingKind
    assert rebuilt.findings[0].detail()==judgement.findings[0].detail()


@pytest.mark.parametrize('field,value',[('ok',0),('value',None),('value',True),('value',float('nan')),
    ('value',10**1000),('limit',float('inf')),('accepted',False)])
def test_malformed_verdict_refuses(judgement,field,value):
    record=codec.encode(judgement)
    record['fields']['verdicts']['items'][0]['fields'][field]=value
    with pytest.raises(ProofUnavailable):codec.decode(record)


def test_nonempty_suggestion_is_not_silently_dropped(judgement):
    judgement.findings[0].suggestions=(object(),)
    with pytest.raises(ProofUnavailable):codec.encode(judgement)


@pytest.mark.parametrize('field,value',[('text','changed'),('facts_v',True),('kind',None),('severity','unknown')])
def test_rendered_finding_metadata_exact(judgement,field,value):
    record=codec.encode(judgement);record['fields']['findings']['items'][0][field]=value
    with pytest.raises(ProofUnavailable):codec.decode(record)


@pytest.mark.parametrize('value',[object(),{'type':'unknown','fields':{}},
    {'type':'enum','name':[],'value':'x'},{'type':'dict','items':[['same',1],['same',2]]}])
def test_unknown_nested_values_refuse(value):
    with pytest.raises(ProofUnavailable):
        codec.encode(value) if not isinstance(value,dict) else codec.decode(value)

@pytest.mark.parametrize('key,value',[('critical_checks',True),('critical_checks','0'),
    ('critical_checks',-1),('critical_checks',1),('critical_unknown','unknown'),
    ('critical_unknown',[{'check':True,'subject':'N','reason':'not judged'}]),
    ('findings',{'route':True}),('findings',{'route':-1})])
def test_typed_critical_measure_projection(judgement,key,value):
    record=codec.encode(judgement)
    record['fields']['measures']=codec.encode(dict(judgement.measures,**{key:value}))
    with pytest.raises(ProofUnavailable):codec.decode(record)


@pytest.mark.parametrize('field,value',[('expected',True),('actual',[])])
def test_captured_intent_unknown_keeps_observed_scalar_types(judgement,field,value):
    unknown={'check':'captured-intent','subject':'U1','field':'Pm.I','expected':'1A','actual':None}
    unknown[field]=value
    record=codec.encode(judgement)
    record['fields']['measures']=codec.encode(dict(judgement.measures,critical_unknown=[*judgement.measures['critical_unknown'],unknown]))
    with pytest.raises(ProofUnavailable):codec.decode(record)


def test_missing_unjudged_critical_record_refuses(judgement):
    record=codec.encode(judgement)
    record['fields']['measures']=codec.encode(dict(judgement.measures,critical_unknown=[]))
    with pytest.raises(ProofUnavailable):codec.decode(record)
