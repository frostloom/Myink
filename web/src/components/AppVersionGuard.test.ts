import { describe, expect, it } from 'vitest'
import { bundlePathFromIndex, isDifferentBundle } from './AppVersionGuard.utils'

describe('AppVersionGuard', () => {
  it('extracts the hashed entry bundle from the index page', () => {
    expect(
      bundlePathFromIndex(
        '<html><head><script type="module" crossorigin src="/assets/index-new123.js"></script></head></html>',
      ),
    ).toBe('/assets/index-new123.js')
  })

  it('ignores pages without a production entry bundle', () => {
    expect(bundlePathFromIndex('<script type="module" src="/src/main.tsx"></script>')).toBeNull()
  })

  it('reloads only when both valid bundle paths differ', () => {
    expect(isDifferentBundle('/assets/index-old.js', '/assets/index-new.js')).toBe(true)
    expect(isDifferentBundle('/assets/index-new.js', '/assets/index-new.js')).toBe(false)
    expect(isDifferentBundle(null, '/assets/index-new.js')).toBe(false)
  })
})
