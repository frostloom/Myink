// 生成入口：单章生成（可留空 user_instruction）+ 批次生成（N≤20，成本估算标注「估算」）。
// 429 → 闸门码中文横幅（GATE_CODES）；成功 → onTaskStart(taskId) 交给时间线。
import { useState, type FormEvent } from 'react'
import { api, ApiError, GATE_CODES } from '../lib/api'
import type { ChapterMeta } from '../types'
import styles from './GenerationPanel.module.css'

/** 单章估算成本（与 gateway config.go 默认值对齐；无 API 暴露，前端常量标注「估算」） */
const COST_PER_CHAPTER = 0.05
const BATCH_MAX = 20

interface Props {
  projectId: string
  chapters: ChapterMeta[]
  selectedChapter: ChapterMeta | null
  onTaskStart: (taskId: string) => void
}

export function GenerationPanel({ projectId, chapters, selectedChapter, onTaskStart }: Props) {
  const [instruction, setInstruction] = useState('')
  const [batchN, setBatchN] = useState(3)
  const [busy, setBusy] = useState<null | 'chapter' | 'batch'>(null)
  const [banner, setBanner] = useState<string | null>(null)

  // 批次起点 = 已落库最大章序 + 1；空项目 → 1（与 worker _guard_write_order 语义一致）
  const maxSeq = chapters.reduce((m, c) => Math.max(m, c.chapter_seq), 0)
  const batchStart = maxSeq + 1
  const batchCost = (batchN * COST_PER_CHAPTER).toFixed(2)

  function showError(err: unknown) {
    if (err instanceof ApiError) {
      if (err.status === 429) {
        setBanner(GATE_CODES[err.code] ?? `额度受限（${err.code}）`)
      } else if (err.code) {
        setBanner(err.code)
      }
    } else {
      setBanner('请求失败，请重试')
    }
  }

  async function generateChapter(e: FormEvent) {
    e.preventDefault()
    if (!selectedChapter || busy) return
    setBusy('chapter')
    setBanner(null)
    try {
      const resp = await api.generateChapter(projectId, selectedChapter.id, {
        seq: selectedChapter.chapter_seq,
        ...(instruction.trim() ? { user_instruction: instruction.trim() } : {}),
      })
      onTaskStart(resp.task_id)
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  async function generateBatch(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy('batch')
    setBanner(null)
    try {
      const resp = await api.generateBatch(projectId, {
        size: batchN,
        start: batchStart,
      })
      onTaskStart(resp.task_id)
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className={styles.panel}>
      <h3 className={styles.heading}>生成</h3>

      {banner && <div className="banner banner-error">{banner}</div>}

      <form className={styles.form} onSubmit={generateChapter}>
        <label className={styles.label} htmlFor="user-instruction">
          写作指令（可留空）
        </label>
        <textarea
          id="user-instruction"
          className="textarea"
          rows={2}
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="如：节奏放慢，重点刻画战斗场面"
        />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!selectedChapter || busy !== null}
        >
          单章生成
        </button>
      </form>

      <form className={styles.form} onSubmit={generateBatch}>
        <label className={styles.label} htmlFor="batch-n">
          批次生成
        </label>
        <div className={styles.batchRow}>
          <input
            id="batch-n"
            type="number"
            min={1}
            max={BATCH_MAX}
            value={batchN}
            onChange={(e) => setBatchN(Math.max(1, Math.min(BATCH_MAX, Number(e.target.value))))}
          />
          <span className={styles.batchHint}>
            从第 {batchStart} 章起
            <span className={styles.cost}> ≈ ¥{batchCost}（估算）</span>
          </span>
        </div>
        <button
          type="submit"
          className="btn btn-secondary"
          disabled={busy !== null}
        >
          {busy === 'batch' ? '发起中…' : '发起批次'}
        </button>
      </form>
    </div>
  )
}
