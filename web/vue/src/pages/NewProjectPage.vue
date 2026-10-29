<script lang="ts">
import WaitingStatus from '../components/WaitingStatus.vue';
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import { defineComponent, ref, computed, watch, nextTick, onBeforeUnmount, h, Fragment } from 'vue';
import type { PropType } from 'vue';
import { useRouter, useRoute } from 'vue-router';
// 建书向导（§7.11）：书名/题材 + 一句话梗概 → 创建作品 → Planner 生成设定骨架草稿 →
// 可编辑确认 → 落库跳工作台。agent 只提案、用户确认是唯一 canon（§7.11 ③）。
// 布局复用 SettingsPage 的 wrap→rail→main→inner；分区编辑控件对齐 KeyField 风格。
import StructuredTextField from '../components/StructuredTextField.vue';
import ProjectRail from '../components/ProjectRail.vue';
import CreationResourcesDialog from '../components/CreationResourcesDialog.vue';
import { writingResources, type SelectionInput } from '../../../src/lib/writingResources';
import RankingsPanel from '../components/RankingsPanel.vue';
import { useAuth } from '../authContext';
import { api } from '../../../src/lib/api';
import { formatApiError } from '../../../src/lib/apiError';
import { isProjectDraft } from '../../../src/lib/projectCreation';
import { styleLibraryApi, type StyleLibraryItem } from '../../../src/lib/styleLibraryApi';
import { displayGenre, groupCatalog, type GenreCatalogItem, } from '../../../src/lib/genrePacks';
import { emptySection, isSectionEmpty, sectionToBody, splitDraft, type SetupSection, } from '../../../src/lib/bookDraft';
import type { BookOutline, OutlineChapter, OutlineStage, OutlineVolume, Project } from '../../../src/types';
import styles from '../../../src/pages/NewProjectPage.module.css';
const PENDING_PROJECT_CREATION_KEY = 'myink.pending-project-creation';
// 短篇形态参数（docs/SHORT-FORM.md §5）：长篇的章数/每章字数区间与短篇不同，
// 全篇总量上限决定后端会不会把每章字数压下来，压了就得告诉用户。
const SHORT_CHAPTER_MIN = 1;
const SHORT_CHAPTER_MAX = 10;
const SHORT_CHARS_MIN = 1000;
const SHORT_CHARS_MAX = 8000;
const SHORT_TOTAL_MAX = 20000;
function pendingProjectCreationId(): string {
    const existing = window.sessionStorage.getItem(PENDING_PROJECT_CREATION_KEY);
    if (existing)
        return existing;
    const created = window.crypto.randomUUID();
    window.sessionStorage.setItem(PENDING_PROJECT_CREATION_KEY, created);
    return created;
}
/** 通用「每行一条」文本 ↔ 字符串数组（去空行） */
function linesToArray(text: string): string[] {
    return text
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
}
function arrayToLines(arr: string[]): string {
    return arr.join('\n');
}
function chapterRangeLabel(start?: number, end?: number): string {
    return start && end ? `第 ${start}–${end} 章` : '';
}
/** world_rules 键值编辑器：每行「键：值」（全角/半角冒号首个分隔），值可含冒号 */
function worldRulesToText(wr: Record<string, string>): string {
    return Object.entries(wr)
        .map(([k, v]) => `${k}：${v}`)
        .join('\n');
}
function textToWorldRules(text: string): Record<string, string> {
    const out: Record<string, string> = {};
    for (const line of text.split('\n')) {
        const s = line.trim();
        if (!s)
            continue;
        const i = s.indexOf('：');
        const j = s.indexOf(':');
        const idx = i === -1 ? j : j === -1 ? i : Math.min(i, j);
        if (idx <= 0)
            continue;
        out[s.slice(0, idx).trim()] = s.slice(idx + 1).trim();
    }
    return out;
}
function ApiMessage(err: unknown, fallback: string): string {
    return formatApiError(err, fallback);
}
/** 形态由入口决定（/long/new 或 /short/new）；草稿恢复时以服务端记的形态为准。 */
export default defineComponent({
    name: 'NewProjectPage', props: {
        form: {
            type: String as PropType<'long' | 'short'>, default: 'long'
        }
    }, setup(props) {
        const routeForm = computed(() => props.form);
        let generation = 0;
        let alive = true;
        let owner: string | undefined;
        const active = (attempt: number) => alive && generation === attempt;
        onBeforeUnmount(() => { alive = false; generation++; });
        const { session, status, logout } = useAuth();
        const guest = computed(() => status.value === 'anonymous');
        const token = computed(() => session.value?.token ?? '');
        const router = useRouter();
        const navigate = (path: string, options?: {
            replace?: boolean;
            state?: Record<string, string | boolean | null>;
        }) => { const resolved = router.resolve(path); return permitNavigation(() => router[options?.replace ? 'replace' : 'push']({
            path: resolved.path, query: resolved.query, hash: resolved.hash, state: options?.state
        })); };
        const route = useRoute();
        const resumeId = computed(() => typeof route.query.draft === 'string' ? route.query.draft : null);
        const setSearchParams = (query: Record<string, string>, _options: {
            replace: boolean;
        }) => permitNavigation(() => router.replace({
            query
        }));
        const currentPid = ref<string | null>(null);
        const scrollContainer = ref<HTMLElement | null>(null);
        const step = ref(0);
        const resourceOpen = ref(false);
        const resourceError = ref<string | null>(null);
        watch(step, async () => {
            await nextTick();
            if (!scrollContainer.value) return;
            scrollContainer.value.scrollTop = 0;
            const heading = scrollContainer.value.querySelector<HTMLElement>('section:not([hidden]) h2');
            heading?.focus({ preventScroll: true });
        });
        const title = ref('');
        // 已落库的书名（AI 起名/用户填写后确认）；书名留空时由 Planner 在设定草稿带 title 建议
        const savedTitle = ref('');
        const catalog = ref<GenreCatalogItem[]>([]);
        const primaryId = ref<string | null>(null);
        const secondaryId = ref<string | null>(null);
        const premise = ref('');
        // 作品形态：短篇走另一条生成管道（整篇一次成稿），章数/每章字数的区间都不同
        const form = ref<'long' | 'short'>(routeForm.value);
        // 每章目标字数（§6.9 三层字数控制；500–20000，默认 3000）
        const targetWords = ref('3000');
        // 短篇每章字数（1000–8000；全篇总量超上限时后端会压下来并回传提示）
        const shortChars = ref('2000');
        const projects = ref<Project[]>([]);
        const pid = ref<string | null>(null);
        const section = ref<SetupSection | null>(null);
        const draftError = ref<string | null>(null);
        // ③ 整书大纲（§11）：设定确认落库后出现；梗概 + 大致章节数 + 大致故事线 → Planner 提案
        const setupConfirmed = ref(false);
        const outlineCount = ref('200');
        const outlineStoryline = ref('');
        const outline = ref<BookOutline | null>(null);
        const outlineError = ref<string | null>(null);
        // 短篇方案的服务端回执：字数被压到多少（null = 没压过）、审纲留了改稿痕（都要让用户看见，§8 风险）
        const compressedChars = ref<number | null>(null);
        const outlineWarning = ref<string | null>(null);
        const busy = ref<string | null>(resumeId.value ? 'restore' : null);
        const banner = ref<string | null>(null);
        const ok = ref<string | null>(null);
        // 建书时选文风（可选）：列表来自账号文风库，值原样交给后端解析（内置预设是 "builtin:<id>"）
        const styleItems = ref<StyleLibraryItem[]>([]);
        const styleItemId = ref('');
        const initialForm = JSON.stringify(['', null, null, '', '3000', '2000', '200', '', '']);
        const { permitNavigation } = useMemoryFormGuard(() => !guest.value && (
            (busy.value !== null && busy.value !== 'restore') || section.value !== null || outline.value !== null ||
            JSON.stringify([title.value, primaryId.value, secondaryId.value, premise.value, targetWords.value, shortChars.value, outlineCount.value, outlineStoryline.value, styleItemId.value]) !== initialForm), { recovering: () => guest.value });
        watch([
            guest, token
        ], (_next, _previous, onCleanup) => {
            let cancelled = false;
            onCleanup(() => { cancelled = true; });
            projects.value = [];
            catalog.value = [];
            styleItems.value = [];
            if (guest.value)
                return;
            void api.listProjects().then(next => { if (!cancelled)
                projects.value = next; }).catch(() => { });
            void api.listGenrePacks().then(next => { if (!cancelled)
                catalog.value = next; }).catch(() => {
                if (!cancelled)
                    banner.value = '题材目录加载失败，可先不选题材创建';
            });
            void styleLibraryApi.list(token.value).then(out => { if (!cancelled)
                styleItems.value = out.items; }).catch(() => { });
        }, {
            immediate: true
        });
        watch([guest, resumeId, routeForm, () => session.value?.userId], (_next, _previous, onCleanup) => {
            if (!guest.value && resumeId.value && currentPid.value === resumeId.value && owner === session.value?.userId)
                return;
            owner = session.value?.userId;
            generation++;
            let disposed = false;
            currentPid.value = null;
            step.value = 0;
            resourceOpen.value = false;
            resourceError.value = null;
            pid.value = null;
            title.value = '';
            savedTitle.value = '';
            primaryId.value = null;
            secondaryId.value = null;
            premise.value = '';
            form.value = routeForm.value;
            targetWords.value = '3000';
            shortChars.value = '2000';
            styleItemId.value = '';
            section.value = null;
            draftError.value = null;
            setupConfirmed.value = false;
            // 章数初值必须落在本形态的区间里：短篇是 1–10，长篇的 200 会被后端章数校验挡下。
            outlineCount.value = routeForm.value === 'short' ? '5' : '200';
            outlineStoryline.value = '';
            outline.value = null;
            outlineError.value = null;
            compressedChars.value = null;
            outlineWarning.value = null;
            banner.value = null;
            ok.value = null;
            busy.value = resumeId.value ? 'restore' : null;
            // 退出与换账号同样使所有旧请求失效，清空旧账号的创建内容。
            if (guest.value) { busy.value = null; return; }
            if (!resumeId.value) {
                onCleanup(() => { disposed = true; });
                return;
            }
            void api.getCreation(resumeId.value).then(({ project, context }) => {
                if (disposed)
                    return;
                if (!isProjectDraft(project)) {
                    navigate(`/projects/${project.id}`, {
                        replace: true
                    });
                    return;
                }
                currentPid.value = project.id;
                pid.value = project.id;
                title.value = project.title;
                savedTitle.value = project.title;
                const resolvedForm = project.form ?? context.form ?? routeForm.value;
                form.value = resolvedForm;
                targetWords.value = String(project.target_words ?? 3000);
                shortChars.value = String(context.chars_per_chapter ?? 2000);
                premise.value = context.premise ?? '';
                outlineCount.value = String(context.chapter_count ?? (resolvedForm === 'short' ? 5 : 200));
                outlineStoryline.value = context.storyline ?? '';
                section.value = splitDraft(context.setup_draft ?? {});
                setupConfirmed.value = project.creation_status === 'setup_confirmed';
                step.value = setupConfirmed.value ? 2 : 1;
                draftError.value = context.setup_error ?? null;
                outlineError.value = context.outline_error ?? null;
                compressedChars.value = context.lengths_compressed ? context.chars_per_chapter ?? null : null;
                outlineWarning.value = context.outline_warning ?? null;
                outline.value = {
                    objective: context.outline_draft?.objective ?? '', volumes: context.outline_draft?.volumes ?? []
                };
                ok.value = '已恢复待完成作品，可继续确认设定与大纲；不会重复创建作品。';
            }).catch((err) => {
                if (!disposed)
                    banner.value = ApiMessage(err, '恢复草稿失败，请刷新重试');
            })
                .finally(() => {
                if (!disposed)
                    busy.value = null;
            });
            {
                onCleanup(() => { disposed = true; });
                return;
            }
        }, {
            immediate: true, flush: "post"
        });
        const primary = computed(() => catalog.value.find((item) => item.id === primaryId.value) ?? null);
        const secondary = computed(() => catalog.value.find((item) => item.id === secondaryId.value) ?? null);
        const genreLabel = computed(() => displayGenre(primary.value, secondary.value));
        const isShort = computed(() => form.value === 'short');
        /** 短篇方案的服务端回执（归一后的字数、审纲留痕）只落在创建上下文里，要再拉一次才算看见 */
        async function refreshShortNotice(forPid: string) {
            const attempt = generation;
            try {
                const { context } = await api.getCreation(forPid);
                if (!active(attempt))
                    return;
                compressedChars.value = context.lengths_compressed ? context.chars_per_chapter ?? null : null;
                outlineWarning.value = context.outline_warning ?? null;
            }
            catch {
                /* 回执是附加信息，读不到就不显示 */
            }
        }
        function pickPrimary(id: string) {
            const next = primaryId.value === id ? null : id;
            primaryId.value = next;
            secondaryId.value = null;
        }
        function pickSecondary(id: string) {
            if (!primaryId.value)
                return;
            const next = secondaryId.value === id ? null : id;
            secondaryId.value = next;
        }
        async function createAndDraft() {
            const attempt = generation;
            if (guest.value || pid.value || resumeId.value || busy.value)
                return;
            const brief = premise.value.trim();
            if (!brief) {
                banner.value = '请填写创作简报（设定与大纲的种子）';
                return;
            }
            const words = Number(targetWords.value);
            if (!isShort.value && (!Number.isInteger(words) || words < 500 || words > 20000)) {
                banner.value = '目标字数需为 500–20000 的整数';
                return;
            }
            const finalTitle = title.value.trim() || '未命名作品';
            const chapterCount = Number(outlineCount.value);
            const countMin = isShort.value ? SHORT_CHAPTER_MIN : 50;
            const countMax = isShort.value ? SHORT_CHAPTER_MAX : 1000;
            if (!Number.isInteger(chapterCount) || chapterCount < countMin || chapterCount > countMax) {
                banner.value = isShort.value ? '大致章节数需为 1–10 的整数' : '大致章节数需为 50–1000 的整数';
                return;
            }
            const chars = Number(shortChars.value);
            if (isShort.value && (!Number.isInteger(chars) || chars < SHORT_CHARS_MIN || chars > SHORT_CHARS_MAX)) {
                banner.value = '每章字数需为 1000–8000 的整数';
                return;
            }
            let requestId: string;
            try {
                requestId = pendingProjectCreationId();
            }
            catch {
                banner.value = '无法安全保存创建请求，请检查浏览器存储权限后重试';
                return;
            }
            busy.value = 'create';
            banner.value = null;
            ok.value = null;
            try {
                const project = await api.createProject({
                    title: finalTitle,
                    primary_id: primaryId.value,
                    secondary_id: secondaryId.value,
                    // 形态由入口决定，显式声明：短篇的篇幅走 chars_per_chapter（长篇的每章字数走 target_words），互不代填
                    form: form.value,
                    ...(isShort.value ? {
                        chars_per_chapter: chars
                    } : {
                        target_words: words
                    }),
                    premise: brief,
                    chapter_count: chapterCount,
                    storyline: outlineStoryline.value.trim(),
                    request_id: requestId,
                    // 不指定就显式发 null：后端把「没选」与「选了查不到」分得很开（后者 404）。
                    style_item_id: styleItemId.value || null
                });
                if (!active(attempt))
                    return;
                let storageCleanupFailed = false;
                try {
                    window.sessionStorage.removeItem(PENDING_PROJECT_CREATION_KEY);
                }
                catch {
                    storageCleanupFailed = true;
                }
                currentPid.value = project.id;
                pid.value = project.id;
                setSearchParams({
                    draft: project.id
                }, {
                    replace: true
                });
                savedTitle.value = finalTitle;
                void api.listProjects().then(next => { if (active(attempt))
                    projects.value = next; }).catch(() => { });
                // 一键建书：设定草稿 + 整书大纲草稿并行生成（outline 只读 genre/premise，无需等设定确认）
                const results = await Promise.all([
                    regenerate(project.id, true), generateOutline(project.id, true)
                ]);
                if (!active(attempt))
                    return;
                step.value = 1;
                ok.value = results.every(Boolean)
                    ? '作品草稿已保存，设定与整书大纲提案已生成，请编辑并确认。'
                    : '作品草稿已保存；草稿生成未全部完成，请检查提示后重试或手动填写。';
                if (storageCleanupFailed) {
                    banner.value = '作品已创建，但无法清除本机创建标识；后续重试会安全复用同一作品。';
                }
            }
            catch (err) {
                if (!active(attempt))
                    return;
                banner.value = ApiMessage(err, '创建作品失败，请重试');
            }
            finally {
                if (active(attempt)) {
                    busy.value = null;
                }
            }
        }
        async function regenerate(forPid: string, managed = false) {
            const attempt = generation;
            if (!managed && busy.value)
                return false;
            if (!managed)
                busy.value = 'draft';
            banner.value = null;
            draftError.value = null;
            try {
                const resp = await api.setupDraft(forPid, premise.value.trim());
                if (!active(attempt))
                    return false;
                section.value = splitDraft(resp.draft);
                draftError.value = resp.error;
                // AI 起名：书名留空时 Planner 在设定草稿带 title 建议，创建后回写
                const aiTitle = typeof resp.draft.title === 'string' ? resp.draft.title.trim() : '';
                if (!title.value.trim() && aiTitle) {
                    title.value = aiTitle;
                    savedTitle.value = aiTitle;
                    try {
                        await api.updateProject(forPid, {
                            title: aiTitle
                        });
                        if (!active(attempt))
                            return false;
                    }
                    catch {
                        /* 标题是标签，回写失败静默（不阻塞草稿生成） */
                    }
                }
                return !resp.error;
            }
            catch (err) {
                if (!active(attempt))
                    return false;
                banner.value = ApiMessage(err, '生成设定草稿失败，请重试');
                section.value = emptySection();
                return false;
            }
            finally {
                if (active(attempt)) {
                    if (!managed)
                        busy.value = null;
                }
            }
        }
        async function confirm() {
            const attempt = generation;
            if (busy.value || !pid.value || !section.value)
                return;
            busy.value = 'confirm';
            banner.value = null;
            ok.value = null;
            try {
                await api.confirmSetup(pid.value, sectionToBody(section.value));
                if (!active(attempt))
                    return;
                await syncTitle();
                if (!active(attempt))
                    return;
                setupConfirmed.value = true;
                ok.value = '设定已确认，可继续检查整书大纲。';
                step.value = 2;
            }
            catch (err) {
                if (!active(attempt))
                    return;
                banner.value = ApiMessage(err, '确认落库失败，请重试');
            }
            finally {
                if (active(attempt)) {
                    busy.value = null;
                }
            }
        }
        // ③ 提案保存到创建上下文供恢复；确认后才写入正式大纲。
        async function generateOutline(forPid: string, managed = false) {
            const attempt = generation;
            if (!managed && busy.value)
                return false;
            const cc = Number(outlineCount.value);
            const countMin = isShort.value ? SHORT_CHAPTER_MIN : 50;
            const countMax = isShort.value ? SHORT_CHAPTER_MAX : 1000;
            if (!Number.isInteger(cc) || cc < countMin || cc > countMax) {
                banner.value = isShort.value ? '大致章节数需为 1–10 的整数' : '大致章节数需为 50–1000 的整数';
                return false;
            }
            if (!managed)
                busy.value = 'outline-draft';
            banner.value = null;
            outlineError.value = null;
            try {
                const resp = await api.outlineDraft(forPid, {
                    premise: premise.value.trim(),
                    chapter_count: cc,
                    storyline: outlineStoryline.value.trim(),
                    ...(isShort.value ? {
                        chars_per_chapter: Number(shortChars.value)
                    } : {})
                });
                if (!active(attempt))
                    return false;
                // 降级时 outline 为 {} → 归一为空结构，保证可编辑面板始终可渲染。
                outline.value = {
                    objective: typeof resp.outline.objective === 'string' ? resp.outline.objective : '',
                    volumes: Array.isArray(resp.outline.volumes) ? resp.outline.volumes : []
                };
                outlineError.value = resp.error;
                if (isShort.value)
                    await refreshShortNotice(forPid);
                if (!active(attempt))
                    return false;
                return !resp.error;
            }
            catch (err) {
                if (!active(attempt))
                    return false;
                banner.value = ApiMessage(err, '生成大纲失败，请重试');
                outline.value = {
                    objective: '', volumes: []
                };
                return false;
            }
            finally {
                if (active(attempt)) {
                    if (!managed)
                        busy.value = null;
                }
            }
        }
        /** 输入框书名与已落库书名不同步时回写（输入框为 canon；AI 起名/手动改名后生效） */
        async function syncTitle() {
            const attempt = generation;
            if (!pid.value)
                return;
            const t = title.value.trim();
            if (t && t !== savedTitle.value) {
                await api.updateProject(pid.value, {
                    title: t
                });
                if (!active(attempt))
                    return;
                savedTitle.value = t;
            }
        }
        /** 大纲确认落库（单独确认 / 确认全部共用） */
        async function persistOutline() {
            const attempt = generation;
            if (!pid.value || !outline.value)
                return;
            await api.confirmOutline(pid.value, {
                objective: outline.value.objective,
                volumes: outline.value.volumes.map((v) => ({
                    title: v.title,
                    theme: v.theme ?? '',
                    goal: v.goal,
                    key_results: v.key_results ?? [],
                    end_event: v.end_event ?? '',
                    chapter_start: v.chapter_start,
                    chapter_end: v.chapter_end,
                    stages: (v.stages ?? []).map((s) => ({
                        name: s.name,
                        chapter_start: s.chapter_start,
                        chapter_end: s.chapter_end,
                        goal: s.goal,
                        beats: s.beats ?? []
                    })),
                    // 短篇写手读的是逐章细纲，缺它就整篇成稿无从落地；长篇不传（形状是卷+阶段）
                    ...(isShort.value ? {
                        chapters: (v.chapters ?? []).map((c) => ({
                            chapter_seq: c.chapter_seq,
                            title: c.title ?? '',
                            goal: c.goal ?? '',
                            key_scene: c.key_scene ?? '',
                            character_action: c.character_action ?? '',
                            escalation_or_payoff: c.escalation_or_payoff ?? '',
                            hook: c.hook ?? ''
                        }))
                    } : {})
                })),
                premise: premise.value.trim(),
                chapter_count: Number(outlineCount.value) || 0,
                storyline: outlineStoryline.value.trim()
            });
            if (!active(attempt))
                return;
            await syncTitle();
            if (!active(attempt))
                return;
        }
        /** 确认全部并进入工作台（一次落地）：设定未确认先落，再落大纲，再进入 */
        async function confirmAll(selections: SelectionInput[]) {
            const attempt = generation;
            if (busy.value)
                return;
            if (!pid.value || !outline.value || !section.value || (!setupConfirmed.value && isSectionEmpty(section.value))) {
                banner.value = '请先填写有效的设定与整书大纲';
                return;
            }
            busy.value = 'confirm-all';
            resourceError.value = null;
            banner.value = null;
            ok.value = null;
            try {
                const snapshot = await writingResources.snapshot(pid.value);
                if (!active(attempt)) return;
                await writingResources.select(pid.value, snapshot.revision, selections);
                if (!active(attempt)) return;
                if (section.value && !isSectionEmpty(section.value)) {
                    await api.confirmSetup(pid.value, sectionToBody(section.value));
                    if (!active(attempt))
                        return;
                    setupConfirmed.value = true;
                }
                await persistOutline();
                if (!active(attempt))
                    return;
                await syncTitle();
                if (!active(attempt))
                    return;
                ok.value = '设定与整书大纲已落库';
                resourceOpen.value = false;
                navigate(`/projects/${pid.value}`);
            }
            catch (err) {
                if (!active(attempt))
                    return;
                resourceError.value = ApiMessage(err, '资源保存或建书确认失败，请重试；草稿已保留。');
            }
            finally {
                if (active(attempt)) {
                    busy.value = null;
                }
            }
        }
        /** 未完成作品保留为草稿，不开放写作。 */
        async function leaveDraft() {
            const attempt = generation;
            if (!pid.value)
                return;
            try {
                await syncTitle();
                if (!active(attempt))
                    return;
            }
            catch {
                /* 标题同步失败不阻塞进入 */
            }
            if (active(attempt)) await router.push(`/${form.value}`);
        }
        const updateOutline = (patch: Partial<BookOutline>) => outline.value = ((o) => (o ? {
            ...o, ...patch
        } : o))(outline.value);
        const updateVolume = (vi: number, patch: Partial<OutlineVolume>) => outline.value = ((o) => o
            ? {
                ...o, volumes: o.volumes.map((v, j) => (j === vi ? {
                    ...v, ...patch
                } : v))
            } : o)(outline.value);
        /** 短篇逐章细纲的编辑（章号不可手改：后端要求 1..N 齐整，改坏了确认必失败） */
        const updateShortChapter = (vi: number, ci: number, patch: Partial<OutlineChapter>) => outline.value = ((o) => o
            ? {
                ...o,
                volumes: o.volumes.map((v, j) => j === vi
                    ? {
                        ...v, chapters: (v.chapters ?? []).map((c, k) => (k === ci ? {
                            ...c, ...patch
                        } : c))
                    } : v)
            } : o)(outline.value);
        const updateStage = (vi: number, si: number, patch: Partial<OutlineStage>) => outline.value = ((o) => o
            ? {
                ...o,
                volumes: o.volumes.map((v, j) => j === vi
                    ? {
                        ...v, stages: (v.stages ?? []).map((s, k) => (k === si ? {
                            ...s, ...patch
                        } : s))
                    } : v)
            } : o)(outline.value);
        const removeStage = (vi: number, si: number) => outline.value = ((o) => o
            ? {
                ...o,
                volumes: o.volumes.map((v, j) => j === vi ? {
                    ...v, stages: (v.stages ?? []).filter((_, k) => k !== si)
                } : v)
            } : o)(outline.value);
        const addStage = (vi: number) => outline.value = ((o) => o
            ? {
                ...o,
                volumes: o.volumes.map((v, j) => j === vi
                    ? {
                        ...v, stages: [
                            ...(v.stages ?? []),
                            {
                                name: `第 ${(v.stages ?? []).length + 1} 段`, goal: '', beats: []
                            }
                        ]
                    } : v)
            } : o)(outline.value);
        const addVolume = () => outline.value = ((o) => o
            ? {
                ...o,
                volumes: [
                    ...o.volumes,
                    {
                        title: `第 ${o.volumes.length + 1} 卷`,
                        goal: '',
                        stages: [{
                                name: '本卷', goal: '', beats: []
                            }]
                    }
                ]
            } : o)(outline.value);
        const updateSection = (patch: Partial<SetupSection>) => section.value = ((s) => (s ? {
            ...s, ...patch
        } : s))(section.value);
        const sec = computed(() => section.value ?? emptySection());
        const emptyDraft = computed(() => section.value !== null && isSectionEmpty(sec.value));
        // 设定骨架按题材增减（§7.11）：等级阶梯不是通用维度，都市日常/言情不该被排一套境界表。
        // 三态：true 显示 / false 藏起来 / undefined（续建时还没认出题材）不藏——未知就不替用户做主，
        // 草稿里已经有值的也一律不藏（不能让用户确认一份自己看不见的内容）。
        const powerScaling = computed(() => primary.value?.setup_caps?.power_scaling);
        const showRealmOrder = computed(() => powerScaling.value !== false || sec.value.realm_order.length > 0);
        return () => (h("div", {
            "class": styles.wrap, ref: scrollContainer
        }, [
            resourceOpen.value && h(CreationResourcesDialog, { busy: busy.value !== null, error: resourceError.value, onConfirm: confirmAll, onClose: () => { if (!busy.value) resourceOpen.value = false; } }),
            h(ProjectRail, {
                "projects": projects.value, "onLogout": logout
            }), h("main", {
                "class": styles.main
            }, [h("div", {
                    "class": styles.inner
                }, [
                    h("header", {
                        "class": styles.header
                    }, [h("div", null, [
                            h("h1", null, [pid.value || resumeId.value ? '继续创建作品' : `新建${isShort.value ? '短篇' : '长篇'}`]), h("div", {
                                "class": styles.crumb
                            }, ["创作简报启动，AI 生成设定骨架与整书大纲，你确认后落库。"])
                        ])]), banner.value && h("div", {
                        "class": "banner banner-error", role: "alert"
                    }, [banner.value]), ok.value && h("div", {
                        "class": "banner banner-warning"
                    }, [ok.value]),
                    busy.value && !resourceOpen.value && h(WaitingStatus, { label: busy.value === 'create' ? (pid.value ? '正在生成设定与整书大纲' : '正在创建作品') : ({ restore: '正在恢复作品草稿', draft: '正在生成设定草稿', confirm: '正在确认设定', 'outline-draft': '正在生成整书大纲', 'confirm-all': '正在保存作品' } as Record<string, string>)[busy.value] ?? '正在保存作品' }),
                    !isShort.value && h("nav", { class: styles.steps, 'aria-label': '建书步骤' }, ['作品信息', '设定', '大纲'].map((label, index) => h('button', { type: 'button', disabled: busy.value !== null || (index > 0 && !pid.value) || (index === 2 && !setupConfirmed.value), 'aria-current': step.value === index ? 'step' : undefined, onClick: () => { step.value = index; } }, label))),
                    !isShort.value && (draftError.value || outlineError.value) && h('div', { class: 'banner banner-warning', role: 'alert' }, [draftError.value && `设定生成失败：${draftError.value}。`, outlineError.value && `大纲生成失败：${outlineError.value}。`, '可返回对应步骤重试或手动填写。']),
                    (isShort.value || step.value === 0) && h(RankingsPanel, null), h("section", {
                        "class": `panel ${styles.section}`, hidden: !isShort.value && step.value !== 0
                    }, [
                        h("h2", {
                            "class": styles.sectionTitle, tabindex: -1
                        }, ["① 作品信息"]), h("label", {
                            "class": styles.field
                        }, [
                            h("span", {
                                "class": styles.fieldLabel
                            }, ["书名"]), h("input", {
                                "class": "input", "value": title.value, "disabled": busy.value === 'restore', "onInput": (e: Event) => title.value = (e.target as HTMLInputElement).value, "placeholder": "如《破晓录》，留空由 AI 起名", "maxLength": 60
                            }, [])
                        ]), h("div", {
                            "class": styles.field
                        }, [
                            h("span", {
                                "class": styles.fieldLabel
                            }, ["题材"]), h("div", {
                                "class": styles.lockedGenre
                            }, [genreLabel.value]), groupCatalog(catalog.value).map(({ group, items }) => (h("div", {
                                "key": group, "class": styles.genreGroup
                            }, [
                                h("div", {
                                    "class": styles.genreGroupTitle
                                }, [
                                    "主题材 · ", group
                                ]), h("div", {
                                    "class": styles.genreChips
                                }, [items.map((item) => (h("button", {
                                        "key": item.id, "type": "button", "disabled": busy.value === 'restore' || pid.value !== null, "class": styles.chip + (primaryId.value === item.id ? ' ' + styles.chipOn : ''), "onClick": () => pickPrimary(item.id)
                                    }, [item.name])))])
                            ]))), h("div", {
                                "class": styles.genreGroup
                            }, [
                                h("div", {
                                    "class": styles.genreGroupTitle
                                }, ["辅题材（可选，须先选主题材）"]), groupCatalog(catalog.value).map(({ group, items }) => (h("div", {
                                    "key": `sec-${group}`
                                }, [
                                    h("div", {
                                        "class": styles.genreSubTitle
                                    }, [group]), h("div", {
                                        "class": styles.genreChips
                                    }, [items.map((item) => (h("button", {
                                            "key": item.id, "type": "button", "disabled": busy.value === 'restore' || pid.value !== null || !primaryId.value || item.id === primaryId.value, "class": styles.chip + (secondaryId.value === item.id ? ' ' + styles.chipOn : ''), "onClick": () => pickSecondary(item.id)
                                        }, [item.name])))])
                                ])))
                            ]), h("p", {
                                "class": styles.hint
                            }, ["题材字段由平台统一发布，新作品使用所选题材的最新版本。"])
                        ]), h("label", {
                            "class": styles.field
                        }, [
                            h("span", {
                                "class": styles.fieldLabel
                            }, ["文风（可选）"]), h("select", {
                                "class": "input", "aria-label": "文风", "value": styleItemId.value, "disabled": busy.value === 'restore' || pid.value !== null, "onChange": (e: Event) => styleItemId.value = (e.target as HTMLInputElement).value
                            }, [
                                h("option", {
                                    "value": ""
                                }, ["不指定"]), styleItems.value.map((item) => (h("option", {
                                    "key": item.id, "value": item.id
                                }, [
                                    item.name, item.builtin ? '（内置）' : '（我的）'
                                ])))
                            ])
                        ]), isShort.value ? (h(Fragment, null, [
                            h("label", {
                                "class": styles.field
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["章数（1–10）"]), h("input", {
                                    "class": "input", "type": "number", "min": SHORT_CHAPTER_MIN, "max": SHORT_CHAPTER_MAX, "value": outlineCount.value, "disabled": busy.value === 'restore' || pid.value !== null, "onInput": (e: Event) => outlineCount.value = (e.target as HTMLInputElement).value
                                }, [])
                            ]), h("label", {
                                "class": styles.field
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, [
                                    "每章字数（", SHORT_CHARS_MIN, "–", SHORT_CHARS_MAX, "）"
                                ]), h("input", {
                                    "class": "input", "type": "number", "min": SHORT_CHARS_MIN, "max": SHORT_CHARS_MAX, "step": 500, "value": shortChars.value, "disabled": busy.value === 'restore' || pid.value !== null, "onInput": (e: Event) => shortChars.value = (e.target as HTMLInputElement).value
                                }, [])
                            ])
                        ])) : (h("label", {
                            "class": styles.field
                        }, [
                            h("span", {
                                "class": styles.fieldLabel
                            }, ["每章目标字数（500–20000）"]), h("input", {
                                "class": "input", "type": "number", "min": 500, "max": 20000, "step": 100, "value": targetWords.value, "disabled": busy.value === 'restore' || pid.value !== null, "onInput": (e: Event) => targetWords.value = (e.target as HTMLInputElement).value
                            }, [])
                        ])), h("label", {
                            "class": styles.field
                        }, [
                            h("span", {
                                "class": styles.fieldLabel
                            }, ["创作简报"]), h("textarea", {
                                "class": "textarea", "rows": 5, "value": premise.value, "disabled": busy.value === 'restore', "onInput": (e: Event) => premise.value = (e.target as HTMLInputElement).value, "placeholder": '写你的脑洞，越具体越好：题材、主角身份、金手指、世界观、关键冲突或想要的结局。\n' +
                                    '例：都市修仙，主角是个程序员，靠解析代码的方式理解修仙功法。\n' +
                                    '或：被逐出宗门的外门弟子，带着一枚能推演因果的玉佩，从北境一路查清父母死因并证道。'
                            }, [])
                        ]), h("div", {
                            "class": styles.saveRow
                        }, [h("button", {
                                "type": "button", "class": "btn btn-primary", "disabled": busy.value !== null || pid.value !== null || resumeId.value !== null, "onClick": createAndDraft
                            }, [pid.value ? '作品草稿已保存' : busy.value === 'create' ? '创建中…' : '创建作品']), !isShort.value && pid.value && h('button', { type: 'button', class: 'btn btn-primary', disabled: busy.value !== null, onClick: () => { step.value = 1; } }, '下一步')])
                    ]), pid.value && (h("section", {
                        "class": `panel ${styles.section}`, hidden: !isShort.value && step.value !== 1
                    }, [
                        h("div", {
                            "class": styles.draftHead
                        }, [
                            h("h2", {
                                "class": styles.sectionTitle, tabindex: -1
                            }, ["② 设定骨架草稿"]), h("button", {
                                "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null || setupConfirmed.value, "onClick": () => regenerate(pid.value!)
                            }, [busy.value === 'draft' ? '重新生成中…' : '重新生成草稿'])
                        ]), isShort.value && draftError.value && (h("div", {
                            "class": "banner banner-warning"
                        }, [
                            "LLM 生成降级：", draftError.value, "（可手填后确认）"
                        ])), section.value === null ? (h("div", {
                            "class": "empty"
                        }, ["正在生成设定草稿…"])) : emptyDraft.value ? (h("div", {
                            "class": "empty"
                        }, ["草稿为空（LLM 未产出），请手动填写以下分区。"])) : null, section.value !== null && (h("div", null, [
                            showRealmOrder.value && (h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["境界体系（每行一阶）"]), h((StructuredTextField<string[]>), {
                                    "className": "textarea", "rows": Math.max(3, sec.value.realm_order.length), "value": sec.value.realm_order, "format": arrayToLines, "parse": linesToArray, "onChange": (value) => updateSection({
                                        realm_order: value
                                    })
                                })
                            ])), h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["世界观规则（每行「键：值」）"]), h((StructuredTextField<Record<string, string>>), {
                                    "className": "textarea", "rows": Math.max(3, Object.keys(sec.value.world_rules).length), "value": sec.value.world_rules, "format": worldRulesToText, "parse": textToWorldRules, "onChange": (value) => updateSection({
                                        world_rules: value
                                    })
                                })
                            ]), h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["硬约束（每行一条）"]), h((StructuredTextField<string[]>), {
                                    "className": "textarea", "rows": Math.max(3, sec.value.hard_constraints.length), "value": sec.value.hard_constraints, "format": arrayToLines, "parse": linesToArray, "onChange": (value) => updateSection({
                                        hard_constraints: value
                                    })
                                })
                            ]), h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["势力"]), sec.value.forces.map((f, i) => (h("div", {
                                    "key": i, "class": styles.rowGrid
                                }, [
                                    h("input", {
                                        "class": "input", "placeholder": "名称", "value": f.name, "onInput": (e: Event) => updateSection({
                                            forces: sec.value.forces.map((x, j) => (j === i ? {
                                                ...x, name: (e.target as HTMLInputElement).value
                                            } : x))
                                        })
                                    }, []), h("input", {
                                        "class": "input", "placeholder": "立场", "value": f.stance, "onInput": (e: Event) => updateSection({
                                            forces: sec.value.forces.map((x, j) => j === i ? {
                                                ...x, stance: (e.target as HTMLInputElement).value
                                            } : x)
                                        })
                                    }, []), h("button", {
                                        "type": "button", "class": "btn btn-quiet", "onClick": () => updateSection({
                                            forces: sec.value.forces.filter((_, j) => j !== i)
                                        })
                                    }, ["删"])
                                ]))), h("button", {
                                    "type": "button", "class": "btn btn-quiet", "onClick": () => updateSection({
                                        forces: [
                                            ...sec.value.forces,
                                            {
                                                name: '', stance: '', resources: []
                                            }
                                        ]
                                    })
                                }, ["+ 添加势力"])
                            ]), h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["核心人物"]), sec.value.characters.map((c, i) => (h("div", {
                                    "key": i, "class": styles.charGrid
                                }, [
                                    h("input", {
                                        "class": "input", "placeholder": "姓名", "value": c.name, "onInput": (e: Event) => updateSection({
                                            characters: sec.value.characters.map((x, j) => j === i ? {
                                                ...x, name: (e.target as HTMLInputElement).value
                                            } : x)
                                        })
                                    }, []), (powerScaling.value !== false || c.realm_cap.trim() !== '') && (h("input", {
                                        "class": "input", "placeholder": "境界上限", "value": c.realm_cap, "onInput": (e: Event) => updateSection({
                                            characters: sec.value.characters.map((x, j) => j === i ? {
                                                ...x, realm_cap: (e.target as HTMLInputElement).value
                                            } : x)
                                        })
                                    }, [])), h("input", {
                                        "class": "input", "placeholder": "出身", "value": c.origin, "onInput": (e: Event) => updateSection({
                                            characters: sec.value.characters.map((x, j) => j === i ? {
                                                ...x, origin: (e.target as HTMLInputElement).value
                                            } : x)
                                        })
                                    }, []), h("button", {
                                        "type": "button", "class": "btn btn-quiet", "onClick": () => updateSection({
                                            characters: sec.value.characters.filter((_, j) => j !== i)
                                        })
                                    }, ["删"])
                                ]))), h("button", {
                                    "type": "button", "class": "btn btn-quiet", "onClick": () => updateSection({
                                        characters: [
                                            ...sec.value.characters,
                                            {
                                                name: '', role: '', race: '', origin: '', realm_cap: '', personality: ''
                                            }
                                        ]
                                    })
                                }, ["+ 添加人物"])
                            ]), h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["关键地点"]), sec.value.locations.map((l, i) => (h("div", {
                                    "key": i, "class": styles.rowGrid
                                }, [
                                    h("input", {
                                        "class": "input", "placeholder": "名称", "value": l.name, "onInput": (e: Event) => updateSection({
                                            locations: sec.value.locations.map((x, j) => j === i ? {
                                                name: (e.target as HTMLInputElement).value
                                            } : x)
                                        })
                                    }, []), h("button", {
                                        "type": "button", "class": "btn btn-quiet", "onClick": () => updateSection({
                                            locations: sec.value.locations.filter((_, j) => j !== i)
                                        })
                                    }, ["删"])
                                ]))), h("button", {
                                    "type": "button", "class": "btn btn-quiet", "onClick": () => updateSection({
                                        locations: [
                                            ...sec.value.locations,
                                            {
                                                name: ''
                                            }
                                        ]
                                    })
                                }, ["+ 添加地点"])
                            ]), h("div", {
                                "class": styles.saveRow
                            }, [!isShort.value && h('button', { type: 'button', class: 'btn btn-quiet', disabled: busy.value !== null, onClick: () => { step.value = 0; } }, '上一步'), h("button", {
                                    "type": "button", "class": "btn btn-primary", "disabled": busy.value !== null || emptyDraft.value, "onClick": confirm
                                }, [busy.value === 'confirm' ? '确认中…' : isShort.value ? '确认落库' : '确认设定，下一步'])])
                        ]))
                    ])), pid.value && (h("section", {
                        "class": `panel ${styles.section}`, hidden: !isShort.value && step.value !== 2
                    }, [
                        h("div", {
                            "class": styles.draftHead
                        }, [
                            h("h2", {
                                "class": styles.sectionTitle, tabindex: -1
                            }, ["③ 整书大纲"]), h("button", {
                                "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null, "onClick": () => pid.value && generateOutline(pid.value)
                            }, [busy.value === 'outline-draft' ? '生成中…' : outline.value ? '重新生成大纲' : '生成大纲'])
                        ]), isShort.value && outlineError.value && (h("div", {
                            "class": "banner banner-warning"
                        }, [
                            "LLM 生成降级：", outlineError.value, "（可手填后确认）"
                        ])), h("div", {
                            "class": styles.block
                        }, [
                            h("span", {
                                "class": styles.fieldLabel
                            }, [isShort.value ? `大致章节数（${SHORT_CHAPTER_MIN}–${SHORT_CHAPTER_MAX}）`
                                    : '大致章节数（50–1000）']), h("input", {
                                "class": "input", "type": "number", "min": isShort.value ? SHORT_CHAPTER_MIN : 50, "max": isShort.value ? SHORT_CHAPTER_MAX : 1000, "value": outlineCount.value, "onInput": (e: Event) => outlineCount.value = (e.target as HTMLInputElement).value
                            }, [])
                        ]), isShort.value && compressedChars.value !== null && (h("div", {
                            "class": "banner banner-warning"
                        }, [
                            "每章字数已按全篇 ", SHORT_TOTAL_MAX, " 字上限归一为每章 ", compressedChars.value, " 字，生成时按这个数走。"
                        ])), isShort.value && outlineWarning.value && (h("div", {
                            "class": "banner banner-warning"
                        }, [
                            "方案审纲留痕：", outlineWarning.value
                        ])), h("details", {
                            "class": styles.block
                        }, [
                            h("summary", {
                                "class": styles.fieldLabel
                            }, ["补充故事线（可选，不填则由 Planner 自动推导）"]), h("textarea", {
                                "class": "textarea", "rows": 2, "value": outlineStoryline.value, "onInput": (e: Event) => outlineStoryline.value = (e.target as HTMLInputElement).value, "placeholder": "如：前期入宗立身，中期追查玉佩真相，后期宗门惊变、决战北境。"
                            }, [])
                        ]), outline.value && (h("div", {
                            "class": styles.outlineStack
                        }, [
                            h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["全书 Objective（终局，可验证状态）"]), h("textarea", {
                                    "class": `textarea ${styles.growArea}`, "rows": 4, "value": outline.value.objective, "onInput": (e: Event) => updateOutline({
                                        objective: (e.target as HTMLInputElement).value
                                    }), "placeholder": "如：从杂役修士成为宗门长老并公开父辈冤案真相"
                                }, [])
                            ]), isShort.value && (h("div", {
                                "class": styles.block
                            }, [
                                h("span", {
                                    "class": styles.fieldLabel
                                }, ["逐章方案（短篇唯一一卷；写手照它一次成稿，章号不可改）"]), outline.value.volumes.length === 0 && (h("div", {
                                    "class": "empty"
                                }, ["方案为空（LLM 未产出），请点上方「重新生成大纲」。"])), outline.value.volumes.map((v, vi) => (h("div", {
                                    "key": vi, "class": styles.block
                                }, [
                                    h("label", {
                                        "class": styles.field
                                    }, [
                                        h("span", {
                                            "class": styles.fieldLabel
                                        }, ["篇名"]), h("input", {
                                            "class": "input", "placeholder": "全篇 · 篇名", "value": v.title, "onInput": (e: Event) => updateVolume(vi, {
                                                title: (e.target as HTMLInputElement).value
                                            })
                                        }, [])
                                    ]), h("label", {
                                        "class": styles.field
                                    }, [
                                        h("span", {
                                            "class": styles.fieldLabel
                                        }, ["主题"]), h("input", {
                                            "class": "input", "placeholder": "一句话主题", "value": v.theme ?? '', "onInput": (e: Event) => updateVolume(vi, {
                                                theme: (e.target as HTMLInputElement).value
                                            })
                                        }, [])
                                    ]), h("label", {
                                        "class": styles.field
                                    }, [
                                        h("span", {
                                            "class": styles.fieldLabel
                                        }, ["全篇目标（结局时主角必须达到的可验证状态）"]), h("textarea", {
                                            "class": `textarea ${styles.growArea}`, "rows": 3, "value": v.goal, "onInput": (e: Event) => updateVolume(vi, {
                                                goal: (e.target as HTMLInputElement).value
                                            })
                                        }, [])
                                    ]), (v.chapters ?? []).map((c, ci) => {
                                        const seq = c.chapter_seq ?? ci + 1;
                                        return (h("div", {
                                            "key": ci, "class": styles.stageFold
                                        }, [h("div", {
                                                "class": styles.block
                                            }, [
                                                h("div", {
                                                    "class": styles.foldTitle
                                                }, [
                                                    "第", seq, " 章", c.title ? ` · ${c.title}` : ''
                                                ]), h("label", {
                                                    "class": styles.field
                                                }, [
                                                    h("span", {
                                                        "class": styles.fieldLabel
                                                    }, [
                                                        "第 ", seq, " 章 · 章节标题"
                                                    ]), h("input", {
                                                        "class": "input", "placeholder": "像平台内容，不要文艺化总结", "value": c.title ?? '', "onInput": (e: Event) => updateShortChapter(vi, ci, {
                                                            title: (e.target as HTMLInputElement).value
                                                        })
                                                    }, [])
                                                ]), h("label", {
                                                    "class": styles.field
                                                }, [
                                                    h("span", {
                                                        "class": styles.fieldLabel
                                                    }, [
                                                        "第 ", seq, " 章 · 本章目标"
                                                    ]), h("textarea", {
                                                        "class": "textarea", "rows": 2, "placeholder": "本章结束时必须达到的可验证状态", "value": c.goal ?? '', "onInput": (e: Event) => updateShortChapter(vi, ci, {
                                                            goal: (e.target as HTMLInputElement).value
                                                        })
                                                    }, [])
                                                ]), h("label", {
                                                    "class": styles.field
                                                }, [
                                                    h("span", {
                                                        "class": styles.fieldLabel
                                                    }, [
                                                        "第 ", seq, " 章 · 关键场面"
                                                    ]), h("input", {
                                                        "class": "input", "placeholder": "谁 + 在何处 + 做什么", "value": c.key_scene ?? '', "onInput": (e: Event) => updateShortChapter(vi, ci, {
                                                            key_scene: (e.target as HTMLInputElement).value
                                                        })
                                                    }, [])
                                                ]), h("label", {
                                                    "class": styles.field
                                                }, [
                                                    h("span", {
                                                        "class": styles.fieldLabel
                                                    }, [
                                                        "第 ", seq, " 章 · 角色动作"
                                                    ]), h("input", {
                                                        "class": "input", "placeholder": "主角主动做出的选择或行动", "value": c.character_action ?? '', "onInput": (e: Event) => updateShortChapter(vi, ci, {
                                                            character_action: (e.target as HTMLInputElement).value
                                                        })
                                                    }, [])
                                                ]), h("label", {
                                                    "class": styles.field
                                                }, [
                                                    h("span", {
                                                        "class": styles.fieldLabel
                                                    }, [
                                                        "第 ", seq, " 章 · 压力升级或回报"
                                                    ]), h("input", {
                                                        "class": "input", "placeholder": "本章的压力升级或回报", "value": c.escalation_or_payoff ?? '', "onInput": (e: Event) => updateShortChapter(vi, ci, {
                                                            escalation_or_payoff: (e.target as HTMLInputElement).value
                                                        })
                                                    }, [])
                                                ]), h("label", {
                                                    "class": styles.field
                                                }, [
                                                    h("span", {
                                                        "class": styles.fieldLabel
                                                    }, [
                                                        "第 ", seq, " 章 · 章尾钩子"
                                                    ]), h("input", {
                                                        "class": "input", "placeholder": "让读者接着读下一章的那个具体理由", "value": c.hook ?? '', "onInput": (e: Event) => updateShortChapter(vi, ci, {
                                                            hook: (e.target as HTMLInputElement).value
                                                        })
                                                    }, [])
                                                ])
                                            ])]));
                                    })
                                ])))
                            ])), !isShort.value && outline.value.volumes.map((v, vi) => {
                                const volumeRange = chapterRangeLabel(v.chapter_start, v.chapter_end);
                                const stageCount = (v.stages ?? []).length;
                                return (h("details", {
                                    "key": vi, "class": styles.volumeFold
                                }, [
                                    h("summary", {
                                        "class": styles.foldSummary
                                    }, [
                                        h("span", {
                                            "class": styles.foldTitle
                                        }, [
                                            "第", vi + 1, "卷大纲", v.title ? ` · ${v.title}` : ''
                                        ]), h("span", {
                                            "class": styles.foldMeta
                                        }, [
                                            volumeRange || '章区间未定', stageCount ? ` · ${stageCount} 段` : ''
                                        ])
                                    ]), h("div", {
                                        "class": styles.foldBody
                                    }, [
                                        h("label", {
                                            "class": styles.field
                                        }, [
                                            h("span", {
                                                "class": styles.fieldLabel
                                            }, ["卷名"]), h("input", {
                                                "class": "input", "placeholder": "卷名", "value": v.title, "onInput": (e: Event) => updateVolume(vi, {
                                                    title: (e.target as HTMLInputElement).value
                                                })
                                            }, [])
                                        ]), h("label", {
                                            "class": styles.field
                                        }, [
                                            h("span", {
                                                "class": styles.fieldLabel
                                            }, ["主题"]), h("input", {
                                                "class": "input", "value": v.theme ?? '', "placeholder": "一句话主题", "onInput": (e: Event) => updateVolume(vi, {
                                                    theme: (e.target as HTMLInputElement).value
                                                })
                                            }, [])
                                        ]), h("div", {
                                            "class": styles.rangeRow
                                        }, [
                                            h("label", {
                                                "class": styles.field
                                            }, [
                                                h("span", {
                                                    "class": styles.fieldLabel
                                                }, ["起始章"]), h("input", {
                                                    "class": "input", "type": "number", "min": 1, "placeholder": "起始章", "value": v.chapter_start ?? '', "onInput": (e: Event) => updateVolume(vi, {
                                                        chapter_start: Number((e.target as HTMLInputElement).value) || undefined
                                                    })
                                                }, [])
                                            ]), h("label", {
                                                "class": styles.field
                                            }, [
                                                h("span", {
                                                    "class": styles.fieldLabel
                                                }, ["结束章"]), h("input", {
                                                    "class": "input", "type": "number", "min": 1, "placeholder": "结束章", "value": v.chapter_end ?? '', "onInput": (e: Event) => updateVolume(vi, {
                                                        chapter_end: Number((e.target as HTMLInputElement).value) || undefined
                                                    })
                                                }, [])
                                            ])
                                        ]), h("label", {
                                            "class": styles.field
                                        }, [
                                            h("span", {
                                                "class": styles.fieldLabel
                                            }, ["卷目标"]), h("textarea", {
                                                "class": `textarea ${styles.growArea}`, "rows": 3, "placeholder": "本卷结束时主角须达到的可验证状态", "value": v.goal, "onInput": (e: Event) => updateVolume(vi, {
                                                    goal: (e.target as HTMLInputElement).value
                                                })
                                            }, [])
                                        ]), h("label", {
                                            "class": styles.field
                                        }, [
                                            h("span", {
                                                "class": styles.fieldLabel
                                            }, ["关键结果 KR（每行一条）"]), h((StructuredTextField<string[]>), {
                                                "className": `textarea ${styles.growArea}`, "rows": 4, "placeholder": "每行一条可验证结果", "value": v.key_results ?? [], "format": arrayToLines, "parse": linesToArray, "onChange": (value) => updateVolume(vi, {
                                                    key_results: value
                                                })
                                            })
                                        ]), h("label", {
                                            "class": styles.field
                                        }, [
                                            h("span", {
                                                "class": styles.fieldLabel
                                            }, ["卷末不可逆事件"]), h("textarea", {
                                                "class": `textarea ${styles.growArea}`, "rows": 3, "placeholder": "只写事件，不写第几章", "value": v.end_event ?? '', "onInput": (e: Event) => updateVolume(vi, {
                                                    end_event: (e.target as HTMLInputElement).value
                                                })
                                            }, [])
                                        ]), (v.stages ?? []).map((s, si) => {
                                            const stageRange = chapterRangeLabel(s.chapter_start, s.chapter_end);
                                            return (h("details", {
                                                "key": si, "class": styles.stageFold
                                            }, [
                                                h("summary", {
                                                    "class": styles.foldSummary
                                                }, [
                                                    h("span", {
                                                        "class": styles.foldTitle
                                                    }, [s.name || `第 ${si + 1} 段`]), h("span", {
                                                        "class": styles.foldMeta
                                                    }, [stageRange || '章区间未定'])
                                                ]), h("div", {
                                                    "class": styles.foldBody
                                                }, [
                                                    h("div", {
                                                        "class": styles.stageHead
                                                    }, [
                                                        h("label", {
                                                            "class": styles.field
                                                        }, [
                                                            h("span", {
                                                                "class": styles.fieldLabel
                                                            }, ["阶段名"]), h("input", {
                                                                "class": "input", "placeholder": "前期 / 中期 / 后期", "value": s.name, "onInput": (e: Event) => updateStage(vi, si, {
                                                                    name: (e.target as HTMLInputElement).value
                                                                })
                                                            }, [])
                                                        ]), h("button", {
                                                            "type": "button", "class": "btn btn-quiet", "onClick": () => removeStage(vi, si)
                                                        }, ["删除本段"])
                                                    ]), h("div", {
                                                        "class": styles.rangeRow
                                                    }, [
                                                        h("label", {
                                                            "class": styles.field
                                                        }, [
                                                            h("span", {
                                                                "class": styles.fieldLabel
                                                            }, ["起始章"]), h("input", {
                                                                "class": "input", "type": "number", "min": 1, "placeholder": "起始章", "value": s.chapter_start ?? '', "onInput": (e: Event) => updateStage(vi, si, {
                                                                    chapter_start: Number((e.target as HTMLInputElement).value) || undefined
                                                                })
                                                            }, [])
                                                        ]), h("label", {
                                                            "class": styles.field
                                                        }, [
                                                            h("span", {
                                                                "class": styles.fieldLabel
                                                            }, ["结束章"]), h("input", {
                                                                "class": "input", "type": "number", "min": 1, "placeholder": "结束章", "value": s.chapter_end ?? '', "onInput": (e: Event) => updateStage(vi, si, {
                                                                    chapter_end: Number((e.target as HTMLInputElement).value) || undefined
                                                                })
                                                            }, [])
                                                        ])
                                                    ]), h("label", {
                                                        "class": styles.field
                                                    }, [
                                                        h("span", {
                                                            "class": styles.fieldLabel
                                                        }, ["阶段目标"]), h("textarea", {
                                                            "class": `textarea ${styles.growArea}`, "rows": 3, "placeholder": "约 30 章一段，写作时会注入当前阶段", "value": s.goal, "onInput": (e: Event) => updateStage(vi, si, {
                                                                goal: (e.target as HTMLInputElement).value
                                                            })
                                                        }, [])
                                                    ]), h("label", {
                                                        "class": styles.field
                                                    }, [
                                                        h("span", {
                                                            "class": styles.fieldLabel
                                                        }, ["阶段节拍（每行一条）"]), h((StructuredTextField<string[]>), {
                                                            "className": `textarea ${styles.growArea}`, "rows": Math.max(4, s.beats?.length ?? 0), "placeholder": "谁 + 在何处 + 做什么 + 导致什么", "value": s.beats ?? [], "format": arrayToLines, "parse": linesToArray, "onChange": (value) => updateStage(vi, si, {
                                                                beats: value
                                                            })
                                                        })
                                                    ])
                                                ])
                                            ]));
                                        }), h("button", {
                                            "type": "button", "class": "btn btn-quiet", "onClick": () => addStage(vi)
                                        }, ["+ 本卷加一段"])
                                    ])
                                ]));
                            }), h("div", {
                                "class": styles.saveRow
                            }, [
                                !isShort.value && (h("button", {
                                    "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null, "onClick": addVolume
                                }, ["+ 新增一卷"])), !isShort.value && h('button', { type: 'button', class: 'btn btn-quiet', disabled: busy.value !== null, onClick: () => { step.value = 1; } }, '上一步'), h("button", {
                                    "type": "button", "class": "btn btn-primary", "disabled": busy.value !== null || !outline.value.objective.trim() || outline.value.volumes.length === 0 || (!setupConfirmed.value && emptyDraft.value), "onClick": () => { resourceError.value = null; resourceOpen.value = true; }
                                }, ['选择资源并完成建书']), h("button", {
                                    "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null, "onClick": leaveDraft
                                }, ["保留草稿，返回作品库"])
                            ])
                        ])), !outline.value && (h("div", {
                            "class": styles.saveRow
                        }, [h("button", {
                                "type": "button", "class": "btn btn-quiet", "disabled": busy.value !== null, "onClick": leaveDraft
                            }, ["保留草稿，返回作品库"])]))
                    ]))
                ])])
        ]));
    }
});

</script>
