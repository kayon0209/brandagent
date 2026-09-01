'use client'

/**
 * Single source for client idempotency keys (P1-2/P1-9).
 *
 * One user ACTION mints exactly one key; the same action's automatic
 * retries must REUSE it so the server ledger can return the first
 * outcome instead of double-calling the model. Callers keep the key for
 * the action's lifetime (see usePlatformVariants / the write page).
 */

export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}
