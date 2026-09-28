// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { CanvasMedia } from './CanvasMedia'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function stubMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
    matches: reduce && query.includes('prefers-reduced-motion'),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })))
}

it('plays the video when motion is allowed', () => {
  stubMotion(false)
  const { container } = render(<CanvasMedia url="blob:video" poster="blob:poster" />)
  const video = container.querySelector('video')
  expect(video).toBeTruthy()
  expect(video?.getAttribute('poster')).toBe('blob:poster')
  expect(video?.autoplay).toBe(true)
  expect(container.querySelector('img')).toBeNull()
})

it('uses the saved still instead of a black first frame when motion is reduced', () => {
  stubMotion(true)
  const { container } = render(<CanvasMedia url="blob:video" poster="blob:poster" />)
  expect(container.querySelector('video')).toBeNull()
  expect(container.querySelector('img')?.getAttribute('src')).toBe('blob:poster')
})
