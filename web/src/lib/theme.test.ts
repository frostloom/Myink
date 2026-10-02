// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import {
  applyTheme,
  applyWallpaper,
  clampLampX,
  clampLampY,
  DEFAULT_LAMP_X,
  DEFAULT_LAMP_Y,
  LAMP_POS_KEY,
  LAMP_X_KEY,
  readLampPlace,
  settleLampDrop,
  writeLampPlace,
  CUSTOM_THEME_STORAGE_KEY,
  CUSTOM_INLINE_VARS,
  DEFAULT_CUSTOM_TOKENS,
  DEFAULT_THEME_STYLE,
  DEFAULT_WALLPAPER,
  PRESET_STORAGE_KEY,
  SHELL_TOKEN_NAMES,
  STYLE_STORAGE_KEY,
  isHexColor,
  nextPresetName,
  officialThemeColor,
  parseWallpaper,
  readActivePreset,
  readPresetStore,
  readTheme,
  readThemeStyle,
  THEME_FONTS,
  THEME_SHELLS,
  THEME_STORAGE_KEY,
  TOKENS_CSS_VAR_NAMES,
  writePresetStore,
  writeTheme,
  writeThemeStyle,
} from './theme'

afterEach(() => {
  localStorage.clear()
  // 一次性抹掉所有内联变量：主题会把一堆变量写到 html 上，逐个列举容易漏
  document.documentElement.removeAttribute('style')
  document.documentElement.removeAttribute('data-theme')
})

function cssVar(name: string): string {
  return document.documentElement.style.getPropertyValue(name)
}

it('reads paper when nothing is stored or the payload is broken', () => {
  expect(readTheme()).toBe('paper')
  localStorage.setItem(THEME_STORAGE_KEY, 'neon')
  expect(readTheme()).toBe('paper')
})

it('persists a valid theme and applies it to the document', () => {
  writeTheme('night')
  expect(readTheme()).toBe('night')
  applyTheme('night')
  expect(document.documentElement.getAttribute('data-theme')).toBe('night')
  expect(document.documentElement.style.colorScheme).toBe('dark')

  applyTheme('paper')
  expect(document.documentElement.getAttribute('data-theme')).toBeNull()
  expect(document.documentElement.style.colorScheme).toBe('light')
})

it('migrates the old single custom pack into one preset', () => {
  expect(isHexColor('#1c1a18')).toBe(true)
  expect(isHexColor('blue')).toBe(false)
  localStorage.setItem(CUSTOM_THEME_STORAGE_KEY, JSON.stringify({
    canvas: '#1c1a18',
    ink: '#ebe6dc',
    editor: '#141311',
    editorInk: '#f0ebe3',
    accent: '#7ab88d',
  }))
  const store = readPresetStore()
  expect(store.items).toHaveLength(1)
  expect(store.items[0].name).toBe('自定义 1')
  expect(store.items[0].tokens.canvas).toBe('#1c1a18')
  applyTheme('custom', store.items[0].tokens)
  expect(document.documentElement.getAttribute('data-theme')).toBe('custom')
  expect(document.documentElement.style.getPropertyValue('--canvas')).toBe('#1c1a18')
})

it('keeps several named presets and remembers the active one', () => {
  writePresetStore({
    activeId: 'p2',
    items: [
      { id: 'p1', name: '白天', tokens: readActivePreset()?.tokens ?? DEFAULT_CUSTOM_TOKENS, wallpaper: DEFAULT_WALLPAPER },
      { id: 'p2', name: '夜里', tokens: {
        ...DEFAULT_CUSTOM_TOKENS,
        canvas: '#121212', ink: '#e6e6e6', editor: '#181818', editorInk: '#e6e6e6', accent: '#7dba90',
      }, wallpaper: DEFAULT_WALLPAPER },
    ],
  })
  expect(readActivePreset()?.name).toBe('夜里')
  expect(nextPresetName(readPresetStore().items)).toBe('自定义 1')
  localStorage.setItem(PRESET_STORAGE_KEY, '{"items":[{"id":1}]}')
  expect(readPresetStore().items).toEqual([])
})

it('renames old 预设 labels to 自定义', () => {
  writePresetStore({
    activeId: 'p1',
    items: [{
      id: 'p1',
      name: '预设 1',
      tokens: { ...DEFAULT_CUSTOM_TOKENS },
      wallpaper: DEFAULT_WALLPAPER,
    }],
  })
  expect(readPresetStore().items[0].name).toBe('自定义 1')
})

it('fades the editor paper and the selections to the chrome opacity too', () => {
  applyTheme('custom', DEFAULT_CUSTOM_TOKENS, { ...DEFAULT_THEME_STYLE, chromeOpacity: 40, font: 'kai', fontSize: 'l' })
  expect(cssVar('--surface-1')).toBe('rgba(255, 253, 247, 0.34)')
  // 正文纸跟外壳同一个滑块，只是层级更高，靠亮度区分而不是靠不透明
  expect(cssVar('--editor')).toBe('rgba(255, 253, 247, 0.4)')
  expect(cssVar('--accent-soft')).toBe('rgba(159, 216, 173, 0.24)')
  expect(cssVar('--line')).toBe('rgba(63, 58, 54, 0.08)')
  expect(cssVar('--font-editor')).toContain('Kaiti')
  expect(cssVar('--font-ui')).toContain('sans-serif')
  expect(cssVar('--font-ui')).not.toContain('Kaiti')
  expect(cssVar('--text-editor')).toBe('19px')
})

it('gives the official themes the same font and opacity knobs', () => {
  applyTheme('night', undefined, { ...DEFAULT_THEME_STYLE, chromeOpacity: 40, font: 'hei', fontSize: 'xl' })
  expect(document.documentElement.getAttribute('data-theme')).toBe('night')
  expect(cssVar('--surface-1')).toBe('rgba(28, 28, 28, 0.4)')
  expect(cssVar('--editor')).toBe('rgba(24, 24, 24, 0.4)')
  expect(cssVar('--accent-soft')).toBe('rgba(30, 42, 34, 0.4)')
  expect(cssVar('--font-editor')).toContain('Heiti')
  expect(cssVar('--font-ui')).toContain('Microsoft YaHei UI')
  expect(cssVar('--text-editor')).toBe('21px')

  // 换回纸感：夜间的内联底色必须清掉，否则会盖住样式表
  applyTheme('paper', undefined, { ...DEFAULT_THEME_STYLE, chromeOpacity: 40, font: 'hei', fontSize: 'xl' })
  // 面板底现在是不透明色（见 tokens.css），所以拉低透明度时 alpha 就等于档位本身，不再乘 0.86
  expect(cssVar('--surface-1')).toBe('rgba(251, 248, 241, 0.4)')
  expect(cssVar('--editor')).toBe('rgba(255, 253, 249, 0.4)')
})

it('leaves the official themes on the stylesheet at full opacity', () => {
  applyTheme('paper')
  expect(cssVar('--surface-1')).toBe('')
  expect(cssVar('--editor')).toBe('')
  expect(cssVar('--line')).toBe('')
  // 只有排版变量会被写上：字号和 tokens.css 原值一致，字体按选中的档位整页生效
  expect(cssVar('--font-ui')).toContain('sans-serif')
  expect(cssVar('--font-editor')).toBe(THEME_FONTS.find((font) => font.id === 'hei')?.css)
  expect(cssVar('--text-editor')).toBe('17px')
})

it('keeps font and opacity at the account level instead of inside a preset', () => {
  expect(readThemeStyle()).toEqual(DEFAULT_THEME_STYLE)
  writeThemeStyle({ ...DEFAULT_THEME_STYLE, chromeOpacity: 55, font: 'kai', fontSize: 'l' })
  expect(readThemeStyle()).toEqual({ ...DEFAULT_THEME_STYLE, chromeOpacity: 55, font: 'kai', fontSize: 'l' })

  localStorage.setItem(STYLE_STORAGE_KEY, '{"chromeOpacity":900,"font":"comic","fontSize":"xxl","lamp":"neon","lampLight":"yes"}')
  expect(readThemeStyle()).toEqual(DEFAULT_THEME_STYLE)
})

it('keeps every shell token defined in tokens.css for all three official themes', () => {
  // 这 13 个是透明度滑杆要稀释的层。任何一处在某个主题块里漏写，THEME_SHELLS 就会拿到空值，
  // 那一层在拉低透明度时静默不生效——所以宁可红。
  expect(SHELL_TOKEN_NAMES).toHaveLength(13)
  for (const [theme, pairs] of Object.entries(THEME_SHELLS)) {
    expect(pairs.map(([name]) => name)).toEqual([...SHELL_TOKEN_NAMES])
    for (const [name, value] of pairs) {
      expect(value, `${theme} 主题里 ${name} 没在 tokens.css 定义`).not.toBe('')
      expect(TOKENS_CSS_VAR_NAMES.has(name), `${name} 不在 tokens.css 里`).toBe(true)
    }
  }
})

it('only clears variables that tokens.css actually defines', () => {
  // 退出自定义主题时逐个 removeProperty。清单里混进一个不存在的名字不会报错，
  // 但真正的名字漏了就会被上一套的自定义色盖住——所以清单里的每一项都必须在 tokens.css 里有出处。
  expect(CUSTOM_INLINE_VARS.length).toBeGreaterThan(0)
  expect(CUSTOM_INLINE_VARS.filter((name) => !TOKENS_CSS_VAR_NAMES.has(name))).toEqual([])
})

it('derives the display tiers from the knob-driven ones', () => {
  // 阅读字号旋钮只写 body / small / heading / editor 四档；micro / title / display 在 tokens.css
  // 里用 calc 挂在它们身上，所以换档时比例恒定。原来 h1 硬编码 34px，正文调到「小」标题不缩。
  // jsdom 不求值 calc，这里断言的是依赖关系；算出来的像素值由浏览器记分卡核。
  expect(officialThemeColor('paper', '--text-micro')).toContain('var(--text-small)')
  expect(officialThemeColor('paper', '--text-title')).toContain('var(--text-body)')
  expect(officialThemeColor('paper', '--text-display')).toContain('var(--text-body)')
})

it('places the lamp anywhere and tucks it away when dragged to the ceiling', () => {
  expect(readLampPlace(1000, 800, 80)).toEqual({ x: DEFAULT_LAMP_X, y: DEFAULT_LAMP_Y, hidden: false })
  expect(clampLampX(-1, 1000)).toBeCloseTo(0.036)
  expect(clampLampY(0.4, 800, 80)).toBeCloseTo(0.4)
  expect(settleLampDrop(0.01, 800, 80)).toEqual({ y: 0, hidden: true })

  localStorage.setItem(LAMP_X_KEY, '0.4')
  expect(readLampPlace(1000, 800, 80).x).toBe(0.4)

  writeLampPlace({ x: 0.3, y: 0, hidden: true }, 1000, 800, 80)
  expect(JSON.parse(localStorage.getItem(LAMP_POS_KEY) || '{}').hidden).toBe(true)
  expect(readLampPlace(1000, 800, 80)).toEqual({ x: 0.3, y: 0, hidden: true })
})

it('keeps a saved serif reading preference without applying it to small UI text', () => {
  writeThemeStyle({ ...DEFAULT_THEME_STYLE, font: 'song', fontSize: 'm', chromeOpacity: 100 })
  applyTheme('paper', undefined, readThemeStyle())
  expect(cssVar('--font-editor')).toContain('SimSun')
  expect(cssVar('--font-ui')).toContain('sans-serif')
  expect(cssVar('--font-ui')).not.toContain('SimSun')
  expect(readThemeStyle().font).toBe('song')
})

it('applies a wallpaper only as a CSS image variable', () => {
  applyWallpaper('blob:http://localhost/demo')
  expect(document.documentElement.style.getPropertyValue('--canvas-image')).toBe(
    'url("blob:http://localhost/demo")',
  )
  applyTheme('night')
  expect(document.documentElement.style.getPropertyValue('--canvas-image')).toBe('')
})

it('covers the viewport at any aspect and lets zoom push past the edges', () => {
  applyWallpaper('blob:x', { kind: 'image', fit: 'cover', zoom: 100, x: 50, y: 50, aspect: 2 })
  expect(document.documentElement.style.getPropertyValue('--canvas-size')).toBe(
    'calc(max(100vw, 200vh) * 1) calc(max(50vw, 100vh) * 1)',
  )
  expect(document.documentElement.style.getPropertyValue('--canvas-position')).toBe('50% 50%')
  expect(document.documentElement.style.getPropertyValue('--canvas-repeat')).toBe('no-repeat')

  applyWallpaper('blob:x', { kind: 'image', fit: 'cover', zoom: 150, x: 0, y: 100, aspect: 2 })
  expect(document.documentElement.style.getPropertyValue('--canvas-size')).toBe(
    'calc(max(100vw, 200vh) * 1.5) calc(max(50vw, 100vh) * 1.5)',
  )
  expect(document.documentElement.style.getPropertyValue('--canvas-position')).toBe('0% 100%')

  applyWallpaper(null)
  expect(document.documentElement.style.getPropertyValue('--canvas-size')).toBe('')
  expect(document.documentElement.style.getPropertyValue('--canvas-repeat')).toBe('')
})

it('fills the side bands with copies instead of leaving them blank in tile mode', () => {
  applyWallpaper('blob:x', { kind: 'image', fit: 'tile', zoom: 100, x: 50, y: 50, aspect: 2 })
  expect(document.documentElement.style.getPropertyValue('--canvas-repeat')).toBe('repeat')
  expect(document.documentElement.style.getPropertyValue('--canvas-size')).toBe('auto calc(100vh * 1)')
})

it('repairs a broken wallpaper config instead of trusting it', () => {
  expect(parseWallpaper(null)).toEqual(DEFAULT_WALLPAPER)
  expect(parseWallpaper({ fit: 'stretch', zoom: 9000, x: -4, y: 999, aspect: 0 })).toEqual({
    kind: 'image',
    fit: 'cover',
    zoom: 300,
    x: 0,
    y: 100,
    aspect: DEFAULT_WALLPAPER.aspect,
  })
})

it('reads an older preset without kind as an image, and never tiles a video', () => {
  const legacy = parseWallpaper({ fit: 'tile', zoom: 120, x: 30, y: 70, aspect: 1.5 })
  expect(legacy.kind).toBe('image')
  expect(legacy.fit).toBe('tile')

  const video = parseWallpaper({ kind: 'video', fit: 'tile', zoom: 120, x: 30, y: 70, aspect: 1 })
  expect(video).toEqual({ kind: 'video', fit: 'cover', zoom: 120, x: 30, y: 70, aspect: 1 })
})
