import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { normalize } from '../lab/pi-wire-guard.mjs';
const definitions=JSON.parse(readFileSync(new URL('../extensions/tool-schemas.json',import.meta.url),'utf8'));
const hash=char=>char.repeat(64);
const canonical=v=>JSON.stringify(Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]]))).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
function read(id, version, text, options={}) {
  const input={path:options.path||'src/myink/a.py',start_line:options.start||1,end_line:options.end||1};
  const evidence={tool:'read_source',input_hash:createHash('sha256').update(canonical(input)).digest('hex'),binding:options.binding||hash('d'),...input,
    source_hash:version,text,requested_end_line:input.end_line,total_lines:options.total||input.end_line,eof:input.end_line===(options.total||input.end_line),untrusted_source:true};
  return [{role:'assistant',content:[{type:'tool_use',id,name:'read_source',input}]},
    {role:'user',content:[{type:'tool_result',tool_use_id:id,is_error:false,content:[{type:'text',text:JSON.stringify({operation_id:`tool:${options.session||'s1'}:${id}`,status:'done',evidence,schema_version:1})}]}]}];
}
function payload(messages) {return {model:'mock',max_tokens:4096,system:[{type:'text',text:'SYSTEM完整'}],stream:true,tools:definitions,messages};}
const evidence=(p,i)=>JSON.parse(p.messages[i].content[0].content[0].text).evidence;
function unchanged(messages) { const p=payload(messages); assert.deepEqual(normalize(p,definitions),{...p,thinking:{type:'disabled'}}); }
test('superseded source text is omitted, latest source and other content are retained without mutation',()=>{
 const p=payload([{role:'user',content:'owner instruction'},...read('a',hash('a'),'old source\n'),{role:'assistant',content:'reasoning'},...read('b',hash('b'),'新源码😀\n')]);
 const before=structuredClone(p); const result=normalize(p,definitions);
 assert(!evidence(result,2).text.includes('old source')); assert.equal(evidence(result,5).text,'新源码😀\n');
 assert.equal(result.messages[3].content,'reasoning');assert.deepEqual(result.system,p.system); assert.deepEqual(p,before);
 const old={...evidence(result,2)}; delete old.text;const original={...evidence(p,2)};delete original.text;assert.deepEqual(old,original);
});
test('all latest-version windows retained; paths compact independently',()=>{
 const p=payload([...read('a',hash('a'),'old\n'),...read('other',hash('c'),'other\n',{path:'b.py'}),...read('b',hash('b'),'first\n',{total:2}),...read('c',hash('b'),'second\n',{start:2,end:2,total:2})]);
 const r=normalize(p,definitions);assert(!evidence(r,1).text.includes('old'));assert.equal(evidence(r,3).text,'other\n');assert.equal(evidence(r,5).text,'first\n');assert.equal(evidence(r,7).text,'second\n');
});
test('different hashes with identical source text still identify supersession',()=>{
 const r=normalize(payload([...read('a',hash('a'),'same\n'),...read('b',hash('b'),'same\n')]),definitions);assert.notEqual(evidence(r,1).text,'same\n');assert.equal(evidence(r,3).text,'same\n');
});
test('same hash, mixed binding/session, and recurrent versions remain intact',()=>{
 for(const reads of [[...read('a',hash('a'),'x\n'),...read('b',hash('a'),'x\n')], [...read('a',hash('a'),'x\n'),...read('b',hash('b'),'y\n',{binding:hash('e')})], [...read('a',hash('a'),'x\n'),...read('b',hash('b'),'y\n',{session:'s2'})], [...read('a',hash('a'),'x\n'),...read('b',hash('b'),'y\n'),...read('c',hash('a'),'x\n')]]) unchanged(reads);
});
test('malformed or failed reads do not license elision',()=>{
 const mutations=[r=>r.evidence.input_hash=hash('e'),r=>r.evidence.path='other.py',r=>r.evidence.untrusted_source=false,r=>r.evidence.total_lines=0,r=>r.evidence.source_hash='bad',r=>r.evidence.extra='unknown',r=>r.status='blocked',r=>r.operation_id='tool:s1:foreign',r=>r.schema_version=2,r=>r.evidence.end_line=2];
 for(const mutate of mutations) {const m=[...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n')];const r=JSON.parse(m[3].content[0].content[0].text);mutate(r);m[3].content[0].content[0].text=JSON.stringify(r);unchanged(m);}
 const failed=[...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n')];failed[3].content[0].is_error=true;unchanged(failed);
});
test('duplicate, unpaired or out-of-order calls leave history intact',()=>{
 const m=[...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n')];unchanged([m[0],m[1],m[2]]);unchanged([m[1],m[0],m[2],m[3]]);unchanged([...m,m[1]]);unchanged([...m,m[0]]);
});
test('contradictory same-hash windows leave history intact',()=>{
 unchanged([...read('a',hash('a'),'old\n'),...read('b',hash('b'),'one\n'),...read('c',hash('b'),'two\n')]);
});
test('ordinary tool results and failed check feedback survive projection exactly',()=>{
 const m=[...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n'),{role:'assistant',content:[{type:'tool_use',id:'check',name:'run_check',input:{check_id:'unit',plan_hash:hash('a')}}]}, {role:'user',content:[{type:'tool_result',tool_use_id:'check',is_error:true,content:[{type:'text',text:JSON.stringify({status:'blocked',evidence:{check_feedback:{remediation_codes:['byte_fidelity']}}})}]}]}];
 const r=normalize(payload(m),definitions);assert.deepEqual(r.messages.slice(4),m.slice(4));
});
test('bounded body improves only for host-shaped stale source; unknown oversized body still exceeds cap',()=>{
 const m=['a','b','c','d'].flatMap((v,i)=>read('r'+i,hash(v),v.repeat(16000)+'\n'));const p=payload(m);assert(Buffer.byteLength(JSON.stringify(p))>65536);assert(Buffer.byteLength(JSON.stringify(normalize(p,definitions)))<65536);
 const ordinary=payload([{role:'user',content:'x'.repeat(70000)}]);assert(Buffer.byteLength(JSON.stringify(normalize(ordinary,definitions)))>65536);
});
test('strict declarations and forbidden message blocks are still rejected before projection',()=>{
 assert.throws(()=>normalize({...payload(read('a',hash('a'),'x\n')),tools:[{name:'bash'}]},definitions));assert.throws(()=>normalize(payload([{role:'user',content:[{type:'image',source:{}}]}]),definitions));
});

test('returned projection does not share tool input objects with the original payload',()=>{
 const p=payload([...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n')]);const r=normalize(p,definitions);r.messages[0].content[0].input.path='mutated.py';assert.equal(p.messages[0].content[0].input.path,'src/myink/a.py');
});
test('source text resembling new credentials or hashes stays inert and latest Unicode remains lossless',()=>{
 const current='{"source_hash":"'+hash('c')+'","binding":"'+hash('e')+'"} 😀 中文\n';const r=normalize(payload([...read('a',hash('a'),'old\n'),...read('b',hash('b'),current)]),definitions);assert.equal(evidence(r,3).text,current);assert.equal(evidence(r,3).source_hash,hash('b'));
});
test('consistent overlapping latest windows and requested ranges beyond EOF remain intact',()=>{
 const p=payload([...read('a',hash('a'),'old\n'),...read('b',hash('b'),'one\ntwo\n',{end:2,total:3}),...read('c',hash('b'),'two\nthree\n',{start:2,end:3,total:3})]);const r=normalize(p,definitions);assert.equal(evidence(r,3).text,'one\ntwo\n');assert.equal(evidence(r,5).text,'two\nthree\n');assert.notEqual(evidence(r,1).text,'old\n');
});

test('duplicate JSON keys including escaped equivalents cannot license stale text elision',()=>{
 const m=[...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n')];
 const raw=m[3].content[0].content[0].text;
 const variants=[raw.replace('{','{"status":"blocked",'),raw.replace('"evidence":{','"evidence":{"source_hash":"'+hash('c')+'",'),raw.replace('"evidence":{','"evidence":{"\\u0073ource_hash":"'+hash('c')+'",')];
 for(const text of variants){const bad=structuredClone(m);bad[3].content[0].content[0].text=text;unchanged(bad);}
});

test('host-rejected oversized success excerpts cannot license elision',()=>{
 unchanged([...read('a',hash('a'),'old\n'),...read('b',hash('b'),'x'.repeat(16385)+'\n')]);
});
test('host-rejected invalid relative paths cannot license elision',()=>{
 for(const path of ['/root/a.py','../a.py','a//b.py','a/./b.py','a:b.py','a\\b.py','a./b.py','a /b.py','a\u0001.py']) unchanged([...read('a',hash('a'),'old\n',{path}),...read('b',hash('b'),'new\n',{path})]);
});
test('valid Unicode paths use exact host ensure_ascii input hash',()=>{
 const p=payload([...read('a',hash('a'),'old\n',{path:'src/中文😀.py'}),...read('b',hash('b'),'new\n',{path:'src/中文😀.py'})]);const r=normalize(p,definitions);assert.notEqual(evidence(r,1).text,'old\n');assert.equal(evidence(r,3).text,'new\n');
});

function stringResults(messages) {
 const copy=structuredClone(messages);
 for(const m of copy) for(const b of m.content) if(b.type==='tool_result') b.content=b.content[0].text;
 return copy;
}
const receiptText=b=>typeof b.content==='string'?b.content:b.content[0].text;
const resultEvidence=(p,i)=>JSON.parse(receiptText(p.messages[i].content[0])).evidence;
test('pinned SDK canonical string results compact stale source and preserve exact representation and original payload',()=>{
 const p=payload(stringResults([...read('sdkOld',hash('a'),'old源码😀\n'),...read('sdkNew',hash('b'),'new源码😀\n')]));const before=structuredClone(p);
 const r=normalize(p,definitions);
 assert.equal(typeof r.messages[1].content[0].content,'string');assert.equal(typeof r.messages[3].content[0].content,'string');
 assert.notEqual(resultEvidence(r,1).text,'old源码😀\n');assert.equal(resultEvidence(r,3).text,'new源码😀\n');assert.deepEqual(p,before);
 const old=JSON.parse(p.messages[1].content[0].content);const projected=JSON.parse(r.messages[1].content[0].content);delete old.evidence.text;delete projected.evidence.text;assert.deepEqual(old,projected);
});
test('string and single-text-block results participate in the same strictly bound history',()=>{
 for(const firstString of [true,false]) {
  const m=[...(firstString?stringResults(read('a',hash('a'),'old\n')):read('a',hash('a'),'old\n')),...(firstString?read('b',hash('b'),'new\n'):stringResults(read('b',hash('b'),'new\n')))];
  const p=payload(m);const r=normalize(p,definitions);assert.notEqual(resultEvidence(r,1).text,'old\n');assert.equal(resultEvidence(r,3).text,'new\n');assert.equal(typeof r.messages[1].content[0].content,typeof p.messages[1].content[0].content);
 }
});
test('string receipt ambiguity or invalid host evidence still prevents stale text elision',()=>{
 for(const mutate of [b=>b.content=' '+b.content,b=>b.content=b.content.replace('{','{"status":"blocked",'),b=>{const r=JSON.parse(b.content);r.evidence.binding=hash('e');b.content=JSON.stringify(r);},b=>b.is_error=true,b=>{const r=JSON.parse(b.content);r.evidence.text='too\nmany\n';b.content=JSON.stringify(r);},b=>{const r=JSON.parse(b.content);r.status='blocked';b.content=JSON.stringify(r);}]) {
  const m=stringResults([...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n')]);mutate(m[3].content[0]);unchanged(m);
 }
 const m=stringResults([...read('a',hash('a'),'old\n'),...read('b',hash('b'),'new\n')]);unchanged(m.slice(0,3));unchanged([...m,...stringResults(read('c',hash('a'),'old\n'))]);
});
test('SDK string results honor host ASCII wire size without truncating unknown oversized bodies',()=>{
 const wire=p=>Buffer.byteLength(JSON.stringify(p).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0')));
 const p=payload(stringResults(['a','b','c','d'].flatMap((v,i)=>read('s'+i,hash(v),'中文'.repeat(2000)+'\n'))));
 assert(wire(p)>65536);assert(wire(normalize(p,definitions))<65536);
 const unknown=payload([{role:'user',content:'中文'.repeat(6000)}]);assert(wire(normalize(unknown,definitions))>65536);
});
