'use client'

/** Derive the real article/note/script title from the generated content. */

export function deriveTitle(content: string, fallback: string): string {
  const firstLine = content.split('\n').map(line => line.trim()).find(Boolean)
  if (!firstLine) return fallback
  // strip a leading markdown-ish heading marker and truncation helpers
  const title = firstLine.replace(/^#+\s*/, '').replace(/^[：:]\s*/, '')
  return title.slice(0, 40) || fallback
}
