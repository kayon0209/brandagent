'use client'

/**
 * Shared consumer top navigation (round-3f P0-4). Every /app/* workspace
 * page mounts the SAME chrome — BrandAgent 项目 素材库 风格实验室 + account —
 * so the app stops reading as several disconnected products. The write page
 * keeps its own document topbar (brand + back + materials + title + publish)
 * which is the same pattern plus the document context.
 */

import Link from 'next/link'
import { UserButton } from '@clerk/nextjs'

import buttonStyles from '@/components/consumer/editor/consumer-editor.module.css'
import styles from '@/components/consumer/materials/consumer-materials.module.css'

type Section = 'projects' | 'materials' | 'style'

const NAV: Array<{ key: Section; href: string; label: string }> = [
  { key: 'projects', href: '/app', label: '项目' },
  { key: 'materials', href: '/app/materials', label: '素材库' },
  { key: 'style', href: '/app/style', label: '风格实验室' },
]

export function ConsumerNav({ active }: { active: Section }) {
  return (
    <div className={styles.consumerNav} data-testid="consumer-nav">
      <Link href="/app" className={styles.consumerNavBrand} aria-label="BrandAgent 首页">
        BrandAgent
      </Link>
      <nav className={styles.consumerNavLinks} aria-label="工作台导航">
        {NAV.map(item => (
          <Link
            key={item.key}
            href={item.href}
            className={styles.consumerNavLink}
            data-active={active === item.key}
            aria-current={active === item.key ? 'page' : undefined}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className={styles.consumerNavAccount}>
        <UserButton afterSignOutUrl="/sign-in" />
      </div>
    </div>
  )
}

export { buttonStyles }