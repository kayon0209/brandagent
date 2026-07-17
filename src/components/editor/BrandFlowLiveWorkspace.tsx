'use client'

import { FormEvent, ReactNode, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  Check,
  ChevronRight,
  CircleDot,
  FileText,
  Gauge,
  LayoutGrid,
  Loader2,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { useBrandFlow } from '@/hooks/useBrandFlow'
import { BrandFlowApiError, BrandFlowWorkspace } from '@/lib/api/brandflow'
import styles from './brandflow-live-workspace.module.css'

const stages = [
  'Brief',
  'Research',
  'Outline',
  'Master content',
  'Channel variants',
  'Final approval',
  'Export',
]
const stageByStatus: Record<string, number> = {
  draft: 0,
  validating_brief: 0,
  waiting_for_clarification: 0,
  researching: 1,
  waiting_for_outline_approval: 2,
  generating_master: 3,
  reviewing_master: 3,
  waiting_for_master_approval: 3,
  generating_channels: 4,
  reviewing_channels: 4,
  waiting_for_final_approval: 5,
  exporting: 6,
  completed: 6,
}
const statusLabel: Record<string, string> = {
  draft: 'Brief 草稿',
  validating_brief: '正在校验 Brief',
  waiting_for_clarification: '等待补充信息',
  researching: '正在检索权威事实',
  waiting_for_outline_approval: '等待大纲审批',
  generating_master: '正在生成主内容',
  reviewing_master: '正在审查主内容',
  waiting_for_master_approval: '等待主内容审批',
  generating_channels: '正在生成渠道版本',
  reviewing_channels: '渠道审查中',
  waiting_for_final_approval: '等待最终审批',
  exporting: '正在准备导出',
  completed: '已完成',
  failed: '已停止',
  cancelled: '已取消',
}

export function BrandFlowLiveWorkspace() {
  const flow = useBrandFlow()
  const [creating, setCreating] = useState(false)
  if (!flow.isLoaded || flow.loading)
    return (
      <CenteredState
        icon={<Loader2 className={styles.spin} />}
        title="正在加载工作区"
        detail="读取任务、审批与保存状态。"
      />
    )
  if (flow.workspace)
    return (
      <TaskWorkspace
        workspace={flow.workspace}
        error={flow.error}
        onBack={flow.closeTask}
        onCommand={flow.command}
        onRefresh={() => flow.openTask(flow.workspace!.task.task_id)}
      />
    )
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>
        <header className={styles.topbar}>
          <div>
            <span>BrandFlow / Tasks</span>
            <h1>内容任务</h1>
          </div>
          <button className={styles.primary} onClick={() => setCreating(true)}>
            创建任务
          </button>
        </header>
        {flow.error && <RecoveryBanner error={flow.error} onRetry={flow.refreshTasks} />}
        {creating ? (
          <CreateTask
            onCancel={() => setCreating(false)}
            onCreate={async (body) => {
              const task = await flow.command<{ task_id: string }>('/api/v1/tasks', body)
              setCreating(false)
              await flow.openTask(task.task_id)
            }}
          />
        ) : flow.tasks.length === 0 ? (
          <EmptyState onCreate={() => setCreating(true)} />
        ) : (
          <section className={styles.taskList} aria-label="任务列表">
            {flow.tasks.map((task) => (
              <button
                key={task.task_id}
                className={styles.taskRow}
                onClick={() => flow.openTask(task.task_id)}
              >
                <span className={styles.statusDot} data-status={task.status} />
                <span>
                  <strong>{task.title}</strong>
                  <small>
                    {statusLabel[task.status] ?? task.status} · {task.selected_channels.length}{' '}
                    个渠道
                  </small>
                </span>
                <ChevronRight />
              </button>
            ))}
          </section>
        )}
      </main>
    </div>
  )
}

function Sidebar() {
  return (
    <aside className={styles.sidebar}>
      <div className={styles.logo}>
        <b>B</b>
        <span>
          <strong>BrandFlow</strong>
          <small>内容工作区</small>
        </span>
      </div>
      <nav>
        <a className={styles.active}>
          <Gauge />
          概览
        </a>
        <a>
          <FileText />
          任务
        </a>
        <a>
          <BookOpen />
          知识
        </a>
        <a>
          <LayoutGrid />
          渠道
        </a>
      </nav>
      <div className={styles.system}>
        <CircleDot />
        状态来自真实服务
      </div>
    </aside>
  )
}

function TaskWorkspace({
  workspace,
  error,
  onBack,
  onCommand,
  onRefresh,
}: {
  workspace: BrandFlowWorkspace
  error: Error | null
  onBack: () => void
  onCommand: <T>(path: string, body: unknown, key?: string) => Promise<T>
  onRefresh: () => void
}) {
  const [tab, setTab] = useState<'lineage' | 'issues' | 'versions' | 'tools'>('issues')
  const task = workspace.task
  const current = stageByStatus[task.status] ?? 0
  const latest = workspace.versions.at(-1)
  const pending = workspace.approval_requirements.filter((item) => item.status === 'pending')
  const finalDecision = workspace.human_decisions.find(
    (item) => item.decision_type === 'final_package' && item.decision === 'approve'
  )
  async function approve(requirement: Record<string, unknown>) {
    const type = String(requirement.decision_type)
    const approvalVersion = workspace.versions.find(
      (version) => version.content_version_id === requirement.content_version_id
    )
    const channel = approvalVersion?.channel
      ? String(approvalVersion.channel)
      : task.selected_channels[0]
    const scope =
      type === 'outline'
        ? 'outline'
        : type.startsWith('master_')
          ? 'master'
          : type === 'channel'
            ? `channels/${channel}`
            : 'final'
    const comment = window.prompt('请输入审批理由。审批将绑定当前不可变版本。')
    if (!comment) return
    await onCommand(`/api/v1/tasks/${task.task_id}/${scope}/approve`, {
      content_version_id: requirement.content_version_id ?? null,
      target_snapshot_hash: requirement.target_snapshot_hash,
      decision: 'approve',
      comment,
    })
  }
  async function exportPackage() {
    if (!finalDecision) return
    const result = await onCommand<{
      artifacts: Record<string, { media_type: string; encoding: string; content: string }>
    }>(`/api/v1/tasks/${task.task_id}/export`, {
      decision_id: finalDecision.decision_id,
      target_snapshot_hash: finalDecision.target_snapshot_hash,
      formats: ['json', 'markdown', 'docx'],
    })
    for (const [format, artifact] of Object.entries(result.artifacts)) {
      const value =
        artifact.encoding === 'base64'
          ? Uint8Array.from(atob(artifact.content), (character) => character.charCodeAt(0))
          : artifact.content
      const url = URL.createObjectURL(new Blob([value], { type: artifact.media_type }))
      const link = document.createElement('a')
      link.href = url
      link.download = `brandflow-${task.task_id}.${format === 'markdown' ? 'md' : format}`
      link.click()
      URL.revokeObjectURL(url)
    }
  }
  async function createPreview() {
    if (!finalDecision) return
    const result = await onCommand<{ artifacts: Record<string, { content: string }> }>(
      `/api/v1/tasks/${task.task_id}/preview`,
      {
        decision_id: finalDecision.decision_id,
        target_snapshot_hash: finalDecision.target_snapshot_hash,
      }
    )
    const preview = result.artifacts?.preview?.content
    if (preview)
      window.open(
        URL.createObjectURL(new Blob([preview], { type: 'text/html' })),
        '_blank',
        'noopener,noreferrer'
      )
  }
  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>
        <header className={styles.taskTop}>
          <button className={styles.back} onClick={onBack}>
            <ArrowLeft />
            返回任务
          </button>
          <div>
            <span>{statusLabel[task.status] ?? task.status}</span>
            <h1>{task.title}</h1>
          </div>
          <button className={styles.secondary} onClick={onRefresh}>
            <RefreshCw />
            刷新
          </button>
        </header>
        {error && <RecoveryBanner error={error} onRetry={onRefresh} />}
        {task.error && (
          <FailurePanel
            error={task.error}
            onRetry={() => onCommand(`/api/v1/tasks/${task.task_id}/retry`, {})}
          />
        )}
        <ol className={styles.stepper}>
          {stages.map((stage, index) => (
            <li
              key={stage}
              data-state={index < current ? 'done' : index === current ? 'current' : 'future'}
            >
              <span>{index < current ? <Check /> : index + 1}</span>
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
            {typeof latest?.content === 'string' ? (
              <article className={styles.content}>
                {latest.content.split('\n').map((line, index) => (
                  <p key={index}>{line || '\u00a0'}</p>
                ))}
              </article>
            ) : (
              <BriefSummary brief={workspace.brief} />
            )}
            {pending.length > 0 && (
              <section className={styles.approvals}>
                <h3>需要人工操作</h3>
                {pending.map((requirement) => (
                  <div key={String(requirement.approval_requirement_id)}>
                    <span>
                      <b>{approvalLabel(String(requirement.decision_type))}</b>
                      <small>
                        版本哈希 {String(requirement.target_snapshot_hash).slice(0, 12)}…
                      </small>
                    </span>
                    <button className={styles.primary} onClick={() => approve(requirement)}>
                      检查并批准
                    </button>
                  </div>
                ))}
              </section>
            )}
            {task.status === 'completed' &&
              !workspace.versions.some((item) =>
                String(item.content_type).startsWith('channel_')
              ) && (
                <button
                  className={styles.primary}
                  onClick={() => onCommand(`/api/v1/tasks/${task.task_id}/channels/generate`, {})}
                >
                  生成渠道版本
                </button>
              )}
            {task.status === 'reviewing_channels' &&
              pending.every((item) => item.decision_type !== 'channel') && (
                <button
                  className={styles.primary}
                  onClick={() => onCommand(`/api/v1/tasks/${task.task_id}/final/prepare`, {})}
                >
                  运行最终门禁
                </button>
              )}
            {finalDecision && (
              <div className={styles.exportActions}>
                <button className={styles.primary} onClick={exportPackage}>
                  导出 Markdown / JSON / DOCX
                </button>
                <button className={styles.secondary} onClick={createPreview}>
                  创建发布预览
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
      </main>
    </div>
  )
}

function ContextContent({
  tab,
  workspace,
}: {
  tab: 'lineage' | 'issues' | 'versions' | 'tools'
  workspace: BrandFlowWorkspace
}) {
  const items =
    tab === 'issues'
      ? workspace.issues
      : tab === 'versions'
        ? workspace.versions
        : tab === 'tools'
          ? workspace.tool_calls
          : workspace.lineage
  if (!items.length)
    return (
      <div className={styles.contextEmpty}>
        <Check />
        当前没有可显示的{tab === 'issues' ? '未解决问题' : '记录'}。
      </div>
    )
  return (
    <div className={styles.contextList}>
      {items.map((item, index) => (
        <div
          key={String(
            item.issue_id ??
              item.content_version_id ??
              item.tool_call_id ??
              item.lineage_id ??
              index
          )}
        >
          <b>
            {tab === 'issues'
              ? String(item.reason)
              : tab === 'versions'
                ? versionTitle(item)
                : tab === 'tools'
                  ? String(item.tool_name)
                  : String(item.transformation_type ?? '内容谱系')}
          </b>
          <small>
            {tab === 'tools'
              ? `${String(item.output_status)} · ${String(item.latency_ms)} ms`
              : tab === 'versions'
                ? `${String(item.created_by_type)} · v${String(item.version_number)}`
                : String(item.status ?? '')}
          </small>
        </div>
      ))}
    </div>
  )
}

function CreateTask({
  onCancel,
  onCreate,
}: {
  onCancel: () => void
  onCreate: (body: unknown) => Promise<void>
}) {
  const [saving, setSaving] = useState(false)
  const [section, setSection] = useState(0)
  const [form, setForm] = useState({
    title: '',
    topic: '',
    brandId: '',
    productId: '',
    audience: '',
    objective: '',
    action: '',
    channels: ['wechat_website'],
  })
  const sections = ['基本信息', '受众与目标', '产品与事实', '渠道与复核']
  const canSubmit = useMemo(
    () =>
      Object.entries(form).every(([key, value]) =>
        key === 'channels' ? value.length > 0 : String(value).trim()
      ),
    [form]
  )
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setSaving(true)
    try {
      await onCreate({
        title: form.title,
        selected_channels: form.channels,
        brief: {
          topic: form.topic,
          brand_id: form.brandId,
          product_id: form.productId,
          target_audience: form.audience,
          publishing_objective: form.objective,
          primary_channel: form.channels[0],
          desired_audience_action: form.action,
        },
      })
    } finally {
      setSaving(false)
    }
  }
  return (
    <form className={styles.create} onSubmit={submit}>
      <header>
        <div>
          <small>GUIDED BRIEF</small>
          <h2>创建内容任务</h2>
          <p>按四个短章节完成 Brief；技术配置不进入内容流程。</p>
        </div>
        <button type="button" className={styles.back} onClick={onCancel}>
          取消
        </button>
      </header>
      <div className={styles.sectionNav}>
        {sections.map((label, index) => (
          <button
            type="button"
            key={label}
            data-active={section === index}
            onClick={() => setSection(index)}
          >
            <span>{index + 1}</span>
            {label}
          </button>
        ))}
      </div>
      <div className={styles.fields}>
        {section === 0 && (
          <>
            <Field
              label="任务名称"
              value={form.title}
              onChange={(title) => setForm({ ...form, title })}
            />
            <Field
              label="主题"
              value={form.topic}
              onChange={(topic) => setForm({ ...form, topic })}
            />
          </>
        )}
        {section === 1 && (
          <>
            <Field
              label="目标受众"
              value={form.audience}
              onChange={(audience) => setForm({ ...form, audience })}
            />
            <Field
              label="发布目标"
              value={form.objective}
              onChange={(objective) => setForm({ ...form, objective })}
            />
            <Field
              label="期望受众行动"
              value={form.action}
              onChange={(action) => setForm({ ...form, action })}
            />
          </>
        )}
        {section === 2 && (
          <>
            <Field
              label="品牌 ID"
              value={form.brandId}
              onChange={(brandId) => setForm({ ...form, brandId })}
            />
            <Field
              label="产品 ID"
              value={form.productId}
              onChange={(productId) => setForm({ ...form, productId })}
            />
          </>
        )}
        {section === 3 && (
          <fieldset>
            <legend>输出渠道</legend>
            {['wechat_website', 'xiaohongshu', 'video_script_60s', 'marketing_email'].map(
              (channel) => (
                <label key={channel}>
                  <input
                    type="checkbox"
                    checked={form.channels.includes(channel)}
                    onChange={(event) =>
                      setForm({
                        ...form,
                        channels: event.target.checked
                          ? [...form.channels, channel]
                          : form.channels.filter((item) => item !== channel),
                      })
                    }
                  />
                  {channelLabel(channel)}
                </label>
              )
            )}
          </fieldset>
        )}
      </div>
      <footer>
        <span>
          {section + 1} / {sections.length} 章节
        </span>
        {section < 3 ? (
          <button type="button" className={styles.primary} onClick={() => setSection(section + 1)}>
            继续
          </button>
        ) : (
          <button className={styles.primary} disabled={!canSubmit || saving}>
            {saving ? '正在创建…' : '提交任务'}
          </button>
        )}
      </footer>
    </form>
  )
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className={styles.field}>
      <span>
        {label}
        <em>必填</em>
      </span>
      <input value={value} onChange={(event) => onChange(event.target.value)} required />
    </label>
  )
}
function BriefSummary({ brief }: { brief: Record<string, unknown> | null }) {
  if (!brief)
    return (
      <div className={styles.contextEmpty}>
        <FileText />
        Brief 尚未保存。
      </div>
    )
  return (
    <dl className={styles.brief}>
      {['topic', 'target_audience', 'publishing_objective', 'desired_audience_action'].map(
        (key) => (
          <div key={key}>
            <dt>
              {
                (
                  {
                    topic: '主题',
                    target_audience: '目标受众',
                    publishing_objective: '发布目标',
                    desired_audience_action: '期望行动',
                  } as Record<string, string>
                )[key]
              }
            </dt>
            <dd>{String(brief[key] ?? '待补充')}</dd>
          </div>
        )
      )}
    </dl>
  )
}
function RecoveryBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const authenticationError = error instanceof BrandFlowApiError && error.status === 401
  const workspaceAccessError =
    error instanceof BrandFlowApiError && (error.status === 403 || error.status === 404)
  const accessError = authenticationError || workspaceAccessError
  return (
    <div className={styles.recovery} role="alert">
      <AlertTriangle />
      <span>
        <b>{accessError ? '当前登录身份无法访问此工作区' : '服务暂时不可用'}</b>
        <small>
          {authenticationError
            ? '请在左侧切换工作区，或重新登录后再试。'
            : workspaceAccessError
              ? '该工作区尚未开通，或你的成员权限已被暂停。请联系工作区管理员。'
            : `${error.message} 已保存的内容保持安全。`}
        </small>
      </span>
      <button onClick={onRetry}>{accessError ? '重新验证' : '重试'}</button>
    </div>
  )
}
function FailurePanel({
  error,
  onRetry,
}: {
  error: NonNullable<BrandFlowWorkspace['task']['error']>
  onRetry: () => void
}) {
  return (
    <div className={styles.failure}>
      <AlertTriangle />
      <div>
        <b>{error.message}</b>
        <p>
          保存状态：{error.saved_work_safe ? '工作已安全保存' : '需要人工核对'} ·{' '}
          {error.requires_human ? '需要人工处理' : '可自动重试'}
        </p>
      </div>
      {error.recoverable && <button onClick={onRetry}>从安全检查点重试</button>}
    </div>
  )
}
function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <section className={styles.empty}>
      <div>
        <FileText />
      </div>
      <h2>还没有内容任务</h2>
      <p>创建首个结构化 Brief。系统会明确显示取证、审批、失败与恢复状态。</p>
      <button className={styles.primary} onClick={onCreate}>
        创建首个任务
      </button>
    </section>
  )
}
function CenteredState({
  icon,
  title,
  detail,
  action,
}: {
  icon: ReactNode
  title: string
  detail: string
  action?: ReactNode
}) {
  return (
    <main className={styles.centered}>
      <div>{icon}</div>
      <h1>{title}</h1>
      <p>{detail}</p>
      {action && <section className={styles.centeredAction}>{action}</section>}
    </main>
  )
}
function versionTitle(item: Record<string, unknown>) {
  const channel = item.channel ? channelLabel(String(item.channel)) : ''
  return `${channel ? `${channel} · ` : ''}${String(item.content_type ?? '内容版本')} v${String(item.version_number ?? '')}`
}
function approvalLabel(type: string) {
  return (
    (
      {
        outline: '批准大纲',
        master_brand: '批准品牌语言',
        master_final: '批准主内容事实与风险',
        channel: '批准渠道版本',
        final_package: '批准最终内容包',
      } as Record<string, string>
    )[type] ?? type
  )
}
function channelLabel(channel: string) {
  return (
    (
      {
        wechat_website: '微信 / 官网',
        xiaohongshu: '小红书',
        video_script_60s: '60 秒视频脚本',
        marketing_email: '营销邮件',
      } as Record<string, string>
    )[channel] ?? channel
  )
}
