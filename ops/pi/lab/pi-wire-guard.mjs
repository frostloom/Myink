// Trusted Pi1.1.0 wire closure. Default remains finite text-only.
const fixedNames = new Set(['observe_metrics','read_source','propose_plan','apply_patch','run_check','candidate_status']);
function stable(value) {
  return JSON.stringify(value && typeof value === 'object' ? (Array.isArray(value) ? value.map(v=>JSON.parse(stable(v))) : Object.fromEntries(Object.keys(value).sort().map(k=>[k,JSON.parse(stable(value[k]))]))) : value);
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
      if (!tool || Object.keys(tool).some(k=>!['name','description','input_schema','cache_control'].includes(k)) ||
          tool.name !== expected.name || tool.description !== expected.description ||
          ![stable(expected.input_schema),stable(projection)].includes(stable(tool.input_schema))) throw new Error('untrusted tool schema');
    });
    result.tools=structuredClone(definitions);
  }
  return result;
}
export default function(api) {
  api.on('before_provider_request', event => normalize(event.payload));
}
