"""合成长篇真实模型评测：全流程生成 → 人工拒绝 → 修订复审。只写隔离库。"""
from __future__ import annotations
import argparse
import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from langgraph.checkpoint.memory import InMemorySaver
from myink.config import settings
from myink.db import new_session, tenant_session
from myink.models import Project, ProjectSettings, Character, Chapter, MemoryCandidate, AgentRun, User
from myink.workflow.chapter_graph import build_chapter_graph
from myink.workflow.review import resolve_review
from myink.api.routes_candidates import reject_candidate, RejectCandidateIn

p=argparse.ArgumentParser()
p.add_argument('--live',action='store_true',required=True)
p.add_argument('--output',default='docs/evaluations/workflow-recovery.json')
p.add_argument('--capture-artifacts', action='store_true', help='保存完整阶段状态、正文及落库内容')
p.add_argument('--local-deepseek', action='store_true', help='在隔离库为合成账号配置本地 DEEPSEEK_API_KEY')
a=p.parse_args()
if ':15432/' not in settings.database_url:
    raise SystemExit('只允许写入隔离测试数据库 15432')
started_at = datetime.now(timezone.utc).isoformat()
instruction = '暴雨导致山间观测站停电。林川左膝扭伤，与许宁协作检查供电，最后找到漏水的接线盒。全章仅两名人物，避免另建人物。'
constraints = ['故事发生在现实世界，没有超能力；人物伤势须有合理恢复过程。']
with new_session() as db:
    user=db.query(User).first()
    if user is None:
        raise SystemExit('隔离库需要先 init --seed')
    if a.local_deepseek:
        from myink.providers.credentials import encrypt_api_key
        from myink.providers.connections import pack_model_settings
        from myink.providers.base import CONFIGURABLE_ROLES
        key = os.getenv('DEEPSEEK_API_KEY', '').strip()
        if not key:
            raise SystemExit('本地未配置 DEEPSEEK_API_KEY')
        user.environment = {'models': pack_model_settings(
            {role: 'custom:demo' for role in CONFIGURABLE_ROLES},
            {'demo': {'protocol': 'openai', 'base_url': 'https://api.deepseek.com',
                      'model': 'deepseek-v4-flash', 'api_key_encrypted': encrypt_api_key(key)}})}
    project=Project(user_id=user.id,title='合成评测：雨夜检修',genre='现实',target_words=3000)
    db.add(project);db.flush();pid=str(project.id);db.commit()
with tenant_session(pid) as db:
    db.add(ProjectSettings(project_id=pid,world_rules={},hard_constraints=constraints,style_profile={}))
    for name in ('林川','许宁'):
        db.add(Character(project_id=pid,name=name,realm_cap='普通人',personality='谨慎负责的检修员'))
tid=str(uuid.uuid4());graph=build_chapter_graph(checkpointer=InMemorySaver())
result=graph.invoke({'project_id':pid,'chapter_seq':1,'task_id':tid,
    'user_instruction':instruction},
    config={'configurable':{'thread_id':tid},'recursion_limit':64})
if result.get('error'):
    raise RuntimeError(result['error'])
first={'chars':len(result.get('draft') or ''),'needs_review':result.get('needs_review')}
artifact_keys = ('characters', 'context', 'cast', 'plan', 'draft', 'candidates', 'report',
                 'audit_verdict', 'persisted', 'needs_review', 'error', 'tool_trace')
initial_artifacts = {key: result.get(key) for key in artifact_keys}
# 人为植入一个明确违反现实设定的结尾，验证拒绝会实际改正文。
bad='林川忽然获得了瞬间移动的超能力，眨眼就到了十公里外。'
result['draft'] += '\n'+bad
rejected_draft = result['draft']
reason = '现实题材不允许瞬间移动；用人物实际检修动作推进。'
with tenant_session(pid) as db:
    ch=db.query(Chapter).filter_by(chapter_seq=1).one();ch.status='awaiting_review'
    cand=MemoryCandidate(project_id=pid,source_chapter=1,kind='fact',payload={'content':bad})
    db.add(cand);db.flush();cid=str(cand.id)
reject_candidate(pid,cid,RejectCandidateIn(reason=reason))
print('初稿已生成；进入人工拒绝后的修订复审。', flush=True)
result=resolve_review(graph,result,task_id=tid)
with tenant_session(pid) as db:
    runs=db.query(AgentRun).filter_by(task_id=tid).order_by(AgentRun.id).all()
    report={'fixture':'纯合成现实题材，不含用户小说内容','initial':first,
            'final_chars':len(result.get('draft') or ''),'error':result.get('error'),
            'needs_review':result.get('needs_review'),'bad_sentence_removed':bad not in result.get('draft',''),
            'runs':[{'node':r.node,'input_tokens':r.input_tokens,'output_tokens':r.output_tokens,
                     'model_id':r.model_id,'duration_ms':r.duration_ms,'cost_est':r.cost_est,
                     'error':r.error,'detail':r.detail} for r in runs]}
    if a.capture_artifacts:
        from myink.models import Fact, Event, CharacterState, ChapterVersion
        def rows(model):
            return [{col.name: getattr(row, col.name) for col in model.__table__.columns}
                    for row in db.query(model).filter_by(project_id=uuid.UUID(pid)).all()]
        report['artifacts'] = {
            'started_at': started_at, 'finished_at': datetime.now(timezone.utc).isoformat(),
            'task_id':tid, 'project_id':pid, 'instruction':instruction, 'constraints':constraints,
            'initial':initial_artifacts, 'human_feedback':{'injected_sentence':bad,
                'reason':reason, 'rejected_draft':rejected_draft, 'source':'评测脚本人为注入，不是模型自然生成'},
            'final':{key:result.get(key) for key in artifact_keys},
            'database':{model.__tablename__:rows(model) for model in
                (Chapter, ChapterVersion, MemoryCandidate, Fact, Event, CharacterState)},
            'limitations':['仅一个合成案例；embedding 关闭，不能证明语义召回质量',
                            '成本为应用估算，不是供应商账单；遥测 detail 可能有截断标记']}
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('runs','artifacts')},ensure_ascii=False))
if result.get('error') or not report['bad_sentence_removed']:
    raise SystemExit(1)
