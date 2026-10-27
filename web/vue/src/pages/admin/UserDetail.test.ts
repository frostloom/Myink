/* eslint-disable vue/one-component-per-file -- Tests mount local router harness components. */
import { defineComponent,h,type VNode } from 'vue';
import { createMemoryHistory,createRouter,RouterView } from 'vue-router';
import { adminContextKey } from './context';
// @vitest-environment jsdom
import { cleanup,screen,render as vueRender } from '@testing-library/vue';
import { afterEach,expect,it,vi } from 'vitest';
import { adminApi,type AdminUser } from '../../../../src/lib/adminApi';
import { ApiError } from '../../../../src/lib/api';
import { UserDetailPage } from './UserDetail';
vi.mock('../../../../src/lib/adminApi', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../../src/lib/adminApi')>();
    return {
        ...actual,
        adminApi: { ...actual.adminApi, getUser: vi.fn(), listRuns: vi.fn() },
    };
});
const alice: AdminUser = {
    id: 'user-1', username: 'alice', tier: 'normal', role: 'user',
    project_count: 1, chapter_count: 2, word_count: 300, task_count: 0,
    metrics: { run_count: 0, input_tokens: 0, output_tokens: 0, cost_est: 0, duration_ms: 0 },
    task_averages: { avg_cost_per_task: null, avg_duration_ms_per_task: null, avg_runs_per_task: null },
};
// 详情页是 /admin 下的子路由，闸门与 token 在父路由上——测试按同一棵树挂载。
function renderDetail() {
    return render(h(UserDetailPage, {}));
}
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});
it('loads one account from the single-user endpoint, not from a search query', async () => {
    vi.mocked(adminApi.getUser).mockResolvedValue(alice);
    vi.mocked(adminApi.listRuns).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    renderDetail();
    expect(await screen.findByRole('heading', { name: /alice/ })).toBeTruthy();
    expect(adminApi.getUser).toHaveBeenCalledWith('token-admin', 'user-1', expect.any(AbortSignal));
    expect(adminApi.listRuns).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { name: '调用明细' })).toBeNull();
    expect(screen.queryByRole('link', { name: '查看作品' })).toBeNull();
    expect(screen.queryByRole('navigation', { name: '账号关联记录' })).toBeNull();
});
it('tells the reader a missing user does not exist instead of echoing the 404 code', async () => {
    vi.mocked(adminApi.getUser).mockRejectedValue(new ApiError(404, 'NOT_FOUND', {}));
    vi.mocked(adminApi.listRuns).mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
    renderDetail();
    expect(await screen.findByText('用户不存在')).toBeTruthy();
});
function render(node: VNode) { const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/admin/users/:userId", component: defineComponent({ render: () => node }) }, { path: "/admin/tasks/:taskId", component: defineComponent({ render: () => node }) }, { path: "/admin", component: { render: () => null } }] }); const destination='/admin/users/user-1';const result=vueRender(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [router], provide: { [adminContextKey as symbol]: { token: 'token-admin', onForbidden: vi.fn() } } } });void router.push(destination);return result; }
