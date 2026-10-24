// @vitest-environment jsdom
import { createRef } from 'react'
import { api as generationApi } from '../lib/api'
import { GenerationPanel } from './GenerationPanel'
import type { ResourceUpdateGate } from './ResourceUpdates'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WritingResourcePicker } from './WritingResourcePicker'
import { ResourceUpdates } from './ResourceUpdates'
import { writingResources as api } from '../lib/writingResources'
vi.mock('../lib/writingResources', async (original) => ({
  ...(await original<typeof import('../lib/writingResources')>()),
  writingResources: {
    catalog: vi.fn(),
    personal: vi.fn(),
    snapshot: vi.fn(),
    updates: vi.fn(),
    dismiss: vi.fn(),
    adopt: vi.fn(),
    createPersonal: vi.fn(),
    savePersonal: vi.fn(),
    select: vi.fn(),
    save: vi.fn(),
  },
}))
const resource = {
  id: 'r',
  name: '规则',
  kind: 'writing_rule' as const,
  source: '真实来源',
  status: 'published' as const,
  generation: 3,
  current_version: 2,
  body: { roles: { writer: '写作要求' } },
}
const snapshot = {
  revision: 4,
  configured: true,
  selections: [
    {
      resource_id: 'r',
      origin: 'platform' as const,
      name: '规则',
      kind: 'writing_rule' as const,
      version: 1,
      generation: 1,
      body: resource.body,
      personal_override: false,
    },
  ],
}
const update = {
  resource_id: 'r',
  name: '规则',
  kind: 'writing_rule' as const,
  current_version: 1,
  target_version: 2,
  target_generation: 3,
  action: 'rollback' as const,
  note: '修正',
  dismissed: false,
}
afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.catalog).mockResolvedValue({ items: [resource] })
  vi.mocked(api.personal).mockResolvedValue({ items: [] })
  vi.mocked(api.snapshot).mockResolvedValue(snapshot)
  vi.mocked(api.updates).mockResolvedValue({ items: [update] })
  vi.mocked(api.dismiss).mockResolvedValue({ ok: true })
})
it('clone saves only a personal resource and cancellation writes nothing', async () => {
  vi.mocked(api.createPersonal).mockResolvedValue({
    ...resource,
    id: 'private',
  })
  render(<WritingResourcePicker projectId="p" />)
  fireEvent.click(
    await screen.findByRole('button', { name: '复制到个人资源 规则' }),
  )
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(api.createPersonal).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: '复制到个人资源 规则' }))
  fireEvent.change(screen.getByLabelText('个人资源名称'), {
    target: { value: '私人规则' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存个人资源' }))
  await waitFor(() =>
    expect(api.createPersonal).toHaveBeenCalledWith({
      name: '私人规则',
      kind: 'writing_rule',
      source: '真实来源',
      body: resource.body,
    }),
  )
  expect(api.save).not.toHaveBeenCalled()
  expect(api.select).not.toHaveBeenCalled()
})
it('close dismisses exact generation and manual review keeps ignored releases visible', async () => {
  render(<ResourceUpdates projectId="p" />)
  await screen.findByRole('dialog')
  fireEvent.click(screen.getByRole('button', { name: '暂不更新' }))
  await waitFor(() =>
    expect(api.dismiss).toHaveBeenCalledWith('p', [
      { resource_id: 'r', target_generation: 3 },
    ]),
  )
  expect(api.adopt).not.toHaveBeenCalled()
  vi.mocked(api.updates).mockResolvedValue({
    items: [{ ...update, dismissed: true }],
  })
  fireEvent.click(screen.getByRole('button', { name: /查看资源更新/ }))
  await screen.findByText(/已忽略/)
})
it('adopts checked releases atomically and preserves overrides', async () => {
  vi.mocked(api.adopt).mockResolvedValue({ ...snapshot, revision: 5 })
  render(<ResourceUpdates projectId="p" />)
  fireEvent.click(await screen.findByRole('button', { name: '采用勾选更新' }))
  await waitFor(() =>
    expect(api.adopt).toHaveBeenCalledWith('p', 4, [
      { resource_id: 'r', target_generation: 3 },
    ]),
  )
  cleanup()
  vi.mocked(api.snapshot).mockResolvedValue({
    ...snapshot,
    selections: [{ ...snapshot.selections[0], personal_override: true }],
  })
  render(<ResourceUpdates projectId="p" />)
  await waitFor(() => expect(api.snapshot).toHaveBeenCalled())
  expect(screen.queryByRole('dialog')).toBeNull()
})
it('adding another resource submits existing snapshot identities without replacing their bodies', async () => {
  const style = {
    ...resource,
    id: 'style',
    name: '文风',
    kind: 'style' as const,
    body: { profile: { description: '克制' } },
  }
  vi.mocked(api.catalog).mockResolvedValue({
    items: [{ ...resource, generation: 9, current_version: 8 }, style],
  })
  vi.mocked(api.select).mockResolvedValue(snapshot)
  render(<WritingResourcePicker projectId="p" />)
  fireEvent.click(await screen.findByRole('checkbox', { name: /文风/ }))
  fireEvent.click(screen.getByRole('button', { name: '保存本书资源选择' }))
  await waitFor(() =>
    expect(api.select).toHaveBeenCalledWith('p', 4, [
      { origin: 'platform', resource_id: 'r', personal_override: false },
      { origin: 'platform', resource_id: 'style' },
    ]),
  )
})
it('stale adoption keeps dialog open and offers refresh instead of applying a new release silently', async () => {
  vi.mocked(api.adopt).mockRejectedValue({ status: 409 })
  render(<ResourceUpdates projectId="p" />)
  fireEvent.click(await screen.findByRole('button', { name: '采用勾选更新' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('dialog')).not.toBeNull()
  expect(screen.getByRole('button', { name: '重新检查版本' })).not.toBeNull()
})
it('project customization only writes the project snapshot, never platform or personal catalogs', async () => {
  vi.mocked(api.select).mockResolvedValue({ ...snapshot, revision: 5 })
  render(<WritingResourcePicker projectId="p" />)
  fireEvent.click(
    await screen.findByRole('button', { name: '自定义本书 规则' }),
  )
  fireEvent.change(screen.getByLabelText('写作'), {
    target: { value: '本书私有偏好' },
  })
  fireEvent.click(screen.getByRole('button', { name: '保存本书个人覆盖' }))
  await waitFor(() =>
    expect(api.select).toHaveBeenCalledWith('p', 4, [
      {
        origin: 'platform',
        resource_id: 'r',
        personal_override: true,
        body: { roles: { writer: '本书私有偏好' } },
      },
    ]),
  )
  expect(api.save).not.toHaveBeenCalled()
  expect(api.createPersonal).not.toHaveBeenCalled()
})
it('an archived selected resource absent from catalogs can still be removed', async () => {
  vi.mocked(api.catalog).mockResolvedValue({ items: [] })
  vi.mocked(api.select).mockResolvedValue({
    ...snapshot,
    selections: [],
    revision: 5,
  })
  render(<WritingResourcePicker projectId="p" />)
  fireEvent.click(
    await screen.findByRole('button', { name: '移除本书选择 规则' }),
  )
  fireEvent.click(screen.getByRole('button', { name: '保存本书资源选择' }))
  await waitFor(() => expect(api.select).toHaveBeenCalledWith('p', 4, []))
})

it('refreshes a new publication before a generation request and waits for explicit continue', async () => {
  vi.mocked(api.updates).mockResolvedValue({ items: [] })
  const generate = vi
    .spyOn(generationApi, 'generateChapter')
    .mockResolvedValue({ task_id: 'new', trace_id: 'trace', status: 'queued' })
  const gate = createRef<ResourceUpdateGate>()
  render(
    <>
      <ResourceUpdates projectId="p" gateRef={gate} autoOpen={false} />
      <GenerationPanel
        projectId="p"
        chapters={[]}
        selectedChapter={null}
        onTaskStart={() => {}}
        beforeGenerate={() => gate.current!.beforeGenerate()}
      />
    </>,
  )
  await waitFor(() => expect(api.updates).toHaveBeenCalledTimes(1))
  vi.mocked(api.updates).mockResolvedValue({ items: [update] })
  fireEvent.click(screen.getByRole('button', { name: /写下一章（第 1 章）/ }))
  await screen.findByRole('dialog')
  expect(generate).not.toHaveBeenCalled()
  expect(api.updates).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: '继续使用当前快照' }))
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(1))
  expect(api.adopt).not.toHaveBeenCalled()
  generate.mockRestore()
})
it('adopts a newly discovered rollback before releasing the queued generation request', async () => {
  vi.mocked(api.updates).mockResolvedValue({ items: [] })
  vi.mocked(api.adopt).mockResolvedValue({ ...snapshot, revision: 5 })
  const generate = vi
    .spyOn(generationApi, 'generateChapter')
    .mockResolvedValue({ task_id: 'new', trace_id: 'trace', status: 'queued' })
  const gate = createRef<ResourceUpdateGate>()
  render(
    <>
      <ResourceUpdates projectId="p" gateRef={gate} autoOpen={false} />
      <GenerationPanel
        projectId="p"
        chapters={[]}
        selectedChapter={null}
        onTaskStart={() => {}}
        beforeGenerate={() => gate.current!.beforeGenerate()}
      />
    </>,
  )
  await waitFor(() => expect(api.updates).toHaveBeenCalledTimes(1))
  vi.mocked(api.updates).mockResolvedValue({ items: [update] })
  fireEvent.click(screen.getByRole('button', { name: /写下一章（第 1 章）/ }))
  fireEvent.click(await screen.findByRole('button', { name: '采用勾选更新' }))
  await waitFor(() => expect(generate).toHaveBeenCalledTimes(1))
  expect(api.adopt).toHaveBeenCalledWith('p', 4, [
    { resource_id: 'r', target_generation: 3 },
  ])
  expect(vi.mocked(api.adopt).mock.invocationCallOrder[0]).toBeLessThan(
    generate.mock.invocationCallOrder[0],
  )
  generate.mockRestore()
})
it('makes genre priority visible and saves explicit primary genre first', async () => {
  const primary = {
    ...resource,
    id: 'g1',
    name: '奇幻',
    kind: 'genre' as const,
  }
  const secondary = {
    ...resource,
    id: 'g2',
    name: '悬疑',
    kind: 'genre' as const,
  }
  vi.mocked(api.catalog).mockResolvedValue({ items: [primary, secondary] })
  vi.mocked(api.snapshot).mockResolvedValue({
    ...snapshot,
    selections: [
      {
        ...snapshot.selections[0],
        resource_id: 'g1',
        name: '奇幻',
        kind: 'genre',
      },
    ],
  })
  vi.mocked(api.select).mockResolvedValue(snapshot)
  render(<WritingResourcePicker projectId="p" />)
  fireEvent.click(await screen.findByRole('checkbox', { name: /悬疑/ }))
  expect(screen.getByText('奇幻 · 主题材')).not.toBeNull()
  expect(screen.getByText('悬疑 · 辅题材')).not.toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '设为主题材 悬疑' }))
  expect(screen.getByText('悬疑 · 主题材')).not.toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '保存本书资源选择' }))
  await waitFor(() =>
    expect(api.select).toHaveBeenCalledWith('p', 4, [
      { origin: 'platform', resource_id: 'g2' },
      { origin: 'platform', resource_id: 'g1', personal_override: false },
    ]),
  )
})

it('keeps private reference choices while platform knowledge is automatic', async () => {
  const reference = {...resource, id: 'foundation', name: '平台人物写法', kind: 'reference' as const, body: {files: [{path: 'characters.md', content: 'generic methods'}]}}
  vi.mocked(api.catalog).mockResolvedValue({items: [reference]})
  vi.mocked(api.personal).mockResolvedValue({items: [{...reference, id: 'private-reference', name: '本书私人参考'}]})
  render(<WritingResourcePicker projectId="p" />)
  await screen.findByRole('checkbox', {name: /本书私人参考/})
  expect(screen.queryByText('平台人物写法')).toBeNull()
  expect(screen.getByText(/写作知识库由AI按需查阅/)).toBeTruthy()
})
