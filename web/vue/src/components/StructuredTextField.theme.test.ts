import { render, screen, cleanup } from '@testing-library/vue'
import { afterEach, expect, it } from 'vitest'
import StructuredTextField from './StructuredTextField.vue'
import GenrePackFields from './GenrePackFields.vue'
afterEach(cleanup)
it('uses the shared theme for multiline structured fields without caller styling', () => {
 render(StructuredTextField, { props: { value: ['凡人流'], format: (v: unknown) => (v as string[]).join('\n'), parse: (v: string) => v.split('\n') } })
 expect(screen.getByRole('textbox').classList.contains('textarea')).toBe(true)
})
it('uses the shared input theme for single line fields and preserves caller class', () => {
 render(StructuredTextField, { props: { value: '内容', format: String, parse: String, singleLine: true, className: 'custom' } })
 const field = screen.getByRole('textbox')
 expect(field.classList.contains('input')).toBe(true)
 expect(field.classList.contains('custom')).toBe(true)
})
it('styles every genre field including subgenre hints consistently', () => {
 render(GenrePackFields, { props: { value: { selling_point: '核心', subgenres: [{name:'凡人流',hook:'积少成多'}], pacing:'节奏',taboos:[],satisfaction:[],mechanics:[],world_hints:[] } } })
 for (const field of screen.getAllByRole('textbox')) expect(field.classList.contains('textarea')).toBe(true)
})
