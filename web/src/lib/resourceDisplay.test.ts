import {expect, it} from 'vitest'
import {resourceTitle} from './resourceDisplay'
it.each([
  ['references/shared/strand-weave-pattern.md', '多条剧情线交织写法'],
  ['references/outlining/plot-signal-vs-spoiler.md', '剧情铺垫与剧透的区别'],
  ['references/reading-power-taxonomy.md', '追读动力与情绪回报'],
])('explains imported filename %s in Chinese', (name, title) => {
  expect(resourceTitle({kind: 'reference', name})).toBe(title)
})
