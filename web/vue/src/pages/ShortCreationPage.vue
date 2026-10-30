<script lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import { defineComponent, ref, computed, watch, onBeforeUnmount, onActivated, onDeactivated, h, Fragment, Teleport } from 'vue';
import { RouterLink as Link, useRouter } from 'vue-router';
/** 短篇建书：与助手聊清楚 → 方案卡弹出来随手改 → 「确认，开写」。
 *
 * 与长篇向导的分工：长篇要先填设定、再确认大纲，两步都不能省；短篇这里聊完那一刻
 * 方案卡就是设定，后端在确认时一次把逐章方案落库（生成需要它）。
 *
 * 版式：一列聊天，输入条钉在底部。方案卡是**悬浮模态**——它是「确认了就照这个写」的
 * 一次性决定，不是右栏那种随时能瞟一眼的常驻面板；同款弹窗见 components/GuestPromptDialog。
 */
import CreationResourcesDialog from '../components/CreationResourcesDialog.vue';
import { writingResources, type SelectionInput } from '../../../src/lib/writingResources';
import ProjectRail from '../components/ProjectRail.vue';
import { useAuth } from '../authContext';
import { api } from '../../../src/lib/api';
import { autoGrow } from '../../../src/lib/autoGrow';
import { formatApiError } from '../../../src/lib/apiError';
import { shortCreationApi, type ShortCreationCard, type ShortCreationPayload } from '../../../src/lib/shortCreationApi';
import { styleLibraryApi, type ResourceStyleItem } from '../../../src/lib/styleLibraryApi';
import type { Project } from '../../../src/types';
import styles from '../../../src/pages/ShortCreationPage.module.css';
const FIELDS: Array<[
    keyof ShortCreationCard,
    string
]> = [
    [
        'working_title', '暂定名'
    ],
    [
        'genre', '题材'
    ],
    [
        'direction', '方向'
    ],
    [
        'protagonist_pressure', '主角压力'
    ],
    [
        'conflict_core', '核心冲突'
    ],
    [
        'emotional_payoff', '情绪回报'
    ],
    [
        'plot_sketch', '大致情节'
    ]
];
const REQUIRED_TEXT: Array<keyof ShortCreationCard> = [
    'working_title', 'genre', 'direction', 'protagonist_pressure',
    'conflict_core', 'emotional_payoff', 'plot_sketch'
];
// 短篇形态参数（docs/SHORT-FORM.md §5）：与后端 src/myink/short/form.py 的
// resolve_short_lengths 同规——先各自夹进声明区间，再看全篇总量把每章字数压下来。
const SHORT_CHAPTER_MIN = 1;
const SHORT_CHAPTER_MAX = 10;
const SHORT_CHARS_MIN = 1000;
const SHORT_CHARS_MAX = 8000;
const SHORT_TOTAL_MAX = 20000;
/** 输入框自增长的上限（px）：再高就把聊天区挤没了。 */
const COMPOSER_MAX_HEIGHT = 200;
/** 卡上算一遍后端会怎么归一（只在确认前提示，不代替后端）。先截断小数，再夹进区间，避免除零。 */
function resolveShortLengths(chapterCount: number, charsPerChapter: number): {
    chars: number;
    compressed: boolean;
} {
    // 卡片字段后端是 int() 截断（creation.py 的 _known），这里同规先截再夹。
    const chapters = Math.min(Math.max(Math.trunc(chapterCount), SHORT_CHAPTER_MIN), SHORT_CHAPTER_MAX);
    const chars = Math.min(Math.max(Math.trunc(charsPerChapter), SHORT_CHARS_MIN), SHORT_CHARS_MAX);
    if (chapters * chars > SHORT_TOTAL_MAX) {
        return {
            chars: Math.max(SHORT_CHARS_MIN, Math.floor(SHORT_TOTAL_MAX / chapters)),
            compressed: true
        };
    }
    return {
        chars, compressed: false
    };
}
function isReady(card: Partial<ShortCreationCard>): boolean {
    return REQUIRED_TEXT.every((field) => String(card[field] ?? '').trim() !== '');
}
/** 页头那行状态字。'talk' 不在表里：等回复时输入框还能用，页头不必再喊一遍。 */
const OPERATION_LABEL: Record<string, string> = {
    plan: '正在规划章节…',
    create: '正在新建会话…',
    switch: '正在打开…',
    delete: '正在删除…'
};
export default defineComponent({
    name: 'ShortCreationPage', setup() {
        const { session, status, logout } = useAuth();
        const guest = computed(() => status.value === 'anonymous');
        const token = computed(() => session.value?.token ?? '');
        const router = useRouter();
        const visible = ref(true);
        onActivated(() => { visible.value = true; refreshStyleOptions(); });
        onDeactivated(() => { visible.value = false; });
        const navigate = (path: string, options?: {
            replace?: boolean;
            state?: Record<string, string | boolean | null>;
        }) => { const resolved = router.resolve(path); return permitNavigation(() => router[options?.replace ? 'replace' : 'push']({
            path: resolved.path, query: resolved.query, hash: resolved.hash, state: options?.state
        })); };
        let generation = 0;
        let talkController: AbortController | null = null;
        let alive = true;
        const active = (attempt: number) => alive && generation === attempt;
        onBeforeUnmount(() => { alive = false; generation++; talkController?.abort(); });
        const projects = ref<Project[]>([]);
        const data = ref<ShortCreationPayload | null>(null);
        const card = ref<Partial<ShortCreationCard>>({});
        const styleItemId = ref('');
        const styleItems = ref<ResourceStyleItem[]>([]);
        let styleRequest = 0;
        function refreshStyleOptions() {
            if (guest.value || !token.value) return;
            const attempt = generation, request = ++styleRequest;
            void styleLibraryApi.resources(token.value).then(out => {
                if (active(attempt) && request === styleRequest) styleItems.value = out.items;
            }).catch(() => {});
        }
        const draft = ref('');
        // 已发出、还没等到服务端回话的那一句：先挂在对话流里，用户才看得见自己发过什么。
        const pending = ref<string | null>(null);
        const operation = ref<'talk' | 'plan' | 'create' | 'switch' | 'delete' | null>(null);
        const busy = computed(() => operation.value !== null);
        const operationRef = ref(false);
        const error = ref<string | null>(null);
        const cardOpen = ref(false);
        const resourcesOpen = ref(false);
        const committedBook = ref<Awaited<ReturnType<typeof shortCreationApi.commit>> | null>(null);
        // App retains this page across ordinary routes. Login destroys that cache;
        // protect an intentional visit and full unload, but allow expired-session recovery.
        const hasUnsavedInput = () => status.value === 'authenticated' && (Boolean(draft.value || pending.value) || (data.value !== null && (JSON.stringify(card.value) !== JSON.stringify(data.value.session.card ?? {}) || styleItemId.value !== (data.value.session.style_item_id ?? ''))));
        const { permitNavigation } = useMemoryFormGuard(to => to?.path === '/login' && hasUnsavedInput(), { unloadDirty: hasUnsavedInput, recovering: () => guest.value });
        // 会话列表退居「历史」：落点是自动的（重进页面必落在那条还没开写的上），列表只是翻旧账用。
        const historyOpen = ref(false);
        const stream = ref<HTMLDivElement | null>(null);
        const composer = ref<HTMLTextAreaElement | null>(null);
        const cardBody = ref<HTMLDivElement | null>(null);
        const closeRef = ref<HTMLButtonElement | null>(null);
        const dialogRef = ref<HTMLElement | null>(null);
        const openerRef = ref<HTMLButtonElement | null>(null);
        const apply = (next: ShortCreationPayload) => {
            committedBook.value = null; resourcesOpen.value = false;
            data.value = next;
            card.value = next.session.card ?? {};
            styleItemId.value = next.session.style_item_id ?? '';
        };
        const opening = ref(false);
        const reload = async () => {
            const attempt = generation;
            if (guest.value || opening.value)
                return;
            opening.value = true;
            error.value = null;
            try {
                const next = await shortCreationApi.open(token.value);
                if (active(attempt))
                    apply(next);
            }
            catch (reason) {
                if (active(attempt))
                    error.value = formatApiError(reason, '打不开建书对话，请稍后重试');
            } finally { if (active(attempt)) opening.value = false; }
        };
        watch([() => session.value?.userId, guest], () => {
            generation++;
            opening.value = false;
            resourcesOpen.value = false; committedBook.value = null;
            talkController?.abort();
            talkController = null;
            data.value = null;
            card.value = {};
            styleItemId.value = '';
            styleItems.value = [];
            projects.value = [];
            draft.value = '';
            pending.value = null;
            error.value = null;
            operation.value = null;
            operationRef.value = false;
            cardOpen.value = false;
            historyOpen.value = false;
            if (guest.value)
                return;
            const attempt = generation;
            void reload();
            refreshStyleOptions();
            void api.listProjects().then(next => { if (active(attempt))
                projects.value = next; }).catch(() => { });
        }, {
            immediate: true
        });
        watch(() => [data.value], () => {
            if (stream.value)
                stream.value.scrollTop = stream.value.scrollHeight;
        }, {
            immediate: true, flush: "post"
        });
        // 助手把卡聊回去（或「新建会话」清空）时，敞开着的卡要跟着收起来。
        watch(() => [data.value?.ready], () => {
            if (!data.value?.ready)
                cardOpen.value = false;
        }, {
            immediate: true, flush: "post"
        });
        // 输入框随内容长高，到上限才内部滚动——不然写长句子只能在一个小格子里挪。
        watch(() => [draft.value], () => {
            if (composer.value)
                autoGrow(composer.value, COMPOSER_MAX_HEIGHT);
        }, {
            immediate: true, flush: "post"
        });
        // 卡里的字段同样随内容长高：整个弹窗只留 .dialogBody 那一条滚动条。
        // 字段框自己再滚，就成了「能滚的块里嵌一个能滚的框」。
        watch(() => [
            visible.value, cardOpen.value, card.value
        ], () => {
            if (!cardBody.value)
                return;
            for (const el of cardBody.value.querySelectorAll('textarea'))
                autoGrow(el);
        }, {
            immediate: true, flush: "post"
        });
        // 焦点留在方案卡内，关闭后回到原入口，键盘用户可以接着聊。
        watch(() => [visible.value, cardOpen.value], (_next, _previous, onCleanup) => {
            if (!visible.value || !cardOpen.value)
                return;
            const opener = openerRef.value;
            closeRef.value?.focus();
            const onKeyDown = (event: KeyboardEvent) => {
                if (event.key === 'Escape') {
                    event.stopPropagation();
                    cardOpen.value = false;
                }
                if (event.key === 'Tab') {
                    const controls = dialogRef.value?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled)');
                    if (!controls?.length)
                        return;
                    const first = controls[0];
                    const last = controls[controls.length - 1];
                    if (event.shiftKey && document.activeElement === first) {
                        event.preventDefault();
                        last.focus();
                    }
                    else if (!event.shiftKey && document.activeElement === last) {
                        event.preventDefault();
                        first.focus();
                    }
                }
            };
            document.addEventListener('keydown', onKeyDown);
            {
                onCleanup(() => {
                    document.removeEventListener('keydown', onKeyDown);
                    opener?.focus();
                });
                return;
            }
        }, {
            immediate: true, flush: "post"
        });
        const run = async (kind: 'talk' | 'plan' | 'create' | 'switch' | 'delete', action: () => Promise<void>, fallback: string, onError?: () => void) => {
            const attempt = generation;
            if (guest.value || operationRef.value)
                return;
            operationRef.value = true;
            error.value = null;
            operation.value = kind;
            try {
                await action();
            }
            catch (reason) {
                if (!active(attempt))
                    return;
                error.value = formatApiError(reason, fallback);
                onError?.();
            }
            finally {
                if (active(attempt)) {
                    operationRef.value = false;
                    operation.value = null;
                }
            }
        };
        const sendDraft = () => {
            const content = draft.value.trim();
            if (!content || busy.value || !data.value || data.value.session.status !== 'active')
                return;
            // 会话 id 先取出来：发送期间用户仍可能去点别的会话，那不该把这句发到新会话里。
            const sessionId = data.value.session.id;
            const attempt = generation;
            // 自己的话立刻进流、输入框立刻清空。等服务端往返才显示的话，用户盯着一个还留着
            // 原话的输入框，会以为回车没生效。失败时再把原话放回输入框。
            draft.value = '';
            pending.value = content;
            const controller = new AbortController();
            talkController = controller;
            void run('talk', async () => {
                const next = await shortCreationApi.send(token.value, sessionId, content, card.value as Record<string, unknown>, controller.signal);
                if (!active(attempt))
                    return;
                apply(next);
                pending.value = null;
            }, '这句话没发出去，请重试', () => {
                pending.value = null;
                draft.value = ((current) => current || content)(draft.value);
            });
        };
        const cancelTalk = () => {
            if (operation.value !== 'talk') return;
            generation++;
            resourcesOpen.value = false; committedBook.value = null;
            talkController?.abort();
            talkController = null;
            draft.value = draft.value || pending.value || '';
            pending.value = null;
            operation.value = null;
            operationRef.value = false;
        };
        const submit = (event: Event) => {
            event.preventDefault();
            sendDraft();
        };
        // 回车发送（Shift+回车换行）。输入法组合态里的回车是「选词上屏」，不能当发送。
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Enter' || event.shiftKey)
                return;
            if (event.isComposing)
                return;
            event.preventDefault();
            sendDraft();
        };
        // 已确认过的会话不再是可写的（类型里 status 只有 active / committed 两种）。
        const committed = computed(() => data.value !== null && data.value.session.status !== 'active');
        const confirm = () => {
            if (committed.value || !data.value?.ready || !isReady(card.value) || busy.value) return;
            if (draft.value && !window.confirm('还有未发送的对话输入，确认放弃这条输入并开始建书？')) return;
            error.value = null;
            cardOpen.value = false;
            resourcesOpen.value = true;
        };
        const createWithResources = (selections: SelectionInput[]) => {
            if (!data.value || busy.value) return;
            const sessionId = data.value.session.id;
            const attempt = generation;
            void run('plan', async () => {
                const initialStyle = styleItems.value.find(item => item.id === styleItemId.value);
                const retained = initialStyle && selections.some(item => item.origin === initialStyle.origin && item.resource_id === initialStyle.resource_id);
                const styleForCommit = initialStyle ? (retained ? initialStyle.id : null) : (styleItemId.value.startsWith('wr:') ? null : styleItemId.value || null);
                const out = committedBook.value ?? await shortCreationApi.commit(token.value, sessionId, card.value as Record<string, unknown>, styleForCommit);
                if (!active(attempt)) return;
                // Resource-save retries reuse the created book and never start writing early.
                committedBook.value = out;
                const snapshot = await writingResources.snapshot(out.project_id);
                if (!active(attempt)) return;
                await writingResources.select(out.project_id, snapshot.revision, selections);
                if (!active(attempt)) return;
                if (!visible.value) return;
                navigate(`/projects/${out.project_id}`, {state: {beginShortWriting: true, planWarning: out.plan_warning}});
            }, '确认失败，请重试');
        };
        /** 另起一条会话：旧的原样留着，列表里随时能翻回去看。 */
        const createSession = () => void run('create', async () => {
            const attempt = generation;
            const next = await shortCreationApi.create(token.value);
            if (!active(attempt))
                return;
            draft.value = '';
            apply(next);
        }, '新建会话失败，请重试');
        const switchTo = (sessionId: string) => {
            const attempt = generation;
            if (busy.value || !data.value || sessionId === data.value.session.id)
                return;
            void run('switch', async () => {
                const next = await shortCreationApi.openSession(token.value, sessionId);
                if (!active(attempt))
                    return;
                draft.value = '';
                apply(next);
            }, '打不开这条会话，请重试');
        };
        /** 从历史列表里翻一条旧会话：翻完就把列表收起来，界面回到聊天本身。 */
        const openFromHistory = (sessionId: string) => {
            historyOpen.value = false;
            switchTo(sessionId);
        };
        /** 删掉的只是这段对话：已经写成的作品不受影响，只有当日那张没写下去的草稿书一并带走。 */
        const removeSession = () => {
            if (!data.value)
                return;
            const sessionId = data.value.session.id;
            const attempt = generation;
            const title = data.value.sessions.find((s) => s.id === sessionId)?.title ?? '这段对话';
            if (!window.confirm(`删除「${title}」？对话记录不可恢复，已经开写的作品不受影响。`))
                return;
            void run('delete', async () => {
                await shortCreationApi.remove(token.value, sessionId);
                if (!active(attempt))
                    return;
                draft.value = '';
                await reload();
            }, '删除失败，请重试');
        };
        return () => {
            if (!data.value) {
                return (h("div", {
                    "class": styles.page
                }, [
                    h(ProjectRail, {
                        "projects": projects.value, "onLogout": logout
                    }), h("div", {
                        "class": styles.thread
                    }, [h("div", {
                            "class": "empty", "role": error.value ? "alert" : "status"
                        }, [error.value ?? '正在打开建书对话…', error.value && h("button", { type: "button", class: "btn btn-secondary", disabled: opening.value, onClick: () => void reload() }, "重新打开建书对话")])])
                ]));
            }
            const cardReady = !committed.value && isReady(card.value);
            const lengths = resolveShortLengths(card.value.chapter_count ?? 5, card.value.chars_per_chapter ?? 4000);
            const busyLabel = operation.value ? OPERATION_LABEL[operation.value] : undefined;
            // 错误只有一处可见：卡开着时进卡里（弹窗盖住了下面的 banner），否则留在对话上。
            const errorBanner = error.value !== null && h("div", {
                "class": "banner banner-error", "role": "alert"
            }, [error.value]);
            return (h("div", {
                "class": styles.page
            }, [
                h("div", {
                    "class": styles.background, "inert": cardOpen.value || resourcesOpen.value
                }, [
                    h(ProjectRail, {
                        "projects": projects.value, "onLogout": logout
                    }), h("main", {
                        "class": styles.main
                    }, [h("div", {
                            "class": styles.thread
                        }, [
                            h("header", {
                                "class": styles.head
                            }, [
                                h("div", null, [
                                    h("h1", null, ["新建短篇"]), h("p", {
                                        "class": styles.sub, "aria-live": "polite"
                                    }, [busyLabel ?? (committed.value ? '已开写'
                                            : data.value.ready ? '方案已备好 · 等你确认' : '构思中 · 先聊聊故事')])
                                ]), h("div", {
                                    "class": styles.headActions
                                }, [
                                    h("button", {
                                        "type": "button", "class": "btn btn-quiet", "aria-expanded": historyOpen.value, "onClick": () => historyOpen.value = ((open) => !open)(historyOpen.value)
                                    }, [
                                        "历史会话", h("span", {
                                            "class": styles.caret, "aria-hidden": "true"
                                        }, [historyOpen.value ? '▾' : '▸'])
                                    ]), h("button", {
                                        "type": "button", "class": "btn btn-quiet", "onClick": createSession, "disabled": busy.value
                                    }, [operation.value === 'create' ? '正在新建…' : '新建会话']), h("button", {
                                        "type": "button", "class": "btn btn-quiet", "onClick": removeSession, "disabled": busy.value
                                    }, [operation.value === 'delete' ? '正在删除…' : '删除会话'])
                                ])
                            ]), historyOpen.value && (h("ul", {
                                "class": styles.history, "aria-label": "历史会话"
                            }, [data.value.sessions.map((item) => (h("li", {
                                    "key": item.id
                                }, [h("button", {
                                        "type": "button", "class": styles.historyItem, "disabled": busy.value, "aria-current": item.id === data.value?.session.id ? 'true' : undefined, "onClick": () => openFromHistory(item.id)
                                    }, [
                                        h("span", {
                                            "class": styles.historyTitle
                                        }, [item.title]), item.status === 'committed' && h("span", {
                                            "class": "badge"
                                        }, ["已开写"])
                                    ])])))])), h("div", {
                                "class": styles.stream, "ref": (element: unknown) => stream.value = element as never, "aria-label": "建书对话"
                            }, [
                                data.value.messages.map((message) => (h("div", {
                                    "key": message.id, "class": [
                                        styles.turn, message.role === 'user' ? styles.mine : styles.theirs,
                                        message.error ? styles.failed : ''
                                    ].join(' ')
                                }, [
                                    h("p", null, [message.content]), message.error && h("small", {
                                        "role": "alert"
                                    }, [
                                        "这一轮没成功：", message.error
                                    ])
                                ]))), pending.value !== null && (h("div", {
                                    "class": [
                                        styles.turn, styles.mine
                                    ].join(' ')
                                }, [h("p", null, [pending.value])])), data.value.ready && !committed.value && (h("section", {
                                    "class": styles.proposal, "hidden": cardOpen.value, "aria-label": "待确认方案"
                                }, [
                                    h("div", null, [
                                        h("small", null, ["待确认方案"]), h("h2", null, [card.value.working_title || '你的短篇']), h("p", null, [
                                            card.value.genre || '题材待定', " · ", card.value.chapter_count ?? 5, " 章 · 每章约 ", lengths.chars, " 字"
                                        ])
                                    ]), h("dl", { "class": styles.proposalStakes }, [
                                        ['主角压力', card.value.protagonist_pressure],
                                        ['核心冲突', card.value.conflict_core],
                                        ['情绪收束', card.value.emotional_payoff]
                                    ].map(([label, value]) => h("div", null, [
                                        h("dt", null, label), h("dd", null, value || '待补充')
                                    ]))), h("button", {
                                        "ref": (element: unknown) => openerRef.value = element as never, "type": "button", "class": `btn btn-primary ${styles.option}`, "disabled": busy.value, "onClick": () => { error.value = null; cardOpen.value = true; }
                                    }, ["开始建书"])
                                ]))
                            ]), !cardOpen.value && !resourcesOpen.value && errorBanner, committed.value && (h("div", {
                                "class": "banner banner-warning", "role": "status"
                            }, [
                                "已开写。想写新的，点「新建会话」；这段对话留着，随时能翻回来看。", data.value.session.book_id && (h(Fragment, null, [
                                    ' ', "刚开写的那本在", h(Link, {
                                        "to": `/projects/${data.value.session.book_id}`
                                    }, () => ["这里"]), "。"
                                ]))
                            ])), operation.value === 'talk' && h("div", {
                                "class": styles.thinking, "role": "status", "aria-live": "polite"
                            }, [
                                h("span", null, "正在努力构思中，请稍后"),
                                h("button", { "type": "button", "class": "btn btn-quiet", "onClick": cancelTalk }, "取消等待")
                            ]), h("form", {
                                "class": styles.composer, "onSubmit": submit
                            }, [
                                h("label", null, [h("textarea", {
                                        "ref": (element: unknown) => composer.value = element as never, "rows": 3, "aria-label": "对助手说", "class": "input", "value": draft.value, "disabled": committed.value || Boolean(committedBook.value) || (busy.value && operation.value !== 'talk'), "maxLength": 4000, "onInput": (event: Event) => draft.value = (event.target as HTMLInputElement).value, "onKeydown": onKeyDown, "placeholder": committed.value ? '本次建书对话已结束' : '说说你想写的故事…'
                                    }, [])]), h("div", {
                                    "class": styles.composerFoot
                                }, [h("button", {
                                        "type": "submit", "class": "btn btn-primary", "disabled": committed.value || Boolean(committedBook.value) || busy.value || draft.value.trim() === ''
                                    }, [committed.value ? '已开写' : operation.value === 'talk' ? '正在回复…' : '发送'])])
                            ])
                        ])])
                ]), visible.value && resourcesOpen.value && h(CreationResourcesDialog, {
                    busy: busy.value, error: error.value,
                    preselectedStyle: (() => { const item = styleItems.value.find(style => style.id === styleItemId.value); return item ? { origin: item.origin, resource_id: item.resource_id } : undefined })(),
                    onConfirm: createWithResources,
                    onClose: () => { if (!busy.value) { resourcesOpen.value = false; cardOpen.value = true; } }
                }), visible.value && cardOpen.value && !committed.value && h(Teleport, {
                    to: "body"
                }, [h("div", {
                        "class": styles.backdrop, "onMousedown": (event: MouseEvent) => {
                            if (event.target === event.currentTarget)
                                cardOpen.value = false;
                        }
                    }, [h("section", {
                            "ref": (element: unknown) => dialogRef.value = element as never, "class": styles.dialog, "role": "dialog", "aria-modal": "true", "aria-labelledby": "plan-card-title", "aria-busy": operation.value === 'plan'
                        }, [
                            h("header", {
                                "class": styles.dialogHead
                            }, [
                                h("div", null, [
                                    h("h2", {
                                        "id": "plan-card-title"
                                    }, ["方案"]), h("p", null, ["确认了就照这个写。哪一项不对，直接改。"])
                                ]), h("button", {
                                    "ref": (element: unknown) => closeRef.value = element as never, "type": "button", "class": styles.close, "aria-label": "关闭方案卡", "onClick": () => cardOpen.value = false
                                }, ["×"])
                            ]), h("div", {
                                "class": styles.dialogBody, "ref": (element: unknown) => cardBody.value = element as never
                            }, [committedBook.value && h('p', {class: 'banner'}, '作品已创建，方案已保存。请继续确认写作资源；本次重试不会重复创建作品。'),
                                FIELDS.map(([key, label]) => (h("label", {
                                    "key": key, "class": key === 'working_title' || key === 'genre' ? styles.identityField : styles.storyField
                                }, [
                                    h("span", null, [
                                        label, REQUIRED_TEXT.includes(key) ? '（必填）' : ''
                                    ]), h("textarea", {
                                        "class": "input", "rows": key === 'plot_sketch' ? 3 : 1, "disabled": busy.value || Boolean(committedBook.value), "aria-label": label, "value": String(card.value[key] ?? ''), "maxLength": 4000, "onInput": (event: Event) => card.value = {
                                            ...card.value, [key]: (event.target as HTMLInputElement).value
                                        }
                                    }, [])
                                ]))), h("div", {
                                    "class": styles.pair
                                }, [
                                    h("label", null, [
                                        h("span", null, ["章数（1–10）"]), h("input", {
                                            "class": "input", "type": "number", "min": 1, "max": 10, "aria-label": "章数", "disabled": busy.value || Boolean(committedBook.value), "value": card.value.chapter_count ?? 5, "onInput": (event: Event) => card.value = {
                                                ...card.value, chapter_count: Number((event.target as HTMLInputElement).value)
                                            }
                                        }, [])
                                    ]), h("label", null, [
                                        h("span", null, ["每章字数（1000–8000）"]), h("input", {
                                            "class": "input", "type": "number", "min": 1000, "max": 8000, "aria-label": "每章字数", "disabled": busy.value || Boolean(committedBook.value), "value": card.value.chars_per_chapter ?? 4000, "onInput": (event: Event) => card.value = {
                                                ...card.value, chars_per_chapter: Number((event.target as HTMLInputElement).value)
                                            }
                                        }, [])
                                    ])
                                ]), lengths.compressed && (h("div", {
                                    "class": "banner banner-warning"
                                }, [
                                    "每章字数已按全篇 ", SHORT_TOTAL_MAX, " 字上限归一为每章 ", lengths.chars, " 字，生成时按这个数走。"
                                ])), h("label", null, [
                                    h("span", null, ["文风（开写后不可改）"]), h("select", {
                                        "class": "input", "aria-label": "文风", "value": styleItemId.value, "disabled": busy.value || Boolean(committedBook.value), "onChange": (event: Event) => styleItemId.value = (event.target as HTMLInputElement).value
                                    }, [
                                        h("option", {
                                            "value": ""
                                        }, ["不指定"]), styleItemId.value && !styleItems.value.some(item => item.id === styleItemId.value) && h("option", { value: styleItemId.value }, [data.value?.session.style_name || '已保存的旧版文风']), styleItems.value.map((item) => (h("option", {
                                            "key": item.id, "value": item.id
                                        }, [
                                            item.name, item.builtin ? '（平台）' : '（我的）'
                                        ])))
                                    ])
                                ]), errorBanner, !cardReady && h("small", {
                                    "class": styles.hint
                                }, ["还差几个必填项——也可以关掉这张卡，直接告诉助手，它会补上。"])
                            ]), h("footer", {
                                "class": styles.dialogFoot
                            }, [
                                h(Link, {
                                    "to": "/writing-resources"
                                }, () => ["去写作资源添加文风"]), h("button", {
                                    "type": "button", "class": "btn btn-quiet", "onClick": () => cardOpen.value = false
                                }, ["再聊聊"]), h("button", {
                                    "type": "button", "class": "btn btn-primary", "disabled": !cardReady || busy.value, "onClick": () => confirm()
                                }, [operation.value === 'plan' ? '正在规划…' : '确认，开写'])
                            ])
                        ])])])
            ]));
        };
    }
});

</script>
