"""Platform gateway boundary with HTTP transport replaced, no real calls."""
import hashlib
import importlib
import importlib.util
import json

import httpx
import pytest


def api():
    assert importlib.util.find_spec('myink.evaluation.platform_call') is not None, 'C16 platform adapter missing'
    return importlib.import_module('myink.evaluation.platform_call')


def config():
    return {'model':'deepseek-v4.1-flash','protocol':'anthropic','base_url':'http://127.0.0.1:8088',
       'budget_scope_id':'local-trial-1','_api_key':'scoped-fixture','pricing_id':'a'*64,
       'prices':{'input':'2','output':'8','cache_read':'0.2','cache_write':None},
       'max_tokens':100,'temperature':0.1,'timeout_seconds':2,'json_mode':False}


def transport(monkeypatch,data,status=200):
    calls=[];real=httpx.Client
    def handle(request):calls.append(request);return httpx.Response(status,json=data)
    class Client(real):
        def __init__(self,**kwargs):
            kwargs.pop('transport',None)
            super().__init__(transport=httpx.MockTransport(handle),**kwargs)
    monkeypatch.setattr(httpx,'Client',Client)
    return calls


def test_platform_anthropic_without_deepseek_key(monkeypatch):
    module=api();monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    calls=transport(monkeypatch,{'id':'msg-1','model':'actual-model','content':[{'type':'text','text':'正文'}],
      'usage':{'input_tokens':7,'output_tokens':9,'cache_read_input_tokens':0,'cache_creation_input_tokens':0},'stop_reason':'end_turn'})
    out=module.platform_call([{'role':'system','content':'instruction'},{'role':'user','content':'write'}],config())
    assert len(calls)==1 and calls[0].url.path=='/v1/messages'
    assert calls[0].headers['X-Pi-Scope']=='local-trial-1'
    assert out['protocol']=='anthropic' and out['model_id']=='actual-model'
    assert out['raw_output']=='正文' and out['accounting_status']=='unreconciled'
    assert out['cost_est'] is None


def test_no_implicit_official_price(monkeypatch):
    module=api();bad=config();bad.pop('prices');calls=transport(monkeypatch,{})
    with pytest.raises(ValueError,match='pric'):module.platform_call([{'role':'user','content':'x'}],bad)
    assert calls==[]
    bad=config();bad.pop('pricing_id')
    with pytest.raises(ValueError,match='pric'):module.platform_call([{'role':'user','content':'x'}],bad)


def test_protocol_tool_thinking_usage_preserved(monkeypatch):
    module=api();data={'id':'msg-2','model':'actual-model','stop_reason':'tool_use',
      'content':[{'type':'thinking','thinking':'分析'},{'type':'text','text':'<think>内部</think>正文'},
                 {'type':'tool_use','id':'t1','name':'read_source','input':{'paths':['src/x.py']}}],
      'usage':{'input_tokens':8,'output_tokens':12,'cache_read_input_tokens':3,'cache_creation_input_tokens':0,'unknown_fee':1}}
    calls=transport(monkeypatch,data)
    out=module.platform_call([{'role':'user','content':'x'}],config())
    sent=json.loads(calls[0].content)
    assert sent['thinking']=={'type':'disabled'} and sent['stream'] is False
    assert out['raw_response']['content'][0]['thinking']=='分析'
    assert out['tool_calls'][0]['arguments']=={'paths':['src/x.py']} and out['finish_reason']=='tool_use'
    assert out['usage']==data['usage'] and out['raw_output']=='正文'
    assert out['cost_status']=='unknown' and out['cost_est'] is None
    assert out['response_projection']['normalized'] is True


@pytest.mark.parametrize('url',['https://upstream.example','http://localhost:8088','http://127.0.0.1:8088/?key=x'])
def test_direct_upstream_and_nonfixed_proxy_refused(url,monkeypatch):
    module=api();bad=config();bad['base_url']=url;calls=transport(monkeypatch,{})
    with pytest.raises(ValueError,match='gateway'):module.platform_call([{'role':'user','content':'x'}],bad)
    assert calls==[]


def test_missing_usage_actual_model_and_http_failure_are_not_zero_or_retried(monkeypatch):
    module=api();calls=transport(monkeypatch,{'error':'scoped-fixture'},status=429)
    out=module.platform_call([{'role':'user','content':'x'}],config())
    assert len(calls)==1 and out['execution']=='budget_stopped' and out['cost_est'] is None
    assert 'scoped-fixture' not in json.dumps(out)
    calls=transport(monkeypatch,{'content':[{'type':'text','text':'x'}]})
    out=module.platform_call([{'role':'user','content':'x'}],config())
    assert out['model_id'] is None and out['input_tokens'] is None and out['output_tokens'] is None
    assert out['cost_status']=='unknown'


def test_only_verified_canonical_receipt_supplies_cost(monkeypatch):
    module=api();data={'id':'msg-3','model':'actual-model','content':[{'type':'text','text':'x'}],
      'usage':{'input_tokens':7,'output_tokens':9,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}
    transport(monkeypatch,data);cfg=config()
    def resolver(identity):
        return {**identity,'attempt_id':'a1','ledger_event_verified':True,'status':'done',
                'usage_known':True,'charged_microyuan':86}
    cfg['_accounting_resolver']=resolver
    out=module.platform_call([{'role':'user','content':'x'}],cfg)
    assert out['accounting_status']=='reconciled' and out['cost_est']==0.000086
    cfg['_accounting_resolver']=lambda identity:{**resolver(identity),'request_sha256':'f'*64}
    out=module.platform_call([{'role':'user','content':'x'}],cfg)
    assert out['accounting_status']=='unreconciled' and out['cost_est'] is None


def test_platform_config_reads_only_selected_four_environment_fields():
    module=api();env={'PLATFORM_MODEL_API_KEY':'scoped-fixture','PLATFORM_MODEL_BASE_URL':'http://127.0.0.1:8088',
       'PLATFORM_MODEL_NAME':'deepseek-v4.1-flash','PLATFORM_MODEL_PROTOCOL':'anthropic','DEEPSEEK_API_KEY':'do-not-use'}
    result=module.platform_config(config(),environ=env)
    assert result['_api_key']=='scoped-fixture' and result['model']=='deepseek-v4.1-flash'
    assert 'do-not-use' not in json.dumps(result)
    with pytest.raises(ValueError):module.platform_config(config(),environ={**env,'PLATFORM_MODEL_PROTOCOL':'openai'})


def test_comparison_platform_provider_does_not_create_legacy_budget(tmp_path):
    from myink.evaluation.comparison import BudgetedProvider
    calls=[]
    def call(messages,cfg):
        calls.append(cfg)
        return {'execution':'completed','raw_output':'body','model_id':'actual-model',
                'input_tokens':None,'output_tokens':None,'cost_est':None,'cost_status':'unknown',
                'accounting_status':'unreconciled','actual_http_attempts':1}
    cfg=config() | {'transport':'platform'}
    provider=BudgetedProvider(tmp_path,None,cfg,call=call)
    response=provider.generate([{'role':'user','content':'x'}],model_id='ignored',max_tokens=999)
    assert response.content=='body' and response.model_id=='actual-model'
    assert response.cost_est is None and not response.usage_complete and calls[0]['max_tokens']==100
    saved=json.loads((tmp_path/'requests/0001/result.json').read_text(encoding='utf-8'))
    assert saved['cost_est'] is None and 'scoped-fixture' not in json.dumps(saved)


def test_cli_platform_plan_requires_explicit_transport_and_keeps_secrets_out(tmp_path,monkeypatch,capsys):
    import sys
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('c16_cli',Path('scripts/evaluate.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cfg={k:v for k,v in config().items() if not k.startswith('_') and k not in ('protocol','base_url','model')}
    path=tmp_path/'config.json';path.write_text(json.dumps(cfg),encoding='utf-8')
    for name,value in {'API_KEY':'scoped-fixture','BASE_URL':'http://127.0.0.1:8088','NAME':'deepseek-v4.1-flash','PROTOCOL':'anthropic'}.items():
        monkeypatch.setenv('PLATFORM_MODEL_'+name,value)
    monkeypatch.setattr(sys,'argv',['evaluate.py','plan','--transport','platform','--config',str(path)])
    assert module.main()==0
    output=capsys.readouterr().out
    assert 'canonical local-trial-1' in output and 'scoped-fixture' not in output
    assert json.loads(output)['network_calls']==0



def test_platform_audit_artifacts_read_back_with_existing_case_and_result_hashes(tmp_path):
    from test_evaluation import case
    module=api();cfg=config() | {'transport':'platform'}
    def call(messages,cfg):
        return {'execution':'completed','raw_output':json.dumps({'verdict':'pass','findings':[],'reasons':[]}),
                'model_id':'actual-model','usage':None,'cost_est':None,'cost_status':'unknown','actual_http_attempts':1}
    directory=tmp_path/'run'
    module.run_platform_cases([case(False)],directory,cfg,live=True,call=call)
    spec=importlib.util.spec_from_file_location('c16_readback','scripts/evaluate.py')
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    cases,rows=cli.load_run(directory)
    assert len(cases)==len(rows)==1 and rows[0]['cost_est'] is None
    assert cli.score_run(directory)['operations']['cost']['value'] is None


def test_platform_audit_timeout_keeps_planned_remaining_slot(tmp_path):
    from test_evaluation import case
    module=api();count=0
    def call(messages,cfg):
        nonlocal count
        count+=1
        if count==1:raise TimeoutError('fixture')
        return {'execution':'completed','raw_output':'{}','model_id':'m','cost_est':None,'cost_status':'unknown','actual_http_attempts':1}
    rows=module.run_platform_cases([case(True),case(False)],tmp_path/'run',config(),live=True,call=call)
    assert len(rows)==2 and rows[0]['execution']=='timeout' and rows[1]['execution']=='completed'


@pytest.mark.parametrize('cost', [None, 'missing', 0, 0.25])
def test_fixround1_comparison_consumer_retains_all_planned_unknown_cost_slots(tmp_path,monkeypatch,cost):
    """Run the production loop; replace only unavailable provider/DB/graph boundaries.

    Compile the real run function without importing its service-bearing module.
    No SQL, graph/business capture or HTTP boundary is actually executed.
    """
    import ast
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace
    from datetime import datetime, timezone
    import secrets
    import time
    import uuid
    import html
    from unittest.mock import patch
    from myink.evaluation.comparison import ComparisonCase, blind_bundle, direct_context
    from myink.evaluation.cases import json_text
    path=Path('scripts/evaluate-comparison.py')
    tree=ast.parse(path.read_text(encoding='utf-8'))
    selected=ast.Module(body=[node for node in tree.body if isinstance(node,ast.FunctionDef)
                             and node.name in ('normalized','run')],type_ignores=[])
    class Statement:
        def where(self,*args):return self
        def limit(self,*args):return self
    class Session:
        def execute(self,*args):return self
        def scalar_one(self):return 'fixed-owner'
        def scalar_one_or_none(self):return None
        def add(self,*args):pass
        def commit(self):pass
        def flush(self):pass
    class Row:
        id='id';project_id='pid';chapter_seq=21
        def __init__(self,**kwargs):self.__dict__.update(kwargs)
    class Provider:
        def __init__(self,*args):self.records=[];self.active={}
        def generate(self,*args,**kwargs):
            self.records.append({} if cost=='missing' else {'cost_est':cost})
            return SimpleNamespace(content='fixed text',error=None,finish_reason='stop')
    def graph():
        def stream(*args,**kwargs):
            # The graph/provider boundary returns a fixed response and one unknown-cost receipt.
            providers[0].generate([])
            return iter([{'draft':'fixed text'}])
        return SimpleNamespace(stream=stream)
    providers=[]
    def provider(*args):
        result=Provider();providers.append(result);return result
    module=api();monkeypatch.setattr(module,'platform_config',lambda cfg:cfg)
    ns=dict(__file__=str(path.resolve()),Path=Path,json=json,hashlib=hashlib,datetime=datetime,
      timezone=timezone,time=time,uuid=uuid,secrets=secrets,html=html,ExitStack=__import__('contextlib').ExitStack,
      patch=patch,settings=SimpleNamespace(embed_enabled=False),ComparisonCase=ComparisonCase,
      require_isolated_database=lambda:{'boundary':'fixed_no_services'},BudgetedProvider=provider,
      provenance=lambda *args:{'source_hashes':{}},json_text=json_text,
      new_session=lambda:nullcontext(Session()),tenant_session=lambda *args:nullcontext(Session()),
      select=lambda *args:Statement(),delete=lambda *args:Statement(),direct_context=direct_context,
      prompts=SimpleNamespace(write_messages=lambda *args,**kwargs:[]),
      nodes=SimpleNamespace(_WRITE_TOKENS_PER_CHAR=2,make_chain=None),
      ledger_l2=SimpleNamespace(make_chain=None),recall=SimpleNamespace(_hybrid_recall=None),
      FallbackChain=lambda *args,**kwargs:None,InMemorySaver=lambda:None,
      build_chapter_graph=lambda **kwargs:graph(),blind_bundle=blind_bundle,
      save_manifest=lambda path,data:(path/'manifest.json').write_text(json_text(data),encoding='utf-8'))
    ns.update({name:Row for name in ('User','Project','ProjectSettings','Character','Alias','Fact','Event','Chapter','AgentRun')})
    exec(compile(selected,str(path),'exec'),ns)
    case={'id':'fixed','characters':['Lin'],'history':[],'previous_tail':'old chapter',
          'constraints':['plain setting'],'instruction':'continue','target_words':80}
    directory=tmp_path/'comparison'
    result=ns['run'](directory,[case],live=True,max_calls=1,max_cost=1,
                      platform_config=config() | {'transport':'platform'})
    rows=json.loads((directory/'results.json').read_text(encoding='utf-8'))
    assert result['planned_outputs']==6 and result['completed_outputs']==6 and len(rows)==6
    assert {(r['variant'],r['repetition']) for r in rows}=={(v,n) for v in ('direct','full','no_hybrid') for n in (1,2)}
    assert all(r['estimated_cost_yuan']==(None if cost in (None,'missing') else cost) for r in rows)
    assert result['actual_requests'] is None and result['cost_reserved_or_estimated_yuan'] is None
