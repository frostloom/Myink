import assert from 'node:assert/strict';
import { normalize } from '../lab/pi-wire-guard.mjs';
const payload = {model:'mock-model',max_tokens:64,stream:true,system:[{type:'text',text:'system',cache_control:{type:'ephemeral'}}],messages:[{role:'user',content:[{type:'text',text:'hello',cache_control:{type:'ephemeral'}}]}],thinking:{type:'adaptive'}};
const result=normalize(payload);
assert.deepEqual(result.thinking,{type:'disabled'});
assert.deepEqual(result.system,[{type:'text',text:'system'}]);
assert.deepEqual(result.messages,[{role:'user',content:[{type:'text',text:'hello'}]}]);
assert.throws(()=>normalize({...payload,tools:[{name:'bash'}]}));
assert.throws(()=>normalize({...payload,messages:[{role:'user',content:[{type:'image',source:{}}]}]}));
assert.throws(()=>normalize({...payload,messages:[{role:'user',content:[{type:'text',text:'ok',unexpected:true}]}]}));
console.log('wire guard: 6 assertions passed');

const {readFileSync} = await import('node:fs');
const schemas=JSON.parse(readFileSync(new URL('../extensions/tool-schemas.json',import.meta.url),'utf8'));
const granted=schemas.filter(d=>['observe_metrics','read_source','candidate_status'].includes(d.name));
const toolPayload={...payload,tools:granted.map(d=>({...d,input_schema:{type:'object',properties:d.input_schema.properties,required:d.input_schema.required}}))};
const toolsResult=normalize(toolPayload,granted);
assert.deepEqual(toolsResult.tools,granted);
assert.throws(()=>normalize(toolPayload));
assert.throws(()=>normalize({...toolPayload,tools:[{name:'bash',input_schema:{}}]},granted));
const history={...toolPayload,messages:[{role:'assistant',content:[{type:'tool_use',id:'call-1',name:'candidate_status',input:{},cache_control:{type:'ephemeral'}}]},{role:'user',content:[{type:'tool_result',tool_use_id:'call-1',is_error:false,content:[{type:'text',text:'receipt',cache_control:{type:'ephemeral'}}]}]}]};
assert.equal(normalize(history,granted).messages[0].content[0].type,'tool_use');
assert.throws(()=>normalize({...toolPayload,messages:[{role:'assistant',content:[{type:'tool_use',id:'call',name:'bash',input:{command:'evil'}}]}]},granted));
console.log('controlled wire guard: 5 assertions passed');

// Pinned Pi1.1.0 SDK default adds eager_input_streaming; controlled model compat disables it.
const defaultSdkTools=toolPayload.tools.map(tool=>({...tool,eager_input_streaming:true}));
assert.throws(()=>normalize({...toolPayload,tools:defaultSdkTools},granted),/untrusted tool schema/);
assert.deepEqual(normalize(toolPayload,granted).tools,granted);
console.log('controlled SDK compatibility: default eager flag denied; compatible projection accepted');
