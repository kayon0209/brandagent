// ============================================================
// 付费意向收集页 —— 在正式接入支付前，先收集付费意向
// src/app/upgrade/page.tsx
// ============================================================
'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

// ─── 套餐信息 ──────────────────────────────────────────────
const PLAN_INFO = {
  pro: {
    name: 'Pro 早鸟',
    price: '¥29 / 月',
    originalPrice: '¥39 / 月',   // 正式上线价
    perks: [
      '每月 500,000 tokens（约 50–80 篇文章）',
      'SEO 关键词分析',
      '无限历史记录',
      '优先生成队列（更快响应）',
      '批量大纲生成',
    ],
  },
  team: {
    name: 'Team 早鸟',
    price: '¥99 / 月',
    originalPrice: '¥149 / 月',  // 正式上线价
    perks: [
      '5 个团队席位',
      '共享 2,000,000 tokens / 月',
      '共享模板库 + 团队风格配置',
      '成员使用统计看板',
      '专属客户经理',
    ],
  },
} as const

type PlanKey = keyof typeof PLAN_INFO

// ─── 表单（需要 useSearchParams，包在 Suspense 里）────────
function UpgradeForm() {
  const searchParams = useSearchParams()
  const planParam = searchParams.get('plan') as PlanKey | null
  const plan: PlanKey = planParam === 'team' ? 'team' : 'pro'
  const info = PLAN_INFO[plan]

  // Mock: no Clerk auth — email left empty for user to fill in
  const [email, setEmail] = useState('')
  const [wechat, setWechat] = useState('')
  const [note, setNote] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) {
      setError('请填写邮箱，方便我们联系你')
      return
    }
    setLoading(true)
    setError('')

    try {
      const res = await fetch('/api/upgrade-intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan, email, wechat, note }),
      })
      if (!res.ok) throw new Error('提交失败，请稍后再试')
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败，请稍后再试')
    } finally {
      setLoading(false)
    }
  }

  // 提交成功
  if (submitted) {
    return (
      <div className="text-center py-16">
        <div
          className="text-5xl mb-6"
          style={{ fontFamily: 'var(--font-serif)', color: 'var(--color-gold)' }}
        >
          ✦
        </div>
        <h2
          className="mb-4"
          style={{ fontFamily: 'var(--font-serif)', fontSize: '1.75rem', color: 'var(--color-ink)' }}
        >
          已收到你的升级意向
        </h2>
        <p
          className="mb-2 text-sm"
          style={{ color: 'var(--color-ink-muted)', lineHeight: 1.8 }}
        >
          我们会在 24 小时内通过邮箱或微信联系你，确认付款方式和开通时间。
        </p>
        <p
          className="mb-10 text-sm"
          style={{ color: 'var(--color-ink-faint)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}
        >
          感谢支持 — 你的反馈是我们继续开发的最大动力
        </p>
        <Link href="/dashboard" className="btn-primary">
          继续使用免费版
        </Link>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-0"
      style={{ border: '1px solid var(--color-ivory-border)' }}
    >
      {/* 左侧：套餐权益 */}
      <div
        className="p-10"
        style={{ backgroundColor: 'var(--color-ink)', borderRight: '1px solid rgba(255,255,255,0.06)' }}
      >
        <div
          className="mb-2 text-xs uppercase tracking-widest"
          style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-gold-muted)' }}
        >
          {info.name}
        </div>
        {/* 价格 + 划线原价 */}
        <div className="flex items-baseline gap-3 mb-1">
          <div
            style={{ fontFamily: 'var(--font-serif)', fontSize: '2rem', fontWeight: 700, color: 'var(--color-ivory)' }}
          >
            {info.price}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.875rem',
              color: 'rgba(250,250,248,0.3)',
              textDecoration: 'line-through',
            }}
          >
            {info.originalPrice}
          </div>
        </div>
        <p
          className="mb-6 text-xs"
          style={{ color: 'var(--color-gold)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}
        >
          早鸟价 · 正式上线后永久有效
        </p>

        <ul className="space-y-3 mb-10">
          {info.perks.map((perk) => (
            <li key={perk} className="flex items-start gap-3 text-sm">
              <span style={{ color: 'var(--color-gold)', fontFamily: 'var(--font-mono)', flexShrink: 0, marginTop: '0.1em' }}>✦</span>
              <span style={{ color: 'rgba(250,250,248,0.75)', fontWeight: 300 }}>{perk}</span>
            </li>
          ))}
        </ul>

        <div
          className="p-4 text-xs"
          style={{
            border: '1px solid rgba(184,134,11,0.3)',
            backgroundColor: 'rgba(184,134,11,0.06)',
            color: 'rgba(250,250,248,0.5)',
            lineHeight: 1.75,
            fontFamily: 'var(--font-mono)',
            letterSpacing: '0.02em',
          }}
        >
          目前 Pro / Team 版正在小范围内测，提交意向后我们会人工确认并开通，通常在 24 小时内完成。
        </div>
      </div>

      {/* 右侧：表单 */}
      <div className="p-10" style={{ backgroundColor: 'var(--color-surface)' }}>
        <h2
          className="mb-2"
          style={{ fontFamily: 'var(--font-serif)', fontSize: '1.375rem', color: 'var(--color-ink)' }}
        >
          留下联系方式
        </h2>
        <p
          className="mb-8 text-sm"
          style={{ color: 'var(--color-ink-muted)', fontWeight: 300 }}
        >
          我们会主动联系你确认付款方式，无骚扰承诺。
        </p>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* 邮箱 */}
          <div>
            <label
              className="block mb-1.5 text-xs uppercase tracking-widest"
              style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-muted)' }}
            >
              邮箱 <span style={{ color: 'var(--color-gold)' }}>*</span>
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="your@email.com"
              required
              style={{
                width: '100%',
                padding: '0.625rem 0.875rem',
                border: '1px solid var(--color-ivory-border)',
                backgroundColor: 'var(--color-ivory)',
                color: 'var(--color-ink)',
                fontFamily: 'var(--font-sans)',
                fontSize: '0.9375rem',
                outline: 'none',
              }}
            />
          </div>

          {/* 微信（可选） */}
          <div>
            <label
              className="block mb-1.5 text-xs uppercase tracking-widest"
              style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-muted)' }}
            >
              微信号 <span style={{ color: 'var(--color-ink-faint)' }}>（可选，更快联系）</span>
            </label>
            <input
              type="text"
              value={wechat}
              onChange={(e) => setWechat(e.target.value)}
              placeholder="微信号"
              style={{
                width: '100%',
                padding: '0.625rem 0.875rem',
                border: '1px solid var(--color-ivory-border)',
                backgroundColor: 'var(--color-ivory)',
                color: 'var(--color-ink)',
                fontFamily: 'var(--font-sans)',
                fontSize: '0.9375rem',
                outline: 'none',
              }}
            />
          </div>

          {/* 备注 */}
          <div>
            <label
              className="block mb-1.5 text-xs uppercase tracking-widest"
              style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink-muted)' }}
            >
              使用场景 <span style={{ color: 'var(--color-ink-faint)' }}>（可选，帮助我们更好服务你）</span>
            </label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="例：技术博客、营销文章、团队内容生产……"
              rows={3}
              style={{
                width: '100%',
                padding: '0.625rem 0.875rem',
                border: '1px solid var(--color-ivory-border)',
                backgroundColor: 'var(--color-ivory)',
                color: 'var(--color-ink)',
                fontFamily: 'var(--font-sans)',
                fontSize: '0.9375rem',
                outline: 'none',
                resize: 'vertical',
              }}
            />
          </div>

          {/* 错误提示 */}
          {error && (
            <p className="text-sm" style={{ color: '#c0392b', fontFamily: 'var(--font-mono)' }}>
              {error}
            </p>
          )}

          {/* 提交 */}
          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full"
            style={{ opacity: loading ? 0.6 : 1, cursor: loading ? 'not-allowed' : 'pointer' }}
          >
            {loading ? '提交中…' : `提交升级意向（${info.name}）`}
          </button>

          <p
            className="text-xs text-center"
            style={{ color: 'var(--color-ink-faint)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}
          >
            提交后不会自动扣款 · 确认后再付款
          </p>
        </form>
      </div>
    </div>
  )
}

// ─── 页面 ──────────────────────────────────────────────────
export default function UpgradePage() {
  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--color-ivory)' }}>

      {/* 顶部导航 */}
      <header className="site-header sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 md:px-10">
          <div className="flex items-center justify-between h-16">
            <Link href="/" style={{ fontFamily: 'var(--font-serif)', fontWeight: 700, fontSize: '1.125rem', color: 'var(--color-ink)', textDecoration: 'none' }}>
              AI写作助手
            </Link>
            <div className="flex items-center gap-4">
              <Link href="/#pricing" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6875rem', color: 'var(--color-ink-muted)', textDecoration: 'none', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                ← 返回定价
              </Link>
              <Link href="/dashboard" className="btn-ghost" style={{ padding: '0.5rem 1.25rem', fontSize: '0.6875rem' }}>
                工作台
              </Link>
            </div>
          </div>
        </div>
      </header>

      {/* 主内容 */}
      <main className="max-w-4xl mx-auto px-6 md:px-10 py-16 md:py-24">

        <div className="text-center mb-12">
          <div className="flex justify-center mb-6">
            <span className="section-label">升级套餐</span>
          </div>
          <h1
            style={{
              fontFamily: 'var(--font-serif)',
              fontSize: 'clamp(1.5rem, 4vw, 2.25rem)',
              fontWeight: 700,
              color: 'var(--color-ink)',
              letterSpacing: '-0.02em',
            }}
          >
            锁定早鸟价格
          </h1>
          <p
            className="mt-4 max-w-lg mx-auto text-sm"
            style={{ color: 'var(--color-ink-muted)', lineHeight: 1.8, fontWeight: 300 }}
          >
            正式支付功能上线前，通过人工方式处理升级。
            留下联系方式，24 小时内确认——这也是我们最真实的付费需求验证。
            <br />
            <span style={{ color: 'var(--color-ink-faint)' }}>名额有限，早鸟价格先到先得。</span>
          </p>
        </div>

        <Suspense fallback={
          <div className="text-center py-12" style={{ color: 'var(--color-ink-faint)', fontFamily: 'var(--font-mono)', fontSize: '0.875rem' }}>
            加载中…
          </div>
        }>
          <UpgradeForm />
        </Suspense>

      </main>
    </div>
  )
}
