import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { ClerkProvider } from '@clerk/nextjs'
import { zhCN } from '@clerk/localizations'
import '../styles/globals.css'

export const metadata: Metadata = {
  // UX audit: the root title still carried the legacy B-end product name;
  // the consumer product's own identity comes first (the enterprise surface
  // sets its own route-level metadata under /brandflow)
  title: 'BrandAgent · 一次写完，处处像你',
  description: 'BrandAgent 个人创作工作台 — 素材、核心观点、稿纸、平台预览；AI 失败不改稿，来源可溯，不代替你发布。',
}

// Clerk's applicationName is configured on the Clerk Dashboard as the legacy
// project name ("ai-blog"), which the frontend cannot change. Hardcode the
// brand into the titles so the sign-in/up surfaces never leak the old name.
const brandLocalization = {
  ...zhCN,
  signIn: {
    ...zhCN.signIn!,
    start: {
      ...zhCN.signIn!.start!,
      title: '登录 BrandAgent',
    },
  },
  signUp: {
    ...zhCN.signUp!,
    start: {
      ...zhCN.signUp!.start!,
      title: '创建 BrandAgent 账户',
    },
  },
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <ClerkProvider
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      afterSignInUrl="/app"
      afterSignUpUrl="/app"
      localization={brandLocalization}
    >
      <html lang="zh-CN">
        <body>{children}</body>
      </html>
    </ClerkProvider>
  )
}
