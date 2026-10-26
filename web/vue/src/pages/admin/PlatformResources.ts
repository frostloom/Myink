import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import type { PropType } from 'vue';
import { Fragment, computed, defineComponent, h as renderNode, shallowRef, watch } from 'vue';
import { api } from "../../../../src/lib/api";
import { formatApiError } from "../../../../src/lib/apiError";
import { composeFields, type GenreCatalogItem, type GenreFields } from "../../../../src/lib/genrePacks";
import { platformApi, type PlatformConfigurationData, type PlatformConfigurationInput, type PromptRoleTemplates, } from "../../../../src/lib/platformApi";
import styles from "../../../../src/pages/admin/AdminResources.module.css";
import GenrePackFields from "../../components/GenrePackFields.vue";
import { AdminDialog } from "./AdminDialog";
import { useAdminContext } from './context';
import { CreationInput, Disclosure } from "./ExecutionContent";
const PROMPTS = [
    { id: 'writer', name: '写作', description: '章节正文、人物动作与叙事表达' },
    { id: 'planner', name: '规划', description: '故事设定、大纲与章节计划' },
    { id: 'validator_l2', name: '语义校验', description: '情节逻辑与设定一致性检查' },
    { id: 'extract', name: '抽取', description: '人物、事件与状态信息抽取' },
    { id: 'audit', name: '审核', description: '内容质量与写作要求审核' },
    { id: 'summarize', name: '摘要', description: '章节内容与长期记忆摘要' },
];
function genreValue(configuration: PlatformConfigurationData, item: GenreCatalogItem): GenreFields {
    const defaults = composeFields(item);
    const overrides = configuration.genre_packs[item.id] ?? {};
    return Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, overrides[key as keyof GenreFields] ?? value])) as unknown as GenreFields;
}
const PlatformResources = defineComponent((props: {
    kind: "prompts" | "genres";
}) => {
    const { onForbidden } = useAdminContext();
    const configuration = shallowRef<PlatformConfigurationData | null>(null);
    const setConfiguration = (next: typeof configuration.value | ((old: typeof configuration.value) => typeof configuration.value)) => { configuration.value = typeof next === "function" ? next(configuration.value) : next; };
    const promptTemplates = shallowRef<PromptRoleTemplates[]>([]);
    const setPromptTemplates = (next: typeof promptTemplates.value | ((old: typeof promptTemplates.value) => typeof promptTemplates.value)) => { promptTemplates.value = typeof next === "function" ? next(promptTemplates.value) : next; };
    const catalog = shallowRef<GenreCatalogItem[]>([]);
    const setCatalog = (next: typeof catalog.value | ((old: typeof catalog.value) => typeof catalog.value)) => { catalog.value = typeof next === "function" ? next(catalog.value) : next; };
    const loading = shallowRef(true);
    const setLoading = (next: typeof loading.value | ((old: typeof loading.value) => typeof loading.value)) => { loading.value = typeof next === "function" ? next(loading.value) : next; };
    const busy = shallowRef(false);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const error = shallowRef("");
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const notice = shallowRef("");
    const setNotice = (next: typeof notice.value | ((old: typeof notice.value) => typeof notice.value)) => { notice.value = typeof next === "function" ? next(notice.value) : next; };
    const search = shallowRef("");
    const setSearch = (next: typeof search.value | ((old: typeof search.value) => typeof search.value)) => { search.value = typeof next === "function" ? next(search.value) : next; };
    const selected = shallowRef<string | null>(null);
    const setSelected = (next: typeof selected.value | ((old: typeof selected.value) => typeof selected.value)) => { selected.value = typeof next === "function" ? next(selected.value) : next; };
    const prompt = shallowRef("");
    const setPrompt = (next: typeof prompt.value | ((old: typeof prompt.value) => typeof prompt.value)) => { prompt.value = typeof next === "function" ? next(prompt.value) : next; };
    const genre = shallowRef<GenreFields | null>(null);
    const setGenre = (next: typeof genre.value | ((old: typeof genre.value) => typeof genre.value)) => { genre.value = typeof next === "function" ? next(genre.value) : next; };
    const restore = shallowRef(false);
    useMemoryFormGuard(() => selected.value !== null);
    const setRestore = (next: typeof restore.value | ((old: typeof restore.value) => typeof restore.value)) => { restore.value = typeof next === "function" ? next(restore.value) : next; };
    const isPrompt = computed(() => (props.kind === "prompts"));
    const title = computed(() => (isPrompt.value ? "提示词" : "题材包"));
    const load = async () => {
        setLoading(true);
        setError("");
        setNotice("");
        try {
            const [config, items, templates] = await Promise.all([
                platformApi.getConfiguration(),
                props.kind === "genres" ? api.listGenrePacks() : Promise.resolve([]),
                props.kind === "prompts" ? platformApi.getPromptTemplates() : Promise.resolve([]),
            ]);
            setConfiguration(config);
            setCatalog(items);
            setPromptTemplates(templates);
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403)
                onForbidden();
            setError(formatApiError(err, "配置加载失败，请重试"));
        }
        finally {
            setLoading(false);
        }
    };
    watch([() => load], (_next, _old, onCleanup) => {
        const cleanup = (() => {
            void load();
        })();
        if (typeof cleanup === "function")
            onCleanup(cleanup);
    }, { immediate: true, flush: "post" });
    function close() {
        setSelected(null);
        setError("");
    }
    function edit(id: string) {
        if (!configuration.value)
            return;
        setSelected(id);
        setError("");
        setNotice("");
        setRestore(false);
        if (isPrompt.value)
            setPrompt(configuration.value.prompts[id] ?? "");
        else {
            const item = catalog.value.find((item: GenreCatalogItem) => item.id === id);
            if (item)
                setGenre(genreValue(configuration.value, item));
        }
    }
    async function save() {
        if (!configuration.value || !selected.value)
            return;
        setBusy(true);
        setError("");
        const prompts = { ...configuration.value.prompts };
        const genrePacks = { ...configuration.value.genre_packs };
        if (isPrompt.value) {
            if (prompt.value.trim())
                prompts[selected.value] = prompt.value;
            else
                delete prompts[selected.value];
        }
        else if (restore.value)
            delete genrePacks[selected.value];
        else if (genre.value)
            genrePacks[selected.value] = genre.value;
        try {
            const saved = await platformApi.updateConfiguration({
                ...configuration.value,
                prompts,
                genre_packs: genrePacks as PlatformConfigurationInput["genre_packs"],
                model_connections: configuration.value.model_connections.map((connection: import("../../../../src/lib/platformApi").PlatformConnection) => ({
                    id: connection.id,
                    name: connection.name,
                    protocol: connection.protocol,
                    base_url: connection.base_url,
                    model: connection.model,
                    enabled: connection.enabled,
                    user_visible: connection.user_visible,
                    input_price: connection.input_price,
                    output_price: connection.output_price,
                })),
            });
            setConfiguration(saved);
            setSelected(null);
            setNotice(`${title.value}已保存`);
            if (!isPrompt.value) {
                setCatalog([]);
                setLoading(true);
                try {
                    setCatalog(await api.listGenrePacks());
                }
                catch (err) {
                    if ((err as {
                        status?: number;
                    }).status === 403)
                        onForbidden();
                    setError("题材包已保存，但列表刷新失败，请重新加载配置后继续编辑。");
                }
                finally {
                    setLoading(false);
                }
            }
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403)
                onForbidden();
            setError((err as {
                status?: number;
            }).status === 409 ? "配置已被其他管理员更新，草稿已保留。请取消后重新加载配置，再核对更改。" : formatApiError(err, "保存失败，请重试"));
        }
        finally {
            setBusy(false);
        }
    }
    const cards = computed(() => (isPrompt.value ? PROMPTS.map((role: {
        id: string;
        name: string;
        description: string;
    }) => ({
        id: role.id,
        name: `${role.name}提示词`,
        group: "平台提示词",
        summary: promptTemplates.value.find((item: PromptRoleTemplates) => item.role === role.id)?.templates[0]?.content ?? "未读取到内置模板",
        custom: !!configuration.value?.prompts[role.id],
    })) : catalog.value.map((item: GenreCatalogItem) => ({
        id: item.id,
        name: `${item.name}题材包`,
        group: item.group,
        summary: configuration.value ? genreValue(configuration.value, item).selling_point : "",
        custom: !!configuration.value?.genre_packs[item.id],
    }))));
    const filtered = computed(() => (cards.value.filter((card: {
        id: string;
        name: string;
        group: string;
        summary: string;
        custom: boolean;
    }) => `${card.name} ${card.group} ${card.summary}`.toLowerCase().includes(search.value.trim().toLowerCase()))));
    const selectedCard = computed(() => (cards.value.find((card: {
        id: string;
        name: string;
        group: string;
        summary: string;
        custom: boolean;
    }) => card.id === selected.value)));
    const selectedTemplates = computed(() => (promptTemplates.value.find((item: PromptRoleTemplates) => item.role === selected.value)?.templates ?? []));
    return () => {
        return (renderNode("div", { "class": styles.page }, [
            renderNode("header", { "class": styles.pageHead }, [renderNode("div", {}, [
                    renderNode("h1", {}, [title.value]), renderNode("p", {}, [isPrompt.value ? "查看实际内置提示词，管理各创作环节的追加指令。" : "管理题材的卖点、流派、节奏与世界设定。"])
                ])]), !selected.value && error.value && (renderNode("p", { "role": "alert", "class": "banner banner-error" }, [error.value])), notice.value && renderNode("p", { "role": "status" }, [notice.value]), renderNode("div", { "class": styles.toolbar }, [
                renderNode("input", { "class": "input", "aria-label": `搜索${title.value}`, "placeholder": `搜索${title.value}名称或内容`, "value": search.value, "onInput": (e: Event) => setSearch((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, []), renderNode("span", {}, [
                    filtered.value.length, " 个", title.value
                ]), renderNode("button", { "class": "btn btn-quiet", "disabled": loading.value || busy.value, "onClick": () => void load() }, ["重新加载配置"])
            ]), loading.value ? (renderNode("p", { "role": "status" }, [
                "正在加载", title.value, "…"
            ])) : !configuration.value ? (renderNode("p", { "class": "empty" }, ["配置加载失败，请重新加载配置。"])) : filtered.value.length === 0 ? (renderNode("div", { "class": styles.empty }, [
                "没有匹配的", title.value, "，请尝试其他关键词。"
            ])) : (renderNode("div", { "class": styles.grid }, [filtered.value.map((card: {
                    id: string;
                    name: string;
                    group: string;
                    summary: string;
                    custom: boolean;
                }) => (renderNode("button", { "type": "button", "key": card.id, "class": `${styles.card} ${styles.resourceCard}`, "aria-label": `编辑 ${card.name}`, "onClick": () => edit(card.id) }, [
                    renderNode("span", { "class": styles.cardHead }, [
                        renderNode("span", { "class": styles.provider }, [card.group]), renderNode("span", {}, [card.custom ? (isPrompt.value ? "内置 + 追加指令" : "已自定义") : "内置内容"])
                    ]), renderNode("strong", { "class": styles.cardTitle }, [card.name]), renderNode("span", { "class": styles.preview }, [card.summary || "暂无内容，点击编辑"]), renderNode("span", { "class": styles.editHint }, [
                        "编辑 ", isPrompt.value ? "提示词" : "题材包", " ↗"
                    ])
                ])))])), selectedCard.value && (renderNode(AdminDialog, { "title": `编辑${selectedCard.value.name}`, "onClose": close, "busy": busy.value, children: [renderNode("form", { "onSubmit": (e: SubmitEvent) => {
                            e.preventDefault();
                            void save();
                        } }, [
                        renderNode("p", { "class": styles.hint }, [isPrompt.value ? "附加指令会与内置提示词一起生效；留空保存可恢复内置提示词。" : "保存后用于新建作品，已有作品保留创建时的题材快照。"]), isPrompt.value && (renderNode("section", { "class": styles.templates, "aria-label": "内置提示词模板" }, [
                            renderNode("h3", {}, [
                                "实际内置模板 · ", selectedTemplates.value.length, " 个"
                            ]), renderNode("p", { "class": styles.hint }, ["内置模板由程序维护，以下为当前工作流使用的真实内容。每次调用还会按任务拼接题材、文风和上下文；建书设定按题材能力使用对应版本。"]), selectedTemplates.value.map((template: {
                                id: string;
                                title: string;
                                content: string;
                                source: string;
                                editable_content?: string;
                                fixed_content?: string;
                                description?: string;
                                when?: string;
                            }, index: number) => (renderNode("details", { "key": template.id, "open": index === 0 }, [
                                renderNode("summary", {}, [template.title]), renderNode(CreationInput, { "value": template.content, "system": true }), renderNode(Disclosure, { "title": "技术诊断", children: [renderNode("small", {}, [
                                            "来源：", template.source
                                        ])] })
                            ])))
                        ])), renderNode("fieldset", { "class": styles.resourceFields, "disabled": busy.value }, [isPrompt.value ? (renderNode("label", {}, [
                                "管理员追加指令", renderNode("textarea", { "class": "textarea", "rows": 12, "maxLength": 20000, "value": prompt.value, "onInput": (e: Event) => setPrompt((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value), "placeholder": "输入该创作环节的附加要求" }, [])
                            ])) : (genre.value && (renderNode(Fragment, {}, [
                                !restore.value && (renderNode(GenrePackFields, { "value": genre.value, "onChange": (next: GenreFields) => {
                                        setGenre(next);
                                        setRestore(false);
                                    } })), renderNode("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => {
                                        setRestore((previous: boolean) => !previous);
                                    } }, [restore.value ? "撤销恢复" : "恢复内置内容"]), restore.value && (renderNode("p", { "role": "status" }, ["保存后将移除自定义覆盖并重新加载内置内容，取消不会修改题材包。"]))
                            ])))]), error.value && (renderNode("p", { "role": "alert", "class": "banner banner-error" }, [error.value])), renderNode("footer", { "class": styles.actions }, [
                            renderNode("button", { "type": "button", "class": "btn btn-secondary", "disabled": busy.value, "onClick": close }, ["取消"]), renderNode("button", { "type": "submit", "class": "btn btn-primary", "disabled": busy.value }, [busy.value ? "保存中…" : `保存${title.value}`])
                        ])
                    ])] }))
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        kind: { type: String as PropType<"prompts" | "genres">, required: true }
    }
});
export default PlatformResources;
