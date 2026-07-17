/**
 * POST /api/analytics/similarity
 * 语义相似度数据采集埋点（PRD 附录 C）
 *
 * V1.0 简化实现：仅记录 ai_draft_hash，不做向量计算（需要独立向量服务）
 * 向量相似度计算留给离线批处理任务（V1.5）
 *
 * Body: { articleId: string, aiDraftHash: string, userFinalText: string }
 */
import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'

const RequestSchema = z.object({
  articleId: z.string().uuid('无效的文章 ID'),
  aiDraftHash: z.string().min(1, '缺少 AI 初稿哈希'),
  /** 用户最终文本（用于离线向量计算）— 当前仅记录长度不存全文 */
  userFinalTextLength: z.number().int().min(0),
})

export async function POST(req: NextRequest) {
  const userId = 'anonymous'

  const parsed = RequestSchema.safeParse(await req.json().catch(() => ({})))
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

  const { articleId, aiDraftHash, userFinalTextLength } = parsed.data

  // 非阻塞写入分析日志（失败不阻断用户）
  const admin = createSupabaseAdminClient()
  admin
    .from('article_analytics')
    .upsert(
      {
        article_id: articleId,
        user_id: userId,
        ai_draft_hash: aiDraftHash,
        user_final_text_length: userFinalTextLength,
        exported_at: new Date().toISOString(),
      },
      { onConflict: 'article_id' }
    )
    .then(({ error }) => {
      if (error) {
        console.warn('[analytics/similarity] insert failed:', error.message)
      }
    })

  return NextResponse.json({ success: true, data: null })
}
