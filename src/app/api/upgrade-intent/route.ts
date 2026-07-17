// ============================================================
// 付费意向收集接口
// POST /api/upgrade-intent
// 在正式接入支付前，记录想升级的用户信息
// ============================================================
import { NextResponse } from 'next/server'
import { z } from 'zod'
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'

const bodySchema = z.object({
  plan:   z.enum(['pro', 'team']),
  email:  z.string().email('请填写有效邮箱'),
  wechat: z.string().max(64).optional().default(''),
  note:   z.string().max(500).optional().default(''),
})

export async function POST(req: Request) {
  // 已移除 Clerk 认证，使用匿名用户
  const userId = 'anonymous'

  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json(
      { success: false, error: { code: 'VALIDATION_ERROR', message: '请求体格式错误' } },
      { status: 400 },
    )
  }

  const parsed = bodySchema.safeParse(body)
  if (!parsed.success) {
    return NextResponse.json(
      { success: false, error: { code: 'VALIDATION_ERROR', message: parsed.error.issues[0]?.message ?? '参数错误' } },
      { status: 400 },
    )
  }

  const { plan, email, wechat, note } = parsed.data

  const admin = createSupabaseAdminClient()

  const { error } = await admin.from('upgrade_intents').insert({
    clerk_user_id: userId ?? null,   // 未登录用户也允许提交
    plan,
    email,
    wechat: wechat || null,
    note: note || null,
  })

  if (error) {
    console.error('[upgrade-intent] insert failed:', error.message)
    return NextResponse.json(
      { success: false, error: { code: 'DB_ERROR', message: '提交失败，请稍后再试' } },
      { status: 500 },
    )
  }

  return NextResponse.json({ success: true })
}
