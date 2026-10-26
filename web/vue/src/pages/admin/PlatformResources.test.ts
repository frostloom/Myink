import { flushPromises } from '@vue/test-utils';
import { defineComponent,h,type VNode } from 'vue';
import { createMemoryHistory,createRouter } from 'vue-router';
import { adminContextKey } from './context';
// @vitest-environment jsdom
import { cleanup,fireEvent,screen,render as vueRender,waitFor,within } from '@testing-library/vue';
import { afterEach,beforeEach,expect,it,vi } from 'vitest';
import { api } from '../../../../src/lib/api';
import { emptyFields } from '../../../../src/lib/genrePacks';
import { platformApi } from '../../../../src/lib/platformApi';
import PlatformConfiguration from './PlatformConfiguration';
vi.mock('../../../../src/lib/api', () => ({ api: { listGenrePacks: vi.fn() } }));
vi.mock('../../../../src/lib/platformApi', () => ({
    platformApi: {
        getConfiguration: vi.fn(),
        getPromptTemplates: vi.fn(),
        updateConfiguration: vi.fn(),
        getReadiness: vi.fn(),
    },
}));
const genre = { ...emptyFields(), id: 'fantasy', name: '奇幻', group: '幻想', selling_point: '内置奇幻卖点' };
const config = {
    version: 2,
    model_connections: [],
    model_routes: {},
    prompts: { writer: '写作要求', audit: '审核要求' },
    genre_packs: { fantasy: { selling_point: '定制奇幻卖点' } },
};
function page(section: 'prompts' | 'genres') {
    render(h(PlatformConfiguration, { "section": section }));
}
beforeEach(() => {
    vi.mocked(platformApi.getPromptTemplates).mockResolvedValue([
        {
            role: 'writer',
            templates: [
                {
                    id: 'system_write',
                    title: '长篇正文写作',
                    content: '真实系统模板正文',
                    source: 'src/myink/workflow/prompts.py:SYSTEM_WRITE',
                },
            ],
        },
    ]);
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(config);
    vi.mocked(api.listGenrePacks).mockResolvedValue([genre, { ...genre, id: 'city', name: '都市' }]);
    vi.mocked(platformApi.getReadiness).mockResolvedValue({ ready: true, checks: [] });
    vi.mocked(platformApi.updateConfiguration).mockResolvedValue({ ...config, version: 3 });
});
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});
it('shows prompt cards and opens only the clicked prompt editor', async () => {
    page('prompts');
    await flushPromises();
    await fireEvent.click(await screen.findByRole('button', { name: '编辑 写作提示词' }));
    expect(screen.getByRole('dialog', { name: '编辑写作提示词' })).toBeTruthy();
    expect((screen.getByLabelText('管理员追加指令') as HTMLTextAreaElement).value).toBe('写作要求');
    expect(screen.queryByRole('combobox')).toBeNull();
    await fireEvent.update(screen.getByLabelText('管理员追加指令'), '未保存');
    await fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(platformApi.updateConfiguration).not.toHaveBeenCalled();
});
it('saves only the chosen prompt while preserving other resources', async () => {
    page('prompts');
    await flushPromises();
    await fireEvent.click(await screen.findByRole('button', { name: '编辑 写作提示词' }));
    await fireEvent.update(screen.getByLabelText('管理员追加指令'), '新要求');
    await fireEvent.click(screen.getByRole('button', { name: '保存提示词' }));
    await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled());
    expect(vi.mocked(platformApi.updateConfiguration).mock.calls[0][0]).toMatchObject({
        version: 2,
        prompts: { writer: '新要求', audit: '审核要求' },
        genre_packs: config.genre_packs,
    });
});
it('shows genre cards without a selector and edits only the clicked genre', async () => {
    page('genres');
    await flushPromises();
    expect(await screen.findByRole('button', { name: '编辑 奇幻题材包' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '编辑 都市题材包' })).toBeTruthy();
    expect(screen.queryByRole('combobox')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: '编辑 奇幻题材包' }));
    expect((screen.getByLabelText('核心卖点') as HTMLTextAreaElement).value).toBe('定制奇幻卖点');
    await fireEvent.update(screen.getByLabelText('核心卖点'), '新的卖点');
    await fireEvent.click(screen.getByRole('button', { name: '保存题材包' }));
    await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled());
    const body = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0];
    expect(body.prompts).toEqual(config.prompts);
    expect(body.genre_packs.fantasy.selling_point).toBe('新的卖点');
    expect(body.genre_packs.fantasy).not.toHaveProperty('name');
});
it('restores a genre without reusing stale effective catalog contents', async () => {
    vi.mocked(platformApi.updateConfiguration).mockResolvedValue({ ...config, version: 3, genre_packs: {} });
    vi.mocked(api.listGenrePacks)
        .mockResolvedValueOnce([{ ...genre, selling_point: '定制奇幻卖点' }])
        .mockResolvedValue([genre]);
    page('genres');
    await flushPromises();
    await fireEvent.click(await screen.findByRole('button', { name: '编辑 奇幻题材包' }));
    await fireEvent.click(screen.getByRole('button', { name: '恢复内置内容' }));
    expect(screen.queryByLabelText('核心卖点')).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('保存后');
    expect(platformApi.updateConfiguration).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: '保存题材包' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(vi.mocked(platformApi.updateConfiguration).mock.calls[0][0].genre_packs).toEqual({});
    expect(api.listGenrePacks).toHaveBeenCalledTimes(2);
    await fireEvent.click(await screen.findByRole('button', { name: '编辑 奇幻题材包' }));
    expect((screen.getByLabelText('核心卖点') as HTMLTextAreaElement).value).toBe('内置奇幻卖点');
});
it('retains the selected resource draft after a conflict', async () => {
    vi.mocked(platformApi.updateConfiguration).mockRejectedValue({ status: 409 });
    page('genres');
    await flushPromises();
    await fireEvent.click(await screen.findByRole('button', { name: '编辑 奇幻题材包' }));
    await fireEvent.update(screen.getByLabelText('核心卖点'), '冲突草稿');
    await fireEvent.click(screen.getByRole('button', { name: '保存题材包' }));
    await screen.findByRole('alert');
    expect((screen.getByLabelText('核心卖点') as HTMLTextAreaElement).value).toBe('冲突草稿');
});
it('shows live built-in templates while keeping administrator additions separate', async () => {
    page('prompts');
    await flushPromises();
    await fireEvent.click(await screen.findByRole('button', { name: '编辑 写作提示词' }));
    expect(within(screen.getByRole('dialog')).getByText('真实系统模板正文')).toBeTruthy();
    expect((screen.getByLabelText('管理员追加指令') as HTMLTextAreaElement).value).toBe('写作要求');
    expect(screen.getByText(/内置模板由程序维护/)).toBeTruthy();
});
it('does not claim built-in content when the real template catalog fails to load', async () => {
    vi.mocked(platformApi.getPromptTemplates).mockRejectedValueOnce({ status: 503, code: '模板加载失败' });
    page('prompts');
    await flushPromises();
    expect((await screen.findByRole('alert')).textContent).toContain('模板加载失败');
    expect(screen.queryByRole('button', { name: '编辑 写作提示词' })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: '重新加载配置' }));
    expect(await screen.findByRole('button', { name: '编辑 写作提示词' })).toBeTruthy();
});
function render(node: VNode) { const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:pathMatch(.*)*", component: { render: () => null } }] }); return vueRender(defineComponent({ render: () => node }), { global: { plugins: [router], provide: { [adminContextKey as symbol]: { token: 'token-admin', onForbidden: vi.fn() } } } }); }
