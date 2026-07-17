'use client'

import { useState } from 'react'
import { AlertTriangle, Check, X, ShieldCheck, FileText } from 'lucide-react'
import styles from './brandflow-live-workspace.module.css'

interface ApprovalDialogProps {
  open: boolean
  title: string
  decisionType: string
  versionSummary: string
  snapshotHash: string
  issues: Array<Record<string, unknown>>
  error?: string | null
  onApprove: (comment: string) => Promise<void>
  onReject: (reason: string) => Promise<void>
  onClose: () => void
}

export function ApprovalDialog({
  open,
  title,
  decisionType,
  versionSummary,
  snapshotHash,
  issues,
  error,
  onApprove,
  onReject,
  onClose,
}: ApprovalDialogProps) {
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [mode, setMode] = useState<'review' | 'approve' | 'reject'>('review')

  if (!open) return null

  async function handleApprove() {
    if (submitting) return
    setSubmitting(true)
    try {
      await onApprove(comment || '已审核通过')
    } finally {
      setSubmitting(false)
      setComment('')
      setMode('review')
    }
  }

  async function handleReject() {
    if (submitting || !comment.trim()) return
    setSubmitting(true)
    try {
      await onReject(comment)
    } finally {
      setSubmitting(false)
      setComment('')
      setMode('review')
    }
  }

  const decisionLabel =
    decisionType === 'outline' ? '大纲审批'
    : decisionType.startsWith('master_') ? '主内容审批'
    : decisionType === 'channel' ? '渠道审批'
    : decisionType === 'final' ? '最终审批'
    : '审批'

  return (
    <div className={styles.dialogOverlay} onClick={onClose}>
      <div className={styles.dialog} onClick={(e) => e.stopPropagation()} role="dialog" aria-label={decisionLabel}>
        <header className={styles.dialogHeader}>
          <div>
            <h2>{decisionLabel}</h2>
            <p>{title}</p>
          </div>
          <button onClick={onClose} aria-label="关闭" title="关闭审批">
            <X size={18} />
          </button>
        </header>

        <div className={styles.dialogBody}>
          <div className={styles.dialogSummary}>
            <FileText size={16} />
            <span>
              <b>当前版本</b>
              <small>{versionSummary}</small>
              <small style={{ fontFamily: 'monospace', fontSize: 11, color: '#667085' }}>
                快照 {snapshotHash.slice(0, 12)}&hellip;
              </small>
            </span>
          </div>

          {issues.length > 0 && (
            <div className={styles.dialogIssues}>
              <h4>
                <AlertTriangle size={14} /> 待审查问题 ({issues.length})
              </h4>
              <ul>
                {issues.slice(0, 5).map((issue, i) => (
                  <li key={i}>
                    <span data-severity={String(issue.severity ?? 'info')}>
                      {issue.severity === 'critical' ? '🔴' : issue.severity === 'warning' ? '🟡' : '🔵'}
                    </span>
                    {String(issue.reason).slice(0, 120)}
                    {String(issue.reason).length > 120 ? '…' : ''}
                  </li>
                ))}
                {issues.length > 5 && <li>…及其他 {issues.length - 5} 个问题</li>}
              </ul>
            </div>
          )}

          {error && (
            <div style={{background:'#fef2f2',border:'1px solid #fecaca',borderRadius:6,padding:'8px 12px',marginTop:12,display:'flex',alignItems:'center',gap:8,color:'#991b1b',fontSize:13}}>
              <AlertTriangle size={14} />
              {error}
            </div>
          )}

          {mode === 'review' ? (
            <div className={styles.dialogActions}>
              <button
                className={styles.dialogApproveBtn}
                onClick={() => setMode('approve')}
              >
                <Check size={16} /> 批准
              </button>
              <button
                className={styles.dialogRejectBtn}
                onClick={() => setMode('reject')}
              >
                <X size={16} /> 退回修订
              </button>
            </div>
          ) : (
            <>
              <div className={styles.dialogComment}>
                <label>
                  {mode === 'approve' ? '审批备注（可选）' : '退回理由（必填）'}
                </label>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder={
                    mode === 'approve'
                      ? '输入审批备注…'
                      : '请说明退回原因和需要修改的内容…'
                  }
                  rows={4}
                />
              </div>

              <div className={styles.dialogActions}>
                <button
                  className={styles.dialogApproveBtn}
                  disabled={submitting || (mode === 'reject' && !comment.trim())}
                  onClick={mode === 'approve' ? handleApprove : handleReject}
                >
                  {submitting
                    ? '提交中…'
                    : mode === 'approve'
                      ? '确认批准'
                      : '确认退回'}
                </button>
                <button
                  className={styles.dialogCancelBtn}
                  disabled={submitting}
                  onClick={() => setMode('review')}
                >
                  返回
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
