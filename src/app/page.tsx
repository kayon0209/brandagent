import Link from 'next/link'
import { redirect } from 'next/navigation'

import { auth } from '@clerk/nextjs/server'

/**
 * Landing page (UX review N9) + entry routing (upgrade plan task 15).
 *
 * For two rounds the entire product hid behind a login wall: the root was a
 * bare redirect, so the three trust promises that make this product worth
 * trying were invisible until AFTER sign-up. A landing page is not marketing
 * garnish — it is the product's value contract, stated up front:
 *
 *   1. AI 失败绝不改稿   — the manuscript is never silently damaged
 *   2. 不代替你发布      — publishing stays in the user's hands
 *   3. 没有来源的事实不写 — every factual claim is traceable
 *
 * Rollback switch preserved: NEXT_PUBLIC_DEFAULT_ENTRY=brandflow keeps the
 * old redirect-to-enterprise behavior for the compatibility window.
 */
export default async function HomePage() {
  if (process.env.NEXT_PUBLIC_DEFAULT_ENTRY === 'brandflow') {
    redirect('/brandflow')
  }

  const { userId } = await auth()

  return (
    <main className="landing-page">
      <header className="landing-header">
        <span className="landing-brand">BrandAgent</span>
        <Link href="/app" className="landing-enter">
          {userId ? '项目' : '登录并开始写作'}
        </Link>
      </header>

      <section className="landing-hero">
        <h1>
          一次写完，
          <br />
          处处像你。
        </h1>
        <p className="landing-hero-copy">
          把一句想法写成公众号、小红书和口播稿——难的不是生成文字，
          是每一句都还得像你自己，而且站得住。
        </p>
        <Link href="/app" className="landing-cta">
          {userId ? '继续写作' : '免费开始写作'}
        </Link>
        {!userId && (
          <p className="landing-cta-note">内置每月 AI 额度；写作与保存不消耗额度，无需绑定任何卡。</p>
        )}
      </section>

      <section className="landing-promises" aria-label="我们的三条承诺">
        <div className="landing-promise">
          <h2>始终保留你的原稿</h2>
          <p>AI 只在被要求的地方给出建议，接受前你的稿纸纹丝不动；生成失败也不会留下半截内容。</p>
        </div>
        <div className="landing-promise">
          <h2>发布始终由你决定</h2>
          <p>预览随便看，发布永远由你在平台后台亲手完成——这是刻意的安全设计，不是功能缺失。</p>
        </div>
        <div className="landing-promise">
          <h2>每个事实都能回看来源</h2>
          <p>出现无法溯源的数字或事实时，AI 宁可拒绝改写；每条可引用素材都能点开看到原文出处。</p>
        </div>
      </section>

      <section className="landing-flow">
        <h2>怎么用</h2>
        <ol>
          <li>写下这篇文章的核心观点</li>
          <li>把笔记、录音稿、资料导入素材库，需要时挂到项目上</li>
          <li>生成初稿，选中任何一句让 AI 展开、换例或精简</li>
          <li>一键得到三个平台版本，发布前检查帮你过最后一眼</li>
        </ol>
      </section>

      <footer className="landing-footer">
        <Link href="/app" className="landing-footer-enter">
          {userId ? '继续写作' : '登录 / 注册'}
        </Link>
        <p>你的稿件数据存储在你自己的工作区，可随时导出带走。</p>
      </footer>
    </main>
  )
}
