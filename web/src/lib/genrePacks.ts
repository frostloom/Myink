/** 题材包：根目录条目。辅题材不并进主题材字段，写章提示里按 7:3 另附。 */

export const UNSELECTED_NAME = '未选题材'

export interface GenreSubgenre {
  name: string
  hook: string
}

export interface GenreFields {
  selling_point: string
  subgenres: GenreSubgenre[]
  taboos: string[]
  pacing: string
  satisfaction: string[]
  mechanics: string[]
  world_hints: string[]
}

export interface GenreCatalogItem extends GenreFields {
  id: string
  name: string
  group: string
}

export interface BookGenrePack extends GenreFields {
  source_id: string | null
  source_name: string
  secondary_id: string | null
  secondary_name: string | null
}

export function emptyFields(): GenreFields {
  return {
    selling_point: '',
    subgenres: [],
    taboos: [],
    pacing: '',
    satisfaction: [],
    mechanics: [],
    world_hints: [],
  }
}

export function displayGenre(primary?: GenreCatalogItem | null, secondary?: GenreCatalogItem | null): string {
  if (!primary) return UNSELECTED_NAME
  return secondary ? `${primary.name}+${secondary.name}` : primary.name
}

export function composeFields(
  primary?: GenreCatalogItem | null,
  secondary?: GenreCatalogItem | null,
): GenreFields {
  if (!primary) return emptyFields()
  const fields: GenreFields = {
    selling_point: primary.selling_point,
    subgenres: primary.subgenres.map((s) => ({ ...s })),
    taboos: [...primary.taboos],
    pacing: primary.pacing,
    satisfaction: [...primary.satisfaction],
    mechanics: [...primary.mechanics],
    world_hints: [...primary.world_hints],
  }
  if (!secondary) return fields
  const extra = secondary.selling_point.trim()
  const tag = extra
    ? `辅题材（${secondary.name}）按 7:3 附在主题材之后：${extra}`
    : `辅题材（${secondary.name}）按 7:3 附在主题材之后`
  const base = fields.selling_point.trim()
  fields.selling_point = base ? `${base}\n${tag}` : tag
  return fields
}

export function groupCatalog(items: GenreCatalogItem[]): Array<{ group: string; items: GenreCatalogItem[] }> {
  const order: string[] = []
  const map = new Map<string, GenreCatalogItem[]>()
  for (const item of items) {
    if (!map.has(item.group)) {
      map.set(item.group, [])
      order.push(item.group)
    }
    map.get(item.group)!.push(item)
  }
  return order.map((group) => ({ group, items: map.get(group) ?? [] }))
}

export function isManagedPack(pack: BookGenrePack | Record<string, unknown> | null | undefined): pack is BookGenrePack {
  return !!pack && typeof pack === 'object' && 'source_name' in pack && Object.keys(pack).length > 0
}
