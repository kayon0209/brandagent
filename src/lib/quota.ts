/**
 * DEPRECATED — consumer quota authority moved to the FastAPI usage ledger
 * (services/agent-api/src/agent_api/application/usage.py) in upgrade plan
 * task 13. This module is kept for one release cycle so existing B-end
 * callers keep working; it must not be double-written: the new C-end
 * surfaces read quota through the BFF (/api/brandagent passthrough) and
 * the agent-api usage_ledger table.
 *
 * Do not add new call sites.
 * @deprecated since consumer upgrade task 13 — use the BFF consumer usage endpoint.
 */
import { createSupabaseAdminClient } from '@/lib/api/supabase-server'

export interface QuotaCheckResult {
  allowed: boolean
  remaining: number
  used: number
  quota: number
}

/**
 * Read the consumer usage summary through the BFF (agent-api usage ledger).
 * The ledger is the single authority for C-end quota.
 */
export async function fetchConsumerUsage(): Promise<QuotaCheckResult> {
  const { brandFlowRequest } = await import('@/lib/api/brandflow')
  const summary = await brandFlowRequest<{ used: number; quota: number }>(
    '/api/v1/consumer/usage',
  )
  return {
    allowed: summary.used < summary.quota,
    remaining: summary.quota - summary.used,
    used: summary.used,
    quota: summary.quota,
  }
}

/**
 * @deprecated Legacy Supabase-backed quota check. Kept for one release
 * cycle for existing B-end callers; new code must use fetchConsumerUsage.
 */
export async function checkQuota(
  clerkUserId: string,
  estimatedTokens: number
): Promise<QuotaCheckResult> {
  const admin = createSupabaseAdminClient()

  // 查询用户配额，同时重置已过期配额
  const { data: user, error } = await admin
    .from('users')
    .select('plan_tier, token_used, token_quota, quota_reset_at')
    .eq('clerk_id', clerkUserId)
    .single()

  if (error || !user) {
    // 用户记录不存在时，默认允许（首次调用会在 upsert 时创建记录）
    return { allowed: true, remaining: 30000, used: 0, quota: 30000 }
  }

  // Pro/Team 用户无配额限制
  if (user.plan_tier !== 'free') {
    return { allowed: true, remaining: Infinity, used: user.token_used, quota: Infinity }
  }

  // 检查是否需要重置配额（每月 1 日）
  const resetAt = new Date(user.quota_reset_at)
  const now = new Date()
  if (now >= resetAt) {
    const nextReset = new Date(now.getFullYear(), now.getMonth() + 1, 1)
    await admin
      .from('users')
      .update({ token_used: 0, quota_reset_at: nextReset.toISOString() })
      .eq('clerk_id', clerkUserId)

    return {
      allowed: estimatedTokens <= user.token_quota,
      remaining: user.token_quota - estimatedTokens,
      used: 0,
      quota: user.token_quota,
    }
  }

  const remaining = user.token_quota - user.token_used
  return {
    allowed: remaining >= estimatedTokens,
    remaining,
    used: user.token_used,
    quota: user.token_quota,
  }
}

/**
 * 记录实际消耗的 tokens（生成完成后调用）
 */
export async function recordTokenUsage(
  clerkUserId: string,
  operation: string,
  inputTokens: number,
  outputTokens: number,
  articleId?: string
): Promise<void> {
  const admin = createSupabaseAdminClient()
  const total = inputTokens + outputTokens

  // 并行执行：写日志 + 更新用量计数
  await Promise.all([
    admin.from('usage_logs').insert({
      user_id: clerkUserId,
      article_id: articleId ?? null,
      operation,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      model: 'glm-4.5-air',
    }),
    admin.rpc('increment_token_used', {
      p_clerk_id: clerkUserId,
      p_tokens: total,
    }),
  ])
}
