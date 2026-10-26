/* eslint-disable vue/one-component-per-file -- Tests mount local router harness components. */
import { defineComponent,h,type VNode } from 'vue';
import { createMemoryHistory,createRouter,RouterView } from 'vue-router';
import { authKey } from '../../authContext';
import { adminContextKey } from './context';
// @vitest-environment jsdom
import { cleanup,fireEvent,screen,render as vueRender } from '@testing-library/vue';
import { afterEach,expect,it,vi } from 'vitest';
import { adminApi,type AdminRun,type AdminRunDetail,type AdminTaskDetail } from '../../../../src/lib/adminApi';
import { TaskDetailView } from './TaskDetail';
vi.mock('../../../../src/lib/adminApi', () => ({ adminApi: { getTask: vi.fn(), listTaskRuns: vi.fn(), getRun: vi.fn() } }));
afterEach(cleanup);
const captured = (data: unknown) => ({ data, truncated: false, redacted: false, limits: { max_depth: 10, max_items: 80, max_text: 12000, max_bytes: 65536 } });
const metrics = { run_count: 2, input_tokens: 200, output_tokens: 100, cost_est: 0.01, duration_ms: 2000 };
const task = { id: 't', project_id: 'p', user_id: 'u', username: '作者', project_title: '停下的秒针', task_type: 'short_generate', status: 'done', chapter_seq: null, batch_task_id: null, retry_count: 0, created_at: '2026-10-24T10:00:00Z', updated_at: '2026-10-24T10:01:00Z', metrics, payload: captured({ chars_per_chapter: 1000, chapter_count: 1, writing_resources: { role_prompts: { writer: { body: { templates: { system_write: 'SECRET_LONG_INTERNAL_PROMPT' } } } }, reference_library: [{ name: 'references/shared/core-constraints.md' }] } }), error: captured(null), elapsed_ms: 60000, elapsed_includes_waits: true } as AdminTaskDetail;
const run = (id: number, time: string): AdminRun => ({ id, project_id: 'p', user_id: 'u', username: '作者', project_title: '停下的秒针', task_id: 't', node: 'short_write', role: 'Writer', model_id: 'test-model', input_tokens: 100, output_tokens: 50, cost_est: 0.005, duration_ms: 1000, cache_hit: false, degraded: false, retry_count: 0, created_at: time, updated_at: time });
function setup() {
    vi.mocked(adminApi.getTask).mockResolvedValue(task);
    vi.mocked(adminApi.listTaskRuns).mockResolvedValue({ items: [run(17, '2026-10-24T10:00:20Z'), run(19, '2026-10-24T10:00:00Z')], total: 2, offset: 0, limit: 25 });
    vi.mocked(adminApi.getRun).mockResolvedValue({ ...run(19, '2026-10-24T10:00:00Z'), detail: captured({ response: { content: '正文结果' }, tool_trace: [{ tool: 'read_genre_reference', arguments: { path: 'references/shared/core-constraints.md' }, result: '{"path":"references/shared/core-constraints.md","content":"写作方法"}' }] }), error: captured(null), detail_missing: false, prompt_missing: false } as AdminRunDetail);
    render(h(TaskDetailView, { "token": "token", "taskId": "t", "onForbidden": vi.fn() }));
}
it('puts task outcome and grouped calls before opt-in technical snapshots', async () => {
    setup();
    await screen.findByText('停下的秒针');
    expect(screen.getByRole('heading', { name: '执行记录' })).toBeTruthy();
    expect(screen.queryByText('SECRET_LONG_INTERNAL_PROMPT')).toBeNull();
    expect(screen.getByText('目标篇幅')).toBeTruthy();
    expect(screen.queryByText('chars_per_chapter')).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
    const calls = await screen.findAllByRole('button', { name: /查看节点 short_write/ });
    expect(calls[0].getAttribute('aria-label')).toContain('#19');
    expect(calls[1].getAttribute('aria-label')).toContain('#17');
});
it('shows actual library reads with Chinese purposes after selecting a call', async () => {
    setup();
    await fireEvent.click(await screen.findByRole('button', { name: '查看节点 short_write #19' }));
    expect(await screen.findByText('故事创作的基本约束')).toBeTruthy();
    expect(screen.getByText('已读取正文')).toBeTruthy();
    expect(screen.queryByText('调试详情')).toBeNull();
});
it('does not mark missing or failed reference results as successful reads', async () => {
    const { ExecutionContent } = await import('./ExecutionContent');
    render(h(ExecutionContent, { "value": { tool_trace: [{ tool: 'read_genre_reference', arguments: { path: 'missing.md' }, result: '{"error":"not available"}' }, { tool: 'read_genre_reference', arguments: {}, result: '{"files":[]}' }, { tool: 'read_genre_reference', arguments: { path: 'old.md' }, result: '' }] } }));
    expect(await screen.findByText('读取失败')).toBeTruthy();
    expect(screen.getByText('已返回目录')).toBeTruthy();
    expect(screen.getByText('结果未留存')).toBeTruthy();
    expect(screen.queryByText('已读取正文')).toBeNull();
});
it('keeps task navigation active in detail routes and closes the compact menu on selection', async () => {
    const { default: AdminRail } = await import('../../components/AdminRail.vue');
    render(h(AdminRail, { "onLogout": vi.fn() }));
    const menu = await screen.findByText('管理导航'); // CSS hides this control at the test runner's desktop width.
    await fireEvent.click(menu);
    expect(menu.getAttribute('aria-expanded')).toBe('true');
    const link = screen.getByRole('link', { name: '任务' });
    expect(link.getAttribute('aria-current')).toBe('page');
    await fireEvent.click(link);
    expect(menu.getAttribute('aria-expanded')).toBe('false');
});
function render(node: VNode) { const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/admin/users/:userId", component: defineComponent({ render: () => node }) }, { path: "/admin/tasks/:taskId", component: defineComponent({ render: () => node }) }, { path: "/admin", component: { render: () => null } }] }); const destination='/admin/tasks/t';const result=vueRender(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [router], provide: { [authKey as symbol]: {logout:vi.fn()}, [adminContextKey as symbol]: { token: 'token-admin', onForbidden: vi.fn() } } } });void router.push(destination);return result; }
