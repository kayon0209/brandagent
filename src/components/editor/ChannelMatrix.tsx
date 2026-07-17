'use client'

import { useMemo, useState } from 'react'
import {
  Check, AlertTriangle, X, Edit3, Eye, GitCompare,
  FileWarning, LayoutGrid, RefreshCw,
} from 'lucide-react'
import styles from './brandflow-live-workspace.module.css'

const channelLabels: Record<string, string> = {
  wechat_website: '微信 / 官网',
  xiaohongshu: '小红书',
  video_script_60s: '60 秒视频脚本',
  marketing_email: '营销邮件',
}

const channelFormats: Record<string, string> = {
  wechat_website: '长文 · Markdown · 800-2000 字',
  xiaohongshu: '短文 · 口语化 · 300-800 字 · 话题标签',
  video_script_60s: '视频脚本 · 60 秒 · 口播 + 画面提示',
  marketing_email: '邮件 · 主题+正文+CTA · 500-1500 字',
}

interface ChannelMatrixProps {
  versions: Array<Record<string, unknown>>
  reviews: Array<Record<string, unknown>>
  selectedChannels: string[]
  taskStatus: string
  onViewChannel: (channel: string) => void
  onEditChannel: (channel: string) => void
  onRegenerate: (channel: string) => void
}

export function ChannelMatrix({
  versions,
  reviews,
  selectedChannels,
  taskStatus,
  onViewChannel,
  onEditChannel,
  onRegenerate,
}: ChannelMatrixProps) {
  const [compareMode, setCompareMode] = useState(false)

  const masterVersion = useMemo(
    () =>
      versions.find(
        (v) =>
          v.content_type === 'master_approved' ||
          v.content_type === 'master_draft' ||
          v.channel === null
      ),
    [versions]
  )

  const channelVersions = useMemo(() => {
    const map: Record<string, Record<string, unknown>> = {}
    for (const ch of selectedChannels) {
      const chVersions = versions
        .filter((v) => v.channel === ch)
        .sort(
          (a, b) => (Number(b.version_number) ?? 0) - (Number(a.version_number) ?? 0)
        )
      if (chVersions.length > 0) {
        map[ch] = chVersions[0]
      }
    }
    return map
  }, [versions, selectedChannels])

  const channelReviews = useMemo(() => {
    const map: Record<string, Array<Record<string, unknown>>> = {}
    for (const r of reviews) {
      const contentVersionId = r.content_version_id as string
      const cv = versions.find((v) => v.content_version_id === contentVersionId)
      const ch = cv?.channel as string
      if (ch && selectedChannels.includes(ch)) {
        if (!map[ch]) map[ch] = []
        map[ch].push(r)
      }
    }
    return map
  }, [reviews, versions, selectedChannels])

  function channelStatus(channel: string): 'approved' | 'pending' | 'failed' | 'not_started' | 'warning' {
    const v = channelVersions[channel]
    if (!v) return 'not_started'
    if (v.approval_status === 'approved') {
      const revs = channelReviews[channel] ?? []
      const hasWarnings = revs.some((r) => r.passed === false || (r.issues as unknown[])?.length > 0)
      return hasWarnings ? 'warning' : 'approved'
    }
    const revs = channelReviews[channel] ?? []
    if (revs.some((r) => r.passed === false)) return 'failed'
    return 'pending'
  }

  function isStale(channel: string): boolean {
    if (!masterVersion) return false
    const chVersion = channelVersions[channel]
    if (!chVersion) return false
    const masterContentId = masterVersion.content_version_id as string | undefined
    const chMasterRefId = chVersion.master_content_version_id as string | undefined
    return masterContentId != null && chMasterRefId != null && masterContentId !== chMasterRefId
  }

  function requirementChecks(channel: string) {
    const revs = channelReviews[channel] ?? []
    const allIssues = revs
      .flatMap((r) => (r.issues as Array<Record<string, unknown>>) ?? [])
    return {
      format: revs.some((r) => r.review_type === 'channel_format' && r.passed === true),
      facts: revs.some((r) => r.review_type === 'factual' && r.passed === true),
      brand: revs.some((r) => r.review_type === 'brand' && r.passed === true),
      compliance: revs.some((r) => r.review_type === 'compliance' && r.passed === true),
      consistency: revs.some((r) => r.review_type === 'cross_channel_consistency' && r.passed === true),
      issues: allIssues.length,
    }
  }

  const statusLabel = (s: string) =>
    s === 'approved'
      ? '已批准'
      : s === 'pending'
        ? '审查中'
        : s === 'failed'
          ? '未通过'
          : s === 'warning'
            ? '有警告'
            : '尚未生成'

  if (selectedChannels.length === 0) {
    return (
      <div className={styles.contextEmpty}>
        <LayoutGrid size={28} />
        <p>此任务未选择输出渠道。</p>
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 14 }}>
        <button
          className={styles.secondary}
          onClick={() => setCompareMode(!compareMode)}
          style={{ padding: '6px 12px', fontSize: 13 }}
        >
          {compareMode ? '返回卡片视图' : '比较一致性'}
        </button>
      </div>

      {compareMode ? (
        <ChannelCompareTable
          selectedChannels={selectedChannels}
          requirementChecks={requirementChecks}
        />
      ) : (
        <div className={styles.channelMatrix}>
          {masterVersion && (
            <div className={styles.channelMatrixMaster}>
              <span>
                <b>已批准主内容</b> · v
                {String(masterVersion.version_number ?? '?')}
              </span>
              <small>
                渠道版本引用：{masterVersion.immutable_hash
                  ? String(masterVersion.immutable_hash).slice(0, 12) + '…'
                  : '未知'}
              </small>
            </div>
          )}

          {selectedChannels.map((ch) => {
            const v = channelVersions[ch]
            const status = channelStatus(ch)
            const stale = isStale(ch)
            return (
              <div
                key={ch}
                className={styles.channelCard}
                data-status={status === 'not_started' ? 'pending' : status}
                data-stale={stale ? 'true' : 'false'}
              >
                <div className={styles.channelCardHead}>
                  <h4>{channelLabels[ch] ?? ch}</h4>
                  <span className={styles.channelCardStatus} data-status={status}>
                    {statusLabel(status)}
                  </span>
                </div>

                <small style={{ color: '#667085', fontSize: 13 }}>
                  {channelFormats[ch] ?? '自定义格式'}
                </small>

                {v ? (
                  <>
                    <span style={{ fontSize: 13, color: '#475467' }}>
                      版本 v{String(v.version_number ?? '?')}
                      {v.created_by_type === 'human' ? ' (人工)' : v.created_by_type === 'model' ? ' (AI)' : ''}
                    </span>
                    {stale && (
                      <div className={styles.channelCardSource} data-stale="true">
                        <AlertTriangle size={14} />
                        基于旧版本主内容
                      </div>
                    )}
                  </>
                ) : (
                  <span style={{ fontSize: 13, color: '#667085' }}>
                    尚未生成渠道版本
                  </span>
                )}

                {v && <MiniCheckSummary checks={requirementChecks(ch)} />}

                <div className={styles.channelCardActions}>
                  {v ? (
                    <>
                      <button onClick={() => onViewChannel(ch)}>
                        <Eye size={14} /> 查看
                      </button>
                      <button onClick={() => onEditChannel(ch)}>
                        <Edit3 size={14} /> 编辑
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => onRegenerate(ch)}
                      disabled={taskStatus === 'failed'}
                    >
                      <RefreshCw size={14} /> 生成
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function MiniCheckSummary({
  checks,
}: {
  checks: {
    format: boolean
    facts: boolean
    brand: boolean
    compliance: boolean
    consistency: boolean
    issues: number
  }
}) {
  const items = [
    { label: '格式', pass: checks.format },
    { label: '事实', pass: checks.facts },
    { label: '品牌', pass: checks.brand },
    { label: '合规', pass: checks.compliance },
    { label: '一致性', pass: checks.consistency },
  ]
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: 12 }}>
      {items.map((item) => (
        <span
          key={item.label}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 3,
            color: item.pass ? '#067647' : '#d92d20',
          }}
          title={`${item.label}：${item.pass ? '通过' : '未通过'}`}
        >
          {item.pass ? <Check size={12} /> : <X size={12} />}
          {item.label}
        </span>
      ))}
      {checks.issues > 0 && (
        <span style={{ color: '#667085', marginLeft: 'auto' }}>
          <FileWarning size={12} /> {checks.issues} 个问题
        </span>
      )}
    </div>
  )
}

function ChannelCompareTable({
  selectedChannels,
  requirementChecks,
}: {
  selectedChannels: string[]
  requirementChecks: (channel: string) => {
    format: boolean
    facts: boolean
    brand: boolean
    compliance: boolean
    consistency: boolean
    issues: number
  }
}) {
  const dims = ['format', 'facts', 'brand', 'compliance', 'consistency'] as const
  const dimLabels: Record<string, string> = {
    format: '格式检查',
    facts: '事实一致性',
    brand: '品牌规范',
    compliance: '合规',
    consistency: '跨渠道一致性',
  }
  return (
    <table className={styles.channelMatrixCompare}>
      <thead>
        <tr>
          <th>渠道</th>
          {dims.map((d) => (
            <th key={d}>{dimLabels[d]}</th>
          ))}
          <th>问题</th>
        </tr>
      </thead>
      <tbody>
        {selectedChannels.map((ch) => {
          const checks = requirementChecks(ch)
          return (
            <tr key={ch}>
              <td>
                <strong>{channelLabels[ch] ?? ch}</strong>
              </td>
              {dims.map((d) => (
                <td
                  key={d}
                  className={checks[d] ? 'pass' : 'fail'}
                >
                  {checks[d] ? <Check size={14} /> : <X size={14} />}
                </td>
              ))}
              <td className={checks.issues === 0 ? 'pass' : 'warn'}>
                {checks.issues === 0 ? (
                  <Check size={14} />
                ) : (
                  `${checks.issues} 项`
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
