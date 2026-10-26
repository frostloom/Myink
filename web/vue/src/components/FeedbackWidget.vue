<script lang="ts">
import AttachmentChip from './AttachmentChip.vue'
import { useAuth } from '../authContext';
import { Teleport } from 'vue';
import { defineComponent, h, Fragment, ref, shallowRef, computed, onScopeDispose, watch, watchEffect } from 'vue';

import { useRoute } from 'vue-router';
import { useTheme } from "../themeContext";
import { api } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import { autoGrow } from "../../../src/lib/autoGrow";
import { clampLampX, LAMP_HANG, lampFixturePx, lampFixtureRect, readLampPlace, settleLampDrop, writeLampPlace, type LampPlace,  } from "../../../src/lib/theme";
import type { Feedback } from "../../../src/types";
import PendantLamp from "./PendantLamp.vue";
import styles from "../../../src/components/FeedbackWidget.module.css";
const CATEGORIES: ReadonlyArray<{
    id: string;
    label: string;
}> = [
    { id: 'bug', label: '问题故障' },
    { id: 'suggestion', label: '功能建议' },
    { id: 'other', label: '其他' },
];
const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(CATEGORIES.map((item) => [item.id, item.label]));
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif']);
const VIDEO_TYPES = new Set(['video/mp4', 'video/webm', 'video/quicktime']);
const IMAGE_MAX_BYTES = 10 * 1024 * 1024;
const VIDEO_MAX_BYTES = 100 * 1024 * 1024;
const MAX_FILES = 4;
const DESCRIPTION_MAX = 2000;
const CONTACT_MAX = 200;
/**
 * 左栏那颗带标签的「反馈」按钮派发这个事件，由这里（全站唯一的挂件实例）接住。
 * 灯不是可靠的入口：手机端整只被 display:none 掉（用户口径，见 FeedbackWidget.module.css ≤640），
 * 桌面上它的点击区又常常压在页面控件上——那一下会让给控件（见 lampRival），灯自己不开面板。
 */
const FEEDBACK_OPEN_EVENT = 'myink:feedback';
const INTERACTIVE_SELECTOR = 'a,button,input,select,textarea,summary,label,[role="button"],[contenteditable]';
/** 灯罩淡出只认「看得见的开关」：多行输入与正文不算对手——灯罩压住段落是吊灯的常态。 */
const LAMP_SHADE_SELECTOR = 'a,button,select,input,summary,label,[role="button"]';
function sampleCorners(rect: DOMRect): Array<[
    number,
    number
]> {
    const inset = 6;
    return [
        [(rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2],
        [rect.left + inset, rect.top + inset],
        [rect.right - inset, rect.top + inset],
        [rect.left + inset, rect.bottom - inset],
        [rect.right - inset, rect.bottom - inset],
    ];
}
/**
 * 某一个点上压着的最上层可点元素；没有就返回 null。`selector` 允许换判据：点击让位用
 * `INTERACTIVE_SELECTOR`（什么都能抢），灯罩淡出用 `LAMP_SHADE_SELECTOR`（正文不算对手）。
 *
 * 只判可交互元素，不判正文：这是文字产品，灯罩压住段落是吊灯的常态，压住按钮才是事故。
 * 灯自己不算对手——`.hit` 带 `data-lamp`，整条 dock 也在排除之列，否则手伸过去拿灯会把灯弄没。
 */
function pointRival(x: number, y: number, selector = INTERACTIVE_SELECTOR): HTMLElement | null {
    // jsdom 没有排版，也不实现 elementsFromPoint：测试环境按「没压到东西」处理。
    if (typeof document.elementsFromPoint !== 'function')
        return null;
    for (const el of document.elementsFromPoint(x, y)) {
        const node = el as HTMLElement;
        if (node.closest('[data-lamp]') || node.closest(`.${styles.dock}`))
            continue;
        const rival = node.closest<HTMLElement>(selector);
        if (rival)
            return rival;
    }
    return null;
}
/**
 * 灯的点击区（那颗 52×44 的 .hit，不是 104px 的灯罩——灯罩是 pointer-events:none，压根抢不到点击）
 * 底下压着的最上层可点元素；没有就返回 null。
 *
 * 判定放在点击这一刻而不是挂载时——内容是异步渲染的（项目卡的链接 fetch 回来才存在），
 * 挂载时量到的空位在半秒后就过期了。
 */
function lampRival(button: HTMLElement): HTMLElement | null {
    for (const [x, y] of sampleCorners(button.getBoundingClientRect())) {
        if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight)
            continue;
        const rival = pointRival(x, y);
        if (rival)
            return rival;
    }
    return null;
}
/** 客户端先拦一道：限额与服务端一致，别让用户等上传完了才被拒。 */
function fileError(file: File): string | null {
    if (IMAGE_TYPES.has(file.type)) {
        if (file.size > IMAGE_MAX_BYTES)
            return '单张图片不要超过 10 MB';
        return null;
    }
    if (VIDEO_TYPES.has(file.type)) {
        if (file.size > VIDEO_MAX_BYTES)
            return '单个视频不要超过 100 MB';
        return null;
    }
    return '只支持 jpg / png / webp / gif 图片与 mp4 / webm / mov 视频';
}
function formatSize(bytes: number): string {
    if (bytes < 1024)
        return `${bytes} B`;
    if (bytes < 1024 * 1024)
        return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function formatTime(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
}
function FeedbackCard({ item }: {
    item: Feedback;
}) {
    return (h("li", { "class": styles.card }, [h("div", { "class": styles.cardHead }, [h("span", { "class": "badge" }, [CATEGORY_LABELS[item.category] ?? '其他']), item.status === 'resolved'
                ? h("span", { "class": "badge badge-success" }, ["已解决"]) : h("span", { "class": "badge badge-warning" }, ["待处理"]), h("span", { "class": styles.cardTime }, [formatTime(item.created_at)])]), h("p", { "class": styles.cardText }, [item.description]), item.attachments.length > 0 && (h("div", { "class": styles.chipRow }, [item.attachments.map((attachment) => (h(AttachmentChip, { "key": attachment.index, "feedbackId": item.id, "attachment": attachment }, () => [])))]))]));
}
const FeedbackWidget = defineComponent({
    setup() {
        const route = useRoute();
const auth = useAuth();
let active = true;
onScopeDispose(() => { active = false });
        const { style, lampPreview } = useTheme();
        const lamp = computed(() => lampPreview.value?.lamp ?? style.value.lamp);
        const light = computed(() => lampPreview.value?.light ?? style.value.lampLight);
        const place = ref<LampPlace>((() => readLampPlace(window.innerWidth, window.innerHeight, lampFixturePx(lamp.value)))()), setPlace = (next: typeof place.value | ((current: typeof place.value) => typeof place.value)) => {
            place.value = typeof next === "function" ? next(place.value) : next;
        };
        const placeRef = shallowRef(place.value);
        const drag = shallowRef<({
            pointerId: number;
            startX: number;
            startY: number;
            originX: number;
            originY: number;
            moved: boolean;
        } | null) | null>(null);
        const skipClick = shallowRef(false);
        const open = ref(false), setOpen = (next: typeof open.value | ((current: typeof open.value) => typeof open.value)) => {
            open.value = typeof next === "function" ? next(open.value) : next;
        };
        const shaded = ref(false), setShaded = (next: typeof shaded.value | ((current: typeof shaded.value) => typeof shaded.value)) => {
            shaded.value = typeof next === "function" ? next(shaded.value) : next;
        };
        const tab = ref<'submit' | 'mine'>('submit'), setTab = (next: typeof tab.value | ((current: typeof tab.value) => typeof tab.value)) => {
            tab.value = typeof next === "function" ? next(tab.value) : next;
        };
        const category = ref('bug'), setCategory = (next: typeof category.value | ((current: typeof category.value) => typeof category.value)) => {
            category.value = typeof next === "function" ? next(category.value) : next;
        };
        const description = ref(''), setDescription = (next: typeof description.value | ((current: typeof description.value) => typeof description.value)) => {
            description.value = typeof next === "function" ? next(description.value) : next;
        };
        const contact = ref(''), setContact = (next: typeof contact.value | ((current: typeof contact.value) => typeof contact.value)) => {
            contact.value = typeof next === "function" ? next(contact.value) : next;
        };
        const picked = ref<Array<{
            file: File;
            url: string;
        }>>([]), setPicked = (next: typeof picked.value | ((current: typeof picked.value) => typeof picked.value)) => {
            picked.value = typeof next === "function" ? next(picked.value) : next;
        };
        const busy = ref(false), setBusy = (next: typeof busy.value | ((current: typeof busy.value) => typeof busy.value)) => {
            busy.value = typeof next === "function" ? next(busy.value) : next;
        };
        const notice = ref<string | null>(null), setNotice = (next: typeof notice.value | ((current: typeof notice.value) => typeof notice.value)) => {
            notice.value = typeof next === "function" ? next(notice.value) : next;
        };
        const formError = ref<string | null>(null), setFormError = (next: typeof formError.value | ((current: typeof formError.value) => typeof formError.value)) => {
            formError.value = typeof next === "function" ? next(formError.value) : next;
        };
        const mine = ref<Feedback[] | null>(null), setMine = (next: typeof mine.value | ((current: typeof mine.value) => typeof mine.value)) => {
            mine.value = typeof next === "function" ? next(mine.value) : next;
        };
        const mineLoading = ref(false), setMineLoading = (next: typeof mineLoading.value | ((current: typeof mineLoading.value) => typeof mineLoading.value)) => {
            mineLoading.value = typeof next === "function" ? next(mineLoading.value) : next;
        };
        const mineError = ref<string | null>(null), setMineError = (next: typeof mineError.value | ((current: typeof mineError.value) => typeof mineError.value)) => {
            mineError.value = typeof next === "function" ? next(mineError.value) : next;
        };
        const bulbRef = shallowRef<HTMLButtonElement | null>(null);
        const closeRef = shallowRef<HTMLButtonElement | null>(null);
        const dialogRef = shallowRef<HTMLElement | null>(null);
        const descRef = shallowRef<HTMLTextAreaElement | null>(null);
        const wasOpen = shallowRef(false);
        const pickedRef = shallowRef(picked.value);
        watchEffect(() => { pickedRef.value = picked.value; });
        // 打开时焦点落到关闭按钮，Esc 收起，Tab 在面板内循环；关掉后把焦点还给灯泡，键盘用户不会掉队。
        // 同时锁住背后的页面，避免面板开着时正文还在滚。
        watch(() => [open.value], (_next, _prev, onCleanup) => {
            if (open.value) {
                wasOpen.value = true;
                const previousOverflow = document.body.style.overflow;
                document.body.style.overflow = 'hidden';
                closeRef.value?.focus();
                const onKey = (event: KeyboardEvent) => {
                    if (event.key === 'Escape') {
                        event.stopPropagation();
                        setOpen(false);
                        return;
                    }
                    if (event.key !== 'Tab')
                        return;
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
                };
                document.addEventListener('keydown', onKey);
                onCleanup(() => {
                    document.body.style.overflow = previousOverflow;
                    document.removeEventListener('keydown', onKey);
                });
                return;
            }
            if (wasOpen.value) {
                wasOpen.value = false;
                bulbRef.value?.focus();
            }
        }, { immediate: true, flush: "post" });
        // 面板里的草稿图是本地 File 的 object URL，卸载时统一还回去。
        // 只认卸载：跟着 picked 变会连刚加进去的那几张一起撤销。
        watch(() => [], (_next, _prev, onCleanup) => {
            onCleanup(() => {
                pickedRef.value.forEach((item) => URL.revokeObjectURL(item.url));
            });
        }, { immediate: true, flush: "post" });
        // 左栏那颗「反馈」按钮只派发事件，表单状态全在这里——挂件是全站唯一的实例。
        watch(() => [], (_next, _prev, onCleanup) => {
            const onOpen = () => setOpen(true);
            window.addEventListener(FEEDBACK_OPEN_EVENT, onOpen);
            onCleanup(() => window.removeEventListener(FEEDBACK_OPEN_EVENT, onOpen));
        }, { immediate: true, flush: "post" });
        watch(() => [open.value, tab.value, mine.value], (_next, _prev, onCleanup) => {
            if (!open.value || tab.value !== 'mine' || mine.value !== null)
                return;
            const controller = new AbortController();
            setMineLoading(true);
            setMineError(null);
            api.listFeedback(controller.signal)
                .then((result) => { if (!controller.signal.aborted)
                setMine(result.items); })
                .catch((reason: unknown) => {
                if (!controller.signal.aborted)
                    setMineError(formatApiError(reason, '加载失败，请稍后重试'));
            })
                .finally(() => { if (!controller.signal.aborted)
                setMineLoading(false); });
            onCleanup(() => controller.abort());
        }, { immediate: true, flush: "post" });
        const beforeUnload = (event: BeforeUnloadEvent) => {
            if (description.value || contact.value || picked.value.length || busy.value) { event.preventDefault(); event.returnValue = ''; }
        };
        window.addEventListener('beforeunload', beforeUnload);
        onScopeDispose(() => window.removeEventListener('beforeunload', beforeUnload));
        function addFiles(event: Event & {target: HTMLInputElement}) {
            const chosen = Array.from(event.target.files ?? []);
            event.target.value = '';
            if (chosen.length === 0)
                return;
            const room = MAX_FILES - picked.value.length;
            if (room <= 0) {
                setFormError(`最多 ${MAX_FILES} 个附件`);
                return;
            }
            const accepted: Array<{
                file: File;
                url: string;
            }> = [];
            let error: string | null = null;
            for (const file of chosen.slice(0, room)) {
                const problem = fileError(file);
                if (problem) {
                    error = problem;
                    continue;
                }
                accepted.push({ file, url: URL.createObjectURL(file) });
            }
            if (accepted.length > 0)
                setPicked((current) => [...current, ...accepted]);
            setFormError(error ?? (chosen.length > room ? `最多 ${MAX_FILES} 个附件` : null));
        }
        function removeFile(url: string) {
            URL.revokeObjectURL(url);
            setPicked((current) => current.filter((item) => item.url !== url));
        }
        function onSubmit(event: Event) {
            event.preventDefault();
            if (auth.status.value !== 'authenticated' || !auth.session.value?.roleVerified) return;
            if (busy.value)
                return;
            const text = description.value.trim();
            if (!text) {
                setFormError('请先写下问题描述');
                return;
            }
            const snapshot = {description: description.value, category: category.value, contact: contact.value, files: [...picked.value]};
            const form = new FormData();
            form.append('description', text);
            form.append('category', category.value);
            form.append('contact', contact.value.trim());
            form.append('page_url', route.fullPath.split('#')[0]);
            for (const item of picked.value)
                form.append('files', item.file);
            setBusy(true);
            setFormError(null);
            setNotice(null);
            api.submitFeedback(form)
                .then(() => {
                if (!active) return;
                const unchanged = description.value === snapshot.description && contact.value === snapshot.contact && category.value === snapshot.category && picked.value.length === snapshot.files.length && picked.value.every((item, index) => item.url === snapshot.files[index]?.url);
                snapshot.files.forEach((item) => URL.revokeObjectURL(item.url));
                const submittedUrls = new Set(snapshot.files.map(item => item.url));
                setPicked(current => current.filter(item => !submittedUrls.has(item.url)));
                if (description.value === snapshot.description) { setDescription(''); if (descRef.value) descRef.value.style.height = ''; }
                if (contact.value === snapshot.contact) setContact('');
                if (category.value === snapshot.category) setCategory('bug');
                setMine(null); // 下次进「我的反馈」重新拉，刚提交的这条才会在
                setNotice('已提交，我们会在「我的反馈」里同步处理进度。');
                if (unchanged) setTab('mine');
            })
                .catch((reason: unknown) => { if (active) setFormError(formatApiError(reason, '提交失败，请稍后重试')) })
                .finally(() => { if (active) setBusy(false) });
        }
        /**
         * 手伸到灯下、而灯罩正压着可点的东西时，把灯罩淡下去。点击让位早就做了（见下面的 onClick），
         * 这一条补的是眼睛那一半：同一个判据（pointRival）、同一条规矩（「灯罩压在按钮上是事故」）。
         *
         * 灯罩矩形用 `lampFixtureRect()` 算，不是量 DOM：灯是 fixed 的，位置只跟视口有关，
         * 而 `.sway` 的 ±2.2° 摆动会让量到的盒子每帧漂 3px 出头——判「手在不在罩下」用不着那份精度。
         * 只听鼠标：触屏的滑动会让人在手机上把灯一闪一闪，而 ≤640 整只灯本来就不在场。
         */
        watch(() => [lamp.value, open.value, place.value.hidden], (_next, _prev, onCleanup) => {
            if (place.value.hidden || open.value) {
                setShaded(false);
                return;
            }
            function onWindowPointerMove(event: PointerEvent) {
                if (event.pointerType !== 'mouse')
                    return;
                const box = lampFixtureRect(placeRef.value, lamp.value, window.innerWidth, window.innerHeight);
                const inside = event.clientX >= box.left
                    && event.clientX <= box.right
                    && event.clientY >= box.top
                    && event.clientY <= box.bottom;
                setShaded(inside && pointRival(event.clientX, event.clientY, LAMP_SHADE_SELECTOR) !== null);
            }
            window.addEventListener('pointermove', onWindowPointerMove);
            onCleanup(() => window.removeEventListener('pointermove', onWindowPointerMove));
        }, { immediate: true, flush: "post" });
        function moveLamp(next: LampPlace) {
            placeRef.value = next;
            setPlace(next);
        }
        function onPointerDown(event: PointerEvent & { currentTarget: HTMLDivElement & HTMLButtonElement }) {
            if (event.button !== 0)
                return;
            const current = placeRef.value;
            drag.value = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                originX: current.x,
                originY: current.hidden ? 0 : current.y,
                moved: false,
            };
            event.currentTarget.setPointerCapture?.(event.pointerId);
        }
        function onPointerMove(event: PointerEvent & { currentTarget: HTMLDivElement & HTMLButtonElement }) {
            const state = drag.value;
            if (!state || state.pointerId !== event.pointerId)
                return;
            const dx = event.clientX - state.startX;
            const dy = event.clientY - state.startY;
            if (Math.abs(dx) <= 4 && Math.abs(dy) <= 4)
                return;
            state.moved = true;
            const width = window.innerWidth || 1;
            const height = window.innerHeight || 1;
            const dropped = settleLampDrop(state.originY + dy / height, height, lampFixturePx(lamp.value));
            moveLamp({
                x: clampLampX(state.originX + dx / width, width),
                y: dropped.y,
                hidden: dropped.hidden,
            });
        }
        function onPointerUp(event: PointerEvent & { currentTarget: HTMLDivElement & HTMLButtonElement }) {
            const state = drag.value;
            if (!state || state.pointerId !== event.pointerId)
                return;
            drag.value = null;
            if (!state.moved)
                return;
            skipClick.value = true;
            const width = window.innerWidth || 1;
            const height = window.innerHeight || 1;
            const dropped = settleLampDrop(state.originY + (event.clientY - state.startY) / height, height, lampFixturePx(lamp.value));
            const next: LampPlace = {
                x: clampLampX(state.originX + (event.clientX - state.startX) / width, width),
                y: dropped.y,
                hidden: dropped.hidden,
            };
            moveLamp(next);
            writeLampPlace(next, width, height, lampFixturePx(lamp.value));
        }
        const hang = computed(() => LAMP_HANG[lamp.value]);
        const cordPx = computed(() => place.value.hidden ? 0 : place.value.y * (typeof window === 'undefined' ? 800 : window.innerHeight));
        return () => (h(Fragment, null, [h("div", { "class": styles.dock, "style": {
                    left: `${place.value.x * 100}%`,
                    ['--cord' as string]: hang.value.cord,
                    ['--beam' as string]: hang.value.beam,
                    ['--span' as string]: String(300 - hang.value.top),
                } }, [!place.value.hidden && (h(Fragment, null, [h("span", { "class": styles.cord, "style": { height: `${cordPx.value}px` } }, []), h("span", { "class": styles.hang, "style": { top: `${cordPx.value}px` }, "data-shaded": shaded.value ? 'true' : undefined }, [h("span", { "class": open.value ? `${styles.sway} ${styles.swaying}` : styles.sway }, [light.value && h("span", { "class": styles.glow }, []), h(PendantLamp, { "id": lamp.value, "lit": light.value, "hanging": true, "class": styles.fixture }, () => [])])])])), h("button", { "ref": bulbRef, "type": "button", "class": place.value.hidden ? styles.tip : styles.hit, "style": place.value.hidden ? undefined : { top: `${cordPx.value + lampFixturePx(lamp.value) - 46}px` }, "data-lamp": lamp.value, "data-light": light.value && !place.value.hidden ? 'on' : 'off', "data-hidden": place.value.hidden ? 'true' : 'false', "aria-label": "问题反馈", "aria-expanded": open.value, "onPointerDown": onPointerDown, "onPointerMove": onPointerMove, "onPointerUp": onPointerUp, "onClick": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => {
                        if (skipClick.value) {
                            skipClick.value = false;
                            return;
                        }
                        // 灯的点击区压住别的控件时，这一下归那个控件：灯是装饰，不能替页面吃掉点击。
                        // 不搬灯——实测在满版内容的页面上（项目库、管理台）往左让多少格都还在内容里，
                        // 而在能挪开的页面上它会挪到正文列中间，比压住按钮更难看。拖动不受影响。
                        const rival = lampRival(event.currentTarget);
                        if (rival) {
                            rival.click();
                            return;
                        }
                        setOpen(true);
                    } }, []), !place.value.hidden && (h("button", { "type": "button", "class": styles.tag, "style": { top: `${cordPx.value + lampFixturePx(lamp.value) - 2}px` }, "onClick": () => setOpen(true) }, ["反馈"]))]), open.value && feedbackPortal(h("div", { "class": styles.backdrop, "onMouseDown": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => {
                    if (event.target === event.currentTarget)
                        setOpen(false);
                } }, [h("section", { "ref": dialogRef, "class": styles.dialog, "role": "dialog", "aria-modal": "true", "aria-labelledby": "feedback-title" }, [h("header", { "class": styles.head }, [h("div", {}, [h("h2", { "id": "feedback-title" }, ["问题反馈"]), h("p", { "class": styles.headHint }, ["遇到的问题、想要的功能都可以写在这里，附上截图或录屏更好定位。"])]), h("button", { "ref": closeRef, "type": "button", "class": styles.close, "aria-label": "关闭", "onClick": () => setOpen(false) }, ["×"])]), h("nav", { "class": styles.tabs, "aria-label": "反馈视图" }, [h("button", { "type": "button", "aria-pressed": tab.value === 'submit', "onClick": () => setTab('submit') }, ["提交反馈"]), h("button", { "type": "button", "aria-pressed": tab.value === 'mine', "onClick": () => setTab('mine') }, ["我的反馈"])]), h("div", { "class": styles.body }, [tab.value === 'submit' ? (h("form", { "class": styles.form, "onSubmit": onSubmit }, [h("div", { "class": styles.field }, [h("span", { "class": styles.fieldLabel }, ["类型"]), h("div", { "class": styles.segRow }, [CATEGORIES.map((item) => (h("button", { "key": item.id, "type": "button", "class": item.id === category.value ? `${styles.seg} ${styles.segActive}` : styles.seg, "aria-pressed": item.id === category.value, "onClick": () => setCategory(item.id) }, [item.label])))])]), h("label", { "class": styles.field }, [h("span", { "class": styles.fieldLabel }, ["问题描述"]), h("textarea", { "ref": descRef, "class": "textarea", "aria-label": "问题描述", "required": true, "maxLength": DESCRIPTION_MAX, "placeholder": "越具体越好：在哪个页面、点了什么、期望怎样、实际怎样", "value": description.value, "onInput": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => {
                                        setDescription(event.target.value);
                                        autoGrow(event.target, 280);
                                    }, "onFocus": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => autoGrow(event.target, 280) }, []), h("span", { "class": styles.counter }, [description.value.length, "/", DESCRIPTION_MAX])]), h("label", { "class": styles.field }, [h("span", { "class": styles.fieldLabel }, ["联系方式（可选）"]), h("input", { "class": "input", "aria-label": "联系方式", "maxLength": CONTACT_MAX, "placeholder": "邮箱或其它能联系到你的方式", "value": contact.value, "onInput": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => setContact(event.target.value) }, [])]), h("div", { "class": styles.field }, [h("span", { "class": styles.fieldLabel }, ["图片 / 视频"]), h("div", { "class": styles.pickRow }, [h("label", { "class": `btn btn-secondary ${styles.pickLabel}` }, [picked.value.length > 0 ? '继续添加' : '选择文件', h("input", { "class": styles.pickInput, "type": "file", "multiple": true, "accept": "image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime", "aria-label": "上传图片或视频", "onChange": addFiles }, [])]), h("span", { "class": styles.pickHint }, ["最多", MAX_FILES, "个 · 图片 ≤ 10 MB · 视频 ≤ 100 MB"])]), picked.value.length > 0 && (h("ul", { "class": styles.pickedList }, [picked.value.map((item) => (h("li", { "key": item.url, "class": styles.pickedItem }, [h("span", { "class": styles.pickedThumb }, [item.file.type.startsWith('video/')
                                                ? h("video", { "src": item.url, "muted": true, "playsInline": true, "preload": "metadata" }, []) : h("img", { "src": item.url, "alt": "" }, [])]), h("span", { "class": styles.pickedMeta }, [h("span", { "class": styles.pickedName }, [item.file.name]), h("span", { "class": styles.pickedSize }, [formatSize(item.file.size)])]), h("button", { "type": "button", "class": "btn btn-quiet", "aria-label": `移除 ${item.file.name}`, "onClick": () => removeFile(item.url) }, ["移除"])])))]))]), (formError.value || notice.value) && (h("div", { "class": formError.value ? 'banner banner-error' : 'banner', "role": formError.value ? 'alert' : 'status' }, [formError.value ?? notice.value])), h("div", { "class": styles.actions }, [h("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => setOpen(false) }, ["先不写了"]), h("button", { "type": "submit", "class": "btn btn-primary", "disabled": busy.value }, [busy.value ? '提交中…' : '提交'])])])) : (h("div", { "class": styles.mine }, [h("div", { "class": styles.mineHead }, [h("span", { "class": styles.fieldLabel }, ["我提交过的反馈"]), h("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => setMine(null), "disabled": mineLoading.value }, ["刷新"])]), notice.value && h("div", { "class": "banner", "role": "status" }, [notice.value]), mineLoading.value && h("div", { "class": "empty", "role": "status" }, ["正在加载…"]), mineError.value && h("div", { "class": "banner banner-error", "role": "alert" }, [mineError.value]), !mineLoading.value && !mineError.value && mine.value?.length === 0 && (h("div", { "class": "empty" }, ["还没有提交过反馈。"])), mine.value && mine.value.length > 0 && (h("ul", { "class": styles.cardList }, [mine.value.map((item) => h(FeedbackCard, { "key": item.id, "item": item }, () => []))]))]))])])]), document.body)]));
    }
});

function feedbackPortal(content: import('vue').VNode, _container: HTMLElement) { return h(Teleport, { to: 'body' }, [content]) }

export default FeedbackWidget

</script>
