import base64,json,os,sys,logging
sys.path.insert(0,'/eval');logging.disable(logging.CRITICAL)
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.workflow.nodes import _parse_json
from action_matrix import Action,parse_source_matrix
p=json.loads(base64.b64decode(os.environ['SOURCE_QUANTIFIER']))
conn=resolve_connection('audit',{},load_configuration(),tier='normal');provider=_chain_from_override(conn,False).providers[0]
count=0
def emit(v):print(json.dumps(v,ensure_ascii=False),flush=True)
def hook(req):
 global count
 if count>=6:raise RuntimeError('Six-request quantifier cap reached')
 count+=1;emit({'event':'attempt','attempt':count})
provider._client.event_hooks['request'].append(hook)
for c in p['cases']:
 actors=['甲','乙'];actions=[Action(text=t,temporal_scope='occurrence') for t in c.get('actions',[c.get('action')])]
 content={'tables':[{'table_id':0,'actors':actors,'actions':[a.model_dump() for a in actions]}],'segments':[{'id':0,'text':c['text']}]}
 r=provider.generate([{'role':'system','content':p['prompt']},{'role':'user','content':json.dumps(content,ensure_ascii=False)}],model_id=conn['model'],temperature=0,json_mode=True,max_tokens=1200,disable_thinking=True)
 if r.error or r.finish_reason=='length':raise RuntimeError('Quantifier provider failure')
 data=_parse_json(r.content)
 if len(data.get('tables',[]))!=1 or data['tables'][0].get('table_id')!=0:raise ValueError('Invalid table ID')
 table=parse_source_matrix({'cells':data['tables'][0]['cells']},actors=actors,actions=actions,segments=[c['text']])
 actual=[cell.status for cell in sorted(table.cells,key=lambda c:(c.actor_id,c.action_id))]
 emit({'event':'result','id':c['id'],'correct':actual==c['expected'],'expected':c['expected'],'actual':actual,'response':data,'input_tokens':r.input_tokens,'output_tokens':r.output_tokens})
emit({'event':'complete','attempts':count})
