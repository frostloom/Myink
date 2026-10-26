"""Static source navigation is bounded observation, never execution authority."""
import hashlib,json
from pathlib import Path
import pytest


def locate(root,files,focus=''):
    from ops.pi.source_locator import source_index
    return source_index(root,files,focus)


def source(tmp_path,text,name='a.py'):
    root=tmp_path/'source';(root/'src').mkdir(parents=True,exist_ok=True)
    p=root/'src'/name;p.write_text(text);return root,p


def test_qualified_functions_decorators_async_and_nested_ranges(tmp_path):
    text='class Handler:\n    @decorator\n    async def run(self):\n        def inner():\n            return 1\n        return inner()\n\ndef outer():\n    return 2\n'
    root,p=source(tmp_path,text)
    row=locate(root,['src/a.py'])['files'][0]
    found={s['name']:(s['start_line'],s['end_line']) for s in row['symbols']}
    assert found=={'Handler.run':(2,6),'Handler.run.inner':(4,5),'outer':(8,9)}
    assert row['source_sha256']==hashlib.sha256(p.read_bytes()).hexdigest()
    assert row['line_count']==9 and row['omitted_symbols']==0


def test_only_declared_files_and_no_execution(tmp_path):
    marker=tmp_path/'executed'
    root,p=source(tmp_path,f'from pathlib import Path\nPath({str(marker)!r}).write_text("bad")\ndef allowed():\n    return 1\n')
    (root/'src/hidden.py').write_text('def secret():\n    pass\n')
    result=locate(root,['src/a.py'])
    assert [r['path'] for r in result['files']]==['src/a.py'] and not marker.exists()


@pytest.mark.parametrize('name,text,status',[
    ('broken.py','def broken(:\n','syntax_error'),
    ('notes.txt','def not_python():\n','not_python'),
    ('big.py','#'*(1024*1024+1),'too_large'),
],ids=['syntax','non-python','large'])
def test_unavailable_symbols_are_explicit_without_blocking_fix(tmp_path,name,text,status):
    root,p=source(tmp_path,text,name)
    row=locate(root,['src/'+name])['files'][0]
    assert row['status']==status and row['symbols']==[]
    assert row['source_sha256']==hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.mark.parametrize('target',['../outside.py','/tmp/outside.py','src/../outside.py'])
def test_path_escape_rejected(tmp_path,target):
    root,p=source(tmp_path,'pass\n')
    with pytest.raises(ValueError):locate(root,[target])


def test_linked_source_rejected(tmp_path):
    root,p=source(tmp_path,'pass\n');(root/'src/link.py').symlink_to(p)
    with pytest.raises(ValueError):locate(root,['src/link.py'])


def test_budget_is_explicit_and_plan_target_prioritized(tmp_path):
    text=''.join(f'def helper_{n}():\n    return {n}\n' for n in range(300))+'def target_fix():\n    return 0\n'
    root,p=source(tmp_path,text)
    result=locate(root,['src/a.py'],'Only change target_fix')
    row=result['files'][0]
    assert any(s['name']=='target_fix' for s in row['symbols']) and row['omitted_symbols']>0
    assert len(json.dumps(result,ensure_ascii=True,separators=(',',':')).encode())<=8192


@pytest.mark.parametrize('dense',[False,True])
def test_launcher_injects_source_map_and_persists_same_bytes(config_file,monkeypatch,dense):
    from ops.pi import development_launcher as launcher
    from ops.pi.development_inputs import read_json
    cp,c=config_file;observed={}
    if dense:
        from ops.pi.development_inputs import tree_hash, authorization_hash, file_hash
        (Path(c['source_path'])/'src/a.py').write_text(''.join(
            f'def moderately_long_helper_name_{n}():\n    return {n}\n' for n in range(300)))
        c['source_sha256']=tree_hash(Path(c['source_path']))
        review=read_json(c['review_path'])
        review.update(base=c['source_sha256'],authorization_sha256=authorization_hash(c))
        Path(c['review_path']).write_text(json.dumps(review));c['review_sha256']=file_hash(c['review_path'])
        cp.write_text(json.dumps(c))
    class Host:
        owned={};pending={};operation_id='synthetic-locator'
        def reconcile(self):pass
        def _daemon(self):pass
        def _call(self,*a):return type('Output',(),{'stdout':''})()
    monkeypatch.setattr(launcher,'_host',lambda *a:Host())
    def capture(host,config,initial,*args):
        observed.update(initial)
        raise RuntimeError('sentinel after prompt capture; no provider invoked')
    monkeypatch.setattr(launcher,'_exchange',capture)
    result=launcher.execute(cp,transport=lambda *a:None)
    assert result['policy_restored'] and result['original_history_unchanged'] and result['new_attempts']==0
    prompt_json=observed['prompt'].split('\n')[-1]
    payload=json.loads(prompt_json)
    fragment=prompt_json.split('"source_index":',1)[1].lstrip()
    _,end=json.JSONDecoder().raw_decode(fragment)
    assert len(fragment[:end].encode('ascii'))<=8192
    assert payload['source_index']['files'][0]['path']=='src/a.py'
    assert read_json(Path(c['root'])/'source-index-private.json')==payload['source_index']


from ops.pi.tests.test_development_inputs import config_file
