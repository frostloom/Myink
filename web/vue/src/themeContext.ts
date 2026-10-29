import { ref, shallowRef, computed, inject, type InjectionKey } from 'vue'
import {
  applyTheme,
  applyWallpaper,
  DEFAULT_WALLPAPER,
  PRESET_LIMIT,
  nextPresetName,
  readActivePreset,
  readPresetStore,
  readTheme,
  readThemeStyle,
  writePresetStore,
  writeTheme,
  writeThemeStyle,
  type CustomPreset,
  type CustomThemeTokens,
  type LampId,
  type ThemeId,
  type ThemeStyle,
  type WallpaperConfig,
  type WallpaperKind,
} from '../../src/lib/theme'
import { clearWallpaper, readPoster, readWallpaper } from '../../src/lib/themeImage'

type Applied = { url: string | null; kind: WallpaperKind; config: WallpaperConfig; poster?: string | null }
export function createThemeScope() {
 const objectUrl = shallowRef<string | null>(null)
 const posterUrl = shallowRef<string | null>(null)
 const applied = shallowRef<Applied | null>(null)
 const seqRef = ref(0)
 const theme = ref<ThemeId>(readTheme())
 const store = shallowRef(readPresetStore())
 const style = shallowRef(readThemeStyle())
 const lampPreview = shallowRef<{lamp: LampId; light: boolean} | null>(null)
 const video = shallowRef<{url:string; poster:string | null; config:WallpaperConfig} | null>(null)
 const setVideo = (next: typeof video.value) => { video.value = next }
 const setThemeState = (next: ThemeId) => { theme.value = next }
 const setStore = (next: typeof store.value) => { store.value = next }
 const setStyleState = (next: ThemeStyle) => { style.value = next }
 const setLampPreview = (next: typeof lampPreview.value) => { lampPreview.value = next }
 applyTheme(theme.value, readActivePreset()?.tokens, style.value)
  let preview: Applied | null = null
  const dropUrl = () => {
    if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
    if (posterUrl.value) URL.revokeObjectURL(posterUrl.value)
    objectUrl.value = null
    posterUrl.value = null
    applied.value = null
    if (!preview) setVideo(null)
  }

  const showWallpaper = async (id: string | null) => {
    // 连着切预设时两次读库会交错：拿到字节时先确认自己还是最后一次调用，
    // 否则这次新建的 URL 会被后一次顶掉、再没人撤销（单个最大 50MB）。
    const seq = ++seqRef.value
    dropUrl()
    const preset = id ? readPresetStore().items.find((item) => item.id === id) ?? null : null
    const blob = preset ? await readWallpaper(preset.id) : null
    if (seq !== seqRef.value) return
    if (!blob || !preset) {
      renderWallpaper(preview)
      return
    }
    const url = URL.createObjectURL(blob)
    objectUrl.value = url
    const config = preset.wallpaper ?? DEFAULT_WALLPAPER
    // 视频铺不到 body 的 CSS 背景上，改交给固定的 <video> 层。静帧另读，减少动态时用它。
    if (config.kind === 'video') {
      const posterBlob = await readPoster(preset.id)
      if (seq !== seqRef.value) {
        URL.revokeObjectURL(url)
        if (objectUrl.value === url) objectUrl.value = null
        return
      }
      const poster = posterBlob ? URL.createObjectURL(posterBlob) : null
      posterUrl.value = poster
      applied.value = { url, kind: 'video', config, poster }
      renderWallpaper(preview ?? applied.value)
      return
    }
    applied.value = { url, kind: config.kind, config, poster: null }
    renderWallpaper(preview ?? applied.value)
  }

  // 预览与还原都走这里：还原用的是留着的那份句柄，不再回头读库，免得异步回来后盖掉草稿
  function renderWallpaper(next: Applied | null) {
    if (!next?.url) {
      setVideo(null)
      applyWallpaper(null)
      return
    }
    if (next.kind === 'video') {
      applyWallpaper(null)
      setVideo({ url: next.url, poster: next.poster ?? null, config: next.config })
      return
    }
    setVideo(null)
    applyWallpaper(next.url, next.config)
  }

  const setWallpaperPreview = (next: Applied | null) => {
    preview = next
    renderWallpaper(preview ?? applied.value)
  }

  const persist = (next: typeof store.value, nextTheme: ThemeId) => {
    writePresetStore(next)
    writeTheme(nextTheme)
    setStore(next)
    setThemeState(nextTheme)
  }

  const setTheme = (id: Exclude<ThemeId, 'custom'>) => {
    applyTheme(id, undefined, style.value)
    persist(readPresetStore(), id)
    void showWallpaper(null)
  }

  const selectPreset = (id: string) => {
    const current = readPresetStore()
    const preset = current.items.find((item) => item.id === id)
    if (!preset) return
    const next = { items: current.items, activeId: id }
    applyTheme('custom', preset.tokens, style.value)
    persist(next, 'custom')
    void showWallpaper(id)
  }

  // 新建的预设只在编辑器的草稿里存在，直到「保存这套」才第一次写盘；所以不存在的 id 要能插入。
  const savePreset = (
    id: string,
    name: string,
    tokens: CustomThemeTokens,
    wallpaper: WallpaperConfig,
  ) => {
    const current = readPresetStore()
    const exists = current.items.some((item) => item.id === id)
    if (!exists && current.items.length >= PRESET_LIMIT) return
    const entry: CustomPreset = {
      id,
      name: name.trim() || nextPresetName(current.items),
      tokens,
      wallpaper,
    }
    const items = exists
      ? current.items.map((item) => (item.id === id ? entry : item))
      : [...current.items, entry]
    const next = { items, activeId: id }
    applyTheme('custom', tokens, style.value)
    persist(next, 'custom')
    void showWallpaper(id)
  }

  // 字体与透明度是账号级的：官方三套一样跟着走，所以存完要按当前主题重新铺一遍
  const saveStyle = (next: ThemeStyle) => {
    writeThemeStyle(next)
    setStyleState(next)
    const current = readPresetStore()
    applyTheme(readTheme(), current.items.find((item) => item.id === current.activeId)?.tokens, next)
  }

  const deletePreset = (id: string) => {
    const current = readPresetStore()
    const items = current.items.filter((item) => item.id !== id)
    const activeId = current.activeId === id ? items[0]?.id ?? null : current.activeId
    const next = { items, activeId }
    writePresetStore(next)
    setStore(next)
    void clearWallpaper(id)
    if (readTheme() !== 'custom' || current.activeId !== id) return
    if (!activeId) {
      applyTheme('paper', undefined, style.value)
      writeTheme('paper')
      setThemeState('paper')
      void showWallpaper(null)
      return
    }
    const preset = items.find((item) => item.id === activeId)
    if (!preset) return
    applyTheme('custom', preset.tokens, style.value)
    writeTheme('custom')
    void showWallpaper(activeId)
  }


 let started = false
 function start() { if (started) return; started = true; void showWallpaper(theme.value === 'custom' ? store.value.activeId : null) }
 function dispose() { ++seqRef.value; started = false; preview = null; dropUrl(); applyWallpaper(null) }
 return {theme, presets: computed(() => store.value.items), activePresetId: computed(() => store.value.activeId), style, lampPreview, video, setTheme, selectPreset, savePreset, deletePreset, saveStyle, setWallpaperPreview, setLampPreview, start, dispose}
}
export type ThemeScope = ReturnType<typeof createThemeScope>
export const themeKey: InjectionKey<ThemeScope> = Symbol('theme')
export function useTheme(): ThemeScope {
 const scope = inject(themeKey)
 if (!scope) throw new Error('Theme scope is missing')
 return scope
}
