// ============================================================
// Token 配额查询接口
// src/app/api/quota/route.ts
// ============================================================
import { NextResponse } from 'next/server'
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'

export async function GET() {
  const userId = 'anonymous'

  const admin = createSupabaseAdminClient()
  const { data: user, error } = await admin
    .from('users')
    .select('plan_tier, token_used, token_quota, quota_reset_at')
    .eq('clerk_id', userId)
    .single()

  if (error || !user) {
    // 用户记录尚不存在，返回免费默认值
    return NextResponse.json({
      success: true,
      data: { used: 0, total: 30000, plan: 'Free' },
    })
  }

  // 检查是否需要重置配额（每月 1 日）
  const resetAtRaw = user.quota_reset_at
  let used = user.token_used

  if (resetAtRaw) {
    const resetAt = new Date(resetAtRaw)
    const now = new Date()

    // Guard against invalid dates from DB
    if (!isNaN(resetAt.getTime()) && now >= resetAt) {
      used = 0
      const nextReset = new Date(now.getFullYear(), now.getMonth() + 1, 1)
      // 异步重置，记录错误但不阻断响应
      admin
        .from('users')
        .update({ token_used: 0, quota_reset_at: nextReset.toISOString() })
        .eq('clerk_id', userId)
        .then(({ error: resetErr }) => {
          if (resetErr) console.error('[quota] monthly reset failed:', resetErr.message)
        })
    }
  }

  const planLabel =
    user.plan_tier === 'pro' ? 'Pro' : user.plan_tier === 'team' ? 'Team' : 'Free'

  const total = user.plan_tier === 'free' ? user.token_quota : null // null 表示无限制

  return NextResponse.json({
    success: true,
    data: { used, total, plan: planLabel },
  })
}
