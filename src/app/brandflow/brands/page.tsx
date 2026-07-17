'use client'

import { useBrandFlow } from '@/hooks/useBrandFlow'
import { AlertTriangle, Check, FileText, Loader2, ShieldCheck } from 'lucide-react'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/styles/brandflow'

export default function BrandFlowBrands() {
  const flow = useBrandFlow()
  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载品牌信息</h1>
        <p>获取品牌规范与生效版本。</p>
      </main>
    )
  }

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div>
          <span>BrandFlow / Brands</span>
          <h1>品牌规范管理</h1>
        </div>
      </header>
      {flow.error && (
        <div className={styles.recovery} role="alert">
          <AlertTriangle />
          <span><b>数据加载失败</b><small>{flow.error.message}</small></span>
          <button onClick={flow.refreshTasks}>重试</button>
        </div>
      )}
      <section className={styles.areaCard}>
        <div className={styles.areaCardHeader}>
          <div>
            <span className={styles.panelLabel}>BRAND PROFILE</span>
            <h2>当前工作区品牌</h2>
          </div>
        </div>
        <p className={styles.readingText}>
          品牌规范由 MCP 工具从品牌文档中提取并版本化管理。每个任务运行时加载当前生效规范版本，
          并在合规审查中检查内容是否符合品牌语言、术语和禁止声明要求。
        </p>
        <div className={styles.knowledgeEmpty}>
          <ShieldCheck size={48} />
          <h3>品牌规范随任务运行加载</h3>
          <p>
            工作区品牌配置从 MCP 品牌工具中获取。首个任务运行时会自动加载并缓存品牌规范版本。
            规范变更将使依赖该版本的审批失效，确保内容始终通过最新标准检查。
          </p>
        </div>
      </section>
    </main>
  )
}
