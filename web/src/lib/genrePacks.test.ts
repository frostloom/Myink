import { expect, test } from 'vitest'
import { composeFields, displayGenre, emptyFields, UNSELECTED_NAME, type GenreCatalogItem } from './genrePacks'

function item(id: string, name: string, extra: Partial<GenreCatalogItem> = {}): GenreCatalogItem {
  return {
    id, name, group: '玄幻修仙',
    selling_point: `${name}卖点`,
    subgenres: [{ name: `${name}流派`, hook: '钩子' }],
    taboos: [`${name}禁忌`],
    pacing: `${name}节奏`,
    satisfaction: [`${name}爽点`],
    mechanics: [`${name}机制`],
    world_hints: [`${name}法则`],
    ...extra,
  }
}

test('display name locks to pack names', () => {
  expect(displayGenre()).toBe(UNSELECTED_NAME)
  expect(displayGenre(item('a', '修仙'))).toBe('修仙')
  expect(displayGenre(item('a', '修仙'), item('b', '系统流'))).toBe('修仙+系统流')
})

test('compose overlays secondary mechanics/satisfaction/taboos only', () => {
  const fields = composeFields(item('xiuxian', '修仙'), item('xitong', '系统流'))
  expect(fields.pacing).toBe('修仙节奏')
  expect(fields.world_hints).toEqual(['修仙法则'])
  expect(fields.subgenres[0].name).toBe('修仙流派')
  expect(fields.selling_point).toContain('辅题材（系统流）')
  expect(fields.mechanics).toEqual(['修仙机制', '系统流机制'])
  expect(fields.taboos).toEqual(['修仙禁忌', '系统流禁忌'])
})

test('empty compose is empty fields', () => {
  expect(composeFields()).toEqual(emptyFields())
})
