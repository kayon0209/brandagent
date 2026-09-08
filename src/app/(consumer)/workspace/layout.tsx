import type { ReactNode } from 'react'

import '@/styles/consumer-tokens.css'

export const metadata = {
  title: 'BrandAgent',
}

export default function ConsumerAppLayout({ children }: { children: ReactNode }) {
  return <div className="consumer-app-root">{children}</div>
}
