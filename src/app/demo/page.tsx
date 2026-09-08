import { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'BrandAgent · 交互演示',
  description: 'BrandAgent 个人品牌创作工作台的交互演示',
}

export default function DemoPage() {
  return (
    <iframe
      src="/demo.html"
      style={{
        width: '100%',
        height: '100vh',
        border: 'none',
      }}
    />
  )
}
