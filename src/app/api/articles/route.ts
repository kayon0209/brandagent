/**
 * 文章列表 & 创建 API Route
 * GET  /api/articles  — 获取当前用户的文章列表
 * POST /api/articles  — 创建新文章（草稿）
 */
import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'
import type { Article } from '@/types'

// ── Zod Schema ────────────────────────────────────────────────────

const OutlineSectionSchema = z.object({
  id: z.string(),
  title: z.string(),
  points: z.array(z.string()),
  content: z.string().optional(),
})

const ArticleBodySchema = z.object({
  title: z.string().max(200).optional(),
  outline: z.array(OutlineSectionSchema).optional(),
  content: z.string().optional(),
  status: z.enum(['draft', 'completed']).optional(),
  wordCount: z.number().int().min(0).optional(),
})

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

// ── GET /api/articles ─────────────────────────────────────────────

export async function GET() {
  const userId = 'anonymous'

  try {
    const supabase = createSupabaseAdminClient()
    const { data, error } = await supabase
      .from('articles')
      .select('*')
      .eq('user_id', userId)
      .order('updated_at', { ascending: false })

    if (error) {
      console.error('[GET /api/articles] Supabase error:', error)
      return NextResponse.json(
        { success: false, error: { code: 'DB_ERROR', message: '查询失败，请稍后重试' } },
        { status: 500 }
      )
    }

    const articles: Article[] = (data ?? []).map(rowToArticle)
    return NextResponse.json({ success: true, data: { articles } })
  } catch (err: unknown) {
    console.error('[GET /api/articles] Unexpected error:', err)
    return NextResponse.json(
      { success: false, error: { code: 'DB_ERROR', message: '服务异常，请稍后重试' } },
      { status: 500 }
    )
  }
}

// ── POST /api/articles ────────────────────────────────────────────

export async function POST(req: NextRequest) {
  const userId = 'anonymous'

  const parsed = ArticleBodySchema.safeParse(await req.json().catch(() => ({})))
  if (!parsed.success) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: 'VALIDATION_ERROR',
          message: parsed.error.issues[0]?.message ?? '入参校验失败',
        },
      },
      { status: 400 }
    )
  }

  const { title, outline, content, status, wordCount } = parsed.data

  try {
    const supabase = createSupabaseAdminClient()
    const { data, error } = await supabase
      .from('articles')
      .insert({
        user_id: userId,
        title: title ?? null,
        outline: outline ?? [],
        content: content ?? null,
        status: status ?? 'draft',
        word_count: wordCount ?? null,
      })
      .select('*')
      .single()

    if (error) {
      console.error('[POST /api/articles] Supabase error:', error)
      return NextResponse.json(
        { success: false, error: { code: 'DB_ERROR', message: '创建失败，请稍后重试' } },
        { status: 500 }
      )
    }

    const article = rowToArticle(data)
    return NextResponse.json({ success: true, data: { article } }, { status: 201 })
  } catch (err: unknown) {
    console.error('[POST /api/articles] Unexpected error:', err)
    return NextResponse.json(
      { success: false, error: { code: 'DB_ERROR', message: '服务异常，请稍后重试' } },
      { status: 500 }
    )
  }
}
