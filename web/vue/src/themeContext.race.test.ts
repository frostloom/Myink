import { beforeEach, expect, it, vi } from 'vitest'
import { createThemeScope } from './themeContext'
import { DEFAULT_CUSTOM_TOKENS, DEFAULT_WALLPAPER } from '../../src/lib/theme'
import { readWallpaper } from '../../src/lib/themeImage'
vi.mock('../../src/lib/themeImage',()=>({readWallpaper:vi.fn(),readPoster:vi.fn(async()=>null),clearWallpaper:vi.fn(async()=>{})}))
beforeEach(()=>{localStorage.clear();URL.createObjectURL=vi.fn(()=> 'blob:saved');URL.revokeObjectURL=vi.fn()})
it('a delayed saved wallpaper cannot replace an active draft preview',async()=>{let resolve!:(blob:Blob)=>void;vi.mocked(readWallpaper).mockImplementation(()=>new Promise(r=>{resolve=r}));const scope=createThemeScope();scope.savePreset('p','主题',DEFAULT_CUSTOM_TOKENS,DEFAULT_WALLPAPER);scope.setWallpaperPreview({url:'blob:draft',kind:'image',config:DEFAULT_WALLPAPER});resolve(new Blob(['x']));await Promise.resolve();expect(document.documentElement.style.getPropertyValue('--canvas-image')).toContain('blob:draft');scope.setWallpaperPreview(null);expect(document.documentElement.style.getPropertyValue('--canvas-image')).toContain('blob:saved');scope.dispose()})
it('does not create a media URL after disposal while an indexedDB read is pending',async()=>{let resolve!:(blob:Blob)=>void;vi.mocked(readWallpaper).mockImplementation(()=>new Promise(r=>{resolve=r}));const scope=createThemeScope();scope.savePreset('p','主题',DEFAULT_CUSTOM_TOKENS,DEFAULT_WALLPAPER);scope.dispose();resolve(new Blob(['x']));await Promise.resolve();expect(URL.createObjectURL).not.toHaveBeenCalled()})
