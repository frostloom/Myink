import { h } from 'vue'

// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '../workspaceTestUtils';
import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError } from '../../../src/lib/api';
import type { ChapterMeta } from '../../../src/types';
import GenerationPanel from './GenerationPanel.vue';
vi.mock('../../../src/lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../src/lib/api')>();
    return {
        ...actual,
        api: {
            ...actual.api,
            generateChapter: vi.fn(),
            generateBatch: vi.fn(),
        },
    };
});
const chapter: ChapterMeta = {
    id: 'chapter-16',
    chapter_seq: 16,
    title: '第十六章',
    status: 'confirmed',
    word_count: 3000,
    summary: null,
};
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
});
it('shows the writing controls by default and starts the next chapter from a direct click', async () => {
    vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'task-17', trace_id: 'trace-17', status: 'queued' });
    const onTaskStart = vi.fn();
    render(h(GenerationPanel, { "projectId": "project-1", "chapters": [chapter], "selectedChapter": chapter, "onTaskStart": onTaskStart }, []));
    const button = screen.getByRole('button', { name: '写下一章（第 17 章）' });
    expect(button).toBeTruthy();
    await fireEvent.click(button);
    await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith('project-1', 'chapter-16', { seq: 17, mode: 'auto' }));
    expect(onTaskStart).toHaveBeenCalledWith('task-17', undefined, 17, 'auto');
    expect((await screen.findByRole('status')).textContent).toContain('第 17 章写作任务已创建');
    expect(screen.queryByRole('progressbar')).toBeNull();
});
it('passes the optional writing instruction and exposes a request error', async () => {
    vi.mocked(api.generateChapter).mockRejectedValue(new ApiError(429, 'CONCURRENCY_LIMIT', null));
    render(h(GenerationPanel, { "projectId": "project-1", "chapters": [chapter], "selectedChapter": chapter, "onTaskStart": () => { } }, []));
    await fireEvent.input(screen.getByLabelText('写作指令（可留空）'), { target: { value: '承接上一章结尾' } });
    await fireEvent.click(screen.getByRole('button', { name: '写下一章（第 17 章）' }));
    await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith('project-1', 'chapter-16', { seq: 17, mode: 'auto', user_instruction: '承接上一章结尾' }));
    expect((await screen.findByRole('alert')).textContent).toContain('本书已有进行中的任务');
});
it('continues a failed empty placeholder instead of skipping to another chapter', async () => {
    vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'task-17b', trace_id: 'trace-17b', status: 'queued' });
    const placeholder: ChapterMeta = {
        id: 'chapter-17-writing',
        chapter_seq: 17,
        title: null,
        status: 'failed',
        word_count: 0,
        summary: null,
    };
    render(h(GenerationPanel, { "projectId": "project-1", "chapters": [chapter, placeholder], "selectedChapter": placeholder, "onTaskStart": () => { } }, []));
    await fireEvent.click(screen.getByRole('button', { name: '继续生成第 17 章' }));
    await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith('project-1', 'chapter-17-writing', { seq: 17, mode: 'auto' }));
});
it('shows the target chapter as running and prevents a duplicate start', async () => {
    const writing: ChapterMeta = {
        id: 'chapter-17-writing',
        chapter_seq: 17,
        title: null,
        status: 'writing',
        word_count: 0,
        summary: null,
    };
    render(h(GenerationPanel, { "projectId": "project-1", "chapters": [chapter, writing], "selectedChapter": writing, "onTaskStart": () => { } }, []));
    expect(screen.getByText('当前生成：第 17 章')).toBeTruthy();
    expect((screen.getByRole('button', { name: '第 17 章生成中…' }) as HTMLButtonElement).disabled).toBe(true);
});
it('binds a batch task to its first chapter page', async () => {
    vi.mocked(api.generateBatch).mockResolvedValue({ task_id: 'batch-17', trace_id: 'trace-batch', status: 'queued' });
    const onTaskStart = vi.fn();
    render(h(GenerationPanel, { "projectId": "project-1", "chapters": [chapter], "selectedChapter": chapter, "onTaskStart": onTaskStart }, []));
    await fireEvent.click(screen.getByRole('button', { name: '发起批次' }));
    await waitFor(() => expect(api.generateBatch).toHaveBeenCalledWith('project-1', { size: 3, start: 17 }));
    expect(onTaskStart).toHaveBeenCalledWith('batch-17', 3, 17);
});
it('clears the previous book notice when switching projects', async () => {
    vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'task-17', trace_id: 'trace-17', status: 'queued' });
    const { rerender } = render(h(GenerationPanel, { "projectId": "project-a", "chapters": [chapter], "selectedChapter": chapter, "onTaskStart": () => { } }, []));
    await fireEvent.click(screen.getByRole('button', { name: '写下一章（第 17 章）' }));
    expect((await screen.findByRole('status')).textContent).toContain('第 17 章写作任务已创建');
    expect(screen.queryByRole('progressbar')).toBeNull();
    await rerender(h(GenerationPanel, { "projectId": "project-b", "chapters": [], "selectedChapter": null, "onTaskStart": () => { } }, []));
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByText('下一章：第 1 章')).toBeTruthy();
});
it('manual mode is sent with the chapter request and disables batch generation', async () => {
    vi.mocked(api.generateChapter).mockResolvedValue({ task_id: 'manual-17', trace_id: 'trace-manual', status: 'queued' });
    const onTaskStart = vi.fn();
    render(h(GenerationPanel, { "projectId": "project-1", "chapters": [chapter], "selectedChapter": chapter, "onTaskStart": onTaskStart }, []));
    await fireEvent.click(screen.getByRole('button', { name: '手动确认 Plan' }));
    expect((screen.getByLabelText('批次生成') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: '发起批次' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('手动模式需要逐章确认计划，批量生成已禁用。')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: '写下一章（第 17 章）' }));
    await waitFor(() => expect(api.generateChapter).toHaveBeenCalledWith('project-1', 'chapter-16', { seq: 17, mode: 'manual' }));
    expect(onTaskStart).toHaveBeenCalledWith('manual-17', undefined, 17, 'manual');
});
it.each(['next', 'rewrite', 'batch'] as const)('ignores a late %s response after switching projects', async (action) => {
    let finish!: (value: Awaited<ReturnType<typeof api.generateChapter>>) => void;
    const pending = new Promise<Awaited<ReturnType<typeof api.generateChapter>>>(resolve => { finish = resolve; });
    vi.mocked(api.generateChapter).mockReturnValue(pending);
    vi.mocked(api.generateBatch).mockReturnValue(pending);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const onTaskStart = vi.fn();
    const props = { chapters: [chapter], selectedChapter: chapter, onTaskStart };
    const view = render(h(GenerationPanel, { ...props, "projectId": "a" }, []));
    const label = action === 'next' ? '写下一章（第 17 章）' : action === 'rewrite' ? '重写第 16 章' : '发起批次';
    await fireEvent.click(screen.getByRole('button', { name: label }));
    await view.rerender(h(GenerationPanel, { ...props, "projectId": "b" }, []));
    await act(async () => finish({ task_id: 'task-a', trace_id: 'trace-a', status: 'queued' }));
    expect(onTaskStart).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).toBeNull();
});
it('does not send a request after an old project preflight finishes', async () => {
    let finish!: (allowed: boolean) => void;
    const beforeGenerate = () => new Promise<boolean>(resolve => { finish = resolve; });
    const props = { chapters: [], selectedChapter: null, onTaskStart: vi.fn(), beforeGenerate };
    const view = render(h(GenerationPanel, { ...props, "projectId": "a" }, []));
    await fireEvent.click(screen.getByRole('button', { name: '写下一章（第 1 章）' }));
    await view.rerender(h(GenerationPanel, { ...props, "projectId": "b" }, []));
    await act(async () => finish(true));
    expect(api.generateChapter).not.toHaveBeenCalled();
});
it('does not clear the new project busy state when an old request fails', async () => {
    let fail!: (error: Error) => void;
    vi.mocked(api.generateChapter).mockImplementation(pid => pid === 'a'
        ? new Promise((_resolve, reject) => { fail = reject; }) : new Promise(() => { }));
    const props = { chapters: [], selectedChapter: null, onTaskStart: vi.fn() };
    const view = render(h(GenerationPanel, { ...props, "projectId": "a" }, []));
    await fireEvent.click(screen.getByRole('button', { name: '写下一章（第 1 章）' }));
    await view.rerender(h(GenerationPanel, { ...props, "projectId": "b" }, []));
    await fireEvent.click(screen.getByRole('button', { name: '写下一章（第 1 章）' }));
    await act(async () => fail(new Error('old failure')));
    expect(screen.queryByRole('alert')).toBeNull();
    expect((screen.getByRole('button', { name: '发起中…' }) as HTMLButtonElement).disabled).toBe(true);
});
it('marks explicit rewrite as retaining the current plan',async()=>{
 vi.spyOn(window,'confirm').mockReturnValue(true)
 vi.mocked(api.generateChapter).mockResolvedValue({task_id:'rewrite-16',trace_id:'trace',status:'queued'})
 const onTaskStart=vi.fn()
 render(h(GenerationPanel,{projectId:'project-1',chapters:[chapter],selectedChapter:chapter,onTaskStart}))
 await fireEvent.click(screen.getByRole('button',{name:'重写第 16 章'}))
 await waitFor(()=>expect(onTaskStart).toHaveBeenCalledWith('rewrite-16',undefined,16,'auto','rewrite'))
})
it('offers explicit replan separately from plan-preserving rewrite',async()=>{
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(true)
 vi.mocked(api.generateChapter).mockResolvedValue({task_id:'replan-16',trace_id:'trace',status:'queued'})
 const onTaskStart=vi.fn()
 render(h(GenerationPanel,{projectId:'project-1',chapters:[chapter],selectedChapter:chapter,onTaskStart}))
 await fireEvent.click(screen.getByRole('button',{name:'重新规划第 16 章'}))
 expect(confirm).toHaveBeenCalledWith(expect.stringContaining('重新生成计划和正文'))
 await waitFor(()=>expect(api.generateChapter).toHaveBeenCalledWith('project-1','chapter-16',{seq:16,rewrite:true,replan:true,mode:'auto'}))
 expect(onTaskStart).toHaveBeenCalledWith('replan-16',undefined,16,'auto')
})

it.each(['next', 'rewrite', 'replan', 'batch'] as const)('announces pending %s immediately and clears it on failure', async action => {
 let reject!: (error: Error) => void
 const pending = new Promise<Awaited<ReturnType<typeof api.generateChapter>>>((_resolve, fail) => { reject = fail })
 vi.mocked(api.generateChapter).mockReturnValue(pending)
 vi.mocked(api.generateBatch).mockReturnValue(pending)
 vi.spyOn(window, 'confirm').mockReturnValue(true)
 render(h(GenerationPanel, {projectId:'p', chapters:[chapter], selectedChapter:chapter, onTaskStart:()=>{}}))
 const labels = {next:'写下一章（第 17 章）', rewrite:'重写第 16 章', replan:'重新规划第 16 章', batch:'发起批次'}
 const expected = {next:'正在提交章节写作', rewrite:'正在提交重写', replan:'正在提交重新规划', batch:'正在提交批量写作'}
 await fireEvent.click(screen.getByRole('button', {name:labels[action]}))
 expect(screen.getByRole('status').textContent).toContain(expected[action])
 expect(screen.getByRole('progressbar').hasAttribute('value')).toBe(false)
 expect((screen.getByLabelText('写作指令（可留空）') as HTMLTextAreaElement).disabled).toBe(false)
 await act(async () => reject(new Error('offline')))
 expect(await screen.findByRole('alert')).toBeTruthy()
 expect(screen.queryByRole('progressbar')).toBeNull()
 expect((screen.getByRole('button', {name:labels[action]}) as HTMLButtonElement).disabled).toBe(false)
})
it('keeps batch input and instruction after guest quota refusal and explains reducing the batch or registering', async () => {
    vi.mocked(api.generateBatch).mockRejectedValue(new ApiError(429, 'GUEST_QUOTA_EXHAUSTED', null));
    render(h(GenerationPanel, { projectId: 'project-1', chapters: [chapter], selectedChapter: chapter, onTaskStart: () => {} }));
    await fireEvent.input(screen.getByLabelText('批次生成'), { target: { value: '5' } });
    await fireEvent.input(screen.getByLabelText('写作指令（可留空）'), { target: { value: '保留人物伏笔' } });
    await fireEvent.click(screen.getByRole('button', { name: '发起批次' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('减少章数');
    expect(alert.textContent).toContain('注册');
    expect((screen.getByLabelText('批次生成') as HTMLInputElement).value).toBe('5');
    expect((screen.getByLabelText('写作指令（可留空）') as HTMLTextAreaElement).value).toBe('保留人物伏笔');
    expect((screen.getByRole('button', { name: '发起批次' }) as HTMLButtonElement).disabled).toBe(false);
});
