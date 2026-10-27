import { h } from 'vue'
import { render as renderComponent } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'

// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '../workspaceTestUtils';
import { afterEach, expect, it, vi } from 'vitest';
import type { ArtifactState } from '../composables/useTaskEvents';
import { api } from '../../../src/lib/api';
import type { AgentRun, ChapterPlan, TaskControlResponse } from '../../../src/types';
import ChapterPlanPanel from './ChapterPlanPanel.vue';
vi.mock('../../../src/lib/api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../../src/lib/api')>();
    return {
        ...actual,
        api: { ...actual.api, confirmTaskPlan: vi.fn(), cancelTask: vi.fn() },
    };
});
function plan(goal: string): ChapterPlan {
    return {
        project_id: 'project-1', chapter_seq: 17,
        goals: [goal],
        scenes: [{ location_id: '东峰', participants: ['林尘'], goal: '查证线索', time: '清晨' }],
        characters: [], hooks_to_plant: [], hooks_to_resolve: [],
        expected_events: ['林尘确认吊坠纹路'], hard_constraints: ['不得升级'],
        transition: {
            mode: 'continue', anchor_quote: '他握紧残片。', pending_action: '查清纹路',
            opening_beat: '林尘沿着章尾动作抬头观察吊坠。', bridge: '',
        },
    };
}
function run(attempt: number, value: ChapterPlan): AgentRun {
    return {
        task_id: 'task-17', node: 'plan_chapter', model_id: 'stub',
        input_tokens: 1, output_tokens: 1, cache_hit: false, duration_ms: 1,
        cost_est: 0, retry_count: 0, degraded: false, error: null,
        detail: { plan: value, plan_attempt: attempt, writing_mode: 'manual' },
    };
}
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
});
it.each(['confirm', 'cancel'] as const)('ignores %s completion after its panel is unmounted', async action => {
    let finish!: (value: TaskControlResponse) => void
    const pending = new Promise<TaskControlResponse>(resolve => { finish = resolve })
    vi.mocked(api.confirmTaskPlan).mockReturnValue(pending)
    vi.mocked(api.cancelTask).mockReturnValue(pending)
    const onConfirmed = vi.fn(), onCancelled = vi.fn()
    const view = renderComponent(ChapterPlanPanel, { props: { taskId: 'task-17', chapterSeq: 17, status: 'awaiting_plan', runs: [run(1, plan('目标'))], artifact: null, onConfirmed, onCancelled } })
    await fireEvent.click(screen.getByRole('button', { name: action === 'confirm' ? '确认计划并开始写作' : '取消本次写作' }))
    view.unmount()
    finish({ task_id: 'task-17', status: action === 'confirm' ? 'queued' : 'cancelled' }); await flushPromises()
    expect(onConfirmed).not.toHaveBeenCalled()
    expect(onCancelled).not.toHaveBeenCalled()
})
it('does not associate an old confirmation with a new task or keep its edited plan', async () => {
    let finish!: (value: TaskControlResponse) => void
    vi.mocked(api.confirmTaskPlan).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const onConfirmed = vi.fn()
    const view = renderComponent(ChapterPlanPanel, { props: { taskId: 'task-17', chapterSeq: 17, status: 'awaiting_plan', runs: [run(1, plan('旧目标'))], artifact: null, onConfirmed, onCancelled: vi.fn() } })
    await fireEvent.click(screen.getByRole('button', { name: '确认计划并开始写作' }))
    await view.rerender({ taskId: 'task-18', chapterSeq: 18, runs: [run(1, { ...plan('新目标'), chapter_seq: 18 })] })
    expect((screen.getByLabelText(/本章目标/) as HTMLTextAreaElement).value).toBe('新目标')
    finish({ task_id: 'task-17', status: 'queued' }); await flushPromises()
    expect(onConfirmed).not.toHaveBeenCalled()
    expect((screen.getByRole('button', { name: '确认计划并开始写作' }) as HTMLButtonElement).disabled).toBe(false)
})
it('lets the user edit the current manual plan before write starts', async () => {
    vi.mocked(api.confirmTaskPlan).mockResolvedValue({ task_id: 'task-17', status: 'queued' });
    const onConfirmed = vi.fn();
    render(h(ChapterPlanPanel, { "taskId": "task-17", "chapterSeq": 17, "status": "awaiting_plan", "runs": [run(1, plan('旧目标'))], "artifact": null, "onConfirmed": onConfirmed, "onCancelled": () => { } }, []));
    await fireEvent.input(screen.getByLabelText(/本章目标/), { target: { value: '用户修订后的目标' } });
    await fireEvent.click(screen.getByRole('button', { name: '确认计划并开始写作' }));
    await waitFor(() => expect(api.confirmTaskPlan).toHaveBeenCalledTimes(1));
    const [, submitted, expectedAttempt] = vi.mocked(api.confirmTaskPlan).mock.calls[0];
    expect(submitted.goals).toEqual(['用户修订后的目标']);
    expect(expectedAttempt).toBe(1);
    expect(onConfirmed).toHaveBeenCalledWith('task-17', 17);
});
it('shows a streaming replan while folding the previous plan into history', async () => {
    const artifact: ArtifactState = {
        artifactId: 'plan-v2', taskId: 'task-17', stage: 'plan', chapterSeq: 17,
        attempt: 2, content: '{"goals":["新版计划正在生成', complete: false,
        failed: false, artifact: null, message: null,
    };
    render(h(ChapterPlanPanel, { "taskId": "task-17", "chapterSeq": 17, "status": "running", "runs": [run(1, plan('旧版目标'))], "artifact": artifact, "onConfirmed": () => { }, "onCancelled": () => { } }, []));
    expect(screen.getByText('AI 正在规划')).toBeTruthy();
    expect(screen.getByText('历史计划（1）')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '确认计划并开始写作' })).toBeNull();
});
it('grows the plan boxes to their content so only the plan body scrolls', async () => {
    // jsdom 量不出真实高度，把 scrollHeight 钉成非零值：接线在，每个框就都该拿到内联高。
    const measured = vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockReturnValue(140);
    try {
        render(h(ChapterPlanPanel, { "taskId": "task-17", "chapterSeq": 17, "status": "awaiting_plan", "runs": [run(1, plan('目标'))], "artifact": null, "onConfirmed": () => { }, "onCancelled": () => { } }, []));
        await waitFor(() => expect(screen.getByLabelText(/本章目标/)).toBeTruthy());
        // 计划正文那块自己滚（.body）：里面的框再滚，就成了「能滚的块里嵌一个能滚的框」。
        const boxes = Array.from(document.querySelectorAll('textarea'));
        expect(boxes.length).toBeGreaterThan(3);
        for (const box of boxes)
            expect(box.style.height).toBe('140px');
    }
    finally {
        measured.mockRestore();
    }
});
it('can cancel a task that is waiting for plan confirmation', async () => {
    vi.mocked(api.cancelTask).mockResolvedValue({ task_id: 'task-17', status: 'cancelled' });
    const onCancelled = vi.fn();
    render(h(ChapterPlanPanel, { "taskId": "task-17", "chapterSeq": 17, "status": "awaiting_plan", "runs": [run(1, plan('目标'))], "artifact": null, "onConfirmed": () => { }, "onCancelled": onCancelled }, []));
    await fireEvent.click(screen.getByRole('button', { name: '取消本次写作' }));
    await waitFor(() => expect(api.cancelTask).toHaveBeenCalledWith('task-17'));
    expect(onCancelled).toHaveBeenCalledWith('task-17', 17);
});
it('preserves Enter and submits separate goals instead of merging them', async () => {
    vi.mocked(api.confirmTaskPlan).mockResolvedValue({ task_id: 'task-17', status: 'queued' });
    render(h(ChapterPlanPanel, { "taskId": "task-17", "chapterSeq": 17, "status": "awaiting_plan", "runs": [run(1, plan('第一目标'))], "artifact": null, "onConfirmed": () => { }, "onCancelled": () => { } }, []));
    const goals = screen.getByLabelText(/本章目标/) as HTMLTextAreaElement;
    await fireEvent.input(goals, { target: { value: '第一目标\n' } });
    expect(goals.value).toBe('第一目标\n');
    await fireEvent.input(goals, { target: { value: goals.value + '第二目标\n' } });
    await fireEvent.click(screen.getByRole('button', { name: '确认计划并开始写作' }));
    await waitFor(() => expect(api.confirmTaskPlan).toHaveBeenCalled());
    expect(vi.mocked(api.confirmTaskPlan).mock.calls[0][1].goals).toEqual(['第一目标', '第二目标']);
});
it('preserves partial state keys while editing', async () => {
    const value = { ...plan('目标'), characters: [{ character_id: '主角', expected_state: {} }] };
    vi.mocked(api.confirmTaskPlan).mockResolvedValue({ task_id: 'task-17', status: 'queued' });
    render(h(ChapterPlanPanel, { "taskId": "task-17", "chapterSeq": 17, "status": "awaiting_plan", "runs": [run(1, value)], "artifact": null, "onConfirmed": () => { }, "onCancelled": () => { } }, []));
    const state = screen.getByLabelText('人物 1 状态') as HTMLTextAreaElement;
    await fireEvent.input(state, { target: { value: '伤' } });
    expect(state.value).toBe('伤');
    await fireEvent.input(state, { target: { value: '伤势：未愈\n' } });
    await fireEvent.click(screen.getByRole('button', { name: '确认计划并开始写作' }));
    await waitFor(() => expect(api.confirmTaskPlan).toHaveBeenCalled());
    const submitted = vi.mocked(api.confirmTaskPlan).mock.calls[0][1];
    expect(submitted.characters[0].expected_state).toEqual({ 伤势: '未愈' });
});
it('preserves a participant delimiter until the next name is typed', async () => {
    vi.mocked(api.confirmTaskPlan).mockResolvedValue({ task_id: 'task-17', status: 'queued' });
    render(h(ChapterPlanPanel, { "taskId": "task-17", "chapterSeq": 17, "status": "awaiting_plan", "runs": [run(1, plan('目标'))], "artifact": null, "onConfirmed": () => { }, "onCancelled": () => { } }, []));
    const people = screen.getByLabelText('场景 1 人物') as HTMLInputElement;
    await fireEvent.input(people, { target: { value: '林尘、' } });
    expect(people.value).toBe('林尘、');
    await fireEvent.input(people, { target: { value: people.value + '同伴' } });
    await fireEvent.click(screen.getByRole('button', { name: '确认计划并开始写作' }));
    await waitFor(() => expect(api.confirmTaskPlan).toHaveBeenCalled());
    expect(vi.mocked(api.confirmTaskPlan).mock.calls[0][1].scenes[0].participants).toEqual(['林尘', '同伴']);
});

it('keeps edited list values when native change bubbles on blur before confirmation', async () => {
    vi.mocked(api.confirmTaskPlan).mockResolvedValue({ task_id: 'task-17', status: 'queued' });
    const onConfirmed = vi.fn();
    render(h(ChapterPlanPanel, { taskId: 'task-17', chapterSeq: 17, status: 'awaiting_plan', runs: [run(1, plan('旧目标'))], artifact: null, onConfirmed, onCancelled: () => {} }));
    const goals = screen.getByLabelText(/本章目标/);
    await fireEvent.input(goals, { target: { value: '第一目标\n第二目标' } });
    await fireEvent.change(goals);
    await fireEvent.blur(goals);
    expect((screen.getByLabelText(/本章目标/) as HTMLTextAreaElement).value).toBe('第一目标\n第二目标');
    await fireEvent.click(screen.getByRole('button', { name: '确认计划并开始写作' }));
    await waitFor(() => expect(api.confirmTaskPlan).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.confirmTaskPlan).mock.calls[0][1].goals).toEqual(['第一目标', '第二目标']);
    expect(onConfirmed).toHaveBeenCalledWith('task-17', 17);
});
it('shows replacement plan streaming even when parsing retry uses the same plan attempt',()=>{
 const artifact:ArtifactState={artifactId:'retry',taskId:'task-17',stage:'plan',chapterSeq:17,attempt:1,content:'{"goals":["新的计划"]}',complete:false,failed:false,artifact:null,message:null}
 render(h(ChapterPlanPanel,{taskId:'task-17',chapterSeq:17,status:'running',runs:[run(1,plan('旧版目标'))],artifact,onConfirmed:()=>{},onCancelled:()=>{}}))
 expect(screen.getByText('AI 正在规划')).toBeTruthy()
})

it.each(['confirm','cancel'] as const)('announces pending plan %s and clears the indicator on failure', async action => {
 let fail!: (error: Error) => void
 const pending = new Promise<TaskControlResponse>((_resolve, reject) => {fail=reject})
 vi.mocked(api.confirmTaskPlan).mockReturnValue(pending)
 vi.mocked(api.cancelTask).mockReturnValue(pending)
 render(h(ChapterPlanPanel,{taskId:'task-17', chapterSeq:17, status:'awaiting_plan', runs:[run(1,plan('目标'))], artifact:null, onConfirmed:()=>{}, onCancelled:()=>{}}))
 await fireEvent.click(screen.getByRole('button',{name:action==='confirm'?'确认计划并开始写作':'取消本次写作'}))
 expect(screen.getByRole('status').textContent).toContain(action==='confirm'?'正在确认章节计划':'正在取消本次写作')
 expect(screen.getByRole('progressbar').hasAttribute('value')).toBe(false)
 expect((screen.getByLabelText(/本章目标/) as HTMLTextAreaElement).value).toBe('目标')
 fail(new Error('offline')); await flushPromises()
 expect(screen.queryByRole('progressbar')).toBeNull()
 expect(screen.getByRole('alert')).toBeTruthy()
})

it.each(['failed', 'cancelled'] as const)('does not claim AI is still planning after task %s', async status => {
 render(h(ChapterPlanPanel,{taskId:'task-17',chapterSeq:17,status,runs:[],artifact:null,onConfirmed:()=>{},onCancelled:()=>{}}))
 expect(screen.queryByText('AI 正在规划')).toBeNull()
 expect(screen.getByRole('status').textContent).toContain(status==='failed'?'规划未能完成':'本次规划已取消')
})
