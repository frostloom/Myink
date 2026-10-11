// Pinned trusted extension. Finite text-only wire; no tools or continuation hooks.
export function normalize(payload) {
  const allowed = new Set(['model','max_tokens','messages','system','stream','temperature','top_p','top_k','stop_sequences','thinking']);
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) || Object.keys(payload).some(k=>!allowed.has(k))) throw new Error('unsupported provider payload');
  function content(value) {
    if (typeof value === 'string') return value;
    if (!Array.isArray(value) || !value.length) throw new Error('text content required');
    return value.map(block=> {
      if (!block || block.type !== 'text' || typeof block.text !== 'string' || Object.keys(block).some(k=>!['type','text','cache_control'].includes(k))) throw new Error('unsupported content block');
      return {type:'text',text:block.text};
    });
  }
  if (!Array.isArray(payload.messages) || !payload.messages.length) throw new Error('messages required');
  const result={...payload,thinking:{type:'disabled'},messages:payload.messages.map(m=> {
    if (!m || !['user','assistant'].includes(m.role) || Object.keys(m).some(k=>!['role','content'].includes(k))) throw new Error('unsupported message');
    return {role:m.role,content:content(m.content)};
  })};
  if ('system' in payload) result.system=content(payload.system);
  return result;
}
export default function(api) {
  api.on('before_provider_request', event => normalize(event.payload));
}
