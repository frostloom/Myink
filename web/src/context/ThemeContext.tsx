import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
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
} from '../lib/theme'
import { clearWallpaper, readPoster, readWallpaper } from '../lib/themeImage'
import { CanvasMedia } from '../components/CanvasMedia'

/** 当前正铺着的背景。主题页要能「还原」回它，所以要留着句柄；url 为 null 表示什么都别铺。
 * poster 只有视频有：减少动态时用这张静帧，而不是停在经常发黑的第 0 秒。 */
type Applied = { url: string | null; kind: WallpaperKind; config: WallpaperConfig; poster?: string | null }

interface ThemeContextValue {
  theme: ThemeId
  presets: CustomPreset[]
  activePresetId: string | null
  style: ThemeStyle
  setTheme: (id: Exclude<ThemeId, 'custom'>) => void
  selectPreset: (id: string) => void
  savePreset: (id: string, name: string, tokens: CustomThemeTokens, wallpaper: WallpaperConfig) => void
  deletePreset: (id: string) => void
  saveStyle: (style: ThemeStyle) => void
  /** 主题页草稿的实时预览；传 null 还原成盘上那套。URL 由调用方持有，这里只管铺。 */
  setWallpaperPreview: (preview: Applied | null) => void
  /** 吊灯草稿。主题页改灯型或开关灯光时，右上角那只灯立刻跟着变，离开页面就丢掉。 */
  lampPreview: { lamp: LampId; light: boolean } | null
  setLampPreview: (preview: { lamp: LampId; light: boolean } | null) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const objectUrl = useRef<string | null>(null)
  const posterUrl = useRef<string | null>(null)
  const applied = useRef<Applied | null>(null)
  const seqRef = useRef(0)
  const [theme, setThemeState] = useState<ThemeId>(() => {
    const initial = readTheme()
    applyTheme(initial, readActivePreset()?.tokens, readThemeStyle())
    return initial
  })
  const [store, setStore] = useState(() => readPresetStore())
  const [style, setStyleState] = useState<ThemeStyle>(() => readThemeStyle())
  const [lampPreview, setLampPreview] = useState<{ lamp: LampId; light: boolean } | null>(null)
  const [video, setVideo] = useState<{ url: string; poster: string | null; config: WallpaperConfig } | null>(null)

  const dropUrl = useCallback(() => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    if (posterUrl.current) URL.revokeObjectURL(posterUrl.current)
    objectUrl.current = null
    posterUrl.current = null
    applied.current = null
    setVideo(null)
  }, [])

  const showWallpaper = useCallback(async (id: string | null) => {
    // 连着切预设时两次读库会交错：拿到字节时先确认自己还是最后一次调用，
    // 否则这次新建的 URL 会被后一次顶掉、再没人撤销（单个最大 50MB）。
    const seq = ++seqRef.current
    dropUrl()
    const preset = id ? readPresetStore().items.find((item) => item.id === id) ?? null : null
    const blob = preset ? await readWallpaper(preset.id) : null
    if (seq !== seqRef.current) return
    if (!blob || !preset) {
      applyWallpaper(null)
      return
    }
    const url = URL.createObjectURL(blob)
    objectUrl.current = url
    const config = preset.wallpaper ?? DEFAULT_WALLPAPER
    // 视频铺不到 body 的 CSS 背景上，改交给固定的 <video> 层。静帧另读，减少动态时用它。
    if (config.kind === 'video') {
      const posterBlob = await readPoster(preset.id)
      if (seq !== seqRef.current) {
        URL.revokeObjectURL(url)
        if (objectUrl.current === url) objectUrl.current = null
        return
      }
      const poster = posterBlob ? URL.createObjectURL(posterBlob) : null
      posterUrl.current = poster
      applied.current = { url, kind: 'video', config, poster }
      applyWallpaper(null)
      setVideo({ url, poster, config })
      return
    }
    applied.current = { url, kind: config.kind, config, poster: null }
    applyWallpaper(url, config)
  }, [dropUrl])

  useEffect(() => {
    const current = readPresetStore()
    void showWallpaper(readTheme() === 'custom' ? current.activeId : null)
    return () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
      if (posterUrl.current) URL.revokeObjectURL(posterUrl.current)
    }
  }, [showWallpaper])

  // 预览与还原都走这里：还原用的是留着的那份句柄，不再回头读库，免得异步回来后盖掉草稿
  const setWallpaperPreview = useCallback((preview: Applied | null) => {
    const next = preview ?? applied.current
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
  }, [])

  const persist = useCallback((next: typeof store, nextTheme: ThemeId) => {
    writePresetStore(next)
    writeTheme(nextTheme)
    setStore(next)
    setThemeState(nextTheme)
  }, [])

  const setTheme = useCallback((id: Exclude<ThemeId, 'custom'>) => {
    applyTheme(id, undefined, style)
    persist(readPresetStore(), id)
    void showWallpaper(null)
  }, [persist, showWallpaper, style])

  const selectPreset = useCallback((id: string) => {
    const current = readPresetStore()
    const preset = current.items.find((item) => item.id === id)
    if (!preset) return
    const next = { items: current.items, activeId: id }
    applyTheme('custom', preset.tokens, style)
    persist(next, 'custom')
    void showWallpaper(id)
  }, [persist, showWallpaper, style])

  // 新建的预设只在编辑器的草稿里存在，直到「保存这套」才第一次写盘；所以不存在的 id 要能插入。
  const savePreset = useCallback((
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
    applyTheme('custom', tokens, style)
    persist(next, 'custom')
    void showWallpaper(id)
  }, [persist, showWallpaper, style])

  // 字体与透明度是账号级的：官方三套一样跟着走，所以存完要按当前主题重新铺一遍
  const saveStyle = useCallback((next: ThemeStyle) => {
    writeThemeStyle(next)
    setStyleState(next)
    const current = readPresetStore()
    applyTheme(readTheme(), current.items.find((item) => item.id === current.activeId)?.tokens, next)
  }, [])

  const deletePreset = useCallback((id: string) => {
    const current = readPresetStore()
    const items = current.items.filter((item) => item.id !== id)
    const activeId = current.activeId === id ? items[0]?.id ?? null : current.activeId
    const next = { items, activeId }
    writePresetStore(next)
    setStore(next)
    void clearWallpaper(id)
    if (readTheme() !== 'custom' || current.activeId !== id) return
    if (!activeId) {
      applyTheme('paper', undefined, style)
      writeTheme('paper')
      setThemeState('paper')
      void showWallpaper(null)
      return
    }
    const preset = items.find((item) => item.id === activeId)
    if (!preset) return
    applyTheme('custom', preset.tokens, style)
    writeTheme('custom')
    void showWallpaper(activeId)
  }, [showWallpaper, style])

  const value = useMemo(
    () => ({
      theme,
      presets: store.items,
      activePresetId: store.activeId,
      style,
      setTheme,
      selectPreset,
      savePreset,
      deletePreset,
      saveStyle,
      setWallpaperPreview,
      lampPreview,
      setLampPreview,
    }),
    [theme, store, style, setTheme, selectPreset, savePreset, deletePreset, saveStyle, setWallpaperPreview, lampPreview],
  )
  return (
    <ThemeContext.Provider value={value}>
      {video && <CanvasMedia url={video.url} poster={video.poster} config={video.config} />}
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme 必须在 ThemeProvider 内使用')
  return ctx
}
