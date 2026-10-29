import { Fragment, h as renderNode } from 'vue';
import { parseReferenceFile, resourceTitle } from "../../../../src/lib/resourceDisplay";
import { internalResourceFields, resourceFieldLabels } from "../../../../src/lib/resourceFieldLabels";
import type { ResourceBody } from "../../../../src/lib/writingResources";
import styles from "../../../../src/pages/admin/AdminResources.module.css";
import { Disclosure } from "./Disclosure";
function ContentValue({ value }: {
    value: unknown;
}) {
    if (value === null || value === undefined || value === '')
        return null;
    if (Array.isArray(value)) {
        if (value.length && value.every(item => item && typeof item === 'object' && typeof item.name === 'string' && typeof item.hook === 'string')) {
            return renderNode('ul', { class: styles.namedEntries }, value.map((item, index) => renderNode('li', { key: index }, [
                renderNode('strong', {}, item.name), renderNode('span', {}, item.hook),
                renderNode(ContentValue, { value: Object.fromEntries(Object.entries(item).filter(([key]) => key !== 'name' && key !== 'hook')) }),
            ])));
        }
        return value.length ? renderNode('ul', {}, value.map((item, index) => renderNode('li', { key: index }, [renderNode(ContentValue, { value: item })]))) : null;
    }
    if (typeof value === 'object')
        return (renderNode("dl", {}, [Object.entries(value).filter(([key, v]) => !internalResourceFields.has(key) && v !== "" && v !== null && (!Array.isArray(v) || v.length)).map(([k, v]) => (renderNode("div", { "key": k }, [
                renderNode("dt", {}, [resourceFieldLabels[k] ?? (/[a-z_]/i.test(k) ? "创作内容" : k)]), renderNode("dd", {}, [renderNode(ContentValue, { "value": v })])
            ])))]));
    if (typeof value === 'boolean')
        return renderNode("span", {}, [value ? "启用" : "关闭"]);
    return (renderNode(Fragment, {}, [String(value).split(/\n\s*\n|\n/).filter(Boolean).map((line: string, i: number) => {
            const heading = /^(#{1,6})\s+(.+)$/.exec(line);
            return heading ? (renderNode("h4", { "key": i }, [heading[2]])) : (renderNode("p", { "key": i }, [line.replace(/^[-*]\s+/, "• ")]));
        })]));
}
function ReferenceEntries({ entries }: {
    entries: Record<string, string>[];
}) {
    const titleKeys = ['label', '技法名称', '桥段名称', '模式名称', '人设类型', '场景类型', '设定类型', '命名对象', '节奏类型', '题材/流派', '题材'];
    const technical = new Set(['编号', '关键词', '意图与同义词', '层级', 'label_type', 'template_file', '推荐基础检索表', '推荐动态检索表', '默认查询词', 'contract注入层']);
    const displayNames: Record<string, string> = { canonical_genre: '所属题材', route_tags: '故事方向', trope_tags: '桥段特点', format_tags: '创作形式', aliases: '常见别名', notes: '用途说明', 大模型指令: '使用方法', 详细展开: '方法说明', 毒点: '需要避免', 正例: '示范写法', 反例: '不推荐的写法', 反模式: '不推荐的模式' };
    return renderNode("div", { "class": styles.referenceEntries }, [entries.map((entry: Record<string, string>, index: number) => {
            const titleKey = titleKeys.find((key: string) => entry[key]);
            const title = titleKey ? entry[titleKey] : `参考方法 ${index + 1}`;
            const metadata = Object.fromEntries(Object.entries(entry).filter(([key, value]) => technical.has(key) && value));
            const content = Object.fromEntries(Object.entries(entry).filter(([key]) => !technical.has(key) && key !== titleKey && key !== "核心摘要").map(([key, value]) => [displayNames[key] ?? key, value]));
            return renderNode("details", { "key": index, "class": styles.referenceEntry, "open": index === 0 }, [
                renderNode("summary", {}, [
                    renderNode("strong", {}, [title]), entry["核心摘要"] && renderNode("span", {}, [entry["核心摘要"]])
                ]), renderNode(ContentValue, { "value": content }), Object.keys(metadata).length > 0 && renderNode(Disclosure, { "title": "查看检索说明", children: [renderNode(ContentValue, { "value": metadata })] })
            ]);
        })]);
}
function GenreContent({ body }: { body: Extract<ResourceBody, {catalog_id: string}> }) {
    const fields = body.fields;
    const label = (key: string) => resourceFieldLabels[key] ?? key;
    return renderNode('div', { class: styles.genreContent }, [
        fields.selling_point && renderNode('p', {class: styles.genreLead}, String(fields.selling_point)),
        renderNode('div', {class: styles.genreSections}, Object.entries(fields)
            .filter(([key,value]) => key !== 'selling_point' && !internalResourceFields.has(key) && value != null && value !== '' && (!Array.isArray(value) || value.length))
            .map(([key,value]) => renderNode('section', {key,'aria-label':label(key)}, [
                renderNode('h4', {}, label(key)), renderNode(ContentValue, {value}),
            ]))),
        body.setup_caps && renderNode('details', {class: styles.genreCapabilities}, [
            renderNode('summary', {}, '开书准备'), renderNode(ContentValue, {value:body.setup_caps}),
        ]),
    ]);
}
GenreContent.props = ['body'];
GenreContent.inheritAttrs = false;
export function ResourceContent({ body }: {
    body: ResourceBody;
}) {
    return (renderNode("div", { "class": styles.readableContent }, ["catalog_id" in body && "fields" in body ? renderNode(GenreContent, {body}) : "files" in body ? (body.files.map((file: {
            path: string;
            content: string;
        }, index: number) => (renderNode("section", { "key": index }, [
            renderNode("h4", {}, [resourceTitle({ kind: "reference", name: file.path }) || `参考内容 ${index + 1}`]), /\.csv$/i.test(file.path) && typeof parseReferenceFile(file) === "string" ? renderNode(Fragment, {}, [
                renderNode("p", {}, ["这份资料的表格格式不完整，暂时无法整理成条目。"]), renderNode(Disclosure, { "title": "技术诊断", children: [renderNode("p", { "style": { whiteSpace: "pre-wrap", overflowWrap: "anywhere" } }, [file.content])] })
            ]) : /\.csv$/i.test(file.path) ? renderNode(ReferenceEntries, { "entries": parseReferenceFile(file) as Record<string, string>[] }) : renderNode(ContentValue, { "value": parseReferenceFile(file) })
        ])))) : (renderNode(ContentValue, { "value": body }))]));
}
ContentValue.props = ["value"];
ContentValue.inheritAttrs = false;
ReferenceEntries.props = ["entries"];
ReferenceEntries.inheritAttrs = false;
ResourceContent.props = ["body"];
ResourceContent.inheritAttrs = false;
