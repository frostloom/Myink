import { createHash } from 'node:crypto';
// Trusted Pi1.1.0 wire closure. Default remains finite text-only.
const fixedNames = new Set(['observe_metrics','read_source','propose_plan','apply_patch','run_check','candidate_status']);
function stable(value) {
  return JSON.stringify(value && typeof value === 'object' ? (Array.isArray(value) ? value.map(v=>JSON.parse(stable(v))) : Object.fromEntries(Object.keys(value).sort().map(k=>[k,JSON.parse(stable(value[k]))]))) : value);
}
// Request-only projection: neither durable receipts nor the Pi session are rewritten.
function sourceHistoryProjection(result) {
  const calls=new Map(), results=new Set(), paths=new Map();
  const object=v=>v && typeof v==='object' && !Array.isArray(v);
  const keys=(v,expected)=>object(v) && Object.keys(v).length===expected.length && expected.every(k=>Object.hasOwn(v,k));
  const sha=v=>typeof v==='string' && /^[a-f0-9]{64}$/.test(v);
  const relative=path=>typeof path==='string' && path.length>0 && path.length<=4096 &&
    !/[\\:\x00-\x1f]/.test(path) && !path.startsWith('/') &&
    path.split('/').every(part=>part && part!=='.' && part!=='..' && !/[. ]$/.test(part));
  const hostInput=value=>stable(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  const invalidate=path=>{ if (typeof path==='string') paths.set(path,null); };
  for (const message of result.messages) {
    if (!Array.isArray(message.content)) continue;
    for (const block of message.content) {
      if (block.type==='tool_use') {
        if (calls.has(block.id)) return result;
        calls.set(block.id,block);
      } else if (block.type==='tool_result') {
        const call=calls.get(block.tool_use_id);
        if (!call || results.has(block.tool_use_id)) return result;
        results.add(block.tool_use_id);
        if (call.name!=='read_source') continue;
        const args=call.input, path=args.path;
        if (paths.has(path) && paths.get(path)===null) continue;
        let receipt;
        try {
          // Pinned SDK may flatten the extension's single text block to a string.
          const raw=typeof block.content==='string' ? block.content
            : Array.isArray(block.content) && block.content.length===1 && block.content[0].type==='text' ? block.content[0].text : null;
          if (typeof raw!=='string') throw new Error();
          receipt=JSON.parse(raw);
          // controlled-tools.ts emits exactly JSON.stringify(receipt); reject ambiguous JSON.
          if (raw!==JSON.stringify(receipt)) throw new Error();
        } catch { invalidate(path); continue; }
        const e=receipt?.evidence;
        const session=typeof receipt?.operation_id==='string' ? receipt.operation_id.match(/^tool:([A-Za-z0-9._-]{1,128}):([A-Za-z0-9_-]{1,128})$/) : null;
        if (block.is_error || !keys(receipt,['operation_id','status','evidence','schema_version']) || receipt.schema_version!==1 || receipt.status!=='done' ||
            !keys(args,['path','start_line','end_line']) || !relative(path) ||
            !Number.isInteger(args.start_line) || !Number.isInteger(args.end_line) || args.start_line<1 || args.end_line<args.start_line || args.end_line>args.start_line+199 ||
            !session || session[2]!==call.id ||
            !keys(e,['tool','input_hash','binding','path','source_hash','text','start_line','end_line','requested_end_line','total_lines','eof','untrusted_source']) ||
            e.tool!=='read_source' || e.path!==path || !sha(e.source_hash) || !sha(e.binding) || !sha(e.input_hash) ||
            e.input_hash!==createHash('sha256').update(hostInput(args)).digest('hex') || typeof e.text!=='string' || Buffer.byteLength(e.text,'utf8')>16384 || e.untrusted_source!==true ||
            !Number.isInteger(e.total_lines) || e.total_lines<1 || e.start_line!==args.start_line || e.requested_end_line!==args.end_line ||
            e.end_line!==Math.min(args.end_line,e.total_lines) || e.end_line<e.start_line || e.eof!==(e.end_line===e.total_lines)) {
          invalidate(path); continue;
        }
        const lines=e.text.match(/[^\n\r\v\f\x1c-\x1e\x85\u2028\u2029]*(?:\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]|$)/gu).filter(v=>v!=='');
        if (lines.length!==e.end_line-e.start_line+1) { invalidate(path); continue; }
        let history=paths.get(path);
        const identity=session[1]+':'+e.binding;
        if (!history) { history={identity,versions:[],reads:[],lines:new Map(),total:new Map()}; paths.set(path,history); }
        if (history.identity!==identity || (history.versions.at(-1)!==e.source_hash && history.versions.includes(e.source_hash))) { invalidate(path); continue; }
        if (history.total.has(e.source_hash) && history.total.get(e.source_hash)!==e.total_lines) { invalidate(path); continue; }
        history.total.set(e.source_hash,e.total_lines);
        let windows=history.lines.get(e.source_hash);
        if (!windows) { windows=new Map(); history.lines.set(e.source_hash,windows); }
        let consistent=true;
        for(let i=0;i<lines.length;i++) {
          const n=e.start_line+i;
          if (windows.has(n) && windows.get(n)!==lines[i]) consistent=false;
          windows.set(n,lines[i]);
        }
        if (!consistent) { invalidate(path); continue; }
        if (history.versions.at(-1)!==e.source_hash) history.versions.push(e.source_hash);
        history.reads.push({block,receipt});
      }
    }
  }
  if (calls.size!==results.size) return result;
  for(const history of paths.values()) {
    if (!history || history.versions.length<2) continue;
    for(const {block,receipt} of history.reads) {
      if (receipt.evidence.source_hash===history.versions.at(-1)) continue;
      receipt.evidence.text='[Superseded source text omitted from this request. Historical hash is not current patch authority; use the latest read_source receipt.]';
      if (typeof block.content==='string') block.content=JSON.stringify(receipt);
      else block.content[0].text=JSON.stringify(receipt);
    }
  }
  return result;
}
export function normalize(payload, definitions = []) {
  const controlled = definitions.length > 0;
  if (!Array.isArray(definitions) || definitions.some(d=>!fixedNames.has(d.name)) || new Set(definitions.map(d=>d.name)).size !== definitions.length) throw new Error('invalid trusted tool closure');
  const names = new Set(definitions.map(d=>d.name));
  const allowed = new Set(['model','max_tokens','messages','system','stream','temperature','top_p','top_k','stop_sequences','thinking',...(controlled?['tools']:[])]);
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || Object.keys(payload).some(k=>!allowed.has(k))) throw new Error('unsupported provider payload');
  const content = (value, role, textOnly=false) => {
    if (typeof value === 'string') return value;
    if (!Array.isArray(value) || !value.length) throw new Error('content required');
    return value.map(block=> {
      if (!block || typeof block !== 'object' || Array.isArray(block)) throw new Error('invalid content block');
      if (block.type === 'text' && typeof block.text === 'string' && Object.keys(block).every(k=>['type','text','cache_control'].includes(k))) return {type:'text',text:block.text};
      if (controlled && !textOnly && block.type === 'tool_use' && role === 'assistant' && names.has(block.name) &&
          /^[A-Za-z0-9_-]{1,128}$/.test(block.id) && block.input && typeof block.input === 'object' && !Array.isArray(block.input) &&
          Object.keys(block).every(k=>['type','id','name','input','cache_control'].includes(k))) return {type:'tool_use',id:block.id,name:block.name,input:block.input};
      if (controlled && !textOnly && block.type === 'tool_result' && role === 'user' &&
          /^[A-Za-z0-9_-]{1,128}$/.test(block.tool_use_id) && typeof block.is_error === 'boolean' &&
          Object.keys(block).every(k=>['type','tool_use_id','content','is_error','cache_control'].includes(k)))
        return {type:'tool_result',tool_use_id:block.tool_use_id,content:content(block.content,'user',true),is_error:block.is_error};
      throw new Error('unsupported content block');
    });
  };
  if (!Array.isArray(payload.messages) || !payload.messages.length) throw new Error('messages required');
  const result={...payload,thinking:{type:'disabled'},messages:payload.messages.map(m=> {
    if (!m || !['user','assistant'].includes(m.role) || Object.keys(m).some(k=>!['role','content'].includes(k))) throw new Error('unsupported message');
    return {role:m.role,content:content(m.content,m.role)};
  })};
  if ('system' in payload) result.system=content(payload.system,'system',true);
  if (controlled) {
    if (!Array.isArray(payload.tools) || payload.tools.length !== definitions.length) throw new Error('fixed declarations required');
    payload.tools.forEach((tool,index)=> {
      const expected=definitions[index];
      const projection={type:'object',properties:expected.input_schema.properties,required:expected.input_schema.required};
      // Fixed SDK-local patch routing shell only; strict model schema is restored below.
      const shell={type:'object',properties:{},required:[],additionalProperties:true};
      const shellProjection={type:'object',properties:{},required:[]};
      const schemas=[stable(expected.input_schema),stable(projection)];
      if (expected.name==='apply_patch') schemas.push(stable(shell),stable(shellProjection));
      if (!tool || Object.keys(tool).some(k=>!['name','description','input_schema','cache_control'].includes(k)) ||
          tool.name !== expected.name || tool.description !== expected.description ||
          !schemas.includes(stable(tool.input_schema))) throw new Error('untrusted tool schema');
    });
    result.tools=structuredClone(definitions);
  }
  return controlled ? sourceHistoryProjection(structuredClone(result)) : result;
}
export default function(api) {
  api.on('before_provider_request', event => normalize(event.payload));
}
