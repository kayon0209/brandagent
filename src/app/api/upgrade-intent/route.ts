// ============================================================
// 付费意向收集接口
// POST /api/upgrade-intent
// 在正式接入支付前，记录想升级的用户信息
// ============================================================
import { NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { z } from 'zod'
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'

const bodySchema = z.object({
  plan:   z.enum(['pro', 'team']),
  email:  z.string().email('请填写有效邮箱'),
  wechat:  z.string().max(64).optional().default(''),
  note:   z.string().max(500).optional().default(''),
})

// S2: in-process rate limit — same email may submit once per day. The
// upgrade-intent form used to accept unlimited anonymous writes, which
// invited scripted spam and stored contact data without an owner.
const DAY_MS = 24 * 60 * 60 * 1000
const recentSubmissions = new Map<string, number>()

function rateLimited(key: string): boolean {
  const now = Date.now()
  const last = recentSubmissions.get(key)
  if (last && now - last < DAY_MS) return true
  recentSubmissions.set(key, now)
  // opportunistic cleanup so the map cannot grow unbounded
  if (recentSubmissions.size > 1000) {
    for (const [k, t] of recentSubmissions) {
      if (now - t > DAY_MS) recentSubmissions.delete(k)
    }
  }
  return false
}

export async function POST(req: Request) {
  // S2: an upgrade intent carries the user's contact details — it must
  // have an owner. Anonymous visitors are asked to sign in first.
  const { userId } = await auth()
  if (!userId) {
    return NextResponse.json(
      { success: false, error: { code: 'AUTH_REQUIRED', message: '登录后才能提交升级意向，这样我们也能直接在你的账户里为你开通。' } },
      { status: 401 },
    )
  }

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

  if (rateLimited(email) || rateLimited(userId)) {
    return NextResponse.json(
      { success: false, error: { code: 'RATE_LIMITED', message: '今天已经提交过了，我们会尽快通过邮箱联系你。' } },
      { status: 429 },
    )
  }

  const admin = createSupabaseAdminClient()

  const { error } = await admin.from('upgrade_intents').insert({
    clerk_user_id: userId,
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
