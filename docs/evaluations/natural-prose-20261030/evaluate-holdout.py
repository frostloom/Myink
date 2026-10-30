"""Resource-only natural-prose A/B; synthetic inputs, no model grading or database writes."""
import base64,hashlib,json,logging,os,random,time
from copy import deepcopy
logging.disable(logging.CRITICAL)
from myink.db import new_session
from myink.platform_configuration import load_configuration,resolve_connection
from myink.providers import _chain_from_override
from myink.seed import STYLE_PRESETS
from myink.writing_resources import catalog,capture_role_prompts
from myink.writing_resource_runtime import bind_resources
from myink.workflow import prompts
from myink.workflow.nodes import _check_draft
p=json.loads(base64.b64decode(os.environ['NATURAL_HOLDOUT_INPUT']))
assert len(p['cases'])==2 and p['repetitions']==1 and p['max_requests']==4
conn=resolve_connection('writer',{},load_configuration(),tier='normal')
provider=_chain_from_override(conn,False).providers[0];attempts=0

def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def cap(request):
 global attempts
 if attempts>=4:raise RuntimeError('Four-request natural-prose comparison cap')
 attempts+=1;emit({'event':'attempt','attempt':attempts})
provider._client.event_hooks['request'].append(cap)
with new_session() as db:documents=catalog(db,include_automatic=True);roles=capture_role_prompts(db)
base_ids={'writing-rule:continuity','expression-rule:bans','expression-rule:prose','writing-rule:scene-causality','expression-rule:dialogue','writing-rule:genre-pacing'}
style=next(row['style_profile'] for row in STYLE_PRESETS if row['id']=='natural-narration')
emit({'event':'start','model':conn['model'],'request_cap':4,'temperature':.7,'target_words':p['target_words'],'comparison':'fresh realism holdouts; same published rules, original generic profile vs sample-augmented profile'})
for index,case in enumerate(p['cases']):
 genre=next(r for r in documents if r['kind']=='genre' and r['name']==case['genre'])
 selected=[r for r in documents if r['id'] in base_ids or r['id']==genre['id'] or r['kind']=='genre_rule' and genre['body']['catalog_id'] in r['body'].get('genre_ids',[])]
 assert {r['id'] for r in selected if r['id'] in base_ids}==base_ids
 for repeat in range(1):
  variants=['published','exemplar'] if (index+repeat)%2==0 else ['exemplar','published']
  for variant in variants:
   selections=[dict(resource_id=r['id'],kind=r['kind'],name=r['name'],origin='platform',version=r['current_version'],body=deepcopy(r['body'])) for r in selected]
   current_style=deepcopy(style)
   if variant=='exemplar':current_style['reference_excerpts']=p['reference_excerpts']
   snapshot={'configured':True,'selections':selections,'role_prompts':deepcopy(roles)}
   context={'short_context':[{'kind':'prev_chapter_tail','tail':case['previous_tail']}],'long_term_facts':[{'content':f,'is_hard':True} for f in case['facts']]}
   plan={'goals':[case['goal']],'expected_events':case['expected_events']+[case['must_end']],'hard_constraints':case['facts']}
   with bind_resources(snapshot):messages=prompts.write_messages(context,plan,style_profile=current_style,target_words=p['target_words'])
   wire='\n'.join(m['content'] for m in messages)
   for required in [case['previous_tail'],case['goal'],*case['facts'],*plan['expected_events']]:
    assert required in wire or json.dumps(required,ensure_ascii=False)[1:-1] in wire,'Missing original input'
   if variant=='exemplar':
    for excerpt in p['reference_excerpts']:assert wire.count(excerpt)==1,'Missing original sample'
   emit({'event':'sample_start','case':case['id'],'repeat':repeat,'variant':variant,'resource_ids':[r['resource_id'] for r in selections],'messages_sha256':hashlib.sha256(wire.encode()).hexdigest(),'message_chars':len(wire)})
   start=time.monotonic()
   try:
    response=provider.generate(messages,model_id=conn['model'],max_tokens=2800,temperature=.7,disable_thinking=True)
    if response.error or response.finish_reason=='length':raise ValueError('provider_error_or_truncated')
    text=_check_draft(response.content)
    emit({'event':'sample','case':case['id'],'repeat':repeat,'variant':variant,'text':text,'chars':len(text),'finish_reason':response.finish_reason,'input_tokens':response.input_tokens,'output_tokens':response.output_tokens,'duration_ms':round((time.monotonic()-start)*1000)})
   except Exception as error:emit({'event':'sample_failed','case':case['id'],'repeat':repeat,'variant':variant,'error_type':type(error).__name__,'error':'incomplete_or_invalid_output','duration_ms':round((time.monotonic()-start)*1000)})
emit({'event':'complete','attempts':attempts})
