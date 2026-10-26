import { beforeEach, expect, it, vi } from 'vitest'
import { createThemeScope } from './themeContext'
import { DEFAULT_CUSTOM_TOKENS, DEFAULT_WALLPAPER, readPresetStore, readThemeStyle, readTheme } from '../../src/lib/theme'
beforeEach(() => { localStorage.clear(); vi.stubGlobal('URL', {createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn()}) })
it('persists presets only when saved and falls back to paper after final deletion', () => {
 const scope = createThemeScope()
 scope.savePreset('one', '我的主题', DEFAULT_CUSTOM_TOKENS, DEFAULT_WALLPAPER)
 expect(scope.theme.value).toBe('custom')
 expect(readPresetStore().activeId).toBe('one')
 scope.deletePreset('one')
 expect(scope.theme.value).toBe('paper')
 expect(readTheme()).toBe('paper')
 scope.dispose()
})
it('saves font and opacity for official themes as well', () => {
 const scope = createThemeScope(); scope.setTheme('paper')
 scope.saveStyle({ ...scope.style.value, chromeOpacity: 40 })
 expect(readThemeStyle().chromeOpacity).toBe(40)
 expect(scope.style.value.chromeOpacity).toBe(40)
 scope.dispose()
})
