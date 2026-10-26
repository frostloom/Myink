import { defineComponent,h,type VNode } from 'vue';
// @vitest-environment jsdom
import { cleanup,fireEvent,screen,render as vueRender,waitFor } from '@testing-library/vue';
import { afterEach,expect,it,vi } from 'vitest';
import { adminApi } from '../../../../src/lib/adminApi';
import { AdminTrends } from './AdminTrends';
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
vi.mock('echarts', () => ({ init: () => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }) }));
it('loads UTC dates, shows real empty state and supports seven days', async () => {
    const spy = vi.spyOn(adminApi, 'getTrends').mockResolvedValue({ start_date: '2026-01-01', end_date: '2026-01-30', timezone: 'UTC', items: [] });
    render(h(AdminTrends, { "token": "token", "onForbidden": () => { } }));
    await screen.findByText('所选日期暂无记录');
    expect(screen.getByText(/UTC/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: '近7天' }));
    await waitFor(() => expect(spy.mock.calls.length).toBe(2));
    const [, start, end] = spy.mock.calls[1];
    expect((Date.parse(end) - Date.parse(start)) / 86400000).toBe(6);
    spy.mockRestore();
});
it('renders real summary and separate cost and token charts', async () => {
    vi.spyOn(adminApi, 'getTrends').mockResolvedValue({ start_date: '2026-01-01', end_date: '2026-01-01', timezone: 'UTC', items: [{ day: '2026-01-01', user_count: 2, project_count: 1, chapter_count: 3, task_count: 4, run_count: 5, input_tokens: 100, output_tokens: 75, cost_est: 0.25 }] });
    render(h(AdminTrends, { "token": "token", "onForbidden": () => { } }));
    expect(await screen.findByText('100')).toBeTruthy();
    expect(screen.getByText('估算费用（人民币）')).toBeTruthy();
    expect(screen.getByText(/费用为估算人民币金额/)).toBeTruthy();
    expect(screen.getByText('0.25')).toBeTruthy();
    expect(screen.queryByText(/美元/)).toBeNull();
    expect(screen.getByRole('img', { name: '每日输入与输出 Token' })).toBeTruthy();
    expect(screen.getByRole('img', { name: '每日估算费用' })).toBeTruthy();
    await fireEvent.update(screen.getByLabelText('开始日期'), '2025-01-01');
    await fireEvent.click(screen.getByRole('button', { name: '查询趋势' }));
    expect(screen.getByRole('alert').textContent).toContain('90');
});
it('shows request failure with retry', async () => {
    vi.spyOn(adminApi, 'getTrends').mockRejectedValue(new Error('offline'));
    render(h(AdminTrends, { "token": "token", "onForbidden": () => { } }));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试' })).toBeTruthy();
});
function render(node: VNode) { return vueRender(defineComponent({ render: () => node })); }
