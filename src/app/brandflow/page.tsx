'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function BrandFlowIndex() {
  const router = useRouter()
  useEffect(() => { router.replace('/brandflow/tasks') }, [router])
  return null
}
