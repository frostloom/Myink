"""Exercise real prompt -> model tool request -> frozen DB content -> final answer."""
import copy
import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from myink import writing_resources as svc
from myink.models.platform import PlatformConfiguration
from myink.models.writing_resource import WritingResource, WritingResourceRevision, WritingResourcePublication, ProjectWritingResources
from myink.providers.base import ModelResponse
from myink.workflow import nodes
from myink.writing_resource_runtime import bind_resources


class ReadingChain:
    chain = []

    def __init__(self, final='{}'):
        self.calls = []
        self.final = final

    def generate(self, messages, **kwargs):
        self.calls.append((copy.deepcopy(messages), kwargs))
        names = [t['function']['name'] for t in kwargs.get('tools') or []]
        if not names:
            return ModelResponse(content='TOOLS_NOT_AVAILABLE', model_id='fake')
        replies = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        if not replies:
            arguments = {}
        elif len(replies) == 1:
            arguments = {'path': replies[0]['files'][0]['path']}
        else:
            assert replies[-1]['content'] == 'FROZEN_CHARACTER_METHOD'
            return ModelResponse(content=self.final, model_id='fake')
        return ModelResponse(content='', model_id='fake', tool_calls=[{
            'id': f'lookup-{len(replies)}', 'name': 'read_genre_reference', 'arguments': arguments}])


@pytest.fixture
def library():
    engine = create_engine('sqlite://')
    for model in (PlatformConfiguration, WritingResource, WritingResourceRevision, WritingResourcePublication, ProjectWritingResources):
        model.__table__.create(engine)
    with Session(engine) as db:
        row = svc.create_resource(db, {'name':'人物设计写法', 'kind':'reference', 'source':'test',
            'body': {'files':[{'path':'characters.md','content':'FROZEN_CHARACTER_METHOD'}]}})
        svc.publish(db,row.id,0,'')
        snapshot = svc.capture_task_resources(db,None)
        svc.update_resource(db,row.id,1,{'body':{'files':[{'path':'characters.md','content':'NEW_PUBLICATION'}]}})
        svc.publish(db,row.id,2,'')
        with bind_resources(snapshot):
            yield db


@pytest.mark.parametrize('function,kwargs,final', [
    ('generate_book_setup', {'genre':'现实','premise':'设计可信的人物关系'}, '{}'),
    ('generate_book_outline', {'genre':'现实','premise':'设计可信的人物关系'}, '{"volumes":[]}'),
    ('generate_short_plan', {'genre':'现实','premise':'设计可信的人物关系','chapter_count':1,'chars_per_chapter':1000}, '{"volumes":[{"chapters":[]}]}'),
    ('review_short_plan', {'plan':{},'chapter_count':1}, '{"verdict":"pass"}'),
])
def test_planning_entry_really_executes_reference_requests(library, monkeypatch, function, kwargs, final):
    from myink import book_setup
    chain = ReadingChain(final)
    traces = []
    monkeypatch.setattr('myink.providers.make_chain', lambda *args,**kwargs: chain)
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs: traces.append(kwargs))
    result = getattr(book_setup,function)(**kwargs, db=library, project_id=str(uuid.uuid4()))
    assert len(chain.calls) == 3, result
    assert all(c[1]['tools'][0]['function']['name']=='read_genre_reference' for c in chain.calls)
    assert len(traces) == 3
    assert traces[-1]['detail']['tool_trace'][-1]['tool']=='read_genre_reference'


def test_node_llm_supplies_reference_tool_for_planner(library, monkeypatch):
    chain=ReadingChain()
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    monkeypatch.setattr(nodes,'record_snapshot',lambda *args,**kwargs:None)
    response, trace = nodes._llm(library, {'project_id':str(uuid.uuid4())}, 'plan_cast','Planner',chain,
                                 [{'role':'system','content':'规划人物出场'},{'role':'user','content':'设计人物'}])
    assert response.content=='{}'
    assert len(trace)==2

@pytest.mark.parametrize('node,role,json_mode', [('short_write','Writer',False),('short_continue','Writer',False),('short_review','Audit',True),('short_revise','Writer',False)])
def test_short_story_entry_executes_library_without_long_novel_checks(library,monkeypatch,node,role,json_mode):
    from myink.workflow import short_runner
    chain=ReadingChain('FINAL')
    records=[]
    monkeypatch.setattr(short_runner,'make_chain',lambda *args,**kwargs:chain)
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:records.append(kwargs))
    response=short_runner._call(library,str(uuid.uuid4()),str(uuid.uuid4()),node=node,role=role,
        messages=[{'role':'system','content':'创作'},{'role':'user','content':'构造可信的人物关系'}],max_tokens=1000,json_mode=json_mode)
    assert response.content=='FINAL'
    assert len(chain.calls)==3
    assert len(records)==3
    assert records[-1]['detail']['tool_trace'][-1]['tool']=='read_genre_reference'


def test_account_creation_admits_each_tool_round(library, monkeypatch):
    from myink import book_setup
    chain=ReadingChain('{"reply":"完成","card":{}}')
    admitted=[]
    monkeypatch.setattr('myink.providers.make_user_chain',lambda *args,**kwargs:chain)
    def admit(chain,*,user_id,messages,**options):
        admitted.append(user_id)
        return chain.generate(messages,**options)
    monkeypatch.setattr('myink.model_admission.generate_account_model',admit)
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    uid=uuid.uuid4()
    result=book_setup.generate_short_creation_turn([],{},user_id=uid,db=library)
    assert result[0]=='完成'
    assert admitted==[uid,uid,uid]


def test_reference_only_loop_rejects_unadvertised_project_tools(library,monkeypatch):
    from myink.workflow.reference_access import generate_with_references
    chain=ReadingChain()
    def generate(messages,**options):
        if any(m['role']=='tool' for m in messages):
            assert 'UNKNOWN_TOOL' in next(m['content'] for m in messages if m['role']=='tool')
            return ModelResponse(content='{}',model_id='fake')
        return ModelResponse(content='',model_id='fake',tool_calls=[{'id':'bad','name':'inspect_character','arguments':{'name':'他人的角色'}}])
    chain.generate=generate
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    monkeypatch.setattr(nodes,'execute_tool',lambda *args:pytest.fail('unadvertised tool must not execute'))
    response,trace=generate_with_references(library,None,'creation','Planner',chain,[],user_id=uuid.uuid4(),json_mode=True,max_tokens=1000)
    assert response.content=='{}'
    assert 'UNKNOWN_TOOL' in trace[0]['result']


def test_volume_audit_entry_can_consult_frozen_references(library,monkeypatch):
    from myink.validation import global_audit
    chain=ReadingChain('{"findings":[]}')
    monkeypatch.setattr(global_audit,'make_chain',lambda *args,**kwargs:chain)
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    result,error=global_audit._run_kind_llm(library,str(uuid.uuid4()),None,(1,10),
        [{'role':'system','content':'审核卷规划'},{'role':'user','content':'判断情节推进'}],detail={})
    assert error is None
    assert result==[]
    assert len(chain.calls)==3


def test_final_tool_round_preserves_thinking_option_and_output_protocol(library,monkeypatch):
    from myink.workflow.reference_access import generate_with_references
    from dataclasses import replace
    monkeypatch.setattr('myink.workflow.reference_access.reference_tools',lambda:[{'type':'function','function':{'name':'read_genre_reference'}}])
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    monkeypatch.setattr('myink.config.settings',replace(nodes.settings,max_tool_calls=1))
    options=[]
    class Chain:
        chain=[]
        def generate(self,messages,**kwargs):
            options.append(kwargs)
            if kwargs.get('tools'):
                return ModelResponse(content='',model_id='fake',tool_calls=[{'id':'one','name':'read_genre_reference','arguments':{}}])
            assert kwargs.get('disable_thinking') is True
            return ModelResponse(content='{"complete":true}',model_id='fake')
    response,trace=generate_with_references(library,str(uuid.uuid4()),'book_setup','Planner',Chain(),[],max_tokens=100,
                                           json_mode=True,disable_thinking=True)
    assert response.content=='{"complete":true}'
    assert len(options)==2 and len(trace)==1


def test_model_can_finish_without_unnecessary_lookup(library,monkeypatch):
    from myink.workflow.reference_access import generate_with_references
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    calls=[]
    class Chain:
        chain=[]
        def generate(self,messages,**kwargs):
            calls.append(kwargs)
            return ModelResponse(content='直接完成局部修订',model_id='fake')
    response,trace=generate_with_references(library,str(uuid.uuid4()),'patch','Writer',Chain(),[],max_tokens=100,json_mode=False)
    assert response.content=='直接完成局部修订'
    assert len(calls)==1 and trace==[]


def test_final_round_rejects_tool_requests_instead_of_publishing_process_text(library,monkeypatch):
    from dataclasses import replace
    from myink.workflow.reference_access import generate_with_references
    monkeypatch.setattr('myink.config.settings',replace(nodes.settings,max_tool_calls=0))
    class Chain:
        chain=[]
        def generate(self,messages,**kwargs):
            return ModelResponse(content='I will check another reference',model_id='fake',tool_calls=[
                {'id':'late','name':'read_genre_reference','arguments':{'path':'characters.md'}}])
    monkeypatch.setattr(nodes,'record_run',lambda *args,**kwargs:None)
    response,trace=generate_with_references(library,str(uuid.uuid4()),'short_write','Writer',Chain(),[],max_tokens=100,json_mode=False)
    assert response.error and 'TOOL_PROTOCOL_ERROR' in response.error
    assert response.content=='' and not response.tool_calls
    assert trace==[]


def test_explicit_empty_tools_disables_further_provider_tool_use():
    from myink.providers.deepseek import DeepSeekProvider
    from myink.providers.anthropic import AnthropicProvider
    args=dict(model_id='test',max_tokens=100,temperature=None,json_mode=True,tools=[])
    assert DeepSeekProvider._request_kwargs([],disable_thinking=True,**args)['tool_choice']=='none'
    anthropic=object.__new__(AnthropicProvider)
    assert anthropic._payload([],stream=False,**args)['tool_choice']=={'type':'none'}


def test_manual_audit_captures_published_library_before_building_prompts(library,monkeypatch):
    from myink.validation import global_audit
    from myink.writing_resource_runtime import current_resources
    seen=[]
    def assemble(*args):
        snapshot=current_resources()
        assert snapshot and snapshot['reference_library']
        seen.append(snapshot['reference_library'][0]['version'])
        return {'volumes':[]}
    monkeypatch.setattr(global_audit,'assemble_volume_context',assemble)
    monkeypatch.setattr('myink.workflow.prompts.global_audit_messages',lambda *args:[])
    monkeypatch.setattr(global_audit,'_run_kind_llm',lambda *args,**kwargs:([],None))
    monkeypatch.setattr(global_audit,'normalize_and_verify_findings',lambda *args:[])
    monkeypatch.setattr(global_audit,'record_report',lambda *args,**kwargs:{'status':'completed'})
    with bind_resources(None):
        assert global_audit.run_global_audit(library,str(uuid.uuid4()),(1,2))['status']=='completed'
        assert current_resources() is None
    assert seen==[2]  # New manual admission captures the latest published version.


def test_optional_database_argument_still_reads_frozen_platform_version(library,monkeypatch):
    from contextlib import contextmanager
    from myink.writing_resource_runtime import reference_read
    opened=[]
    @contextmanager
    def read_session():
        opened.append(True)
        yield library
    monkeypatch.setattr('myink.db.new_session',read_session)
    assert reference_read('characters.md')['content']=='FROZEN_CHARACTER_METHOD'
    assert opened==[True]


def test_reference_hint_supplies_exact_frozen_paths_without_loading_bodies(library):
    from myink.writing_resource_runtime import automatic_reference_messages
    content='\n'.join(m['content'] for m in automatic_reference_messages('writer'))
    assert 'characters.md' in content
    assert 'FROZEN_CHARACTER_METHOD' not in content
    assert 'NEW_PUBLICATION' not in content
