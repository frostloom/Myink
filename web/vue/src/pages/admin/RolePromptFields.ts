import type { PropType } from 'vue';
import { Fragment, computed, defineComponent, h as renderNode, shallowRef, watch } from 'vue';
import { platformApi, type PromptRoleTemplates } from "../../../../src/lib/platformApi";
import { writingRoles } from "../../../../src/lib/resourceDisplay";
import type { ResourceBody } from "../../../../src/lib/writingResources";
import AutoTextarea from "../../components/AutoTextarea.vue";
import { Disclosure } from "./Disclosure";
import { ReadableContent } from "./ReadableContent";
type RoleBody = Extract<ResourceBody, {
    role: string;
}>;
export const RolePromptFields = defineComponent((props: {
    value: RoleBody;
    onChange?: (value: ResourceBody) => void;
    readOnly?: boolean;
    templateId?: string;
    onReadyChange?: (ready: boolean) => void;
}) => {
    const templates = shallowRef<PromptRoleTemplates["templates"]>([]);
    const setTemplates = (next: typeof templates.value | ((old: typeof templates.value) => typeof templates.value)) => { templates.value = typeof next === "function" ? next(templates.value) : next; };
    const error = shallowRef("");
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const legacySupplement = shallowRef<string | null>(null);
    const setLegacySupplement = (next: typeof legacySupplement.value | ((old: typeof legacySupplement.value) => typeof legacySupplement.value)) => { legacySupplement.value = typeof next === "function" ? next(legacySupplement.value) : next; };
    const retry = shallowRef(0);
    const setRetry = (next: typeof retry.value | ((old: typeof retry.value) => typeof retry.value)) => { retry.value = typeof next === "function" ? next(retry.value) : next; };
    const hasSupplement = computed(() => (props.value.supplement !== undefined));
    watch([() => props.value.role, () => retry.value, () => (props.readOnly ?? false), () => hasSupplement.value, () => props.onReadyChange], (_next, _old, onCleanup) => {
        const cleanup = (() => {
            let live = true;
            props.onReadyChange?.(false);
            Promise.all([platformApi.getPromptTemplates(), !(props.readOnly ?? false) && !hasSupplement.value ? platformApi.getConfiguration() : Promise.resolve(null),]).then(([items, configuration]) => {
                if (live) {
                    const roleTemplates = items.find((item: PromptRoleTemplates) => item.role === props.value.role)?.templates ?? [];
                    if (!roleTemplates.length) {
                        setError("未读取到此分工的创作环节，请重新加载。");
                        props.onReadyChange?.(false);
                        return;
                    }
                    setTemplates(roleTemplates);
                    setLegacySupplement(configuration?.prompts[props.value.role] ?? "");
                    setError("");
                    props.onReadyChange?.(true);
                }
            }).catch(() => {
                if (live) {
                    setError("写作环节说明或共用补充加载失败，请重试。");
                    props.onReadyChange?.(false);
                }
            });
            return () => { live = false; props.onReadyChange?.(false); };
        })();
        if (typeof cleanup === "function")
            onCleanup(cleanup);
    }, { immediate: true, flush: "post" });
    const visibleTemplates = computed(() => (props.templateId ? templates.value.filter((template: {
        id: string;
        title: string;
        content: string;
        source: string;
        editable_content?: string;
        fixed_content?: string;
        description?: string;
        when?: string;
    }) => template.id === props.templateId) : templates.value));
    const showSupplement = computed(() => (!props.templateId || props.templateId === "__supplement__"));
    const role = computed(() => (writingRoles[props.value.role]));
    const supplement = computed(() => (props.value.supplement ?? legacySupplement.value ?? ""));
    function changeTemplate(id: string, text: string) {
        props.onChange?.({ ...props.value, supplement: supplement.value, templates: {
                ...props.value.templates,
                [id]: text,
            } });
    }
    return () => {
        return renderNode("section", { "aria-label": `${role.value?.name ?? "角色"}的创作要求` }, [
            renderNode("p", {}, [
                role.value?.purpose, "。发布后，对应环节的新创作任务自动使用，无需作者逐本选择；已受理任务继续使用原版本。"
            ]), error.value && renderNode("div", { "role": "alert" }, [
                error.value, renderNode("button", { "class": "btn", "onClick": () => setRetry((v: number) => v + 1) }, ["重新加载环节说明"])
            ]), !templates.value.length && !error.value && renderNode("p", { "role": "status" }, ["正在读取实际写作环节…"]), templates.value.length > 0 && showSupplement.value && ((props.readOnly ?? false) ? renderNode("section", {}, [
                renderNode("h3", {}, ["各环节共用的补充要求"]), renderNode("p", { "style": { whiteSpace: "pre-wrap" } }, [props.value.supplement === undefined ? "此版本沿用当时的平台补充要求。" : props.value.supplement || "没有额外的共用要求。"])
            ]) : renderNode("label", { "style": { display: "grid", gap: "8px", marginTop: "24px" } }, [
                "各环节共用的补充要求", renderNode(AutoTextarea, { "aria-label": "各环节共用的补充要求", "class": "textarea", "rows": 4, "value": supplement.value, "disabled": legacySupplement.value === null, "onChange": (event: Event) => props.onChange?.({ ...props.value, supplement: (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }) }), renderNode("span", {}, ["会自动用于此角色的各个环节，与下方要求一起保存草稿、发布和回退；留空表示不追加。"])
            ])), !props.templateId && renderNode("p", {}, ["以下按具体创作环节分别配置。点击环节名称展开；“共用补充要求”会用于此分工的所有环节。"]), visibleTemplates.value.map((template: {
                id: string;
                title: string;
                content: string;
                source: string;
                editable_content?: string;
                fixed_content?: string;
                description?: string;
                when?: string;
            }, index: number) => renderNode(Disclosure, { "key": template.id, "defaultOpen": index === 0, "title": renderNode(Fragment, {}, [
                    renderNode("span", {}, [template.title]), renderNode("span", { "style": { display: "block", fontWeight: 400, fontSize: "var(--text-small)", color: "var(--ink-subtle)", marginTop: "6px" } }, [template.when])
                ]), children: [renderNode("fieldset", { "style": { margin: 0, padding: 0, minWidth: 0, border: 0 } }, [
                        template.description && renderNode("p", {}, [template.description]), (props.readOnly ?? false) ? renderNode(ReadableContent, { "value": props.value.templates[template.id] ?? template.editable_content ?? "" }) : renderNode("label", {}, [
                            template.title, " · 创作要求", renderNode(AutoTextarea, { "class": "textarea", "rows": 8, "style": { width: "100%", marginTop: "8px" }, "value": props.value.templates[template.id] ?? template.editable_content ?? "", "disabled": legacySupplement.value === null, "onChange": (event: Event) => changeTemplate(template.id, (event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) })
                        ]), renderNode("details", { "style": { marginTop: "16px" } }, [
                            renderNode("summary", {}, ["系统保留的流程与输出格式"]), renderNode("p", {}, ["这些约定保证生成结果能够接回写作流程，由系统维护。"]), renderNode("p", { "style": { whiteSpace: "pre-wrap", overflowWrap: "anywhere" } }, [template.fixed_content ?? template.content])
                        ])
                    ])] }))
        ]);
    };
}, {
    inheritAttrs: false,
    props: {
        value: { type: Object as PropType<RoleBody>, required: true },
        onChange: { type: Function as PropType<(value: ResourceBody) => void>, default: undefined },
        readOnly: { type: Boolean as PropType<boolean>, default: undefined },
        templateId: { type: String as PropType<string>, default: undefined },
        onReadyChange: { type: Function as PropType<(ready: boolean) => void>, default: undefined }
    }
});
