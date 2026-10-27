<script lang="ts">
import { defineComponent, onMounted, onScopeDispose, reactive, h, ref, shallowRef, computed, watch, watchEffect } from 'vue';
import type { CSSProperties, PropType } from 'vue';
import { useRouter, RouterLink, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router';
import NativeDialog from "../components/NativeDialog.vue";
import PendantLamp from "../components/PendantLamp.vue";
import ProjectRail from "../components/ProjectRail.vue";
import { usePrefersReducedMotion } from "../composables/usePrefersReducedMotion";
import { useAuth } from "../authContext";
import { useTheme } from "../themeContext";
import { api } from "../../../src/lib/api";
import { formatApiError } from "../../../src/lib/apiError";
import { applyTheme, clampChromeOpacity, clampPercent, clampWallpaperZoom, CUSTOM_TOKEN_FIELDS, DEFAULT_CUSTOM_TOKENS, DEFAULT_WALLPAPER, hexToRgba, isHexColor, LAMPS, newPresetId, nextPresetName, PRESET_LIMIT, primaryInkFor, THEMES, THEME_FONTS, THEME_FONT_SIZES, WALLPAPER_ZOOM_MAX, WALLPAPER_ZOOM_MIN, type CustomPreset, type CustomTokenKey, type CustomThemeTokens, type ThemeId, type ThemeStyle, type WallpaperConfig,  } from "../../../src/lib/theme";
import { captureVideoPoster, clearWallpaper, readPoster, readWallpaper, wallpaperError, wallpaperKindOf, writePoster, writeWallpaper,  } from "../../../src/lib/themeImage";
import { OFFICIAL_THEME_TOKENS, PINNED_WORKSPACE_PREVIEW, WORKSPACE_PREVIEW_SIZE, type PreviewTokens,  } from "../../../src/lib/themePreview";
import type { Project } from "../../../src/types";
import styles from "../../../src/pages/SettingsPage.module.css";
const preview = PINNED_WORKSPACE_PREVIEW;
// 背景图预览框固定成 16:9，这样框里的铺法和整页一致，拖拽手感才对得上
const STAGE_ASPECT = 16 / 9;
// 编辑器草稿。id 可能是还没落库的新预设；file / drop / poster 是背景草稿，保存时才写 IndexedDB。
// poster 是视频的首帧静帧（也就视频有）；dirty 只标记「改过」，用来判断退出时要不要拦一下
type Editor = {
    id: string;
    isNew: boolean;
    name: string;
    tokens: CustomThemeTokens;
    wallpaper: WallpaperConfig;
    file: File | null;
    poster: Blob | null;
    drop: boolean;
    dirty: boolean;
};
type OpenedTheme = {
    kind: 'official';
    id: Exclude<ThemeId, 'custom'>;
} | {
    kind: 'preset';
    id: string;
};
// 收起编辑块和离开页面都会丢掉草稿，都要先问一句
type PendingExit = {
    kind: 'collapse';
} | {
    kind: 'leave';
};
function scale2(value: number): number {
    return Math.round(value * 100) / 100;
}
/** 预览框里的铺法：和整页同一套算法，只是把 vw/vh 换成框自身的百分比 */
function stageStyle(image: string | null, config: WallpaperConfig): CSSProperties {
    const { aspect, fit, x, y, zoom } = config;
    const scale = zoom / 100;
    const coverWidth = scale2(Math.max(1, aspect / STAGE_ASPECT) * 100 * scale);
    const coverHeight = scale2(Math.max(STAGE_ASPECT / aspect, 1) * 100 * scale);
    return {
        backgroundImage: image ? `url("${image}")` : 'none',
        backgroundPosition: `${x}% ${y}%`,
        backgroundRepeat: fit === 'tile' ? 'repeat' : 'no-repeat',
        backgroundSize: fit === 'tile'
            ? `auto ${scale2(100 * scale)}%`
            : `${coverWidth}% ${coverHeight}%`,
    };
}
function previewStyle(tokens: PreviewTokens, style: ThemeStyle, image: string | null, wallpaper: WallpaperConfig): CSSProperties {
    const face = THEME_FONTS.find((item) => item.id === style.font) ?? THEME_FONTS[0];
    const size = THEME_FONT_SIZES.find((item) => item.id === style.fontSize) ?? THEME_FONT_SIZES[1];
    const alpha = clampChromeOpacity(style.chromeOpacity) / 100;
    const mix = (value: number) => Math.round(Math.min(1, Math.max(0, value)) * 100) / 100;
    return {
        '--preview-canvas': tokens.canvas,
        '--preview-ink': tokens.ink,
        '--preview-editor-ink': tokens.editorInk,
        '--preview-accent': tokens.accent,
        // 和整页一样：外壳和纸都跟着透明度走。官方主题的面板底是独立一档不透明色（tokens.css），
        // 预设配色没有这一档，只能继续拿纸色按 0.86 摊薄——和 applyCustomPaint 同一套。
        '--preview-chrome': tokens.surface
            ? hexToRgba(tokens.surface, mix(alpha))
            : hexToRgba(tokens.editor, mix(alpha * 0.86)),
        '--preview-editor': hexToRgba(tokens.editor, mix(alpha)),
        '--preview-accent-soft': hexToRgba(tokens.accent, mix(alpha * 0.34)),
        // 主按钮的字色。原来这里拿画布色当字用，预览把一个读不了的按钮当成产品样子展示。
        '--preview-btn-ink': tokens.btnInk ?? primaryInkFor(tokens.accent),
        '--preview-font': face.css,
        '--preview-editor-size': size.editor,
        '--preview-image': image ? `url("${image}")` : 'none',
        '--preview-position': `${wallpaper.x}% ${wallpaper.y}%`,
    } as CSSProperties;
}
function imageAspect(url: string, fallback: number): Promise<number> {
    return new Promise((resolve) => {
        const image = new Image();
        image.onload = () => resolve(image.naturalWidth / image.naturalHeight || fallback);
        image.onerror = () => resolve(fallback);
        image.src = url;
    });
}
const WorkspacePreview = defineComponent({
    props: {
        tokens: { type: Object as PropType<PreviewTokens>, required: true },
        style: { type: Object as PropType<ThemeStyle>, required: true },
        image: { type: String as PropType<string | null>, default: null },
        wallpaper: { type: Object as PropType<WallpaperConfig>, required: true },
        size: { type: String as PropType<'thumb' | 'large'>, required: true },
    },
    setup(props: {
        tokens: PreviewTokens;
        style: ThemeStyle;
        image: string | null;
        wallpaper: WallpaperConfig;
        size: 'thumb' | 'large';
    }) {
        const frame = shallowRef<HTMLDivElement | null>(null);
        onMounted(() => {
            const el = frame.value;
            if (!el)
                return;
            const fit = () => {
                const width = el.clientWidth;
                el.style.setProperty('--preview-scale', width > 0 ? String(width / WORKSPACE_PREVIEW_SIZE.width) : '0.22');
            };
            fit();
            if (typeof ResizeObserver === 'undefined')
                return;
            const observer = new ResizeObserver(fit);
            observer.observe(el);
            onScopeDispose(() => observer.disconnect());
        });
        return () => (h("div", { "ref": frame, "class": [
                styles.themePreview,
                props.size === 'large' ? styles.themePreviewLarge : '',
            ].filter(Boolean).join(' '), "style": previewStyle(props.tokens, props.style, props.image, props.wallpaper), "aria-hidden": "true" }, [h("div", { "class": styles.themePreviewApp }, [h("div", { "class": styles.themePreviewRail }, [h("div", { "class": styles.themePreviewBrand }, [preview.brand]), h("div", { "class": styles.themePreviewRailList }, [preview.books.map((book) => (h("div", { "key": book, "class": book === preview.book ? `${styles.themePreviewItem} ${styles.themePreviewItemActive}` : styles.themePreviewItem }, [book])))]), h("div", { "class": styles.themePreviewRailFoot }, [preview.bookLinks.map((link) => (h("div", { "key": link, "class": styles.themePreviewItem }, [link]))), h("div", { "class": styles.themePreviewUser }, [h("span", {}, [preview.user]), h("span", {}, ["登出"])])])]), h("div", { "class": styles.themePreviewPanel }, [h("div", { "class": styles.themePreviewPanelHead }, [h("span", {}, ["章节"]), h("span", {}, ["导出 .md"]), h("span", {}, ["删除本书"])]), preview.chapters.map((chapter) => (h("div", { "key": chapter.seq, "class": chapter.active ? `${styles.themePreviewChapter} ${styles.themePreviewItemActive}` : styles.themePreviewChapter }, [h("span", {}, ["第", chapter.seq, "章"]), h("small", {}, [chapter.words, "字"]), h("small", {}, [chapter.status])])))]), h("div", { "class": styles.themePreviewMain }, [h("div", { "class": styles.themePreviewTabs }, [h("span", {}, ["Plan", h("small", {}, ["章节计划"])]), h("span", { "class": styles.themePreviewTabActive }, ["正文", h("small", {}, ["Write"])])]), h("div", { "class": styles.themePreviewEditorHead }, [h("div", {}, [h("div", { "class": styles.themePreviewTitle }, [preview.title]), h("small", {}, [preview.badge, "·", preview.version])]), h("div", { "class": styles.themePreviewTools }, [h("span", {}, ["校正记忆"]), h("span", {}, ["删除本章"]), h("span", {}, ["历史版本"])])]), h("div", { "class": styles.themePreviewPaper }, [h("p", { "class": styles.themePreviewBody }, [preview.body])]), h("div", { "class": styles.themePreviewEditorFoot }, [h("span", {}, ["已保存"]), h("span", { "class": styles.themePreviewGhost }, ["保存"])])]), h("div", { "class": `${styles.themePreviewPanel} ${styles.themePreviewRight}` }, [h("div", { "class": styles.themePreviewPanelHead }, [h("span", {}, ["生成与重写"]), h("small", {}, ["下一章：第 2 章"])]), h("div", { "class": styles.themePreviewLabel }, ["写作指令（可留空）"]), h("div", { "class": `${styles.themePreviewField} ${styles.themePreviewInstruction}` }, ["如：节奏放慢，重点刻画战斗场面"]), h("div", { "class": styles.themePreviewAction }, ["写下一章（第 2 章）"]), h("div", { "class": styles.themePreviewLabel }, ["写作模式"]), h("div", { "class": styles.themePreviewModes }, [h("span", { "class": styles.themePreviewItemActive }, ["自动"]), h("span", {}, ["手动确认 Plan"])]), h("small", {}, ["展示 Plan 后自动写作"]), h("div", { "class": styles.themePreviewGhost }, ["重写第 1 章"]), h("div", { "class": styles.themePreviewLabel }, ["批次生成"]), h("div", { "class": styles.themePreviewBatch }, [h("span", { "class": styles.themePreviewField }, ["3"]), h("small", {}, ["从第 3 章起 ≈ ¥0.15"])]), h("div", { "class": styles.themePreviewGhost }, ["发起批次"]), h("div", { "class": styles.themePreviewPanelHead }, [h("span", {}, ["章节流转"]), h("small", {}, ["第 1 章 · 已完成 · ¥0.0580"])]), h("small", {}, ["1 次生成 · 16 个阶段"])])])]));
    }
});
export const AppearancePage = defineComponent({
    setup() {
        let active = true;
        onScopeDispose(() => { active = false });
        const auth = useAuth();
        const { logout } = auth;
        const guest = computed(() => auth.status.value !== 'authenticated');
        const reducedMotion = usePrefersReducedMotion();
        const { theme, presets, activePresetId, style, setTheme, selectPreset, savePreset, deletePreset, saveStyle, setWallpaperPreview, setLampPreview, } = useTheme();
        const projects = ref<Project[]>([]), setProjects = (next: typeof projects.value | ((current: typeof projects.value) => typeof projects.value)) => {
            projects.value = typeof next === "function" ? next(projects.value) : next;
        };
        const presetMedia = ref<Record<string, string>>({}), setPresetMedia = (next: typeof presetMedia.value | ((current: typeof presetMedia.value) => typeof presetMedia.value)) => {
            presetMedia.value = typeof next === "function" ? next(presetMedia.value) : next;
        };
        const presetPosters = ref<Record<string, string>>({}), setPresetPosters = (next: typeof presetPosters.value | ((current: typeof presetPosters.value) => typeof presetPosters.value)) => {
            presetPosters.value = typeof next === "function" ? next(presetPosters.value) : next;
        };
        const banner = ref<string | null>(null), setBanner = (next: typeof banner.value | ((current: typeof banner.value) => typeof banner.value)) => {
            banner.value = typeof next === "function" ? next(banner.value) : next;
        };
        const opened = ref<OpenedTheme | null>(null), setOpened = (next: typeof opened.value | ((current: typeof opened.value) => typeof opened.value)) => {
            opened.value = typeof next === "function" ? next(opened.value) : next;
        };
        const editor = ref<Editor | null>(null), setEditor = (next: typeof editor.value | ((current: typeof editor.value) => typeof editor.value)) => {
            editor.value = typeof next === "function" ? next(editor.value) : next;
        };
        const draftStyle = ref<ThemeStyle>(style.value), setDraftStyle = (next: typeof draftStyle.value | ((current: typeof draftStyle.value) => typeof draftStyle.value)) => {
            draftStyle.value = typeof next === "function" ? next(draftStyle.value) : next;
        };
        const draftUrl = ref<string | null>(null), setDraftUrl = (next: typeof draftUrl.value | ((current: typeof draftUrl.value) => typeof draftUrl.value)) => {
            draftUrl.value = typeof next === "function" ? next(draftUrl.value) : next;
        };
        const confirmDelete = ref(false), setConfirmDelete = (next: typeof confirmDelete.value | ((current: typeof confirmDelete.value) => typeof confirmDelete.value)) => {
            confirmDelete.value = typeof next === "function" ? next(confirmDelete.value) : next;
        };
        const pendingExit = ref<PendingExit | null>(null), setPendingExit = (next: typeof pendingExit.value | ((current: typeof pendingExit.value) => typeof pendingExit.value)) => {
            pendingExit.value = typeof next === "function" ? next(pendingExit.value) : next;
        };
        const draftUrlRef = shallowRef<(string | null) | null>(null);
        const drag = shallowRef<({
            pointerId: number;
            startX: number;
            startY: number;
            x: number;
            y: number;
            spanX: number;
            spanY: number;
        } | null) | null>(null);
        const editing = computed(() => editor.value !== null);
        const activePreset = computed(() => presets.value.find((item) => item.id === activePresetId.value) ?? null);
        // 预设封面的静帧：视频用首帧，图片就是本体
        const presetStill = (item: CustomPreset): string | null => (item.wallpaper.kind === 'video' ? presetPosters.value[item.id] : undefined) ?? presetMedia.value[item.id] ?? null;
        const savedEditingMedia = computed(() => editor.value && !editor.value.isNew ? presetMedia.value[editor.value.id] ?? null : null);
        const draftMedia = computed(() => editor.value ? (editor.value.file ? draftUrl.value : editor.value.drop ? null : savedEditingMedia.value) : null);
        const draftImage = computed(() => editor.value?.wallpaper.kind === 'video' ? null : draftMedia.value);
        const draftVideo = computed(() => editor.value?.wallpaper.kind === 'video' ? draftMedia.value : null);
        const styleDirty = computed(() => draftStyle.value.chromeOpacity !== style.value.chromeOpacity
            || draftStyle.value.font !== style.value.font
            || draftStyle.value.fontSize !== style.value.fontSize
            || draftStyle.value.lamp !== style.value.lamp
            || draftStyle.value.lampLight !== style.value.lampLight);
        const editorDirty = computed(() => editor.value?.dirty ?? false);
        const unsaved = computed(() => editorDirty.value || styleDirty.value);
        const previewing = computed(() => editing.value || styleDirty.value);
        const beforeUnload = (event: BeforeUnloadEvent) => { if (unsaved.value) { event.preventDefault(); event.returnValue = ''; } };
        window.addEventListener('beforeunload', beforeUnload);
        onScopeDispose(() => window.removeEventListener('beforeunload', beforeUnload));

        // 吊灯草稿直接作用到右上角那只灯，离开这一页就收回，没保存的选择不会留下来
        watch(() => [draftStyle.value.lamp, draftStyle.value.lampLight, setLampPreview], (_next, _prev, onCleanup) => {
            setLampPreview({ lamp: draftStyle.value.lamp, light: draftStyle.value.lampLight });
            onCleanup(() => setLampPreview(null));
        }, { immediate: true, flush: "post" });
        // 退出预览要回到的那套：即便中途点了删除，这里也始终是当前已保存的状态
        const restore = () => {
            // 背景交给 ThemeContext 按它手里那份句柄重铺：图片和视频两种它都认得
            setWallpaperPreview(null);
            applyTheme(theme.value, activePreset.value?.tokens, style.value);
        };
        const restoreRef = shallowRef(restore);
        watchEffect(() => { restoreRef.value = restore; });
        // 走路由离开页面前拦一下，别让没保存的改动悄悄没了。用 ref 读最新的脏状态，好让回调保持稳定
        const blocker = reactive({ state: 'unblocked', reset: () => { pendingNavigation = null; blocker.state = 'unblocked'; }, proceed: () => { const next = pendingNavigation; pendingNavigation = null; blocker.state = 'unblocked'; bypassLeave = true; if (next)
                void router.push(next); } });
        const router = useRouter();
        let pendingNavigation: string | null = null;
        let bypassLeave = false;
        const protect = (to: {
            fullPath: string;
        }) => { if (bypassLeave) {
            bypassLeave = false;
            return true;
        } ; if (!unsaved.value)
            return true; pendingNavigation = to.fullPath; blocker.state = 'blocked'; return false; };
        onBeforeRouteLeave(protect);
        onBeforeRouteUpdate(protect);
        const askingExit = computed(() => pendingExit.value !== null || blocker.state === 'blocked');
        const cancelExit = () => {
            setPendingExit(null);
            if (blocker.state === 'blocked')
                blocker.reset();
        };
        function confirmExit() {
            const pending = pendingExit.value;
            setPendingExit(null);
            if (blocker.state === 'blocked') {
                blocker.proceed();
                return;
            }
            if (pending?.kind === 'collapse')
                closeEditor();
        }
        watch(() => [guest.value], (_next, _prev, _onCleanup) => {
            if (guest.value)
                return;
            api.listProjects().then(setProjects).catch((err) => {
                setBanner(formatApiError(err, '作品列表加载失败'));
            });
        }, { immediate: true, flush: "post" });
        watch(() => [presets.value], (_next, _prev, onCleanup) => {
            let cancelled = false;
            const created: string[] = [];
            void Promise.all(presets.value.map(async (item) => {
                const blob = await readWallpaper(item.id);
                if (!blob)
                    return null;
                const media = URL.createObjectURL(blob);
                created.push(media);
                if (item.wallpaper.kind !== 'video')
                    return [item.id, media, ''] as const;
                const poster = await readPoster(item.id);
                const still = poster ? URL.createObjectURL(poster) : '';
                if (still)
                    created.push(still);
                return [item.id, media, still] as const;
            })).then((entries) => {
                const loaded = entries.filter((entry) => entry !== null);
                if (cancelled) {
                    created.forEach((url) => URL.revokeObjectURL(url));
                    return;
                }
                setPresetMedia(Object.fromEntries(loaded.map(([id, media]) => [id, media])));
                setPresetPosters(Object.fromEntries(loaded.filter(([, , still]) => still).map(([id, , still]) => [id, still])));
            });
            onCleanup(() => {
                cancelled = true;
                created.forEach((url) => URL.revokeObjectURL(url));
            });
        }, { immediate: true, flush: "post" });
        watch(() => [], (_next, _prev, onCleanup) => {
            onCleanup(() => {
                if (draftUrlRef.value)
                    URL.revokeObjectURL(draftUrlRef.value);
            });
        }, { immediate: true, flush: "post" });
        watch(() => [opened.value], (_next, _prev, onCleanup) => {
            if (!opened.value)
                return;
            const onKey = (event: KeyboardEvent) => {
                if (event.key === 'Escape')
                    setOpened(null);
            };
            window.addEventListener('keydown', onKey);
            onCleanup(() => window.removeEventListener('keydown', onKey));
        }, { immediate: true, flush: "post" });
        watch(() => [askingExit.value, cancelExit], (_next, _prev, onCleanup) => {
            if (!askingExit.value)
                return;
            const onKey = (event: KeyboardEvent) => {
                if (event.key === 'Escape')
                    cancelExit();
            };
            window.addEventListener('keydown', onKey);
            onCleanup(() => window.removeEventListener('keydown', onKey));
        }, { immediate: true, flush: "post" });
        // 实时预览：配色草稿和字体/透明度草稿一改就作用到整页（官方主题也吃字体和透明度）
        watch(() => [previewing.value, editor.value, draftMedia.value, draftStyle.value, theme.value, activePreset.value, setWallpaperPreview], (_next, _prev, _onCleanup) => {
            if (!previewing.value)
                return;
            if (editor.value) {
                applyTheme('custom', editor.value.tokens, draftStyle.value);
                // 已保存的文件还在从本机读：空 url 会把整页背景先擦掉，等读到再铺。
                const waitingForSavedMedia = !editor.value.isNew && !editor.value.file && !editor.value.drop && !draftMedia.value;
                if (!waitingForSavedMedia) {
                    setWallpaperPreview({ url: draftMedia.value, kind: editor.value.wallpaper.kind, config: editor.value.wallpaper });
                }
                return;
            }
            applyTheme(theme.value, activePreset.value?.tokens, draftStyle.value);
        }, { immediate: true, flush: "post" });
        // 收起 / 保存 / 离开页面：把整页还原成盘上那套
        watch(() => [previewing.value], (_next, _prev, onCleanup) => {
            if (!previewing.value)
                return;
            onCleanup(() => restoreRef.value());
        }, { immediate: true, flush: "post" });
        function replaceDraftUrl(url: string | null) {
            if (draftUrlRef.value)
                URL.revokeObjectURL(draftUrlRef.value);
            draftUrlRef.value = url;
            setDraftUrl(url);
        }
        function openEditor(next: Editor) {
            replaceDraftUrl(null);
            setBanner(null);
            setConfirmDelete(false);
            setEditor(next);
        }
        function closeEditor() {
            replaceDraftUrl(null);
            setConfirmDelete(false);
            setEditor(null);
        }
        // 收起会丢掉草稿，改过就先问一句
        function onCollapse() {
            if (editorDirty.value) {
                setPendingExit({ kind: 'collapse' });
                return;
            }
            closeEditor();
        }
        function onCreate() {
            if (presets.value.length >= PRESET_LIMIT) {
                setBanner(`最多 ${PRESET_LIMIT} 套自定义`);
                return;
            }
            openEditor({
                id: newPresetId(),
                isNew: true,
                name: nextPresetName(presets.value),
                tokens: { ...DEFAULT_CUSTOM_TOKENS },
                wallpaper: { ...DEFAULT_WALLPAPER },
                file: null,
                poster: null,
                drop: false,
                dirty: false,
            });
        }
        function editPreset(id: string) {
            const preset = presets.value.find((item) => item.id === id);
            if (!preset)
                return;
            openEditor({
                id,
                isNew: false,
                name: preset.name,
                tokens: { ...preset.tokens },
                wallpaper: { ...preset.wallpaper },
                file: null,
                poster: null,
                drop: false,
                dirty: false,
            });
        }
        function patch(next: Partial<Editor>) {
            setEditor((current) => (current ? { ...current, ...next, dirty: true } : current));
        }
        function patchTokens(key: CustomTokenKey, value: string) {
            setEditor((current) => (current
                ? { ...current, tokens: { ...current.tokens, [key]: value }, dirty: true }
                : current));
        }
        function patchWallpaper(next: Partial<WallpaperConfig>) {
            setEditor((current) => (current
                ? { ...current, wallpaper: { ...current.wallpaper, ...next }, dirty: true }
                : current));
        }
        function onPickWallpaper(file: File | undefined) {
            if (!file || !editor.value)
                return;
            const error = wallpaperError(file);
            if (error) {
                setBanner(error);
                return;
            }
            setBanner(null);
            const kind = wallpaperKindOf(file) ?? 'image';
            replaceDraftUrl(URL.createObjectURL(file));
            // 视频没有平铺一说，换过来时把铺法拉回铺满
            patch({
                file,
                poster: null,
                drop: false,
                wallpaper: { ...editor.value.wallpaper, kind, fit: kind === 'video' ? 'cover' : editor.value.wallpaper.fit },
            });
            if (kind === 'video') {
                void captureVideoPoster(file).then(({ poster, aspect }) => {
                    setEditor((current) => (current?.file === file
                        ? { ...current, poster, wallpaper: { ...current.wallpaper, aspect: aspect ?? current.wallpaper.aspect } }
                        : current));
                });
                return;
            }
            void imageAspect(draftUrlRef.value ?? '', editor.value.wallpaper.aspect).then((next) => {
                setEditor((current) => (current?.file === file
                    ? { ...current, wallpaper: { ...current.wallpaper, aspect: next } }
                    : current));
            });
        }
        function onDropWallpaper() {
            if (!editor.value)
                return;
            replaceDraftUrl(null);
            // 去掉之后就没有背景了，kind 跟着退回图片，避免整页留着一层空的视频
            patch({ file: null, poster: null, drop: true, wallpaper: { ...editor.value.wallpaper, kind: 'image' } });
        }
        function onSave() {
            if (!editor.value)
                return;
            const snapshot = editor.value;
            const tokens = { ...snapshot.tokens };
            for (const field of CUSTOM_TOKEN_FIELDS) {
                if (!isHexColor(tokens[field.key])) {
                    setBanner(`${field.label}需要是 #RGB 或 #RRGGBB`);
                    return;
                }
                tokens[field.key] = tokens[field.key].trim();
            }
            if (!editor.value.name.trim()) {
                setBanner('先给这套起个名字');
                return;
            }
            setBanner(null);
            const saved = {
                id: editor.value.id,
                name: editor.value.name.trim(),
                tokens,
                wallpaper: editor.value.wallpaper,
            };
            // 背景先落库再保存主题：保存会重新读盘，读到的是刚写进去的新图
            const commit = () => {
                if (!active) return;
                savePreset(saved.id, saved.name, saved.tokens, saved.wallpaper);
                // file / drop 留着不清：编辑期间草稿图才是整页背景的准头，清掉会闪一下空白
                setEditor((current) => (current === snapshot
                    ? { ...current, isNew: false, name: saved.name, tokens: saved.tokens, dirty: false }
                    : current));
            };
            if (editor.value.file) {
                // 视频连首帧静帧一起写：卡片列表用它当封面
                const writes: Array<Promise<void>> = [writeWallpaper(editor.value.id, editor.value.file)];
                if (editor.value.poster)
                    writes.push(writePoster(editor.value.id, editor.value.poster));
                void Promise.all(writes).then(commit);
            }
            else if (editor.value.drop)
                void clearWallpaper(editor.value.id).then(commit);
            else
                commit();
        }
        function onSaveStyle() {
            saveStyle(draftStyle.value);
        }
        function onDelete() {
            if (!editor.value)
                return;
            if (!confirmDelete.value) {
                setConfirmDelete(true);
                return;
            }
            if (!editor.value.isNew)
                deletePreset(editor.value.id);
            closeEditor();
        }
        function onWallpaperPointerDown(event: PointerEvent & { currentTarget: HTMLDivElement & HTMLButtonElement }) {
            if (!editor.value || !draftMedia.value)
                return;
            const box = event.currentTarget;
            const boxWidth = box.clientWidth;
            const boxHeight = box.clientHeight;
            const { aspect, x, y, zoom } = editor.value.wallpaper;
            const scale = zoom / 100;
            drag.value = {
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                x,
                y,
                // background-position 是百分比，拖动一格能移动多少取决于图片比框大出多少
                spanX: Math.max(boxWidth, (boxWidth * aspect) / STAGE_ASPECT) * scale - boxWidth,
                spanY: Math.max((boxHeight * STAGE_ASPECT) / aspect, boxHeight) * scale - boxHeight,
            };
            box.setPointerCapture(event.pointerId);
        }
        function onWallpaperPointerMove(event: PointerEvent & { currentTarget: HTMLDivElement & HTMLButtonElement }) {
            const state = drag.value;
            if (!state || state.pointerId !== event.pointerId)
                return;
            const x = state.spanX > 1
                ? clampPercent(state.x - ((event.clientX - state.startX) / state.spanX) * 100, state.x)
                : state.x;
            const y = state.spanY > 1
                ? clampPercent(state.y - ((event.clientY - state.startY) / state.spanY) * 100, state.y)
                : state.y;
            patchWallpaper({ x, y });
        }
        function onWallpaperPointerUp(event: PointerEvent & { currentTarget: HTMLDivElement & HTMLButtonElement }) {
            const state = drag.value;
            if (!state || state.pointerId !== event.pointerId)
                return;
            drag.value = null;
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
        const openedView = computed(() => opened.value && (opened.value.kind === 'official'
            ? {
                label: THEMES.find((item) => item.id === opened.value!.id)?.label ?? opened.value!.id,
                tokens: OFFICIAL_THEME_TOKENS[opened.value!.id],
                image: null as string | null,
                wallpaper: DEFAULT_WALLPAPER,
                active: opened.value!.id === theme.value,
                apply: () => { const selected = opened.value; if (selected?.kind === 'official') setTheme(selected.id) },
            }
            : (() => {
                const item = presets.value.find((preset) => preset.id === opened.value!.id);
                if (!item)
                    return null;
                return {
                    label: item.name,
                    tokens: item.tokens,
                    image: presetStill(item),
                    wallpaper: item.wallpaper,
                    active: theme.value === 'custom' && item.id === activePresetId.value,
                    apply: () => selectPreset(item.id),
                };
            })()));
        function applyOpened() {
            openedView.value?.apply();
            setOpened(null);
        }
        return () => (h("div", { "class": styles.wrap }, [h(ProjectRail, { "projects": projects.value, "onLogout": logout }, () => []), h("main", { "class": styles.main }, [h("div", { "class": styles.inner }, [h("header", { "class": styles.header }, [h("div", {}, [h("h1", {}, ["主题"]), h("div", { "class": styles.crumb }, [h(RouterLink, { "to": "/long" }, () => ["返回长篇"])])])]), banner.value && h("div", { "class": "banner banner-error" }, [banner.value]), h("section", { "class": `panel ${styles.section}` }, [h("h2", { "class": styles.sectionTitle }, ["已有配置"]), h("div", { "class": styles.themeGrid, "role": "group", "aria-label": "主题" }, [THEMES.map((item) => (h("button", { "key": item.id, "type": "button", "class": item.id === theme.value ? `${styles.themeCard} ${styles.themeCardActive}` : styles.themeCard, "aria-label": item.label, "aria-pressed": item.id === theme.value, "onClick": () => setOpened({ kind: 'official', id: item.id }) }, [h(WorkspacePreview, { "size": "thumb", "tokens": OFFICIAL_THEME_TOKENS[item.id], "style": draftStyle.value, "image": null, "wallpaper": DEFAULT_WALLPAPER }, () => []), h("span", { "class": styles.themeCardMeta }, [h("span", { "class": styles.themeCardTitle }, [item.label])])]))), presets.value.map((item) => (h("button", { "key": item.id, "type": "button", "class": theme.value === 'custom' && item.id === activePresetId.value ? `${styles.themeCard} ${styles.themeCardActive}` : styles.themeCard, "aria-label": item.name, "aria-pressed": theme.value === 'custom' && item.id === activePresetId.value, "onClick": () => setOpened({ kind: 'preset', id: item.id }) }, [h(WorkspacePreview, { "size": "thumb", "tokens": item.tokens, "style": draftStyle.value, "image": presetStill(item), "wallpaper": item.wallpaper }, () => []), h("span", { "class": styles.themeCardMeta }, [h("span", { "class": styles.themeCardTitle }, [item.name])])])))]), h("div", {}, [h("button", { "type": "button", "class": "btn btn-secondary", "onClick": onCreate }, ["新建自定义"])])]), h("section", { "class": `panel ${styles.section}` }, [h("h2", { "class": styles.sectionTitle }, ["字体与透明度"]), h("div", { "class": styles.themeEditor }, [h("div", { "class": styles.themeEditorCol }, [h("div", { "class": styles.themeField }, [h("span", { "class": styles.fieldLabel }, ["正文字体"]), h("div", { "class": styles.themeChoiceRow }, [THEME_FONTS.map((item) => (h("button", { "key": item.id, "type": "button", "class": draftStyle.value.font === item.id ? `${styles.themeChoice} ${styles.themeChoiceActive}` : styles.themeChoice, "aria-label": item.label, "aria-pressed": draftStyle.value.font === item.id, "style": { fontFamily: item.css }, "onClick": () => setDraftStyle((current) => ({ ...current, font: item.id })) }, [item.label])))])]), h("div", { "class": styles.themeField }, [h("span", { "class": styles.fieldLabel }, ["字号"]), h("div", { "class": styles.themeChoiceRow }, [THEME_FONT_SIZES.map((item) => (h("button", { "key": item.id, "type": "button", "class": draftStyle.value.fontSize === item.id ? `${styles.themeChoice} ${styles.themeChoiceActive}` : styles.themeChoice, "aria-label": item.label, "aria-pressed": draftStyle.value.fontSize === item.id, "onClick": () => setDraftStyle((current) => ({ ...current, fontSize: item.id })) }, [h("span", { "class": styles.themeChoiceSample, "style": { fontSize: item.editor } }, ["永"]), h("span", { "class": styles.themeChoiceLabel }, [item.label])])))])])]), h("div", { "class": styles.themeEditorCol }, [h("label", { "class": styles.themeField }, [h("span", { "class": styles.fieldLabel }, ["界面透明度"]), h("span", { "class": styles.themeSwatchRow }, [h("input", { "type": "range", "min": 20, "max": 100, "aria-label": "界面透明度", "value": draftStyle.value.chromeOpacity, "onInput": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => setDraftStyle((current) => ({
                                                ...current,
                                                chromeOpacity: clampChromeOpacity(Number(event.target.value)),
                                            })) }, []), h("span", { "class": styles.themeSliderValue }, [draftStyle.value.chromeOpacity, "%"])])])])]), h("div", { "class": styles.lampBlock }, [h("h2", { "class": styles.sectionTitle }, ["吊灯"]), h("div", { "class": styles.lampGrid, "role": "group", "aria-label": "吊灯" }, [LAMPS.map((item) => (h("button", { "key": item.id, "type": "button", "class": draftStyle.value.lamp === item.id ? `${styles.lampCard} ${styles.lampCardActive}` : styles.lampCard, "aria-label": item.label, "aria-pressed": draftStyle.value.lamp === item.id, "onClick": () => setDraftStyle((current) => ({ ...current, lamp: item.id })) }, [h(PendantLamp, { "id": item.id, "lit": draftStyle.value.lampLight }, () => [])])))]), h("div", { "class": styles.lampSwitch }, [h("span", { "class": styles.fieldLabel }, ["灯光"]), h("button", { "type": "button", "class": `btn ${draftStyle.value.lampLight ? 'btn-primary' : 'btn-secondary'}`, "aria-pressed": draftStyle.value.lampLight, "onClick": () => setDraftStyle((current) => ({ ...current, lampLight: !current.lampLight })) }, [draftStyle.value.lampLight ? '开' : '关'])])]), h("div", { "class": styles.themeActions }, [h("button", { "type": "button", "class": "btn btn-primary", "onClick": onSaveStyle, "disabled": !styleDirty.value }, ["保存"]), h("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => setDraftStyle(style.value), "disabled": !styleDirty.value }, ["还原"])])]), editor.value && (h("section", { "class": `panel ${styles.section}` }, [h("div", { "class": styles.themeEditorHead }, [h("h2", { "class": styles.sectionTitle }, [editor.value.isNew ? '新建自定义' : `配色与背景图 · ${editor.value.name}`]), h("button", { "type": "button", "class": "btn btn-quiet", "onClick": onCollapse }, ["收起"])]), h("div", { "class": styles.themeEditor }, [h("div", { "class": styles.themeEditorCol }, [h("label", { "class": styles.themeField }, [h("span", { "class": styles.fieldLabel }, ["名称"]), h("input", { "class": "input", "aria-label": "名称", "value": editor.value.name, "onInput": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => patch({ name: event.target.value }) }, [])]), h("div", { "class": styles.themeFields }, [CUSTOM_TOKEN_FIELDS.map((field) => (h("label", { "key": field.key, "class": styles.themeField }, [h("span", { "class": styles.fieldLabel }, [field.label]), h("span", { "class": styles.themeSwatchRow }, [h("input", { "type": "color", "aria-label": `${field.label}色板`, "value": isHexColor(editor.value!.tokens[field.key]) && editor.value!.tokens[field.key].length !== 4
                                                    ? editor.value!.tokens[field.key]
                                                    : '#000000', "onInput": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => patchTokens(field.key, event.target.value) }, []), h("input", { "class": "input", "aria-label": field.label, "value": editor.value!.tokens[field.key], "onInput": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => patchTokens(field.key, event.target.value) }, [])])])))])]), h("div", { "class": styles.themeEditorCol }, [h("div", { "class": styles.themeField }, [h("span", { "class": styles.fieldLabel }, ["背景"]), h("div", { "class": styles.themeWallpaperStage, "style": draftVideo.value ? undefined : stageStyle(draftImage.value, editor.value.wallpaper), "role": "presentation", "onPointerDown": onWallpaperPointerDown, "onPointerMove": onWallpaperPointerMove, "onPointerUp": onWallpaperPointerUp, "onPointerCancel": onWallpaperPointerUp }, [draftVideo.value && (h("video", { "class": styles.themeWallpaperVideo, "src": draftVideo.value, "autoPlay": !reducedMotion.value, "muted": true, "loop": true, "playsInline": true, "style": {
                                                objectPosition: `${editor.value.wallpaper.x}% ${editor.value.wallpaper.y}%`,
                                                transform: editor.value.wallpaper.zoom === 100
                                                    ? undefined
                                                    : `scale(${editor.value.wallpaper.zoom / 100})`,
                                            } }, []))]), h("div", { "class": styles.themeWallpaperActions }, [h("label", { "class": `btn btn-secondary ${styles.themeWallpaperPick}` }, [draftMedia.value ? '换一个' : '选择图片或视频', h("input", { "class": styles.themeWallpaperInput, "type": "file", "accept": "image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm", "aria-label": "上传背景", "onChange": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => {
                                                    onPickWallpaper(event.target.files?.[0]);
                                                    event.target.value = '';
                                                } }, [])]), draftMedia.value && (h("button", { "type": "button", "class": "btn btn-quiet", "onClick": onDropWallpaper }, ["去掉"]))])]), h("div", { "class": styles.themeWallpaperRow }, [h("span", { "class": styles.fieldLabel }, ["铺法"]), h("div", { "class": styles.themeChoiceRow }, [([['cover', '铺满'], ['tile', '平铺']] as const)
                                            .filter(([fit]) => fit !== 'tile' || !draftVideo.value)
                                            .map(([fit, label]) => (h("button", { "key": fit, "type": "button", "class": `${styles.themeChoice} ${styles.themeChoiceTight} ${editor.value!.wallpaper.fit === fit ? styles.themeChoiceActive : ''}`, "aria-pressed": editor.value!.wallpaper.fit === fit, "onClick": () => patchWallpaper({ fit }) }, [h("span", { "class": styles.themeChoiceLabel }, [label])])))]), h("span", { "class": styles.fieldLabel }, ["缩放"]), h("input", { "class": styles.themeWallpaperZoom, "type": "range", "min": WALLPAPER_ZOOM_MIN, "max": WALLPAPER_ZOOM_MAX, "aria-label": "图片缩放", "value": editor.value.wallpaper.zoom, "onInput": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => patchWallpaper({ zoom: clampWallpaperZoom(Number(event.target.value)) }) }, []), h("span", { "class": styles.themeSliderValue }, [editor.value.wallpaper.zoom, "%"])])])]), h("div", { "class": styles.themeActions }, [h("button", { "type": "button", "class": "btn btn-primary", "onClick": onSave }, ["保存这套"]), h("button", { "type": "button", "class": `btn ${confirmDelete.value ? styles.themeDeleteArmed : styles.themeDelete}`, "onClick": onDelete }, [confirmDelete.value ? '确认删除' : '删除这套']), confirmDelete.value && (h("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => setConfirmDelete(false) }, ["取消"]))])]))])]), openedView.value && (h("div", { "class": styles.themeDialogBackdrop, "onClick": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => {
                    if (event.target === event.currentTarget)
                        setOpened(null);
                } }, [h(NativeDialog, { "class": styles.themeDialog, "onClose": () => setOpened(null), "aria-labelledby": "theme-preview-title" }, [h("div", { "class": styles.themeDialogHead }, [h("div", {}, [h("h2", { "id": "theme-preview-title" }, [openedView.value.label]), openedView.value.active && h("span", { "class": "badge badge-success" }, ["使用中"])]), h("button", { "type": "button", "class": "btn btn-quiet", "onClick": () => setOpened(null) }, ["关闭"])]), h(WorkspacePreview, { "size": "large", "tokens": openedView.value.tokens, "style": draftStyle.value, "image": openedView.value.image, "wallpaper": openedView.value.wallpaper }, () => []), h("div", { "class": styles.themeDialogActions }, [h("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => setOpened(null) }, ["先不应用"]), opened.value?.kind === 'preset' && (h("button", { "type": "button", "class": "btn btn-secondary", "onClick": () => {
                                const id = opened.value!.id;
                                setOpened(null);
                                editPreset(id);
                            } }, ["编辑这套"])), h("button", { "type": "button", "class": "btn btn-primary", "onClick": applyOpened, "disabled": openedView.value.active }, ["应用这套"])])])])), askingExit.value && (h("div", { "class": styles.themeDialogBackdrop, "onClick": (event: Event & { target: HTMLInputElement & HTMLTextAreaElement; currentTarget: HTMLElement }) => {
                    if (event.target === event.currentTarget)
                        cancelExit();
                } }, [h(NativeDialog, { "class": `${styles.themeDialog} ${styles.themeConfirm}`, "onClose": cancelExit, "aria-labelledby": "theme-exit-title" }, [h("h2", { "id": "theme-exit-title", "class": styles.themeConfirmTitle }, ["还没保存"]), h("p", { "class": styles.themeConfirmText }, ["直接退出的话，刚才改的东西不会保留。"]), h("div", { "class": styles.themeDialogActions }, [h("button", { "type": "button", "class": "btn btn-secondary", "onClick": cancelExit }, ["取消"]), h("button", { "type": "button", "class": "btn btn-primary", "onClick": confirmExit }, ["确认"])])])]))]));
    }
});

export default AppearancePage

</script>
