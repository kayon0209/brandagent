'use client'

/**
 * Consumer route-group error boundary: a crash in any /app* subtree
 * shows spoken recovery guidance (never a white screen or raw stack),
 * with a retry that reloads the route.
 */

import { useEffect } from 'react'

export default function ConsumerError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // server-side observability hook point; the message itself never
    // reaches the UI (no raw provider/stack text for C-end users)
    console.error('[consumer-app-error]', error.digest ?? error.message)
  }, [error])

  return (
    <div className="consumer-app-root" style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <section style={{ maxWidth: 420, padding: 24, textAlign: 'center' }} role="alert">
        <h1 style={{ fontSize: 20, margin: '0 0 8px' }}>工作台出了点问题</h1>
        <p style={{ color: '#6b6560', margin: '0 0 16px' }}>
          你的内容已自动保存，不会丢失。可以再试一次，或稍后回来。
        </p>
        <button type="button" className="consumer-primary-button" onClick={reset}>
          再试一次
        </button>
      </section>
    </div>
  )
}
