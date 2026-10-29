import { h, ref, toValue } from 'vue'
import { useRoute } from 'vue-router'
// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '../workspaceTestUtils';
import { createMemoryRouter, RouterProvider } from '../workspaceRouterTestUtils';
import { afterEach, expect, it, vi } from 'vitest';
import { api } from '../../../src/lib/api';
import type { AgentRun, ChapterMeta, TaskStatus } from '../../../src/types';
import WorkspacePage from './WorkspacePage.vue';
const authSession = ref({ userId: 'test-user', username: 'alice' });
const liveTask = vi.hoisted(() => ({
    status: 'running' as TaskStatus,
    refresh: vi.fn(),
    retry: vi.fn(),
    runs: [] as AgentRun[],
    shortProgress: null as {
        stage: string;
        current: number;
        total: number;
    } | null,
    artifacts: [] as Array<{
        artifactId: string;
        taskId: string;
        stage: string;
        chapterSeq: number;
        attempt: number;
        content: string;
        complete: boolean;
        failed: boolean;
        artifact: unknown | null;
        message: string | null;
    }>,
}));
vi.mock('../../../src/lib/writingResources', async (original) => ({
    ...await original<typeof import('../../../src/lib/writingResources')>(),
    writingResources: {
        updates: async () => ({ items: [] }),
        snapshot: async () => ({ revision: 0, configured: false, selections: [] }),
    },
}));
vi.mock('../authContext', () => ({
    useAuth: () => ({ logout: vi.fn(), session: authSession }),
}));
vi.mock('../composables/useTaskEvents', () => ({
    useTaskEvents: (taskIdSource: import('vue').MaybeRefOrGetter<string | null>) => {
        const route = useRoute();
        const snapshot = () => {
            void route.fullPath;
            const taskId = toValue(taskIdSource);
            return ({
                phase: taskId ? (['done', 'failed', 'cancelled'].includes(liveTask.status) ? 'terminal' : 'running') : 'idle',
                status: taskId ? liveTask.status : null,
                nodes: [],
                artifacts: taskId ? liveTask.artifacts : [],
                runs: taskId ? liveTask.runs : [],
                progress: null,
                budget: { requests_used: 7 },
                shortProgress: taskId ? liveTask.shortProgress : null,
                error: null,
                payload: {},
                lastEventId: null,
                stop: vi.fn(),
                retry: liveTask.retry,
                refresh: liveTask.refresh,
            });
        };
        return new Proxy({} as ReturnType<typeof snapshot>, { get: (_target, key) => snapshot()[key as keyof ReturnType<typeof snapshot>] });
    },
}));
vi.mock('../components/ProjectRail.vue', () => ({ default: () => h("div", {}, []) }));
vi.mock('../components/LessonsPanel.vue', () => ({ default: () => h("div", {}, ["lessons-panel"]) }));
vi.mock('../components/AuditPanel.vue', () => ({ default: () => h("div", {}, ["audit-panel"]) }));
vi.mock('../components/CandidatePanel.vue', () => ({ default: () => h("div", {}, ["candidate-panel"]) }));
vi.mock('../components/ChapterEditor.vue', () => ({ default: ({ chapter, allowMemoryCorrection }: {
        chapter: ChapterMeta;
        allowMemoryCorrection?: boolean;
    }) => h("div", {}, [h("span", {}, ["editor-", chapter.chapter_seq]), h("span", {}, ["memory-correction-", String(allowMemoryCorrection)])]),
}));
vi.mock('../components/ChapterPlanPanel.vue', () => ({ default: ({ taskId, chapterSeq, onConfirmed }: {
        taskId: string | null;
        chapterSeq: number;
        onConfirmed: (taskId: string, chapterSeq: number) => void;
    }) => h("div", {}, [h("span", {}, ["plan-page-", chapterSeq]), h("button", { "type": "button", "onClick": () => taskId && onConfirmed(taskId, chapterSeq) }, ["confirm-plan"])]),
}));
vi.mock('../components/StreamingChapterView.vue', () => ({ default: ({ chapterSeq }: {
        chapterSeq: number;
    }) => (h("section", { "aria-label": `第 ${chapterSeq} 章生成正文` }, ["write-page-", chapterSeq])),
}));
vi.mock('../components/ChapterList.vue', () => ({ default: ({ chapters, onSelect }: {
        chapters: ChapterMeta[];
        onSelect: (id: string) => void;
    }) => (h("div", {}, [chapters.map((chapter) => (h("button", { "key": chapter.id, "type": "button", "onClick": () => onSelect(chapter.id) }, ["chapter-", chapter.chapter_seq])))])),
}));
vi.mock('../components/GenerationPanel.vue', () => ({ default: ({ onTaskStart }: {
        onTaskStart: (id: string, total?: number, seq?: number) => void;
    }) => (h("div", {}, [h("span", {}, ["generation-panel"]), h("button", { "type": "button", "onClick": () => onTaskStart('task-13', undefined, 13) }, ["start-13"])])),
}));
vi.mock('../components/TaskTimeline.vue', () => ({ default: ({ taskId, chapterSeq, runs, liveNode, budget }: {
        taskId: string | null;
        chapterSeq: number | null;
        runs: AgentRun[];
        liveNode: string | null;
        budget?: {
            requests_used: number;
        };
    }) => (h("div", {}, [h("div", {}, ["timeline-", taskId ?? 'none', "-chapter-", chapterSeq ?? 'none']), h("span", {}, ["flow-runs-", runs.length]), h("span", {}, ["flow-budget-", budget?.requests_used ?? 'missing']), h("span", {}, ["flow-live-", liveNode ?? 'none'])])),
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
            generateShort: vi.fn(),
            resumeTask: vi.fn(),
        },
    };
});
afterEach(() => {
    cleanup();
    authSession.value = { userId: 'test-user', username: 'alice' };
    vi.clearAllMocks();
    liveTask.artifacts = [];
    liveTask.runs = [];
    liveTask.status = 'running';
    liveTask.shortProgress = null;
    sessionStorage.clear();
    // 右栏展开偏好会跨用例残留，下一个用例就该从「默认收起」开始了。
    localStorage.clear();
});
it('does not let delayed initial task history replace a newly started task', async () => {
    let resolveHistory!: (value: Awaited<ReturnType<typeof api.listTasks>>) => void;
    vi.mocked(api.listProjects).mockResolvedValue([]);
    vi.mocked(api.listChapters).mockResolvedValue(Array.from({ length: 12 }, (_, i) => ({ id: `chapter-${i + 1}`, chapter_seq: i + 1, title: `第${i + 1}章`, summary: null, status: 'confirmed' as const, word_count: 2000 })));
    vi.mocked(api.listCandidates).mockResolvedValue([]);
    vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(api.listForeshadows).mockResolvedValue([]);
    vi.mocked(api.listTasks).mockImplementation((_pid, seq) => seq === undefined
        ? new Promise(resolve => { resolveHistory = resolve; }) : Promise.resolve([]));
    const router = createMemoryRouter([{ path: '/projects/:projectId', element: h(WorkspacePage) }], { initialEntries: ['/projects/project-1'] });
    render(h(RouterProvider, { router }));
    await waitFor(() => expect(resolveHistory).toBeTypeOf('function'));
    await fireEvent.click(screen.getByRole('button', { name: '生成与校验' }));
    await fireEvent.click(screen.getByRole('button', { name: 'start-13' }));
    expect(screen.getByText('timeline-task-13-chapter-13')).toBeTruthy();
    // Snapshot was taken while a previous chapter-13 attempt was running.
    // That attempt can fail before the new task starts, while its response is delayed.
    resolveHistory([{ task_id: 'task-old', task_type: 'chapter_generate', status: 'running', chapter_seq: 13,
        batch_size: null, batch_current: null, cost_total: 0, error: null, created_at: null }]);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText('timeline-task-13-chapter-13')).toBeTruthy();
});

function setupHistory() {
    vi.mocked(api.listProjects).mockResolvedValue([]);
    vi.mocked(api.listCandidates).mockResolvedValue([]);
    vi.mocked(api.listGraph).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(api.listForeshadows).mockResolvedValue([]);
    vi.mocked(api.listTasks).mockResolvedValue([]);
    vi.mocked(api.listChapters).mockResolvedValue([]);
    const router = createMemoryRouter([{ path: '/projects/:projectId', element: h(WorkspacePage) }], { initialEntries: ['/projects/project-1'] });
    return router;
}
const oldTask = { task_id: 'task-old', task_type: 'chapter_generate', status: 'running' as const, chapter_seq: 13,
    batch_size: null, batch_current: null, cost_total: 0, error: null, created_at: null };
it('restores an existing initial task when no newer task was started', async () => {
    const router = setupHistory();
    vi.mocked(api.listTasks).mockResolvedValue([oldTask]);
    render(h(RouterProvider, { router }));
    await screen.findByRole('button', { name: '生成与校验' });
    await fireEvent.click(screen.getByRole('button', { name: '生成与校验' }));
    await screen.findByText('timeline-task-old-chapter-13');
});
it('does not auto-select a late initial chapter after starting a new task', async () => {
    const router = setupHistory();
    let finish!: (chapters: ChapterMeta[]) => void;
    vi.mocked(api.listChapters).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    render(h(RouterProvider, { router }));
    await screen.findByRole('button', { name: '生成与校验' });
    await fireEvent.click(screen.getByRole('button', { name: '生成与校验' }));
    await fireEvent.click(screen.getByRole('button', { name: 'start-13' }));
    finish([{ id: 'old-review', chapter_seq: 12, title: null, summary: null, status: 'awaiting_review', word_count: 2000 }]);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText('timeline-task-13-chapter-13')).toBeTruthy();
});
it.each(['project', 'account'])('discards delayed initial history after a %s round trip', async scope => {
    const router = setupHistory();
    let finish!: (tasks: typeof oldTask[]) => void;
    vi.mocked(api.listTasks).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    render(h(RouterProvider, { router }));
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    if (scope === 'project') {
        await act(async () => { await router.navigate('/projects/project-2'); });
        await act(async () => { await router.navigate('/projects/project-1'); });
    } else {
        await act(async () => { authSession.value = { userId: 'other-user', username: 'bob' }; });
        await act(async () => { authSession.value = { userId: 'test-user', username: 'alice' }; });
    }
    await fireEvent.click(screen.getByRole('button', { name: '生成与校验' }));
    finish([oldTask]);
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText('timeline-none-chapter-none')).toBeTruthy();
});
it('ignores delayed initial chapters after disposal instead of requesting task recovery', async () => {
    const router = setupHistory();
    let finish!: (chapters: ChapterMeta[]) => void;
    vi.mocked(api.listChapters).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const page = render(h(RouterProvider, { router }));
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    page.unmount();vi.mocked(api.listTasks).mockClear();finish([]);
    await act(async () => { await Promise.resolve(); });
    expect(api.listTasks).not.toHaveBeenCalled();
});
