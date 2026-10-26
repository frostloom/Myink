import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import extension from '../extensions/controlled-tools.ts';
const definitions=JSON.parse(readFileSync(new URL('../extensions/tool-schemas.json',import.meta.url),'utf8'));
process.env.PI_TOOL_PHASE='develop';
process.env.PI_TOOL_BROKER_URL='http://127.0.0.1:8088';
process.env.PI_TOOL_SCOPE_TOKEN='synthetic';
const registry=new Map(),hooks=new Map();
extension({registerTool:t=>registry.set(t.name,t),on:(n,h)=>hooks.set(n,h),setActiveTools:()=>{}});
const local={type:'object',properties:{},required:[],additionalProperties:true};
assert.deepEqual(registry.get('apply_patch').parameters,local);
assert.deepEqual(registry.get('read_source').parameters,definitions.find(d=>d.name==='read_source').input_schema);
const active=definitions.filter(d=>['read_source','apply_patch','run_check','candidate_status'].includes(d.name));
for (const projected of [false,true]) {
  const tools=active.map(d=>({...d,input_schema:d.name==='apply_patch'?(projected?{type:'object',properties:{},required:[]}:local):d.input_schema}));
  const payload={model:'synthetic',max_tokens:64,messages:[{role:'user',content:'test'}],tools};
  assert.deepEqual(hooks.get('before_provider_request')({payload}).tools,active);
}
const originalFetch=globalThis.fetch;
const bad={plan_hash:'a'.repeat(64),base:'base',candidate_hash:'b'.repeat(64),edits:{extra:1}};
const receipt={operation_id:'tool:synthetic:bad',status:'blocked',schema_version:1,evidence:{reason:'tool argument type mismatch'}};
let received;
globalThis.fetch=async(_url,options)=>{received=JSON.parse(options.body);return {status:200,text:async()=>JSON.stringify(receipt)}};
try {
  const result=await registry.get('apply_patch').execute('bad',bad);
  assert.deepEqual(received.arguments,bad);
  assert.deepEqual(result.details.receipt,receipt);assert.equal(result.isError,true);
} finally {globalThis.fetch=originalFetch;}
for (const name of ['read_source','run_check','candidate_status']) {
  const wrong=active.map(d=>({...d,input_schema:d.name===name?local:d.input_schema}));
  assert.throws(()=>hooks.get('before_provider_request')({payload:{model:'synthetic',max_tokens:64,messages:[{role:'user',content:'test'}],tools:wrong}}));
}
const changed=active.map(d=>({...d,input_schema:d.name==='apply_patch'?{...local,properties:{evil:{type:'string'}}}:d.input_schema}));
assert.throws(()=>hooks.get('before_provider_request')({payload:{model:'synthetic',max_tokens:64,messages:[{role:'user',content:'test'}],tools:changed}}));
console.log('rejected patch: local object routing, unchanged strict model schema, raw host rejection and forged schema checks passed');
