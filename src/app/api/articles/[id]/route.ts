/**
 * 单篇文章 CRUD API Route
 * GET    /api/articles/[id]  — 获取单篇文章
 * PATCH  /api/articles/[id]  — 更新文章（保存草稿）
 * DELETE /api/articles/[id]  — 删除文章
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

const ArticlePatchSchema = z.object({
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

// ── 所有权验证 ────────────────────────────────────────────────────

interface RouteParams {
  params: Promise<{ id: string }>
}

// ── GET /api/articles/[id] ────────────────────────────────────────

export async function GET(_req: NextRequest, { params }: RouteParams) {
  const userId = 'anonymous'

  const { id } = await params

  try {
    const supabase = createSupabaseAdminClient()
    const { data, error } = await supabase
      .from('articles')
      .select('*')
      .eq('id', id)
      .single()

    if (error || !data) {
      return NextResponse.json(
        { success: false, error: { code: 'NOT_FOUND', message: '文章不存在' } },
        { status: 404 }
      )
    }

    if (data.user_id !== userId) {
      return NextResponse.json(
        { success: false, error: { code: 'FORBIDDEN', message: '无权访问此文章' } },
        { status: 403 }
      )
    }

    return NextResponse.json({ success: true, data: { article: rowToArticle(data) } })
  } catch (err: unknown) {
    console.error('[GET /api/articles/[id]] Unexpected error:', err)
    return NextResponse.json(
      { success: false, error: { code: 'DB_ERROR', message: '服务异常，请稍后重试' } },
      { status: 500 }
    )
  }
}

// ── PATCH /api/articles/[id] ──────────────────────────────────────

export async function PATCH(req: NextRequest, { params }: RouteParams) {
  const userId = 'anonymous'

  const { id } = await params

  const parsed = ArticlePatchSchema.safeParse(await req.json().catch(() => ({})))
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

  try {
    const supabase = createSupabaseAdminClient()

    // 验证所有权
    const { data: existing, error: fetchError } = await supabase
      .from('articles')
      .select('user_id')
      .eq('id', id)
      .single()

    if (fetchError || !existing) {
      return NextResponse.json(
        { success: false, error: { code: 'NOT_FOUND', message: '文章不存在' } },
        { status: 404 }
      )
    }

    if (existing.user_id !== userId) {
      return NextResponse.json(
        { success: false, error: { code: 'FORBIDDEN', message: '无权修改此文章' } },
        { status: 403 }
      )
    }

    const { title, outline, content, status, wordCount } = parsed.data

    // 只更新传入的字段
    const updatePayload: Record<string, unknown> = { updated_at: new Date().toISOString() }
    if (title !== undefined) updatePayload.title = title
    if (outline !== undefined) updatePayload.outline = outline
    if (content !== undefined) updatePayload.content = content
    if (status !== undefined) updatePayload.status = status
    if (wordCount !== undefined) updatePayload.word_count = wordCount

    const { data, error } = await supabase
      .from('articles')
      .update(updatePayload)
      .eq('id', id)
      .select('*')
      .single()

    if (error || !data) {
      console.error('[PATCH /api/articles/[id]] Supabase error:', error)
      return NextResponse.json(
        { success: false, error: { code: 'DB_ERROR', message: '更新失败，请稍后重试' } },
        { status: 500 }
      )
    }

    return NextResponse.json({ success: true, data: { article: rowToArticle(data) } })
  } catch (err: unknown) {
    console.error('[PATCH /api/articles/[id]] Unexpected error:', err)
    return NextResponse.json(
      { success: false, error: { code: 'DB_ERROR', message: '服务异常，请稍后重试' } },
      { status: 500 }
    )
  }
}

// ── DELETE /api/articles/[id] ─────────────────────────────────────

export async function DELETE(_req: NextRequest, { params }: RouteParams) {
  const userId = 'anonymous'

  const { id } = await params

  try {
    const supabase = createSupabaseAdminClient()

    // 验证所有权
    const { data: existing, error: fetchError } = await supabase
      .from('articles')
      .select('user_id')
      .eq('id', id)
      .single()

    if (fetchError || !existing) {
      return NextResponse.json(
        { success: false, error: { code: 'NOT_FOUND', message: '文章不存在' } },
        { status: 404 }
      )
    }

    if (existing.user_id !== userId) {
      return NextResponse.json(
        { success: false, error: { code: 'FORBIDDEN', message: '无权删除此文章' } },
        { status: 403 }
      )
    }

    const { error } = await supabase.from('articles').delete().eq('id', id)

    if (error) {
      console.error('[DELETE /api/articles/[id]] Supabase error:', error)
      return NextResponse.json(
        { success: false, error: { code: 'DB_ERROR', message: '删除失败，请稍后重试' } },
        { status: 500 }
      )
    }

    return NextResponse.json({ success: true, data: null })
  } catch (err: unknown) {
    console.error('[DELETE /api/articles/[id]] Unexpected error:', err)
    return NextResponse.json(
      { success: false, error: { code: 'DB_ERROR', message: '服务异常，请稍后重试' } },
      { status: 500 }
    )
  }
}
