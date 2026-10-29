import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import { computed, defineComponent, h as renderNode, shallowRef, watch } from 'vue';
import { RouterLink as Link } from 'vue-router';
import { formatApiError, formatErrorText } from "../../../../src/lib/apiError";
import { platformApi, type PlatformConfigurationData, type PlatformConfigurationInput, type PlatformConnection, type PlatformConnectionInput, } from "../../../../src/lib/platformApi";
import styles from "../../../../src/pages/admin/AdminResources.module.css";
import type { ModelProbeRequest } from "../../../../src/types";
import { AdminDialog } from "./AdminDialog";
import { useAdminContext } from './context';
const PROVIDERS = [
    { id: 'openai', name: 'OpenAI', protocol: 'openai', url: 'https://api.openai.com/v1' },
    { id: 'anthropic', name: 'Anthropic', protocol: 'anthropic', url: 'https://api.anthropic.com/v1' },
    { id: 'deepseek', name: 'DeepSeek', protocol: 'openai', url: 'https://api.deepseek.com/v1' },
    {
        id: 'dashscope',
        name: '通义千问（DashScope）',
        protocol: 'openai',
        url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    },
    { id: 'zhipu', name: '智谱 GLM', protocol: 'openai', url: 'https://open.bigmodel.cn/api/paas/v4' },
    { id: 'custom', name: '自定义 / 中转服务', protocol: 'openai', url: '' },
] as const;
function providerFor(connection: PlatformConnection) {
    return PROVIDERS.find((p: {
        readonly id: "openai";
        readonly name: "OpenAI";
        readonly protocol: "openai";
        readonly url: "https://api.openai.com/v1";
    } | {
        readonly id: "anthropic";
        readonly name: "Anthropic";
        readonly protocol: "anthropic";
        readonly url: "https://api.anthropic.com/v1";
    } | {
        readonly id: "deepseek";
        readonly name: "DeepSeek";
        readonly protocol: "openai";
        readonly url: "https://api.deepseek.com/v1";
    } | {
        readonly id: "dashscope";
        readonly name: "通义千问（DashScope）";
        readonly protocol: "openai";
        readonly url: "https://dashscope.aliyuncs.com/compatible-mode/v1";
    } | {
        readonly id: "zhipu";
        readonly name: "智谱 GLM";
        readonly protocol: "openai";
        readonly url: "https://open.bigmodel.cn/api/paas/v4";
    } | {
        readonly id: "custom";
        readonly name: "自定义 / 中转服务";
        readonly protocol: "openai";
        readonly url: "";
    }) => p.url && connection.base_url.replace(/\/$/, '') === p.url) ?? PROVIDERS[5];
}
function input(connection: PlatformConnection): PlatformConnectionInput {
    return {
        id: connection.id,
        name: connection.name,
        protocol: connection.protocol,
        base_url: connection.base_url,
        model: connection.model,
        enabled: connection.enabled,
        user_visible: connection.user_visible,
        minimum_tier: connection.minimum_tier ?? 'normal',
        input_price: connection.input_price,
        output_price: connection.output_price,
    };
}
type Draft = PlatformConnection & {
    api_key: string;
};
const ModelManagement = defineComponent((_props: Record<string, never>) => {
    const { onForbidden } = useAdminContext();
    const configuration = shallowRef<PlatformConfigurationData | null>(null);
    const setConfiguration = (next: typeof configuration.value | ((old: typeof configuration.value) => typeof configuration.value)) => { configuration.value = typeof next === "function" ? next(configuration.value) : next; };
    const loading = shallowRef(true);
    const setLoading = (next: typeof loading.value | ((old: typeof loading.value) => typeof loading.value)) => { loading.value = typeof next === "function" ? next(loading.value) : next; };
    const error = shallowRef("");
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const notice = shallowRef("");
    const setNotice = (next: typeof notice.value | ((old: typeof notice.value) => typeof notice.value)) => { notice.value = typeof next === "function" ? next(notice.value) : next; };
    const search = shallowRef("");
    const setSearch = (next: typeof search.value | ((old: typeof search.value) => typeof search.value)) => { search.value = typeof next === "function" ? next(search.value) : next; };
    const draft = shallowRef<Draft | null>(null);
    const setDraft = (next: typeof draft.value | ((old: typeof draft.value) => typeof draft.value)) => { draft.value = typeof next === "function" ? next(draft.value) : next; };
    const provider = shallowRef("custom");
    const setProvider = (next: typeof provider.value | ((old: typeof provider.value) => typeof provider.value)) => { provider.value = typeof next === "function" ? next(provider.value) : next; };
    const deleting = shallowRef<PlatformConnection | null>(null);
    const setDeleting = (next: typeof deleting.value | ((old: typeof deleting.value) => typeof deleting.value)) => { deleting.value = typeof next === "function" ? next(deleting.value) : next; };
    const replacement = shallowRef("");
    const setReplacement = (next: typeof replacement.value | ((old: typeof replacement.value) => typeof replacement.value)) => { replacement.value = typeof next === "function" ? next(replacement.value) : next; };
    const busy = shallowRef(false);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const probeBusy = shallowRef(false);
    const setProbeBusy = (next: typeof probeBusy.value | ((old: typeof probeBusy.value) => typeof probeBusy.value)) => { probeBusy.value = typeof next === "function" ? next(probeBusy.value) : next; };
    const probeResult = shallowRef("");
    const setProbeResult = (next: typeof probeResult.value | ((old: typeof probeResult.value) => typeof probeResult.value)) => { probeResult.value = typeof next === "function" ? next(probeResult.value) : next; };
    const models = shallowRef<string[]>([]);
    const setModels = (next: typeof models.value | ((old: typeof models.value) => typeof models.value)) => { models.value = typeof next === "function" ? next(models.value) : next; };
    const probeError = shallowRef("");
    const setProbeError = (next: typeof probeError.value | ((old: typeof probeError.value) => typeof probeError.value)) => { probeError.value = typeof next === "function" ? next(probeError.value) : next; };
    const showKey = shallowRef(false);
    useMemoryFormGuard(() => draft.value !== null || deleting.value !== null);
    const setShowKey = (next: typeof showKey.value | ((old: typeof showKey.value) => typeof showKey.value)) => { showKey.value = typeof next === "function" ? next(showKey.value) : next; };
    const load = async () => {
        setLoading(true);
        setError("");
        try {
            setConfiguration(await platformApi.getConfiguration());
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403)
                onForbidden();
            setError(formatApiError(err, "模型加载失败"));
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
    function edit(connection?: PlatformConnection) {
        setError("");
        setNotice("");
        setModels([]);
        setProbeResult("");
        setProbeError("");
        setShowKey(false);
        setProvider(connection ? providerFor(connection).id : "openai");
        setDraft(connection ? { ...connection, api_key: "" } : {
            id: crypto.randomUUID(),
            name: "",
            protocol: "openai",
            base_url: PROVIDERS[0].url,
            model: "",
            api_key: "",
            has_api_key: false,
            enabled: true,
            user_visible: true,
        });
    }
    function patch(values: Partial<Draft>) {
        setDraft((previous: Draft | null) => (previous ? { ...previous, ...values } : previous));
        setProbeResult("");
        setProbeError("");
        setModels([]);
    }
    async function persist(connections: PlatformConnectionInput[], routes: Record<string, string>,
        vipRoutes = configuration.value?.vip_model_routes ?? {}) {
        if (!configuration.value)
            return false;
        setBusy(true);
        setError("");
        setNotice("");
        try {
            const saved = await platformApi.updateConfiguration({
                ...configuration.value,
                model_connections: connections,
                model_routes: routes,
                vip_model_routes: vipRoutes,
                genre_packs: configuration.value.genre_packs as PlatformConfigurationInput["genre_packs"],
            });
            setConfiguration(saved);
            setNotice("模型配置已保存");
            return true;
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403)
                onForbidden();
            setError((err as {
                status?: number;
            }).status === 409 ? "配置已被其他管理员更新，草稿已保留。请取消后重新加载配置，再核对更改。" : formatApiError(err, "保存失败，请重试"));
            return false;
        }
        finally {
            setBusy(false);
        }
    }
    async function save() {
        if (!draft.value || !configuration.value)
            return;
        const changed = {
            ...input(draft.value),
            name: draft.value!.name.trim(),
            base_url: draft.value!.base_url.trim().replace(/\/$/, ""),
            model: draft.value!.model.trim(),
            ...(draft.value!.api_key.trim() ? { api_key: draft.value!.api_key.trim() } : {}),
        };
        if (!changed.name || !changed.model || !changed.base_url || (!draft.value!.has_api_key && !draft.value!.api_key.trim())) {
            setError("请填写显示名称、模型 ID、请求地址和 API Key");
            return;
        }
        try {
            if (!["http:", "https:"].includes(new URL(changed.base_url).protocol))
                throw new Error("protocol");
        }
        catch {
            setError("请输入有效的 http/https 请求地址");
            return;
        }
        const normalReference = Object.values(configuration.value.model_routes).includes(`custom:${draft.value!.id}`);
        const vipReference = Object.values(configuration.value.vip_model_routes ?? {}).includes(`custom:${draft.value!.id}`);
        if (!changed.enabled && (normalReference || vipReference)) {
            setError("此模型仍用于平台任务，请先在“模型分配”中更换模型，再停用。");
            return;
        }
        if (changed.minimum_tier === 'vip' && normalReference) {
            setError('此模型仍分配给普通用户，请先更换普通用户的模型分配，再设为 VIP 专用。');
            return;
        }
        const routes = { ...configuration.value.model_routes };
        if (!routes.writer) {
            if (!changed.enabled || changed.minimum_tier === 'vip') {
                setError("请先启用第一个模型，作为平台的默认写作模型。");
                return;
            }
            routes.writer = `custom:${draft.value!.id}`;
        }
        const exists = configuration.value.model_connections.some((c: PlatformConnection) => c.id === draft.value!.id);
        const connections = configuration.value.model_connections.map((c: PlatformConnection) => (c.id === draft.value!.id ? changed : input(c)));
        if (!exists)
            connections.push(changed);
        if (await persist(connections, routes))
            setDraft(null);
    }
    async function remove() {
        if (!deleting.value || !configuration.value)
            return;
        const connections = configuration.value.model_connections.filter((c: PlatformConnection) => c.id !== deleting.value!.id).map(input);
        const routes = Object.fromEntries(Object.entries(configuration.value.model_routes).filter(([, value]) => value !== `custom:${deleting.value!.id}`));
        if (connections.length && configuration.value.model_routes.writer === `custom:${deleting.value!.id}`) {
            if (!connections.some((c: PlatformConnectionInput) => c.enabled && c.minimum_tier !== 'vip' && `custom:${c.id}` === replacement.value)) {
                setError("请选择一个已启用的替代写作模型，再确认删除。");
                return;
            }
            routes.writer = replacement.value;
        }
        const vipRoutes = Object.fromEntries(Object.entries(configuration.value.vip_model_routes ?? {})
            .filter(([, value]) => value !== `custom:${deleting.value!.id}`));
        if (await persist(connections, routes, vipRoutes))
            setDeleting(null);
    }
    async function probe(operation: "models" | "test") {
        if (!draft.value)
            return;
        if (!draft.value!.base_url.trim() || (!draft.value!.has_api_key && !draft.value!.api_key.trim()) || (operation === "test" && !draft.value!.model.trim())) {
            setProbeError("请先填写请求地址、API Key 和测试所需的模型 ID");
            return;
        }
        const body: ModelProbeRequest = {
            protocol: draft.value!.protocol,
            base_url: draft.value!.base_url.trim(),
            ...(draft.value!.model.trim() ? { model: draft.value!.model.trim() } : {}),
            ...(draft.value!.api_key.trim() ? { api_key: draft.value!.api_key.trim() } : { connection_id: draft.value!.id }),
        };
        setProbeBusy(true);
        setProbeResult("");
        setProbeError("");
        try {
            if (operation === "models") {
                const result = await platformApi.listModels(body);
                if (!result.ok) {
                    setProbeError(formatErrorText(result.error, undefined, "获取模型列表失败，请检查地址和接口支持情况"));
                    return;
                }
                setModels(result.models);
                setProbeResult(`已获取 ${result.models.length} 个模型，点击下方模型即可选用`);
            }
            else {
                const result = await platformApi.testConnection(body);
                if (!result.ok) {
                    setProbeError(formatErrorText(result.error, undefined, "连接测试失败，请检查模型 ID 和服务配置"));
                    return;
                }
                setProbeResult(`连接正常 · ${result.latency_ms ?? 0} ms`);
            }
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403)
                onForbidden();
            setProbeError(formatApiError(err, operation === "models" ? "获取模型列表失败，请重试" : "连接测试失败，请重试"));
        }
        finally {
            setProbeBusy(false);
        }
    }
    const filtered = computed(() => ((configuration.value?.model_connections ?? []).filter((c: PlatformConnection) => `${c.name} ${c.model} ${providerFor(c).name}`.toLowerCase().includes(search.value.trim().toLowerCase()))));
    const editingExisting = computed(() => (draft.value && configuration.value?.model_connections.some((c: PlatformConnection) => c.id === draft.value!.id)));
    return () => {
        return (renderNode("div", { "class": styles.page }, [
            renderNode("header", { "class": styles.pageHead }, [
                renderNode("div", {}, [
                    renderNode("h1", {}, ["AI 模型"]), renderNode("p", {}, ["管理平台内置模型和自建服务，供创作与平台任务使用。"]), renderNode(Link, { "to": "/admin/model-routes" }, { default: () => ["调整模型分配"] })
                ]), renderNode("button", { "type": "button", "class": "btn btn-primary", "disabled": !configuration.value || loading.value, "onClick": () => edit() }, ["新增模型"])
            ]), !draft.value && !deleting.value && error.value && (renderNode("div", { "role": "alert", "class": "banner banner-error" }, [error.value])), notice.value && renderNode("div", { "role": "status" }, [notice.value]), renderNode("div", { "class": styles.toolbar }, [
                renderNode("input", { "class": "input", "aria-label": "搜索模型", "placeholder": "搜索名称、模型 ID 或服务商", "value": search.value, "onInput": (e: Event) => setSearch((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, []), renderNode("span", {}, [
                    filtered.value.length, " 个模型"
                ]), renderNode("button", { "class": "btn btn-quiet", "disabled": loading.value, "onClick": () => void load() }, ["重新加载配置"])
            ]), loading.value ? (renderNode("p", { "role": "status" }, ["正在加载模型…"])) : !configuration.value ? (renderNode("p", { "class": "empty" }, ["模型加载失败，请重新加载配置。"])) : filtered.value.length === 0 ? (renderNode("div", { "class": styles.empty }, [
                renderNode("h2", {}, [search.value ? "没有匹配的模型" : "还没有添加模型"]), renderNode("p", {}, [search.value ? "试试其他名称或模型 ID。" : "点击“新增模型”，填写你自己的模型服务地址和密钥。"])
            ])) : (renderNode("div", { "class": styles.grid }, [filtered.value.map((connection: PlatformConnection) => (renderNode("article", { "key": connection.id, "class": styles.card }, [
                    renderNode("div", { "class": styles.cardHead }, [
                        renderNode("span", { "class": styles.provider }, [providerFor(connection).name]), renderNode('div', { class: styles.audience }, [renderNode('span', { class: `${styles.audienceBadge} ${connection.minimum_tier === 'vip' ? styles.premiumBadge : ''}` }, connection.minimum_tier === 'vip' ? '仅 VIP' : '普通 + VIP'), renderNode("span", {}, [connection.enabled ? "已启用" : "已停用"])])
                    ]), renderNode("h2", {}, [connection.name]), connection.model !== connection.name && renderNode("code", {}, [connection.model]), renderNode("p", { "class": styles.address }, [connection.base_url]), renderNode("div", { "class": styles.tags }, [
                        connection.origin === "builtin" && renderNode("span", {}, ["平台内置"]), renderNode("span", {}, [connection.protocol === "anthropic" ? "Anthropic 原生" : "OpenAI 兼容"]), renderNode("span", {}, [connection.user_visible ? "用户可选" : "仅后台使用"]), renderNode("span", {}, [connection.minimum_tier === 'vip' ? 'VIP 专用' : '所有会员可用']), renderNode("span", {}, [connection.has_api_key ? "密钥已保存" : "待配置密钥"])
                    ]), renderNode("footer", {}, [
                        renderNode("button", { "type": "button", "class": "btn btn-secondary", "aria-label": `编辑 ${connection.name}`, "onClick": () => edit(connection) }, ["编辑"]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `删除 ${connection.name}`, "onClick": () => {
                                setError("");
                                setReplacement("");
                                setDeleting(connection);
                            } }, ["删除"])
                    ])
                ])))])), draft.value && (renderNode(AdminDialog, { "title": editingExisting.value ? "编辑模型" : "新增模型", "busy": busy.value || probeBusy.value, "onClose": () => {
                    setDraft(null);
                    setError("");
                }, children: [renderNode("form", { "onSubmit": (e: SubmitEvent) => {
                            e.preventDefault();
                            void save();
                        } }, [
                        !configuration.value?.model_routes.writer && (renderNode("p", { "class": styles.hint }, ["第一个模型将作为默认写作模型，之后可在“模型分配”中调整。"])), renderNode("fieldset", { "disabled": busy.value || probeBusy.value, "class": styles.fields }, [
                            renderNode("label", {}, [
                                "显示名称", renderNode("input", { "class": "input", "autoFocus": true, "required": true, "value": draft.value!.name, "onInput": (e: Event) => patch({ name: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": "例如：我的 DeepSeek" }, [])
                            ]), renderNode("label", {}, [
                                "模型服务商", renderNode("select", { "class": "input", "value": provider.value, "onChange": (e: Event) => {
                                        const next = PROVIDERS.find((p: {
                                            readonly id: "openai";
                                            readonly name: "OpenAI";
                                            readonly protocol: "openai";
                                            readonly url: "https://api.openai.com/v1";
                                        } | {
                                            readonly id: "anthropic";
                                            readonly name: "Anthropic";
                                            readonly protocol: "anthropic";
                                            readonly url: "https://api.anthropic.com/v1";
                                        } | {
                                            readonly id: "deepseek";
                                            readonly name: "DeepSeek";
                                            readonly protocol: "openai";
                                            readonly url: "https://api.deepseek.com/v1";
                                        } | {
                                            readonly id: "dashscope";
                                            readonly name: "通义千问（DashScope）";
                                            readonly protocol: "openai";
                                            readonly url: "https://dashscope.aliyuncs.com/compatible-mode/v1";
                                        } | {
                                            readonly id: "zhipu";
                                            readonly name: "智谱 GLM";
                                            readonly protocol: "openai";
                                            readonly url: "https://open.bigmodel.cn/api/paas/v4";
                                        } | {
                                            readonly id: "custom";
                                            readonly name: "自定义 / 中转服务";
                                            readonly protocol: "openai";
                                            readonly url: "";
                                        }) => p.id === (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value)!;
                                        const previous = PROVIDERS.find((p: {
                                            readonly id: "openai";
                                            readonly name: "OpenAI";
                                            readonly protocol: "openai";
                                            readonly url: "https://api.openai.com/v1";
                                        } | {
                                            readonly id: "anthropic";
                                            readonly name: "Anthropic";
                                            readonly protocol: "anthropic";
                                            readonly url: "https://api.anthropic.com/v1";
                                        } | {
                                            readonly id: "deepseek";
                                            readonly name: "DeepSeek";
                                            readonly protocol: "openai";
                                            readonly url: "https://api.deepseek.com/v1";
                                        } | {
                                            readonly id: "dashscope";
                                            readonly name: "通义千问（DashScope）";
                                            readonly protocol: "openai";
                                            readonly url: "https://dashscope.aliyuncs.com/compatible-mode/v1";
                                        } | {
                                            readonly id: "zhipu";
                                            readonly name: "智谱 GLM";
                                            readonly protocol: "openai";
                                            readonly url: "https://open.bigmodel.cn/api/paas/v4";
                                        } | {
                                            readonly id: "custom";
                                            readonly name: "自定义 / 中转服务";
                                            readonly protocol: "openai";
                                            readonly url: "";
                                        }) => p.id === provider.value);
                                        setProvider(next.id);
                                        patch({
                                            protocol: next.protocol,
                                            ...(!draft.value!.base_url || draft.value!.base_url === previous?.url ? { base_url: next.url } : {}),
                                        });
                                    } }, [PROVIDERS.map((p: {
                                        readonly id: "openai";
                                        readonly name: "OpenAI";
                                        readonly protocol: "openai";
                                        readonly url: "https://api.openai.com/v1";
                                    } | {
                                        readonly id: "anthropic";
                                        readonly name: "Anthropic";
                                        readonly protocol: "anthropic";
                                        readonly url: "https://api.anthropic.com/v1";
                                    } | {
                                        readonly id: "deepseek";
                                        readonly name: "DeepSeek";
                                        readonly protocol: "openai";
                                        readonly url: "https://api.deepseek.com/v1";
                                    } | {
                                        readonly id: "dashscope";
                                        readonly name: "通义千问（DashScope）";
                                        readonly protocol: "openai";
                                        readonly url: "https://dashscope.aliyuncs.com/compatible-mode/v1";
                                    } | {
                                        readonly id: "zhipu";
                                        readonly name: "智谱 GLM";
                                        readonly protocol: "openai";
                                        readonly url: "https://open.bigmodel.cn/api/paas/v4";
                                    } | {
                                        readonly id: "custom";
                                        readonly name: "自定义 / 中转服务";
                                        readonly protocol: "openai";
                                        readonly url: "";
                                    }) => (renderNode("option", { "key": p.id, "value": p.id }, [p.name])))])
                            ]), renderNode("label", {}, [
                                "请求地址", renderNode("input", { "class": "input", "required": true, "type": "url", "value": draft.value!.base_url, "onInput": (e: Event) => patch({ base_url: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": "https://api.example.com/v1" }, [])
                            ]), renderNode("label", {}, [
                                "接口协议", renderNode("select", { "class": "input", "value": draft.value!.protocol, "onChange": (e: Event) => patch({ protocol: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value as "openai" | "anthropic" }) }, [
                                    renderNode("option", { "value": "openai" }, ["OpenAI 兼容"]), renderNode("option", { "value": "anthropic" }, ["Anthropic 原生"])
                                ])
                            ]), renderNode("label", {}, [
                                "模型 ID", renderNode("input", { "class": "input", "required": true, "value": draft.value!.model, "onInput": (e: Event) => patch({ model: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": "填写服务商提供的模型 ID" }, [])
                            ]), renderNode('label', {}, [
                                '最低会员等级', renderNode('select', { class: 'input', value: draft.value!.minimum_tier ?? 'normal',
                                    onChange: (e: Event) => patch({ minimum_tier: (e.target as HTMLSelectElement).value as 'normal' | 'vip' }) }, [
                                    renderNode('option', { value: 'normal' }, '普通用户及 VIP'),
                                    renderNode('option', { value: 'vip' }, '仅 VIP'),
                                ])
                            ]), renderNode("label", {}, [
                                "API Key", renderNode("input", { "class": "input", "type": showKey.value ? "text" : "password", "autoComplete": "new-password", "required": !draft.value!.has_api_key, "value": draft.value!.api_key, "onInput": (e: Event) => patch({ api_key: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": draft.value!.has_api_key ? "已保存，留空保留原密钥" : "填写 API Key" }, [])
                            ]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => setShowKey(!showKey.value) }, [showKey.value ? "隐藏输入的密钥" : "显示输入的密钥"]), renderNode("div", { "class": styles.options }, [
                                renderNode("label", {}, [
                                    renderNode("input", { "type": "checkbox", "checked": draft.value!.enabled, "onChange": (e: Event) => patch({ enabled: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked }) }, []), "启用模型"
                                ]), renderNode("label", {}, [
                                    renderNode("input", { "type": "checkbox", "checked": draft.value!.user_visible, "onChange": (e: Event) => patch({ user_visible: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked }) }, []), "向用户发布"
                                ])
                            ]), renderNode("div", { "class": styles.probe }, [
                                renderNode("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => void probe("models") }, ["获取模型列表"]), renderNode("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => void probe("test") }, ["测试连接"])
                            ])
                        ]), probeBusy.value && renderNode("p", { "role": "status" }, ["正在连接模型服务…"]), probeResult.value && renderNode("p", { "role": "status" }, [probeResult.value]), probeError.value && renderNode("p", { "role": "alert" }, [probeError.value]), models.value.length > 0 && (renderNode("div", { "class": styles.suggestions, "aria-label": "上游可用模型" }, [models.value.map((model: string) => (renderNode("button", { "class": "btn btn-quiet", "type": "button", "key": model, "disabled": busy.value || probeBusy.value, "onClick": () => {
                                    setDraft({ ...draft.value!, model });
                                    setProbeResult("");
                                    setProbeError("");
                                } }, [model])))])), error.value && (renderNode("p", { "role": "alert", "class": "banner banner-error" }, [error.value])), renderNode("footer", { "class": styles.actions }, [
                            renderNode("button", { "type": "button", "class": "btn btn-secondary", "disabled": busy.value || probeBusy.value, "onClick": () => {
                                    setDraft(null);
                                    setError("");
                                } }, ["取消"]), renderNode("button", { "class": "btn btn-primary", "type": "submit", "disabled": busy.value || probeBusy.value }, [busy.value ? "保存中…" : "保存模型"])
                        ])
                    ])] })), deleting.value && (renderNode(AdminDialog, { "title": "删除模型", "busy": busy.value, "onClose": () => {
                    setDeleting(null);
                    setError("");
                }, children: [renderNode("p", {}, [
                        "确认删除“", deleting.value!.name, "”？对应角色的模型分配也会被清除，请及时重新分配。"
                    ]), configuration.value?.model_routes.writer === `custom:${deleting.value!.id}` && configuration.value.model_connections.length > 1 && (renderNode("label", { "class": styles.replacement }, [
                        "替代写作模型", renderNode("select", { "class": "input", "value": replacement.value, "disabled": busy.value, "onChange": (e: Event) => setReplacement((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [
                            renderNode("option", { "value": "" }, ["请选择替代写作模型"]), configuration.value.model_connections.filter((c: PlatformConnection) => c.id !== deleting.value!.id && c.enabled).map((c: PlatformConnection) => (renderNode("option", { "key": c.id, "value": `custom:${c.id}` }, [c.name])))
                        ])
                    ])), error.value && renderNode("p", { "role": "alert" }, [error.value]), renderNode("footer", { "class": styles.actions }, [
                        renderNode("button", { "type": "button", "class": "btn btn-secondary", "disabled": busy.value, "onClick": () => {
                                setDeleting(null);
                                setError("");
                            } }, ["取消"]), renderNode("button", { "type": "button", "class": "btn btn-primary", "disabled": busy.value, "onClick": () => void remove() }, [busy.value ? "删除中…" : "确认删除"])
                    ])] }))
        ]));
    };
}, {
    inheritAttrs: false,
    props: {}
});
export default ModelManagement;
