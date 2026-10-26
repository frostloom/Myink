import { mount } from '@vue/test-utils'
import { describe,expect,it } from 'vitest'
import type { ResourceBody } from '../../../../src/lib/writingResources'
import { ResourceBodyFields } from './ResourceBodyFields'
import { ResourceContent } from './ResourceContent'

describe('Vue administrator content', () => {
  it('renders creative content while concealing internal identifiers', () => {
    const wrapper = mount(ResourceContent, { props: { body: { catalog_id: 'private-id', fields: { selling_point: '故事卖点' } } as ResourceBody } })
    expect(wrapper.text()).toContain('故事卖点')
    expect(wrapper.text()).not.toContain('private-id')
  })
  it('preserves unknown and hidden resource fields when editing', async () => {
    const value = { roles: { writer: '原文' }, validation: { not_is: true }, genre_ids: ['fantasy'], future: { setting: 'keep' } }
    let result: unknown
    const wrapper = mount(ResourceBodyFields, { props: { kind: 'writing_rule', value, onChange: (next: unknown) => { result = next } } })
    await wrapper.find('textarea').setValue('新文')
    expect(result).toEqual({ ...value, roles: { writer: '新文' } })
  })
})
