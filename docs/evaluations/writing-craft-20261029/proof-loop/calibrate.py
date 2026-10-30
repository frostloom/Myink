import base64,json,logging,os,time
logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
samples=json.loads(base64.b64decode(os.environ['PROOF_CALIBRATION']))
connection=resolve_connection('audit',{},load_configuration(),tier='normal')
provider=_chain_from_override(connection,False).providers[0]
attempts=0
cap=len(samples)
def hook(request):
 global attempts
 if attempts>=cap: raise RuntimeError('Calibration HTTP cap reached')
 attempts+=1
 print(json.dumps({'event':'attempt','attempt':attempts}),flush=True)
provider._client.event_hooks['request'].append(hook)
system='''你只校对一个具体叙事要求，不评价文风。仅依据给定正文判断该要求是否已满足。met=有正文依据且满足要求的全部部分；not_met=明确违背或要求发生的动作没有在正文发生；uncertain=确有无法判定的歧义。正常后续状态变化不是历史矛盾。禁止补写、猜测、改写要求或假设某个未交代的关键动作发生过。返回严格JSON：{"status":"met|not_met|uncertain","evidence_quotes":["逐字复制正文中相关的连续原句"],"reason":"一句话说明"}。引文必须来自正文，不得来自要求；不得拼接、改字或用省略号替代。met必须给出能支持该要求的正文证据；找不到不能met。'''
for row in samples:
 start=time.monotonic()
 response=provider.generate([{'role':'system','content':system},{'role':'user','content':json.dumps({'requirement':row['requirement'],'text':row['text']},ensure_ascii=False)}],model_id=connection['model'],temperature=0,json_mode=True,max_tokens=1000,disable_thinking=True)
 if response.error or response.finish_reason=='length':raise RuntimeError('Calibration failed or truncated')
 result=_parse_json(response.content)
 quotes=result.get('evidence_quotes',[])
 valid=result.get('status') in ('met','not_met','uncertain') and isinstance(quotes,list) and all(isinstance(q,str) and q.strip() and q in row['text'] for q in quotes)
 if result.get('status')=='met' and not quotes:valid=False
 print(json.dumps({'event':'result','id':row['id'],'expected':row['expected'],'result':result,'evidence_valid':valid,'input_tokens':response.input_tokens,'output_tokens':response.output_tokens,'ms':round((time.monotonic()-start)*1000)},ensure_ascii=False),flush=True)
print(json.dumps({'event':'complete','attempts':attempts,'model':connection['model']}),flush=True)
