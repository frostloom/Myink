// Pure real extension execution with only the HTTP dependency replaced. No installed Pi/model call.
import assert from 'node:assert/strict';
import extension from '../extensions/controlled-tools.ts';
process.env.PI_TOOL_PHASE='analysis';
process.env.PI_TOOL_BROKER_URL='http://127.0.0.1:8088';
process.env.PI_TOOL_SCOPE_TOKEN='synthetic-tools-token';
const registry=new Map();const hooks=new Map();let active=[];let runtimeReady=false;
extension({registerTool:tool=>registry.set(tool.name,tool),on:(name,hook)=>hooks.set(name,hook),setActiveTools:names=>{
  if (!runtimeReady) throw new Error('Extension runtime not initialized. Action methods cannot be called during extension loading.');
  active=names;
}});
assert.equal(registry.size,6);
for (const tool of registry.values()) {
  assert.equal(tool.exposure,'model-only');assert.equal(tool.defaultActive,false);
}
assert.deepEqual(active,[]);
assert.equal(typeof hooks.get('session_start'),'function');
runtimeReady=true;
await hooks.get('session_start')();
assert.deepEqual(active,['observe_metrics','read_source','candidate_status']);
for (const [phase, expected] of [
  ['plan',['observe_metrics','read_source','propose_plan','candidate_status']],
  ['develop',['read_source','apply_patch','run_check','candidate_status']],
  ['diagnose',['observe_metrics','read_source','candidate_status']],
]) {
  process.env.PI_TOOL_PHASE=phase;
  const tools=new Map(), events=new Map();let ready=false, selected=[];
  extension({registerTool:tool=>tools.set(tool.name,tool),on:(name,hook)=>events.set(name,hook),setActiveTools:names=>{
    if (!ready) throw new Error('action during loading');selected=names;
  }});
  assert.equal(tools.size,6);assert.deepEqual(selected,[]);
  for (const tool of tools.values()) {assert.equal(tool.exposure,'model-only');assert.equal(tool.defaultActive,false);}
  ready=true;await events.get('session_start')();assert.deepEqual(selected,expected);
}
process.env.PI_TOOL_PHASE='analysis';
const receipt={schema_version:1,operation_id:'tool:test:call',status:'blocked',evidence:{reason:'path denied'}};
let sent;
const originalFetch=globalThis.fetch;
globalThis.fetch=async (url,options)=>{sent={url:String(url),headers:options.headers,body:JSON.parse(options.body)};return {ok:true,text:async()=>JSON.stringify(receipt)};};
try {
  const result=await registry.get('read_source').execute('call',{path:'.env',start_line:1,end_line:1});
  assert.deepEqual(sent.body,{tool:'read_source',call_id:'call',arguments:{path:'.env',start_line:1,end_line:1}});
  assert.equal(sent.url,'http://127.0.0.1:8088/v1/tools');
  assert.deepEqual(Object.keys(sent.headers).sort(),['Content-Type','X-Pi-Scope','x-api-key']);
  assert.deepEqual(JSON.parse(result.content[0].text),receipt);assert.equal(result.isError,true);
  await assert.rejects(()=>registry.get('apply_patch').execute('call',{}),/ungranted/);
  assert.equal(hooks.get('tool_call')({toolName:'read_source',toolCallId:'parent/1',parentToolCallId:'parent'}).block,true);
  assert.equal(hooks.get('tool_call')({toolName:'nested_model',toolCallId:'call'}).block,true);
  assert.deepEqual(active,['observe_metrics','read_source','candidate_status']);
  const payload={model:'mock',max_tokens:64,messages:[{role:'user',content:'hello'}],tools:active.map(n=>{const t=registry.get(n);return {name:n,description:t.description,input_schema:{type:'object',properties:t.parameters.properties,required:t.parameters.required}};})};
  assert.equal(hooks.get('before_provider_request')({payload}).tools[0].input_schema.additionalProperties,false);
  console.log('controlled extension: deferred four-phase activation, real forward/denial/normalization assertions passed; HTTP simulated');
} finally {globalThis.fetch=originalFetch;}
