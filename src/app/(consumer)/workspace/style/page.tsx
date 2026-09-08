'use client'

/**
 * Style Lab (round-3 six-layer distillation) — /app/style
 *
 * The workflow this page serves (user-specified premise): an agent that
 * imitates from a few sample texts produces distorted copies; distilling
 * a corpus into REUSABLE RULES first, then writing BY the rules, is what
 * actually preserves a voice. Six layers: L1 language DNA, L2 structure
 * template, L3 topic logic, L4 evidence strategy, L5 cognitive frame,
 * L6 visual guide. L1-L2 = how to write, L3-L5 = how to think, L6 = how
 * to present.
 *
 * Round-3b (2026-09-05, 诉求 3 — 深化): the previous page only showed
 * the JSON-shaped rules inside the UI; users couldn't take the rule
 * FILE anywhere. The page now also:
 *   - opens with a collapsible "先看示例" preview so first-timers see
 *     what the output actually looks like before pasting any corpus;
 *   - offers per-report "复制 Markdown / 下载 .md" so the rule file is
 *     a portable artifact (the user can hand it to another tool or
 *     paste it into their own notes);
 *   - exposes "应用到写作" — a one-click jump to /app?apply=report_id so
 *     a future Write page can read the selected style report id and
 *     feed its rules into variant generation. (end-to-end prompt wiring
 *     is v3.1; this round ships the entry point + the marker on the
 *     workspace side).
 */

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'

import { brandFlowRequest } from '@/lib/api/brandflow'
import { fetchConsumerUsage } from '@/lib/consumer-usage'
import { newIdempotencyKey } from '@/lib/idempotency'
import { ConsumerNav } from '@/components/consumer/ConsumerNav'
import styles from '@/components/consumer/materials/consumer-materials.module.css'
import { StyleArchive } from '@/components/consumer/style/StyleArchive'

const FORMS: Array<{ value: string; label: string }> = [
  { value: 'long_form', label: '长文' },
  { value: 'wechat_article', label: '公众号' },
  { value: 'blog', label: '博客' },
  { value: 'newsletter', label: 'Newsletter' },
  { value: 'xiaohongshu_note', label: '小红书图文' },
]

/** round-3f (风格 1): tab labels need a distinguishing date so two runs of
 * the same form don't render as identical 「公众号 · 中文规则」 pills. */
function reportDate(iso?: string): string {
  if (!iso) return '—'
  const m = iso.match(/^\d{4}-(\d{2})-(\d{2})/)
  if (!m) return iso.slice(0, 10)
  return `${Number(m[1])} 月 ${Number(m[2])} 日`
}

const LAYER_META: Array<{ key: string; title: string; group: string; question: string }> = [
  { key: 'l1_language_dna', title: '语言 DNA', group: '怎么写', question: '用什么词、什么节奏说话' },
  { key: 'l2_structure_template', title: '文章结构模板', group: '怎么写', question: '怎样开篇、展开、转折、收束' },
  { key: 'l3_topic_logic', title: '选题逻辑', group: '怎么想', question: '选什么话题、用什么切入角度' },
  { key: 'l4_evidence_strategy', title: '素材策略', group: '怎么想', question: '引用什么、用多少数据与案例' },
  { key: 'l5_cognitive_frame', title: '认知框架', group: '怎么想', question: '默认的世界观与价值判断' },
  { key: 'l6_visual_guide', title: '视觉风格指南', group: '怎么呈现', question: '配图、排版、字体、色彩' },
]

interface StyleLayer {
  rules: string[]
  summary: string
}
interface StyleReport {
  report_id: string
  form: string
  language: string
  layers: Record<string, StyleLayer>
  created_at: string
  /** round-3g B (D4): corpus provenance for the archive view */
  corpus_stats?: { article_count?: number; total_chars?: number }
  corpus_articles?: Array<{ index: number; title?: string; excerpt: string; char_count: number }>
}

const EXAMPLE_REPORT: StyleReport = {
  report_id: 'example',
  form: 'wechat_article',
  language: 'zh',
  layers: {
    l1_language_dna: {
      summary: '句子平均 18 字以内；段落多在 3–5 句；高频用「其实」「说到底」做语气锚点。',
      rules: [
        '句长控制在 8–24 字之间，超过 30 字必拆。',
        '每段不超过 5 句；段落之间留 1 行空行。',
        '语气锚点词：「其实」「说到底」「反过来」每千字至少 3 次。',
        '反例：避免超过 60 字的长复合句；避免书面化「因此」「综上所述」。',
      ],
    },
    l2_structure_template: {
      summary: '反直觉 hook → 一句核心观点 → 三个并列展开 → 反转收束。',
      rules: [
        '开头必须有一个「反直觉事实 / 数据反差」的 hook（≤40 字）。',
        '第二段亮出核心观点（一句话）。',
        '中段三个并列展开，每段首句即论点。',
        '结尾用反转或反问收束，回扣开头的 hook。',
      ],
    },
    l3_topic_logic: {
      summary: '选题偏向「被忽略的小事 / 行业里没人说的真相」。',
      rules: [
        '优先选「被忽略的小事」和「行业里没人说的真相」。',
        '避开纯教程 / 纯情绪宣泄 / 纯新闻陈述。',
        '切入角度三问：写给谁 / 解决什么 / 凭什么是我。',
      ],
    },
    l4_evidence_strategy: {
      summary: '每千字至少 1 个一手案例 + 2 个具体数字；引用来源给到原始链接。',
      rules: [
        '每千字至少 1 个一手案例 + 2 个具体数字。',
        '案例先抛出再佐证；不用「某研究表明」式抽象引用。',
        '数据必给来源链接或具体时间点。',
      ],
    },
    l5_cognitive_frame: {
      summary: '务实且轻度怀疑；偏好「能落地」的解决方案；默认假设读者是同行而非小白。',
      rules: [
        '价值判断倾向：务实 > 理想；轻度怀疑 > 权威。',
        '默认假设读者是同行（不必解释基础概念）。',
        '隐含前提：「真正有用的东西都很朴素」。',
      ],
    },
    l6_visual_guide: {
      summary: '依据语料无法直接推断（纯文本无视觉信息），需补充截图或图像语料后再生成。',
      rules: [],
    },
  },
  created_at: new Date().toISOString(),
}

function reportToMarkdown(report: StyleReport): string {
  const form = FORMS.find(option => option.value === report.form)?.label ?? report.form
  const lang = report.language === 'zh' ? '中文规则' : 'EN rules'
  const date = report.created_at?.slice(0, 10) ?? '—'
  const lines: string[] = []
  lines.push(`# 风格规则文件 · ${form} · ${lang}`)
  lines.push('')
  lines.push(`> 蒸馏于 ${date} · BrandAgent Style Lab (六层蒸馏 round-3)`)
  lines.push('')
  lines.push('---')
  lines.push('')
  for (const layer of LAYER_META) {
    const content = report.layers[layer.key]
    if (!content) continue
    lines.push(`## ${layer.title}（${layer.group} · ${layer.question}）`)
    lines.push('')
    lines.push(`**一句话：** ${content.summary}`)
    lines.push('')
    if (content.rules.length > 0) {
      lines.push('**规则：**')
      lines.push('')
      for (const rule of content.rules) {
        lines.push(`- ${rule}`)
      }
      lines.push('')
    } else {
      lines.push('*该层在当前语料中无法可靠推断。*')
      lines.push('')
    }
  }
  return lines.join('\n')
}

async function copyText(value: string): Promise<void> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  // fallback for browsers that block clipboard API without a user gesture
  if (typeof document !== 'undefined') {
    const textarea = document.createElement('textarea')
    textarea.value = value
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'absolute'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
}

function downloadFile(name: string, content: string, mime: string): void {
  if (typeof window === 'undefined') return
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export default function StyleLabPage() {
  const [articles, setArticles] = useState<string[]>(['', ''])
  const [form, setForm] = useState('wechat_article')
  const [outputLanguage, setOutputLanguage] = useState<'auto' | 'zh' | 'en'>('auto')
  const [analyzing, setAnalyzing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reports, setReports] = useState<StyleReport[]>([])
  const [activeReportId, setActiveReportId] = useState<string | null>(null)
  const [progress, setProgress] = useState<string | null>(null)
  // 诉求 3 — 深化：让首次进入风格实验室的用户立刻看到「产出长这样」，
  // 不用先粘语料才能感知价值。
  const [showExample, setShowExample] = useState(true)
  const [copyStatus, setCopyStatus] = useState<string | null>(null)
  // round-3f (P0-2): export menu open state per report header
  const [exportOpen, setExportOpen] = useState(false)
  // v4 P2-1: gate the analysis button when the workspace token quota is
  // exhausted (spec §3-A4: =100% disables generation-class buttons). We poll
  // usage on mount; a QUOTA_EXCEEDED from analyze also latches it so a
  // mid-session exhaustion is reflected without a reload.
  const [quotaExhausted, setQuotaExhausted] = useState(false)

  const loadReports = useCallback(async () => {
    try {
      const data = await brandFlowRequest<{ items: StyleReport[] }>('/api/v1/consumer/style/reports')
      setReports(data.items ?? [])
    } catch {
      /* list is best-effort; the composer is the primary surface */
    }
  }, [])

  useEffect(() => {
    void loadReports()
  }, [loadReports])

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const usage = await fetchConsumerUsage()
        if (active) setQuotaExhausted(!usage.allowed)
      } catch {
        // usage is best-effort; the button stays enabled and the live 409
        // path still gates the call
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const validArticles = articles.filter(article => article.trim().length > 0)

  const analyze = useCallback(async () => {
    if (validArticles.length < 2 || analyzing) return
    setAnalyzing(true)
    setError(null)
    setProgress('正在通读你的语料…')
    const narrativeTimer = setInterval(() => {
      setProgress(previous =>
        previous === '正在通读你的语料…'
          ? '正在逐层拆解风格（语言 → 结构 → 选题 → 素材 → 认知 → 视觉）…'
          : '正在合成可复用的规则文件…',
      )
    }, 25_000)
    try {
      const report = await brandFlowRequest<StyleReport>('/api/v1/consumer/style/analyze', {
        method: 'POST',
        headers: { 'Idempotency-Key': newIdempotencyKey() },
        body: JSON.stringify({
          articles: validArticles,
          form,
          outputLanguage: outputLanguage === 'auto' ? undefined : outputLanguage,
        }),
      })
      // round-3g: digest short-circuit returns an EXISTING report — prepend
      // must dedupe by id or React renders the same key twice and the
      // whole tab section crashes (observed live: tabs never appear)
      setReports(previous => {
        if (previous.some(item => item.report_id === report.report_id)) return previous
        return [report, ...previous]
      })
      setActiveReportId(report.report_id)
      setArticles(['', ''])
      // 报告生成后折叠示例卡——避免一直挡视野
      setShowExample(false)
    } catch (analyzeError) {
      const message = analyzeError instanceof Error ? analyzeError.message : ''
      if (message.includes('QUOTA_EXCEEDED') || message.includes('额度')) {
        setQuotaExhausted(true)
      }
      setError(
        analyzeError instanceof Error
          ? analyzeError.message
          : '分析暂时不可用。提供方可能已执行请求，预估额度可能已计入；再次分析会作为一次新请求。',
      )
    } finally {
      clearInterval(narrativeTimer)
      setAnalyzing(false)
      setProgress(null)
    }
  }, [analyzing, form, outputLanguage, validArticles])

  const activeReport = reports.find(report => report.report_id === activeReportId) ?? reports[0] ?? null

  // round-3g B: archive view state — clicking a report tab opens the
  // ARCHIVE (detail) view; 补充样本 returns to the corpus composer.
  const [archiveOpen, setArchiveOpen] = useState(false)
  const openArchive = (reportId: string) => {
    setActiveReportId(reportId)
    setArchiveOpen(true)
  }
  /** BA-0001 style display number: derived from list order (oldest = 1),
   * display-layer only — the DB id stays the real key. */
  const archiveNumber = (report: StyleReport): string => {
    const position = reports.findIndex(item => item.report_id === report.report_id)
    if (position < 0) return 'BA-0001'
    const serial = Math.max(1, reports.length - position)
    return `BA-${String(serial).padStart(4, '0')}`
  }
  const chineseDate = (iso?: string): string => {
    if (!iso) return '—'
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
    if (!m) return iso.slice(0, 10)
    return `${m[1]} 年 ${Number(m[2])} 月 ${Number(m[3])} 日`
  }

  const handleCopy = useCallback(async (report: StyleReport) => {
    try {
      await copyText(reportToMarkdown(report))
      setCopyStatus('已复制规则文件（Markdown）到剪贴板。')
      setTimeout(() => setCopyStatus(null), 2400)
    } catch {
      setCopyStatus('复制失败，请改用下载 .md。')
      setTimeout(() => setCopyStatus(null), 2400)
    }
  }, [])

  const handleDownload = useCallback((report: StyleReport) => {
    const form = FORMS.find(option => option.value === report.form)?.label ?? report.form
    const stamp = report.created_at?.slice(0, 10) ?? new Date().toISOString().slice(0, 10)
    const name = `brandagent-style-${form}-${stamp}-${report.report_id.slice(0, 8)}.md`
    downloadFile(name, reportToMarkdown(report), 'text/markdown;charset=utf-8')
  }, [])

  return (
    <div className={styles.page}>
      {/* round-3f (P0-4): unified app navigation — 项目 back-link now lives
          in the nav instead of a lone corner link */}
      <ConsumerNav active="style" />
      <header className={styles.homeHeader}>
        <div>
          <h1>风格实验室</h1>
          <p className={styles.homeSubtitle}>先分析一批完整文章，把风格拆成规则；之后写作按规则来，不做单篇模仿。</p>
        </div>
        <button type="button" className="consumer-primary-button" data-testid="style-open-sample" onClick={() => setShowExample(previous => !previous)}>
          {showExample ? '收起示例' : '查看示例报告'}
        </button>
      </header>

      {/* 诉求 3 — 深化：示例报告折叠卡。首次进入时展开，报告生成后收起。 */}
      <section className={styles.styleExampleCard} aria-label="示例风格报告">
        <button
          type="button"
          className={styles.styleExampleToggle}
          aria-expanded={showExample}
          onClick={() => setShowExample(previous => !previous)}
        >
          <span className={styles.styleExampleTag}>先看示例</span>
          <span className={styles.styleExampleHint}>
            不粘语料也能看到产出长什么样——{showExample ? '点此收起' : '点此展开'}
          </span>
        </button>
        {showExample && (
          <div className={styles.styleExampleBody}>
            <p className={styles.styleExampleIntro}>
              这是一份「示例公众号作者」的风格蒸馏报告（虚拟示例，提交后会基于你真实语料生成你自己的版本）。六层各产出一段摘要 + 若干条可执行规则，整份可作为 Markdown 规则文件带走。
            </p>
            <ul className={styles.styleExampleRules}>
              {EXAMPLE_REPORT.layers.l1_language_dna.rules.slice(0, 3).map((rule, index) => (
                <li key={index}>{rule}</li>
              ))}
            </ul>
            <p className={styles.styleExampleFormLabel}>
              文章形态：{FORMS.find(option => option.value === EXAMPLE_REPORT.form)?.label} · 规则文件语言：{EXAMPLE_REPORT.language === 'zh' ? '中文规则' : 'EN rules'}
            </p>
          </div>
        )}
      </section>

      <section className={styles.state} aria-label="语料输入">
        <label className="consumer-field-label">
          参考文章（至少 2 篇同一作者的完整文章，支持最多 20 篇）
        </label>
        {articles.map((article, index) => (
          <textarea
            key={index}
            className="consumer-text-input"
            rows={Math.min(4, Math.max(2, Math.ceil(article.length / 400)))}
            placeholder={`第 ${index + 1} 篇参考文章，直接粘贴…`}
            value={article}
            onChange={event => {
              // round-3f (风格 3): the moment the user starts typing, the
              // example card folds away — it was there for the first look
              setShowExample(false)
              setArticles(previous => previous.map((item, i) => (i === index ? event.target.value : item)))
            }}
          />
        ))}
        <div className={styles.composerActions}>
          {articles.length < 20 && (
            <button type="button" className={styles.composerCancel} onClick={() => setArticles(previous => [...previous, ''])}>
              + 再加一篇
            </button>
          )}
          {articles.length > 2 && (
            <button
              type="button"
              className={styles.composerCancel}
              onClick={() => setArticles(previous => previous.slice(0, -1))}
            >
              移除最后一篇
            </button>
          )}
        </div>

        <div className={styles.styleControls}>
          <div className={styles.styleField}>
            <label className="consumer-field-label" htmlFor="style-form">
              文章形态
            </label>
            <select
              id="style-form"
              className="consumer-text-input"
              value={form}
              onChange={event => setForm(event.target.value)}
            >
              {FORMS.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.styleField}>
            <label className="consumer-field-label" htmlFor="style-language">
              规则语言
            </label>
            <select
              id="style-language"
              className="consumer-text-input"
              value={outputLanguage}
              onChange={event => setOutputLanguage(event.target.value as 'auto' | 'zh' | 'en')}
            >
              <option value="auto">跟随语料（默认）</option>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>

        <p className={styles.styleWhyHint}>
          为什么至少 2 篇？单篇模仿正是会失真的做法——你贴一篇，AI 学的是「这一篇怎么写」；贴两篇以上，AI 才有机会识别「这位作者反复用的方式」。
        </p>

        <button
          type="button"
          className="consumer-primary-button"
          disabled={analyzing || validArticles.length < 2 || quotaExhausted}
          onClick={() => void analyze()}
        >
          {analyzing ? '正在分析…' : '分析我的写作风格'}
        </button>
        {quotaExhausted && (
          <p className={styles.generateProgress}>本月额度已用完，分析功能已暂停。下周或升级后恢复。</p>
        )}
        {analyzing && progress && (
          <p role="status" data-testid="style-progress" className={styles.generateProgress}>
            {progress}
          </p>
        )}
        {validArticles.length > 0 && validArticles.length < 2 && !analyzing && (
          <p className={styles.generateProgress}>还需 {2 - validArticles.length} 篇参考文章——单篇模仿正是容易失真的做法。</p>
        )}
        {error && (
          <p role="alert" className={styles.generateProgress}>
            {error}
          </p>
        )}
      </section>

      {copyStatus && (
        <p role="status" data-testid="copy-status" className={styles.generateProgress}>
          {copyStatus}
        </p>
      )}

      {reports.length > 0 && (
        <section aria-label="我的风格档案报告">
          <h2 className={styles.sectionTitle}>我的风格档案</h2>
          <div className={styles.styleReportTabs}>
            {reports.slice(0, 8).map(report => (
              <button
                key={report.report_id}
                type="button"
                data-testid="style-report-tab"
                className={report.report_id === activeReport?.report_id ? styles.styleTabActive : styles.styleTab}
                onClick={() => openArchive(report.report_id)}
              >
                {FORMS.find(option => option.value === report.form)?.label ?? report.form} ·{' '}
                {reportDate(report.created_at)}
              </button>
            ))}
          </div>

          {activeReport && archiveOpen && (
            <StyleArchive
              report={activeReport}
              serial={archiveNumber(activeReport)}
              onClose={() => setArchiveOpen(false)}
              onCopy={() => void handleCopy(activeReport)}
              onDownload={() => handleDownload(activeReport)}
            />
          )}

          {activeReport && !archiveOpen && (
            <article className={styles.styleReport}>
              <header className={styles.styleReportHead}>
                <div>
                  <span className={styles.styleReportMeta}>
                    {FORMS.find(option => option.value === activeReport.form)?.label ?? activeReport.form} ·{' '}
                    {activeReport.language === 'zh' ? '中文规则文件' : 'EN rule file'}
                  </span>
                  <h3 className={styles.styleReportHeading}>
                    蒸馏于 {activeReport.created_at?.slice(0, 10) ?? '—'}
                  </h3>
                </div>
                <div className={styles.styleReportActions}>
                  {/* round-3f (P0-2): technical entry points (Markdown/.md)
                      collapse behind an 导出 ▾ menu; the page highlights
                      only 应用到写作. */}
                  <ExportMenu onCopy={() => void handleCopy(activeReport)} onDownload={() => handleDownload(activeReport)} />
                  <Link
                    href={`/app?apply=${activeReport.report_id}`}
                    className={styles.styleReportActionPrimary}
                    data-testid="style-apply"
                  >
                    应用到写作 →
                  </Link>
                </div>
              </header>

              {LAYER_META.map(layer => {
                const content = activeReport.layers[layer.key]
                if (!content) return null
                return (
                  <section key={layer.key} className={styles.styleLayer}>
                    <header className={styles.styleLayerHeader}>
                      <span className={styles.styleLayerGroup}>{layer.group}</span>
                      <h3>{layer.title}</h3>
                      <span className={styles.styleLayerQuestion}>· {layer.question}</span>
                    </header>
                    <p className={styles.styleLayerSummary}>{content.summary}</p>
                    {content.rules.length > 0 ? (
                      <ul className={styles.styleRules}>
                        {content.rules.map((rule, index) => (
                          <li key={index}>{rule}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className={styles.styleRulesEmpty}>此层在当前语料中无法可靠推断，未生成规则。</p>
                    )}
                  </section>
                )
              })}
              <footer className={styles.styleReportFooter}>
                这套风格可以导出带走，也可以在新项目写作时引用。
              </footer>
            </article>
          )}
        </section>
      )}
    </div>
  )
}

/** round-3f (P0-2): 导出 ▾ collapses 复制规则 / 下载规则文件 behind one
 * secondary control so technical entry points don't sit next to the main
 * action on the report header. */
function ExportMenu({ onCopy, onDownload }: { onCopy(): void; onDownload(): void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={styles.exportWrap} data-testid="export-menu">
      <button
        type="button"
        className={styles.styleReportAction}
        aria-expanded={open}
        onClick={() => setOpen(previous => !previous)}
      >
        导出 ▾
      </button>
      {open && (
        <div className={styles.exportMenu} role="menu">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onCopy()
            }}
          >
            复制规则
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              onDownload()
            }}
          >
            下载规则文件
          </button>
        </div>
      )}
    </div>
  )
}
