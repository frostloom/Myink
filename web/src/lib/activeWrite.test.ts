// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { clearActiveWrite, readActiveWrite, writeActiveWrite, clearActiveShortWrite, readActiveShortWrite, writeActiveShortWrite } from './activeWrite'

afterEach(() => {
  sessionStorage.clear()
})

it('remembers an in-flight write per book', () => {
  writeActiveWrite('user-a', 'book-a', { taskId: 'task-2', chapterSeq: 2, batchTotal: null })
  writeActiveWrite('user-a', 'book-b', { taskId: 'task-1', chapterSeq: 1, batchTotal: 3 })
  expect(readActiveWrite('user-a', 'book-a')).toEqual({ taskId: 'task-2', chapterSeq: 2, batchTotal: null })
  expect(readActiveWrite('user-a', 'book-b')).toEqual({ taskId: 'task-1', chapterSeq: 1, batchTotal: 3 })
  clearActiveWrite('user-a', 'book-a')
  expect(readActiveWrite('user-a', 'book-a')).toBeNull()
  expect(readActiveWrite('user-a', 'book-b')?.taskId).toBe('task-1')
})

it('does not expose an in-flight write to another account with the same project id', () => {
  writeActiveWrite('user-a', 'book-a', { taskId: 'task-a', chapterSeq: 2, batchTotal: null })

  expect(readActiveWrite('user-b', 'book-a')).toBeNull()
  expect(readActiveWrite('user-a', 'book-a')?.taskId).toBe('task-a')
})

it('ignores a broken payload instead of throwing', () => {
  sessionStorage.setItem('myink.activeWrite.user-a.book-a', '{')
  expect(readActiveWrite('user-a', 'book-a')).toBeNull()
})

it('isolates accepted short tasks from other accounts, books and long-form writes', () => {
  writeActiveShortWrite('user-a', 'short-a', 'short-task')
  writeActiveShortWrite('user-a', 'short-b', 'other-short-task')
  writeActiveWrite('user-a', 'long-a', { taskId: 'long-task', chapterSeq: 1, batchTotal: null })
  expect(readActiveShortWrite('user-a', 'short-a')).toBe('short-task')
  expect(readActiveShortWrite('user-b', 'short-a')).toBeNull()
  clearActiveShortWrite('user-a', 'short-a')
  expect(readActiveShortWrite('user-a', 'short-a')).toBeNull()
  expect(readActiveShortWrite('user-a', 'short-b')).toBe('other-short-task')
  expect(readActiveWrite('user-a', 'long-a')?.taskId).toBe('long-task')
})
