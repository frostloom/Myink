// 自定义背景：按预设 id 存在本机 IndexedDB。视频还多存一张首帧静帧，
// 列表和对话框用它当缩略图——不然一页里会同时播好几个 <video>。

export const WALLPAPER_IMAGE_MAX_BYTES = 2 * 1024 * 1024
export const WALLPAPER_VIDEO_MAX_BYTES = 50 * 1024 * 1024

export const WALLPAPER_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif'])
export const WALLPAPER_VIDEO_TYPES = new Set(['video/mp4', 'video/webm'])

const DB_NAME = 'myink-theme'
const STORE = 'files'
const LEGACY_KEY = 'wallpaper'
const POSTER_SUFFIX = ':poster'

const memory = new Map<string, Blob>()

export function wallpaperKindOf(file: File): 'image' | 'video' | null {
  if (WALLPAPER_IMAGE_TYPES.has(file.type)) return 'image'
  if (WALLPAPER_VIDEO_TYPES.has(file.type)) return 'video'
  return null
}

export function wallpaperError(file: File): string | null {
  const kind = wallpaperKindOf(file)
  if (!kind) return '只要 jpg / png / webp / gif 图片或 mp4 / webm 视频'
  if (kind === 'video') {
    return file.size > WALLPAPER_VIDEO_MAX_BYTES ? '视频不要超过 50 MB' : null
  }
  return file.size > WALLPAPER_IMAGE_MAX_BYTES ? '图片不要超过 2 MB' : null
}

/** 视频首帧当缩略图。抓不到（解码失败、无 DOM）就返回空，界面退回纯色块。 */
export async function captureVideoPoster(source: Blob): Promise<{ poster: Blob | null; aspect: number | null }> {
  if (typeof document === 'undefined' || typeof URL.createObjectURL !== 'function') {
    return { poster: null, aspect: null }
  }
  const url = URL.createObjectURL(source)
  const video = document.createElement('video')
  video.muted = true
  video.playsInline = true
  video.preload = 'auto'
  video.src = url
  try {
    const ready = await new Promise<boolean>((resolve) => {
      video.onloadeddata = () => resolve(true)
      video.onerror = () => resolve(false)
    })
    if (!ready || video.videoWidth === 0) return { poster: null, aspect: null }
    // 不少片子开头是黑场，往后挪一帧再抓
    const at = Math.min(0.15, (video.duration || 0) / 10)
    if (at > 0) {
      await new Promise<void>((resolve) => {
        const done = () => resolve()
        video.onseeked = done
        window.setTimeout(done, 1200)
        video.currentTime = at
      })
    }
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return { poster: null, aspect: video.videoWidth / video.videoHeight }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const poster = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob((blob) => resolve(blob), 'image/webp', 0.8)
    })
    return { poster, aspect: video.videoWidth / video.videoHeight }
  } catch {
    return { poster: null, aspect: null }
  } finally {
    URL.revokeObjectURL(url)
  }
}

function openDb(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') return Promise.resolve(null)
  return new Promise((resolve) => {
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => resolve(null)
  })
}

function getBlob(db: IDBDatabase, key: string): Promise<Blob | null> {
  return new Promise((resolve) => {
    const req = db.transaction(STORE, 'readonly').objectStore(STORE).get(key)
    req.onsuccess = () => resolve(req.result instanceof Blob ? req.result : null)
    req.onerror = () => resolve(null)
  })
}

export async function readWallpaper(id: string): Promise<Blob | null> {
  const db = await openDb()
  if (!db) return memory.get(id) ?? (id === 'legacy' ? memory.get(LEGACY_KEY) ?? null : null)
  const found = await getBlob(db, id)
  if (found) return found
  if (id !== 'legacy') return null
  return getBlob(db, LEGACY_KEY)
}

/** 与壁纸分开存：读视频预设时两样都要，读缩略图时只要这一张。 */
export async function readPoster(id: string): Promise<Blob | null> {
  const key = `${id}${POSTER_SUFFIX}`
  const db = await openDb()
  if (!db) return memory.get(key) ?? null
  return getBlob(db, key)
}

async function put(db: IDBDatabase | null, key: string, blob: Blob): Promise<void> {
  memory.set(key, blob)
  if (!db) return
  await new Promise<void>((resolve) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(blob, key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => resolve()
  })
}

export async function writeWallpaper(id: string, blob: Blob): Promise<void> {
  await put(await openDb(), id, blob)
}

export async function writePoster(id: string, blob: Blob): Promise<void> {
  await put(await openDb(), `${id}${POSTER_SUFFIX}`, blob)
}

export async function clearWallpaper(id: string): Promise<void> {
  const keys = [id, `${id}${POSTER_SUFFIX}`]
  if (id === 'legacy') keys.push(LEGACY_KEY)
  for (const key of keys) memory.delete(key)
  const db = await openDb()
  if (!db) return
  await new Promise<void>((resolve) => {
    const tx = db.transaction(STORE, 'readwrite')
    for (const key of keys) tx.objectStore(STORE).delete(key)
    tx.oncomplete = () => resolve()
    tx.onerror = () => resolve()
  })
}
