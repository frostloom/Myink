import { defineComponent,h,type VNode } from 'vue';
// @vitest-environment jsdom
import { cleanup,fireEvent,screen,render as vueRender } from '@testing-library/vue';
import { afterEach,expect,it } from 'vitest';
import { ExecutionContent } from './ExecutionContent';
import { ReadableContent } from './ReadableContent';
afterEach(cleanup);
it('renders a structured chapter plan as readable content without exposing keys', () => {
    render(h(ReadableContent, { "value": '```json\n{"chapter_count":2,"chapters":[{"seq":1,"title":"夜归","goal":"发现失踪线索","beats":["收到来信","发现脚印"]}],"custom_extra":"保留额外的创作信息"}\n```' }));
    expect(screen.getByText('章节安排')).toBeTruthy();
    expect(screen.getByText('本章目标')).toBeTruthy();
    expect(screen.getByText('发现失踪线索')).toBeTruthy();
    expect(screen.getByText('收到来信')).toBeTruthy();
    expect(screen.getByText('保留额外的创作信息')).toBeTruthy();
    expect(screen.queryByText('custom_extra')).toBeNull();
    expect(screen.queryByText('chapter_count')).toBeNull();
});
it('renders review findings and advice separately and turns chapter markers into headings', () => {
    const { unmount } = render(h(ExecutionContent, { "value": { response: { content: JSON.stringify({ verdict: 'revise', issues: ['第三章动机不足'], suggestions: ['补充决定的原因'] }) } } }));
    expect(screen.getByRole('heading', { name: '发现的问题' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '修改建议' })).toBeTruthy();
    unmount();
    render(h(ExecutionContent, { "value": { response: { content: '=== CHAPTER 1 CONTENT ===\n夜里的钟响了。' } } }));
    expect(screen.getByRole('heading', { name: '第 1 章' })).toBeTruthy();
    expect(screen.getByText('夜里的钟响了。')).toBeTruthy();
});
it('explains tool requests as an intermediate step instead of presenting machine commentary as a finished draft', () => {
    render(h(ExecutionContent, { "value": { response: { content: "I'll read references first.", tool_calls: [{ name: 'read_genre_reference', arguments: { path: 'references/shared/core-constraints.md' } }] } } }));
    expect(screen.getByText('本次回复发起了 1 项资料或状态查阅请求，尚不是最终成稿。')).toBeTruthy();
    expect(screen.queryByText("I'll read references first.")).toBeNull();
});
it('organizes input sections and parses embedded structured brief data', async () => {
    render(h(ExecutionContent, { "value": { messages: [{ role: 'user', content: '【创作要求】\n保持悬念。\n【章节计划】\n{"title":"夜归","goal":"发现失踪线索"}\n【章标记】\n=== CHAPTER 1 CONTENT ===' }] } }));
    const disclosure = screen.getByText('查看创作依据（1 条）').closest('details')!;
    disclosure.open = true;
    await fireEvent(disclosure, new Event('toggle'));
    expect(await screen.findByRole('heading', { name: '创作要求' })).toBeTruthy();
    expect(screen.getByText('发现失踪线索')).toBeTruthy();
    expect(screen.queryByText(/=== CHAPTER/)).toBeNull();
});
it('does not dump incomplete captured JSON as a readable lookup result', async () => {
    render(h(ExecutionContent, { "value": { tool_trace: [{ tool: 'read_genre_reference', arguments: { path: 'references/shared/core-constraints.md' }, result: '{"path":"references/shared/core-constraints.md","content":"# 基本约束\\n写到这里被截断' }] } }));
    expect(screen.getByText('已返回正文片段')).toBeTruthy();
    expect(screen.queryByText(/\{"path"/)).toBeNull();
});
it('reads a structured plan followed by a plain instruction without showing JSON syntax', () => {
    render(h(ReadableContent, { "value": '{"title":"夜归","goal":"发现失踪线索"}\n请沿这个计划继续。' }));
    expect(screen.getByText('发现失踪线索')).toBeTruthy();
    expect(screen.getByText('请沿这个计划继续。')).toBeTruthy();
});
it('shows the supplied reference catalogue by purpose instead of backend paths', async () => {
    render(h(ExecutionContent, { "value": { messages: [{ role: 'system', content: '【本任务可查阅的准确路径】\n下面只列目录，不含资料正文。\n["references/shared/core-constraints.md","references/csv/人设与关系.csv"]' }] } }));
    const disclosure = screen.getByText('查看创作依据（1 条）').closest('details')!;
    disclosure.open = true;
    await fireEvent(disclosure, new Event('toggle'));
    expect(await screen.findByText('本次提供 2 项写作资料供 AI 按需查阅；提供目录不代表已经阅读。')).toBeTruthy();
    expect(screen.queryByText(/references\/shared/)).toBeNull();
    const catalogue = screen.getByText('查看可用资料名称').closest('details')!;
    catalogue.open = true;
    await fireEvent(catalogue, new Event('toggle'));
    expect(await screen.findByText('故事创作的基本约束')).toBeTruthy();
    expect(screen.getByText('人物设计与关系写法')).toBeTruthy();
});
it('does not invent an audit verdict from invalid structured output', () => {
    render(h(ExecutionContent, { "value": { response: { content: '{"verdict":"pass","issues":[' } } }));
    expect(screen.queryByText('审核通过')).toBeNull();
    expect(screen.getByText('模型回复的格式无法识别，或留存内容不完整，当前无法可靠展示结果。可展开技术诊断核对原始回复。')).toBeTruthy();
});
function render(node: VNode) { return vueRender(defineComponent({ render: () => node })); }

it('renders short scalar facts as compact labelled rows while keeping narrative sections', () => {
    render(h(ReadableContent, { value: { chapter_count: 2, genre: '悬疑', goal: '线索'.repeat(150) } }));
    expect(screen.getByText('计划章数').tagName).toBe('DT');
    expect(screen.getByText('题材').nextElementSibling?.textContent).toBe('悬疑');
    expect(screen.getByRole('heading', { name: '本章目标' })).toBeTruthy();
});
