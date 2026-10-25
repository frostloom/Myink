// @vitest-environment jsdom
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { StructuredTextField } from './StructuredTextField'

afterEach(cleanup)

function WorldEditor() {
  const [value, setValue] = useState<Record<string, string>>({ 魔法: '有代价' })
  return <>
    <StructuredTextField value={value} format={rules => Object.entries(rules).map(([k, v]) => `${k}：${v}`).join('\n')}
      parse={text => Object.fromEntries(text.split('\n').filter(line => line.includes('：')).map(line => line.split('：')))} onChange={setValue} />
    <button onClick={() => setValue({ 魔法: '有代价' })}>替换规则</button>
  </>
}

it('preserves local incomplete keys but resets them for a new equivalent external value', () => {
  render(<WorldEditor />)
  const field = screen.getByRole('textbox') as HTMLTextAreaElement
  fireEvent.change(field, { target: { value: '魔法：有代价\n未完成' } })
  expect(field.value).toBe('魔法：有代价\n未完成')
  fireEvent.click(screen.getByRole('button', { name: '替换规则' }))
  expect(field.value).toBe('魔法：有代价')
})

function ParticipantEditor() {
  const [value, setValue] = useState(['林尘'])
  return <>
    <StructuredTextField singleLine value={value} format={people => people.join('、')}
      parse={text => text.split('、').filter(Boolean)} onChange={setValue} />
    <button onClick={() => setValue(['林尘'])}>替换人物</button>
  </>
}

it('resets a trailing participant delimiter when a new equivalent plan replaces the value', () => {
  render(<ParticipantEditor />)
  const field = screen.getByRole('textbox') as HTMLInputElement
  fireEvent.change(field, { target: { value: '林尘、' } })
  expect(field.value).toBe('林尘、')
  fireEvent.click(screen.getByRole('button', { name: '替换人物' }))
  expect(field.value).toBe('林尘')
})
