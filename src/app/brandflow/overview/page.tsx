'use client'

import { useBrandFlow } from '@/hooks/useBrandFlow'
import { AlertTriangle, Bell, ChevronRight, CircleHelp, FileText, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import Link from 'next/link'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/styles/brandflow'

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

export default function BrandFlowOverview() {
  const flow = useBrandFlow()
  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载</h1>
        <p>获取任务列表与系统状态。</p>
      </main>
    )
  }

  const pendingApprovals = flow.tasks.filter((t) =>
    ['waiting_for_outline_approval', 'waiting_for_master_approval', 'waiting_for_final_approval'].includes(t.status)
  )
  const running = flow.tasks.filter((t) =>
    ['researching', 'generating_master', 'reviewing_master', 'generating_channels', 'reviewing_channels'].includes(t.status)
  )
  const failed = flow.tasks.filter((t) => t.status === 'failed')
  const completed = flow.tasks.filter((t) => t.status === 'completed')

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div>
          <span>BrandFlow</span>
          <h1>概览</h1>
        </div>
        <Link href="/brandflow/tasks?create=true" className={styles.primary}>创建任务</Link>
      </header>
      {flow.error && <RecoveryBanner error={flow.error} onRetry={flow.refreshTasks} />}

      {(pendingApprovals.length > 0 || failed.length > 0) && (
        <section className={styles.actionStrip}>
          <div>
            <span className={styles.warningIcon}><Bell size={18} /></span>
            <p>
              <b>{pendingApprovals.length + failed.length} 个任务需要人工操作</b>
              <small>
                {pendingApprovals.length > 0 && `${pendingApprovals.length} 个审批待处理`}
                {pendingApprovals.length > 0 && failed.length > 0 && ' · '}
                {failed.length > 0 && `${failed.length} 个任务已停止`}
              </small>
            </p>
          </div>
          <Link href="/brandflow/tasks">打开任务收件箱</Link>
        </section>
      )}

      <div className={styles.overviewGrid}>
        <section className={styles.areaCard}>
          <div className={styles.areaCardHeader}>
            <div>
              <span className={styles.panelLabel}>需要操作</span>
              <h2>待你处理</h2>
            </div>
            <Link href="/brandflow/tasks">查看全部</Link>
          </div>
          {pendingApprovals.length === 0 ? (
            <div className={styles.contextEmpty}>
              <ShieldCheck size={20} />
              没有待处理的审批。
            </div>
          ) : (
            pendingApprovals.slice(0, 5).map((task) => (
              <Link
                key={task.task_id}
                href={`/brandflow/tasks/${task.task_id}`}
                className={styles.taskRow}
              >
                <span className={styles.statusDot} data-status={task.status} />
                <span>
                  <strong>{task.title}</strong>
                  <small>{statusLabel[task.status] ?? task.status}</small>
                </span>
                <ChevronRight size={16} />
              </Link>
            ))
          )}
        </section>

        <section className={styles.areaCard}>
          <div className={styles.areaCardHeader}>
            <div>
              <span className={styles.panelLabel}>正在运行</span>
              <h2>正在运行</h2>
            </div>
          </div>
          {running.length === 0 ? (
            <div className={styles.contextEmpty}>
              <Loader2 size={20} />
              当前无运行中的任务。
            </div>
          ) : (
            running.map((task) => (
              <Link
                key={task.task_id}
                href={`/brandflow/tasks/${task.task_id}`}
                className={styles.taskRow}
              >
                <span className={styles.statusDot} data-status={task.status} />
                <span>
                  <strong>{task.title}</strong>
                  <small>{statusLabel[task.status] ?? task.status}</small>
                </span>
                <ChevronRight size={16} />
              </Link>
            ))
          )}
          {failed.length > 0 && (
            <div className={styles.systemNotice}>
              <span className={styles.statusDot} data-status="failed" />
              <p>
                <b>{failed.length} 个任务需要恢复</b>
                <small>前往任务中心查看失败原因。</small>
              </p>
            </div>
          )}
        </section>
      </div>

      <section className={styles.areaCard}>
        <div className={styles.areaCardHeader}>
          <div>
            <span className={styles.panelLabel}>最近完成</span>
            <h2>最近完成</h2>
          </div>
          <Link href="/brandflow/tasks">查看任务中心</Link>
        </div>
        {completed.length === 0 ? (
          <div className={styles.contextEmpty}>
            <FileText size={20} />
            尚无已完成的任务。
          </div>
        ) : (
          <div className={styles.compactTable}>
            <div className={styles.tableHead}>
              <span>内容任务</span>
              <span>状态</span>
              <span>渠道</span>
            </div>
            {completed.slice(0, 5).map((task) => (
              <Link key={task.task_id} href={`/brandflow/tasks/${task.task_id}`} className={styles.tableRow}>
                <b>{task.title}</b>
                <span>{statusLabel[task.status]}</span>
                <span>{task.selected_channels.length} 个渠道</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className={styles.areaCard}>
        <span className={styles.panelLabel}>系统状态</span>
        <h2>系统服务</h2>
        <div className={styles.systemNotice}>
          <span className={styles.statusDot} />
          <p>
            <b>知识与工具服务前端状态</b>
            <small>状态为直接从后端获取的实时数据，不包含虚构指标。</small>
          </p>
        </div>
      </section>
    </main>
  )
}

function RecoveryBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const accessError = error instanceof BrandFlowApiError && (error.status === 401 || error.status === 403 || error.status === 404)
  return (
    <div className={styles.recovery} role="alert">
      <AlertTriangle />
      <span>
        <b>{accessError ? '当前登录身份无法访问此工作区' : '服务暂时不可用'}</b>
        <small>{accessError ? '请切换工作区或重新登录。' : `${error.message} 已保存的内容保持安全。`}</small>
      </span>
      <button onClick={onRetry}>{accessError ? '重新验证' : '重试'}</button>
    </div>
  )
}
