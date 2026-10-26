import { h, ref } from 'vue'

// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from '../workspaceTestUtils';
import { createMemoryRouter, RouterProvider } from '../workspaceRouterTestUtils';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../../src/lib/api';
import { openSSE, type SSEEvent } from '../../../src/lib/sse';
import type { ChapterMeta, TaskDetail, TaskSummary } from '../../../src/types';
import WorkspacePage from './WorkspacePage.vue';
vi.mock('../../../src/lib/writingResources', async (original) => ({
    ...await original<typeof import('../../../src/lib/writingResources')>(),
    writingResources: {
        updates: async () => ({ items: [] }),
        snapshot: async () => ({ revision: 0, configured: false, selections: [] }),
    },
}));
vi.mock('../authContext', () => ({
    useAuth: () => ({ logout: vi.fn(), session: ref(null) }),
}));
vi.mock('../components/ProjectRail.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/LessonsPanel.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/AuditPanel.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/CandidatePanel.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/GenerationPanel.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/TaskTimeline.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/ChapterEditor.vue', () => ({ default: () => h("div", {}, ["saved-chapter"]) }));
vi.mock('../components/ChapterPlanPanel.vue', () => ({ default: () => h("section", {}, ["live-plan-page"]),
}));
vi.mock('../../../src/lib/sse', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../../../src/lib/sse')>()),
    openSSE: vi.fn(),
}));
vi.mock('../../../src/lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../src/lib/api')>();
    return {
        ...actual,
        api: {
            ...actual.api,
            listProjects: vi.fn(),
            listChapters: vi.fn(),
            listCandidates: vi.fn(),
            listGraph: vi.fn(),
            listForeshadows: vi.fn(),
            listTasks: vi.fn(),
            getTask: vi.fn(),
        },
    };
});
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});
it('replaces the full Plan page with live正文 before the model stream completes', async () => {
    const chapter: ChapterMeta = {
        id: 'chapter-14', chapter_seq: 14, title: null,
        status: 'planning', word_count: 0, summary: null,
    };
    const summary: TaskSummary = {
        task_id: 'task-14', task_type: 'chapter_generate', status: 'running',
        chapter_seq: 14, batch_size: null, batch_current: null,
        cost_total: 0, error: null, created_at: null,
    };
    const detail: TaskDetail = {
        task_id: 'task-14', task_type: 'chapter_generate', status: 'running',
        payload: { seq: 14, mode: 'auto' }, error: null, retry_count: 0,
        trace_id: null, chapter_seq: 14, batch_task_id: null,
        created_at: null, cost_total: 0, runs: [],
    };
    vi.mocked(api.listProjects).mockResolvedValue([]);
    vi.mocked(api.listChapters).mockResolvedValue([chapter]);
    vi.mocked(api.listCandidates).mockResolvedValue([]);
    vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(api.listForeshadows).mockResolvedValue([]);
    vi.mocked(api.listTasks).mockResolvedValue([summary]);
    vi.mocked(api.getTask).mockResolvedValue(detail);
    let startWrite!: () => void;
    let finishStream!: () => void;
    const waitForWrite = new Promise<void>((resolve) => { startWrite = resolve; });
    const waitForFinish = new Promise<void>((resolve) => { finishStream = resolve; });
    const event = (patch: Partial<SSEEvent>): SSEEvent => ({
        type: 'artifact_delta', task_id: 'task-14', node: '', status: '', message: '',
        stage: 'plan', chapter_seq: 14, attempt: 1, offset: 0, done: 0, total: 0,
        artifact_id: 'plan-1', content: '', artifact: '', ...patch,
    });
    vi.mocked(openSSE).mockImplementation(async (_url, onEvent) => {
        onEvent(event({ type: 'status', status: 'running' }));
        onEvent(event({ type: 'artifact_reset' }));
        onEvent(event({ type: 'artifact_delta', content: '{"goals":["承接"]}' }));
        onEvent(event({ type: 'artifact_complete', offset: 16 }));
        await waitForWrite;
        onEvent(event({
            type: 'artifact_reset', stage: 'write', artifact_id: 'write-1',
        }));
        onEvent(event({
            type: 'artifact_delta', stage: 'write', artifact_id: 'write-1',
            content: '=== CONTENT ===\n模型仍在写，这段已经到达浏览器',
        }));
        await waitForFinish;
        onEvent(event({
            type: 'artifact_complete', stage: 'write', artifact_id: 'write-1', offset: 21,
        }));
        onEvent(event({ type: 'status', status: 'awaiting_review' }));
        return { reason: 'terminal' };
    });
    const router = createMemoryRouter([{ path: '/projects/:projectId', element: h(WorkspacePage, {}, []) }], { initialEntries: ['/projects/project-1'] });
    render(h(RouterProvider, { "router": router }, []));
    expect(await screen.findByText('live-plan-page')).toBeTruthy();
    expect(screen.queryByText('模型仍在写，这段已经到达浏览器')).toBeNull();
    await act(async () => { startWrite(); });
    expect(await screen.findByText('模型仍在写，这段已经到达浏览器')).toBeTruthy();
    expect(screen.getByText('实时写作', { selector: 'span' })).toBeTruthy();
    expect(screen.queryByText('live-plan-page')).toBeNull();
    expect(vi.mocked(openSSE).mock.results[0]?.type).toBe('return');
    await act(async () => { finishStream(); });
    await waitFor(() => expect(api.getTask).toHaveBeenCalled());
});
