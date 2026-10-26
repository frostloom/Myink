import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import type { PropType } from 'vue';
import { Fragment, computed, defineComponent, h as renderNode, shallowRef, watch } from 'vue';
import { isLegacyRoleSupplement, isSupportingReference, resourceUsage } from "../../../../src/lib/resourceDisplay";
import { writingResources as api, resourceError, resourceKinds, type ResourceBody, type ResourceKind, type ResourceSnapshot, type SelectionInput, type WritingResource, } from "../../../../src/lib/writingResources";
import { AdminDialog } from "./AdminDialog";
import { ResourceBodyFields } from "./ResourceBodyFields";
import { ResourceUpdates } from "./ResourceUpdates";
export const WritingResourcePicker = defineComponent((props: {
    projectId: string;
}) => {
    const catalog = shallowRef<WritingResource[]>([]);
    const setCatalog = (next: typeof catalog.value | ((old: typeof catalog.value) => typeof catalog.value)) => { catalog.value = typeof next === "function" ? next(catalog.value) : next; };
    const personal = shallowRef<WritingResource[]>([]);
    const setPersonal = (next: typeof personal.value | ((old: typeof personal.value) => typeof personal.value)) => { personal.value = typeof next === "function" ? next(personal.value) : next; };
    const snapshot = shallowRef<ResourceSnapshot | null>(null);
    const setSnapshot = (next: typeof snapshot.value | ((old: typeof snapshot.value) => typeof snapshot.value)) => { snapshot.value = typeof next === "function" ? next(snapshot.value) : next; };
    const chosen = shallowRef<SelectionInput[]>([]);
    const setChosen = (next: typeof chosen.value | ((old: typeof chosen.value) => typeof chosen.value)) => { chosen.value = typeof next === "function" ? next(chosen.value) : next; };
    const error = shallowRef("");
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const busy = shallowRef(false);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const notice = shallowRef("");
    const setNotice = (next: typeof notice.value | ((old: typeof notice.value) => typeof notice.value)) => { notice.value = typeof next === "function" ? next(notice.value) : next; };
    const editing = shallowRef<{
        item: WritingResource;
        own: boolean;
        projectOrigin?: "platform" | "personal";
    } | null>(null);
    const setEditing = (next: typeof editing.value | ((old: typeof editing.value) => typeof editing.value)) => { editing.value = typeof next === "function" ? next(editing.value) : next; };
    const name = shallowRef("");
    const setName = (next: typeof name.value | ((old: typeof name.value) => typeof name.value)) => { name.value = typeof next === "function" ? next(name.value) : next; };
    const body = shallowRef("");
    useMemoryFormGuard(() => editing.value !== null || (snapshot.value !== null && JSON.stringify(chosen.value) !== JSON.stringify(snapshot.value.selections.map(item => ({ origin: item.origin, resource_id: item.resource_id, personal_override: item.personal_override, ...(item.personal_override ? { body: item.body } : {}) })))));
    const setBody = (next: typeof body.value | ((old: typeof body.value) => typeof body.value)) => { body.value = typeof next === "function" ? next(body.value) : next; };
    watch([() => props.projectId], (_next, _old, onCleanup) => {
        const cleanup = (() => {
            let live = true;
            Promise.all([api.catalog(), api.personal(), api.snapshot(props.projectId)]).then(([c, p, s]) => {
                if (!live)
                    return;
                setCatalog(c.items.filter((item: WritingResource) => item.kind !== "role_prompt" && item.kind !== "reference" && !isSupportingReference(item) && !isLegacyRoleSupplement(item)));
                setPersonal(p.items.filter((item: WritingResource) => item.kind !== "role_prompt"));
                setSnapshot(s);
                setChosen(s.selections.map((i: import("../../../../src/lib/writingResources").ResourceSelection) => ({
                    origin: i.origin,
                    resource_id: i.resource_id,
                    personal_override: i.personal_override,
                    ...(i.personal_override ? { body: i.body } : {}),
                })));
            }).catch(e => {
                if (live)
                    setError(resourceError(e));
            });
            return () => {
                live = false;
            };
        })();
        if (typeof cleanup === "function")
            onCleanup(cleanup);
    }, { immediate: true, flush: "post" });
    function chosenMetadata(entry: SelectionInput) {
        return (snapshot.value?.selections.find((item: import("../../../../src/lib/writingResources").ResourceSelection) => item.origin === entry.origin && item.resource_id === entry.resource_id) ?? (entry.origin === "platform" ? catalog.value : personal.value).find((item: WritingResource) => item.id === entry.resource_id));
    }
    const chosenGenres = computed(() => (chosen.value.filter((entry: SelectionInput) => chosenMetadata(entry)?.kind === "genre")));
    const resourceGroups = computed<ResourceKind[]>(() => (["genre", "genre_rule", "style", "writing_rule", "expression_rule", "reference"]));
    const groupDescriptions = computed<Partial<Record<ResourceKind, string>>>(() => ({
        genre: "决定本书的题材方向和基本写法；多选时可指定主题材。",
        genre_rule: "例如修仙精调：规划时检查资源与突破代价，写正文时落实铺垫与收获，审稿时检查是否兑现。勾选、题材匹配并保存后，用于新发起的任务。",
        style: "约定叙事声音、对话和描写习惯；作品自己的文风与样本优先。",
        writing_rule: "例如章节衔接与收尾：下一次生成、续写或修订正文时使用；配置了规划或审核要求的规则，也会在对应环节使用。",
        expression_rule: "例如中文小说表达、句式偏好：下一次写正文或改稿时约束表达，审稿时检查是否符合要求。可自行勾选或自定义。",
        reference: "这是你自行维护的参考资料；平台写作知识库由 AI 按需查阅，无需勾选。",
    }));
    function pinnedSelection(item: WritingResource, origin: "platform" | "personal") {
        if (!chosen.value.some((entry: SelectionInput) => entry.origin === origin && entry.resource_id === item.id))
            return undefined;
        return snapshot.value?.selections.find((entry: import("../../../../src/lib/writingResources").ResourceSelection) => entry.origin === origin && entry.resource_id === item.id);
    }
    function effectiveResource(item: WritingResource, origin: "platform" | "personal"): WritingResource {
        const choice = chosen.value.find((entry: SelectionInput) => entry.origin === origin && entry.resource_id === item.id);
        const metadata = choice ? chosenMetadata(choice) : undefined;
        const body = choice?.personal_override && choice.body ? choice.body : metadata?.body ?? item.body;
        return { ...item, body };
    }
    function genreRuleHint(item: WritingResource, origin: "platform" | "personal") {
        const effective = effectiveResource(item, origin);
        const ids = "genre_ids" in effective.body ? effective.body.genre_ids ?? [] : [];
        if (item.kind !== "genre_rule" || !ids.length)
            return null;
        const allGenres = [...catalog.value, ...personal.value, ...(snapshot.value?.selections ?? [])].filter((item: WritingResource | import("../../../../src/lib/writingResources").ResourceSelection) => item.kind === "genre" && "catalog_id" in item.body);
        const names = ids.map((id: string) => allGenres.find((item: WritingResource | import("../../../../src/lib/writingResources").ResourceSelection) => "catalog_id" in item.body && item.body.catalog_id === id)?.name ?? "其他匹配题材");
        const matches = chosenGenres.value.some((entry: SelectionInput) => {
            const metadata = chosenMetadata(entry);
            return metadata && "catalog_id" in metadata.body && ids.includes(metadata.body.catalog_id);
        });
        return renderNode(Fragment, {}, [
            renderNode("p", {}, [
                "适用题材：", names.join("、")
            ]), renderNode("p", {}, [matches ? "已匹配当前选择的题材，勾选此规则并保存后生效。" : "尚未匹配本书题材；仅选中此规则不会生效。"])
        ]);
    }
    function makePrimary(entry: SelectionInput) {
        setChosen((previous: SelectionInput[]) => {
            const firstGenre = previous.findIndex((item: SelectionInput) => chosenMetadata(item)?.kind === "genre");
            const remaining = previous.filter((item: SelectionInput) => !(item.origin === entry.origin && item.resource_id === entry.resource_id));
            remaining.splice(Math.max(0, firstGenre), 0, entry);
            return remaining;
        });
    }
    async function saveSelection() {
        if (!snapshot.value)
            return;
        setBusy(true);
        try {
            const s = await api.select(props.projectId, snapshot.value!.revision, chosen.value);
            setSnapshot(s);
            setNotice("资源快照已保存，后续生成使用此版本。");
            setError("");
        }
        catch (e) {
            setError(resourceError(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function savePrivate() {
        if (!editing.value)
            return;
        setBusy(true);
        try {
            const input = {
                name: name.value,
                source: editing.value!.item.source,
                body: JSON.parse(body.value) as ResourceBody,
            };
            if (editing.value!.projectOrigin && snapshot.value) {
                const next = chosen.value.map((entry: SelectionInput) => entry.origin === editing.value!.projectOrigin && entry.resource_id === editing.value!.item.id ? { ...entry, personal_override: true, body: input.body } : entry);
                const savedSnapshot = await api.select(props.projectId, snapshot.value!.revision, next);
                setSnapshot(savedSnapshot);
                setChosen(next);
                setEditing(null);
                setNotice("已保存本书个人覆盖，平台更新不会替换此内容。");
                setError("");
                return;
            }
            const saved = editing.value!.own ? await api.savePersonal(editing.value!.item.id, {
                ...input,
                expected_generation: editing.value!.item.generation,
            }) : await api.createPersonal({ ...input, kind: editing.value!.item.kind });
            setPersonal((old: WritingResource[]) => [...old.filter((i: WritingResource) => i.id !== saved.id), saved]);
            setEditing(null);
            setNotice("已保存到个人资源库，请勾选并保存本书选择。");
            setError("");
        }
        catch (e) {
            setError(resourceError(e));
        }
        finally {
            setBusy(false);
        }
    }
    return () => {
        return (renderNode("section", { "id": "writing-resources", "class": "panel", "style": { padding: "1.5rem", marginBottom: "1rem" } }, [
            renderNode("h2", {}, ["本书写作资源"]), renderNode("p", {}, ["在下方分别选择题材包、题材规则、文风、创作规则和表达规则，点击“保存本书资源选择”后用于新发起的规划、写作和审核；正在运行的任务继续使用原版本。个人修改只属于你，不会同步到管理后台。"]), renderNode("p", {}, ["角色提示词按写作环节自动生效。知识库由 AI 根据本书题材与当前任务按需查阅，选择题材包不代表每次必读某份资料；已读取情况以执行记录为准。"]), snapshot.value && !snapshot.value!.configured && (renderNode("p", {}, ["尚未配置：继续使用建书时的原有题材和文风。首次保存后以以下选择为准，请同时确认题材与文风。"])), error.value && !editing.value && renderNode("p", { "role": "alert" }, [error.value]), notice.value && renderNode("p", { "role": "status" }, [notice.value]), chosenGenres.value.length > 0 && (renderNode("section", { "aria-label": "待保存题材顺序" }, [
                renderNode("h3", {}, ["题材优先级（保存后生效）"]), renderNode("p", {}, ["主题材主导，辅题材补充；组合遵循主辅 7:3 的优先级。"]), chosenGenres.value.map((entry: SelectionInput, index: number) => (renderNode("p", { "key": `${entry.origin}:${entry.resource_id}` }, [
                    chosenMetadata(entry)?.name, " · ", " ", index === 0 ? "主题材" : "辅题材", renderNode("button", { "class": "btn btn-quiet", "disabled": busy.value || index === 0, "onClick": () => makePrimary(entry) }, [
                        "设为主题材 ", chosenMetadata(entry)?.name
                    ])
                ])))
            ])), snapshot.value?.selections.map((s: import("../../../../src/lib/writingResources").ResourceSelection) => (renderNode("p", { "key": `${s.origin}:${s.resource_id}` }, [
                s.name, " · ", s.origin === "platform" ? "平台" : "个人", " · v", s.version, " ", s.kind === "genre" && ` · 已保存${snapshot.value!.selections.filter((entry: import("../../../../src/lib/writingResources").ResourceSelection) => entry.kind === "genre")[0] === s ? "主题材" : "辅题材"}`, s.personal_override ? " · 个人覆盖（更新不会替换）" : "", renderNode("button", { "class": "btn btn-quiet", "disabled": busy.value || !chosen.value.some((entry: SelectionInput) => entry.origin === s.origin && entry.resource_id === s.resource_id), "onClick": () => setChosen((old: SelectionInput[]) => old.filter((entry: SelectionInput) => !(entry.origin === s.origin && entry.resource_id === s.resource_id))) }, [
                    "移除本书选择 ", s.name
                ]), renderNode("button", { "class": "btn btn-quiet", "disabled": busy.value || !chosen.value.some((entry: SelectionInput) => entry.origin === s.origin && entry.resource_id === s.resource_id), "onClick": () => {
                        setEditing({
                            item: {
                                id: s.resource_id,
                                name: s.name,
                                kind: s.kind,
                                source: s.origin,
                                status: "published",
                                generation: s.generation,
                                current_version: s.version,
                                body: s.body,
                            },
                            own: false,
                            projectOrigin: s.origin,
                        });
                        setName(s.name);
                        setBody(JSON.stringify(s.body, null, 2));
                        setError("");
                    } }, [
                    "自定义本书 ", s.name
                ])
            ]))), (["platform", "personal"] as const).map((origin: "platform" | "personal") => (renderNode("section", { "key": origin }, [
                renderNode("h3", {}, [origin === "platform" ? "平台资源" : "我的资源"]), resourceGroups.value.map((kind: ResourceKind) => {
                    const items = (origin === "platform" ? catalog.value : personal.value).filter((item: WritingResource) => item.kind === kind);
                    if (!items.length)
                        return null;
                    return renderNode("section", { "key": kind, "aria-label": `${origin === "platform" ? "平台" : "个人"}${resourceKinds[kind]}`, "style": { marginTop: "24px" } }, [
                        renderNode("h4", {}, [
                            resourceKinds[kind], " · ", items.length, " 项"
                        ]), renderNode("p", {}, [groupDescriptions.value[kind]]), items.map((item: WritingResource) => (renderNode("div", { "key": item.id, "style": {
                                borderBottom: "1px solid var(--line)",
                                padding: ".75rem 0",
                            } }, [
                            renderNode("label", {}, [
                                renderNode("input", { "type": "checkbox", "disabled": busy.value, "checked": chosen.value.some((s: SelectionInput) => s.origin === origin && s.resource_id === item.id), "onChange": (e: Event) => setChosen((old: SelectionInput[]) => (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked ? [...old, { origin, resource_id: item.id }] : old.filter((s: SelectionInput) => !(s.origin === origin && s.resource_id === item.id))) }, []), " ", item.name, " · ", resourceKinds[item.kind], " · v", pinnedSelection(item, origin)?.version ?? item.current_version
                            ]), pinnedSelection(item, origin) && pinnedSelection(item, origin)?.version !== item.current_version && renderNode("p", {}, [
                                "平台另有 v", item.current_version, "，采用更新后才会替换本书版本。"
                            ]), renderNode("p", {}, [resourceUsage(effectiveResource(item, origin)).when]), genreRuleHint(item, origin), renderNode("button", { "class": "btn btn-quiet", "disabled": busy.value, "onClick": () => {
                                    setEditing({ item, own: origin === "personal" });
                                    setName(item.name);
                                    setBody(JSON.stringify(item.body, null, 2));
                                    setError("");
                                } }, [
                                origin === "platform" ? "复制到个人资源" : "编辑个人资源", " ", item.name
                            ])
                        ])))
                    ]);
                })
            ]))), renderNode("button", { "class": "btn btn-primary", "disabled": busy.value || !snapshot.value, "onClick": () => void saveSelection() }, ["保存本书资源选择"]), renderNode(ResourceUpdates, { "key": snapshot.value?.revision, "projectId": props.projectId, "autoOpen": false, "onAdopt": (s: ResourceSnapshot) => {
                    setSnapshot(s);
                    setChosen(s.selections.map((i: import("../../../../src/lib/writingResources").ResourceSelection) => ({
                        origin: i.origin,
                        resource_id: i.resource_id,
                        personal_override: i.personal_override,
                        ...(i.personal_override ? { body: i.body } : {}),
                    })));
                } }), editing.value && (renderNode(AdminDialog, { "title": editing.value!.projectOrigin ? "本书个人覆盖" : "个人资源副本", "busy": busy.value, "onClose": () => setEditing(null), children: [renderNode("p", {}, ["不会修改平台发布内容或其他用户的资源。"]), renderNode("fieldset", { "disabled": busy.value }, [
                        renderNode("label", {}, [
                            "个人资源名称", renderNode("input", { "class": "input", "value": name.value, "disabled": !!editing.value!.projectOrigin, "onInput": (e: Event) => setName((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                        ]), renderNode(ResourceBodyFields, { "kind": editing.value!.item.kind, "genres": [...catalog.value, ...personal.value].filter((item: WritingResource) => item.kind === "genre" && "catalog_id" in item.body).map((item: WritingResource) => ({ id: (item.body as {
                                    catalog_id: string;
                                }).catalog_id, name: item.name })), "value": JSON.parse(body.value) as ResourceBody, "onChange": (value: ResourceBody) => setBody(JSON.stringify(value, null, 2)) })
                    ]), error.value && renderNode("p", { "role": "alert" }, [error.value]), renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => setEditing(null) }, ["取消"]), renderNode("button", { "class": "btn btn-primary", "disabled": busy.value || !name.value.trim(), "onClick": () => void savePrivate() }, [editing.value!.projectOrigin ? "保存本书个人覆盖" : "保存个人资源"])] }))
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        projectId: { type: String as PropType<string>, required: true }
    }
});
