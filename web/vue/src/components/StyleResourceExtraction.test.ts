import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { ref } from 'vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import StyleResourceExtraction from './StyleResourceExtraction.vue'

const mocks = vi.hoisted(() => ({ extract: vi.fn(), list: vi.fn(), createPersonal: vi.fn(), create: vi.fn(), publish: vi.fn(), catalogAll: vi.fn(), personal: vi.fn(), importLegacy: vi.fn() }))
vi.mock('../../../src/lib/styleLibraryApi', () => ({ styleLibraryApi: { extract: mocks.extract, list: mocks.list } }))
vi.mock('../../../src/lib/writingResources', async original => ({ ...await original<object>(), writingResources: mocks }))
const session = ref<{ userId: string; token: string; role: string; roleVerified: boolean; isGuest?: boolean }>({ userId: 'user-1', token: 't', role: 'user', roleVerified: true })
vi.mock('../authContext', () => ({ useAuth: () => ({ session, status: ref('authenticated') }) }))

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  session.value = { userId: 'user-1', token: 't', role: 'user', roleVerified: true }
  mocks.extract.mockResolvedValue({ draft: { narrative_voice: '干净自然', source: 'sample' } })
  mocks.list.mockResolvedValue({ items: [] })
  mocks.createPersonal.mockResolvedValue({ id: 'mine', name: '日常', kind: 'style', body: { profile: {} } })
  mocks.create.mockResolvedValue({ id: 'platform', generation: 0 })
  mocks.publish.mockResolvedValue({ id: 'platform', generation: 1 })
  mocks.catalogAll.mockResolvedValue({ items: [] })
  mocks.importLegacy.mockResolvedValue({ id: 'imported' })
  mocks.personal.mockResolvedValue({ items: [] })
})
async function draft() {
  await fireEvent.click(screen.getByRole('button', { name: '从文章提取文风' }))
  await fireEvent.update(screen.getByLabelText('文章样本'), '一段用来分析的文字。')
  await fireEvent.click(screen.getByRole('button', { name: '提取文风' }))
  await screen.findByDisplayValue('干净自然')
  await fireEvent.update(screen.getByLabelText('文风名称'), '日常')
}
it('extracts and saves an editable personal resource without publication', async () => {
  render(StyleResourceExtraction)
  await draft()
  await fireEvent.update(screen.getByDisplayValue('干净自然'), '轻松自然')
  expect(screen.queryByLabelText('发布给所有用户')).toBeNull()
  await fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
  await waitFor(() => expect(mocks.createPersonal).toHaveBeenCalledWith(expect.objectContaining({ name: '日常', kind: 'style', body: { profile: expect.objectContaining({ narrative_voice: '轻松自然' }) } })))
  expect(mocks.create).not.toHaveBeenCalled(); expect(mocks.publish).not.toHaveBeenCalled()
})
it('only publishes when a verified administrator explicitly chooses it, and retries without creating a duplicate', async () => {
  session.value = { ...session.value, role: 'admin' }
  mocks.publish.mockRejectedValueOnce(new Error('暂时不可用')).mockResolvedValueOnce({ id: 'platform', generation: 1 })
  render(StyleResourceExtraction)
  await draft()
  await fireEvent.click(screen.getByLabelText('发布给所有用户'))
  await fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
  await screen.findByRole('alert')
  expect(mocks.create).toHaveBeenCalledTimes(1)
  await fireEvent.click(screen.getByRole('button', { name: '重试发布' }))
  await waitFor(() => expect(mocks.publish).toHaveBeenCalledTimes(2))
  expect(mocks.create).toHaveBeenCalledTimes(1)
  expect(mocks.createPersonal).not.toHaveBeenCalled()
})
it('copies an existing legacy personal style into private resources', async () => {
  mocks.list.mockResolvedValue({ items: [{ id: 'old-id', name: '旧文风', builtin: false, profile: { pacing: '缓慢' } }, { id: 'builtin:x', name: '内置', builtin: true }] })
  render(StyleResourceExtraction)
  await fireEvent.click(screen.getByRole('button', { name: '导入旧版个人文风' }))
  await fireEvent.click(await screen.findByRole('button', { name: '导入 旧文风' }))
  await waitFor(() => expect(mocks.importLegacy).toHaveBeenCalledWith('old-id'))
  expect(mocks.create).not.toHaveBeenCalled()
  mocks.personal.mockResolvedValue({ items: [{ source_resource_id: 'legacy-style:old-id' }] })
  await fireEvent.click(screen.getByRole('button', { name: '导入旧版个人文风' }))
  expect(await screen.findByText('没有待导入的旧版个人文风。')).toBeTruthy()
})
it('keeps an administrator extraction private unless publication was selected', async () => {
  session.value = { ...session.value, role: 'admin' }
  render(StyleResourceExtraction)
  await draft()
  expect((screen.getByLabelText('发布给所有用户') as HTMLInputElement).checked).toBe(false)
  await fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
  await waitFor(() => expect(mocks.createPersonal).toHaveBeenCalledOnce())
  expect(mocks.create).not.toHaveBeenCalled(); expect(mocks.publish).not.toHaveBeenCalled()
})
it('does not publish an old account draft after the account changes', async () => {
  let finish!: (value: {id:string; generation:number}) => void
  session.value = { ...session.value, role: 'admin' }
  mocks.create.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  render(StyleResourceExtraction)
  await draft()
  await fireEvent.click(screen.getByLabelText('发布给所有用户'))
  await fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
  session.value = { userId: 'another', token: 'other', role: 'admin', roleVerified: true }
  finish({ id: 'platform', generation: 0 })
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(mocks.publish).not.toHaveBeenCalled()
})

it('recognizes an already-published resource when the publish response was lost', async () => {
  session.value = { ...session.value, role: 'admin' }
  const resource = { id: 'platform', generation: 0, name: '日常', source: '文章样本提取', body: { profile: { narrative_voice: '干净自然', source: 'sample' } } }
  mocks.create.mockResolvedValue(resource)
  mocks.publish.mockRejectedValueOnce(new Error('连接中断'))
  mocks.catalogAll.mockResolvedValue({ items: [{ ...resource, status: 'published', current_version: 1 }] })
  render(StyleResourceExtraction); await draft()
  await fireEvent.click(screen.getByLabelText('发布给所有用户'))
  await fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
  expect(await screen.findByText('文风已发布，所有用户均可选用。')).toBeTruthy()
  expect(mocks.create).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('button', { name: '重试发布' })).toBeNull()
})
it('does not show an old account publish error after switching accounts during reconciliation', async () => {
  let rejectCatalog!: (reason: Error) => void
  session.value = { ...session.value, role: 'admin' }
  mocks.publish.mockRejectedValueOnce(new Error('发布连接中断'))
  mocks.catalogAll.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectCatalog = reject }))
  render(StyleResourceExtraction); await draft()
  await fireEvent.click(screen.getByLabelText('发布给所有用户'))
  await fireEvent.click(screen.getByRole('button', { name: '保存文风' }))
  await waitFor(() => expect(mocks.catalogAll).toHaveBeenCalledOnce())
  session.value = { userId: 'another', token: 'other', role: 'user', roleVerified: true }
  rejectCatalog(new Error('目录连接中断'))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(screen.queryByRole('alert')).toBeNull()
})
