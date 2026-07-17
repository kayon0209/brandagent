'use client'

import { useMemo, useState } from 'react'
import { Check, X, Download, AlertTriangle, ShieldCheck, FileText } from 'lucide-react'
import styles from './brandflow-live-workspace.module.css'

interface ExportDialogProps {
  open: boolean
  taskTitle: string
  availableChannels: string[]
  approvalVersion: string
  sourceVersion: string
  guardrailPassed: boolean
  guardrailIssues: string[]
  onExport: (channels: string[], formats: string[]) => Promise<void>
  onClose: () => void
}

const channelLabels: Record<string, string> = {
  wechat_website: '微信 / 官网',
  xiaohongshu: '小红书',
  video_script_60s: '60 秒视频脚本',
  marketing_email: '营销邮件',
}

const formatOptions = [
  { key: 'markdown', label: 'Markdown', desc: '含 YAML 前置元数据和内容主体', ext: '.md' },
  { key: 'json', label: 'JSON', desc: '结构化数据，含版本、谱系和审批记录', ext: '.json' },
  { key: 'docx', label: 'DOCX', desc: '排版文档，适合进一步编辑和打印', ext: '.docx' },
]

export function ExportDialog({
  open,
  taskTitle,
  availableChannels,
  approvalVersion,
  sourceVersion,
  guardrailPassed,
  guardrailIssues,
  onExport,
  onClose,
}: ExportDialogProps) {
  const [selectedChannels, setSelectedChannels] = useState<string[]>([...availableChannels])
  const [selectedFormats, setSelectedFormats] = useState<string[]>(['markdown'])
  const [exporting, setExporting] = useState(false)

  const canExport = useMemo(
    () => guardrailPassed && selectedChannels.length > 0 && selectedFormats.length > 0,
    [guardrailPassed, selectedChannels, selectedFormats]
  )

  function toggleChannel(ch: string) {
    setSelectedChannels((prev) =>
      prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch]
    )
  }

  function toggleFormat(f: string) {
    setSelectedFormats((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]
    )
  }

  async function handleExport() {
    if (!canExport || exporting) return
    setExporting(true)
    try {
      await onExport(selectedChannels, selectedFormats)
      onClose()
    } finally {
      setExporting(false)
    }
  }

  if (!open) return null

  return (
    <div className={styles.dialogOverlay} onClick={onClose}>
      <div className={styles.dialog} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="导出内容">
        <header className={styles.dialogHeader}>
          <div>
            <h2>导出内容包</h2>
            <p>{taskTitle}</p>
          </div>
          <button onClick={onClose} aria-label="关闭" title="关闭导出">
            <X size={18} />
          </button>
        </header>

        <div className={styles.dialogBody}>
          {/* Guardrail status */}
          <div className={styles.dialogSummary} data-pass={guardrailPassed ? 'true' : 'false'}>
            <ShieldCheck size={16} />
            <span>
              <b>{guardrailPassed ? '门禁检查通过' : '门禁未通过'}</b>
              <small>
                {guardrailPassed
                  ? '所有内容版本均已通过审批，可以安全导出。'
                  : guardrailIssues.length === 1
                    ? guardrailIssues[0]
                    : '存在多个问题，详见下方列表'}
              </small>
            </span>
          </div>
          {!guardrailPassed && guardrailIssues.length > 1 && (
            <ul style={{margin:'4px 0 0',paddingLeft:18,fontSize:12,color:'#667085'}}>
              {guardrailIssues.map((issue, i) => <li key={i}>{issue}</li>)}
            </ul>
          )}

          {/* Immutable summary */}
          <div className={styles.exportMeta}>
            <span>
              <FileText size={14} />
              审批版本：{approvalVersion}
            </span>
            <span>
              <FileText size={14} />
              来源版本：{sourceVersion}
            </span>
          </div>

          {/* Channel selection */}
          <div className={styles.exportSection}>
            <h4>选择导出渠道</h4>
            <div className={styles.exportOptions}>
              {availableChannels.map((ch) => (
                <label key={ch} className={styles.exportOption}>
                  <input
                    type="checkbox"
                    checked={selectedChannels.includes(ch)}
                    onChange={() => toggleChannel(ch)}
                  />
                  <span>{channelLabels[ch] ?? ch}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Format selection */}
          <div className={styles.exportSection}>
            <h4>选择导出格式</h4>
            <div className={styles.exportOptions}>
              {formatOptions.map((f) => (
                <label key={f.key} className={styles.exportOption}>
                  <input
                    type="checkbox"
                    checked={selectedFormats.includes(f.key)}
                    onChange={() => toggleFormat(f.key)}
                  />
                  <span>
                    <b>{f.label}</b>
                    <small>{f.desc}</small>
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Package summary */}
          <div className={styles.exportSummary}>
            <p>
              将导出 <b>{selectedChannels.length}</b> 个渠道 的
              <b> {selectedFormats.length}</b> 种格式。
              导出操作将记录审计版本，生成不可变包摘要。
            </p>
          </div>

          {/* Actions */}
          <div className={styles.dialogActions}>
            <button
              className={styles.dialogApproveBtn}
              disabled={!canExport || exporting}
              onClick={handleExport}
              title={!guardrailPassed ? '门禁未通过，无法导出' : undefined}
            >
              <Download size={16} />
              {exporting ? '导出中…' : '确认导出'}
            </button>
            <button className={styles.dialogCancelBtn} onClick={onClose} disabled={exporting}>
              取消
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
