import { defineComponent,h,type VNode } from 'vue';
// @vitest-environment jsdom
import { cleanup,screen,render as vueRender } from '@testing-library/vue';
import { afterEach,expect,it } from 'vitest';
import { ResourceContent } from './ResourceContent';
afterEach(cleanup);
it('turns CSV materials into readable entries including quoted commas and multiline examples', () => {
    render(h(ResourceContent, { "body": { files: [{ path: 'references/csv/写作技法.csv', content: '\uFEFF技法名称,适用技能,核心摘要,正例\n对白声线,write,"按身份,区分说话方式","先停一下。\n让我想想。"' }] } }));
    expect(screen.getByRole('heading', { name: '叙事与写作技巧' })).toBeTruthy();
    expect(screen.getByText('按身份,区分说话方式')).toBeTruthy();
    expect(screen.getByText('写作时参考')).toBeTruthy();
    expect(screen.getByText(/先停一下。/)).toBeTruthy();
    expect(screen.queryByText(/技法名称,适用技能/)).toBeNull();
});
it('explains resource rules and hides storage fields without removing creative content', () => {
    render(h(ResourceContent, { "body": { roles: { writer: '让人物通过行动改变关系' }, genre_ids: ['internal-id'] } }));
    expect(screen.getByText('写作')).toBeTruthy();
    expect(screen.getByText('让人物通过行动改变关系')).toBeTruthy();
    expect(screen.queryByText('internal-id')).toBeNull();
});
it('explains incomplete reference tables instead of dumping broken CSV', () => {
    render(h(ResourceContent, { "body": { files: [{ path: '写作技法.csv', content: '名称,摘要\n声线,"未闭合的引号' }] } }));
    expect(screen.getByText('这份资料的表格格式不完整，暂时无法整理成条目。')).toBeTruthy();
    expect(screen.queryByText(/声线,"未闭合/)).toBeNull();
});
it('makes a technique the entry title and puts retrieval metadata behind an optional disclosure', () => {
    render(h(ResourceContent, { "body": { files: [{ path: '写作技法.csv', content: '编号,技法名称,关键词,核心摘要,大模型指令,毒点\nWT-001,声线差异化,声线|口吻,让人物说话各有习惯,先区分身份,全员一个腔调' }] } }));
    expect(screen.getByText('声线差异化').closest('summary')).toBeTruthy();
    expect(screen.getByText('使用方法')).toBeTruthy();
    expect(screen.getByText('需要避免')).toBeTruthy();
    expect(screen.queryByText('WT-001')).toBeNull();
    expect(screen.queryByText('声线|口吻')).toBeNull();
});
it('explains the English taxonomy columns using genre names and meanings', () => {
    render(h(ResourceContent, { "body": { files: [{ path: 'references/taxonomy/genre-index.csv', content: 'label,canonical_genre,label_type,template_file,aliases,notes\n都市异能,都市,platform,都市异能.md,现代异能,现代社会里的异能故事' }] } }));
    expect(screen.getByText('都市异能').closest('summary')).toBeTruthy();
    expect(screen.getByText('所属题材')).toBeTruthy();
    expect(screen.getByText('现代社会里的异能故事')).toBeTruthy();
    expect(screen.queryByText('platform')).toBeNull();
    expect(screen.queryByText('都市异能.md')).toBeNull();
});
function render(node: VNode) { return vueRender(defineComponent({ render: () => node })); }
it('renders full genre fields densely without repeating name and hook labels', () => {
    const body = {catalog_id:'xiuxian',fields:{selling_point:'与天争命，资源稀缺。',subgenres:[{name:'凡人流',hook:'算计谨慎、积少成多'},{name:'无敌流',hook:'开局强势、专治不服'}],taboos:['不凭空升级'],pacing:'松紧相间',satisfaction:['逆境破局'],mechanics:['修炼代价'],world_hints:['宗门秩序']},setup_caps:{power_scaling:true}};
    render(h(ResourceContent, {body}));
    expect(screen.queryByText('题材内容')).toBeNull();
    expect(screen.queryByText('名称')).toBeNull();
    expect(screen.queryByText('故事钩子')).toBeNull();
    const first=screen.getByText('凡人流').closest('li');
    expect(first?.textContent).toContain('算计谨慎、积少成多');
    for(const value of ['不凭空升级','松紧相间','逆境破局','修炼代价','宗门秩序'])expect(screen.getByText(value)).toBeTruthy();
    expect(screen.getByRole('region',{name:'细分题材'})).toBeTruthy();
});
