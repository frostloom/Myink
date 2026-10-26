<script lang="ts">
import { defineComponent, h, Fragment, ref, shallowRef, computed, onScopeDispose, watch } from 'vue';

import { RouterLink, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router';
import ProjectRail from "../components/ProjectRail.vue";
import { useAuth } from "../authContext";
import { api } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import { styleLibraryApi, type StyleLibraryItem } from "../../../src/lib/styleLibraryApi";
import type { Project } from "../../../src/types";
import styles from "../../../src/pages/StyleLibraryPage.module.css";
/** 文笔八维：与后端 prompts._STYLE_PROSE_DIMS 同一份口径（键 → 中文名，顺序即展示顺序）。
 *  那边负责给模型看，这边给人看，键名改动要两边一起改。 */
const PROSE_DIMS: Array<[
    string,
    string
]> = [
    ['narrative_voice', '叙事声音与语气'],
    ['dialogue_style', '对话风格'],
    ['scene_description', '场景描写特征'],
    ['transitions', '转折与衔接手法'],
    ['pacing', '节奏特征'],
    ['diction', '词汇偏好'],
    ['emotional_expression', '情绪表达方式'],
    ['distinctive_habits', '独特习惯'],
];
/** 主区的键与中文名，顺序即展示顺序：文笔八维在前，短约束在后，清单收尾。 */
const MAIN_ORDER: Array<[
    string,
    string
]> = [
    ['pov', '视角'],
    ...PROSE_DIMS,
    ['sentence_style', '句式风格'],
    ['lexicon_tendency', '词汇修辞倾向'],
    ['dialogue', '对话腔调'],
    ['forbidden', '禁用表达（每行一条）'],
    ['reference_excerpts', '样本摘录（每行一条）'],
];
/** 统计层的键（确定性测量）：认得出的给中文名，认不出的原样显示键名——不能因为不认识就丢。 */
const STAT_LABELS: Record<string, string> = {
    sentence_len_dist: '句长分布',
    dialogue_ratio: '对话占比',
    para_stats: '段落结构',
    frequent_words: '高频词串',
    source: '来源',
};
/** 只认这两种形状：字符串与字符串数组。数字 / 嵌套对象是统计层的中间结果，手改没有意义。 */
function editable(value: unknown): value is string | string[] {
    return typeof value === 'string'
        || (Array.isArray(value) && value.every((entry) => typeof entry === 'string'));
}
/** 统计值一行化：数组用顿号连，别的原样 JSON——嵌套对象也得看得见。 */
function describe(value: unknown): string {
    if (Array.isArray(value))
        return value.join('、');
    return typeof value === 'string' ? value : JSON.stringify(value);
}
function MainField({ label, value, readOnly, onChange }: {
    label: string;
    value: string | string[];
    readOnly: boolean;
    onChange: (next: unknown) => void;
}) {
    const lines = Array.isArray(value);
    // 看已有项是读，不是填表：串成一段话/一串条目，别把八维摊成八个只读输入框。
    if (readOnly) {
        return (h("div", { "class": styles.field }, [h("span", { "class": styles.fieldLabel }, [label]), lines
                ? h("ul", { "class": styles.fieldList }, [value.map((entry) => h("li", { "key": entry }, [entry]))]) : h("p", { "class": styles.fieldText }, [value])]));
    }
    return (h("label", {}, [h("span", {}, [label]), h("textarea", { "class": "input", "rows": lines ? 3 : 2, "aria-label": label, "value": lines ? value.join('\n') : value, "onInput": (e: Event & { target: HTMLInputElement }) => onChange(lines
                ? e.target.value.split('\n')
                : e.target.value) }, [])]));
}
// onChange carries profile values, not bubbling native DOM change events.
MainField.inheritAttrs = false;
/** 档案正文：主区放文笔，统计指纹折起来。新建与查看共用，两边看到的东西才是同一份。 */
function ProfileFields({ profile, readOnly, onChange }: {
    profile: Record<string, unknown>;
    readOnly: boolean;
    onChange: (key: string, next: unknown) => void;
}) {
    const main = MAIN_ORDER.filter(([key]) => editable(profile[key]));
    const shown = new Set(main.map(([key]) => key));
    // extract_error 是页面上单独的降级提示，不是档案的一部分。
    const stats = Object.keys(profile).filter((key) => !shown.has(key) && key !== 'extract_error');
    return (h(Fragment, null, [main.length > 0 && h("h3", { "class": styles.blockTitle }, ["文笔"]), main.map(([key, label]) => (h(MainField, { "key": key, "label": label, "value": profile[key] as string | string[], "readOnly": readOnly, "onChange": (next) => onChange(key, next) }, () => []))), stats.length > 0 && (h("details", { "class": styles.stats }, [h("summary", {}, ["统计指纹 · 句长、段落与高频词"]), h("div", { "class": styles.statList }, [stats.map((key) => (h("div", { "class": styles.stat, "key": key }, [h("span", {}, [STAT_LABELS[key] ?? key]), h("code", {}, [describe(profile[key])])])))])]))]));
}
function hasContent(value: unknown): boolean {
    if (typeof value === 'string')
        return value.trim().length > 0;
    if (typeof value === 'number')
        return Number.isFinite(value);
    if (Array.isArray(value))
        return value.some(hasContent);
    if (value !== null && typeof value === 'object')
        return Object.values(value).some(hasContent);
    return false;
}
function profileSummary(profile: Record<string, unknown>): string {
    return ['narrative_voice', 'pacing', 'pov'].map((key) => profile[key])
        .filter((value): value is string => typeof value === 'string' && value.trim() !== '')
        .slice(0, 2).join(' · ');
}
export const StyleLibraryPage = defineComponent({
    setup() {
        const auth = useAuth();
        const { session, logout } = auth;
        const guest = computed(() => auth.status.value !== 'authenticated');
        const token = computed(() => session.value?.token ?? '');
        const projects = ref<Project[]>([]), setProjects = (next: typeof projects.value | ((current: typeof projects.value) => typeof projects.value)) => {
            projects.value = typeof next === "function" ? next(projects.value) : next;
        };
        const items = ref<StyleLibraryItem[]>([]), setItems = (next: typeof items.value | ((current: typeof items.value) => typeof items.value)) => {
            items.value = typeof next === "function" ? next(items.value) : next;
        };
        const selectedId = ref<string | null>(null), setSelectedId = (next: typeof selectedId.value | ((current: typeof selectedId.value) => typeof selectedId.value)) => {
            selectedId.value = typeof next === "function" ? next(selectedId.value) : next;
        };
        const name = ref(''), setName = (next: typeof name.value | ((current: typeof name.value) => typeof name.value)) => {
            name.value = typeof next === "function" ? next(name.value) : next;
        };
        const note = ref(''), setNote = (next: typeof note.value | ((current: typeof note.value) => typeof note.value)) => {
            note.value = typeof next === "function" ? next(note.value) : next;
        };
        const newOpen = ref(false), setNewOpen = (next: typeof newOpen.value | ((current: typeof newOpen.value) => typeof newOpen.value)) => {
            newOpen.value = typeof next === "function" ? next(newOpen.value) : next;
        };
        const sampleText = ref(''), setSampleText = (next: typeof sampleText.value | ((current: typeof sampleText.value) => typeof sampleText.value)) => {
            sampleText.value = typeof next === "function" ? next(sampleText.value) : next;
        };
        const draft = ref<Record<string, unknown> | null>(null), setDraft = (next: typeof draft.value | ((current: typeof draft.value) => typeof draft.value)) => {
            draft.value = typeof next === "function" ? next(draft.value) : next;
        };
        const newName = ref(''), setNewName = (next: typeof newName.value | ((current: typeof newName.value) => typeof newName.value)) => {
            newName.value = typeof next === "function" ? next(newName.value) : next;
        };
        const busy = ref<'extract' | 'save' | 'rename' | 'delete' | null>(null), setBusy = (next: typeof busy.value | ((current: typeof busy.value) => typeof busy.value)) => {
            busy.value = typeof next === "function" ? next(busy.value) : next;
        };
        const inFlight = shallowRef(false);
        const loading = ref(true), setLoading = (next: typeof loading.value | ((current: typeof loading.value) => typeof loading.value)) => {
            loading.value = typeof next === "function" ? next(loading.value) : next;
        };
        const extractedSample = ref(''), setExtractedSample = (next: typeof extractedSample.value | ((current: typeof extractedSample.value) => typeof extractedSample.value)) => {
            extractedSample.value = typeof next === "function" ? next(extractedSample.value) : next;
        };
        const error = ref<string | null>(null), setError = (next: typeof error.value | ((current: typeof error.value) => typeof error.value)) => {
            error.value = typeof next === "function" ? next(error.value) : next;
        };
        const message = ref<string | null>(null), setMessage = (next: typeof message.value | ((current: typeof message.value) => typeof message.value)) => {
            message.value = typeof next === "function" ? next(message.value) : next;
        };
        // rail 的书目：与别的页面同一个来源，拿不到就当空列表（rail 的分区链接照样在）。
        watch(() => [guest.value], (_next, _prev, _onCleanup) => {
            if (guest.value) {
                setProjects([]);
                return;
            }
            api.listProjects().then(setProjects).catch(() => setProjects([]));
        }, { immediate: true, flush: "post" });
        let loadGeneration = 0;
        let listRequest: AbortController | null = null;
        onScopeDispose(() => { ++loadGeneration; listRequest?.abort(); });
        const reload = async () => {
            const generation = ++loadGeneration;
            listRequest?.abort();
            if (guest.value || !token.value) {
                setItems([]); setLoading(false); setError(null);
                return;
            }
            const request = new AbortController();
            listRequest = request;
            setLoading(true);
            setError(null);
            try {
                const result = await styleLibraryApi.list(token.value, request.signal);
                if (generation === loadGeneration && !request.signal.aborted) setItems(result.items);
            }
            catch (reason) {
                if (generation === loadGeneration && !request.signal.aborted) setError(formatApiError(reason, '读不到文风库，请稍后重试'));
            }
            finally {
                if (generation === loadGeneration && !request.signal.aborted) setLoading(false);
            }
        };
        watch(() => [guest.value, token.value], () => { void reload(); }, { immediate: true, flush: "post" });
        const run = async (operation: NonNullable<typeof busy.value>, action: () => Promise<void>, fallback: string) => {
            if (guest.value || !token.value) { setError('请先登录后使用文风库。'); return; }
            if (inFlight.value)
                return;
            inFlight.value = true;
            setError(null);
            setMessage(null);
            setBusy(operation);
            try {
                await action();
            }
            catch (reason) {
                setError(formatApiError(reason, fallback));
            }
            finally {
                setBusy(null);
                inFlight.value = false;
            }
        };
        const selected = computed(() => items.value.find((item) => item.id === selectedId.value) ?? null);
        const builtins = computed(() => items.value.filter((item) => item.builtin));
        const mine = computed(() => items.value.filter((item) => !item.builtin));
        const hasDraft = computed(() => sampleText.value !== '' || draft.value !== null || newName.value !== '');
        const unsaved = computed(() => hasDraft.value || busy.value !== null || (selected.value !== null && !selected.value.builtin && (name.value !== selected.value.name || note.value !== selected.value.note)));
        const beforeUnload = (event: BeforeUnloadEvent) => { if (unsaved.value) { event.preventDefault(); event.returnValue = ''; } };
        window.addEventListener('beforeunload', beforeUnload);
        onScopeDispose(() => window.removeEventListener('beforeunload', beforeUnload));
        const protect = () => !unsaved.value || window.confirm('文风还没保存，确认离开？');
        onBeforeRouteLeave(protect);
        onBeforeRouteUpdate(protect);
        const usableDraft = computed(() => draft.value !== null && Object.entries(draft.value)
            .some(([key, value]) => key !== 'extract_error' && key !== 'source' && hasContent(value)));
        const sampleChanged = computed(() => draft.value !== null && sampleText.value !== extractedSample.value);
        const canSave = computed(() => usableDraft.value && newName.value.trim() !== '' && !sampleChanged.value);
        const busyMessage = computed(() => busy.value === 'extract' ? '正在提取文风…'
            : busy.value === 'save' ? '正在保存文风…'
                : busy.value === 'rename' ? '正在保存修改…'
                    : busy.value === 'delete' ? '正在删除文风…' : null);
        // 同一时刻只开一个面板：新建与查看互斥，页面上不会同时出现两个「文风名」。
        const openItem = (item: StyleLibraryItem) => {
            setNewOpen(false);
            setSelectedId(item.id);
            setName(item.name);
            setNote(item.note);
            setError(null);
            setMessage(null);
        };
        const openNew = () => {
            setSelectedId(null);
            setNewOpen(true);
            setError(null);
            setMessage(null);
        };
        const extract = () => sampleText.value.trim() !== '' && void run('extract', async () => {
            setDraft((await styleLibraryApi.extract(token.value, [sampleText.value])).draft);
            setExtractedSample(sampleText.value);
        }, '提取失败，请重试');
        const saveNew = () => canSave.value && void run('save', async () => {
            // extract_error 只是页面上的降级提示，不是档案的一部分，不落库。
            const { extract_error: _omit, ...profile } = draft.value ?? {};
            // 编辑中保留空行，避免 Enter 被受控输入吞掉；仅在保存时整理已知清单。
            for (const key of ['forbidden', 'reference_excerpts']) {
                const value = profile[key];
                if (Array.isArray(value) && value.every((entry) => typeof entry === 'string')) {
                    profile[key] = value.map((entry) => entry.trim()).filter((entry) => entry !== '');
                }
            }
            const saved = await styleLibraryApi.save(token.value, {
                name: newName.value.trim(), profile, sample_chars: Array.from(extractedSample.value).length,
            });
            // 追加而不是重拉：列表已经按「内置在前」排好，插到末尾不会打乱。
            setItems((prev) => [...prev, saved]);
            openItem(saved);
            setNewName('');
            setSampleText('');
            setExtractedSample('');
            setDraft(null);
            setMessage('文风已保存，可在创作时选用。');
        }, '保存失败，请重试');
        const rename = () => name.value.trim() !== '' && void run('rename', async () => {
            if (selected.value === null)
                return;
            const next = await styleLibraryApi.patch(token.value, selected.value.id, { name: name.value.trim(), note: note.value });
            setItems((prev) => prev.map((item) => (item.id === next.id ? next : item)));
            setName(next.name);
            setNote(next.note);
            setMessage('名称与备注已保存。');
        }, '保存修改失败，请重试');
        const remove = (item: StyleLibraryItem) => void run('delete', async () => {
            if (!window.confirm(`删除文风「${item.name}」？`))
                return;
            await styleLibraryApi.remove(token.value, item.id);
            setItems((prev) => prev.filter((row) => row.id !== item.id));
            if (selectedId.value === item.id)
                setSelectedId(null);
            setMessage('文风已删除。');
        }, '删除失败，请重试');
        const row = (item: StyleLibraryItem) => (h("li", { "key": item.id }, [h("button", { "type": "button", "aria-label": item.name, "aria-pressed": item.id === selectedId.value, "disabled": busy.value !== null, "class": item.id === selectedId.value ? `${styles.item} ${styles.itemOn}` : styles.item, "onClick": () => openItem(item) }, [h("span", { "class": styles.itemName }, [item.name]), h("span", { "class": styles.itemSummary }, [item.note || `文风 · ${profileSummary(item.profile) || '查看文笔与写作约束'}`])])]));
        return () => (h("div", { "class": styles.wrap }, [h("div", { "class": styles.rail }, [h(ProjectRail, { "projects": projects.value, "onLogout": logout }, () => [])]), h("main", { "class": styles.main }, [h("div", { "class": styles.inner }, [h("header", { "class": styles.header }, [h("div", {}, [h("div", { "class": styles.eyebrow }, ["写作资源"]), h("h1", {}, ["文风库"]), h("p", { "class": styles.hint }, ["收藏写作风格，用于长篇与短篇创作。"])]), h(RouterLink, { "class": styles.back, "to": "/long" }, () => ["返回长篇"])]), h("div", { "class": styles.layout }, [h("aside", { "class": styles.catalog, "aria-label": "文风目录" }, [h("div", { "class": styles.catalogHead }, [h("h2", {}, ["全部文风", h("span", {}, [items.value.length])]), h("button", { "type": "button", "class": "btn btn-secondary", "disabled": busy.value !== null, "onClick": openNew }, [hasDraft.value ? '继续新建文风' : '新建文风'])]), loading.value && h("p", { "class": styles.hint, "role": "status" }, ["正在加载文风库…"]), h("ul", { "class": styles.list, "aria-label": "文风" }, [builtins.value.length > 0 && h("li", { "class": styles.groupTitle }, ["内置文风", h("span", {}, [builtins.value.length])]), builtins.value.map(row), h("li", { "class": styles.groupTitle }, ["我的文风", h("span", {}, [mine.value.length])]), mine.value.map(row)]), !loading.value && mine.value.length === 0 && h("p", { "class": styles.hint }, ["尚未保存个人文风"])]), newOpen.value ? (h("section", { "class": styles.newBox, "aria-label": "新建文风" }, [h("div", { "class": styles.detailHead }, [h("div", { "class": styles.eyebrow }, ["个人文风"]), h("h2", {}, [draft.value === null ? '从文章中提取文风' : '预览与调整']), h("ol", { "class": styles.steps, "aria-label": "新建步骤" }, [h("li", { "aria-current": draft.value === null ? 'step' : undefined }, ["01 文章样本"]), h("li", { "aria-current": draft.value !== null ? 'step' : undefined }, ["02 文风预览"]), h("li", {}, ["03 保存选用"])])]), h("details", { "class": styles.sample, "open": draft.value === null }, [h("summary", {}, [draft.value === null ? '文章样本' : `查看或更换样本 · ${Array.from(sampleText.value).length} 字`]), h("label", {}, [h("span", {}, ["粘贴文章"]), h("textarea", { "class": "input", "rows": 9, "aria-label": "粘贴文章", "value": sampleText.value, "disabled": busy.value !== null, "placeholder": "粘贴具有代表性的小说正文，保留叙述、对话与场景描写。", "onInput": (e: Event & { target: HTMLInputElement }) => setSampleText(e.target.value) }, [])]), draft.value !== null && h("div", { "class": styles.actions }, [h("button", { "type": "button", "class": "btn btn-secondary", "aria-label": "提取文风", "disabled": busy.value !== null || sampleText.value.trim() === '', "onClick": extract }, [busy.value === 'extract' ? '提取中…' : '重新提取文风']), h("span", { "class": styles.hint }, ["重新提取会替换当前文风预览。"])])]), typeof draft.value?.extract_error === 'string' && (h("div", { "class": "banner banner-warning", "role": "alert" }, [draft.value.extract_error])), draft.value !== null && (h("fieldset", { "class": styles.editorFields, "disabled": busy.value !== null }, [h("label", { "class": styles.nameField }, [h("span", {}, ["文风名"]), h("input", { "class": "input", "aria-label": "文风名", "value": newName.value, "maxLength": 64, "placeholder": "例如：渡口白描", "onInput": (e: Event & { target: HTMLInputElement }) => setNewName(e.target.value) }, [])]), h("p", { "class": styles.hint }, ["调整提取结果后保存。已保存文风仅支持修改名称与备注。"]), h(ProfileFields, { "profile": draft.value, "readOnly": false, "onChange": (key, next) => setDraft((prev) => ({ ...(prev ?? {}), [key]: next })) }, () => [])]))])) : selected.value === null ? (h("section", { "class": styles.empty }, [h("span", { "class": styles.eyebrow }, ["文笔 · 节奏 · 表达"]), h("h2", {}, ["选择文风，查看写作特征"]), h("p", { "class": styles.hint }, ["选择文风查看叙事特点与样本摘录，或导入文章，提取自己的写作风格。"])])) : (h("section", { "class": styles.detail, "aria-label": "文风详情" }, [h("div", { "class": styles.detailHead }, [h("div", { "class": styles.eyebrow }, [selected.value.builtin ? '内置文风 · 只读' : '我的文风']), h("h2", {}, [selected.value.name]), profileSummary(selected.value.profile) && h("p", { "class": styles.summary }, ["文风概要：", profileSummary(selected.value.profile)]), Array.isArray(selected.value.profile.reference_excerpts) && typeof selected.value.profile.reference_excerpts[0] === 'string' && (h("blockquote", { "class": styles.excerpt }, [selected.value.profile.reference_excerpts[0]]))]), !selected.value.builtin && (h("fieldset", { "class": styles.metadata, "disabled": busy.value !== null }, [h("label", {}, [h("span", {}, ["文风名"]), h("input", { "class": "input", "aria-label": "文风名", "value": name.value, "maxLength": 64, "onInput": (e: Event & { target: HTMLInputElement }) => setName(e.target.value) }, [])]), h("label", {}, [h("span", {}, ["备注"]), h("input", { "class": "input", "aria-label": "备注", "value": note.value, "maxLength": 200, "placeholder": "记录样本来源或适用题材", "onInput": (e: Event & { target: HTMLInputElement }) => setNote(e.target.value) }, [])])])), h(ProfileFields, { "profile": selected.value.profile, "readOnly": true, "onChange": () => undefined }, () => [])]))])]), h("div", { "class": styles.actionBar }, [h("div", { "class": styles.feedback }, [error.value ? h("p", { "class": styles.error, "role": "alert" }, [error.value]) : h("p", { "role": "status" }, [busyMessage.value || message.value || (newOpen.value ? draft.value === null ? '先提取文章中的文笔与表达特征。'
                                : sampleChanged.value ? '样本已更改，请重新提取后保存。'
                                    : !usableDraft.value ? '未提取到有效文风，请调整样本后重试。'
                                        : !newName.value.trim() ? '填写文风名后即可保存。' : '保存后可在长篇与短篇创作中选用。'
                                : selected.value?.builtin ? '内置文风可直接用于创作。'
                                    : selected.value ? '文风内容只读，可修改名称与备注。' : '选择文风，或从文章中提取。')])]), h("div", { "class": styles.actions }, [newOpen.value ? h(Fragment, null, [h("button", { "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null, "onClick": () => setNewOpen(false) }, ["暂存并关闭"]), draft.value === null
                                ? h("button", { "type": "button", "class": "btn btn-primary", "aria-label": "提取文风", "disabled": busy.value !== null || sampleText.value.trim() === '', "onClick": extract }, [busy.value === 'extract' ? '提取中…' : '提取文风']) : h("button", { "type": "button", "class": "btn btn-primary", "aria-label": "保存文风", "disabled": busy.value !== null || !canSave.value, "onClick": saveNew }, [busy.value === 'save' ? '保存中…' : '保存文风'])]) : selected.value && !selected.value.builtin ? h(Fragment, null, [selected.value.removable && h("button", { "type": "button", "class": "btn btn-quiet", "aria-label": "删除文风", "disabled": busy.value !== null, "onClick": () => selected.value && remove(selected.value) }, ["删除文风"]), h("button", { "type": "button", "class": "btn btn-primary", "aria-label": "重命名", "disabled": busy.value !== null || !name.value.trim() || (name.value === selected.value.name && note.value === selected.value.note), "onClick": rename }, [busy.value === 'rename' ? '保存中…' : '保存修改'])]) : error.value && h("button", { "type": "button", "class": "btn btn-secondary", "disabled": loading.value, "onClick": () => void reload() }, ["重新加载"])])])])]));
    }
});

export default StyleLibraryPage

</script>
