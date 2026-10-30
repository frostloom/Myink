import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import type { PropType } from 'vue';
import { RouterLink } from 'vue-router';
import { Fragment, computed, defineComponent, onMounted, onUnmounted, h as renderNode, shallowRef, watch } from 'vue';
import { emptyFields } from "../../../../src/lib/genrePacks";
import { platformApi, type PromptRoleTemplates } from "../../../../src/lib/platformApi";
import { isLegacyRoleSupplement, isSourceNotice, isSupportingReference, referencePurpose, resourceSummary, resourceTitle, resourceUsage, writingRoles, } from "../../../../src/lib/resourceDisplay";
import { writingResources as api, emptyResourceStyleProfile, resourceError, resourceKinds, type ResourceBody, type ResourceKind, type ResourceRevision, type WritingResource, } from "../../../../src/lib/writingResources";
import styles from "../../../../src/pages/admin/AdminResources.module.css";
import { AdminDialog } from "./AdminDialog";
import { useAdminContext } from './context';
import { ResourceBodyFields } from "./ResourceBodyFields";
import { ResourceContent } from "./ResourceContent";
import { RolePromptFields } from "./RolePromptFields";
import { formatDate } from "./shared";
const WritingResources = defineComponent((props: {
    scope?: "all" | "prompts" | "genres";
}) => {
    const { onForbidden } = useAdminContext();
    const loading = shallowRef(true);
    const setLoading = (next: typeof loading.value | ((old: typeof loading.value) => typeof loading.value)) => { loading.value = typeof next === "function" ? next(loading.value) : next; };
    const filter = shallowRef("all");
    const setFilter = (next: typeof filter.value | ((old: typeof filter.value) => typeof filter.value)) => { filter.value = typeof next === "function" ? next(filter.value) : next; };
    const showArchived = shallowRef(false);
    const setShowArchived = (next: typeof showArchived.value | ((old: typeof showArchived.value) => typeof showArchived.value)) => { showArchived.value = typeof next === "function" ? next(showArchived.value) : next; };
    const archiving = shallowRef(false);
    const setArchiving = (next: typeof archiving.value | ((old: typeof archiving.value) => typeof archiving.value)) => { archiving.value = typeof next === "function" ? next(archiving.value) : next; };
    const allowedKinds = computed(() => ((Object.keys(resourceKinds) as ResourceKind[]).filter((k: ResourceKind) => (props.scope ?? "all") === "all" || ((props.scope ?? "all") === "genres" ? ["genre", "genre_rule"].includes(k) : ["role_prompt", "writing_rule", "expression_rule", "genre_rule"].includes(k)))));
    const title = computed(() => ((props.scope ?? "all") === "prompts" ? "提示词" : (props.scope ?? "all") === "genres" ? "题材包" : "写作资源"));
    const items = shallowRef<WritingResource[]>([]);
    const setItems = (next: typeof items.value | ((old: typeof items.value) => typeof items.value)) => { items.value = typeof next === "function" ? next(items.value) : next; };
    const promptCatalog = shallowRef<PromptRoleTemplates[]>([]);
    const setPromptCatalog = (next: typeof promptCatalog.value | ((old: typeof promptCatalog.value) => typeof promptCatalog.value)) => { promptCatalog.value = typeof next === "function" ? next(promptCatalog.value) : next; };
    const promptError = shallowRef("");
    const setPromptError = (next: typeof promptError.value | ((old: typeof promptError.value) => typeof promptError.value)) => { promptError.value = typeof next === "function" ? next(promptError.value) : next; };
    const promptRetry = shallowRef(0);
    const setPromptRetry = (next: typeof promptRetry.value | ((old: typeof promptRetry.value) => typeof promptRetry.value)) => { promptRetry.value = typeof next === "function" ? next(promptRetry.value) : next; };
    const selectedPromptId = shallowRef<string | null>(null);
    const setSelectedPromptId = (next: typeof selectedPromptId.value | ((old: typeof selectedPromptId.value) => typeof selectedPromptId.value)) => { selectedPromptId.value = typeof next === "function" ? next(selectedPromptId.value) : next; };
    const selected = shallowRef<WritingResource | null>(null);
    const setSelected = (next: typeof selected.value | ((old: typeof selected.value) => typeof selected.value)) => { selected.value = typeof next === "function" ? next(selected.value) : next; };
    const history = shallowRef<ResourceRevision[]>([]);
    const setHistory = (next: typeof history.value | ((old: typeof history.value) => typeof history.value)) => { history.value = typeof next === "function" ? next(history.value) : next; };
    const historyStatus = shallowRef<"loading" | "ready" | "error">("ready");
    const setHistoryStatus = (next: typeof historyStatus.value | ((old: typeof historyStatus.value) => typeof historyStatus.value)) => { historyStatus.value = typeof next === "function" ? next(historyStatus.value) : next; };
    const historyRequest = shallowRef(0);
    const previewReady = shallowRef(false);
    const setPreviewReady = (next: typeof previewReady.value | ((old: typeof previewReady.value) => typeof previewReady.value)) => { previewReady.value = typeof next === "function" ? next(previewReady.value) : next; };
    const name = shallowRef("");
    const setName = (next: typeof name.value | ((old: typeof name.value) => typeof name.value)) => { name.value = typeof next === "function" ? next(name.value) : next; };
    const source = shallowRef("");
    const setSource = (next: typeof source.value | ((old: typeof source.value) => typeof source.value)) => { source.value = typeof next === "function" ? next(source.value) : next; };
    const body = shallowRef("");
    const setBody = (next: typeof body.value | ((old: typeof body.value) => typeof body.value)) => { body.value = typeof next === "function" ? next(body.value) : next; };
    const error = shallowRef("");
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const busy = shallowRef(false);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const search = shallowRef("");
    const setSearch = (next: typeof search.value | ((old: typeof search.value) => typeof search.value)) => { search.value = typeof next === "function" ? next(search.value) : next; };
    const preview = shallowRef<"publish" | ResourceRevision | null>(null);
    const setPreview = (next: typeof preview.value | ((old: typeof preview.value) => typeof preview.value)) => { preview.value = typeof next === "function" ? next(preview.value) : next; };
    const note = shallowRef("");
    const setNote = (next: typeof note.value | ((old: typeof note.value) => typeof note.value)) => { note.value = typeof next === "function" ? next(note.value) : next; };
    const kind = shallowRef<ResourceKind>("reference");
    useMemoryFormGuard(() => selected.value !== null);
    const setKind = (next: typeof kind.value | ((old: typeof kind.value) => typeof kind.value)) => { kind.value = typeof next === "function" ? next(kind.value) : next; };
    const selectableKinds = computed<ResourceKind[]>(() => (allowedKinds.value.filter((k: ResourceKind) => k !== "role_prompt")));
    const available = computed(() => (items.value.filter((item: WritingResource) => !isSupportingReference(item) && !isLegacyRoleSupplement(item) && (showArchived.value || item.status !== "archived"))));
    const cards = computed<Array<{
        item: WritingResource;
        prompt?: {
            id: string;
            title: string;
            when?: string;
        };
    }>>(() => {
        const result: Array<{
            item: WritingResource;
            prompt?: {
                id: string;
                title: string;
                when?: string;
            };
        }> = [];
        for (const item of available.value) {
            if (!allowedKinds.value.includes(item.kind))
                continue;
            if (item.kind !== "role_prompt") {
                result.push({ item });
                continue;
            }
            if (!("role" in item.body))
                continue;
            const role = item.body.role;
            result.push({ item, prompt: { id: "__supplement__", title: `${writingRoles[role]?.name ?? "角色"}共用补充`, when: "仅在需要所有相关环节共用同一要求时编辑" } });
            for (const template of promptCatalog.value.find((group: PromptRoleTemplates) => group.role === role)?.templates ?? []) {
                result.push({ item, prompt: template });
            }
        }
        return result;
    });
    const matchedCards = computed(() => (cards.value.filter(({ item, prompt }) => {
        const content = prompt && "templates" in item.body ? (prompt.id === "__supplement__" ? item.body.supplement ?? "" : item.body.templates[prompt.id] ?? "") : item.kind === "reference" ? referencePurpose(item) : resourceSummary(item.body).slice(0, 200);
        return `${prompt?.title ?? ""} ${prompt?.when ?? ""} ${resourceTitle(item)} ${item.name} ${content}`.toLowerCase().includes(search.value.trim().toLowerCase());
    })));
    const visible = computed(() => (matchedCards.value.filter(({ item }) => filter.value === "all" || item.kind === filter.value)));
    const visiblePrompts = computed(() => (visible.value.filter(({ item }) => item.kind === "role_prompt").sort((a: {
        item: WritingResource;
        prompt?: {
            id: string;
            title: string;
            when?: string;
        };
    }, b: {
        item: WritingResource;
        prompt?: {
            id: string;
            title: string;
            when?: string;
        };
    }) => {
        const order = Object.keys(writingRoles);
        return order.indexOf("role" in a.item.body ? a.item.body.role : "") - order.indexOf("role" in b.item.body ? b.item.body.role : "");
    })));
    const commonCount = computed(() => (visiblePrompts.value.filter(({ prompt }) => prompt?.id === "__supplement__").length));
    const hasPromptResources = computed(() => (allowedKinds.value.includes("role_prompt") && available.value.some((item: WritingResource) => item.kind === "role_prompt")));
    const promptsLoading = computed(() => (hasPromptResources.value && !promptCatalog.value.length && !promptError.value));
    function failure(e: unknown) {
        if ((e as {
            status?: number;
        }).status === 403)
            onForbidden();
        setError(resourceError(e));
    }
    async function load() {
        setLoading(true);
        try {
            setItems((await api.adminList()).items);
            setError("");
        }
        catch (e) {
            failure(e);
        }
        finally {
            setLoading(false);
        }
    }
    onMounted(() => {
        const cleanup = (() => {
            let live = true;
            api.adminList().then((r: {
                items: WritingResource[];
            }) => {
                if (live)
                    setItems(r.items);
            }).catch(e => {
                if (live) {
                    failure(e);
                }
            }).finally(() => {
                if (live)
                    setLoading(false);
            });
            return () => {
                live = false;
            };
        })();
        if (typeof cleanup === "function")
            onUnmounted(cleanup);
    });
    watch([() => hasPromptResources.value, () => items.value, () => promptRetry.value, () => promptCatalog.value.length], (_next, _old, onCleanup) => {
        const cleanup = (() => {
            if (!hasPromptResources.value || promptCatalog.value.length)
                return;
            let live = true;
            platformApi.getPromptTemplates().then((catalog: PromptRoleTemplates[]) => {
                if (!catalog.length)
                    throw new Error("empty prompt catalog");
                if (live) {
                    setPromptCatalog(catalog);
                    setPromptError("");
                }
            }).catch(() => {
                if (live)
                    setPromptError("创作环节列表加载失败，请重新加载。");
            });
            return () => { live = false; };
        })();
        if (typeof cleanup === "function")
            onCleanup(cleanup);
    }, { immediate: true, flush: "post" });
    const selectedPromptTitle = computed(() => (selected.value?.kind !== "role_prompt" ? undefined : selectedPromptId.value === "__supplement__" ? `${selected.value && "role" in selected.value!.body ? writingRoles[selected.value!.body.role]?.name ?? "角色" : "角色"}共用补充` : promptCatalog.value.flatMap((group: PromptRoleTemplates) => group.templates).find((template: {
        id: string;
        title: string;
        content: string;
        source: string;
        editable_content?: string;
        fixed_content?: string;
        description?: string;
        when?: string;
    }) => template.id === selectedPromptId.value)?.title));
    async function edit(item: WritingResource, promptId: string | null = null) {
        const request = ++historyRequest.value;
        setSelectedPromptId(promptId);
        setSelected(item);
        setArchiving(false);
        setName(item.name);
        setSource(item.source);
        setBody(JSON.stringify(item.body, null, 2));
        setPreview(null);
        setError("");
        setHistory([]);
        setHistoryStatus("loading");
        setNote("");
        try {
            const revisions = await api.revisions(item.id);
            if (request !== historyRequest.value)
                return;
            setHistory(revisions.items);
            setHistoryStatus("ready");
        }
        catch (e) {
            if (request !== historyRequest.value)
                return;
            setHistoryStatus("error");
            failure(e);
        }
    }
    function closeEditor() {
        historyRequest.value += 1;
        setSelected(null);
        setSelectedPromptId(null);
        setPreview(null);
        setError("");
    }
    async function save() {
        if (!selected.value)
            return;
        setBusy(true);
        try {
            const parsed = JSON.parse(body.value) as ResourceBody;
            const saved = selected.value!.id ? await api.save(selected.value!.id, {
                name: name.value,
                source: source.value,
                body: parsed,
                expected_generation: selected.value!.generation,
            }) : await api.create({ name: name.value, kind: kind.value, source: source.value, body: parsed });
            setSelected(saved);
            setItems((old: WritingResource[]) => [...old.filter((i: WritingResource) => i.id !== saved.id), saved]);
            setError("");
        }
        catch (e) {
            failure(e);
        }
        finally {
            setBusy(false);
        }
    }
    async function release() {
        if (!selected.value || !preview.value || (selected.value!.kind === "role_prompt" && !previewReady.value))
            return;
        setBusy(true);
        try {
            const saved = preview.value === "publish" ? await api.publish(selected.value!.id, selected.value!.generation, note.value) : await api.rollback(selected.value!.id, selected.value!.generation, preview.value.version, note.value);
            closeEditor();
            setItems((old: WritingResource[]) => old.map((i: WritingResource) => (i.id === saved.id ? saved : i)));
            setError("");
        }
        catch (e) {
            failure(e);
        }
        finally {
            setBusy(false);
        }
    }
    async function archive() {
        if (!selected.value)
            return;
        setBusy(true);
        try {
            const saved = await api.save(selected.value!.id, {
                expected_generation: selected.value!.generation,
                name: selected.value!.name,
                source: selected.value!.source,
                body: selected.value!.body,
                status: "archived",
            });
            setItems((old: WritingResource[]) => old.map((item: WritingResource) => item.id === saved.id ? saved : item));
            closeEditor();
            setArchiving(false);
            setError("");
        }
        catch (error) {
            failure(error);
        }
        finally {
            setBusy(false);
        }
    }
    const clean = computed(() => (!!selected.value && selected.value!.name === name.value && selected.value!.source === source.value && JSON.stringify(selected.value!.body, null, 2) === body.value));
    function resourceCard(i: WritingResource, prompt?: {
        id: string;
        title: string;
        when?: string;
    }) {
        const cardTitle = prompt?.title ?? resourceTitle(i);
        return (renderNode("button", { "key": `${i.id}:${prompt?.id ?? "resource"}`, "class": `${styles.card} ${styles.resourceCard}`, "aria-label": `编辑 ${cardTitle}`, "onClick": () => void edit(i, prompt?.id ?? null) }, [
            renderNode("span", { "class": styles.resourceBadges }, [
                renderNode("span", {}, [resourceKinds[i.kind]]), renderNode("span", {}, [{ draft: "草稿", published: "已发布", archived: "已下架" }[i.status]])
            ]), renderNode("strong", { "class": styles.cardTitle }, [cardTitle]), renderNode("span", { "class": styles.preview }, [prompt && "templates" in i.body ? (prompt.id === "__supplement__" ? i.body.supplement || "适用于此分工各环节的共用要求" : i.body.templates[prompt.id] || prompt.when || "点击编辑此环节的创作要求").slice(0, 200) : i.kind === "role_prompt" && "role" in i.body ? writingRoles[i.body.role]?.purpose ?? resourceSummary(i.body).slice(0, 200) : i.kind === "reference" ? referencePurpose(i) : resourceSummary(i.body).slice(0, 200)]), renderNode("span", { "class": styles.tags }, [renderNode("span", {}, [resourceUsage(i).activation])]), renderNode("span", { "class": styles.usage }, [prompt?.when ?? resourceUsage(i).when]), renderNode("span", { "class": styles.resourceMeta }, [i.current_version ? `已发布 v${i.current_version}` : "尚未发布"]), renderNode("span", { "class": styles.editHint }, ["查看与编辑"])
        ]));
    }
    return () => {
        return (renderNode("div", { "class": styles.page }, [
            renderNode("header", { "class": styles.pageHead }, [
                renderNode("div", {}, [
                    renderNode("h1", {}, [title.value]), renderNode("p", {}, ["管理自动生效的角色提示词、AI按需查阅的写作知识库，以及作者可选用的题材与文风。"])
                ]), (props.scope ?? "all") === "all" && renderNode(RouterLink, { "to": "/writing-resources", "class": "btn btn-secondary" }, () => "提取文章文风"), renderNode("button", { "class": "btn btn-primary", "onClick": () => {
                        historyRequest.value += 1;
                        setSelectedPromptId(null);
                        setSelected({
                            id: "",
                            name: "",
                            kind: selectableKinds.value[0],
                            source: "",
                            body: initialBody(selectableKinds.value[0]),
                            generation: 0,
                            current_version: null,
                            status: "draft",
                        });
                        setArchiving(false);
                        setName("");
                        setSource("");
                        setBody(JSON.stringify(initialBody(selectableKinds.value[0])));
                        setKind(selectableKinds.value[0]);
                        setHistory([]);
                        setHistoryStatus("ready");
                        setError("");
                        setPreview(null);
                    } }, ["新建资源"])
            ]), !selected.value && error.value && renderNode("p", { "role": "alert" }, [error.value]), renderNode("div", { "class": styles.toolbar }, [
                renderNode("input", { "class": "input", "aria-label": "搜索写作资源", "placeholder": "搜索创作环节、题材、文风或规则…", "value": search.value, "onInput": (e: Event) => setSearch((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, []), renderNode("label", {}, [
                    renderNode("input", { "type": "checkbox", "checked": showArchived.value, "onChange": (event: Event) => setShowArchived((event.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked) }, []), " 显示已下架资源"
                ]), renderNode("button", { "class": "btn", "onClick": () => void load() }, ["重新加载"])
            ]), renderNode("div", { "class": styles.resourceTabs, "role": "group", "aria-label": "资源类型筛选" }, [[
                    ["all", "全部"],
                    ...allowedKinds.value.map((k: ResourceKind) => [k, resourceKinds[k]]),
                ].map(([key, label]) => (renderNode("button", { "key": key, "class": "btn btn-quiet", "aria-pressed": filter.value === key, "onClick": () => setFilter(key) }, [
                    label, renderNode("span", {}, [matchedCards.value.filter(({ item }) => key === "all" || item.kind === key).length])
                ])))]), renderNode("p", { "class": styles.hint, "role": "status" }, [loading.value || promptsLoading.value ? "正在加载资源与创作环节…" : `共 ${visible.value.length} 张卡片`]), hasPromptResources.value && promptError.value && renderNode("p", { "role": "alert" }, [
                promptError.value, "部分环节尚未加载，搜索结果可能不完整。", renderNode("button", { "class": "btn", "onClick": () => setPromptRetry((value: number) => value + 1) }, ["重新加载创作环节"])
            ]), !loading.value && !promptsLoading.value && !promptError.value && visible.value.length === 0 && (renderNode("div", { "class": styles.empty }, [search.value || filter.value !== "all" ? "没有匹配的资源，请调整搜索或筛选条件。" : "暂无资源，点击“新建资源”开始添加。"])), visiblePrompts.value.length > 0 && renderNode("section", { "aria-labelledby": "automatic-prompts-heading" }, [
                renderNode("h2", { "id": "automatic-prompts-heading" }, ["角色提示词 · 自动生效"]), renderNode("p", { "class": styles.hint }, [
                    visiblePrompts.value.length - commonCount.value, " 个环节提示词 · ", commonCount.value, " 项共用补充，共 ", visiblePrompts.value.length, " 张卡片"
                ]), renderNode("p", {}, ["每张卡片对应一个具体环节，点击后只编辑该环节。共用补充单独列出；进入相应环节时自动使用已发布内容。"]), Object.entries(writingRoles).map(([role, description]) => {
                    const group = visiblePrompts.value.filter(({ item }) => "role" in item.body && item.body.role === role);
                    if (!group.length)
                        return null;
                    return renderNode("section", { "key": role, "class": styles.promptGroup, "aria-label": `${description.name}环节提示词` }, [
                        renderNode("div", { "class": styles.promptGroupHead }, [
                            renderNode("h3", {}, [description.name]), renderNode("span", {}, [
                                group.length, " 张卡片"
                            ])
                        ]), renderNode("p", { "class": styles.hint }, [description.purpose]), renderNode("div", { "class": `${styles.grid} ${styles.resourceGrid}` }, [group.map(({ item, prompt }) => resourceCard(item, prompt))])
                    ]);
                })
            ]), visible.value.some(({ item }) => item.kind === "reference") && renderNode("section", { "aria-labelledby": "reference-library-heading", "style": { marginTop: "32px" } }, [
                renderNode("h2", { "id": "reference-library-heading" }, ["写作知识库 · AI按需查阅"]), renderNode("p", {}, ["这些是写作方法与示例，无需作者选择。人物设计与关系写法不是本书的人物名单或关系设定；本书实际人物与关系会随创作上下文使用。"]), renderNode("div", { "class": `${styles.grid} ${styles.resourceGrid}` }, [visible.value.filter(({ item }) => item.kind === "reference").map(({ item }) => resourceCard(item))])
            ]), renderNode("section", { "aria-labelledby": "selectable-resources-heading", "style": { marginTop: "32px" } }, [
                renderNode("h2", { "id": "selectable-resources-heading" }, ["可选写作资源"]), renderNode("p", {}, ["作者为作品选用后生效，作品保留选定版本，平台更新由作者确认后采用。未配置资源的旧作品沿用原有默认规则。"]), renderNode("div", { "class": `${styles.grid} ${styles.resourceGrid}` }, [visible.value.filter(({ item }) => item.kind !== "role_prompt" && item.kind !== "reference").map(({ item }) => resourceCard(item))])
            ]), renderNode("section", { "style": { marginTop: "32px" }, "aria-labelledby": "private-writing-context-heading" }, [
                renderNode("h2", { "id": "private-writing-context-heading" }, ["作品自行维护的内容"]), renderNode("p", {}, ["作者文风与样本、人物状态、世界观、历史正文、大纲与章节计划、作品复盘经验，随创作过程使用；由各作品自行维护，不会同步为平台资源。"])
            ]), items.value.some(isSupportingReference) && renderNode("details", { "style": { marginTop: "32px" } }, [
                renderNode("summary", {}, ["资料来源与使用说明"]), renderNode("p", {}, ["部分参考素材来自 webnovel-writer，原始来源与许可随资料保留；这里只作为说明资料，不列入可选创作素材。"]), items.value.filter(isSourceNotice).map((item: WritingResource) => renderNode("details", { "key": item.id }, [
                    renderNode("summary", {}, [resourceTitle(item)]), renderNode(ResourceContent, { "body": item.body })
                ]))
            ]), selected.value && (renderNode(AdminDialog, { "title": archiving.value ? "下架资源" : preview.value ? "发布预览" : `编辑${selectedPromptTitle.value ?? (resourceTitle(selected.value) || "新资源")}`, "busy": busy.value, "onClose": closeEditor, children: [archiving.value ? (renderNode(Fragment, {}, [
                        renderNode("p", {}, [
                            "确认下架“", resourceTitle(selected.value), "”？", selected.value!.kind === "reference" ? "下架后新任务不再查阅此资料，已受理任务仍保留原版本。" : "下架后用户不能再新选此资源，已选用的作品仍保留原有快照。"
                        ]), renderNode("p", {}, ["版本历史保留，可在“显示已下架资源”中重新编辑并发布。本次不会保存未提交的编辑内容。"]), renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => setArchiving(false) }, ["取消下架"]), renderNode("button", { "class": "btn btn-primary", "disabled": busy.value, "onClick": () => void archive() }, ["确认下架"])
                    ])) : preview.value ? (renderNode(Fragment, {}, [
                        renderNode("p", {}, [
                            preview.value === "publish" ? "发布当前已保存草稿" : "回退至历史版本 v" + preview.value.version, "。", ["role_prompt", "reference"].includes(selected.value!.kind) ? "新发起的创作使用发布版本，已受理任务保留原版本。" : "历史版本保持不变，已有作品需主动采用更新。"
                        ]), selected.value!.kind === "role_prompt" && renderNode("p", { "class": "banner banner-warning" }, [
                            "本次", preview.value === "publish" ? "发布" : "回退", "会更新整个 AI 分工，下列全部环节和共用补充一起生效。请逐项核对后确认。"
                        ]), renderNode("h3", {}, [selected.value!.kind === "role_prompt" ? `${resourceTitle(selected.value)}：全部环节与共用补充` : (preview.value === "publish" ? resourceTitle(selected.value) : preview.value.name)]), selected.value!.kind === "role_prompt" && "templates" in (preview.value === "publish" ? selected.value!.body : preview.value.body) ? renderNode(RolePromptFields, { "value": (preview.value === "publish" ? selected.value!.body : preview.value.body) as Extract<ResourceBody, {
                                role: string;
                            }>, "onReadyChange": setPreviewReady, "readOnly": true }) : renderNode(ResourceContent, { "body": preview.value === "publish" ? selected.value!.body : preview.value.body }), selected.value!.kind === "role_prompt" && !previewReady.value && renderNode("p", { "role": "status" }, ["全部发布内容读取完成后，才可确认发布或回退。"]), renderNode("label", {}, [
                            "发布说明", renderNode("input", { "class": "input", "value": note.value, "onInput": (e: Event) => setNote((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                        ]), renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => setPreview(null) }, ["返回编辑"]), renderNode("button", { "class": "btn btn-primary", "disabled": busy.value || (selected.value!.kind === "role_prompt" && !previewReady.value), "onClick": () => void release() }, [preview.value === "publish" ? "确认发布" : "确认回退"])
                    ])) : (renderNode(Fragment, {}, [
                        selected.value!.kind === "role_prompt" && renderNode("p", {}, [
                            "当前只编辑“", selectedPromptTitle.value, "”。发布和回退仍按所属 AI 分工统一管理；发布前请核对该分工草稿中的其他修改。"
                        ]), renderNode("fieldset", { "disabled": busy.value, "class": styles.resourceFields }, [
                            selected.value!.kind !== "role_prompt" && renderNode("label", {}, [
                                "资源名称", renderNode("input", { "class": "input", "value": ["role_prompt", "reference"].includes(selected.value!.kind) ? resourceTitle({ name: name.value, kind: selected.value!.kind }) : name.value, "onInput": (e: Event) => setName((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [])
                            ]), !selected.value!.id && (renderNode("label", {}, [
                                "资源类型", renderNode("select", { "class": "input", "value": kind.value, "onChange": (e: Event) => {
                                        const next = (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value as ResourceKind;
                                        setKind(next);
                                        setBody(JSON.stringify(next === "reference" ? { files: [] } : next === "style" ? { profile: emptyResourceStyleProfile() } : next === "genre" ? { catalog_id: crypto.randomUUID(), fields: emptyFields() } : next === "genre_rule" ? {
                                            genre_ids: [],
                                            roles: {
                                                writer: "",
                                                planner: "",
                                                audit: "",
                                            },
                                        } : {
                                            roles: {
                                                writer: "",
                                                planner: "",
                                                audit: "",
                                            },
                                        }));
                                    } }, [Object.entries(resourceKinds).filter(([k]) => selectableKinds.value.includes(k as ResourceKind)).map(([k, v]) => (renderNode("option", { "key": k, "value": k }, [v])))])
                            ])), selected.value!.kind === "role_prompt" && "templates" in JSON.parse(body.value) ? renderNode(RolePromptFields, { "value": JSON.parse(body.value) as Extract<ResourceBody, {
                                    role: string;
                                }>, "templateId": selectedPromptId.value ?? undefined, "onChange": (value: ResourceBody) => setBody(JSON.stringify(value, null, 2)) }) : renderNode(ResourceBodyFields, { "kind": selected.value!.id ? selected.value!.kind : kind.value, "value": JSON.parse(body.value) as ResourceBody, "genres": items.value.filter((item: WritingResource) => item.kind === "genre" && "catalog_id" in item.body).map((item: WritingResource) => ({ id: (item.body as {
                                        catalog_id: string;
                                    }).catalog_id, name: item.name })), "onChange": (value: ResourceBody) => setBody(JSON.stringify(value, null, 2)) })
                        ]), renderNode("footer", { "class": styles.actions }, [
                            selected.value!.id && selected.value!.kind !== "role_prompt" && selected.value!.status !== "archived" && renderNode("button", { "class": "btn btn-quiet", "disabled": busy.value, "onClick": () => { setError(""); setArchiving(true); } }, ["下架资源"]), renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": closeEditor }, ["取消"]), renderNode("button", { "class": "btn", "disabled": busy.value || !name.value.trim(), "onClick": () => void save() }, ["保存草稿"]), renderNode("button", { "class": "btn btn-primary", "disabled": busy.value || !clean.value || !selected.value!.id, "onClick": () => { setPreviewReady(false); setPreview("publish"); } }, ["预览发布"])
                        ]), renderNode("h3", {}, ["版本历史"]), historyStatus.value === "loading" && renderNode("p", { "role": "status" }, ["正在读取发布历史…"]), historyStatus.value === "error" && renderNode("p", { "class": styles.hint }, ["发布历史未能加载，请关闭后重新打开此资源重试。"]), historyStatus.value === "ready" && !history.value.length && (renderNode("p", { "class": styles.hint }, ["尚无发布记录，发布后可在这里查看和回退。"])), history.value.map((h: ResourceRevision) => (renderNode("details", { "key": h.version }, [
                            renderNode("summary", {}, [
                                "v", h.version, " · ", resourceTitle({ name: h.name, kind: selected.value!.kind }), " · ", formatDate(h.created_at)
                            ]), renderNode("p", {}, [h.note]), selected.value!.kind === "role_prompt" && "templates" in h.body ? renderNode(RolePromptFields, { "value": h.body, "readOnly": true }) : renderNode(ResourceContent, { "body": h.body }), renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => { setPreviewReady(false); setPreview(h); } }, [
                                "预览回退至 v", h.version
                            ])
                        ])))
                    ])), error.value && renderNode("p", { "role": "alert" }, [error.value])] }))
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        scope: { type: String as PropType<"all" | "prompts" | "genres">, default: undefined }
    }
});
export default WritingResources;
function initialBody(kind: ResourceKind): ResourceBody {
    if (kind === 'reference')
        return { files: [] };
    if (kind === 'genre')
        return { catalog_id: crypto.randomUUID(), fields: emptyFields() };
    if (kind === 'style')
        return { profile: emptyResourceStyleProfile() };
    return {
        ...(kind === 'genre_rule' ? { genre_ids: [] } : {}),
        roles: { writer: '', planner: '', audit: '' },
    };
}
