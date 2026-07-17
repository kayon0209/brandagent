'use client'

import { useMemo, useState } from 'react'
import { GitCompare, Columns, List, X } from 'lucide-react'
import styles from './brandflow-live-workspace.module.css'

type DiffMode = 'side-by-side' | 'inline'
type DiffFilter = 'text' | 'facts' | 'structure' | 'tone' | 'channel' | 'compliance'

interface VersionMeta {
  content_version_id: string
  content_type: string
  channel: string | null
  version_number: number
  created_by_type: 'human' | 'model' | 'workflow'
  created_by_id: string
  model_call_id: string | null
  prompt_version: string | null
  created_at: string
  change_summary: string
  immutable_hash: string
}

interface DiffLine {
  type: 'add' | 'del' | 'same' | 'mod'
  left?: string
  right?: string
  line: string
}

function computeDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  const maxLen = Math.max(oldLines.length, newLines.length)
  const result: DiffLine[] = []

  for (let i = 0; i < maxLen; i++) {
    const o = oldLines[i]
    const n = newLines[i]
    if (o === undefined && n !== undefined) {
      result.push({ type: 'add', line: n, right: n })
    } else if (n === undefined && o !== undefined) {
      result.push({ type: 'del', line: o, left: o })
    } else if (o === n) {
      result.push({ type: 'same', line: o, left: o, right: n })
    } else if (o && n && linesSimilar(o, n)) {
      result.push({ type: 'mod', line: `${o} → ${n}`, left: o, right: n })
    } else {
      if (o) result.push({ type: 'del', line: o, left: o })
      if (n) result.push({ type: 'add', line: n, right: n })
    }
  }

  return result
}

function linesSimilar(a: string, b: string): boolean {
  const aWords = new Set(a.toLowerCase().split(/\s+/))
  const bWords = new Set(b.toLowerCase().split(/\s+/))
  let overlap = 0
  for (const w of aWords) {
    if (bWords.has(w)) overlap++
  }
  return overlap / Math.max(aWords.size, bWords.size) > 0.4
}

function lineMatchesFilter(line: string, filter: DiffFilter | null): boolean {
  if (!filter) return true
  switch (filter) {
    case 'text':
      return true
    case 'facts':
      return /\d+[%％]|\d+[万千百亿]|数据|统计|调查|研究|报告/.test(line)
    case 'structure':
      return /^#/.test(line) || /^[*-]/.test(line) || /^\d+\./.test(line)
    case 'tone':
      return /[！？]|推荐|建议|务必|一定|必须|最佳|首选/.test(line)
    case 'channel':
      return /@|链接|关注|转发|扫码|订阅|点击/.test(line)
    case 'compliance':
      return /风险|免责|合规|声明|条款|隐私/.test(line)
    default:
      return true
  }
}

const filters: { key: DiffFilter; label: string }[] = [
  { key: 'text', label: '文本' },
  { key: 'facts', label: '事实' },
  { key: 'structure', label: '结构' },
  { key: 'tone', label: '语气' },
  { key: 'channel', label: '渠道格式' },
  { key: 'compliance', label: '合规' },
]

interface VersionDiffViewerProps {
  versions: Array<Record<string, unknown>>
}

export function VersionDiffViewer({ versions }: VersionDiffViewerProps) {
  const [mode, setMode] = useState<DiffMode>('side-by-side')
  const [activeFilter, setActiveFilter] = useState<DiffFilter | null>(null)
  const [selectedLeft, setSelectedLeft] = useState<number>(0)
  const [selectedRight, setSelectedRight] = useState<number>(1)

  const contentVersions = useMemo(
    () =>
      versions
        .filter((v) => typeof v.content === 'string')
        .sort((a, b) => (Number(b.version_number) ?? 0) - (Number(a.version_number) ?? 0)),
    [versions]
  )

  const left = contentVersions[selectedLeft] ?? null
  const right = contentVersions[selectedRight] ?? null

  const diff = useMemo(() => {
    if (!left || !right) return []
    return computeDiff(String(left.content ?? ''), String(right.content ?? ''))
  }, [left, right])

  // activeFilter is used only in rendering (lineMatchesFilter), not in diff computation

  function versionTitle(item: Record<string, unknown>, index: number): string {
    const channel = item.channel ? ` · ${channelLabel(String(item.channel))}` : ''
    const byType = String(item.created_by_type ?? '')
    const human = byType === 'human' ? ' (人工)' : byType === 'model' ? ' (AI)' : ''
    return `v${String(item.version_number ?? index + 1)}${channel}${human} — ${String(item.change_summary ?? '无摘要')}`
  }

  if (contentVersions.length < 2) {
    return (
      <div className={styles.diffEmpty}>
        <GitCompare size={32} />
        <p>需要至少两个版本才能进行比较。</p>
        <small>当内容被 AI 生成或人工修订后，新版本将出现在此列表中。</small>
      </div>
    )
  }

  const addCount = diff.filter((d) => d.type === 'add').length
  const delCount = diff.filter((d) => d.type === 'del').length
  const modCount = diff.filter((d) => d.type === 'mod').length

  return (
    <div className={styles.diffContainer}>
      <div className={styles.diffHeader}>
        <div className={styles.diffModeToggle}>
          <button
            data-active={mode === 'side-by-side'}
            onClick={() => setMode('side-by-side')}
            title="并排比较"
          >
            <Columns size={14} />
          </button>
          <button
            data-active={mode === 'inline'}
            onClick={() => setMode('inline')}
            title="行内比较"
          >
            <List size={14} />
          </button>
        </div>

        <select
          value={selectedLeft}
          onChange={(e) => setSelectedLeft(Number(e.target.value))}
          style={{
            border: '1px solid #d0d5dd',
            borderRadius: 6,
            padding: '4px 10px',
            fontSize: 13,
          }}
        >
          {contentVersions.map((v, i) => (
            <option key={i} value={i} disabled={i === selectedRight}>
              {versionTitle(v, i)}
            </option>
          ))}
        </select>

        <span style={{ color: '#667085', fontSize: 13 }}>vs</span>

        <select
          value={selectedRight}
          onChange={(e) => setSelectedRight(Number(e.target.value))}
          style={{
            border: '1px solid #d0d5dd',
            borderRadius: 6,
            padding: '4px 10px',
            fontSize: 13,
          }}
        >
          {contentVersions.map((v, i) => (
            <option key={i} value={i} disabled={i === selectedLeft}>
              {versionTitle(v, i)}
            </option>
          ))}
        </select>

        <div style={{ marginLeft: 'auto', fontSize: 12, color: '#667085' }}>
          <span style={{ color: '#12b76a', fontWeight: 600 }}>+{addCount}</span>
          {' · '}
          <span style={{ color: '#d92d20', fontWeight: 600 }}>-{delCount}</span>
          {' · '}
          <span style={{ color: '#f79009', fontWeight: 600 }}>~{modCount}</span>
        </div>
      </div>

      <div className={styles.diffFilter}>
        {filters.map((f) => (
          <button
            key={f.key}
            data-active={activeFilter === f.key}
            onClick={() => setActiveFilter(activeFilter === f.key ? null : f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {mode === 'side-by-side' ? (
        <div className={styles.diffSideBySide}>
          <div>
            <DiffVersionMeta version={left} index={selectedLeft} versions={contentVersions} />
            {(left ? String(left.content ?? '') : '').split('\n').map((line, i) => {
              const isChanged = diff.some((d) => d.type === 'del' && d.left === line)
              const matches = !activeFilter || (isChanged && lineMatchesFilter(line, activeFilter))
              return (
                <div
                  key={i}
                  style={{
                    padding: '2px 0',
                    font: '14px/1.7 Georgia, serif',
                    color: isChanged ? '#991b1b' : '#172033',
                    textDecoration: isChanged ? 'line-through' : 'none',
                    opacity: activeFilter && !matches ? 0.3 : 1,
                  }}
                >
                  {line || '\u00a0'}
                </div>
              )
            })}
          </div>
          <div>
            <DiffVersionMeta version={right} index={selectedRight} versions={contentVersions} />
            {(right ? String(right.content ?? '') : '').split('\n').map((line, i) => {
              const isChanged = diff.some((d) => d.type === 'add' && d.right === line)
              const matches = !activeFilter || (isChanged && lineMatchesFilter(line, activeFilter))
              return (
                <div
                  key={i}
                  style={{
                    padding: '2px 0',
                    font: '14px/1.7 Georgia, serif',
                    color: isChanged ? '#067647' : '#172033',
                    fontWeight: isChanged ? 600 : 400,
                    opacity: activeFilter && !matches ? 0.3 : 1,
                  }}
                >
                  {line || '\u00a0'}
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <div className={styles.diffInline}>
          {diff.map((d, i) => {
            const matches = !activeFilter || (d.type !== 'same' && lineMatchesFilter(d.line, activeFilter))
            return (
              <div
                key={i}
                className={`${styles.diffLine} ${
                  d.type === 'add'
                    ? styles.diffLineAdd
                    : d.type === 'del'
                      ? styles.diffLineDel
                      : d.type === 'mod'
                        ? styles.diffLineMod
                        : ''
                }`}
                style={{ opacity: activeFilter && !matches ? 0.3 : 1 }}
              >
                <span className={styles.diffLineTag}>
                  {d.type === 'add' ? '+' : d.type === 'del' ? '\u2212' : d.type === 'mod' ? '改' : ''}
                </span>
                <span>{d.line || '\u00a0'}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function DiffVersionMeta({
  version,
  index,
  versions,
}: {
  version: Record<string, unknown> | null
  index: number
  versions: Array<Record<string, unknown>>
}) {
  if (!version) return null
  return (
    <div className={styles.diffVersionMeta}>
      <b>
        v{String(version.version_number ?? index + 1)} · {String(version.content_type ?? '内容')}
        {version.channel ? ` · ${channelLabel(String(version.channel))}` : ''}
      </b>
      <small>
        创建者：{String(version.created_by_type ?? '未知')}
        {version.created_at ? ` · ${new Date(String(version.created_at)).toLocaleString('zh-CN')}` : ''}
      </small>
      {version.change_summary ? <small>摘要：{String(version.change_summary)}</small> : null}
      {version.immutable_hash ? (
        <small>哈希：{String(version.immutable_hash).slice(0, 12)}…</small>
      ) : null}
    </div>
  )
}

function channelLabel(channel: string) {
  return (
    (
      {
        wechat_website: '微信/官网',
        xiaohongshu: '小红书',
        video_script_60s: '60秒视频脚本',
        marketing_email: '营销邮件',
      } as Record<string, string>
    )[channel] ?? channel
  )
}
