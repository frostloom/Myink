// @vitest-environment jsdom
import {
  cleanup,
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import WritingResources from './WritingResources'
import { writingResources } from '../../lib/writingResources'
import { platformApi } from '../../lib/platformApi'
vi.mock('../../lib/writingResources', async (original) => ({
  ...(await original<typeof import('../../lib/writingResources')>()),
  writingResources: {
    adminList: vi.fn(),
    create: vi.fn(),
    save: vi.fn(),
    revisions: vi.fn(),
    publish: vi.fn(),
    rollback: vi.fn(),
  },
}))
vi.mock('react-router-dom', () => ({
  useOutletContext: () => ({ onForbidden: vi.fn() }),
}))
afterEach(cleanup)
const resource = {
  id: 'r',
  name: '写作',
  kind: 'writing_rule' as const,
  source: 'builtin',
  status: 'published' as const,
  generation: 2,
  current_version: 1,
  body: { roles: { writer: '真实规则' } },
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(writingResources.adminList).mockResolvedValue({
    items: [resource],
  })
  vi.mocked(writingResources.revisions).mockResolvedValue({ items: [] })
})
it('cancelled edits do not save; conflict preserves draft', async () => {
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 写作' }))
  fireEvent.change(screen.getByLabelText('资源名称'), {
    target: { value: '我的草稿' },
  })
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(writingResources.save).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '编辑 写作' }))
  fireEvent.change(screen.getByLabelText('资源名称'), {
    target: { value: '保留草稿' },
  })
  vi.mocked(writingResources.save).mockRejectedValue({ status: 409 })
  fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))
  await screen.findByText(/草稿已保留/)
  expect((screen.getByLabelText('资源名称') as HTMLInputElement).value).toBe(
    '保留草稿',
  )
})
it('publish requires preview confirmation and exact generation', async () => {
  vi.mocked(writingResources.publish).mockResolvedValue(resource)
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 写作' }))
  fireEvent.click(screen.getByRole('button', { name: '预览发布' }))
  expect(writingResources.publish).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '确认发布' }))
  await waitFor(() =>
    expect(writingResources.publish).toHaveBeenCalledWith('r', 2, ''),
  )
})
it('rollback previews an immutable revision and confirms its version with current generation', async () => {
  vi.mocked(writingResources.revisions).mockResolvedValue({
    items: [
      {
        version: 1,
        name: '旧版写作',
        source: 'builtin',
        body: { roles: { writer: '原始规则' } },
        action: 'initial',
        created_at: '2026-10-24',
        note: '原始版本',
      },
    ],
  })
  vi.mocked(writingResources.rollback).mockResolvedValue(resource)
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 写作' }))
  fireEvent.click(await screen.findByText(/v1 · 旧版写作/))
  fireEvent.click(screen.getByRole('button', { name: '预览回退至 v1' }))
  expect(writingResources.rollback).not.toHaveBeenCalled()
  expect(screen.getByText(/原始规则/)).not.toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '确认回退' }))
  await waitFor(() =>
    expect(writingResources.rollback).toHaveBeenCalledWith('r', 2, 1, ''),
  )
})

it('creates a style with runtime-consumed dimensions rather than an unused description', async () => {
  vi.mocked(writingResources.create).mockResolvedValue({
    ...resource,
    id: 'style',
    kind: 'style',
    body: { profile: { pov: '第三人称' } },
  })
  render(<WritingResources />)
  fireEvent.click(screen.getByRole('button', { name: '新建资源' }))
  fireEvent.change(screen.getByLabelText('资源名称'), {
    target: { value: '新文风' },
  })
  fireEvent.change(screen.getByLabelText('资源类型'), {
    target: { value: 'style' },
  })
  fireEvent.change(screen.getByLabelText('视角'), {
    target: { value: '第三人称' },
  })
  fireEvent.change(screen.getByLabelText('叙事声音与语气'), {
    target: { value: '克制' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))
  await waitFor(() => expect(writingResources.create).toHaveBeenCalled())
  const input = vi.mocked(writingResources.create).mock.calls[0][0]
  expect(input.kind).toBe('style')
  expect(input.body).toMatchObject({
    profile: {
      pov: '第三人称',
      narrative_voice: '克制',
      forbidden: [],
      sentence_style: '',
      dialogue: '',
    },
  })
  expect(
    'description' in
      (input.body as { profile: Record<string, unknown> }).profile,
  ).toBe(false)
})

it('shows readable summaries and Chinese status instead of serialized bodies', async () => {
  render(<WritingResources />)
  const card = await screen.findByRole('button', { name: '编辑 写作' })
  expect(card.textContent).toContain('真实规则')
  expect(card.textContent).toContain('已发布')
  expect(card.textContent).not.toContain('"roles"')
  expect(card.textContent).not.toContain('发布标识')
})
it('limits prompts to rules and searches content', async () => {
  vi.mocked(writingResources.adminList).mockResolvedValue({
    items: [
      resource,
      {
        ...resource,
        id: 'ref',
        name: 'docs/世界观.md',
        kind: 'reference',
        body: { files: [{ path: '世界观.md', content: '山海之间' }] },
      },
    ],
  })
  render(<WritingResources scope="prompts" />)
  await screen.findByRole('button', { name: '编辑 写作' })
  expect(screen.queryByRole('button', { name: /编辑.*世界观/ })).toBeNull()
  fireEvent.change(screen.getByLabelText('搜索写作资源'), {
    target: { value: '真实规则' },
  })
  expect(screen.getByRole('button', { name: '编辑 写作' })).not.toBeNull()
})
it('uses reference basename and readable release previews', async () => {
  vi.mocked(writingResources.adminList).mockResolvedValue({
    items: [
      {
        ...resource,
        name: 'docs/世界观.md',
        kind: 'reference',
        body: { files: [{ path: '世界观.md', content: '# 山海\n山海之间' }] },
      },
    ],
  })
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 世界观' }))
  fireEvent.click(screen.getByRole('button', { name: '预览发布' }))
  expect(screen.getByText('山海之间')).not.toBeNull()
  expect(screen.queryByText(/"files"/)).toBeNull()
})

it('keeps internal diagnostics out of writing materials and preserves license information', async () => {
  const catalog = await import('./__fixtures__/author_error_catalog.json?raw')
  vi.mocked(writingResources.adminList).mockResolvedValue({
    items: [
      {
        ...resource,
        id: 'license',
        kind: 'reference',
        name: 'LICENSE',
        body: {
          files: [
            {
              path: 'LICENSE',
              content: 'MIT License\nPermission is hereby granted.',
            },
          ],
        },
      },
      {
        ...resource,
        id: 'catalog',
        kind: 'reference',
        name: 'author_error_catalog.json',
        body: {
          files: [
            { path: 'author_error_catalog.json', content: catalog.default },
          ],
        },
      },
    ],
  })
  render(<WritingResources />)
  expect(await screen.findByText('资料来源与使用说明')).toBeTruthy()
  expect(screen.queryByRole('button', {name:'编辑 author_error_catalog'})).toBeNull()
  expect(screen.queryByRole('button', {name:/编辑.*LICENSE/})).toBeNull()
  expect(screen.getByText('MIT License')).toBeTruthy()
})



it('requires confirmation to take a resource down and keeps it available in the archive filter', async () => {
  vi.mocked(writingResources.save).mockResolvedValue({ ...resource, status: 'archived', generation: 3 })
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 写作' }))
  fireEvent.click(screen.getByRole('button', { name: '下架资源' }))
  expect(writingResources.save).not.toHaveBeenCalled()
  expect(screen.getByText(/已选用的作品仍保留原有快照/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '取消下架' }))
  expect(writingResources.save).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '下架资源' }))
  fireEvent.click(screen.getByRole('button', { name: '确认下架' }))
  await waitFor(() => expect(writingResources.save).toHaveBeenCalledWith('r', {
    expected_generation: 2, name: resource.name, source: resource.source, body: resource.body, status: 'archived',
  }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.queryByRole('button', { name: '编辑 写作' })).toBeNull()
  fireEvent.click(screen.getByLabelText('显示已下架资源'))
  expect(screen.getByRole('button', { name: '编辑 写作' })).toBeTruthy()
})

it('keeps an archive conflict reviewable without discarding edited fields', async () => {
  vi.mocked(writingResources.save).mockRejectedValue({status:409})
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 写作' }))
  fireEvent.change(screen.getByLabelText('资源名称'), {target:{value:'未保存的草稿'}})
  fireEvent.click(screen.getByRole('button', { name: '下架资源' }))
  fireEvent.click(screen.getByRole('button', { name: '确认下架' }))
  await screen.findByText(/草稿已保留/)
  fireEvent.click(screen.getByRole('button', { name: '取消下架' }))
  expect((screen.getByLabelText('资源名称') as HTMLInputElement).value).toBe('未保存的草稿')
})

vi.mock('../../lib/platformApi', () => ({
  platformApi: { getConfiguration: vi.fn().mockResolvedValue({prompts:{}}), getPromptTemplates: vi.fn().mockResolvedValue([{
    role: 'writer', templates: [{id: 'system_write', title: '长篇正文写作',
      content: '默认创作要求\n=== CONTENT ===', source: 'internal',
      editable_content: '默认创作要求', fixed_content: '=== CONTENT ===',
      description: '依据章节计划写出正文', when: '生成长篇章节时'}],
  }]) },
}))

it('separates automatic role prompts from selectable resources and explains when they run', async () => {
  vi.mocked(writingResources.adminList).mockResolvedValue({items: [resource, {
    ...resource, id: 'role-prompt:writer', name: '写作角色提示词', kind: 'role_prompt',
    body: {role: 'writer', templates: {system_write: '默认创作要求'}},
  }]})
  render(<WritingResources />)
  expect(await screen.findByText('角色提示词 · 自动生效')).toBeTruthy()
  expect(screen.getByText('可选写作资源')).toBeTruthy()
  expect(screen.getAllByText(/作品选用后生效/).length).toBeGreaterThan(0)
  fireEvent.click(await screen.findByRole('button', {name: '编辑 长篇正文写作'}))
  expect(await screen.findByLabelText('长篇正文写作 · 创作要求')).toBeTruthy()
  expect(screen.getByRole('dialog').textContent).toContain('生成长篇章节时')
  expect(screen.getByText('=== CONTENT ===')).toBeTruthy()
  expect(screen.queryByLabelText('来源')).toBeNull()
})

it('saves role creative instructions through the same draft and publication lifecycle', async () => {
  const role = {...resource, id: 'role-prompt:writer', name: '写作角色提示词', kind: 'role_prompt' as const,
    body: {role: 'writer', templates: {system_write: '默认创作要求'}}}
  vi.mocked(writingResources.adminList).mockResolvedValue({items:[role]})
  vi.mocked(writingResources.save).mockResolvedValue(role)
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', {name: '编辑 长篇正文写作'}))
  fireEvent.change(await screen.findByLabelText('长篇正文写作 · 创作要求'), {target:{value:'保留作者语气，以行动推进'}})
  fireEvent.click(screen.getByRole('button', {name:'保存草稿'}))
  await waitFor(() => expect(writingResources.save).toHaveBeenCalledWith('role-prompt:writer', {
    expected_generation:2, name:'写作角色提示词', source:'builtin',
    body:{role:'writer', templates:{system_write:'保留作者语气，以行动推进'}, supplement:''},
  }))
})


it('brings a legacy automatic supplement into the role draft and allows explicit clearing', async () => {
  const role = {...resource, id:'role-prompt:writer', name:'写作角色提示词', kind:'role_prompt' as const,
    body:{role:'writer', templates:{system_write:'默认创作要求'}}}
  vi.mocked(platformApi.getConfiguration).mockResolvedValueOnce({version:0,model_connections:[],model_routes:{},genre_packs:{},prompts:{writer:'旧平台共用要求'}})
  vi.mocked(writingResources.adminList).mockResolvedValue({items:[role]})
  vi.mocked(writingResources.save).mockResolvedValue(role)
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', {name:'编辑 写作共用补充'}))
  const supplement = await screen.findByLabelText('各环节共用的补充要求') as HTMLTextAreaElement
  expect(supplement.value).toBe('旧平台共用要求')
  fireEvent.change(supplement, {target:{value:''}})
  fireEvent.click(screen.getByRole('button', {name:'保存草稿'}))
  await waitFor(() => expect(writingResources.save).toHaveBeenCalledWith('role-prompt:writer', expect.objectContaining({
    body:{role:'writer', templates:{system_write:'默认创作要求'}, supplement:''},
  })))
})

it('separates automatic reference methods from selectable book preferences', async () => {
  vi.mocked(writingResources.adminList).mockResolvedValue({items: [{...resource, id: 'characters', kind: 'reference', name: 'references/csv/人设与关系.csv', body: {files: [{path: 'references/csv/人设与关系.csv', content: '编号,适用技能,分类\n1,写作,镜像反派'}]}}]})
  render(<WritingResources />)
  const card = await screen.findByRole('button', {name: '编辑 人物设计与关系写法'})
  expect(screen.getByRole('region', {name: '写作知识库 · AI按需查阅'}).contains(card)).toBe(true)
  expect(screen.getByRole('region', {name: '可选写作资源'}).contains(card)).toBe(false)
  expect(card.textContent).not.toContain('编号,适用技能')
  expect(card.textContent).toContain('无需作者选择')
})
it('shows a readable explanation when a resource history request returns an internal error code', async () => {
  vi.mocked(writingResources.revisions).mockRejectedValue(new Error('not_found'))
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button', { name: '编辑 写作' }))
  expect(await screen.findByText('未找到相关内容')).toBeTruthy()
  expect(screen.queryByText('not_found')).toBeNull()
})
it('lists concrete prompt stages as separate cards and opens only the chosen stage', async () => {
 vi.mocked(platformApi.getPromptTemplates).mockResolvedValue([{role:'writer',templates:[
 {id:'system_write',title:'长篇正文写作',when:'生成长篇章节时',content:'长篇',source:'internal',editable_content:'长篇'},
 {id:'system_short_writer',title:'短篇整篇写作',when:'短篇首次成稿时',content:'短篇',source:'internal',editable_content:'短篇'},
 ]}])
 vi.mocked(writingResources.adminList).mockResolvedValue({items:[{...resource,id:'writer',kind:'role_prompt',body:{role:'writer',supplement:'',templates:{system_write:'长篇',system_short_writer:'短篇'}}}]})
 render(<WritingResources />)
 fireEvent.click(await screen.findByRole('button',{name:'编辑 短篇整篇写作'}))
 expect(await screen.findByLabelText('短篇整篇写作 · 创作要求')).toBeTruthy()
 expect(screen.queryByLabelText('长篇正文写作 · 创作要求')).toBeNull()
 expect(screen.queryByLabelText('各环节共用的补充要求')).toBeNull()
 expect(screen.getByRole('button',{name:'编辑 长篇正文写作'})).toBeTruthy()
})
it('counts rendered prompt cards consistently in tabs and totals, including after searching', async () => {
 vi.mocked(platformApi.getPromptTemplates).mockResolvedValue([{role:'writer',templates:[
 {id:'system_write',title:'长篇正文写作',when:'生成长篇章节时',content:'长篇',source:'internal'},
 {id:'system_short_writer',title:'短篇整篇写作',when:'短篇首次成稿时',content:'短篇',source:'internal'},
 ]}])
 vi.mocked(writingResources.adminList).mockResolvedValue({items:[resource,{...resource,id:'writer',kind:'role_prompt',body:{role:'writer',supplement:'',templates:{system_write:'长篇',system_short_writer:'短篇'}}}]})
 render(<WritingResources />)
 await screen.findByRole('button',{name:'编辑 短篇整篇写作'})
 expect(screen.getAllByRole('button',{name:/^编辑 /})).toHaveLength(4)
 expect(screen.getByRole('button',{name:/^全部\s*4$/})).toBeTruthy()
 expect(screen.getByRole('button',{name:/^角色提示词\s*3$/})).toBeTruthy()
 expect(screen.getByText('共 4 张卡片')).toBeTruthy()
 expect(screen.getByText('2 个环节提示词 · 1 项共用补充，共 3 张卡片')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:/^角色提示词\s*3$/}))
 expect(screen.getAllByRole('button',{name:/^编辑 /})).toHaveLength(3)
 expect(screen.getByText('共 3 张卡片')).toBeTruthy()
 expect(screen.getByRole('button',{name:/^全部\s*4$/})).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:/^全部\s*4$/}))
 fireEvent.change(screen.getByLabelText('搜索写作资源'),{target:{value:'短篇'}})
 expect(screen.getAllByRole('button',{name:/^编辑 /})).toHaveLength(1)
 expect(screen.getByRole('button',{name:/^全部\s*1$/})).toBeTruthy()
 expect(screen.getByRole('button',{name:/^角色提示词\s*1$/})).toBeTruthy()
 expect(screen.getByText('共 1 张卡片')).toBeTruthy()
 expect(screen.queryByRole('button',{name:'编辑 写作共用补充'})).toBeNull()
})

function reviewRoleFixture() {
  vi.mocked(platformApi.getPromptTemplates).mockResolvedValue([{role:'writer',templates:[
    {id:'system_write',title:'长篇正文写作',when:'生成长篇章节时',content:'长篇',source:'internal'},
    {id:'system_short_writer',title:'短篇整篇写作',when:'短篇首次成稿时',content:'短篇',source:'internal'},
  ]}])
  vi.mocked(writingResources.adminList).mockResolvedValue({items:[{...resource,id:'writer',kind:'role_prompt',body:{role:'writer',supplement:'',templates:{system_write:'长篇草稿要求',system_short_writer:'短篇草稿要求'}}}]})
}
it('clears the old stage title when creating a different resource', async () => {
  reviewRoleFixture()
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button',{name:'编辑 短篇整篇写作'}))
  fireEvent.click(screen.getByRole('button',{name:'关闭'}))
  fireEvent.click(screen.getByRole('button',{name:'新建资源'}))
  expect(screen.getByRole('dialog',{name:'编辑新资源'})).toBeTruthy()
})
it('previews the entire role publication, including sibling stage drafts', async () => {
  reviewRoleFixture()
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button',{name:'编辑 短篇整篇写作'}))
  await screen.findByLabelText('短篇整篇写作 · 创作要求')
  fireEvent.click(screen.getByRole('button',{name:'预览发布'}))
  const preview=within(screen.getByRole('dialog',{name:'发布预览'}))
  expect(await preview.findByText('长篇草稿要求')).toBeTruthy()
  expect(preview.getByText('短篇整篇写作')).toBeTruthy()
})
it('keeps metadata failures and retry visible while searching a stage name', async () => {
  reviewRoleFixture()
  vi.mocked(platformApi.getPromptTemplates).mockRejectedValue(new Error('offline'))
  render(<WritingResources />)
  await screen.findByRole('button',{name:'编辑 写作共用补充'})
  fireEvent.change(screen.getByLabelText('搜索写作资源'),{target:{value:'短篇'}})
  expect(await screen.findByRole('button',{name:'重新加载创作环节'})).toBeTruthy()
  expect(screen.queryByText('没有匹配的资源，请调整搜索或筛选条件。')).toBeNull()
})
it('waits for all role preview content before enabling final publication', async () => {
  reviewRoleFixture()
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button',{name:'编辑 短篇整篇写作'}))
  await screen.findByLabelText('短篇整篇写作 · 创作要求')
  let resolvePreview!: (value:Awaited<ReturnType<typeof platformApi.getPromptTemplates>>) => void
  vi.mocked(platformApi.getPromptTemplates).mockReturnValueOnce(new Promise(resolve => {resolvePreview=resolve}))
  fireEvent.click(screen.getByRole('button',{name:'预览发布'}))
  const confirm=screen.getByRole('button',{name:'确认发布'}) as HTMLButtonElement
  expect(confirm.disabled).toBe(true)
  expect(writingResources.publish).not.toHaveBeenCalled()
  resolvePreview([{role:'writer',templates:[{id:'system_write',title:'长篇正文写作',content:'长篇',source:'internal'},{id:'system_short_writer',title:'短篇整篇写作',content:'短篇',source:'internal'}]}])
  await waitFor(()=>expect(confirm.disabled).toBe(false))
})
it('shows history loading instead of claiming that a published role has no history', async () => {
  reviewRoleFixture()
  let resolveHistory!: (value:Awaited<ReturnType<typeof writingResources.revisions>>) => void
  vi.mocked(writingResources.revisions).mockReturnValueOnce(new Promise(resolve => {resolveHistory=resolve}))
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button',{name:'编辑 短篇整篇写作'}))
  expect(screen.getByText('正在读取发布历史…')).toBeTruthy()
  expect(screen.queryByText('尚无发布记录，发布后可在这里查看和回退。')).toBeNull()
  resolveHistory({items:[]})
  expect(await screen.findByText('尚无发布记录，发布后可在这里查看和回退。')).toBeTruthy()
})

it('previews all historical role stages before a bundle rollback', async () => {
  reviewRoleFixture()
  vi.mocked(writingResources.revisions).mockResolvedValue({items:[{version:1,name:'旧版写作',source:'builtin',body:{role:'writer',supplement:'历史共用补充',templates:{system_write:'历史长篇要求',system_short_writer:'历史短篇要求'}},action:'publish',created_at:'2026-10-24',note:''}]})
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button',{name:'编辑 短篇整篇写作'}))
  fireEvent.click(await screen.findByText(/v1 · 旧版写作/))
  fireEvent.click(await screen.findByRole('button',{name:'预览回退至 v1'}))
  const preview=within(screen.getByRole('dialog',{name:'发布预览'}))
  expect(await preview.findByText('历史长篇要求')).toBeTruthy()
  expect(preview.getByText('历史共用补充')).toBeTruthy()
  expect(preview.getByText('短篇整篇写作')).toBeTruthy()
  expect(writingResources.rollback).not.toHaveBeenCalled()
})
it('does not replace the current resource history with a late response from a previously closed resource', async () => {
  vi.mocked(writingResources.adminList).mockResolvedValue({items:[resource,{...resource,id:'new',name:'新资源'}]})
  let resolveOld!: (value:Awaited<ReturnType<typeof writingResources.revisions>>) => void
  const old=new Promise<Awaited<ReturnType<typeof writingResources.revisions>>>(resolve=>{resolveOld=resolve})
  const revision={version:1,name:'当前资源历史',source:'builtin',body:resource.body,action:'publish' as const,created_at:'2026-10-24',note:''}
  vi.mocked(writingResources.revisions).mockImplementation(id=>id==='r'?old:Promise.resolve({items:[revision]}))
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button',{name:'编辑 写作'}))
  fireEvent.click(screen.getByRole('button',{name:'关闭'}))
  fireEvent.click(screen.getByRole('button',{name:'编辑 新资源'}))
  await screen.findByText(/v1 · 当前资源历史/)
  await act(async()=>resolveOld({items:[{...revision,name:'已经关闭的资源历史'}]}))
  expect(screen.queryByText(/v1 · 已经关闭的资源历史/)).toBeNull()
  expect(screen.getByText(/v1 · 当前资源历史/)).toBeTruthy()
})

it('ignores a late history failure after closing the resource editor', async () => {
  let rejectHistory!: (reason: Error) => void
  vi.mocked(writingResources.revisions).mockReturnValueOnce(new Promise((_, reject) => {rejectHistory=reject}))
  render(<WritingResources />)
  fireEvent.click(await screen.findByRole('button',{name:'编辑 写作'}))
  fireEvent.click(screen.getByRole('button',{name:'关闭'}))
  await act(async()=>rejectHistory(new Error('closed history failed')))
  expect(screen.queryByRole('alert')).toBeNull()
})
