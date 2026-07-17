'use client'

import { useState } from 'react'
import { useBrandFlow } from '@/hooks/useBrandFlow'
import { AlertTriangle, CircleHelp, Download, FileCheck2, Loader2, Play, RefreshCw } from 'lucide-react'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/styles/brandflow'

const metrics = [
  { key: 'master', title: '主内容质量', desc: '事实支持率、引用准确率、Brief 覆盖率' },
  { key: 'channel', title: '渠道质量', desc: '格式符合率、新增无支持主张、核心信息保留' },
  { key: 'workflow', title: '工作流', desc: '完成率、修订次数、人工介入节点' },
  { key: 'mcp', title: 'MCP 可靠性', desc: '工具成功率、超时、降级和恢复' },
  { key: 'human', title: '人工编辑', desc: '字符、句子、事实、结构与语气编辑' },
  { key: 'cost', title: '成本与延迟', desc: '按 provider、model、prompt version 记录' },
]

export default function BrandFlowEvaluation() {
  const flow = useBrandFlow()
  const [evalRunning, setEvalRunning] = useState(false)
  const [evals, setEvals] = useState<Array<Record<string, unknown>>>([])
  const [badCases, setBadCases] = useState<Array<Record<string, unknown>>>([])
  const [reportFormat, setReportFormat] = useState('json')
  const [metricsData, setMetricsData] = useState<Record<string, string>>({})

  async function runEval() {
    setEvalRunning(true)
    try {
      const result = await flow.command<{ run_id: string }>('/api/v1/evaluation/runs', {})
      setEvals([{ run_id: result.run_id, status: 'completed', created_at: new Date().toISOString() }, ...evals])
      const bc = await flow.command<{ items: Array<Record<string, unknown>> }>('/api/v1/evaluation/bad-cases', {})
      setBadCases(bc.items)
      try {
        const fetchedMetrics = await flow.command<Record<string, string>>('/api/v1/evaluation/metrics', {})
        setMetricsData(fetchedMetrics)
      } catch {
        /* metrics fetch failure is non-critical */
      }
    } catch {
      /* error handled by hook */
    } finally {
      setEvalRunning(false)
    }
  }

  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载评估数据</h1>
        <p>获取质量指标与评估运行记录。</p>
      </main>
    )
  }

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div>
          <span>BrandFlow / Evaluation</span>
          <h1>质量与工作流评估</h1>
        </div>
        <button className={styles.primary} onClick={runEval} disabled={evalRunning}>
          {evalRunning ? <Loader2 className={styles.spin} size={16} /> : <Play size={16} />}
          {evalRunning ? '运行中…' : '运行评估'}
        </button>
      </header>
      {flow.error && (
        <div className={styles.recovery} role="alert">
          <AlertTriangle />
          <span><b>数据加载失败</b><small>{flow.error.message}</small></span>
          <button onClick={flow.refreshTasks}>重试</button>
        </div>
      )}

      {evals.length === 0 && (
        <div className={styles.evalNotice}>
          <CircleHelp size={18} />
          <p>
            <b>尚未运行评估</b>
            <small>点击上方{'运行评估'}按钮，系统将在版本化任务集上测量内容质量、工作流成功率和成本指标。运行通常需要 1-2 分钟。</small>
          </p>
        </div>
      )}

      <div className={styles.metricGrid}>
        {metrics.map(({ key, title, desc }) => (
          <article className={styles.metricCard} key={key}>
            <span>{metricsData[key] ?? '未测量'}</span>
            <h2>{title}</h2>
            <p>{desc}</p>
          </article>
        ))}
      </div>

      {evals.length > 0 && (
        <>
          <section className={styles.areaCard}>
            <div className={styles.areaCardHeader}>
              <div>
                <span className={styles.panelLabel}>RECENT EVALUATION RUNS</span>
                <h2>评估运行历史</h2>
              </div>
              <div>
                <button
                  onClick={() => setReportFormat(reportFormat === 'json' ? 'markdown' : 'json')}
                  className={styles.secondary}
                >
                  {reportFormat.toUpperCase()} 报告
                </button>
              </div>
            </div>
            {evals.map((item, i) => (
              <div key={i} className={styles.progressTask}>
                <div>
                  <b>Run {String(item.run_id).slice(0, 8)}…</b>
                  <span>{String(item.status)}</span>
                </div>
                <p>{String(item.created_at)}</p>
              </div>
            ))}
          </section>

          {badCases.length > 0 && (
            <section className={styles.areaCard}>
              <div className={styles.areaCardHeader}>
                <div>
                  <span className={styles.panelLabel}>BAD CASES</span>
                  <h2>需要关注的案例</h2>
                </div>
              </div>
              {badCases.map((item, i) => (
                <div key={i} className={styles.taskRow}>
                  <span><b>{String(item.title ?? 'Untitled')}</b></span>
                  <small>{String(item.severity ?? 'warning')}</small>
                </div>
              ))}
            </section>
          )}
        </>
      )}
    </main>
  )
}
