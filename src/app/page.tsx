import { redirect } from 'next/navigation'
import { auth } from '@clerk/nextjs/server'
import { BrandLanding } from '@/components/landing/BrandLanding'

export const metadata = { title: 'BrandAgent · 一个人的编辑部', description: '从自己的素材到可修改、可追溯的母稿。判断与签发留给你。' }

export default async function HomePage() {
  if (process.env.NEXT_PUBLIC_DEFAULT_ENTRY === 'brandflow') redirect('/brandflow')
  const { userId } = await auth()
  return <BrandLanding signedIn={Boolean(userId)} />
}
