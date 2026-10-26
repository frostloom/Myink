<script lang="ts">
import { defineComponent, h, Fragment, ref, shallowRef, computed, watch, onScopeDispose } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ResourceUpdates from "../components/ResourceUpdates.vue";
import type { ResourceUpdateGate } from "../components/ResourceUpdates.vue";
import AuditPanel from "../components/AuditPanel.vue";
import CandidatePanel from "../components/CandidatePanel.vue";
import type { ReleaseTarget } from "../components/CandidatePanel.vue";
import ChapterEditor from "../components/ChapterEditor.vue";
import ChapterPlanPanel from "../components/ChapterPlanPanel.vue";
import ChapterList from "../components/ChapterList.vue";
import GenerationPanel from "../components/GenerationPanel.vue";
import LessonsPanel from "../components/LessonsPanel.vue";
import ProjectRail from "../components/ProjectRail.vue";
import RingProgress from "../components/RingProgress.vue";
import TaskTimeline from "../components/TaskTimeline.vue";
import StreamingChapterView from "../components/StreamingChapterView.vue";
import { useAuth } from "../authContext";
import { useTaskEvents } from "../composables/useTaskEvents";
import { api, ApiError } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import { nodeLabel } from "../../../src/lib/labels";
import { isProjectDraft, projectHref } from "../../../src/lib/projectCreation";
import { readSidePanelOpen, writeSidePanelOpen } from "../../../src/lib/sidePanel";
import { clearActiveWrite, readActiveWrite, writeActiveWrite } from "../../../src/lib/activeWrite";
import { liveStageNode, shortStageProgress } from "../../../src/lib/taskFlow";
import { chapterToOpenForPendingTask, latestActiveGenerationTask, latestChapterAwaitingReview, latestGenerationTask, nodesForChapter, runsForChapter } from "../../../src/lib/taskChapter";
import type { ChapterMeta, MemoryCandidate, Project, WritingMode } from "../../../src/types";
import styles from "../../../src/pages/WorkspacePage.module.css";
export const WorkspacePage = defineComponent({
    name: "WorkspacePage",
    props: [],
    setup() {
        const route = useRoute();
        const router = useRouter();
        const projectId = computed(() => String(route.params.projectId ?? ''));
        const resourceGate = shallowRef<ResourceUpdateGate | null>(null);
        const { logout, session } = useAuth();
        const accountId = computed(() => session.value?.userId ?? '');
        let disposed = false;
        let exportVersion = 0;
        let workspaceVersion = 0;
        watch([accountId, projectId], () => { workspaceVersion += 1 }, { flush: 'sync' });
        onScopeDispose(() => { disposed = true; exportVersion += 1 });
        const navigate = (path: string, opts?: {
            replace?: boolean;
            state?: import('vue-router').HistoryState;
        }) => { const target=router.resolve(path);const to={path:target.path,query:target.query,hash:target.hash,state:opts?.state,force:opts?.replace===true}; return opts?.replace ? router.replace(to) : router.push(to) };
        const searchParams = computed(() => new URLSearchParams(route.query as Record<string, string>));
        const setSearchParams = (query: Record<string, string>, opts?: {
            replace?: boolean;
        }) => opts?.replace ? router.replace({ query }) : router.push({ query });
        const projects = ref<Project[]>([]), setProjects = (next: typeof projects.value | ((current: typeof projects.value) => typeof projects.value)) => projects.value = typeof next === "function" ? next(projects.value) : next;
        const chapters = ref<ChapterMeta[]>([]), setChapters = (next: typeof chapters.value | ((current: typeof chapters.value) => typeof chapters.value)) => chapters.value = typeof next === "function" ? next(chapters.value) : next;
        const candidates = ref<MemoryCandidate[]>([]), setCandidates = (next: typeof candidates.value | ((current: typeof candidates.value) => typeof candidates.value)) => candidates.value = typeof next === "function" ? next(candidates.value) : next;
        const candidateReferenceNames = ref<Record<string, string>>({}), setCandidateReferenceNames = (next: typeof candidateReferenceNames.value | ((current: typeof candidateReferenceNames.value) => typeof candidateReferenceNames.value)) => candidateReferenceNames.value = typeof next === "function" ? next(candidateReferenceNames.value) : next;
        const selectedCid = ref<string | null>(null), setSelectedCid = (next: typeof selectedCid.value | ((current: typeof selectedCid.value) => typeof selectedCid.value)) => selectedCid.value = typeof next === "function" ? next(selectedCid.value) : next;
        const activeTaskId = ref<string | null>(null), setActiveTaskId = (next: typeof activeTaskId.value | ((current: typeof activeTaskId.value) => typeof activeTaskId.value)) => activeTaskId.value = typeof next === "function" ? next(activeTaskId.value) : next;
        const batchTotal = ref<number | null>(null), setBatchTotal = (next: typeof batchTotal.value | ((current: typeof batchTotal.value) => typeof batchTotal.value)) => batchTotal.value = typeof next === "function" ? next(batchTotal.value) : next;
        const activeChapterSeq = ref<number | null>(null), setActiveChapterSeq = (next: typeof activeChapterSeq.value | ((current: typeof activeChapterSeq.value) => typeof activeChapterSeq.value)) => activeChapterSeq.value = typeof next === "function" ? next(activeChapterSeq.value) : next;
        const error = ref<string | null>(null), setError = (next: typeof error.value | ((current: typeof error.value) => typeof error.value)) => error.value = typeof next === "function" ? next(error.value) : next;
        const refreshTick = ref(0), setRefreshTick = (next: typeof refreshTick.value | ((current: typeof refreshTick.value) => typeof refreshTick.value)) => refreshTick.value = typeof next === "function" ? next(refreshTick.value) : next;
        const exporting = ref(false), setExporting = (next: typeof exporting.value | ((current: typeof exporting.value) => typeof exporting.value)) => exporting.value = typeof next === "function" ? next(exporting.value) : next;
        watch([accountId, projectId], () => { exportVersion += 1; setExporting(false) }, { flush: 'sync' });
        const deleting = ref(false), setDeleting = (next: typeof deleting.value | ((current: typeof deleting.value) => typeof deleting.value)) => deleting.value = typeof next === "function" ? next(deleting.value) : next;
        const releaseTarget = ref<ReleaseTarget | null>(null), setReleaseTarget = (next: typeof releaseTarget.value | ((current: typeof releaseTarget.value) => typeof releaseTarget.value)) => releaseTarget.value = typeof next === "function" ? next(releaseTarget.value) : next;
        const releaseResumeKey = ref<number | null>(null), setReleaseResumeKey = (next: typeof releaseResumeKey.value | ((current: typeof releaseResumeKey.value) => typeof releaseResumeKey.value)) => releaseResumeKey.value = typeof next === "function" ? next(releaseResumeKey.value) : next;
        const centerView = ref<'plan' | 'write'>('write'), setCenterView = (next: typeof centerView.value | ((current: typeof centerView.value) => typeof centerView.value)) => centerView.value = typeof next === "function" ? next(centerView.value) : next;
        const sidePanelOpen = ref(readSidePanelOpen()), setSidePanelOpen = (next: typeof sidePanelOpen.value | ((current: typeof sidePanelOpen.value) => typeof sidePanelOpen.value)) => sidePanelOpen.value = typeof next === "function" ? next(sidePanelOpen.value) : next;
        const shortStartFailed = ref(false), setShortStartFailed = (next: typeof shortStartFailed.value | ((current: typeof shortStartFailed.value) => typeof shortStartFailed.value)) => shortStartFailed.value = typeof next === "function" ? next(shortStartFailed.value) : next;
        const shortSubmitting = ref(false), setShortSubmitting = (next: typeof shortSubmitting.value | ((current: typeof shortSubmitting.value) => typeof shortSubmitting.value)) => shortSubmitting.value = typeof next === "function" ? next(shortSubmitting.value) : next;
        const shortSubmitRef = shallowRef(false);
        const shortRequestVersion = shallowRef(0);
        const shortHistory = ref<{
            projectId: string;
            status: 'loading' | 'ready' | 'failed';
        }>({ projectId: projectId.value, status: 'loading' }), setShortHistory = (next: typeof shortHistory.value | ((current: typeof shortHistory.value) => typeof shortHistory.value)) => shortHistory.value = typeof next === "function" ? next(shortHistory.value) : next;
        const shortHistoryReload = ref(0), setShortHistoryReload = (next: typeof shortHistoryReload.value | ((current: typeof shortHistoryReload.value) => typeof shortHistoryReload.value)) => shortHistoryReload.value = typeof next === "function" ? next(shortHistoryReload.value) : next;
        const taskStartVersion = shallowRef(0);
        const shortStarted = shallowRef(false);
        const chapterMaterializeVersion = shallowRef(0);
        const projectIdRef = shallowRef(projectId.value);
        const activeTaskIdRef = shallowRef<(string | null) | null>(null);
        const selectedCidRef = shallowRef<(string | null) | null>(null);
        const selectedChapterSeqRef = shallowRef<(number | null) | null>(null);
        const latestPlanArtifactRef = shallowRef<(string | null) | null>(null);
        const latestWriteArtifactRef = shallowRef<(string | null) | null>(null);
        watch(projectId, value => { projectIdRef.value = value }, { immediate: true, flush: 'sync' });
        // 只允许本页刚发起/续跑的任务在终态时自动跳章一次。历史任务恢复为 terminal 后
        // 不能持续把用户从其他章节拉回待确认章。
        const pendingAutoOpen = shallowRef<({
            taskId: string;
            chapterSeq: number | null;
        } | null) | null>(null);
        const project = computed(() => projects.value.find((p) => p.id === projectId.value));
        const isShortBook = computed(() => project.value?.form === 'short');
        const shortHistoryStatus = computed(() => shortHistory.value.projectId === projectId.value ? shortHistory.value.status : 'loading');
        const allowMemoryCorrection = computed(() => project.value !== undefined && project.value.form !== 'short');
        const showPlanView = computed(() => !isShortBook.value && centerView.value === 'plan');
        // 建书对话页确认完跳进来时带了这个 state：那次 commit 只落书不出稿，入队归本页。
        const handoverState = shallowRef(router.options.history.state ?? {});
        watch(() => route.fullPath, () => { handoverState.value = router.options.history.state ?? {}; });
        const location = computed(() => ({ pathname: route.path, state: handoverState.value }));
        const handover = computed(() => (location.value.state ?? {}) as {
            beginShortWriting?: boolean;
            planWarning?: string | null;
        });
        watch(() => [activeTaskId.value], (_next, _prev, _onCleanup) => {
            activeTaskIdRef.value = activeTaskId.value;
        }, { immediate: true, flush: "post" });
        watch(() => [chapters.value, selectedCid.value], (_next, _prev, _onCleanup) => {
            if (selectedCidRef.value === selectedCid.value)
                return;
            const selected = chapters.value.find((chapter) => chapter.id === selectedCid.value);
            const changedChapter = selectedChapterSeqRef.value !== (selected?.chapter_seq ?? null);
            selectedCidRef.value = selectedCid.value;
            selectedChapterSeqRef.value = selected?.chapter_seq ?? null;
            // 临时章节 id 被数据库真实 id 替换时仍是同一章，不能把正在展示的 Plan 翻回空正文。
            if (!changedChapter)
                return;
            // 规划/写作中先回 Plan；Write 产物经 SSE 回放到达后再翻正文，避免切回来只看到空正文。
            setCenterView(selected?.status === 'planning' || selected?.status === 'writing' ? 'plan' : 'write');
            latestPlanArtifactRef.value = null;
            latestWriteArtifactRef.value = null;
        }, { immediate: true, flush: "post" });
        // 候选池加载失败静默降级（空列表），不阻塞主链路。切书后丢弃上一本迟到的响应。
        const loadCandidates = () => {
            const pid = projectId.value;
            api.listCandidates(pid, '').then((list) => {
                if (projectIdRef.value === pid)
                    setCandidates(list);
            }).catch(() => {
                if (projectIdRef.value === pid)
                    setCandidates([]);
            });
        };
        const loadCandidateReferences = async () => {
            const pid = projectId.value;
            const [graphResult, foreshadowResult] = await Promise.allSettled([
                api.listGraph(pid),
                api.listForeshadows(pid),
            ]);
            if (projectIdRef.value !== pid)
                return;
            const names: Record<string, string> = {};
            if (graphResult.status === 'fulfilled') {
                for (const node of graphResult.value.nodes)
                    names[node.id] = node.name;
            }
            if (foreshadowResult.status === 'fulfilled') {
                for (const item of foreshadowResult.value) {
                    names[item.id] = item.description.length > 48 ? `${item.description.slice(0, 48)}…` : item.description;
                }
            }
            setCandidateReferenceNames(names);
        };
        // 章序 → 待确认候选数（候选面板与章节列表角标联动）
        const pendingByChapter = computed(() => {
            const m = new Map<number, number>();
            for (const c of candidates.value.filter((item) => item.status === 'pending')) {
                m.set(c.source_chapter, (m.get(c.source_chapter) ?? 0) + 1);
            }
            return m;
        });
        const loadProjects = () => {
            api.listProjects().then((list) => {
                setProjects(list);
                const current = list.find((project) => project.id === projectIdRef.value);
                if (current && isProjectDraft(current))
                    navigate(projectHref(current), { replace: true });
            }).catch(() => setProjects([]));
        };
        const loadChapters = async () => {
            const pid = projectId.value;
            const version = workspaceVersion;
            setError(null); // 新一次加载先清陈旧错误横幅
            try {
                const list = await api.listChapters(pid);
                if (disposed || workspaceVersion !== version || projectIdRef.value !== pid)
                    return [];
                setChapters((current) => {
                    const pending = current.filter((chapter) => (chapter.id.startsWith('pending-chapter:')
                        && !list.some((item) => item.chapter_seq === chapter.chapter_seq)));
                    return [...list, ...pending].sort((a, b) => a.chapter_seq - b.chapter_seq);
                });
                return list;
            }
            catch (err) {
                if (disposed || workspaceVersion !== version || projectIdRef.value !== pid)
                    return [];
                setError(formatApiError(err, '章节加载失败'));
                return [];
            }
        };
        watch(() => [accountId.value, loadProjects, loadChapters, loadCandidates, loadCandidateReferences, projectId.value], (_next, _prev, onCleanup) => {
            // projectId 变化 = 切书：立刻丢掉上一本的章节/任务，避免迟到响应把 A 书画到 B 书上。
            setSelectedCid(null);
            setChapters([]);
            setCandidates([]);
            setCandidateReferenceNames({});
            setActiveTaskId(null);
            setBatchTotal(null);
            setActiveChapterSeq(null);
            setReleaseTarget(null);
            setReleaseResumeKey(null);
            setCenterView('write');
            shortRequestVersion.value += 1;
            shortSubmitRef.value = false;
            shortStarted.value = false;
            setShortSubmitting(false);
            setShortStartFailed(false);
            setShortHistory({ projectId: projectId.value, status: 'loading' });
            selectedCidRef.value = null;
            selectedChapterSeqRef.value = null;
            latestPlanArtifactRef.value = null;
            latestWriteArtifactRef.value = null;
            chapterMaterializeVersion.value += 1;
            pendingAutoOpen.value = null;
            setError(null);
            loadProjects();
            const pid = projectId.value;
            const saved = readActiveWrite(accountId.value, pid);
            if (saved) {
                // worker 接手前库里还没有 Task/章节。切回来必须先用本页记下的 taskId 接 SSE。
                const optimisticId = `pending-chapter:${saved.taskId}:${saved.chapterSeq}`;
                const optimisticChapter: ChapterMeta = {
                    id: optimisticId,
                    chapter_seq: saved.chapterSeq,
                    title: null,
                    status: 'planning',
                    word_count: 0,
                    summary: null,
                };
                pendingAutoOpen.value = { taskId: saved.taskId, chapterSeq: saved.chapterSeq };
                // 同一次提交里 selectedSeq 仍是 null，后面的按章 listTasks effect 会先清 taskId。
                // ref / version 立刻对齐，避免空列表把刚恢复的写作盖掉。
                taskStartVersion.value += 1;
                activeTaskIdRef.value = saved.taskId;
                setActiveTaskId(saved.taskId);
                setBatchTotal(saved.batchTotal);
                setActiveChapterSeq(saved.chapterSeq);
                setCenterView('plan');
                setChapters([optimisticChapter]);
                setSelectedCid(optimisticId);
                const materializeVersion = ++chapterMaterializeVersion.value;
                void (async () => {
                    for (let attempt = 0; attempt < 40; attempt += 1) {
                        if (materializeVersion !== chapterMaterializeVersion.value)
                            return;
                        try {
                            const latest = await api.listChapters(pid);
                            if (projectIdRef.value !== pid)
                                return;
                            const target = latest.find((chapter) => chapter.chapter_seq === saved.chapterSeq);
                            if (target) {
                                setChapters(latest);
                                setSelectedCid((current) => current === optimisticId ? target.id : current);
                                return;
                            }
                            setChapters((current) => {
                                const pending = current.filter((chapter) => (chapter.id.startsWith('pending-chapter:')
                                    && !latest.some((item) => item.chapter_seq === chapter.chapter_seq)));
                                return [...latest, ...pending].sort((a, b) => a.chapter_seq - b.chapter_seq);
                            });
                        }
                        catch {
                            // 占位章仍由 SSE/终态刷新接管。
                        }
                        await new Promise((resolve) => window.setTimeout(resolve, 250));
                    }
                })();
            }
            const initialTaskVersion = taskStartVersion.value;
            const initialWorkspaceVersion = workspaceVersion;
            const initialIsCurrent = () => !disposed && workspaceVersion === initialWorkspaceVersion && taskStartVersion.value === initialTaskVersion && projectIdRef.value === pid;
            void loadChapters().then(async (list) => {
                if (!initialIsCurrent())
                    return;
                if (saved) {
                    const real = list.find((chapter) => chapter.chapter_seq === saved.chapterSeq);
                    if (real)
                        setSelectedCid(real.id);
                    return;
                }
                const inProgress = latestChapterAwaitingReview(list);
                if (inProgress) {
                    setSelectedCid(inProgress.id);
                    return;
                }
                try {
                    const tasks = await api.listTasks(pid);
                    if (!initialIsCurrent())
                        return;
                    const active = latestActiveGenerationTask(tasks);
                    const seq = active?.chapter_seq;
                    if (!active || !seq)
                        return;
                    const existing = list.find((chapter) => chapter.chapter_seq === seq);
                    if (existing) {
                        setSelectedCid(existing.id);
                        return;
                    }
                    const optimisticId = `pending-chapter:${active.task_id}:${seq}`;
                    const optimisticChapter: ChapterMeta = {
                        id: optimisticId,
                        chapter_seq: seq,
                        title: null,
                        status: active.status === 'awaiting_plan' || active.status === 'queued' ? 'planning' : 'writing',
                        word_count: 0,
                        summary: null,
                    };
                    setChapters((current) => (current.some((chapter) => chapter.chapter_seq === seq)
                        ? current
                        : [...current, optimisticChapter].sort((a, b) => a.chapter_seq - b.chapter_seq)));
                    pendingAutoOpen.value = { taskId: active.task_id, chapterSeq: seq };
                    setActiveTaskId(active.task_id);
                    setBatchTotal(active.batch_size);
                    setActiveChapterSeq(seq);
                    setCenterView('plan');
                    setSelectedCid(optimisticId);
                }
                catch {
                    // 没有进行中任务就保持空书；不阻塞切书。
                }
            });
            loadCandidates();
            void loadCandidateReferences();
            onCleanup(() => {
                chapterMaterializeVersion.value += 1;
            });
        }, { immediate: true, flush: "post" });
        // 跨页深链（审计视图「跳章」→ /projects/:pid?chapter=<seq>）：一次性选中目标章并清参数
        watch(() => [searchParams.value, chapters.value, setSearchParams], (_next, _prev, _onCleanup) => {
            const seqRaw = searchParams.value.get('chapter');
            if (seqRaw === null)
                return;
            const target = chapters.value.find((c) => c.chapter_seq === Number(seqRaw));
            if (target) {
                setSelectedCid(target.id);
                setSearchParams({}, { replace: true });
            }
        }, { immediate: true, flush: "post" });
        const handleTaskStart = (taskId: string, total?: number, chapterSeq?: number, _mode: WritingMode = 'auto') => {
            taskStartVersion.value += 1;
            setBatchTotal(total ?? null);
            setActiveTaskId(taskId);
            // 短篇没有 Plan 产物，翻到 Plan 页只会停在「等待计划」上。
            if (!isShortBook.value)
                setCenterView('plan');
            latestPlanArtifactRef.value = null;
            latestWriteArtifactRef.value = null;
            pendingAutoOpen.value = { taskId, chapterSeq: chapterSeq ?? null };
            if (chapterSeq !== undefined) {
                writeActiveWrite(accountId.value, projectId.value, { taskId, chapterSeq, batchTotal: total ?? null });
            }
            // 单章任务带出对应章（右栏按章过滤）；批次任务不带（按 :ch{seq} 子线程切）
            setActiveChapterSeq(chapterSeq ?? null);
            if (chapterSeq === undefined)
                return;
            const existing = chapters.value.find((chapter) => chapter.chapter_seq === chapterSeq);
            if (existing) {
                setSelectedCid(existing.id);
                return;
            }
            // 网关返回任务后先在界面建立目标章，确保新任务从第一帧起不占用上一章的正文和右栏。
            // worker 会随即持久化同章 writing 记录；轮询拿到真实 id 后无缝替换临时页。
            const optimisticId = `pending-chapter:${taskId}:${chapterSeq}`;
            const optimisticChapter: ChapterMeta = {
                id: optimisticId,
                chapter_seq: chapterSeq,
                title: null,
                status: 'planning',
                word_count: 0,
                summary: null,
            };
            setChapters((current) => {
                if (current.some((chapter) => chapter.chapter_seq === chapterSeq))
                    return current;
                return [...current, optimisticChapter].sort((a, b) => a.chapter_seq - b.chapter_seq);
            });
            setSelectedCid(optimisticId);
            const materializeVersion = ++chapterMaterializeVersion.value;
            void (async () => {
                for (let attempt = 0; attempt < 40; attempt += 1) {
                    if (materializeVersion !== chapterMaterializeVersion.value)
                        return;
                    try {
                        const list = await api.listChapters(projectId.value);
                        if (materializeVersion !== chapterMaterializeVersion.value)
                            return;
                        const target = list.find((chapter) => chapter.chapter_seq === chapterSeq);
                        if (target) {
                            setChapters(list);
                            setSelectedCid((current) => current === optimisticId ? target.id : current);
                            return;
                        }
                        setChapters([...list, optimisticChapter].sort((a, b) => a.chapter_seq - b.chapter_seq));
                    }
                    catch {
                        // SSE/终态刷新仍会继续接管；短暂列表请求失败不打断正在运行的写作任务。
                    }
                    await new Promise((resolve) => window.setTimeout(resolve, 250));
                }
            })();
        };
        // 入队失败先回查一次再报错：请求可能已经送到服务端、只是回包丢了（网关超时、断网）。
        // 不回查就会一边写着整篇、一边告诉用户「没能开始写」，而重试还会被并发闸 429 挡掉——
        // 状态说反了，唯一的出口还是个死按钮。
        const startShortGeneration = async () => {
            if (shortSubmitRef.value)
                return;
            const pid = projectId.value;
            const version = ++shortRequestVersion.value;
            const isCurrent = () => projectIdRef.value === pid && shortRequestVersion.value === version;
            shortSubmitRef.value = true;
            setShortSubmitting(true);
            try {
                if (resourceGate.value && !(await resourceGate.value.beforeGenerate()))
                    return;
                if (!isCurrent())
                    return;
                try {
                    const response = await api.generateShort(pid);
                    if (!isCurrent())
                        return;
                    handleTaskStart(response.task_id);
                    return;
                }
                catch {
                    // 落到回查：确认服务端到底有没有接上这次生成。
                    if (!isCurrent())
                        return;
                }
                try {
                    const latest = (await api.listTasks(pid)).find((task) => task.task_type === 'short_generate');
                    if (!isCurrent())
                        return;
                    if (latest) {
                        handleTaskStart(latest.task_id);
                        return;
                    }
                }
                catch {
                    if (!isCurrent())
                        return;
                    // 结果不明时先核对历史，不能直接再发起一次整篇生成。
                    setShortHistory({ projectId: pid, status: 'failed' });
                }
                setShortStartFailed(true);
            }
            finally {
                if (isCurrent()) {
                    shortSubmitRef.value = false;
                    setShortSubmitting(false);
                }
            }
        };
        // 建书对话页确认完跳进来那一次：入队归本页（中间栏状态带上就是重试入口）。
        // 顺序是显式的——先入队，再抹掉 history.state 上的标记，硬刷新带不回来（带回来就是
        // 白花一次整篇配额）。shortStarted 是 React 18 StrictMode 下的第二道闸；activeTaskId
        // 那一格挡住「重进页面时其实已经有任务了」的重复入队（自动恢复那条 effect 用
        // taskStartVersion 保证不会把我们刚接上的 taskId 又抹回 null）。
        watch(() => [isShortBook.value, shortHistoryStatus.value, handover.value.beginShortWriting, handover.value.planWarning, activeTaskId.value, location.value.pathname, navigate, startShortGeneration], (_next, _prev, _onCleanup) => {
            // 先等 projects 到手：isShortBook 还是 false 的时候就抹标记，会把这次意图整个吞掉。
            if (!isShortBook.value || shortHistoryStatus.value !== 'ready')
                return;
            if (handover.value.beginShortWriting && !shortStarted.value && activeTaskId.value === null) {
                shortStarted.value = true;
                void startShortGeneration();
            }
            if (handover.value.beginShortWriting) {
                handoverState.value = { ...handoverState.value, beginShortWriting: undefined };
                navigate(location.value.pathname, { replace: true, state: { beginShortWriting: undefined, planWarning: handover.value.planWarning ?? null } });
            }
        }, { immediate: true, flush: "post" });
        // 放行本章：resume 同一 task_id 续跑（§6.11 确认流收尾）。taskId 不变但 SSE 已关流，
        // 用 releaseResumeKey 强制重连；终态 → 既有 effect 刷章节/候选，正文出现、按钮消失。
        const handleRelease = (taskId: string, chapterSeq: number, batchSize?: number) => {
            taskStartVersion.value += 1;
            setBatchTotal(batchSize ?? null);
            setActiveChapterSeq(chapterSeq);
            setActiveTaskId(taskId);
            pendingAutoOpen.value = { taskId, chapterSeq };
            setReleaseTarget(null);
            setReleaseResumeKey(Date.now());
        };
        const handlePlanConfirmed = (taskId: string, chapterSeq: number) => {
            taskStartVersion.value += 1;
            setBatchTotal(null);
            setActiveChapterSeq(chapterSeq);
            setActiveTaskId(taskId);
            setCenterView('write');
            pendingAutoOpen.value = { taskId, chapterSeq };
            setChapters((current) => current.map((chapter) => (chapter.chapter_seq === chapterSeq ? { ...chapter, status: 'writing' } : chapter)));
            setReleaseResumeKey(Date.now());
        };
        const handlePlanCancelled = (_taskId: string, chapterSeq: number) => {
            pendingAutoOpen.value = null;
            setChapters((current) => current.map((chapter) => (chapter.chapter_seq === chapterSeq ? { ...chapter, status: 'cancelled' } : chapter)));
            setReleaseResumeKey(Date.now());
            setCenterView('write');
            void loadChapters();
        };
        const task = useTaskEvents(activeTaskId, { batchTotal: () => batchTotal.value ?? undefined, resumeKey: () => releaseResumeKey.value });
        const taskPhase = computed(() => task.phase);
        // 生成任务进入终态/过期 → 章节状态与内容已更新：刷新列表 + 让编辑器重拉当前章正文 + 重载候选池
        watch(() => [taskPhase.value, task.status, loadChapters, loadCandidates, activeTaskId.value, activeChapterSeq.value, batchTotal.value, accountId.value, projectId.value], (_next, _prev, _onCleanup) => {
            if (taskPhase.value === 'terminal' || taskPhase.value === 'expired' || taskPhase.value === 'error') {
                chapterMaterializeVersion.value += 1;
                void loadChapters();
                loadCandidates();
                setRefreshTick((t) => t + 1);
                // 单章任务停在 awaiting_review → 候选确认完后给「放行本章」；放行完成（done）即清
                if (task.status === 'awaiting_review' && activeTaskId.value && activeChapterSeq.value) {
                    setReleaseTarget({ taskId: activeTaskId.value, chapterSeq: activeChapterSeq.value, batchSize: batchTotal.value ?? undefined });
                }
                else if (task.status === 'done' || task.status === 'failed' || task.status === 'cancelled') {
                    clearActiveWrite(accountId.value, projectId.value);
                    setReleaseTarget(null);
                }
            }
        }, { immediate: true, flush: "post" });
        // 单章完成或转人工后只自动打开一次刚生成的章。历史任务重载同样是 terminal，若不以
        // pendingAutoOpen 限定，用户从第 17 章点到其他章节时会立刻被旧终态 effect 拉回。
        watch(() => [taskPhase.value, activeTaskId.value, chapters.value, selectedCid.value], (_next, _prev, _onCleanup) => {
            const pending = pendingAutoOpen.value;
            const target = chapterToOpenForPendingTask(chapters.value, pending, activeTaskId.value, taskPhase.value, selectedCid.value);
            if (!target)
                return;
            pendingAutoOpen.value = null;
            if (target.id !== selectedCid.value)
                setSelectedCid(target.id);
        }, { immediate: true, flush: "post" });
        // 刷新页面或重新进入项目时恢复尚未处理的最新章节，让用户直接看到候选与放行入口。
        watch(() => [chapters.value, selectedCid.value, taskPhase.value], (_next, _prev, _onCleanup) => {
            if (selectedCid.value || taskPhase.value !== 'idle')
                return;
            const target = latestChapterAwaitingReview(chapters.value);
            if (target)
                setSelectedCid(target.id);
        }, { immediate: true, flush: "post" });
        const selectedChapter = computed(() => chapters.value.find((c) => c.id === selectedCid.value) ?? null);
        // 兜底：刷新/重挂载后当前章若停在 awaiting_review（无活动任务流），从任务列表找回
        // 待人工任务补设放行目标。只设不清——放行完成由终态 effect 清、点按钮由 handleRelease
        // 清，此处清会在同一次提交里覆盖终态 effect 刚设的目标（selectedChapter.status 仍陈旧）。
        watch(() => [projectId.value, selectedChapter.value], (_next, _prev, onCleanup) => {
            if (!selectedChapter.value || selectedChapter.value.status !== 'awaiting_review')
                return;
            let cancelled = false;
            api
                .listTasks(projectId.value, selectedChapter.value!.chapter_seq)
                .then((tasks) => {
                if (cancelled)
                    return;
                const awaiting = tasks.find((t) => t.status === 'awaiting_review');
                if (awaiting) {
                    setReleaseTarget({ taskId: awaiting.task_id, chapterSeq: selectedChapter.value!.chapter_seq, batchSize: awaiting.batch_size ?? undefined });
                }
            })
                .catch(() => { });
            onCleanup(() => {
                cancelled = true;
            });
        }, { immediate: true, flush: "post" });
        const selectedSeq = computed(() => selectedChapter.value?.chapter_seq ?? null);
        // 短篇：整篇任务不属于任何一章，按章取任务一条都取不到，只能整表取最新那条
        // short_generate（重进页面后审稿报告要能自己回来）。
        watch(() => [projectId.value, isShortBook.value, shortHistoryReload.value], (_next, _prev, onCleanup) => {
            if (!isShortBook.value)
                return;
            let cancelled = false;
            const requestVersion = taskStartVersion.value;
            setShortHistory({ projectId: projectId.value, status: 'loading' });
            api.listTasks(projectId.value)
                .then((tasks) => {
                if (cancelled || requestVersion !== taskStartVersion.value)
                    return;
                const latest = tasks.find((task) => task.task_type === 'short_generate') ?? null;
                activeTaskIdRef.value = latest?.task_id ?? null;
                setActiveTaskId(latest?.task_id ?? null);
                setBatchTotal(null);
                setActiveChapterSeq(null);
                setReleaseTarget(null);
                setShortHistory({ projectId: projectId.value, status: 'ready' });
            })
                .catch(() => {
                if (cancelled || requestVersion !== taskStartVersion.value)
                    return;
                setShortHistory({ projectId: projectId.value, status: 'failed' });
            });
            onCleanup(() => { cancelled = true; });
        }, { immediate: true, flush: "post" });
        // 每章只呈现一份状态流转：选章后加载覆盖该章的最新生成任务，实时和历史共用一条流程。
        watch(() => [accountId.value, projectId.value, selectedSeq.value, isShortBook.value], (_next, _prev, onCleanup) => {
            // 短篇走上面那条整篇任务恢复，按章对齐会把整条任务清掉。
            if (isShortBook.value)
                return;
            const saved = readActiveWrite(accountId.value, projectId.value);
            const pending = pendingAutoOpen.value;
            const remembered = pending?.taskId
                ? {
                    taskId: pending.taskId,
                    chapterSeq: pending.chapterSeq,
                    batchTotal: saved?.taskId === pending.taskId ? saved.batchTotal : null,
                }
                : saved;
            if (selectedSeq.value === null) {
                // 切书恢复的同一轮里章节还没选上；不能把刚接上的 taskId 清掉。
                if (remembered)
                    return;
                setActiveTaskId(null);
                setBatchTotal(null);
                setActiveChapterSeq(null);
                setReleaseTarget(null);
                return;
            }
            if (remembered && remembered.chapterSeq === selectedSeq.value) {
                activeTaskIdRef.value = remembered.taskId;
                setActiveTaskId(remembered.taskId);
                setBatchTotal(remembered.batchTotal ?? null);
                setActiveChapterSeq(selectedSeq.value);
                return;
            }
            let cancelled = false;
            setActiveTaskId(null);
            setBatchTotal(null);
            setActiveChapterSeq(null);
            setReleaseTarget(null);
            const requestVersion = taskStartVersion.value;
            api.listTasks(projectId.value, selectedSeq.value)
                .then((tasks) => {
                if (cancelled || requestVersion !== taskStartVersion.value)
                    return;
                const latest = latestGenerationTask(tasks);
                if (!latest) {
                    const keep = readActiveWrite(accountId.value, projectId.value);
                    if (keep && keep.chapterSeq === selectedSeq.value) {
                        activeTaskIdRef.value = keep.taskId;
                        setActiveTaskId(keep.taskId);
                        setBatchTotal(keep.batchTotal);
                        setActiveChapterSeq(selectedSeq.value);
                        return;
                    }
                    setActiveTaskId(null);
                    setBatchTotal(null);
                    setActiveChapterSeq(null);
                    setReleaseTarget(null);
                    return;
                }
                setActiveTaskId(latest.task_id);
                setBatchTotal(latest.batch_size);
                setActiveChapterSeq(selectedSeq.value);
                setReleaseResumeKey(null);
                setReleaseTarget(latest.status === 'awaiting_review'
                    ? { taskId: latest.task_id, chapterSeq: selectedSeq.value!, batchSize: latest.batch_size ?? undefined }
                    : null);
            })
                .catch(() => { });
            onCleanup(() => { cancelled = true; });
        }, { immediate: true, flush: "post" });
        const taskRuns = computed(() => runsForChapter(task.runs, {
            taskId: activeTaskId.value,
            batch: batchTotal.value !== null,
            selectedSeq: selectedSeq.value,
            activeChapterSeq: activeChapterSeq.value,
        }));
        const taskNodes = computed(() => nodesForChapter(task.nodes, {
            taskId: activeTaskId.value,
            batch: batchTotal.value !== null,
            selectedSeq: selectedSeq.value,
            activeChapterSeq: activeChapterSeq.value,
        }));
        const visibleTaskRuns = computed(() => isShortBook.value ? task.runs : taskRuns.value);
        const visibleTaskNodes = computed(() => isShortBook.value ? task.nodes : taskNodes.value);
        const planArtifact = computed(() => task.artifacts.find((item) => item.chapterSeq === selectedSeq.value && item.stage === 'plan') ?? null);
        const writeArtifact = computed(() => task.artifacts.find((item) => item.chapterSeq === selectedSeq.value && item.stage === 'write') ?? null);
        const taskIsCreating = computed(() => task.status === 'queued' || task.status === 'running' || task.status === 'awaiting_plan');
        const taskInFlight = computed(() => Boolean(activeTaskId.value) && (taskIsCreating.value || task.status === 'awaiting_review'
            || taskPhase.value === 'connecting'
            || taskPhase.value === 'live'
            || taskPhase.value === 'reconnecting'));
        const hasPlan = computed(() => planArtifact.value !== null || visibleTaskRuns.value.some((run) => (run.node === 'plan_chapter' && run.detail?.plan)));
        const shortReviewRun = computed(() => [...task.runs].reverse().find((run) => run.node === 'short_review' && run.detail?.short_review));
        const shortReview = computed(() => shortReviewRun.value?.detail?.short_review);
        const shortEmptyChapters = computed(() => shortReviewRun.value?.detail?.empty_chapters ?? []);
        const shortLengthFindings = computed(() => shortReviewRun.value?.detail?.length_findings ?? []);
        const shortNeedsCheck = computed(() => Boolean(shortReview.value?.warning || shortReviewRun.value?.degraded || shortReviewRun.value?.error
            || shortLengthFindings.value.length || (shortReview.value?.verdict === 'revise' && !shortReviewRun.value?.detail?.revised)));
        const shortFailed = computed(() => task.status === 'failed' || task.status === 'cancelled' || taskPhase.value === 'error');
        const shortStage = computed(() => shortStageProgress(task.shortProgress));
        const shortStatus = computed(() => shortHistoryStatus.value === 'loading' ? '正在查询写作任务…'
            : shortHistoryStatus.value === 'failed' ? '未能确认写作状态，请重新查询'
                : shortSubmitting.value ? '正在提交写作任务…'
                    : taskInFlight.value ? shortStage.value ? `正在${nodeLabel(shortStage.value.stage)}…` : '正在写整篇…'
                        : task.status === 'done'
                            ? shortEmptyChapters.value.length ? '部分正文未完成'
                                : shortNeedsCheck.value ? '正文已生成，仍需检查'
                                    : shortReview.value ? '整篇写完了' : '正文已生成，审稿记录待核实'
                            : task.status === 'cancelled' ? '这次写作已取消'
                                : shortFailed.value ? '这次写作没能完成'
                                    : shortStartFailed.value ? '没能开始写'
                                        : '还没开始写');
        const canStartShort = computed(() => shortHistoryStatus.value === 'ready' && !taskInFlight.value && task.status !== 'done' && task.status !== 'cancelled');
        const startShort = async () => {
            if (shortSubmitRef.value || !canStartShort.value)
                return;
            setShortStartFailed(false);
            if (!activeTaskId.value) {
                await startShortGeneration();
                return;
            }
            // 连接故障只重连；任务失败要调用服务端续跑，重连 SSE 不会启动 worker。
            if (task.status !== 'failed' && task.status !== 'paused') {
                task.retry();
                return;
            }
            const pid = projectId.value;
            const version = ++shortRequestVersion.value;
            const isCurrent = () => projectIdRef.value === pid && shortRequestVersion.value === version;
            shortSubmitRef.value = true;
            setShortSubmitting(true);
            setError(null);
            try {
                await api.resumeTask(activeTaskId.value);
                if (!isCurrent())
                    return;
                setReleaseResumeKey(Date.now());
                task.refresh();
            }
            catch (reason) {
                if (!isCurrent())
                    return;
                setError(formatApiError(reason, '续跑失败，请重试'));
                task.refresh();
                task.retry();
            }
            finally {
                if (isCurrent()) {
                    shortSubmitRef.value = false;
                    setShortSubmitting(false);
                }
            }
        };
        const isPendingChapter = computed(() => selectedChapter.value?.id.startsWith('pending-chapter:') ?? false);
        const liveNode = computed(() => taskIsCreating.value ? isShortBook.value ? task.shortProgress?.stage ?? null
            : liveStageNode(visibleTaskRuns.value, planArtifact.value, writeArtifact.value)
            : null);
        const showCreationWorkspace = computed(() => Boolean(selectedChapter.value && (hasPlan.value || taskIsCreating.value || isPendingChapter.value)));
        const canOpenWrite = computed(() => Boolean(selectedChapter.value && (writeArtifact.value !== null
            || selectedChapter.value.status === 'writing'
            || (!taskIsCreating.value && !isPendingChapter.value))));
        // 新的 Plan（包括审核后的 replan）先占满中栏；Writer 真正开始输出后再自动翻到正文。
        // artifact_id 作为一次产物的稳定边界，避免后续每个 delta 都抢走用户手动切换的页面。
        watch(() => [planArtifact.value?.artifactId], (_next, _prev, _onCleanup) => {
            if (!planArtifact.value || latestPlanArtifactRef.value === planArtifact.value.artifactId)
                return;
            latestPlanArtifactRef.value = planArtifact.value.artifactId;
            setCenterView('plan');
        }, { immediate: true, flush: "post" });
        watch(() => [writeArtifact.value?.artifactId], (_next, _prev, _onCleanup) => {
            if (!writeArtifact.value || latestWriteArtifactRef.value === writeArtifact.value.artifactId)
                return;
            latestWriteArtifactRef.value = writeArtifact.value.artifactId;
            setCenterView('write');
        }, { immediate: true, flush: "post" });
        const handleNotFound = () => {
            setSelectedCid(null);
            void loadChapters();
        };
        const handleSaved = () => {
            void loadChapters();
        };
        // Markdown 导出（纯前端拼接下载）：逐章拉正文 → 标题/章节分隔 → Blob 下载
        const handleExportMarkdown = async () => {
            if (exporting.value || chapters.value.length === 0)
                return;
            const pid = projectId.value;
            const owner = accountId.value;
            const version = ++exportVersion;
            const chapterSnapshot = chapters.value.map(({ id, chapter_seq }) => ({ id, chapter_seq }));
            const project = projects.value.find((p) => p.id === pid);
            const isCurrent = () => !disposed && version === exportVersion && pid === projectId.value && owner === accountId.value;
            setExporting(true);
            try {
                const lines: string[] = [`# ${project?.title ?? 'Myink 作品'}`, ''];
                for (const c of chapterSnapshot) {
                    if (!isCurrent()) return;
                    const detail = await api.getChapter(pid, c.id);
                    if (!isCurrent()) return;
                    const title = detail.title?.trim() || '';
                    lines.push(title ? `## 第 ${c.chapter_seq} 章 · ${title}` : `## 第 ${c.chapter_seq} 章`, '');
                    lines.push(detail.content?.trim() ?? '', '');
                }
                const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${project?.title ?? 'myink'}.md`;
                a.click();
                URL.revokeObjectURL(url);
            }
            catch {
                if (isCurrent()) setError('导出失败');
            }
            finally {
                if (isCurrent()) setExporting(false);
            }
        };
        const handleNavigateChapter = (seq: number) => {
            const target = chapters.value.find((c) => c.chapter_seq === seq);
            if (target)
                setSelectedCid(target.id);
        };
        // 整本书删除（阶段 6 硬删）：confirm → 删除成功回作品库；有进行中任务 → Python 409
        const handleDeleteBook = () => {
            const project = projects.value.find((p) => p.id === projectId.value);
            const title = project?.title ?? '本书';
            if (!window.confirm(`删除《${title}》？全书正文、记忆、向量与任务记录将一并移除，不可撤销。`))
                return;
            setDeleting(true);
            api
                .deleteProject(projectId.value)
                .then(() => navigate(project?.form === 'short' ? '/short' : '/long'))
                .catch((err) => {
                setDeleting(false);
                setError(err instanceof ApiError && err.status === 409
                    ? '本书有进行中任务，无法删除。请先暂停/取消后再试。'
                    : err instanceof ApiError
                        ? formatApiError(err, '删除失败')
                        : '删除失败');
            });
        };
        const toggleSidePanel = () => {
            const next = !sidePanelOpen.value;
            setSidePanelOpen(next);
            writeSidePanelOpen(next);
        };
        return () => {
            return (h("div", { "class": styles.wrap, "data-form": isShortBook.value ? 'short' : 'long' }, [h(ProjectRail, { "projects": projects.value, "onLogout": logout }, () => []), h("aside", { "class": styles.chapters, "aria-label": "章节列表" }, [h("div", { "class": styles.sideHead }, [h("h3", { "class": styles.sideTitle }, ["章节"]), h("button", { "type": "button", "class": "btn btn-quiet", "disabled": exporting.value || chapters.value.length === 0, "onClick": () => void handleExportMarkdown() }, [exporting.value ? '导出中…' : '导出 .md']), h("button", { "type": "button", "class": "btn btn-quiet", "disabled": deleting.value, "onClick": handleDeleteBook }, [deleting.value ? '删除中…' : '删除本书'])]), h(ChapterList, { "chapters": chapters.value, "selectedCid": selectedCid.value, "onSelect": setSelectedCid, "pendingByChapter": pendingByChapter.value }, () => [])]), h("main", { "class": styles.main }, [h("div", { "class": styles.resourceEntry }, [h(RouterLink, { "class": "btn btn-secondary", "to": `/projects/${projectId.value}/settings#writing-resources` }, () => ["选择写作资源"]), h("span", {}, ["题材包、题材规则、文风、创作与表达规则"])]), h(ResourceUpdates, { "key": projectId.value, "projectId": projectId.value, "ref": resourceGate }, () => []), error.value && h("div", { "class": "banner banner-error", "role": "alert" }, [error.value]), isShortBook.value && (h("div", { "class": styles.band, "role": "status" }, [h("span", {}, [shortStatus.value]), handover.value.planWarning && h("span", { "class": styles.bandWarn }, [handover.value.planWarning]), shortHistoryStatus.value === 'failed' && (h("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => {
                                setShortHistory({ projectId: projectId.value, status: 'loading' });
                                setShortHistoryReload((tick) => tick + 1);
                            } }, ["重新查询任务"])), canStartShort.value && (h("button", { "type": "button", "class": "btn btn-quiet", "disabled": shortSubmitting.value, "onClick": () => void startShort() }, [shortStartFailed.value || shortFailed.value ? '重试' : '开始写']))])), isShortBook.value && task.status === 'done' && shortReview.value && (h("section", { "class": styles.shortResult, "aria-label": "整篇检查摘要" }, [(shortEmptyChapters.value.length > 0 || shortNeedsCheck.value) && (h("div", { "class": styles.resultWarning, "role": "alert" }, [shortEmptyChapters.value.length > 0 && h("p", {}, ["第 ", shortEmptyChapters.value.join('、'), " 章仍缺正文，请在章节列表中查看并补齐。"]), shortReview.value.warning && h("p", {}, [shortReview.value.warning]), !shortReview.value.warning && (shortReviewRun.value?.degraded || shortReviewRun.value?.error) && h("p", {}, ["本次审稿未正常完成，请检查正文。"]), shortLengthFindings.value.length > 0 && h("p", {}, [shortLengthFindings.value.length, " 项篇幅偏差，请检查对应章节。"]), shortReview.value.verdict === 'revise' && !shortReviewRun.value?.detail?.revised && h("p", {}, ["审稿建议修改，本次未完成改稿。"])])), !shortReview.value.warning && !shortReviewRun.value?.degraded && !shortReviewRun.value?.error && (h("span", { "class": styles.reviewSummary }, [shortReviewRun.value?.detail?.revised ? '已按审稿意见改稿' : shortReview.value.verdict === 'pass' ? '整篇审稿通过' : '有待修改意见'])), (shortReview.value.issues.length > 0 || shortReview.value.suggestions.length > 0 || shortLengthFindings.value.length > 0) && (h("details", { "class": styles.reviewDetails }, [h("summary", {}, ["查看检查意见"]), h("ul", {}, [[...shortReview.value.issues, ...shortReview.value.suggestions].map((item, index) => h("li", { "key": index }, [item])), shortLengthFindings.value.map((finding, index) => (h("li", { "key": `length-${index}` }, [finding.evidence.map((item) => `第 ${item.chapter} 章：${item.quote}`).join('；'), finding.suggestion && h("span", {}, [" · ", finding.suggestion])])))])]))])), selectedChapter.value ? (showCreationWorkspace.value ? h("div", { "class": styles.creationWorkspace }, [h("nav", { "class": styles.stageTabs, "aria-label": `第 ${selectedChapter.value!.chapter_seq} 章创作视图` }, [!isShortBook.value && (h("button", { "type": "button", "class": centerView.value === 'plan' ? styles.stageTabActive : styles.stageTab, "disabled": !hasPlan.value && !taskIsCreating.value && !isPendingChapter.value, "aria-current": centerView.value === 'plan' ? 'page' : undefined, "onClick": () => setCenterView('plan') }, [h("span", {}, ["Plan"]), h("small", {}, [task.status === 'awaiting_plan' ? '等待确认' : '章节计划'])])), h("button", { "type": "button", "class": centerView.value === 'write' ? styles.stageTabActive : styles.stageTab, "disabled": !canOpenWrite.value, "aria-current": centerView.value === 'write' ? 'page' : undefined, "onClick": () => setCenterView('write') }, [h("span", {}, ["正文"]), h("small", {}, [writeArtifact.value?.complete ? '生成完成' : writeArtifact.value ? '实时写作' : 'Write'])])]), h("div", { "class": styles.creationPage }, [showPlanView.value ? (h(ChapterPlanPanel, { "key": `plan-${projectId.value}-${selectedChapter.value!.chapter_seq}`, "taskId": activeTaskId.value, "chapterSeq": selectedChapter.value!.chapter_seq, "status": task.status, "runs": visibleTaskRuns.value, "artifact": planArtifact.value, "onConfirmed": handlePlanConfirmed, "onCancelled": handlePlanCancelled }, () => [])) : taskIsCreating.value ? (h(StreamingChapterView, { "key": `write-${projectId.value}-${selectedChapter.value!.chapter_seq}`, "chapterSeq": selectedChapter.value!.chapter_seq, "artifact": writeArtifact.value, "summary": selectedChapter.value.summary }, () => [])) : isPendingChapter.value ? (h("div", { "class": styles.generatingChapter, "role": "status" }, [h("span", { "class": styles.generatingBadge }, ["准备中"]), h("h2", {}, ["第 ", selectedChapter.value!.chapter_seq, " 章"]), h("p", {}, ["章节页面已经建立，正在连接生成任务。"])])) : (h(ChapterEditor, { "projectId": projectId.value, "chapter": selectedChapter.value, "onNotFound": handleNotFound, "onSaved": handleSaved, "onMemoryChanged": loadCandidates, "refreshTick": refreshTick.value, "allowMemoryCorrection": allowMemoryCorrection.value }, () => []))])]) : (h(ChapterEditor, { "projectId": projectId.value, "chapter": selectedChapter.value, "onNotFound": handleNotFound, "onSaved": handleSaved, "onMemoryChanged": loadCandidates, "refreshTick": refreshTick.value, "allowMemoryCorrection": allowMemoryCorrection.value }, () => []))) : (h("div", { "class": "empty" }, [chapters.value.length === 0
                            ? (isShortBook.value ? (shortSubmitting.value || taskInFlight.value
                                // 成稿是一次几分钟的整篇调用，这期间页面别处毫无变化——画个环，
                                // 「还在写」和「卡住了」才分得开。
                                ? h(RingProgress, { "value": shortStage.value?.value ?? 0, "label": shortStage.value ? nodeLabel(shortStage.value.stage) : '成稿', "indeterminate": shortStage.value?.indeterminate ?? true, "ariaLabel": "短篇写作进度" }, () => []) : '成稿还没出来。')
                                : '还没有章节。在右侧发起首次生成。')
                            : '选择左侧章节开始编辑。']))]), h("aside", { "class": sidePanelOpen.value ? styles.right : styles.rightDock, "aria-label": "生成与校验" }, [h("button", { "type": "button", "class": `btn btn-quiet ${styles.dockToggle}`, "aria-expanded": sidePanelOpen.value, "aria-controls": "workspace-side-body", "onClick": toggleSidePanel }, [sidePanelOpen.value ? '收起面板' : '生成与校验']), h("div", { "class": styles.rightBody, "id": "workspace-side-body", "hidden": !sidePanelOpen.value }, [isShortBook.value ? (h(TaskTimeline, { "key": `flow-${projectId.value}-short`, "taskId": activeTaskId.value, "phase": task.phase, "status": task.status, "budget": task.budget, "nodes": visibleTaskNodes.value, "runs": visibleTaskRuns.value, "liveNode": liveNode.value, "progress": task.progress, "chapterSeq": null, "error": task.error, "onRetry": task.retry, "canControl": batchTotal.value !== null, "refresh": task.refresh }, () => [])) : (h(Fragment, null, [h(GenerationPanel, { "key": `${accountId.value}:${projectId.value}`, "projectId": projectId.value, "chapters": chapters.value, "selectedChapter": selectedChapter.value, "taskBusy": taskInFlight.value, "beforeGenerate": () => resourceGate.value?.beforeGenerate() ?? Promise.resolve(true), "onTaskStart": handleTaskStart }, () => []), h(TaskTimeline, { "key": `flow-${projectId.value}-${selectedSeq.value ?? 'none'}`, "taskId": activeTaskId.value, "phase": task.phase, "status": task.status, "budget": task.budget, "nodes": visibleTaskNodes.value, "runs": visibleTaskRuns.value, "liveNode": liveNode.value, "progress": task.progress, "chapterSeq": selectedSeq.value, "error": task.error, "onRetry": task.retry, "canControl": batchTotal.value !== null, "refresh": task.refresh }, () => []), h(AuditPanel, { "key": `audit-${projectId.value}-${selectedSeq.value ?? 'none'}`, "runs": visibleTaskRuns.value, "onNavigateChapter": handleNavigateChapter }, () => []), h(CandidatePanel, { "key": `${projectId.value}:${selectedSeq.value ?? 'none'}`, "projectId": projectId.value, "chapterSeq": selectedSeq.value, "chapterStatus": selectedChapter.value?.status, "candidates": candidates.value, "onChanged": loadCandidates, "releaseTarget": releaseTarget.value, "onReleased": handleRelease, "referenceNames": candidateReferenceNames.value }, () => []), h(LessonsPanel, { "projectId": projectId.value }, () => [])]))])])]));
        };
    }
});

export default WorkspacePage

</script>
