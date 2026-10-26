import { flushPromises } from '@vue/test-utils';
import { defineComponent,h,type VNode } from 'vue';
import { createMemoryHistory,createRouter } from 'vue-router';
import { adminContextKey } from './context';
// @vitest-environment jsdom
import { cleanup,fireEvent,screen,render as vueRender,waitFor,within } from '@testing-library/vue';
import { afterEach,beforeEach,expect,it,vi } from 'vitest';
import { api } from '../../../../src/lib/api';
import { platformApi } from '../../../../src/lib/platformApi';
import PlatformConfiguration from './PlatformConfiguration';
vi.mock('../../../../src/lib/api', () => ({
    ApiError: class ApiError extends Error {
        code = 'API_ERROR';
    },
    api: { listGenrePacks: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../../../../src/lib/platformApi', () => ({ platformApi: { getReadiness: vi.fn(), getConfiguration: vi.fn(), updateConfiguration: vi.fn(), listModels: vi.fn(), testConnection: vi.fn() } }));
const emptyEnv = { version: 1, model_routes: {}, model_connections: [], prompts: {}, genre_packs: {} };
const onForbidden = vi.fn();
beforeEach(() => {
    vi.mocked(platformApi.getReadiness).mockResolvedValue({ ready: true, checks: [] });
    onForbidden.mockReset();
    Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});
function renderPage() {
    return render(h(PlatformConfiguration, {}));
}
it('keeps the draft and presents failed saves in the notification region', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue({ ...emptyEnv, model_connections: [{
                id: 'test', name: '连接 A', protocol: 'openai', base_url: 'https://example.test/v1',
                model: 'writer', has_api_key: true, enabled: true, user_visible: true,
            }] });
    vi.mocked(platformApi.updateConfiguration).mockRejectedValue({ status: 500, code: '保存失败', body: null });
    renderPage();
    await flushPromises();
    const name = await screen.findByLabelText('连接名称');
    await fireEvent.update(name, '新名称');
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    const notice = await screen.findByRole('alert');
    expect(notice.textContent).toContain('保存失败');
    expect(screen.getByRole('region', { name: '模型连接通知' }).contains(notice)).toBe(true);
    await fireEvent.click(screen.getByRole('button', { name: '关闭通知' }));
    expect((name as HTMLInputElement).value).toBe('新名称');
    expect(platformApi.updateConfiguration).toHaveBeenCalledTimes(1);
});
it.each(['models', 'test'] as const)('reports %s failures visibly without resubmitting on close', async (operation) => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue({ ...emptyEnv, model_connections: [{
                id: 'test', name: '连接 A', protocol: 'openai', base_url: 'https://example.test/v1',
                model: 'writer', has_api_key: true, enabled: true, user_visible: true,
            }] });
    vi.mocked(platformApi.listModels).mockResolvedValue({ ok: false, models: [], error: '服务拒绝' });
    vi.mocked(platformApi.testConnection).mockRejectedValue({ status: 500, code: '服务拒绝', body: null });
    renderPage();
    await flushPromises();
    await screen.findByDisplayValue('连接 A');
    const button = screen.getByRole('button', { name: operation === 'models' ? '获取模型列表' : '测试连接' });
    await fireEvent.click(button);
    const notice = await screen.findByRole('alert');
    expect(notice.textContent).toContain('服务拒绝');
    expect(within(screen.getByRole('region', { name: '模型连接通知' })).getByRole('alert')).toBe(notice);
    await fireEvent.click(screen.getByRole('button', { name: '关闭通知' }));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(operation === 'models' ? platformApi.listModels : platformApi.testConnection).toHaveBeenCalledTimes(1);
});
it('adds a network model and routes Writer through it without exposing saved keys', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    vi.mocked(platformApi.updateConfiguration).mockResolvedValue(emptyEnv);
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('11111111-1111-4111-8111-111111111111');
    renderPage();
    await flushPromises();
    await screen.findByText(/尚未添加网络模型/);
    await fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }));
    await fireEvent.update(screen.getByLabelText('连接名称'), '我的 GPT');
    await fireEvent.update(screen.getByLabelText('请求地址'), 'https://models.example.com/v1');
    await fireEvent.update(screen.getByLabelText('模型 id'), 'novel-pro');
    await fireEvent.update(screen.getByLabelText(/API Key/), 'secret-key');
    await fireEvent.update(screen.getByLabelText('写作'), 'custom:11111111-1111-4111-8111-111111111111');
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalledWith({
        model_routes: { writer: 'custom:11111111-1111-4111-8111-111111111111' },
        model_connections: [{
                id: '11111111-1111-4111-8111-111111111111', name: '我的 GPT', protocol: 'openai',
                base_url: 'https://models.example.com/v1', model: 'novel-pro', api_key: 'secret-key', enabled: true, user_visible: true,
            }],
        version: 1, prompts: {}, genre_packs: {}, user_defaults: { thinking_enabled: false, task_budget: { max_requests: 100, max_cost_yuan: 5, max_runtime_seconds: 1800 }, rankings: { enabled: true, timeout: 10, limit: 10 } },
    }));
});
it('focuses and describes the missing field without saving', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('33333333-3333-4333-8333-333333333333');
    renderPage();
    await flushPromises();
    await screen.findByText(/尚未添加网络模型/);
    await fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }));
    await fireEvent.update(screen.getByLabelText('请求地址'), 'https://models.example.com/v1');
    await fireEvent.update(screen.getByLabelText('模型 id'), 'novel-pro');
    await fireEvent.update(screen.getByLabelText(/API Key/), 'secret-key');
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    const field = screen.getByLabelText('连接名称');
    expect(document.activeElement).toBe(field);
    expect(field.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(field.getAttribute('aria-describedby') ?? '')?.textContent).toContain('连接名称');
    expect(field.scrollIntoView).toHaveBeenCalled();
    expect(platformApi.updateConfiguration).not.toHaveBeenCalled();
});
it('fetches the model list into the datalist and tests connectivity', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    vi.mocked(platformApi.listModels).mockResolvedValue({ ok: true, models: ['novel-pro', 'novel-mini'], error: null });
    vi.mocked(platformApi.testConnection).mockResolvedValue({ ok: true, latency_ms: 88, reply: 'pong', error: null });
    vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue('22222222-2222-4222-8222-222222222222');
    renderPage();
    await flushPromises();
    await screen.findByText(/尚未添加网络模型/);
    await fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }));
    await fireEvent.update(screen.getByLabelText('请求地址'), 'https://models.example.com/v1');
    await fireEvent.update(screen.getByLabelText('模型 id'), 'novel-pro');
    await fireEvent.update(screen.getByLabelText(/API Key/), 'secret-key');
    await fireEvent.click(screen.getByRole('button', { name: '获取模型列表' }));
    await waitFor(() => expect(platformApi.listModels).toHaveBeenCalledWith({
        protocol: 'openai', base_url: 'https://models.example.com/v1', model: 'novel-pro', api_key: 'secret-key',
    }));
    await screen.findByText('已获取 2 个模型');
    const options = Array.from(document.querySelectorAll('datalist option'))
        .map((option) => option.getAttribute('value'));
    expect(options).toEqual(['novel-pro', 'novel-mini']);
    await fireEvent.click(screen.getByRole('button', { name: '测试连接' }));
    await waitFor(() => expect(platformApi.testConnection).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('连接正常 · 88 ms'));
});
it('does not invent a model when the configured catalog is empty', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    renderPage();
    await flushPromises();
    const writer = await screen.findByLabelText('写作');
    const labels = Array.from(writer.querySelectorAll('option')).map((option) => option.textContent);
    expect(labels).toEqual(['请选择默认写作模型']);
    expect(screen.getByLabelText('审核')).toBeTruthy();
    expect(screen.getByLabelText('摘要')).toBeTruthy();
    expect(screen.queryByLabelText('思考模式')).toBeNull();
    expect(screen.queryByText(/deepseek/i)).toBeNull();
    expect(screen.queryByRole('button', { name: '填入 DeepSeek 官方地址' })).toBeNull();
});
it('saves publication flags, role prompts and version while preserving a blank saved credential', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue({ ...emptyEnv, model_connections: [{ id: 'one', name: '模型一', protocol: 'openai', base_url: 'https://example.test/v1', model: 'writer', has_api_key: true, enabled: true, user_visible: true }] });
    vi.mocked(platformApi.updateConfiguration).mockRejectedValue({ status: 409, code: 'configuration_conflict' });
    renderPage();
    await flushPromises();
    await screen.findByDisplayValue('模型一');
    expect((screen.getByLabelText(/API Key/) as HTMLInputElement).value).toBe('');
    await fireEvent.click(screen.getByLabelText('向用户发布'));
    await fireEvent.update(screen.getByLabelText('写作追加指令'), '保持中文叙事');
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    await screen.findByText(/配置已被其他管理员更新/);
    expect((screen.getByLabelText('写作追加指令') as HTMLTextAreaElement).value).toBe('保持中文叙事');
    const body = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0];
    expect(body.version).toBe(1);
    expect(body.prompts.writer).toBe('保持中文叙事');
    expect(body.model_connections[0].user_visible).toBe(false);
    expect(body.model_connections[0]).not.toHaveProperty('api_key');
});
it('keeps configuration disabled after a load failure and supports retry', async () => {
    vi.mocked(platformApi.getConfiguration).mockRejectedValueOnce({ status: 503, code: '平台暂不可用' }).mockResolvedValue(emptyEnv);
    renderPage();
    await flushPromises();
    await screen.findByRole('alert');
    expect((screen.getByRole('button', { name: '保存平台配置' }) as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.click(screen.getByRole('button', { name: '重新加载配置' }));
    await waitFor(() => expect((screen.getByRole('button', { name: '保存平台配置' }) as HTMLButtonElement).disabled).toBe(false));
});
it('edits existing platform genres without sending catalog metadata', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    vi.mocked(api.listGenrePacks).mockResolvedValue([{ id: 'fantasy', name: '奇幻', group: '幻想', selling_point: '原卖点', subgenres: [], taboos: [], pacing: '', satisfaction: [], mechanics: [], world_hints: [] }]);
    vi.mocked(platformApi.updateConfiguration).mockResolvedValue(emptyEnv);
    renderPage();
    await flushPromises();
    await screen.findByDisplayValue('原卖点');
    await fireEvent.update(screen.getByLabelText('核心卖点'), '新卖点');
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled());
    const pack = vi.mocked(platformApi.updateConfiguration).mock.calls[0][0].genre_packs.fantasy;
    expect(pack.selling_point).toBe('新卖点');
    expect(pack).not.toHaveProperty('id');
    expect(pack).not.toHaveProperty('group');
});
it('clears protected configuration through the admin gate when save permission is revoked', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    vi.mocked(platformApi.updateConfiguration).mockRejectedValue({ status: 403, code: 'forbidden' });
    renderPage();
    await flushPromises();
    await waitFor(() => expect((screen.getByRole('button', { name: '保存平台配置' }) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    await waitFor(() => expect(onForbidden).toHaveBeenCalledTimes(1));
});
it('merges partial nullable genre overrides with published genre defaults', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue({ ...emptyEnv, genre_packs: { fantasy: { pacing: '管理员节奏', selling_point: null, subgenres: null, taboos: null, satisfaction: null, mechanics: null, world_hints: null } } } as never);
    vi.mocked(api.listGenrePacks).mockResolvedValue([{ id: 'fantasy', name: '奇幻', group: '幻想', selling_point: '默认卖点', subgenres: [], taboos: ['默认禁忌'], pacing: '默认节奏', satisfaction: [], mechanics: [], world_hints: [] }]);
    renderPage();
    await flushPromises();
    await screen.findByDisplayValue('管理员节奏');
    expect(screen.getByDisplayValue('默认卖点')).toBeTruthy();
    expect(screen.getByDisplayValue('默认禁忌')).toBeTruthy();
});
it('loads and edits admin defaults while preserving fetched leaves through connection saves', async () => {
    const defaults = { thinking_enabled: true, task_budget: { max_requests: 220, max_cost_yuan: 0, max_runtime_seconds: 3000 }, rankings: { enabled: false, timeout: 14, limit: 22 } };
    vi.mocked(platformApi.getConfiguration).mockResolvedValue({ ...emptyEnv, user_defaults: defaults, model_connections: [{ id: 'one', name: '模型一', protocol: 'openai', base_url: 'https://example.test/v1', model: 'writer', has_api_key: true, enabled: true, user_visible: true }] } as never);
    vi.mocked(platformApi.updateConfiguration).mockResolvedValue({ ...emptyEnv, version: 2, user_defaults: { ...defaults, task_budget: { ...defaults.task_budget, max_requests: 250 } } } as never);
    renderPage();
    await flushPromises();
    await screen.findByDisplayValue('模型一');
    expect((screen.getByLabelText('默认思考模式') as HTMLSelectElement).value).toBe('1');
    expect((screen.getByLabelText('默认任务请求上限') as HTMLInputElement).value).toBe('220');
    expect((screen.getByLabelText('默认启用扫榜') as HTMLSelectElement).value).toBe('0');
    await fireEvent.update(screen.getByLabelText('连接名称'), '更新连接');
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalled());
    expect(vi.mocked(platformApi.updateConfiguration).mock.calls[0][0]).toMatchObject({ user_defaults: defaults });
    await waitFor(() => expect((screen.getByLabelText('默认任务请求上限') as HTMLInputElement).value).toBe('250'));
    await fireEvent.update(screen.getByLabelText('默认思考模式'), '0');
    await fireEvent.update(screen.getByLabelText('默认任务费用上限（元）'), '8');
    await fireEvent.update(screen.getByLabelText('默认扫榜超时'), '20');
    await fireEvent.click(screen.getByRole('button', { name: '保存全部更改' }));
    await waitFor(() => expect(platformApi.updateConfiguration).toHaveBeenCalledTimes(2));
    expect(vi.mocked(platformApi.updateConfiguration).mock.calls[1][0]).toMatchObject({ version: 2, user_defaults: { thinking_enabled: false, task_budget: { max_requests: 250, max_cost_yuan: 8, max_runtime_seconds: 3000 }, rankings: { enabled: false, timeout: 20, limit: 22 } } });
});
it('keeps edited admin defaults after a failed save', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    vi.mocked(platformApi.updateConfiguration).mockRejectedValue({ status: 500, code: '保存失败' });
    renderPage();
    await flushPromises();
    await waitFor(() => expect((screen.getByRole('button', { name: '保存平台配置' }) as HTMLButtonElement).disabled).toBe(false));
    await fireEvent.update(screen.getByLabelText('默认任务请求上限'), '160');
    await fireEvent.click(screen.getByRole('button', { name: '保存平台配置' }));
    await screen.findByRole('alert');
    expect((screen.getByLabelText('默认任务请求上限') as HTMLInputElement).value).toBe('160');
});
it('shows saved readiness and explicitly refreshes without losing unsaved drafts', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue({ ...emptyEnv, model_connections: [{
                id: 'test', name: '连接 A', protocol: 'openai', base_url: 'https://example.test', model: 'writer',
                has_api_key: true, enabled: true, user_visible: true,
            }] });
    vi.mocked(platformApi.getReadiness).mockResolvedValueOnce({ ready: false, checks: [
            { role: 'audit', ready: false, reason: 'credential_unavailable' },
            { role: 'writer', ready: true, reason: null },
        ] }).mockResolvedValue({ ready: true, checks: [{ role: 'audit', ready: true, reason: null }] });
    renderPage();
    await flushPromises();
    await screen.findByText('凭据不可用，请重新保存密钥');
    await fireEvent.update(screen.getByLabelText('连接名称'), '尚未保存');
    await fireEvent.click(screen.getByRole('button', { name: '刷新就绪状态' }));
    await screen.findByText('平台创作服务已就绪');
    expect((screen.getByLabelText('连接名称') as HTMLInputElement).value).toBe('尚未保存');
});
it('keeps configuration editable when optional readiness endpoint is unavailable', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    vi.mocked(platformApi.getReadiness).mockRejectedValue({ status: 404, code: 'not_found' });
    renderPage();
    await flushPromises();
    await screen.findByText('暂时无法读取就绪状态');
    expect((screen.getByRole('button', { name: '保存平台配置' }) as HTMLButtonElement).disabled).toBe(false);
});
function render(node: VNode) { const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:pathMatch(.*)*", component: { render: () => null } }] }); return { ...vueRender(defineComponent({ render: () => node }), { global: { plugins: [router], provide: { [adminContextKey as symbol]: { token: 'token-admin', onForbidden: onForbidden } } } }), router }; }

it('protects click-created configuration drafts with no input event and retains them after failed saves', async () => {
    vi.mocked(platformApi.getConfiguration).mockResolvedValue(emptyEnv);
    const { router } = renderPage(); await flushPromises();
    const clean = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(clean); expect(clean.defaultPrevented).toBe(false);
    await fireEvent.click(screen.getByRole('button', { name: '添加网络模型' }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const before = router.currentRoute.value.fullPath;
    await router.push('/other'); expect(router.currentRoute.value.fullPath).toBe(before);
    expect(screen.getByLabelText('连接名称')).toBeTruthy();
    const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); expect(event.defaultPrevented).toBe(true);
    expect(confirm).toHaveBeenCalledTimes(1); confirm.mockRestore();
});
