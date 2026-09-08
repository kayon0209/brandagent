import Link from 'next/link'

import styles from '@/components/consumer/materials/consumer-materials.module.css'

/** round-3g B — 风格档案 detail view; pure presentational so tests can
 * mount it without the page's data plumbing. Card titles follow the spec:
 * 语言节奏 / 开篇方式 / 结构习惯 / 选题视角 / 素材偏好 / 收束方式. */

export const ARCHIVE_LAYER_META: Array<{ key: string; title: string; group: string }> = [
  { key: 'l1_language_dna', title: '语言节奏', group: '怎么写' },
  { key: 'l2_structure_template', title: '开篇方式', group: '怎么写' },
  { key: 'l3_topic_logic', title: '结构习惯', group: '怎么想' },
  { key: 'l4_evidence_strategy', title: '选题视角', group: '怎么想' },
  { key: 'l5_cognitive_frame', title: '素材偏好', group: '怎么想' },
  { key: 'l6_visual_guide', title: '收束方式', group: '怎么呈现' },
]

export interface ArchiveLayer {
  rules: string[]
  summary: string
}

export interface ArchiveReport {
  report_id: string
  form: string
  language: string
  created_at: string
  layers: Record<string, ArchiveLayer>
  corpus_stats?: { article_count?: number; total_chars?: number }
  corpus_articles?: Array<{ index: number; title?: string; excerpt: string; char_count: number }>
}

export function StyleArchive({
  report,
  serial,
  onClose,
  onCopy,
  onDownload,
}: {
  report: ArchiveReport
  serial: string
  onClose(): void
  onCopy(): void
  onDownload(): void
}) {
  const articleCount = report.corpus_stats?.article_count ?? report.corpus_articles?.length ?? 0
  const date = report.created_at?.slice(0, 10) ?? '—'
  const chineseDate = (() => {
    const m = date.match(/^(\d{4})-(\d{2})-(\d{2})$/)
    return m ? `${m[1]} 年 ${Number(m[2])} 月 ${Number(m[3])} 日` : date
  })()

  // 摘要条：每层 summary 的前半句（首个句读截断）
  const summaryTags = ARCHIVE_LAYER_META.map(layer => {
    const content = report.layers[layer.key]
    if (!content?.summary) return null
    const half = content.summary.split(/[。；;!?！？]/)[0]
    return { title: layer.title, text: half || content.summary }
  }).filter(Boolean) as Array<{ title: string; text: string }>

  // 「我们会留意你」：从有规则的层派生，一句一项
  const watchItems = ARCHIVE_LAYER_META.map(layer => {
    const content = report.layers[layer.key]
    if (!content || content.rules.length === 0) return null
    return { title: layer.title, first: content.rules[0] }
  }).filter(Boolean) as Array<{ title: string; first: string }>

  return (
    <article className={styles.styleReport} data-testid="style-archive">
      {/* B1 档案头 */}
      <header className={styles.styleReportHead}>
        <div>
          <h3 className={styles.styleReportHeading}>
            你的风格档案 <span className={styles.archiveSerial} data-testid="archive-serial">{serial}</span>
          </h3>
          <p className={styles.styleReportMeta} data-testid="archive-basis">
            基于 {chineseDate} · {articleCount} 篇文章学习
          </p>
        </div>
        <div className={styles.styleReportActions}>
          <button type="button" className={styles.styleReportAction} onClick={onCopy}>
            复制规则
          </button>
          <button type="button" className={styles.styleReportAction} onClick={onDownload}>
            下载规则文件
          </button>
          <Link href={`/app?apply=${report.report_id}`} className={styles.styleReportActionPrimary} data-testid="style-apply">
            应用到写作
          </Link>
          <button type="button" className={styles.styleReportAction} data-testid="archive-supplement" onClick={onClose}>
            补充样本
          </button>
        </div>
      </header>

      {/* B2 档案摘要条 */}
      {summaryTags.length > 0 && (
        <ul className={styles.archiveTagRow} data-testid="archive-tags" aria-label="风格摘要">
          {summaryTags.map(tag => (
            <li key={tag.title}>
              <strong>{tag.title}</strong>
              <span>{tag.text}</span>
            </li>
          ))}
        </ul>
      )}

      {/* B3+B4 六卡网格 + 留意你侧栏 */}
      <div className={styles.archiveGrid}>
        <div className={styles.archiveCards}>
          {ARCHIVE_LAYER_META.map((layer, layerIndex) => {
            const content = report.layers[layer.key]
            if (!content) return null
            const article = report.corpus_articles?.find(item => item.index === layerIndex + 1)
            return (
              <section key={layer.key} className={styles.archiveCard} data-testid={`archive-card-${layer.key}`}>
                <h4>
                  <span className={styles.styleLayerGroup}>{layer.group}</span> {layer.title}
                </h4>
                <p className={styles.styleLayerSummary}>{content.summary}</p>
                {content.rules.length > 0 ? (
                  <ul className={styles.styleRules}>
                    {content.rules.slice(0, 4).map((rule, index) => (
                      <li key={index}>{rule.length > 64 ? `${rule.slice(0, 64)}…` : rule}</li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.styleRulesEmpty}>此层在当前语料中无法可靠推断。</p>
                )}
                {article && (
                  <a
                    className={styles.archiveSeeSample}
                    href={`#archive-sample-${article.index}`}
                    aria-label={`查看${layer.title}的样本依据`}
                  >
                    见样 →
                  </a>
                )}
              </section>
            )
          })}
        </div>

        {/* B4 右侧「我们会留意你」sticky */}
        {watchItems.length > 0 && (
          <aside className={styles.archiveWatchRail} data-testid="archive-watch" aria-label="我们会留意你">
            <h4>我们会留意你</h4>
            <ul>
              {watchItems.map(item => (
                <li key={item.title}>
                  <strong>{item.title}</strong>——{item.first}
                </li>
              ))}
            </ul>
            <p className={styles.archiveWatchNote}>在你写作时，AI 会按这份档案留意这些习惯。</p>
          </aside>
        )}
      </div>

      {/* B5 样本依据区 */}
      {report.corpus_articles && report.corpus_articles.length > 0 && (
        <section className={styles.archiveBasis} aria-label="样本依据" data-testid="archive-basis-list">
          <h3 className={styles.sectionTitle}>{report.corpus_articles.length} 篇样本依据</h3>
          <ul>
            {report.corpus_articles.map(article => (
              <li key={article.index} id={`archive-sample-${article.index}`}>
                <strong>#{article.index}</strong>
                <span className={styles.archiveBasisTitle}>{article.title || `参考文章 ${article.index}`}</span>
                <span className={styles.archiveBasisMeta}>{article.char_count} 字</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className={styles.styleReportFooter}>
        补充新样本会生成新档案；历史档案保留，可随时回看。
      </footer>
    </article>
  )
}
