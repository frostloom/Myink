// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import type { ArtifactState } from '../hooks/useTaskEvents'
import { StreamingChapterView } from './StreamingChapterView'

afterEach(cleanup)

function artifact(content: string, complete = false): ArtifactState {
  return {
    artifactId: 'write-1', taskId: 'task-1', stage: 'write', chapterSeq: 8,
    attempt: 1, content, complete, failed: false, artifact: null, message: null,
  }
}

it('renders the SSE fragment immediately while the model response is incomplete', () => {
  const { rerender } = render(
    <StreamingChapterView chapterSeq={8} artifact={artifact('=== CONTENT ===\n第一段仍在生成')} />,
  )

  expect(screen.getByText('第一段仍在生成')).toBeTruthy()
  expect(screen.getByText('实时写作')).toBeTruthy()

  rerender(
    <StreamingChapterView chapterSeq={8} artifact={artifact('=== CONTENT ===\n第一段仍在生成，第二段刚刚到达')} />,
  )
  expect(screen.getByText('第一段仍在生成，第二段刚刚到达')).toBeTruthy()
})

it('does not expose an incomplete protocol marker as chapter text', () => {
  render(<StreamingChapterView chapterSeq={8} artifact={artifact('=== CONT')} />)

  expect(screen.queryByText('=== CONT')).toBeNull()
  expect(screen.getByText('模型已开始响应，正在等待第一段正文…')).toBeTruthy()
})

it('keeps the chapter summary above正文 while rewriting', () => {
  render(
    <StreamingChapterView
      chapterSeq={11}
      artifact={artifact('=== CONTENT ===\n新的正文片段')}
      summary="沈砚在清晨醒来，伤处仍疼但已止血。"
    />,
  )

  expect(screen.getByText('沈砚在清晨醒来，伤处仍疼但已止血。')).toBeTruthy()
  expect(screen.getByText('新的正文片段')).toBeTruthy()
})

it('follows new text while the reader stays near the bottom', () => {
  const { rerender } = render(<StreamingChapterView chapterSeq={8} artifact={artifact('第一段')} />)
  const paper = screen.getByRole('region', { name: '正文实时预览' })
  Object.defineProperty(paper, 'scrollHeight', { configurable: true, value: 900 })
  Object.defineProperty(paper, 'clientHeight', { configurable: true, value: 300 })

  rerender(<StreamingChapterView chapterSeq={8} artifact={artifact('第一段\n第二段')} />)

  expect(paper.scrollTop).toBe(900)
})

it('pauses follow after the reader scrolls up and resumes on request', () => {
  const { rerender } = render(<StreamingChapterView chapterSeq={8} artifact={artifact('第一段')} />)
  const paper = screen.getByRole('region', { name: '正文实时预览' })
  Object.defineProperty(paper, 'scrollHeight', { configurable: true, value: 900 })
  Object.defineProperty(paper, 'clientHeight', { configurable: true, value: 300 })
  paper.scrollTop = 120
  fireEvent.scroll(paper)

  rerender(<StreamingChapterView chapterSeq={8} artifact={artifact('第一段\n第二段')} />)
  expect(paper.scrollTop).toBe(120)
  fireEvent.click(screen.getByRole('button', { name: '回到最新' }))
  expect(paper.scrollTop).toBe(900)
})
