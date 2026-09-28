// 用户自选的动态背景层。CSS 背景放不了视频，只能单开一层固定定位的 <video>
// 垫在 #root 下面（负 z-index 画在 body 背景之上、页面内容之下）。
import { useEffect, useRef } from 'react'
import { usePrefersReducedMotion } from '../hooks/usePrefersReducedMotion'
import { DEFAULT_WALLPAPER, type WallpaperConfig } from '../lib/theme'
import styles from './CanvasMedia.module.css'

export function CanvasMedia({ url, poster = null, config = DEFAULT_WALLPAPER }: {
  url: string
  poster?: string | null
  config?: WallpaperConfig
}) {
  const still = usePrefersReducedMotion()
  const videoRef = useRef<HTMLVideoElement>(null)
  const wasStill = useRef(still)

  // autoPlay 只在挂载时生效。系统设置中途切换时，要自己停或接着播。
  useEffect(() => {
    const video = videoRef.current
    const previous = wasStill.current
    wasStill.current = still
    if (!video || previous === still) return
    if (still) {
      video.pause?.()
      return
    }
    const played = video.play?.()
    if (played && typeof played.catch === 'function') void played.catch(() => {})
  }, [still])

  const scale = config.zoom / 100
  const frame = {
    objectPosition: `${config.x}% ${config.y}%`,
    transform: scale === 1 ? undefined : `scale(${scale})`,
  }
  return (
    <div className={styles.canvas} aria-hidden="true">
      {still && poster ? (
        // 首帧经常是黑场，静帧用保存时抓的那一张，而不是停在第 0 秒
        <img className={styles.video} src={poster} alt="" style={frame} />
      ) : (
        <video
          ref={videoRef}
          className={styles.video}
          src={url}
          poster={poster ?? undefined}
          autoPlay={!still}
          muted
          loop
          playsInline
          preload="auto"
          disablePictureInPicture
          style={frame}
        />
      )}
      {/* 暗化层：标题直接铺在背景上，视频内容又不可控，太浅正文会融进去 */}
      <span className={styles.scrim} />
    </div>
  )
}
