import { h } from 'vue'
import { flushPromises } from '@vue/test-utils'

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '../workspaceTestUtils';
import { afterEach, expect, it, vi } from 'vitest';
import TaskBudgetPanel from './TaskBudgetPanel.vue';
import TaskTimeline from './TaskTimeline.vue';
import { api } from '../../../src/lib/api';
vi.mock('../../../src/lib/api', () => ({ api: { resumeTask: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const budget = { limits: { max_requests: 1, max_cost_yuan: 5, max_runtime_seconds: 1800 }, requests_used: 1, cost_used_yuan: 0.1, cost_reserved_yuan: 0.2, runtime_used_seconds: 10, pause_reason: 'request_limit', stage: 'audit', version: 1, resume_publication: null };
it('protects a failed budget submission but releases the form guard after a successful retry', async () => {
    vi.mocked(api.resumeTask).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ task_id: 't', status: 'queued' })
    render(h(TaskBudgetPanel, { task: { task_id: 't', status: 'paused', budget }, onResumed: vi.fn() }))
    for (const label of ['追加请求次数', '追加费用（元）', '追加运行时间（分钟）']) {
        await fireEvent.input(screen.getByLabelText(label), { target: { value: '2' } })
    }
    await fireEvent.click(screen.getByRole('button', { name: '追加并继续' })); await flushPromises()
    const failed = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(failed)
    expect(failed.defaultPrevented).toBe(true)
    expect((screen.getByLabelText('追加请求次数') as HTMLInputElement).value).toBe('2')
    await fireEvent.click(screen.getByRole('button', { name: '重试本次恢复' })); await flushPromises()
    const saved = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(saved)
    expect(saved.defaultPrevented).toBe(false)
})
it('retains the operation id on retry and prevents duplicate clicks', async () => {
    vi.mocked(api.resumeTask).mockRejectedValueOnce(new Error('网络失败')).mockResolvedValueOnce({ task_id: 't', status: 'queued' });
    const resumed = vi.fn();
    render(h(TaskBudgetPanel, { "detailsCollapsed": true, "task": { task_id: 't', status: 'paused', budget }, "onResumed": resumed }, []));
    await fireEvent.input(screen.getByLabelText('追加请求次数'), { target: { value: '2' } });
    await fireEvent.click(screen.getByRole('button', { name: '追加并继续' }));
    await screen.findByRole('alert');
    const first = vi.mocked(api.resumeTask).mock.calls[0][1];
    await fireEvent.click(screen.getByRole('button', { name: '展开预算详情' }));
    await fireEvent.click(screen.getByRole('button', { name: '收起预算详情' }));
    await fireEvent.click(screen.getByRole('button', { name: '重试本次恢复' }));
    await waitFor(() => expect(resumed).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.resumeTask).mock.calls[1][1]).toEqual(first);
    expect(first).toMatchObject({ add_requests: 2 });
});
it('shows unlimited dimensions and separates manual pause', async () => {
    render(h(TaskBudgetPanel, { "task": { task_id: 't', status: 'paused', budget: { ...budget, pause_reason: null, limits: { max_requests: 0, max_cost_yuan: 0, max_runtime_seconds: 0 } } }, "onResumed": vi.fn() }, []));
    expect(screen.getByText(/不限/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '追加并继续' })).toBeNull();
});
function timeline(status: 'running' | 'done' | 'paused' | 'queued', taskBudget: import('../../../src/types').TaskBudgetView = budget) {
    return h(TaskTimeline, { "taskId": "t", "phase": "live", "status": status, "budget": taskBudget, "nodes": [], "runs": [], "progress": null, "error": null, "onRetry": () => { }, "refresh": () => { } }, []);
}
it.each(['running', 'done'] as const)('hides ordinary %s budget internals until deliberate expansion', async (status) => {
    render(timeline(status));
    expect(screen.queryByText(/未确认预留/)).toBeNull();
    expect(screen.queryByText(/运行 10 秒/)).toBeNull();
    const expand = screen.getByRole('button', { name: '展开预算详情' });
    expect(expand.getAttribute('aria-expanded')).toBe('false');
    expand.focus();
    expect(document.activeElement).toBe(expand);
    await fireEvent.click(expand);
    expect(expand.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText(/未确认预留：¥0.2000/)).toBeTruthy();
    expect(screen.getByText(/请求 1 \/ 1/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: '收起预算详情' }));
    expect(screen.queryByText(/未确认预留/)).toBeNull();
});
it('keeps paused budget extension accessible while technical details are collapsed', async () => {
    vi.mocked(api.resumeTask).mockResolvedValue({ task_id: 't', status: 'queued' });
    render(timeline('paused'));
    expect(screen.queryByText(/未确认预留/)).toBeNull();
    await fireEvent.input(screen.getByLabelText('追加请求次数'), { target: { value: '2' } });
    await fireEvent.click(screen.getByRole('button', { name: '追加并继续' }));
    await waitFor(() => expect(api.resumeTask).toHaveBeenCalledWith('t', expect.objectContaining({ add_requests: 2 })));
});
it('keeps uncertain publication repair accessible without expanding technical details', async () => {
    vi.mocked(api.resumeTask).mockResolvedValue({ task_id: 't', status: 'queued' });
    render(timeline('queued', { ...budget, resume_publication: 'uncertain' }));
    expect(screen.queryByText(/未确认预留/)).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: '重新投递（不追加额度）' }));
    await waitFor(() => expect(api.resumeTask).toHaveBeenCalledWith('t', expect.objectContaining({ add_requests: 0, add_cost_yuan: 0, add_runtime_seconds: 0 })));
});
