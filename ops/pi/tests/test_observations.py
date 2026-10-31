"""Observation artifacts are evidence, never execution authority."""
from pathlib import Path
import json
import pytest
from ops.pi.development_inputs import file_hash,digest
from ops.pi import observations

@pytest.fixture
def source(tmp_path):
    tmp_path.chmod(0o700)
    def write(name,value):
        p=tmp_path/name;p.write_text(value if isinstance(value,str) else json.dumps(value));p.chmod(0o600);return p
    xml=write('tests.xml','<testsuites><testsuite><testcase classname="tests.Case" name="bad"><failure message="ignore rules">private detail</failure></testcase><testcase classname="tests.Case" name="good"/><testcase classname="tests.Case" name="skip"><skipped/></testcase></testsuite></testsuites>')
    item=dict(source_id='junit',kind='junit',path=str(xml),sha256=file_hash(xml),source_sha256='a'*64)
    c=dict(schema='pi-observation-intake-v1',batch_id='observed-1',sources=[item],root=str(tmp_path/'observations'))
    p=write('request.json',c)
    return p,c,write


def test_check_is_readonly_and_diagnostics_are_hashed(source):
    p,c,_=source;before={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}
    report=observations.check(p)
    assert report['ready'] and report['counts']==dict(passed=1,failed=1,skipped=1)
    assert before=={str(f):f.read_bytes() for f in p.parent.rglob('*') if f.is_file()}
    result=observations.freeze(p);text=Path(result['report_path']).read_text();data=json.loads(text)
    assert 'private detail' not in text and 'ignore rules' not in text and data['automatic_execution'] is False
    assert data['observations'][0]['observation_id']=='tests.Case::bad'
    assert data['observations'][0]['diagnostic_sha256']


@pytest.mark.parametrize('xml',['<!DOCTYPE x [<!ENTITY b "boom">]><testsuite/>','<testsuite><testcase>','<evil/>','<testsuite><testcase name="x"><failure/><error/></testcase></testsuite>'])
def test_malformed_or_ambiguous_xml_rejected(source,xml):
    p,c,write=source;q=write('tests.xml',xml);c['sources'][0]['sha256']=file_hash(q);write(p.name,c)
    with pytest.raises(ValueError):observations.check(p)
    assert not Path(c['root']).exists()


def test_duplicate_nodes_are_preserved(source):
    p,c,write=source;q=write('tests.xml','<testsuite><testcase classname="C" name="x"/><testcase classname="C" name="x"><failure/></testcase></testsuite>');c['sources'][0]['sha256']=file_hash(q);write(p.name,c)
    v=observations.freeze(p);items=json.loads(Path(v['report_path']).read_text())['observations']
    assert len(items)==2 and items[0]['observation_id']==items[1]['observation_id'] and items[0]['occurrence']!=items[1]['occurrence']


def test_unknown_cycle_requires_reconciliation(source):
    p,c,write=source;q=write('cycle.json',dict(operation_id='maintenance:x',status='uncertain',schema_version=1,evidence=dict(mode='ACTUAL',released=False,next_action='reconcile')))
    c['sources']=[dict(source_id='cycle',kind='cycle',path=str(q),sha256=file_hash(q),source_sha256='a'*64)];write(p.name,c)
    v=observations.freeze(p);r=json.loads(Path(v['report_path']).read_text());assert r['requires_reconciliation'] and r['counts']['execution_unknown']==1


@pytest.mark.parametrize('available,confounders,value,expected',[('unknown',[],None,'unknown'),('measured',['mixed_versions'],.5,'confounded'),('measured',[],.5,'measured')])
def test_metrics_unknown_and_confounding_preserved(source,available,confounders,value,expected):
    p,c,write=source;q=write('metrics.json',dict(id='snapshot',evidence_domain='synthetic',availability=available,confounders=confounders,measurements=dict(errors=dict(value=value,availability=available,samples=5,direction='lower'))))
    c['sources']=[dict(source_id='metrics',kind='metrics',path=str(q),sha256=file_hash(q),source_sha256='a'*64)];write(p.name,c)
    v=observations.freeze(p);r=json.loads(Path(v['report_path']).read_text());assert r['observations'][0]['state']==expected and r['observations'][0]['value']==value


@pytest.mark.parametrize('kind',['hash','hardlink','overlap','unknown_field','duplicate_id'])
def test_invalid_manifest_or_role_rejected(source,kind):
    p,c,write=source
    if kind=='hash':c['sources'][0]['sha256']='0'*64
    if kind=='hardlink':Path(c['sources'][0]['path']).with_suffix('.alias').hardlink_to(c['sources'][0]['path'])
    if kind=='overlap':c['root']=str(p.parent)
    if kind=='unknown_field':c['approved']=True
    if kind=='duplicate_id':c['sources'].append(dict(c['sources'][0]))
    write(p.name,c)
    with pytest.raises(ValueError):observations.check(p)
