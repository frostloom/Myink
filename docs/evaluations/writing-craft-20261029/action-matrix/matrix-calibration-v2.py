import os,sys,base64,json,logging
sys.path.insert(0,'/eval')
logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from chapter_checks import draft_segments
p=json.loads(base64.b64decode(os.environ['MATRIX_CALIBRATION']))
conn=resolve_connection('audit',{},load_configuration(),tier='normal')
provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def hook(req):
 global count
 if count>=6:raise RuntimeError('Six-request matrix cap reached')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(hook)
for c in p['cases']:
 mode=c['mode'];segments=draft_segments(c['text'])
 shared='逐人逐动作填表，不做章节好坏或整体通过判断。actors×actions每个格子都必须独立填写，禁止跳格或用一人的动作代替另一人。共同活动不要求每人独自操作全过程；指出、翻动、对照、确认共同构成核对，但一人坐下不能推出另一人坐下。每个输出字段actor_id和action_id从0开始，严格整数。返回JSON:{"cells":[{"actor_id":0,"action_id":0,"status":"状态","evidence_ids":[0],"reason":"简短依据"}]}。证据编号只能选对应segments，不得编造文字；肯定状态须有证据。'
 instruction=shared+('只读原要求，判断它要求哪个人物完成哪个动作。status=required|forbidden|not_required|uncertain。原要求禁止此肯定命题时用forbidden；没有要求它发生不等于禁止发生。不看正文、不看拆分结果。' if mode=='requirements' else '只读正文，提取已发生的动作事实。status=observed|not_observed|uncertain。不读计划或期望，不因另一人做了或剧情合理就替该人物补做。允许明确同义表达，不要求正文出现动作原词。')
 response=provider.generate([{'role':'system','content':instruction},{'role':'user','content':json.dumps({'actors':c['actors'],'actions':c['actions'],'segments':[{'id':i,'text':t} for i,t in enumerate(segments)]},ensure_ascii=False)}],model_id=conn['model'],temperature=0,json_mode=True,max_tokens=1800,disable_thinking=True)
 if response.error or response.finish_reason=='length':raise RuntimeError('Matrix provider failure or truncation')
 data=_parse_json(response.content);rows=data.get('cells',[])
 expected_pairs={(i,j) for i in range(len(c['actors'])) for j in range(len(c['actions']))}
 valid=len(rows)==len(expected_pairs) and all(type(r.get('actor_id')) is int and type(r.get('action_id')) is int for r in rows) and {(r['actor_id'],r['action_id']) for r in rows}==expected_pairs
 allowed=['required','forbidden','not_required','uncertain'] if mode=='requirements' else ['observed','not_observed','uncertain']
 for r in rows:
  ids=r.get('evidence_ids',[])
  valid=valid and r.get('status') in allowed and isinstance(ids,list) and all(type(i) is int and 0<=i<len(segments) for i in ids)
  if r.get('status') in ['required','forbidden','observed'] and not ids:valid=False
 actual=[r['status'] for r in sorted(rows,key=lambda r:(r['actor_id'],r['action_id']))] if valid else []
 emit({'event':'result','id':c['id'],'mode':mode,'valid':valid,'correct':actual==c['expected'],'expected':c['expected'],'actual':actual,'response':data,'input_tokens':response.input_tokens,'output_tokens':response.output_tokens})
emit({'event':'complete','attempts':count})
