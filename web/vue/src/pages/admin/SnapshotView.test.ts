import { defineComponent,h,type VNode } from 'vue';
// @vitest-environment jsdom
import { cleanup,fireEvent,screen,render as vueRender,waitFor } from '@testing-library/vue';
import { afterEach,expect,it,vi } from 'vitest';
import { adminApi,type AdminSnapshot } from '../../../../src/lib/adminApi';
import { SnapshotView } from './SnapshotView';
vi.mock('../../../../src/lib/adminApi', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../../src/lib/adminApi')>();
    return { ...actual, adminApi: { ...actual.adminApi, getSnapshot: vi.fn() } };
});
function snapshot(overrides: Partial<AdminSnapshot> = {}): AdminSnapshot {
    return {
        id: 31, project_id: 'book-1', task_id: 'task-1', chapter_seq: 4, stage: 'write', attempt: 1,
        model_id: 'model-a', input_tokens: 2000, output_tokens: 3000, cache_hit: false,
        duration_ms: 4200, cost_est: 0.1234, retry_count: 0, degraded: false,
        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
        payload: {
            data: {
                _capture: { scope: 'snapshot', selective: true, truncated: false, redacted: false },
                prompt: {
                    bytes: 4096, truncated: false,
                    sections: [
                        { role: 'system', name: '题材参考文档', policy: 'hash', bytes: 3000, sha256: 'b'.repeat(64) },
                        { role: 'system', name: '世界观硬约束', policy: 'full', text: '灵气不可外放' },
                    ],
                },
                output: { bytes: 5200, sha256: 'c'.repeat(64), excerpt: '他踏进山门。' },
            },
            truncated: true, redacted: false,
            limits: { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 },
        },
        snapshot_missing: false,
        ...overrides,
    };
}
function renderSnapshot() {
    return render(h(SnapshotView, { "token": "token-admin", "snapshotId": 31, "onForbidden": vi.fn() }));
}
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});
it('marks hash-only sections as retained by hash and never invents their text', async () => {
    vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot());
    renderSnapshot();
    expect(await screen.findByText('部分内容已留存')).toBeTruthy();
    expect(screen.getByText('内容已截断')).toBeTruthy();
    expect(screen.getByText('未保存正文')).toBeTruthy();
    expect(screen.getByText('题材参考文档')).toBeTruthy();
    expect(screen.getByText('此部分未保存正文，无法还原当时的具体内容。')).toBeTruthy();
    expect(screen.getByText('灵气不可外放')).toBeTruthy();
    expect(screen.getByText('他踏进山门。')).toBeTruthy();
});
it('offers only the sub-views this stage actually captured', async () => {
    vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot({
        stage: 'recall',
        payload: {
            data: {
                recall: {
                    counts: { long_term_facts: 1 }, stats: { share: 0.5 },
                    groups: { long_term_facts: [{ fact_id: 'f1', content: '灵气不可外放', is_hard: true }] },
                },
            },
            truncated: false, redacted: false,
            limits: { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 },
        },
    }));
    renderSnapshot();
    const nav = await screen.findByRole('navigation', { name: '快照子视图' });
    expect(nav.textContent).toBe('前情与资料必守设定');
    expect(screen.getByRole('button', { name: '前情与资料' }).getAttribute('aria-pressed')).toBe('true');
    await fireEvent.click(screen.getByRole('button', { name: '必守设定' }));
    expect(await screen.findByText('灵气不可外放')).toBeTruthy();
    expect(screen.getByText('作品中必须遵守的事实（1）')).toBeTruthy();
    expect(screen.queryByText('创作要求')).toBeNull();
});
it('tells the operator a legacy row has no payload instead of showing empty tables', async () => {
    vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot({
        snapshot_missing: true,
        payload: {
            data: null, truncated: false, redacted: false,
            limits: { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 },
        },
    }));
    renderSnapshot();
    expect(await screen.findByText('这条旧记录未保存创作依据和输出内容，只能查看调用时间与用量。')).toBeTruthy();
    expect(screen.queryByRole('navigation', { name: '快照子视图' })).toBeNull();
    expect(screen.getByText(/写作 · 第 4 章 · 第 1 次/)).toBeTruthy();
});
it('reloads the same snapshot when asked to refresh', async () => {
    vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot());
    renderSnapshot();
    await screen.findByText('部分内容已留存');
    await fireEvent.click(screen.getByRole('button', { name: '刷新当前视图' }));
    await waitFor(() => expect(adminApi.getSnapshot).toHaveBeenCalledTimes(2));
    expect(adminApi.getSnapshot).toHaveBeenLastCalledWith('token-admin', 31, expect.any(AbortSignal));
});
it('keeps fingerprints and collection details in diagnostics while showing readable prompt purposes', async () => {
    vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot());
    renderSnapshot();
    await screen.findByText('题材参考文档');
    expect(screen.getAllByText('角色职责与创作要求').length).toBeGreaterThan(0);
    expect(screen.queryByText('system')).toBeNull();
    expect(screen.queryByText('仅存哈希')).toBeNull();
    expect(screen.queryByText(/bbbbbbbbbbbb/)).toBeNull();
    expect(screen.getByText('此部分未保存正文，无法还原当时的具体内容。')).toBeTruthy();
});
it('shows findings as problem cards and replacement content as before/after passages', async () => {
    vi.mocked(adminApi.getSnapshot).mockResolvedValue(snapshot({ payload: { ...snapshot().payload, data: { findings: [{ severity: 'major', conflict_type: 'timeline', scope: 'local', source: 'L1', suggestion: '统一回家时间', evidence: [{ chapter: 4, quote: '他在午后来到' }] }], applied_spans: [{ target: '昨日清晨', replacement: '昨日午后' }] } } }));
    renderSnapshot();
    expect(await screen.findByText('统一回家时间')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: '文字修改' }));
    expect(screen.getByText('修改前')).toBeTruthy();
    expect(screen.getByText('昨日清晨')).toBeTruthy();
    expect(screen.getByText('修改后')).toBeTruthy();
});
function render(node: VNode) { return vueRender(defineComponent({ render: () => node })); }
