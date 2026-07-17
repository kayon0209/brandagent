import Link from 'next/link'
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'
import type { Article } from '@/types'

// ── 时间格式化（不引入外部库）────────────────────────────────────

function formatRelativeTime(date: Date): string {
  const now = Date.now()
  const diffMs = now - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffDay >= 1) return `${diffDay} 天前`
  if (diffHour >= 1) return `${diffHour} 小时前`
  if (diffMin >= 1) return `${diffMin} 分钟前`
  return '刚刚'
}

// ── DB 行 → Article 实体 ──────────────────────────────────────────

function rowToArticle(row: Record<string, any>): Article {
  return {
    id: row.id as string,
    userId: row.user_id as string,
    title: (row.title as string | null) ?? null,
    outline: (row.outline as Article['outline']) ?? [],
    content: (row.content as string | null) ?? null,
    status: row.status as Article['status'],
    wordCount: row.word_count as number | undefined,
    createdAt: new Date(row.created_at as string),
    updatedAt: new Date(row.updated_at as string),
  }
}

// ── 状态徽章 ──────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Article['status'] }) {
  if (status === 'completed') {
    return (
      <span
        className="inline-block px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest"
        style={{
          backgroundColor: 'rgba(34, 197, 94, 0.1)',
          color: 'rgb(22, 163, 74)',
          border: '1px solid rgba(34, 197, 94, 0.25)',
        }}
      >
        已完成
      </span>
    )
  }
  return (
    <span
      className="inline-block px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest"
      style={{
        backgroundColor: 'var(--color-surface)',
        color: 'var(--color-ink-muted)',
        border: '1px solid var(--color-ivory-border)',
      }}
    >
      草稿
    </span>
  )
}

// ── 最近文章卡片 ──────────────────────────────────────────────────

function RecentArticleCard({ article }: { article: Article }) {
  const displayTitle = article.title
  const updatedLabel = formatRelativeTime(article.updatedAt)

  return (
    <div
      className="flex items-center justify-between gap-4 px-5 py-4"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-ivory-border)',
      }}
    >
      {/* 左侧：标题 + 元信息 */}
      <div className="min-w-0 flex-1">
        <p
          className="mb-1 truncate text-sm font-semibold leading-snug"
          style={{
            fontFamily: 'var(--font-serif)',
            color: displayTitle ? 'var(--color-ink)' : 'var(--color-ink-faint)',
            fontStyle: displayTitle ? 'normal' : 'italic',
          }}
        >
          {displayTitle ?? '未命名草稿'}
        </p>
        <div className="flex items-center gap-3">
          <StatusBadge status={article.status} />
          <span
            className="text-[11px]"
            style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-faint)' }}
          >
            {updatedLabel}
          </span>
        </div>
      </div>

      {/* 右侧：继续编辑 */}
      <Link
        href={`/dashboard/editor?id=${article.id}`}
        className="btn-ghost shrink-0 text-xs"
      >
        继续编辑
      </Link>
    </div>
  )
}

// ── Server Component 主体 ─────────────────────────────────────────

export default async function DashboardPage() {
  const userId = 'anonymous'
  const firstName = '创作者'

  // 查询最近 3 篇文章
  const supabase = createSupabaseAdminClient()
  const { data, error } = await supabase
    .from('articles')
    .select('*')
    .eq('user_id', userId)
    .order('updated_at', { ascending: false })
    .limit(3)

  if (error) {
    console.error('[DashboardPage] Supabase error:', error)
  }

  const recentArticles: Article[] = (data ?? []).map(rowToArticle)

  return (
    <div>

      {/* ── Greeting ── */}
      <div className="mb-10">
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.6875rem',
            textTransform: 'uppercase',
            letterSpacing: '0.16em',
            color: 'var(--color-gold)',
            marginBottom: '0.5rem',
          }}
        >
          Welcome back
        </p>
        <h1
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 'clamp(1.75rem, 3vw, 2.25rem)',
            fontWeight: 700,
            color: 'var(--color-ink)',
            letterSpacing: '-0.01em',
          }}
        >
          你好，<span style={{ fontStyle: 'italic' }}>{firstName}</span>
        </h1>
        <p
          className="mt-2"
          style={{ color: 'var(--color-ink-muted)', fontWeight: 300, fontSize: '0.9375rem' }}
        >
          准备好开始今天的写作了吗？
        </p>
      </div>

      {/* ── Quick Start Card ── */}
      <div
        className="mb-10 p-10 text-center"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-ivory-border)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* Decorative large text */}
        <div
          className="pointer-events-none absolute -right-4 -top-6 select-none opacity-[0.04]"
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: '10rem',
            fontWeight: 900,
            color: 'var(--color-ink)',
            lineHeight: 1,
          }}
        >
          写
        </div>

        <div className="relative">
          <div
            className="mb-2 text-[11px] uppercase tracking-widest"
            style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-gold)' }}
          >
            快速开始
          </div>
          <h2
            className="mb-3"
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: '1.5rem',
              fontWeight: 700,
              color: 'var(--color-ink)',
            }}
          >
            开始新文章
          </h2>
          <p
            className="mb-8 max-w-sm mx-auto text-sm"
            style={{ color: 'var(--color-ink-muted)', lineHeight: 1.7, fontWeight: 300 }}
          >
            输入一个关键词，AI 帮你生成标题 → 大纲 → 全文
          </p>
          <Link href="/dashboard/editor" className="btn-primary">
            + 新建文章
          </Link>
        </div>
      </div>

      {/* ── Recent Articles ── */}
      <div>
        <div className="flex items-center justify-between mb-6">
          <h2
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: '1.25rem',
              fontWeight: 600,
              color: 'var(--color-ink)',
            }}
          >
            最近文章
          </h2>
          <div className="flex items-center gap-4">
            <div className="rule-divider-gold" />
            <Link
              href="/dashboard/articles"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.6875rem',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
                color: 'var(--color-ink-faint)',
              }}
              className="nav-link-dashboard"
            >
              查看全部 →
            </Link>
          </div>
        </div>

        {recentArticles.length === 0 ? (
          <div
            className="p-12 text-center"
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-ivory-border)',
            }}
          >
            <p
              className="text-sm"
              style={{ color: 'var(--color-ink-faint)', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em' }}
            >
              还没有文章，点击上方按钮开始创作吧
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {recentArticles.map(article => (
              <RecentArticleCard key={article.id} article={article} />
            ))}
          </div>
        )}
      </div>

    </div>
  )
}
