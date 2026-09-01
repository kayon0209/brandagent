import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { ClerkProvider } from '@clerk/nextjs'
import '../styles/globals.css'

export const metadata: Metadata = {
  title: 'BrandFlow · 企业品牌内容工作流',
  description: 'BrandFlow 企业品牌内容工作流 — 结构化 Brief、权威事实取证、多渠道谱系与可恢复 LangGraph 流程。',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <ClerkProvider
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      afterSignInUrl="/app"
      afterSignUpUrl="/app"
    >
      <html lang="zh-CN">
        <body>{children}</body>
      </html>
    </ClerkProvider>
  )
}
