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
globalThis.fetch=async (url,options)=>{sent={url:String(url),headers:options.headers,body:JSON.parse(options.body)};return {ok:true,status:200,text:async()=>JSON.stringify(receipt)};};
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

// The production break caught here is collapsing HTTP rejection, cancellation and
// transport failure into unavailable (or leaking an upstream body/message).
const {test}=await import('node:test');
const canary='synthetic-tools-token http://127.0.0.1:8088 synthetic-argument-body-canary';
const executeRead=signal=>registry.get('read_source').execute('diagnostic-call',{path:canary,start_line:1,end_line:1},signal);
const expectDiagnostic=async (action,message)=>{
  await assert.rejects(action,error=>{
    assert.equal(error.message,message);
    assert.equal(Object.hasOwn(error,'receipt'),false);
    assert.equal(Object.hasOwn(error,'details'),false);
    assert.equal(String(error).includes(canary),false);
    assert.equal(String(error).includes('synthetic-tools-token'),false);
    assert.equal(String(error).includes('http://127.0.0.1:8088'),false);
    assert.equal(error.cause,undefined);
    assert.ok(error.message.length<=100);
    return true;
  });
};

for (const [status,message] of [
  [400,'controlled broker input rejected (HTTP 400)'],
  [401,'controlled broker authentication rejected (HTTP 401)'],
  [403,'controlled broker authentication rejected (HTTP 403)'],
  [408,'controlled broker deadline exceeded (HTTP 408)'],
  [409,'controlled broker state conflict (HTTP 409)'],
  [429,'controlled broker rate limited (HTTP 429)'],
  [500,'controlled broker server error (HTTP 500)'],
  [503,'controlled broker server error (HTTP 503)'],
  [599,'controlled broker server error (HTTP 599)'],
  [302,'controlled broker HTTP rejected (HTTP 302)'],
  [422,'controlled broker HTTP rejected (HTTP 422)'],
]) test(`HTTP ${status} has a bounded diagnostic without reading the error body`,async()=>{
  let calls=0,bodyReads=0;
  const savedFetch=globalThis.fetch;
  globalThis.fetch=async()=>{
    calls++;
    const response={status,ok:false};
    for (const key of ['text','json','body']) Object.defineProperty(response,key,{get(){bodyReads++;throw new Error(canary);}});
    return response;
  };
  try {await expectDiagnostic(()=>executeRead(),message);assert.equal(calls,1);assert.equal(bodyReads,0);}
  finally {globalThis.fetch=savedFetch;}
});

for (const status of [undefined,null,0,99,600,400.5,'400',NaN,Infinity])
  test(`invalid HTTP status ${String(status)} fails closed before receipt reading`,async()=>{
    let bodyReads=0,calls=0;
    const savedFetch=globalThis.fetch;
    globalThis.fetch=async()=>{calls++;return {ok:true,status,text:async()=>{bodyReads++;return JSON.stringify(receipt);}};};
    try {await expectDiagnostic(()=>executeRead(),'controlled broker invalid HTTP status');assert.equal(bodyReads,0);assert.equal(calls,1);}
    finally {globalThis.fetch=savedFetch;}
  });

test('a non-2xx status cannot be bypassed by ok or a valid done receipt',async()=>{
  let reads=0;
  const savedFetch=globalThis.fetch;
  globalThis.fetch=async()=>({ok:true,status:400,text:async()=>{reads++;return JSON.stringify({...receipt,status:'done'});}});
  try {await expectDiagnostic(()=>executeRead(),'controlled broker input rejected (HTTP 400)');assert.equal(reads,0);}
  finally {globalThis.fetch=savedFetch;}
});

for (const stage of ['fetch','body']) test(`${stage} transport failure hides upstream message and does not retry`,async()=>{
  let calls=0;
  const savedFetch=globalThis.fetch;
  globalThis.fetch=async()=>{calls++;if(stage==='fetch') throw new Error(canary);return {ok:true,status:200,text:async()=>{throw new Error(canary);}};};
  try {await expectDiagnostic(()=>executeRead(),'controlled broker transport failure');assert.equal(calls,1);}
  finally {globalThis.fetch=savedFetch;}
});

test('caller abort is separate from HTTP and hides the caller reason',async()=>{
  const savedFetch=globalThis.fetch,controller=new AbortController();let calls=0;
  controller.abort(new Error(canary));
  globalThis.fetch=async(_url,options)=>{calls++;assert.equal(options.signal.aborted,true);throw options.signal.reason;};
  try {await expectDiagnostic(()=>executeRead(controller.signal),'controlled broker aborted');assert.equal(calls,1);}
  finally {globalThis.fetch=savedFetch;}
});

test('local deadline is separate from HTTP and transport without waiting or retrying',async()=>{
  const savedFetch=globalThis.fetch,savedTimeout=AbortSignal.timeout;let calls=0;
  AbortSignal.timeout=milliseconds=>{assert.equal(milliseconds,30000);return AbortSignal.abort(new Error(canary));};
  globalThis.fetch=async(_url,options)=>{calls++;assert.equal(options.signal.aborted,true);throw options.signal.reason;};
  try {await expectDiagnostic(()=>executeRead(),'controlled broker deadline exceeded');assert.equal(calls,1);}
  finally {globalThis.fetch=savedFetch;AbortSignal.timeout=savedTimeout;}
});

test('successful malformed JSON does not expose receipt body through parser errors',async()=>{
  const savedFetch=globalThis.fetch;
  globalThis.fetch=async()=>({ok:true,status:200,text:async()=>`not-json-${canary}`});
  try {await expectDiagnostic(()=>executeRead(),'invalid broker receipt');}
  finally {globalThis.fetch=savedFetch;}
});

test('done and blocked receipts retain their original content, details and error flag',async()=>{
  const savedFetch=globalThis.fetch;
  try {for (const status of ['done','blocked']) {
    const expected={schema_version:1,operation_id:'tool:test:call',status,evidence:{reason:'synthetic proof'}};
    globalThis.fetch=async()=>({ok:true,status:200,text:async()=>JSON.stringify(expected)});
    assert.deepEqual(await executeRead(),{content:[{type:'text',text:JSON.stringify(expected)}],details:{receipt:expected},isError:status!=='done'});
  }} finally {globalThis.fetch=savedFetch;}
});

test('oversized and invalid successful receipts still fail closed',async()=>{
  const savedFetch=globalThis.fetch;
  try {for (const [raw,message] of [
    [' '.repeat(65537),'oversized broker receipt'],
    [JSON.stringify({...receipt,schema_version:2}),'invalid broker receipt'],
    [JSON.stringify({...receipt,status:'accepted'}),'invalid broker receipt'],
    [JSON.stringify({...receipt,operation_id:42}),'invalid broker receipt'],
    [JSON.stringify({...receipt,evidence:'not-an-object'}),'invalid broker receipt'],
  ]) {
    globalThis.fetch=async()=>({ok:true,status:200,text:async()=>raw});
    await expectDiagnostic(()=>executeRead(),message);
  }} finally {globalThis.fetch=savedFetch;}
});
