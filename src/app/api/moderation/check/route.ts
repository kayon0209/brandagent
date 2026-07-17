/**
 * POST /api/moderation/check
 *
 * 内容合规检查端点（Level 1 本地过滤）
 *
 * 请求体：{ text: string }  （最长 500 字）
 * 响应：
 *   成功 → { success: true, data: ModerationResult }
 *   失败 → { success: false, error: { code: string, message: string } }
 *
 * src/app/api/moderation/check/route.ts
 */

import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'

import { createSupabaseAdminClient } from '@/lib/api/supabase-server'
import { checkLocalFilter, hashText, ModerationResult } from '@/lib/moderation/moderator'

// ─── 请求体 Schema ────────────────────────────────────────────────────────────

const CheckBodySchema = z.object({
  text: z
    .string()
    .min(1, '文本不能为空')
    .max(500, '文本最长 500 字'),
})

// ─── 统一响应构造 ─────────────────────────────────────────────────────────────

function ok(data: ModerationResult) {
  return NextResponse.json({ success: true, data })
}

function fail(code: string, message: string, status = 400) {
  return NextResponse.json({ success: false, error: { code, message } }, { status })
}

// ─── Handler ─────────────────────────────────────────────────────────────────

export async function POST(req: NextRequest) {
  // 1. 认证校验（已移除 Clerk，使用匿名用户）
  const userId = 'anonymous'

  // 2. 解析并校验请求体
  let body: unknown
  try {
    body = await req.json()
  } catch {
    return fail('VALIDATION_ERROR', '请求体格式错误，需要 JSON')
  }

  const parsed = CheckBodySchema.safeParse(body)
  if (!parsed.success) {
    const message = parsed.error.issues[0]?.message ?? '参数校验失败'
    return fail('VALIDATION_ERROR', message)
  }

  const { text } = parsed.data

  // 3. Level 1：本地关键词过滤（同步）
  const result = checkLocalFilter(text)

  // 4. 命中敏感词 → 写日志并返回拦截结果
  if (!result.allowed) {
    try {
      const supabase = createSupabaseAdminClient()
      await supabase.from('moderation_logs').insert({
        user_id: userId,
        input_hash: hashText(text),
        trigger_level: result.triggeredLevel ?? 'local_filter',
        rule_id: result.ruleId ?? 'unknown',
      })
    } catch (err) {
      // 日志写入失败不阻断响应，仅打印服务端错误
      console.error('[moderation] Failed to write moderation_logs:', err)
    }

    return ok(result)
  }

  // 5. 未命中 → 直接放行
  return ok({ allowed: true })
}
