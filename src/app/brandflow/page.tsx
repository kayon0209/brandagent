'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

// BrandFlow (B-end approval workspace) — kept intact through the consumer
// upgrade compatibility window (plan task 15). It receives no new C-end
// features; personal creators are served by /app. Removing these routes
// requires separate user authorization after the window closes.
export default function BrandFlowIndex() {
  const router = useRouter()
  useEffect(() => { router.replace('/brandflow/tasks') }, [router])
  return null
}
