'use client'

import { useBrandFlow } from '@/hooks/useBrandFlow'
import { channelLabel } from '@/lib/brandflow-labels'
import { AlertTriangle, Check, LayoutGrid, Loader2, ShieldCheck } from 'lucide-react'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/styles/brandflow'

const channels = [
  { id: 'wechat_website', label: '微信 / 官网', format: '长文', desc: '企业公众号与官网文章，支持富文本、图片与结构化排版。' },
  { id: 'xiaohongshu', label: '小红书', format: '短帖', desc: '社交媒体短文，强调视觉与生活化表达，限制 1000 字。' },
  { id: 'video_script_60s', label: '60 秒视频脚本', format: '视频', desc: '短视频脚本，约 56-60 秒朗读时长，适配口播节奏。' },
  { id: 'marketing_email', label: '营销邮件', format: '邮件', desc: '企业营销邮件，包含主题、正文、CTA，支持 HTML 渲染。' },
]

export default function BrandFlowChannels() {
  const flow = useBrandFlow()
  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载渠道信息</h1>
        <p>获取渠道规范与配置。</p>
      </main>
    )
  }

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div>
          <span>BrandFlow / Channels</span>
          <h1>渠道规范管理</h1>
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
            <span className={styles.panelLabel}>AVAILABLE CHANNELS</span>
            <h2>支持的内容渠道</h2>
          </div>
        </div>
        <p className={styles.readingText}>
          四个渠道均从同一已批准主内容版本派生，每个渠道有独立的格式规范、合规检查和审批流程。
          渠道规范由 MCP 工具加载，与品牌规范一起在任务运行时使用。
        </p>
        <div className={styles.channelGrid}>
          {channels.map((ch) => (
            <article className={styles.channelCard} key={ch.id}>
              <header>
                <span>{ch.label.slice(0, 1)}</span>
                <div>
                  <h2>{ch.label}</h2>
                  <p>{ch.format} · 当前生效规范</p>
                </div>
                <em className={styles.successBadge}>Available</em>
              </header>
              <p className={styles.channelPreviewText}>{ch.desc}</p>
              <footer>
                <ShieldCheck size={14} />
                <small>从已批准主版本生成</small>
              </footer>
            </article>
          ))}
        </div>
      </section>
    </main>
  )
}
