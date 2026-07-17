// ============================================================
// 文章历史列表页
// src/app/(dashboard)/dashboard/articles/page.tsx
// ============================================================
import Link from 'next/link'
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'
import type { Article } from '@/types'
import { ArticleActions } from './ArticleActions'

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

interface StatusBadgeProps {
  status: Article['status']
}

function StatusBadge({ status }: StatusBadgeProps) {
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

// ── 文章卡片 ──────────────────────────────────────────────────────

interface ArticleCardProps {
  article: Article
}

function ArticleCard({ article }: ArticleCardProps) {
  const displayTitle = article.title ?? '未命名草稿'
  const updatedLabel = formatRelativeTime(article.updatedAt)

  return (
    <div
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-ivory-border)',
      }}
    >
      <div className="flex items-start justify-between gap-4 px-6 py-5">
        {/* 左侧：标题 + 元信息 */}
        <div className="min-w-0 flex-1">
          <h3
            className="mb-2 truncate text-base font-semibold leading-snug"
            style={{
              fontFamily: 'var(--font-serif)',
              color: article.title ? 'var(--color-ink)' : 'var(--color-ink-faint)',
              fontStyle: article.title ? 'normal' : 'italic',
            }}
          >
            {displayTitle}
          </h3>
          <div className="flex items-center gap-3">
            <StatusBadge status={article.status} />
            {article.wordCount != null && article.wordCount > 0 && (
              <span
                className="text-[11px]"
                style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-faint)' }}
              >
                {article.wordCount.toLocaleString()} 字
              </span>
            )}
            <span
              className="text-[11px]"
              style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-faint)' }}
            >
              {updatedLabel}
            </span>
          </div>
        </div>

        {/* 右侧：操作按钮 */}
        <div className="flex shrink-0 items-center gap-2">
          <Link
            href={`/dashboard/editor?id=${article.id}`}
            className="btn-ghost text-xs"
          >
            继续编辑
          </Link>
          <ArticleActions articleId={article.id} />
        </div>
      </div>
    </div>
  )
}

// ── 空状态 ────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div
      className="p-12 text-center"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-ivory-border)',
      }}
    >
      <p
        className="mb-1 text-sm"
        style={{
          fontFamily: 'var(--font-mono)',
          color: 'var(--color-ink-faint)',
          letterSpacing: '0.06em',
        }}
      >
        还没有任何文章
      </p>
      <p
        className="mb-6 text-xs"
        style={{ color: 'var(--color-ink-faint)' }}
      >
        点击右上角按钮，开始你的第一篇创作
      </p>
      <Link href="/dashboard/editor" className="btn-primary">
        + 新建文章
      </Link>
    </div>
  )
}

// ── Server Component 主体 ─────────────────────────────────────────

export default async function ArticlesPage() {
  const userId = 'anonymous'

  const supabase = createSupabaseAdminClient()
  const { data, error } = await supabase
    .from('articles')
    .select('*')
    .eq('user_id', userId)
    .order('updated_at', { ascending: false })

  if (error) {
    console.error('[ArticlesPage] Supabase error:', error)
  }

  const articles: Article[] = (data ?? []).map(rowToArticle)

  return (
    <div>
      {/* ── 数据加载失败提示条 ── */}
      {error !== null && (
        <div
          className="mb-6 flex items-center gap-3 px-5 py-4"
          style={{
            border: '1px solid rgba(220, 38, 38, 0.35)',
            backgroundColor: 'rgba(220, 38, 38, 0.04)',
          }}
          role="alert"
        >
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6875rem',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: 'rgb(220, 38, 38)',
              flexShrink: 0,
            }}
          >
            Error
          </span>
          <p
            className="text-sm"
            style={{ color: 'rgb(185, 28, 28)' }}
          >
            数据加载失败，请刷新页面重试
          </p>
        </div>
      )}
      {/* ── 页面头部 ── */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <p
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6875rem',
              textTransform: 'uppercase',
              letterSpacing: '0.16em',
              color: 'var(--color-gold)',
              marginBottom: '0.375rem',
            }}
          >
            My Articles
          </p>
          <h1
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 'clamp(1.5rem, 2.5vw, 1.875rem)',
              fontWeight: 700,
              color: 'var(--color-ink)',
              letterSpacing: '-0.01em',
            }}
          >
            我的文章
          </h1>
        </div>
        <Link href="/dashboard/editor" className="btn-primary">
          + 新建文章
        </Link>
      </div>

      <div className="rule-divider-gold mb-8" />

      {/* ── 文章列表 ── */}
      {articles.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-3">
          {articles.map(article => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}
    </div>
  )
}
