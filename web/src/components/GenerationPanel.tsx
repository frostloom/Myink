// 生成入口：写下一章（永远写「已写最大章 + 1」的下一未写章）+ 重写本章（仅 confirmed 章，
// 带确认弹窗）+ 批次生成（N≤20，成本估算标注「估算」）。
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
  /** 批次生成时带 batchTotal（时间线实时 i/N）；单章任务带 chapterSeq（右栏按章过滤） */
  onTaskStart: (taskId: string, batchTotal?: number, chapterSeq?: number) => void
}

export function GenerationPanel({ projectId, chapters, selectedChapter, onTaskStart }: Props) {
  const [instruction, setInstruction] = useState('')
  const [batchN, setBatchN] = useState(3)
  const [busy, setBusy] = useState<null | 'chapter' | 'batch'>(null)
  const [banner, setBanner] = useState<string | null>(null)

  // 已写最大章序 + 下一章序号（空项目 → 1，与 worker _guard_write_order 语义一致）。
  // 章节列表只有已物化行：写下一章 = seq 恒为 max_seq+1，绝不踩「选已写章被守卫拒绝」。
  const maxSeq = chapters.reduce((m, c) => Math.max(m, c.chapter_seq), 0)
  const nextSeq = maxSeq + 1
  // cid=尾部章占位：worker 全程忽略 chapter_id（grep 零匹配），写序由 seq 权威。
  // 空书无已物化章 → 用 projectId 占位（后端同样放行 seq=1，见 worker _guard_write_order）。
  const tailId =
    chapters.reduce<ChapterMeta | null>(
      (m, c) => (m === null || c.chapter_seq > m.chapter_seq ? c : m),
      null,
    )?.id ?? projectId
  const batchStart = nextSeq
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

  // 写下一章：空书也可写（第 1 章，写作指令透传）；tailId 恒非空（空书回退 projectId 占位）
  async function generateNextChapter(e: FormEvent) {
    e.preventDefault()
    if (busy || !tailId) return
    setBusy('chapter')
    setBanner(null)
    try {
      const resp = await api.generateChapter(projectId, tailId, {
        seq: nextSeq,
        ...(instruction.trim() ? { user_instruction: instruction.trim() } : {}),
      })
      onTaskStart(resp.task_id, undefined, nextSeq)
    } catch (err) {
      showError(err)
    } finally {
      setBusy(null)
    }
  }

  // 重写本章（仅 confirmed 章；awaiting_review 走时间线 resume/reject 分流）：
  // worker _guard_write_order(rewrite=True) 放行已确认章，重写会失效重建该章相关记忆
  async function rewriteChapter() {
    if (!selectedChapter || selectedChapter.status !== 'confirmed' || busy) return
    if (!window.confirm(`重写第 ${selectedChapter.chapter_seq} 章？将失效重建该章相关记忆，不可撤销。`)) return
    setBusy('chapter')
    setBanner(null)
    try {
      const resp = await api.generateChapter(projectId, selectedChapter.id, {
        seq: selectedChapter.chapter_seq,
        rewrite: true,
        ...(instruction.trim() ? { user_instruction: instruction.trim() } : {}),
      })
      onTaskStart(resp.task_id, undefined, selectedChapter.chapter_seq)
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
      onTaskStart(resp.task_id, batchN)
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

      <form className={styles.form} onSubmit={generateNextChapter}>
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
          disabled={busy !== null}
        >
          {busy === 'chapter' ? '发起中…' : `写下一章（第 ${nextSeq} 章）`}
        </button>
        <button
          type="button"
          className="btn btn-quiet"
          disabled={!selectedChapter || selectedChapter.status !== 'confirmed' || busy !== null}
          onClick={rewriteChapter}
        >
          {selectedChapter && selectedChapter.status === 'confirmed'
            ? `重写第 ${selectedChapter.chapter_seq} 章`
            : '重写本章'}
        </button>
        {chapters.length === 0 && (
          <p className={styles.emptyHint}>
            新书可直接写第 1 章（上面的写作指令会生效）；要一次写多章再用下方「发起批次」。
          </p>
        )}
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
