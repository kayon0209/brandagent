'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Edit3, Check, X, RotateCcw, MessageSquare, AlertTriangle,
  FileWarning, Info, Zap, User, GitMerge, ShieldCheck,
} from 'lucide-react'
import styles from './brandflow-live-workspace.module.css'

interface ContentBlock {
  block_id?: string
  block_type: string
  position: number
  content: string
  metadata?: Record<string, unknown>
}

interface ReviewIssue {
  issue_id?: string
  issue_type: string
  severity: 'info' | 'warning' | 'critical'
  problematic_text?: string | null
  reason: string
  suggested_action?: string
  target_block_id?: string | null
  status: string
}

interface BlockEditorProps {
  content: string
  structuredBlocks?: Array<Record<string, unknown>>
  issues?: Array<Record<string, unknown>>
  versionSource?: string
  onSave: (blocks: ContentBlock[]) => void
  onAcceptBlock: (blockIndex: number) => Promise<void>
  onRejectBlock: (blockIndex: number) => Promise<void>
  onRegenerateBlock: (blockIndex: number) => Promise<void>
  regeneratingIndex?: number | null
}

function normalizeBlocks(raw: Array<Record<string, unknown>> | undefined): ContentBlock[] | undefined {
  if (!raw || raw.length === 0) return undefined
  return raw.map((item) => ({
    block_id: item.block_id as string | undefined,
    block_type: (item.block_type as string) ?? 'paragraph',
    position: (item.position as number) ?? 0,
    content: (item.content as string) ?? '',
    metadata: item.metadata as Record<string, unknown> | undefined,
  }))
}

function parseContentToBlocks(content: string): ContentBlock[] {
  const blocks: ContentBlock[] = []
  const sections = content.split(/\n{2,}/)
  let position = 0
  for (const section of sections) {
    const trimmed = section.trim()
    if (!trimmed) continue
    const isHeading = trimmed.startsWith('#')
    blocks.push({
      block_type: isHeading ? 'heading' : 'paragraph',
      position: position++,
      content: trimmed.replace(/^#+\s*/, ''),
      metadata: { source: 'ai' },
    })
  }
  return blocks
}

export function BlockEditor({
  content,
  structuredBlocks,
  issues = [],
  versionSource = 'ai',
  onSave,
  onAcceptBlock,
  onRejectBlock,
  onRegenerateBlock,
  regeneratingIndex,
}: BlockEditorProps) {
  const normalized = normalizeBlocks(structuredBlocks)
  const [blocks, setBlocks] = useState<ContentBlock[]>(
    () => normalized ?? parseContentToBlocks(content)
  )
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editedContent, setEditedContent] = useState('')
  const [noteBlockIndex, setNoteBlockIndex] = useState<number | null>(null)
  const [noteText, setNoteText] = useState('')
  const editorRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const next = normalizeBlocks(structuredBlocks)
    if (next && next.length > 0) {
      setBlocks(next)
    }
  }, [structuredBlocks])

  function getIssuesForBlock(blockIndex: number): Array<Record<string, unknown>> {
    return issues.filter((issue) => {
      const b = blocks[blockIndex]
      if (b?.block_id && issue.target_block_id === b.block_id) return true
      if (issue.problematic_text && b?.content.includes(String(issue.problematic_text))) return true
      if (issue.target_block_id == null && issue.problematic_text == null) {
        return issue.status === 'open'
      }
      return false
    })
  }

  function startEdit(index: number) {
    setEditingIndex(index)
    setEditedContent(blocks[index].content)
  }

  function saveEdit(index: number) {
    const newBlocks = [...blocks]
    newBlocks[index] = {
      ...newBlocks[index],
      content: editedContent,
      metadata: {
        ...(newBlocks[index].metadata as Record<string, unknown>),
        source: newBlocks[index].metadata?.source === 'ai' ? 'mixed' : 'human',
        edited_at: new Date().toISOString(),
      },
    }
    setBlocks(newBlocks)
    setEditingIndex(null)
    onSave(newBlocks)
  }

  function cancelEdit() {
    setEditingIndex(null)
  }

  async function handleAccept(index: number) {
    // Optimistic update
    const newBlocks = [...blocks]
    newBlocks[index] = {
      ...newBlocks[index],
      metadata: {
        ...(newBlocks[index].metadata as Record<string, unknown>),
        approved: true,
      },
    }
    setBlocks(newBlocks)

    try {
      await onAcceptBlock(index)
    } catch {
      // Rollback on error
      const rolledBack = [...blocks]
      rolledBack[index] = {
        ...rolledBack[index],
        metadata: {
          ...(rolledBack[index].metadata as Record<string, unknown>),
          approved: false,
        },
      }
      setBlocks(rolledBack)
    }
  }

  const sourceIcon = (source: string | undefined) => {
    switch (source) {
      case 'ai': return <Zap size={12} />
      case 'human': return <User size={12} />
      case 'mixed': return <GitMerge size={12} />
      case 'approved': return <ShieldCheck size={12} />
      default: return null
    }
  }

  const sourceLabel = (source: string | undefined) => {
    switch (source) {
      case 'ai': return 'AI 生成'
      case 'human': return '人工编辑'
      case 'mixed': return '混合'
      case 'approved': return '已批准'
      default: return '未知'
    }
  }

  return (
    <div className={styles.blockEditor}>
      <div className={styles.blockEditorToolbar}>
        <span>块级编辑 · {blocks.length} 个内容块</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8, fontSize: 12 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className={styles.claimSourced} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%' }} />
            有来源
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className={styles.claimUnsourced} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%' }} />
            无支持
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className={styles.claimMissing} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%' }} />
            缺引用
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className={styles.claimBrand} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%' }} />
            品牌警告
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span className={styles.claimCompliance} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%' }} />
            合规警告
          </span>
        </span>
      </div>

      <div className={styles.blockList}>
        {blocks.map((block, index) => {
          const blockIssues = getIssuesForBlock(index)
          const isEditing = editingIndex === index
          const source = (block.metadata?.source as string) ?? versionSource
          const approved = block.metadata?.approved as boolean | undefined

          return (
            <div key={block.block_id ?? index} className={styles.block}>
              <div className={styles.blockHead}>
                <div className={styles.blockHeadLeft}>
                  <strong>
                    {block.block_type === 'heading' ? '标题' : `段落 ${index + 1}`}
                  </strong>
                  <span
                    className={styles.blockSourceBadge}
                    data-source={
                      approved ? 'approved' : source
                    }
                  >
                    {sourceIcon(approved ? 'approved' : source)}
                    {' '}
                    {approved ? '已批准' : sourceLabel(source)}
                  </span>
                </div>
                <div>
                  {!isEditing && (
                    <button
                      className={styles.secondary}
                      onClick={() => startEdit(index)}
                      style={{ padding: '4px 10px', fontSize: 12, minHeight: 28 }}
                    >
                      <Edit3 size={12} /> 编辑
                    </button>
                  )}
                </div>
              </div>

              <div className={styles.blockBody}>
                {isEditing ? (
                  <div
                    ref={editorRef}
                    className={styles.blockText}
                    contentEditable
                    suppressContentEditableWarning
                    onInput={(e) => setEditedContent(e.currentTarget.textContent ?? '')}
                    dangerouslySetInnerHTML={{ __html: editedContent }}
                  />
                ) : (
                  <div className={styles.blockText}>
                    <ClaimHighlightedText
                      content={block.content}
                      issues={blockIssues}
                    />
                  </div>
                )}
              </div>

              {blockIssues.length > 0 && (
                <div className={styles.blockIssues}>
                  {blockIssues.map((issue, i) => (
                    <div
                      key={String(issue.issue_id ?? i)}
                      className={styles.blockIssueItem}
                      data-severity={String(issue.severity ?? 'info')}
                    >
                      {issue.severity === 'critical' ? (
                        <AlertTriangle size={14} />
                      ) : issue.severity === 'warning' ? (
                        <FileWarning size={14} />
                      ) : (
                        <Info size={14} />
                      )}
                      <span>
                        {String(issue.reason)}
                        {issue.suggested_action ? (
                          <span style={{ display: 'block', color: '#667085', fontSize: 11 }}>
                            建议：{String(issue.suggested_action)}
                          </span>
                        ) : null}
                      </span>
                      <button title="标记为已解决">
                        <Check size={13} /> 解决
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {isEditing && (
                <div className={styles.blockReviewActions}>
                  <button className="accept" onClick={() => saveEdit(index)}>
                    <Check size={14} /> 保存
                  </button>
                  <button onClick={cancelEdit}>
                    <X size={14} /> 取消
                  </button>
                </div>
              )}

              {!isEditing && !approved && (
                <div className={styles.blockReviewActions}>
                  <button className="accept" onClick={() => handleAccept(index)}>
                    <Check size={14} /> 接受
                  </button>
                  <button className="reject" onClick={() => onRejectBlock(index)}>
                    <X size={14} /> 拒绝
                  </button>
                  <button onClick={() => onRegenerateBlock(index)} disabled={regeneratingIndex === index}>
                    <RotateCcw size={14} /> {regeneratingIndex === index ? '生成中…' : '重新生成'}
                  </button>
                  <button onClick={() => setNoteBlockIndex(noteBlockIndex === index ? null : index)}>
                    <MessageSquare size={14} /> 备注
                  </button>
                </div>
              )}

              {noteBlockIndex === index && (
                <div style={{ marginTop: 8, padding: 8, background: '#f9fafb', borderRadius: 6 }}>
                  <textarea
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    placeholder="为这个内容块添加备注…"
                    style={{ width: '100%', minHeight: 60, padding: 8, border: '1px solid #d0d5dd', borderRadius: 4, fontSize: 13 }}
                  />
                  <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
                    <button onClick={() => { setNoteBlockIndex(null); setNoteText(''); }} style={{ fontSize: 12 }}>取消</button>
                    <button onClick={() => { setNoteBlockIndex(null); setNoteText(''); }} style={{ fontSize: 12, background: '#3b5ccc', color: '#fff', border: 'none', borderRadius: 4, padding: '4px 12px' }}>保存备注</button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ClaimHighlightedText({
  content,
  issues,
}: {
  content: string
  issues: Array<Record<string, unknown>>
}) {
  if (issues.length === 0) return <>{content}</>

  const claimIndicators: Array<{
    index: number
    indicator: React.ReactNode
  }> = []

  for (const issue of issues) {
    const probText = issue.problematic_text as string | undefined
    if (!probText) continue

    const type = String(issue.issue_type ?? '')
    const severity = String(issue.severity ?? 'info')
    let className = styles.claimUnsourced

    if (type.includes('sourced')) {
      className = styles.claimSourced
    } else if (type.includes('unsourced') || type.includes('unsupported') || type.includes('speculative')) {
      className = styles.claimUnsourced
    } else if (type.includes('citation') || type.includes('missing')) {
      className = styles.claimMissing
    } else if (type.includes('brand')) {
      className = styles.claimBrand
    } else if (type.includes('compliance')) {
      className = styles.claimCompliance
    } else if (type.includes('human_edit') || type.includes('human')) {
      className = styles.claimHumanEdit
    } else if (type.includes('ai_generated') || type.includes('ai')) {
      // AI generated - no indicator needed
      continue
    } else if (type.includes('factual')) {
      // Legacy 'factual' type mapping
      className = severity === 'critical' ? styles.claimMissing : styles.claimUnsourced
    }

    // Find ALL occurrences of problematic_text, not just the first
    let searchIdx = 0
    while (searchIdx < content.length) {
      const idx = content.indexOf(probText, searchIdx)
      if (idx < 0) break
      claimIndicators.push({
        index: idx,
        indicator: (
          <span
            key={`${String(issue.issue_id ?? 'i')}-${idx}`}
            className={`${styles.claimIndicator} ${className}`}
            title={`${String(issue.reason)} - ${String(issue.suggested_action ?? '请检查')}`}
          />
        ),
      })
      searchIdx = idx + probText.length
    }
  }

  claimIndicators.sort((a, b) => a.index - b.index)

  const elements: React.ReactNode[] = []
  let lastIdx = 0
  for (const { index, indicator } of claimIndicators) {
    elements.push(content.slice(lastIdx, index))
    elements.push(indicator)
    lastIdx = index
  }
  elements.push(content.slice(lastIdx))

  return <>{elements}</>
}
