import { render, cleanup } from '@testing-library/vue'
import { afterEach, expect, it, vi } from 'vitest'
import CanvasMedia from './CanvasMedia.vue'
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('plays video when motion is allowed', () => {
 vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
 const { container } = render(CanvasMedia, { props: { url: 'blob:video', poster: 'blob:poster' } })
 expect(container.querySelector('video')?.autoplay).toBe(true)
 expect(container.querySelector('video')?.getAttribute('poster')).toBe('blob:poster')
})
it('shows saved poster for reduced motion', () => {
 vi.stubGlobal('matchMedia', () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
 const { container } = render(CanvasMedia, { props: { url: 'blob:video', poster: 'blob:poster' } })
 expect(container.querySelector('video')).toBeNull()
 expect(container.querySelector('img')?.getAttribute('src')).toBe('blob:poster')
})
