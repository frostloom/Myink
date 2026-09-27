import { expect, it } from 'vitest'
import { WALLPAPER_VIDEO_MAX_BYTES, wallpaperError, wallpaperKindOf } from './themeImage'

it('accepts a small image and rejects the rest', () => {
  expect(wallpaperError(new File(['x'], 'a.png', { type: 'image/png' }))).toBeNull()
  expect(wallpaperError(new File(['x'], 'a.txt', { type: 'text/plain' })))
    .toBe('只要 jpg / png / webp / gif 图片或 mp4 / webm 视频')
  const big = new File([new Uint8Array(2 * 1024 * 1024 + 1)], 'a.png', { type: 'image/png' })
  expect(wallpaperError(big)).toBe('图片不要超过 2 MB')
})

it('takes mp4 / webm within the larger video budget', () => {
  const mp4 = new File([new Uint8Array(4)], 'a.mp4', { type: 'video/mp4' })
  expect(wallpaperKindOf(mp4)).toBe('video')
  expect(wallpaperError(mp4)).toBeNull()

  // quicktime 等在反馈附件里收，但浏览器能不能当背景播是另一回事，这里不收
  expect(wallpaperError(new File([new Uint8Array(4)], 'a.mov', { type: 'video/quicktime' })))
    .toBe('只要 jpg / png / webp / gif 图片或 mp4 / webm 视频')

  const huge = new File([new Uint8Array(WALLPAPER_VIDEO_MAX_BYTES + 1)], 'a.mp4', { type: 'video/mp4' })
  expect(wallpaperError(huge)).toBe('视频不要超过 50 MB')
})
