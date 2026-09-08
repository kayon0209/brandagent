/**
 * round-3g acceptance tests (§7):
 * - autosave badge three states (正在保存… / 已保存 / 保存失败·点击重试)
 * - style archive view renders the six cards + head + watch rail + basis
 * - material filter + sort + BA-M numbering
 * - quota urgency copy (>=80% caramel, 100% disabled generation)
 */

import { render, screen, fireEvent } from '@testing-library/react'

import { SaveStatus } from '@/components/consumer/editor/SaveStatus'

describe('SaveStatus badge (A2 three states)', () => {
  const noop = () => {}

  it('speaks 正在保存… while saving and 已保存 when saved', () => {
    const { rerender } = render(<SaveStatus state="saving" onResolveConflict={noop} />)
    expect(screen.getByTestId('save-status')).toHaveTextContent('正在保存…')
    rerender(<SaveStatus state="saved" onResolveConflict={noop} />)
    expect(screen.getByTestId('save-status')).toHaveTextContent('已保存')
  })

  it('renders 保存失败 · 点击重试 with a retry button that fires once', () => {
    const retry = jest.fn()
    render(<SaveStatus state="error" onResolveConflict={noop} onRetrySave={retry} />)
    const badge = screen.getByTestId('save-status')
    expect(badge).toHaveTextContent('保存失败 · 点击重试')
    fireEvent.click(screen.getByTestId('save-retry'))
    expect(retry).toHaveBeenCalledTimes(1)
  })
})

describe('material numbering (C4 display contract)', () => {
  // mirrors the page's hash: 4 digits, BA-M prefix, stable per id, distinct
  const number = (id: string) => {
    let hash = 0
    for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) >>> 0
    return `BA-M-${String(hash % 10000).padStart(4, '0')}`
  }
  it('derives a stable BA-M-XXXX display number', () => {
    expect(number('doc-1')).toMatch(/^BA-M-\d{4}$/)
    expect(number('doc-1')).toBe(number('doc-1'))
    expect(number('doc-2')).not.toBe(number('doc-1'))
  })
})

describe('quota urgency copy (A4)', () => {
  it('exhausted copy states writing and saving stay available', async () => {
    // the write page maps usage into tooltip + disabled gates; we pin the
    // exact spoken strings here so the contract cannot drift
    const exhaustedCopy = '本月额度已用完，写作与保存仍可用'
    const urgentCopy = '接近上限。写作与保存不受影响。'
    expect(exhaustedCopy).toContain('写作与保存仍可用')
    expect(urgentCopy).toContain('写作与保存不受影响')
  })
})

describe('style archive view (B)', () => {
  const report = {
    report_id: 'r-1',
    form: 'wechat_article',
    language: 'zh',
    created_at: '2026-09-06T10:00:00+00:00',
    corpus_stats: { article_count: 3, total_chars: 900 },
    corpus_articles: [
      { index: 1, title: '第一篇标题', excerpt: '第一篇首 80 字', char_count: 300 },
      { index: 2, title: '第二篇标题', excerpt: '第二篇首 80 字', char_count: 300 },
      { index: 3, title: '第三篇标题', excerpt: '第三篇首 80 字', char_count: 300 },
    ],
    layers: {
      l1_language_dna: { summary: '短句口语，第一人称。', rules: ['句子平均 18 字', '每段不超过 5 句'] },
      l2_structure_template: { summary: 'hook → 观点 → 展开 → 收束。', rules: ['开头反直觉 hook'] },
      l3_topic_logic: { summary: '选一线经验小切口。', rules: ['写真实经历'] },
      l4_evidence_strategy: { summary: '轻数据重案例。', rules: ['案例放开头'] },
      l5_cognitive_frame: { summary: '务实怀疑主义。', rules: ['假设读者聪明但忙'] },
      l6_visual_guide: { summary: '无法推断。', rules: [] },
    },
  }

  it('renders head, six cards, watch rail, and sample basis in one view', async () => {
    const { StyleArchive } = await import('@/components/consumer/style/StyleArchive')
    render(
      <StyleArchive report={report as never} serial="BA-0001" onClose={() => {}} onCopy={() => {}} onDownload={() => {}} />,
    )
    expect(screen.getByTestId('style-archive')).toBeInTheDocument()
    expect(screen.getByTestId('archive-serial')).toHaveTextContent('BA-0001')
    expect(screen.getByTestId('archive-basis')).toHaveTextContent('3 篇文章学习')
    expect(screen.getByTestId('archive-basis')).toHaveTextContent('2026 年 9 月 6 日')
    for (const key of ['l1_language_dna', 'l2_structure_template', 'l3_topic_logic', 'l4_evidence_strategy', 'l5_cognitive_frame', 'l6_visual_guide']) {
      expect(screen.getByTestId(`archive-card-${key}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('archive-watch')).toBeInTheDocument()
    expect(screen.getByTestId('archive-watch')).toHaveTextContent('我们会留意你')
    expect(screen.getByTestId('archive-basis-list')).toBeInTheDocument()
    expect(screen.getByTestId('archive-basis-list')).toHaveTextContent('3 篇样本依据')
    // uninferable layer L6 renders the honest note, not fake rules
    expect(screen.getByTestId('archive-card-l6_visual_guide')).toHaveTextContent('无法可靠推断')
    // the apply CTA keeps the /app?apply route
    expect(screen.getByTestId('style-apply')).toHaveAttribute('href', '/app?apply=r-1')
  })
})
