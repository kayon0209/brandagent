/**
 * Navigation helpers for the consumer materials page.
 *
 * P1 UX fix: /app/materials must never be a navigation island — the
 * user arrives from a writing project (to import) and needs an explicit
 * way back. The write-page id travels as ?from=<projectId> so the back
 * link returns to THAT project; without context it returns to /app.
 */

export const MATERIALS_FROM_PARAM = 'from'

export function buildMaterialsHref(fromProjectId?: string | null): string {
  if (!fromProjectId) return '/app/materials'
  return `/app/materials?${MATERIALS_FROM_PARAM}=${encodeURIComponent(fromProjectId)}`
}

export function buildMaterialsBackLink(fromProjectId?: string | null): string {
  if (!fromProjectId) return '/app'
  return `/app/write/${fromProjectId}`
}
