import { defineComponent,h,type VNode } from 'vue';
// @vitest-environment jsdom
import { cleanup,fireEvent,screen,render as vueRender } from '@testing-library/vue';
import { afterEach,expect,it,vi } from 'vitest';
import { RolePromptFields } from './RolePromptFields';
vi.mock('../../../../src/lib/platformApi', () => ({ platformApi: { getPromptTemplates: vi.fn().mockResolvedValue([{ role: 'writer', templates: [
                    { id: 'system_write', title: '长篇正文写作', when: '生成长篇章节时', editable_content: '长篇要求', fixed_content: '固定长篇协议' },
                    { id: 'system_short_writer', title: '短篇整篇写作', when: '生成短篇全文时', editable_content: '短篇要求', fixed_content: '固定短篇协议' },
                ] }]) } }));
afterEach(cleanup);
it('shows stage-specific headings and opens only the selected stage while preserving edits by template id', async () => {
    const onChange = vi.fn();
    render(h(RolePromptFields, { "value": { role: 'writer', supplement: '', templates: { system_write: '长篇要求', system_short_writer: '短篇要求' } }, "onChange": onChange }));
    const short = await screen.findByText('短篇整篇写作');
    const section = short.closest('details')!;
    expect(section).toBeTruthy();
    expect(section.open).toBe(false);
    await fireEvent.click(short);
    // jsdom does not perform the native details toggle on a synthetic click.
    section.open = true;
    await fireEvent(section, new Event('toggle'));
    await fireEvent.update(await screen.findByLabelText('短篇整篇写作 · 创作要求'), '新短篇要求');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ templates: { system_write: '长篇要求', system_short_writer: '新短篇要求' } }));
});
it('edits only the chosen stage without inserting defaults for missing sibling stages', async () => {
    const onChange = vi.fn();
    render(h(RolePromptFields, { "templateId": "system_write", "value": { role: 'writer', supplement: '', templates: { system_write: '旧长篇要求' } }, "onChange": onChange }));
    await fireEvent.update(await screen.findByLabelText('长篇正文写作 · 创作要求'), '新长篇要求');
    expect(onChange).toHaveBeenLastCalledWith({ role: 'writer', supplement: '', templates: { system_write: '新长篇要求' } });
});
function render(node: VNode) { return vueRender(defineComponent({ render: () => node })); }
