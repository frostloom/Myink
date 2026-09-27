// 用户自选的动态背景层。CSS 背景放不了视频，只能单开一层固定定位的 <video>
// 垫在 #root 下面（负 z-index 画在 body 背景之上、页面内容之下）。
import { useEffect, useState } from 'react'
import { DEFAULT_WALLPAPER, type WallpaperConfig } from '../lib/theme'
import styles from './CanvasMedia.module.css'

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function CanvasMedia({ url, config = DEFAULT_WALLPAPER }: {
  url: string
  config?: WallpaperConfig
}) {
  const [still, setStill] = useState(prefersReducedMotion)

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setStill(query.matches)
    sync()
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])

  const scale = config.zoom / 100
  return (
    <div className={styles.canvas} aria-hidden="true">
      <video
        className={styles.video}
        src={url}
        // 要求减少动态时停成一张静帧：整页连续动画是最该让路的一类
        autoPlay={!still}
        muted
        loop
        playsInline
        preload="auto"
        disablePictureInPicture
        style={{
          objectPosition: `${config.x}% ${config.y}%`,
          transform: scale === 1 ? undefined : `scale(${scale})`,
        }}
      />
      {/* 暗化层：视频内容不可控，没有它正文的对比度守不住 */}
      <span className={styles.scrim} />
    </div>
  )
}
