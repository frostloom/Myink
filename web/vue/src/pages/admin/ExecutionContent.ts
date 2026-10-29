import { Fragment, h as renderNode } from 'vue';
import type { CapturedData } from "../../../../src/lib/adminApi";
import { parseContent } from "../../../../src/lib/readableContent";
import { resourceTitle } from "../../../../src/lib/resourceDisplay";
import { asRecord } from "../../../../src/lib/snapshotView";
import styles from "../../../../src/pages/admin/ExecutionDetail.module.css";
import { Disclosure } from "./Disclosure";
import { ReadableContent } from "./ReadableContent";
import { ResourceContent } from "./ResourceContent";
export { Disclosure } from './Disclosure';
function records(value: unknown) { return Array.isArray(value) ? value.map(asRecord).filter((item: Record<string, unknown> | null) => item !== null) : []; }
function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
export function CreationInput({ value, system }: {
    value: unknown;
    system: boolean;
}) {
    if (typeof value !== 'string')
        return renderNode(ReadableContent, { "value": value });
    const catalogue: string[] = [];
    let content = value.replace(/【本任务可查阅的准确路径】[\s\S]*?(?=\n【|$)/g, (block: string) => {
        const start = block.indexOf('[');
        const paths = start < 0 ? null : parseContent(block.slice(start));
        if (!Array.isArray(paths) || !paths.every(path => typeof path === 'string')) {
            return '【可供查阅的写作资料】\n目录未完整留存，无法还原全部可用资料。';
        }
        catalogue.push(...paths);
        return `【可供查阅的写作资料】\n本次提供 ${paths.length} 项写作资料供 AI 按需查阅；提供目录不代表已经阅读。`;
    });
    if (system)
        content = content.replace(/输出格式（硬要求[^\n]*\n(?:[^\n]+\n?)+/g, '【交付格式】\n系统已固定章节拆分和交付约定，用于将输出保存为独立章节。\n');
    if (system)
        content = content.replace(/输出严格 JSON：\s*\n\{[^\n]+\}\nverdict[^\n]*/g, '【审核结论的交付约定】\n仅在正文可直接发布时判为通过；存在必须修改的问题时，需要列出问题与可执行的修改建议。')
            .replace(/issues 与 suggestions/g, '问题与修改建议').replace(/写进 issues/g, '记入问题清单');
    content = content.replace(/\bread_genre_reference\b/g, '资料查阅工具')
        .replace(/^=+\s*CHAPTER\s+\d+(?:\s+(?:CONTENT|TITLE))?\s*=+\s*$/gim, '');
    return renderNode(Fragment, {}, [
        renderNode(ReadableContent, { "value": content }), catalogue.length > 0 && renderNode(Disclosure, { "title": "查看可用资料名称", children: [renderNode("ul", { "class": styles.items }, [catalogue.map((path: string, index: number) => renderNode("li", { "key": index }, [resourceTitle({ kind: "reference", name: path })]))])] })
    ]);
}
export function ExecutionError({ value, label }: {
    value: CapturedData;
    label: string;
}) {
    return renderNode("section", { "aria-label": label }, [
        renderNode("h4", {}, [label]), value.truncated && renderNode("p", { "class": styles.muted }, ["内容已截断"]), value.redacted && renderNode("p", { "class": styles.muted }, ["敏感信息已脱敏"]), renderNode(ReadableContent, { "value": value.data })
    ]);
}
export function ExecutionContent({ value }: {
    value: unknown;
}) {
    const data = asRecord(value);
    const response = asRecord(data?.response);
    const output = response?.content;
    const review = asRecord(parseContent(output));
    const invalidOutput = typeof output === 'string' && typeof parseContent(output) === 'string' && /^\s*(?:```(?:json)?\s*)?[[{]\s*"/.test(output);
    const requests = records(response?.tool_calls);
    const reads = records(data?.tool_trace);
    const messages = records(data?.messages);
    return renderNode("div", { "class": styles.content }, [
        renderNode("section", { "aria-label": "实际资料与状态查阅" }, [
            renderNode("h4", {}, ["实际资料与状态查阅"]), reads.length === 0 ? renderNode("p", { "class": styles.muted }, ["本次调用没有保存查阅记录。已提供资料目录不代表实际读取过资料。"]) : renderNode("ul", { "class": styles.reads }, [reads.map((read: Record<string, unknown>, index: number) => {
                    const args = asRecord(read.arguments);
                    const path = text(args?.path);
                    const result = parseContent(read.result);
                    const record = asRecord(result);
                    const failed = Boolean(read.skipped) || Boolean(record?.error) || /^\s*\{\s*"error"\s*:/.test(text(read.result));
                    const incomplete = !record && /^\s*\{/.test(text(read.result));
                    const contentFragment = incomplete && /"content"\s*:/.test(text(read.result));
                    const reference = read.tool === "read_genre_reference";
                    const label = reference ? (path ? resourceTitle({ kind: "reference", name: path }) : "查询写作资料目录") : ({ inspect_character: "查询人物状态", inspect_foreshadows: "查询伏笔", inspect_plot_threads: "查询剧情线", inspect_facts: "查询世界观约束" }[text(read.tool)] ?? "其他只读查阅");
                    const status = read.skipped ? "未执行：额度已用尽" : failed ? "读取失败" : contentFragment ? "已返回正文片段" : reference && typeof record?.content === "string" && record.content.length > 0 ? "已读取正文" : reference && !path && Array.isArray(record?.files) ? "已返回目录" : read.result ? "已返回查阅结果" : "结果未留存";
                    return renderNode("li", { "key": index, "class": styles.read, "data-failed": failed }, [
                        renderNode("div", { "class": styles.readHead }, [
                            renderNode("strong", {}, [label]), renderNode("span", {}, [status])
                        ]), read.skipped ? renderNode("p", { "class": styles.muted }, ["本次可查阅次数已用完，这项请求没有执行。"]) : failed ? renderNode("p", { "class": styles.muted }, ["这次未能取得资料，不能算作已阅读。"]) : incomplete ? renderNode("p", { "class": styles.muted }, ["查阅返回的内容未完整留存，无法还原全文；原始片段可在技术诊断中查看。"]) : record?.content ? renderNode(Disclosure, { "title": "查看读到的资料", children: [renderNode(ResourceContent, { "body": { files: [{ path, content: text(record.content) }] } })] }) : record?.files ? renderNode("p", { "class": styles.muted }, ["取得了可查阅资料清单；取得目录不等于阅读了正文。"]) : read.result ? renderNode(Disclosure, { "title": "查看查阅结果", children: [renderNode(ReadableContent, { "value": result })] }) : null
                    ]);
                })])
        ]), requests.length > 0 ? renderNode("section", {}, [
            renderNode("h4", {}, ["本次调用的进展"]), renderNode("p", { "class": styles.text }, [
                "本次回复发起了 ", requests.length, " 项资料或状态查阅请求，尚不是最终成稿。"
            ]), renderNode("p", { "class": styles.muted }, ["查阅是否执行成功，请以保存的查阅结果为准。"])
        ]) : output != null && output !== "" && renderNode("section", { "aria-label": "模型输出" }, [
            renderNode("h4", {}, ["模型输出"]), invalidOutput ? renderNode("p", { "class": styles.muted }, ["模型回复的格式无法识别，或留存内容不完整，当前无法可靠展示结果。可展开技术诊断核对原始回复。"]) : review?.verdict ? renderNode(Fragment, {}, [
                renderNode("p", {}, [renderNode("strong", {}, [review.verdict === "pass" ? "审核通过" : review.verdict === "revise" ? "建议修改" : "审核结果待确认"])]), renderNode(ReadableContent, { "value": Object.fromEntries(Object.entries(review).filter(([key]) => key !== "verdict")) })
            ]) : renderNode(ReadableContent, { "value": output })
        ]), messages.length > 0 && renderNode(Disclosure, { "title": `查看创作依据（${messages.length} 条）`, children: [renderNode("p", { "class": styles.muted }, ["以下是本次调用实际收到的要求和资料，按用途整理。完整协议和原始记录可在技术诊断中查看。"]), messages.map((message: Record<string, unknown>, index: number) => renderNode("section", { "class": styles.input, "key": index }, [
                    renderNode("h4", {}, [
                        ({ system: "角色职责与创作要求", user: "本次创作任务", assistant: "前轮回复", tool: "查阅返回的资料" }[text(message.role)] ?? "补充输入"), " · ", index + 1
                    ]), renderNode(CreationInput, { "value": message.content, "system": message.role === "system" })
                ]))] })
    ]);
}
CreationInput.props = ["value", "system"];
CreationInput.inheritAttrs = false;
ExecutionError.props = ["value", "label"];
ExecutionError.inheritAttrs = false;
ExecutionContent.props = ["value"];
ExecutionContent.inheritAttrs = false;
