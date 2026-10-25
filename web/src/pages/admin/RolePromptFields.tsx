import { Disclosure } from './Disclosure'
import { ReadableContent } from './ReadableContent'
import { useEffect, useState } from 'react'
import { AutoTextarea } from '../../components/AutoTextarea'
import { platformApi, type PromptRoleTemplates } from '../../lib/platformApi'
import { writingRoles } from '../../lib/resourceDisplay'
import type { ResourceBody } from '../../lib/writingResources'

type RoleBody = Extract<ResourceBody, { role: string }>
export function RolePromptFields({value, onChange, readOnly = false, templateId, onReadyChange}: {
  value: RoleBody; onChange?: (value: ResourceBody) => void; readOnly?: boolean; templateId?: string; onReadyChange?: (ready:boolean) => void
}) {
  const [templates, setTemplates] = useState<PromptRoleTemplates['templates']>([])
  const [error, setError] = useState('')
  const [legacySupplement, setLegacySupplement] = useState<string | null>(null)
  const [retry, setRetry] = useState(0)
  const hasSupplement = value.supplement !== undefined
  useEffect(() => {
    let live = true
    onReadyChange?.(false)
    Promise.all([platformApi.getPromptTemplates(),
      !readOnly && !hasSupplement ? platformApi.getConfiguration() : Promise.resolve(null),
    ]).then(([items, configuration]) => {
      if (live) {
        const roleTemplates = items.find((item) => item.role === value.role)?.templates ?? []
        if (!roleTemplates.length) {
          setError('未读取到此分工的创作环节，请重新加载。')
          onReadyChange?.(false)
          return
        }
        setTemplates(roleTemplates)
        setLegacySupplement(configuration?.prompts[value.role] ?? '')
        setError('')
        onReadyChange?.(true)
      }
    }).catch(() => { if (live) { setError('写作环节说明或共用补充加载失败，请重试。'); onReadyChange?.(false) } })
    return () => { live = false; onReadyChange?.(false) }
  }, [value.role, retry, readOnly, hasSupplement, onReadyChange])
  const visibleTemplates = templateId ? templates.filter(template => template.id === templateId) : templates
  const showSupplement = !templateId || templateId === '__supplement__'
  const role = writingRoles[value.role]
  const supplement = value.supplement ?? legacySupplement ?? ''
  function changeTemplate(id: string, text: string) {
    onChange?.({...value, supplement, templates: {
      ...value.templates, [id]: text,
    }})
  }
  return <section aria-label={`${role?.name ?? '角色'}的创作要求`}>
    <p>{role?.purpose}。发布后，对应环节的新创作任务自动使用，无需作者逐本选择；已受理任务继续使用原版本。</p>
    {error && <div role="alert">{error}<button className="btn" onClick={() => setRetry((v) => v + 1)}>重新加载环节说明</button></div>}
    {!templates.length && !error && <p role="status">正在读取实际写作环节…</p>}
    {templates.length > 0 && showSupplement && (readOnly ? <section><h3>各环节共用的补充要求</h3>
      <p style={{whiteSpace:'pre-wrap'}}>{value.supplement === undefined ? '此版本沿用当时的平台补充要求。' : value.supplement || '没有额外的共用要求。'}</p>
    </section> : <label style={{display:'grid', gap:8, marginTop:24}}>
      各环节共用的补充要求
      <AutoTextarea aria-label="各环节共用的补充要求" className="textarea" rows={4} value={supplement} disabled={legacySupplement === null}
        onChange={(event) => onChange?.({...value, supplement:event.target.value})} />
      <span>会自动用于此角色的各个环节，与下方要求一起保存草稿、发布和回退；留空表示不追加。</span>
    </label>)}
    {!templateId && <p>以下按具体创作环节分别配置。点击环节名称展开；“共用补充要求”会用于此分工的所有环节。</p>}
    {visibleTemplates.map((template, index) => <Disclosure key={template.id} defaultOpen={index === 0} title={<><span>{template.title}</span><span style={{display:'block',fontWeight:400,fontSize:'var(--text-small)',color:'var(--ink-subtle)',marginTop:6}}>{template.when}</span></>}>
      <fieldset style={{margin:0,padding:0,minWidth:0,border:0}}>
      {template.description && <p>{template.description}</p>}
      {readOnly ? <ReadableContent value={value.templates[template.id] ?? template.editable_content ?? ''} /> : <label>
        {template.title} · 创作要求
        <AutoTextarea className="textarea" rows={8} style={{width:'100%', marginTop:8}} value={value.templates[template.id] ?? template.editable_content ?? ''}
          disabled={legacySupplement === null} onChange={(event) => changeTemplate(template.id, event.target.value)} />
      </label>}
      <details style={{marginTop:16}}><summary>系统保留的流程与输出格式</summary>
        <p>这些约定保证生成结果能够接回写作流程，由系统维护。</p>
        <p style={{whiteSpace:'pre-wrap', overflowWrap:'anywhere'}}>{template.fixed_content ?? template.content}</p>
      </details>
    </fieldset></Disclosure>)}
  </section>
}
