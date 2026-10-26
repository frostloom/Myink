import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import type { PropType } from 'vue';
import { Fragment, defineComponent, h as renderNode, shallowRef, watch } from 'vue';
import { RouterLink as Link } from 'vue-router';
import { api } from "../../../../src/lib/api";
import { formatApiError } from "../../../../src/lib/apiError";
import { composeFields, type GenreCatalogItem, type GenreFields } from "../../../../src/lib/genrePacks";
import { platformApi, type PlatformConfigurationData, type PlatformConnectionInput, type PlatformReadiness } from "../../../../src/lib/platformApi";
import styles from "../../../../src/pages/SettingsPage.module.css";
import type { ConnectionTestResult, ModelConnection, ModelProbeRequest, UserDefaults, } from "../../../../src/types";
import ConnectionNotices, { type ConnectionNotice } from "../../components/ConnectionNotices.vue";
import GenrePackFields from "../../components/GenrePackFields.vue";
import { useAdminContext } from './context';
import ModelManagement from "./ModelManagement";
import PlatformResources from "./PlatformResources";
const MODEL_ROLES = [
    { key: 'planner', label: '规划' },
    { key: 'writer', label: '写作' },
    { key: 'validator_l2', label: '语义校验' },
    { key: 'extract', label: '抽取' },
    { key: 'audit', label: '审核' },
    { key: 'summarize', label: '摘要' },
];
const READINESS_REASONS: Record<string, string> = {
    model_unconfigured: '未配置可用模型',
    defaults_invalid: '平台默认偏好无效，请检查保存的配置',
    protocol_invalid: '接口协议无效',
    model_invalid: '模型 id 无效',
    address_invalid: '请求地址无效或不允许使用',
    credential_unavailable: '凭据不可用，请重新保存密钥',
};
const DEFAULT_USER_PREFERENCES: UserDefaults = {
    thinking_enabled: false,
    task_budget: { max_requests: 100, max_cost_yuan: 5, max_runtime_seconds: 1800 },
    rankings: { enabled: true, timeout: 10, limit: 10 },
};
type ConnectionField = 'name' | 'base_url' | 'model' | 'api_key';
type FieldProblem = {
    key: string;
    text: string;
} | null;
type ModelConnectionDraft = ModelConnection & {
    origin?: 'builtin' | 'custom';
    enabled: boolean;
    user_visible: boolean;
    api_key: string;
};
type ProbeState = {
    loading?: 'models' | 'test';
    models?: string[];
    listError?: string;
    test?: ConnectionTestResult;
};
function normalizeGenreOverrides(overrides: PlatformConfigurationData['genre_packs'], catalog: GenreCatalogItem[]): Record<string, GenreFields> {
    return Object.fromEntries(Object.entries(overrides).map(([id, override]) => {
        const defaults = composeFields(catalog.find((item: GenreCatalogItem) => item.id === id));
        const fields = Object.fromEntries((Object.keys(defaults) as Array<keyof GenreFields>)
            .map((key: keyof GenreFields) => [key, override[key] ?? defaults[key]])) as unknown as GenreFields;
        return [id, fields];
    }));
}
type ConfigurationSection = 'models' | 'routes' | 'defaults' | 'prompts' | 'genres' | 'all';
export default function PlatformConfiguration({ section = 'all' }: {
    section?: ConfigurationSection;
}) {
    if (section === 'models')
        return renderNode(ModelManagement, {});
    if (section === 'prompts' || section === 'genres')
        return renderNode(PlatformResources, { "key": section, "kind": section });
    return renderNode(ConfigurationSettings, { "key": section, "section": section });
}
const ConfigurationSettings = defineComponent((props: {
    section: ConfigurationSection;
}) => {
    const { onForbidden } = useAdminContext();
    const readiness = shallowRef<PlatformReadiness | null>(null);
    const setReadiness = (next: typeof readiness.value | ((old: typeof readiness.value) => typeof readiness.value)) => { readiness.value = typeof next === "function" ? next(readiness.value) : next; };
    const readinessLoading = shallowRef(false);
    const setReadinessLoading = (next: typeof readinessLoading.value | ((old: typeof readinessLoading.value) => typeof readinessLoading.value)) => { readinessLoading.value = typeof next === "function" ? next(readinessLoading.value) : next; };
    const readinessUnavailable = shallowRef(false);
    const setReadinessUnavailable = (next: typeof readinessUnavailable.value | ((old: typeof readinessUnavailable.value) => typeof readinessUnavailable.value)) => { readinessUnavailable.value = typeof next === "function" ? next(readinessUnavailable.value) : next; };
    const version = shallowRef(0);
    const setVersion = (next: typeof version.value | ((old: typeof version.value) => typeof version.value)) => { version.value = typeof next === "function" ? next(version.value) : next; };
    const userDefaults = shallowRef<UserDefaults>(DEFAULT_USER_PREFERENCES);
    const setUserDefaults = (next: typeof userDefaults.value | ((old: typeof userDefaults.value) => typeof userDefaults.value)) => { userDefaults.value = typeof next === "function" ? next(userDefaults.value) : next; };
    const loading = shallowRef(true);
    const setLoading = (next: typeof loading.value | ((old: typeof loading.value) => typeof loading.value)) => { loading.value = typeof next === "function" ? next(loading.value) : next; };
    const loaded = shallowRef(false);
    const setLoaded = (next: typeof loaded.value | ((old: typeof loaded.value) => typeof loaded.value)) => { loaded.value = typeof next === "function" ? next(loaded.value) : next; };
    const prompts = shallowRef<Record<string, string>>({});
    const setPrompts = (next: typeof prompts.value | ((old: typeof prompts.value) => typeof prompts.value)) => { prompts.value = typeof next === "function" ? next(prompts.value) : next; };
    const genrePacks = shallowRef<Record<string, GenreFields>>({});
    const setGenrePacks = (next: typeof genrePacks.value | ((old: typeof genrePacks.value) => typeof genrePacks.value)) => { genrePacks.value = typeof next === "function" ? next(genrePacks.value) : next; };
    const catalog = shallowRef<GenreCatalogItem[]>([]);
    const setCatalog = (next: typeof catalog.value | ((old: typeof catalog.value) => typeof catalog.value)) => { catalog.value = typeof next === "function" ? next(catalog.value) : next; };
    const genreId = shallowRef("");
    const setGenreId = (next: typeof genreId.value | ((old: typeof genreId.value) => typeof genreId.value)) => { genreId.value = typeof next === "function" ? next(genreId.value) : next; };
    const routeSel = shallowRef<Record<string, string>>({});
    const setRouteSel = (next: typeof routeSel.value | ((old: typeof routeSel.value) => typeof routeSel.value)) => { routeSel.value = typeof next === "function" ? next(routeSel.value) : next; };
    const connectionDrafts = shallowRef<ModelConnectionDraft[]>([]);
    const setConnectionDrafts = (next: typeof connectionDrafts.value | ((old: typeof connectionDrafts.value) => typeof connectionDrafts.value)) => { connectionDrafts.value = typeof next === "function" ? next(connectionDrafts.value) : next; };
    const probes = shallowRef<Record<string, ProbeState>>({});
    const setProbes = (next: typeof probes.value | ((old: typeof probes.value) => typeof probes.value)) => { probes.value = typeof next === "function" ? next(probes.value) : next; };
    const notices = shallowRef<ConnectionNotice[]>([]);
    const setNotices = (next: typeof notices.value | ((old: typeof notices.value) => typeof notices.value)) => { notices.value = typeof next === "function" ? next(notices.value) : next; };
    const fieldProblem = shallowRef<FieldProblem>(null);
    const setFieldProblem = (next: typeof fieldProblem.value | ((old: typeof fieldProblem.value) => typeof fieldProblem.value)) => { fieldProblem.value = typeof next === "function" ? next(fieldProblem.value) : next; };
    const fieldRefs = shallowRef(new Map<string, HTMLInputElement>());
    const busy = shallowRef<string | null>(null);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const banner = shallowRef<string | null>(null);
    let savedForm = '';
    const formSnapshot = () => JSON.stringify([userDefaults.value, prompts.value, genrePacks.value, routeSel.value, connectionDrafts.value]);
    useMemoryFormGuard(() => loaded.value && formSnapshot() !== savedForm);
    const setBanner = (next: typeof banner.value | ((old: typeof banner.value) => typeof banner.value)) => { banner.value = typeof next === "function" ? next(banner.value) : next; };
    function notify(id: string, tone: "error" | "ok", text: string, returnFocus: HTMLElement | null) {
        setNotices((previous: ConnectionNotice[]) => [
            { id, tone, text, returnFocus },
            ...previous.filter((item: ConnectionNotice) => item.id !== id),
        ]);
    }
    function rejectField(id: string, field: ConnectionField, text: string) {
        const key = `${id}:${field}`;
        setFieldProblem({ key, text });
        setBusy(null);
        fieldRefs.value.get(key)?.focus();
        fieldRefs.value.get(key)?.scrollIntoView({ block: "center", behavior: "auto" });
        return false;
    }
    function fieldAttributes(id: string, field: ConnectionField) {
        const key = `${id}:${field}`;
        return {
            ref: (element: Element | import("vue").ComponentPublicInstance | null) => {
                if (element instanceof HTMLInputElement)
                    fieldRefs.value.set(key, element);
                else
                    fieldRefs.value.delete(key);
            },
            "aria-invalid": fieldProblem.value?.key === key || undefined,
            "aria-describedby": fieldProblem.value?.key === key ? `error-${key}` : undefined,
        };
    }
    function fieldMessage(id: string, field: ConnectionField) {
        const key = `${id}:${field}`;
        return fieldProblem.value?.key === key ? renderNode("span", { "id": `error-${key}`, "class": styles.fieldError }, [fieldProblem.value.text]) : null;
    }
    const refreshReadiness = async () => {
        setReadinessLoading(true);
        try {
            const result = await platformApi.getReadiness();
            setReadiness(result);
            setReadinessUnavailable(false);
        }
        catch (err) {
            setReadiness(null);
            setReadinessUnavailable(true);
            if ((err as {
                status?: number;
            }).status === 403)
                onForbidden();
        }
        finally {
            setReadinessLoading(false);
        }
    };
    const load = async () => {
        setBanner(null);
        setLoading(true);
        setLoaded(false);
        try {
            const [env, items] = await Promise.all([platformApi.getConfiguration(), api.listGenrePacks()]);
            setVersion(env.version);
            setUserDefaults(env.user_defaults ?? DEFAULT_USER_PREFERENCES);
            setPrompts(env.prompts);
            setGenrePacks(normalizeGenreOverrides(env.genre_packs, items));
            setCatalog(items);
            setGenreId((id: string) => id || items[0]?.id || "");
            setRouteSel(Object.fromEntries(MODEL_ROLES.map((r: {
                key: string;
                label: string;
            }) => {
                const value = env.model_routes[r.key] ?? "";
                return [r.key, value.startsWith("custom:") ? value : ""];
            })));
            setConnectionDrafts((env.model_connections ?? []).map((connection: import("../../../../src/lib/platformApi").PlatformConnection) => ({ ...connection, api_key: "" })));
            savedForm = formSnapshot();
            setLoaded(true);
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403) {
                onForbidden();
                return;
            }
            setBanner(formatApiError(err, "平台配置加载失败"));
        }
        finally {
            setLoading(false);
        }
    };
    watch([() => load, () => refreshReadiness], (_next, _old, onCleanup) => {
        const cleanup = (() => {
            void load();
            void refreshReadiness();
        })();
        if (typeof cleanup === "function")
            onCleanup(cleanup);
    }, { immediate: true, flush: "post" });
    async function saveRoutes() {
        const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        const routes = Object.fromEntries(MODEL_ROLES.map((r: {
            key: string;
            label: string;
        }) => [r.key, routeSel.value[r.key]]).filter(([, v]) => v)) as Record<string, string>;
        setBusy("routes");
        setBanner(null);
        setFieldProblem(null);
        const connections: PlatformConnectionInput[] = [];
        for (const draft of connectionDrafts.value) {
            const name = draft.name.trim();
            const baseUrl = draft.base_url.trim().replace(/\/$/, "");
            const model = draft.model.trim();
            if (!name)
                return rejectField(draft.id, "name", "请填写连接名称");
            if (!baseUrl)
                return rejectField(draft.id, "base_url", "请填写请求地址");
            if (!model)
                return rejectField(draft.id, "model", "请填写模型 id");
            try {
                const parsed = new URL(baseUrl);
                if (!["http:", "https:"].includes(parsed.protocol))
                    throw new Error("scheme");
            }
            catch {
                return rejectField(draft.id, "base_url", "请输入有效的 http/https 请求地址");
            }
            if (!draft.has_api_key && !draft.api_key.trim()) {
                return rejectField(draft.id, "api_key", "请填写 API Key");
            }
            connections.push({
                id: draft.id,
                name,
                protocol: draft.protocol,
                enabled: draft.enabled,
                user_visible: draft.user_visible,
                input_price: draft.input_price,
                output_price: draft.output_price,
                base_url: baseUrl,
                model,
                ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
            });
        }
        try {
            const saved = await platformApi.updateConfiguration({
                version: version.value,
                model_routes: routes,
                model_connections: connections,
                prompts: prompts.value,
                genre_packs: genrePacks.value,
                user_defaults: userDefaults.value,
            });
            setVersion(saved.version);
            setUserDefaults(saved.user_defaults ?? userDefaults.value);
            setConnectionDrafts(saved.model_connections.map((connection: import("../../../../src/lib/platformApi").PlatformConnection) => ({ ...connection, api_key: "" })));
            setPrompts(saved.prompts);
            setGenrePacks(normalizeGenreOverrides(saved.genre_packs, catalog.value));
            savedForm = formSnapshot();
            notify("save", "ok", "平台配置已保存", returnFocus);
            void refreshReadiness();
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403) {
                onForbidden();
                return;
            }
            const message = (err as {
                status?: number;
            }).status === 409 ? "配置已被其他管理员更新。请重新加载后核对并保存；当前草稿仍保留。" : formatApiError(err);
            notify("save", "error", message, returnFocus);
        }
        finally {
            setBusy(null);
        }
    }
    function addConnection() {
        setConnectionDrafts((items: ModelConnectionDraft[]) => [...items, {
                id: crypto.randomUUID(),
                name: "",
                protocol: "openai",
                base_url: "",
                model: "",
                api_key: "",
                has_api_key: false,
                enabled: true,
                user_visible: true,
            }]);
    }
    function updateConnection(id: string, patch: Partial<ModelConnectionDraft>) {
        setFieldProblem((problem: FieldProblem) => problem && Object.keys(patch).some((field: string) => problem.key === `${id}:${field}`) ? null : problem);
        setConnectionDrafts((items: ModelConnectionDraft[]) => items.map((item: ModelConnectionDraft) => item.id === id ? { ...item, ...patch } : item));
    }
    function removeConnection(id: string) {
        setConnectionDrafts((items: ModelConnectionDraft[]) => items.filter((item: ModelConnectionDraft) => item.id !== id));
        setRouteSel((routes: Record<string, string>) => Object.fromEntries(Object.entries(routes).map(([role, model]) => [role, model === `custom:${id}` ? "" : model])));
        setProbes((prev: Record<string, ProbeState>) => {
            const next = { ...prev };
            delete next[id];
            return next;
        });
    }
    function probeBody(draft: ModelConnectionDraft): ModelProbeRequest {
        const apiKey = draft.api_key.trim();
        return {
            protocol: draft.protocol,
            base_url: draft.base_url.trim().replace(/\/$/, ""),
            ...(draft.model.trim() ? { model: draft.model.trim() } : {}),
            ...(apiKey ? { api_key: apiKey } : draft.has_api_key ? { connection_id: draft.id } : {}),
        };
    }
    function probeReady(draft: ModelConnectionDraft, needModel: boolean): boolean {
        setFieldProblem(null);
        if (!draft.base_url.trim()) {
            return rejectField(draft.id, "base_url", "请填写请求地址");
        }
        if (needModel && !draft.model.trim()) {
            return rejectField(draft.id, "model", "请填写模型 id");
        }
        if (!draft.has_api_key && !draft.api_key.trim()) {
            return rejectField(draft.id, "api_key", "请填写 API Key");
        }
        return true;
    }
    async function fetchModels(draft: ModelConnectionDraft) {
        const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        if (!probeReady(draft, false))
            return;
        setFieldProblem(null);
        setProbes((p: Record<string, ProbeState>) => ({ ...p, [draft.id]: { ...p[draft.id], loading: "models" } }));
        try {
            const res = await platformApi.listModels(probeBody(draft));
            notify(`probe:${draft.id}`, res.ok ? "ok" : "error", `${draft.name.trim() || "模型连接"}：${res.ok ? `已获取 ${res.models.length} 个模型` : (res.error ?? "获取模型列表失败")}`, returnFocus);
            setProbes((p: Record<string, ProbeState>) => ({ ...p, [draft.id]: {
                    loading: undefined,
                    models: res.models,
                    listError: res.ok ? undefined : (res.error ?? "拉取失败"),
                } }));
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403) {
                onForbidden();
                return;
            }
            notify(`probe:${draft.id}`, "error", `${draft.name.trim() || "模型连接"}：${formatApiError(err, "获取模型列表失败")}`, returnFocus);
            setProbes((p: Record<string, ProbeState>) => ({ ...p, [draft.id]: {
                    loading: undefined,
                    listError: formatApiError(err, "拉取失败"),
                } }));
        }
    }
    async function runTest(draft: ModelConnectionDraft) {
        const returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        if (!probeReady(draft, true))
            return;
        setFieldProblem(null);
        setProbes((p: Record<string, ProbeState>) => ({ ...p, [draft.id]: { ...p[draft.id], loading: "test" } }));
        try {
            const res = await platformApi.testConnection(probeBody(draft));
            notify(`probe:${draft.id}`, res.ok ? "ok" : "error", `${draft.name.trim() || "模型连接"}：${res.ok ? `连接正常 · ${res.latency_ms} ms` : (res.error ?? "连接测试失败")}`, returnFocus);
            setProbes((p: Record<string, ProbeState>) => ({ ...p, [draft.id]: { ...p[draft.id], loading: undefined, test: res } }));
        }
        catch (err) {
            if ((err as {
                status?: number;
            }).status === 403) {
                onForbidden();
                return;
            }
            notify(`probe:${draft.id}`, "error", `${draft.name.trim() || "模型连接"}：${formatApiError(err, "连接测试失败")}`, returnFocus);
            setProbes((p: Record<string, ProbeState>) => ({ ...p, [draft.id]: { loading: undefined, test: {
                        ok: false,
                        latency_ms: 0,
                        reply: null,
                        error: formatApiError(err, "测试失败"),
                    } } }));
        }
    }
    return () => {
        return (renderNode("div", {}, [
            renderNode(ConnectionNotices, { "items": notices.value, "onDismiss": (id: string) => setNotices((items: ConnectionNotice[]) => items.filter((item: ConnectionNotice) => item.id !== id)) }), renderNode("div", {}, [renderNode("div", { "class": styles.inner }, [
                    renderNode("header", { "class": styles.header }, [renderNode("div", {}, [
                            renderNode("h1", {}, [{ all: "模型与平台配置", models: "AI 模型", routes: "模型分配", defaults: "用户默认设置", prompts: "提示词", genres: "题材包" }[props.section]]), renderNode("div", { "class": styles.crumb }, [renderNode(Link, { "to": "/admin" }, { default: () => ["返回管理概览"] })])
                        ])]), banner.value && renderNode("div", { "class": "banner banner-error", "role": "alert" }, [banner.value]), renderNode("div", { "class": styles.saveRow }, [
                        renderNode("button", { "class": "btn btn-secondary", "disabled": loading.value || busy.value !== null, "onClick": () => void load() }, ["重新加载配置"]), renderNode("span", {}, [
                            "版本 ", version.value
                        ]), renderNode("button", { "class": "btn btn-primary", "disabled": loading.value || !loaded.value || busy.value !== null, "onClick": () => void saveRoutes() }, [busy.value === "routes" ? "保存中…" : "保存平台配置"])
                    ]), loading.value && renderNode("p", { "role": "status" }, ["正在加载平台配置…"]), (props.section === "all" || props.section === "routes") && renderNode("section", { "class": `panel ${styles.section}`, "aria-label": "平台就绪状态" }, [
                        renderNode("h2", { "class": styles.sectionTitle }, ["平台就绪状态"]), renderNode("p", { "class": styles.hint }, ["检查已保存配置，不调用模型服务。此状态不包含未保存的草稿，也不代表网络或凭据已通过服务商验证。"]), renderNode("button", { "type": "button", "class": "btn btn-secondary", "disabled": readinessLoading.value, "onClick": () => void refreshReadiness() }, ["刷新就绪状态"]), readinessLoading.value && renderNode("p", { "role": "status" }, ["正在检查就绪状态…"]), readinessUnavailable.value && renderNode("p", {}, ["暂时无法读取就绪状态"]), readiness.value && renderNode(Fragment, {}, [
                            renderNode("p", {}, [readiness.value.ready ? "平台创作服务已就绪" : "平台创作服务尚未就绪"]), renderNode("ul", {}, [readiness.value.checks.map((check: {
                                    role: string;
                                    ready: boolean;
                                    reason: string | null;
                                }) => renderNode("li", { "key": check.role }, [
                                    MODEL_ROLES.find((role: {
                                        key: string;
                                        label: string;
                                    }) => role.key === check.role)?.label ?? check.role, "：", check.ready ? "就绪" : renderNode("span", {}, [READINESS_REASONS[check.reason ?? ""] ?? "配置不可用"])
                                ]))])
                        ])
                    ]), renderNode("fieldset", { "disabled": loading.value || !loaded.value || busy.value !== null, "style": { border: 0, padding: 0, margin: 0, minWidth: 0 } }, [
                        (props.section === "all" || props.section === "routes") && renderNode("section", { "class": `panel ${styles.section}` }, [
                            props.section === "all" && renderNode(Fragment, {}, [
                                renderNode("div", { "class": styles.connectionTitleRow }, [
                                    renderNode("div", {}, [renderNode("h2", { "class": styles.sectionTitle }, ["模型连接与路由"])]), renderNode("button", { "type": "button", "class": "btn btn-secondary", "disabled": busy.value !== null, "onClick": addConnection }, ["添加网络模型"])
                                ]), connectionDrafts.value.length === 0 ? (renderNode("div", { "class": "empty" }, ["尚未添加网络模型。添加后即可在下方为各 Agent 指定主模型。"])) : (renderNode("div", { "class": styles.connectionList }, [connectionDrafts.value.map((connection: ModelConnectionDraft) => (renderNode("article", { "key": connection.id, "class": styles.connectionCard }, [
                                        renderNode("div", { "class": styles.connectionHead }, [
                                            renderNode("div", { "class": styles.compactField }, [
                                                renderNode("input", { ...fieldAttributes(connection.id, "name"), "class": "input", "aria-label": "连接名称", "value": connection.name, "onInput": (e: Event) => updateConnection(connection.id, { name: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": "例如：DeepSeek / 我的 Claude" }, []), fieldMessage(connection.id, "name")
                                            ]), renderNode("select", { "class": "input", "aria-label": "接口协议", "value": connection.protocol, "onChange": (e: Event) => updateConnection(connection.id, { protocol: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value as "openai" | "anthropic" }) }, [
                                                renderNode("option", { "value": "openai" }, ["OpenAI 兼容"]), renderNode("option", { "value": "anthropic" }, ["Anthropic 原生"])
                                            ]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null, "onClick": () => removeConnection(connection.id) }, ["移除"])
                                        ]), renderNode("div", { "class": styles.probeRow }, [
                                            renderNode("label", {}, [
                                                renderNode("input", { "type": "checkbox", "checked": connection.enabled, "onChange": (e: Event) => updateConnection(connection.id, { enabled: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked }) }, []), "启用连接"
                                            ]), renderNode("label", {}, [
                                                renderNode("input", { "type": "checkbox", "checked": connection.user_visible, "onChange": (e: Event) => updateConnection(connection.id, { user_visible: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked }) }, []), "向用户发布"
                                            ])
                                        ]), renderNode("div", { "class": styles.connectionGrid }, [
                                            renderNode("label", { "class": styles.compactField }, [
                                                renderNode("span", {}, ["请求地址"]), renderNode("input", { ...fieldAttributes(connection.id, "base_url"), "class": "input", "value": connection.base_url, "onInput": (e: Event) => updateConnection(connection.id, { base_url: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": connection.protocol === "anthropic" ? "https://api.anthropic.com" : "https://api.openai.com/v1" }, []), fieldMessage(connection.id, "base_url")
                                            ]), renderNode("label", { "class": styles.compactField }, [
                                                renderNode("span", {}, ["模型 id"]), renderNode("input", { ...fieldAttributes(connection.id, "model"), "class": "input", "list": `models-${connection.id}`, "value": connection.model, "onInput": (e: Event) => updateConnection(connection.id, { model: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": connection.protocol === "anthropic" ? "claude-sonnet-4-5" : "gpt-4o" }, []), fieldMessage(connection.id, "model"), renderNode("datalist", { "id": `models-${connection.id}` }, [(probes.value[connection.id]?.models ?? []).map((m: string) => renderNode("option", { "key": m, "value": m }, []))])
                                            ]), renderNode("label", { "class": `${styles.compactField} ${styles.keyField}` }, [
                                                renderNode("span", {}, [
                                                    "API Key ", connection.has_api_key && renderNode("em", {}, ["已保存，留空即保留"])
                                                ]), renderNode("input", { ...fieldAttributes(connection.id, "api_key"), "class": "input", "type": "password", "autoComplete": "new-password", "value": connection.api_key, "onInput": (e: Event) => updateConnection(connection.id, { api_key: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value }), "placeholder": connection.has_api_key ? "••••••••（留空保留）" : "输入 API Key（保存后不再显示原文）" }, []), fieldMessage(connection.id, "api_key")
                                            ])
                                        ]), renderNode("div", { "class": styles.probeRow }, [
                                            renderNode("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null || probes.value[connection.id]?.loading !== undefined, "onClick": () => void fetchModels(connection) }, [probes.value[connection.id]?.loading === "models" ? "获取中…" : "获取模型列表"]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null || probes.value[connection.id]?.loading !== undefined, "onClick": () => void runTest(connection) }, [probes.value[connection.id]?.loading === "test" ? "测试中…" : "测试连接"]), renderNode("span", { "class": styles.probeStatus }, [
                                                probes.value[connection.id]?.test?.ok === true && `连接正常 · ${probes.value[connection.id]?.test?.latency_ms ?? 0} ms`, probes.value[connection.id]?.test?.ok === false && `连接失败：${probes.value[connection.id]?.test?.error ?? "未知错误"}`, probes.value[connection.id]?.listError && `模型列表不可用：${probes.value[connection.id]?.listError}`, probes.value[connection.id]?.models !== undefined && !probes.value[connection.id]?.listError && `已获取 ${probes.value[connection.id]?.models?.length ?? 0} 个模型`
                                            ])
                                        ])
                                    ])))]))
                            ]), renderNode("div", { "class": styles.routeDivider }, [
                                renderNode("h3", {}, ["任务模型分配"]), renderNode("p", { "class": styles.hint }, ["为每个创作环节选择模型；未单独设置的环节跟随默认写作模型。内置模型与自建模型均可分配。"])
                            ]), renderNode("div", { "class": styles.routeList }, [MODEL_ROLES.map((r: {
                                    key: string;
                                    label: string;
                                }) => (renderNode("label", { "key": r.key, "class": styles.routeRow }, [
                                    renderNode("span", { "class": styles.routeLabel }, [r.label]), renderNode("select", { "class": "input", "aria-label": r.label, "value": routeSel.value[r.key] ?? "", "onChange": (e: Event) => setRouteSel((s: Record<string, string>) => ({ ...s, [r.key]: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value })) }, [[
                                            { value: "", label: r.key === "writer" ? "请选择默认写作模型" : "跟随默认写作模型" },
                                            ...connectionDrafts.value.filter((connection: ModelConnectionDraft) => connection.enabled).map((connection: ModelConnectionDraft) => ({
                                                value: `custom:${connection.id}`,
                                                label: `${connection.origin === "builtin" ? "内置 · " : ""}${connection.name.trim() || "未命名连接"}${connection.name.trim() === connection.model.trim() ? "" : ` · ${connection.model.trim() || "未填写模型"}`}`,
                                            })),
                                        ].map((option: {
                                            value: string;
                                            label: string;
                                        }) => (renderNode("option", { "key": option.value, "value": option.value }, [option.label])))])
                                ])))])
                        ]), (props.section === "all" || props.section === "defaults") && renderNode("section", { "class": `panel ${styles.section}` }, [
                            renderNode("h2", { "class": styles.sectionTitle }, ["用户默认设置"]), renderNode("p", { "class": styles.hint }, ["未设置个人偏好的用户将使用这些默认值；已有个人设置继续生效。预算修改仅影响新任务，已有任务保留原预算快照。"]), renderNode("label", { "class": styles.field }, [
                                renderNode("span", {}, ["默认思考模式"]), renderNode("select", { "class": "input", "value": userDefaults.value.thinking_enabled ? "1" : "0", "onChange": (e: Event) => setUserDefaults((value: UserDefaults) => ({ ...value, thinking_enabled: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value === "1" })) }, [
                                    renderNode("option", { "value": "0" }, ["关闭"]), renderNode("option", { "value": "1" }, ["开启"])
                                ])
                            ]), renderNode("h3", {}, ["任务总预算"]), renderNode("p", { "class": styles.hint }, ["0 表示不限，个人预算仍受平台配额和权限限制。"]), ([
                                ["max_requests", "默认任务请求上限"],
                                ["max_cost_yuan", "默认任务费用上限（元）"],
                                ["max_runtime_seconds", "默认任务运行上限（秒）"],
                            ] as const).map(([key, label]) => (renderNode("label", { "key": key, "class": styles.field }, [
                                renderNode("span", {}, [label]), renderNode("input", { "class": "input", "type": "number", "min": "0", "step": key === "max_cost_yuan" ? "0.000001" : "1", "value": userDefaults.value.task_budget[key], "onInput": (e: Event) => setUserDefaults((value: UserDefaults) => ({ ...value, task_budget: { ...value.task_budget, [key]: Number((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) } })) }, [])
                            ]))), renderNode("h3", {}, ["扫榜"]), renderNode("label", { "class": styles.field }, [
                                renderNode("span", {}, ["默认启用扫榜"]), renderNode("select", { "class": "input", "value": userDefaults.value.rankings.enabled ? "1" : "0", "onChange": (e: Event) => setUserDefaults((value: UserDefaults) => ({ ...value, rankings: { ...value.rankings, enabled: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value === "1" } })) }, [
                                    renderNode("option", { "value": "1" }, ["开启"]), renderNode("option", { "value": "0" }, ["关闭（只用示例数据）"])
                                ])
                            ]), ([["timeout", "默认扫榜超时", 60], ["limit", "默认扫榜条数", 50]] as const).map(([key, label, max]) => (renderNode("label", { "key": key, "class": styles.field }, [
                                renderNode("span", {}, [label]), renderNode("input", { "class": "input", "type": "number", "min": "1", "max": max, "value": userDefaults.value.rankings[key], "onInput": (e: Event) => setUserDefaults((value: UserDefaults) => ({ ...value, rankings: { ...value.rankings, [key]: Number((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) } })) }, [])
                            ])))
                        ]), (props.section === "all" || props.section === "prompts") && renderNode("section", { "class": `panel ${styles.section}` }, [
                            renderNode("h2", { "class": styles.sectionTitle }, ["角色提示词"]), renderNode("p", { "class": styles.hint }, ["追加到系统指令中，结构化输出规则始终保留。留空使用内置提示词。"]), MODEL_ROLES.map((role: {
                                key: string;
                                label: string;
                            }) => (renderNode("label", { "key": role.key, "class": styles.field }, [
                                renderNode("span", {}, [
                                    role.label, "追加指令"
                                ]), renderNode("textarea", { "class": "textarea", "rows": 4, "value": prompts.value[role.key] ?? "", "onInput": (e: Event) => setPrompts((previous: Record<string, string>) => ({ ...previous, [role.key]: (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value })) }, [])
                            ])))
                        ]), (props.section === "all" || props.section === "genres") && renderNode("section", { "class": `panel ${styles.section}` }, [
                            renderNode("h2", { "class": styles.sectionTitle }, ["平台题材包"]), renderNode("label", { "class": styles.field }, [
                                renderNode("span", {}, ["编辑根题材"]), renderNode("select", { "class": "input", "value": genreId.value, "onChange": (e: Event) => setGenreId((e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).value) }, [catalog.value.map((item: GenreCatalogItem) => renderNode("option", { "key": item.id, "value": item.id }, [item.name]))])
                            ]), renderNode("p", { "class": styles.hint }, ["更改用于新建作品，已有作品保留建书时的快照。"]), genreId.value && (renderNode(GenrePackFields, { "value": genrePacks.value[genreId.value] ?? composeFields(catalog.value.find((item: GenreCatalogItem) => item.id === genreId.value)), "onChange": (fields: GenreFields) => setGenrePacks((previous: Record<string, GenreFields>) => ({ ...previous, [genreId.value]: fields })) })), renderNode("button", { "class": "btn btn-secondary", "type": "button", "disabled": !genrePacks.value[genreId.value], "onClick": () => setGenrePacks((previous: Record<string, GenreFields>) => {
                                    const next = { ...previous };
                                    delete next[genreId.value];
                                    return next;
                                }) }, ["移除此题材覆盖（保存后生效）"])
                        ]), renderNode("div", { "class": styles.saveRow }, [renderNode("button", { "class": "btn btn-primary", "type": "button", "onClick": () => void saveRoutes() }, ["保存全部更改"])])
                    ])
                ])])
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        section: { type: Object as PropType<ConfigurationSection>, required: true }
    }
});
PlatformConfiguration.props = ["section"];
PlatformConfiguration.inheritAttrs = false;
