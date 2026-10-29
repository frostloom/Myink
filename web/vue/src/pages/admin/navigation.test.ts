// @vitest-environment jsdom
import { defineComponent, h } from 'vue';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/vue';
import { afterEach, expect, it, vi } from 'vitest';
import { adminApi, type AdminProject } from '../../../../src/lib/adminApi';
import { AdminConsole } from './AdminConsole';
import { ChapterDetailPage, ProjectDetailPage } from './ProjectDetail';
import { adminContextKey } from './context';
import { adminReturnTo } from './navigation';

vi.mock('../../../../src/lib/adminApi', async (original) => {
    const actual = await original<typeof import('../../../../src/lib/adminApi')>();
    return { ...actual, adminApi: { ...actual.adminApi, listRuns: vi.fn(), getRun: vi.fn(), listAccessLogs: vi.fn(), listProjects: vi.fn(), getProject: vi.fn(), listChapters: vi.fn(), getProjectContext: vi.fn(), getChapter: vi.fn() } };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const project = { id: 'p', user_id: 'u', username: '作者', title: '测试作品', genre: '悬疑', creation_status: 'completed', chapter_count: 1, word_count: 200, task_count: 1, metrics: { run_count: 2, cost_est: 0.01 } } as AdminProject;
async function setup(destination: string, items = [project]) {
    vi.mocked(adminApi.listProjects).mockResolvedValue({ items, total: 60, limit: 25, offset: 25 });
    vi.mocked(adminApi.getProject).mockResolvedValue(project);
    vi.mocked(adminApi.listChapters).mockResolvedValue({ items: [{ id: 'ch', project_id: 'p', title: '第一章', chapter_seq: 1, word_count: 200, status: 'confirmed', created_at: '', updated_at: '' }], total: 1, limit: 25, offset: 0 });
    // Unresolved context must never delay opening the chapter reader.
    vi.mocked(adminApi.getProjectContext).mockImplementation(() => new Promise(() => {}));
    const router = createRouter({ history: createMemoryHistory(), routes: [
        { path: '/admin', component: AdminConsole },
        { path: '/admin/projects/:projectId', component: ProjectDetailPage },
        { path: '/admin/projects/:projectId/chapters/:chapterId', component: ChapterDetailPage },
        { path: '/admin/users/:userId', component: { render: () => null } },
    ] });
    await router.push(destination);
    render(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [router], provide: { [adminContextKey as symbol]: { token: 'token', onForbidden: vi.fn() } } } });
    return router;
}
it('preserves list filters and pagination when opening a work and returning', async () => {
    const destination = '/admin?tab=projects&userId=u&q=测试&offset=25';
    const router = await setup(destination);
    await fireEvent.click(await screen.findByRole('button', { name: '查看《测试作品》' }));
    expect(await screen.findByRole('heading', { name: '作品详情' })).toBeTruthy();
    expect(router.currentRoute.value.query.returnTo).toBe(destination);
    expect(screen.queryByRole('table')).toBeNull();
    await fireEvent.click(screen.getByRole('link', { name: '返回' }));
    await screen.findByRole('button', { name: '查看《测试作品》' });
    expect(adminApi.listProjects).toHaveBeenLastCalledWith('token', { q: '测试', userId: 'u', offset: 25, limit: 25 }, expect.any(AbortSignal));
    expect((screen.getByRole('textbox', { name: '作品搜索' }) as HTMLInputElement).value).toBe('测试');
    await router.push('/admin?tab=projects&userId=other');
    await waitFor(() => expect((screen.getByRole('textbox', { name: '用户 ID' }) as HTMLInputElement).value).toBe('other'));
    router.back();
    await waitFor(() => expect((screen.getByRole('textbox', { name: '用户 ID' }) as HTMLInputElement).value).toBe('u'));
});
it('opens chapter text in its own route with a return to the owning work', async () => {
    const router = await setup('/admin/projects/p');
    vi.mocked(adminApi.getChapter).mockResolvedValue({ id: 'ch', project_id: 'p', title: '第一章', chapter_seq: 1, word_count: 200, status: 'confirmed', version: 1, created_at: '', updated_at: '', content: '章节正文内容', summary: '摘要内容' });
    await fireEvent.click(await screen.findByRole('button', { name: '查看第一章全文' }));
    expect(await screen.findByText('章节正文内容')).toBeTruthy();
    expect(router.currentRoute.value.path).toBe('/admin/projects/p/chapters/ch');
    expect(screen.queryByRole('heading', { name: '受限上下文快照' })).toBeNull();
    expect(screen.getByRole('link', { name: '返回' }).getAttribute('href')).toBe('/admin/projects/p');
});
it('supports direct work links and ignores unsafe return destinations', async () => {
    await setup('/admin/projects/p?returnTo=https://example.com');
    await screen.findByRole('heading', { name: '作品详情' });
    expect(screen.getByRole('link', { name: '返回' }).getAttribute('href')).toBe('/admin?tab=projects');
    expect(adminReturnTo('//example.com', 'projects')).toBe('/admin?tab=projects');
    expect(adminReturnTo('/admin\\evil', 'projects')).toBe('/admin?tab=projects');
});

it('shows log location details in a closable dialog instead of expanding a table row', async () => {
    vi.mocked(adminApi.listAccessLogs).mockResolvedValue({ items: [{ id: 1, actor_id: 'u', action: 'admin.project', target: 'project_id=p', created_at: '' }], total: 1, offset: 0, limit: 25 });
    await setup('/admin?tab=logs');
    await fireEvent.click(await screen.findByRole('button', { name: '查看定位信息' }));
    expect(await screen.findByRole('dialog', { name: '访问日志详情' })).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(screen.queryByRole('dialog')).toBeNull();
});

it('keeps filtered runs visible while a selected run opens and closes in a dialog', async () => {
    vi.mocked(adminApi.listRuns).mockResolvedValue({ items: [{ id: 7, user_id: 'u', username: '作者', project_id: 'p', project_title: '测试作品', task_id: 't', node: 'short_write', role: 'writer', model_id: 'model', input_tokens: 1, output_tokens: 1, duration_ms: 1, cost_est: 0, cache_hit: false, degraded: false, retry_count: 0, created_at: '', updated_at: '' }], total: 1, limit: 25, offset: 0 });
    vi.mocked(adminApi.getRun).mockImplementation(() => new Promise(() => {}));
    await setup('/admin?tab=runs&userId=u');
    await fireEvent.click(await screen.findByRole('button', { name: '查看节点 short_write #7' }));
    expect(await screen.findByRole('dialog', { name: '运行详情 #7' })).toBeTruthy();
    expect(adminApi.listRuns).toHaveBeenCalledWith('token', { userId: 'u', projectId: '', node: '', offset: 0, limit: 25 }, expect.any(AbortSignal));
    await fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '查看节点 short_write #7' }));
});

it('gives a directly opened chapter a return link to its owning work', async () => {
    vi.mocked(adminApi.getChapter).mockImplementation(() => new Promise(() => {}));
    await setup('/admin/projects/p/chapters/ch');
    expect(screen.getByRole('link', { name: '返回' }).getAttribute('href')).toBe('/admin/projects/p');
});

it('groups the current result page by account without mixing books', async () => {
    await setup('/admin?tab=projects', [project, { ...project, id: 'other', user_id: 'v', username: '另一位', title: '别人的书' }, { ...project, id: 'second', title: '第二本' }]);
    const group = await screen.findByRole('table', { name: '作者的作品' });
    expect(within(group).getByText('测试作品')).toBeTruthy();
    expect(within(group).getByText('第二本')).toBeTruthy();
    expect(within(group).queryByText('别人的书')).toBeNull();
    expect(screen.getByRole('table', { name: '另一位的作品' })).toBeTruthy();
});

it('uses one page heading next to the current-view actions', async () => {
    await setup('/admin?tab=projects');
    await screen.findByRole('button', {name:'查看《测试作品》'});
    expect(screen.getAllByRole('heading', {name:'作品'})).toHaveLength(1);
    expect(screen.getByRole('heading', {name:'作品',level:1})).toBeTruthy();
});
