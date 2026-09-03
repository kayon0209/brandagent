/**
 * Client-safe consumer usage reader (R1: quota visibility).
 *
 * Split out of lib/quota.ts because that module statically imports the
 * Supabase admin client (server-only, next/headers) — importing it from a
 * client component drags next/headers into the pages-directory compile
 * and fails the production build. THIS module touches only the BFF.
 */

export interface ConsumerUsageSummary {
  allowed: boolean
  remaining: number
  used: number
  quota: number
}

export async function fetchConsumerUsage(): Promise<ConsumerUsageSummary> {
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
