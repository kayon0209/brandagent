'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useBrandFlow } from '@/hooks/useBrandFlow'
import { statusLabel, channelLabel, approvalLabel, versionTitle } from '@/lib/brandflow-labels'
import { BrandFlowApiError, BrandFlowWorkspace } from '@/lib/api/brandflow'
import { VersionDiffViewer } from '@/components/editor/VersionDiffViewer'
import { ChannelMatrix } from '@/components/editor/ChannelMatrix'
import { BlockEditor } from '@/components/editor/BlockEditor'
import { ApprovalDialog } from '@/components/editor/ApprovalDialog'
import { ExportDialog } from '@/components/editor/ExportDialog'
import { RecoveryWizard } from '@/components/editor/RecoveryWizard'
import {
  AlertTriangle, ArrowLeft, Check, FileText, Loader2, RefreshCw,
  ShieldCheck, Gauge, FileCode, Grid3X3, GitCompare, ScrollText,
} from 'lucide-react'
import styles from '@/styles/brandflow'

type ContentTab = 'content' | 'blocks' | 'channels' | 'diff'

const stages = [
  'Brief', 'Research', 'Outline', 'Master content',
  'Channel variants', 'Final approval', 'Export',
]
const stageByStatus: Record<string, number> = {
  draft: 0, validating_brief: 0, waiting_for_clarification: 0,
  researching: 1, waiting_for_outline_approval: 2,
  generating_master: 3, reviewing_master: 3, waiting_for_master_approval: 3,
  generating_channels: 4, reviewing_channels: 4, waiting_for_final_approval: 5,
  exporting: 6, completed: 6,
}

export default function BrandFlowTaskDetail() {
  const params = useParams<{ taskId: string }>()
  const flow = useBrandFlow()
  const [tab, setTab] = useState<'lineage' | 'issues' | 'versions' | 'tools'>('issues')
  const [contentTab, setContentTab] = useState<ContentTab>('content')
  const [approvalDialog, setApprovalDialog] = useState<{
    open: boolean
    requirement: Record<string, unknown> | null
  }>({ open: false, requirement: null })
  const [exportDialog, setExportDialog] = useState(false)
  const [selectedChannel, setSelectedChannel] = useState<string | null>(null)
  const [regeneratingIndex, setRegeneratingIndex] = useState<number | null>(null)
  const [approvalError, setApprovalError] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null)

  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 2500)
      return () => clearTimeout(timer)
    }
  }, [toast])

  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载任务工作区</h1>
        <p>获取最新版本、审批和事件数据。</p>
      </main>
    )
  }

  if (!flow.workspace || flow.workspace.task.task_id !== params.taskId) {
    return (
      <main className={styles.centered}>
        <div><Gauge size={32} /></div>
        <h1>已退出任务视图</h1>
        <p>当前没有打开的任务工作区。</p>
        <section className={styles.centeredAction}>
          <Link href="/brandflow/tasks" className={styles.primary}>返回任务列表</Link>
        </section>
      </main>
    )
  }

  const workspace = flow.workspace
  const task = workspace.task
  const current = stageByStatus[task.status] ?? 0
  const latest = workspace.versions.at(-1) as Record<string, unknown> | undefined
  const pending = workspace.approval_requirements.filter((item) => item.status === 'pending')
  const finalDecision = workspace.human_decisions.find(
    (item) => item.decision_type === 'final_package' && item.decision === 'approve'
  )

  function getDisplayVersion(): Record<string, unknown> | undefined {
    if (!selectedChannel) return latest
    const channelVersion = workspace.versions
      .filter(v => v.channel === selectedChannel)
      .sort((a, b) => (Number(b.version_number) ?? 0) - (Number(a.version_number) ?? 0))[0]
    return (channelVersion as Record<string, unknown> | undefined) || latest
  }
  const displayVersion = getDisplayVersion()
  const displayBlocks = (displayVersion?.structured_blocks || latest?.structured_blocks) as Array<Record<string, unknown>> | undefined

  function openApprovalDialog(requirement: Record<string, unknown>) {
    setApprovalDialog({ open: true, requirement })
  }

  async function handleApprove(comment: string) {
    const requirement = approvalDialog.requirement
    if (!requirement) return
    setApprovalError(null)
    try {
      const type = String(requirement.decision_type)
      const scope = type === 'outline' ? 'outline' : type.startsWith('master_') ? 'master' : type === 'channel' ? `channels/${task.selected_channels[0]}` : 'final'
      await flow.command(`/api/v1/tasks/${task.task_id}/${scope}/approve`, {
        content_version_id: requirement.content_version_id ?? null,
        target_snapshot_hash: requirement.target_snapshot_hash,
        decision: 'approve',
        comment,
      })
      setApprovalDialog({ open: false, requirement: null })
      flow.openTask(task.task_id)
      setToast({ message: '内容已批准', type: 'success' })
    } catch (err) {
      setApprovalError(err instanceof Error ? err.message : '批准操作失败，请重试')
    }
  }

  async function handleReject(reason: string) {
    const requirement = approvalDialog.requirement
    if (!requirement) return
    setApprovalError(null)
    try {
      const type = String(requirement.decision_type)
      const scope = type === 'outline' ? 'outline' : type.startsWith('master_') ? 'master' : type === 'channel' ? `channels/${task.selected_channels[0]}` : 'final'
      await flow.command(`/api/v1/tasks/${task.task_id}/${scope}/reject`, {
        content_version_id: requirement.content_version_id ?? null,
        target_snapshot_hash: requirement.target_snapshot_hash,
        decision: 'reject',
        comment: reason,
      })
      setApprovalDialog({ open: false, requirement: null })
      flow.openTask(task.task_id)
      setToast({ message: '内容已退回修订', type: 'success' })
    } catch (err) {
      setApprovalError(err instanceof Error ? err.message : '拒绝操作失败，请重试')
    }
  }

  return (
    <main className={styles.main}>
      <header className={styles.taskTop}>
        <Link href="/brandflow/tasks" className={styles.back}>
          <ArrowLeft size={16} />
          返回任务
        </Link>
        <div>
          <span>{statusLabel[task.status] ?? task.status}</span>
          <h1>{task.title}</h1>
        </div>
        <button className={styles.secondary} onClick={() => flow.openTask(task.task_id)}>
          <RefreshCw size={14} />
          刷新
        </button>
      </header>
      {flow.error && !task.error && <RecoveryBanner error={flow.error} onRetry={() => flow.openTask(task.task_id)} />}
      {task.error && (
        <RecoveryWizard
          error={task.error}
          onRetry={() => flow.command(`/api/v1/tasks/${task.task_id}/retry`, {})}
          onAbandon={() => {/* TODO: POST cancel */}}
        />
      )}
      <ol className={styles.stepper}>
        {stages.map((stage, index) => (
          <li key={stage} data-state={index < current ? 'done' : index === current ? 'current' : 'future'}>
            <span>{index < current ? <Check size={14} /> : index + 1}</span>
            <b>{stage}</b>
          </li>
        ))}
      </ol>
      <div className={styles.workspaceGrid}>
        <section className={styles.canvas}>
          <div className={styles.canvasHead}>
            <div>
              <small>当前工作</small>
              <h2>{latest ? versionTitle(latest) : '任务 Brief'}</h2>
            </div>
            <span className={styles.badge}>{statusLabel[task.status] ?? task.status}</span>
          </div>

          {/* ── Content Tabs ── */}
          <div className={styles.workspaceTabs}>
            {([
              { key: 'content' as const, icon: ScrollText, label: '主内容' },
              { key: 'blocks' as const, icon: FileCode, label: '块编辑' },
              { key: 'channels' as const, icon: Grid3X3, label: `渠道矩阵${task.selected_channels.length > 0 ? ` · ${task.selected_channels.length} 个渠道` : ''}` },
              { key: 'diff' as const, icon: GitCompare, label: '版本对比' },
            ]).map((item) => (
              <button
                key={item.key}
                data-active={contentTab === item.key}
                onClick={() => setContentTab(item.key)}
              >
                <item.icon size={15} style={{ marginRight: 6 }} />
                {item.label}
              </button>
            ))}
          </div>

          {contentTab === 'content' && (
            <>
              {typeof displayVersion?.content === 'string' ? (
                <article className={styles.content}>
                  {selectedChannel && (
                    <div style={{marginBottom:12,padding:'6px 12px',background:'#eef2ff',borderRadius:6,fontSize:13,color:'#3b5ccc',display:'flex',alignItems:'center',gap:8}}>
                      查看渠道：{selectedChannel === 'wechat_website' ? '微信/官网' : selectedChannel === 'xiaohongshu' ? '小红书' : selectedChannel === 'video_script_60s' ? '60秒视频脚本' : selectedChannel === 'marketing_email' ? '营销邮件' : selectedChannel}
                      <button onClick={() => setSelectedChannel(null)} style={{fontSize:12,color:'#667085',textDecoration:'underline',background:'none',border:'none',cursor:'pointer'}}>返回主内容</button>
                    </div>
                  )}
                  {(displayVersion.content as string).split('\n').map((line, i) => (
                    <p key={i}>{line || '\u00a0'}</p>
                  ))}
                </article>
              ) : (
                <BriefSummary brief={workspace.brief} />
              )}
            </>
          )}

          {contentTab === 'blocks' && (
            <>
              {selectedChannel && (
                <div style={{marginBottom:12,padding:'6px 12px',background:'#eef2ff',borderRadius:6,fontSize:13,color:'#3b5ccc',display:'flex',alignItems:'center',gap:8}}>
                  编辑渠道：{selectedChannel === 'wechat_website' ? '微信/官网' : selectedChannel === 'xiaohongshu' ? '小红书' : selectedChannel === 'video_script_60s' ? '60秒视频脚本' : selectedChannel === 'marketing_email' ? '营销邮件' : selectedChannel}
                  <button onClick={() => setSelectedChannel(null)} style={{fontSize:12,color:'#667085',textDecoration:'underline',background:'none',border:'none',cursor:'pointer'}}>返回主内容</button>
                </div>
              )}
              <BlockEditor
                content={typeof displayVersion?.content === 'string' ? displayVersion.content as string : ''}
                structuredBlocks={displayBlocks}
                issues={workspace.issues}
                regeneratingIndex={regeneratingIndex}
                onSave={() => {/* handled by accepting blocks */}}
                onAcceptBlock={async (index) => {
                  await flow.command(`/api/v1/tasks/${task.task_id}/blocks/${index}/accept`, {})
                  flow.openTask(task.task_id)
                }}
                onRejectBlock={async (index) => {
                  await flow.command(`/api/v1/tasks/${task.task_id}/blocks/${index}/reject`, { revision_instruction: '请重新生成此段落' })
                  flow.openTask(task.task_id)
                }}
                onRegenerateBlock={async (index) => {
                  setRegeneratingIndex(index)
                  try {
                    await flow.command(`/api/v1/tasks/${task.task_id}/regenerate_block`, { block_index: index })
                  } finally {
                    setRegeneratingIndex(null)
                  }
                }}
              />
            </>
          )}

          {contentTab === 'channels' && (
            <ChannelMatrix
              versions={workspace.versions}
              reviews={workspace.reviews}
              selectedChannels={task.selected_channels}
              taskStatus={task.status}
              onViewChannel={(channel) => {
                setSelectedChannel(channel)
                setContentTab('content')
              }}
              onEditChannel={(channel) => {
                setSelectedChannel(channel)
                setContentTab('blocks')
              }}
              onRegenerate={(channel) => {
                void flow.command(`/api/v1/tasks/${task.task_id}/channels/generate`, {
                  channels: [channel],
                })
              }}
            />
          )}

          {contentTab === 'diff' && (
            <VersionDiffViewer versions={workspace.versions} />
          )}

          {pending.length > 0 && (
            <section className={styles.approvals}>
              <h3>需要人工操作</h3>
              {pending.map((requirement) => (
                <div key={String(requirement.approval_requirement_id)}>
                  <span>
                    <b>{approvalLabel(String(requirement.decision_type))}</b>
                    <small>{latest ? versionTitle(latest) : '当前版本'}</small>
                  </span>
                  <button className={styles.primary} onClick={() => openApprovalDialog(requirement)}>
                    检查并批准
                  </button>
                </div>
              ))}
            </section>
          )}
          {task.status === 'completed' &&
            !workspace.versions.some((item) => String(item.content_type).startsWith('channel_')) && (
              <button
                className={styles.primary}
                onClick={() => flow.command(`/api/v1/tasks/${task.task_id}/channels/generate`, {})}
              >
                生成渠道版本
              </button>
            )}
          {task.status === 'reviewing_channels' &&
            pending.every((item) => item.decision_type !== 'channel') && (
              <button
                className={styles.primary}
                onClick={() => flow.command(`/api/v1/tasks/${task.task_id}/final/prepare`, {})}
              >
                运行最终门禁
              </button>
            )}
          {finalDecision && (
            <div className={styles.exportActions}>
              <button className={styles.primary} onClick={() => setExportDialog(true)}>
                导出内容
              </button>
            </div>
          )}
        </section>
        <aside className={styles.context}>
          <div className={styles.tabs}>
            {(['issues', 'versions', 'lineage', 'tools'] as const).map((item) => (
              <button key={item} data-active={tab === item} onClick={() => setTab(item)}>
                {{ issues: '问题', versions: '版本', lineage: '谱系', tools: '工具' }[item]}
              </button>
            ))}
          </div>
          <ContextContent tab={tab} workspace={workspace} />
        </aside>
      </div>
      <ApprovalDialog
        open={approvalDialog.open}
        title={task.title}
        decisionType={String(approvalDialog.requirement?.decision_type ?? '')}
        versionSummary={latest ? versionTitle(latest) : ''}
        snapshotHash={String(approvalDialog.requirement?.target_snapshot_hash ?? '')}
        issues={workspace.issues}
        error={approvalError}
        onApprove={handleApprove}
        onReject={handleReject}
        onClose={() => { setApprovalDialog({ open: false, requirement: null }); setApprovalError(null) }}
      />
      <ExportDialog
        open={exportDialog}
        taskTitle={task.title}
        availableChannels={task.selected_channels}
        approvalVersion={latest ? versionTitle(latest) : '未知'}
        sourceVersion="主内容"
        guardrailPassed={!!finalDecision}
        guardrailIssues={finalDecision ? [] : workspace.issues.filter(i => i.status === 'open').map(i => String(i.reason)).slice(0, 3)}
        onExport={async (channels, formats) => {
          const result = await flow.command<{ artifacts: Record<string, { media_type: string; encoding: string; content: string }> }>(
            `/api/v1/tasks/${task.task_id}/export`, {
              decision_id: finalDecision?.decision_id,
              target_snapshot_hash: finalDecision?.target_snapshot_hash,
              formats,
              channels,
            }
          )
          for (const [format, artifact] of Object.entries(result.artifacts)) {
            const value = artifact.encoding === 'base64'
              ? Uint8Array.from(atob(artifact.content), (c) => c.charCodeAt(0))
              : artifact.content
            const url = URL.createObjectURL(new Blob([value], { type: artifact.media_type }))
            const link = document.createElement('a')
            link.href = url
            link.download = `brandflow-${task.task_id}.${format === 'markdown' ? 'md' : format}`
            link.click()
            URL.revokeObjectURL(url)
          }
          setToast({ message: `已导出 ${Object.keys(result.artifacts).length} 个文件`, type: 'success' })
          setExportDialog(false)
        }}
        onClose={() => setExportDialog(false)}
      />
      {toast && (
        <div style={{position:'fixed',bottom:24,right:24,background:toast.type === 'success' ? '#067647' : '#d92d20',color:'#fff',padding:'12px 24px',borderRadius:8,zIndex:9999,display:'flex',alignItems:'center',gap:8,boxShadow:'0 4px 12px rgba(0,0,0,.15)'}}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            {toast.type === 'success' ? <polyline points="20 6 9 17 4 12"/> : <><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></>}
          </svg>
          {toast.message}
        </div>
      )}
    </main>
  )
}

function ContextContent({ tab, workspace }: { tab: string; workspace: BrandFlowWorkspace }) {
  const items =
    tab === 'issues' ? workspace.issues
    : tab === 'versions' ? workspace.versions
    : tab === 'tools' ? workspace.tool_calls
    : workspace.lineage
  if (!items.length) {
    return (
      <div className={styles.contextEmpty}>
        <Check size={16} />
        当前没有可显示的{{ issues: '未解决问题', versions: '版本记录', lineage: '内容谱系', tools: '工具调用' }[tab]}。
      </div>
    )
  }
  return (
    <div className={styles.contextList}>
      {items.map((item, index) => (
        <div key={String(item.issue_id ?? item.content_version_id ?? item.tool_call_id ?? item.lineage_id ?? index)}>
          <b>
            {tab === 'issues' ? String(item.reason)
            : tab === 'versions' ? versionTitle(item)
            : tab === 'tools' ? String(item.tool_name)
            : String(item.transformation_type ?? '内容谱系')}
          </b>
          <small>
            {tab === 'tools' ? `${String(item.output_status)} · ${String(item.latency_ms)} ms`
            : tab === 'versions' ? `${String(item.created_by_type)} · v${String(item.version_number)}`
            : String(item.status ?? '')}
          </small>
        </div>
      ))}
    </div>
  )
}

function BriefSummary({ brief }: { brief: Record<string, unknown> | null }) {
  if (!brief) return <div className={styles.contextEmpty}><FileText /> Brief 尚未保存。</div>
  return (
    <dl className={styles.brief}>
      {(['topic', 'target_audience', 'publishing_objective', 'desired_audience_action'] as const).map((key) => (
        <div key={key}>
          <dt>{{ topic: '主题', target_audience: '目标受众', publishing_objective: '发布目标', desired_audience_action: '期望行动' }[key]}</dt>
          <dd>{String(brief[key] ?? '待补充')}</dd>
        </div>
      ))}
    </dl>
  )
}

function RecoveryBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const authenticationError = error instanceof BrandFlowApiError && error.status === 401
  const workspaceAccessError = error instanceof BrandFlowApiError && (error.status === 403 || error.status === 404)
  const accessError = authenticationError || workspaceAccessError
  return (
    <div className={styles.recovery} role="alert">
      <AlertTriangle />
      <span>
        <b>{accessError ? '当前登录身份无法访问此工作区' : '服务暂时不可用'}</b>
        <small>
          {authenticationError ? '请在左侧切换工作区，或重新登录后再试。'
          : workspaceAccessError ? '该工作区尚未开通，或你的成员权限已被暂停。请联系工作区管理员。'
          : `${error.message} 已保存的内容保持安全。`}
        </small>
      </span>
      <button onClick={onRetry}>{accessError ? '重新验证' : '重试'}</button>
    </div>
  )
}

