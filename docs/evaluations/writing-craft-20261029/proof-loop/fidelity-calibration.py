import os,sys,base64,json,logging
sys.path.insert(0,'/eval')
logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from chapter_checks import parse_fidelity
p=json.loads(base64.b64decode(os.environ['FIDELITY_CALIBRATION']))
conn=resolve_connection('audit',{},load_configuration(),tier='normal')
provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def hook(req):
 global count
 if count>=6:raise RuntimeError('Six-request calibration cap reached')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(hook)
for case in p['cases']:
 request={k:v for k,v in case.items() if k not in ['id','expected']}
 result=provider.generate([{'role':'system','content':p['prompt']},{'role':'user','content':json.dumps(request,ensure_ascii=False)}],model_id=conn['model'],temperature=0,json_mode=True,max_tokens=1200,disable_thinking=True)
 if result.error or result.finish_reason=='length':raise RuntimeError('Failed or truncated calibration')
 parsed=parse_fidelity(_parse_json(result.content),case['events'])
 emit({'event':'result','id':case['id'],'expected':case['expected'],'actual':parsed.passed,'correct':parsed.passed==case['expected'],'review':parsed.model_dump(mode='json'),'input_tokens':result.input_tokens,'output_tokens':result.output_tokens})
emit({'event':'complete','attempts':count})
