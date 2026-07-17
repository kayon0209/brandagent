'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { CircleDot, Gauge, FileText, BookOpen, Tags, LayoutGrid, FileCheck2, Settings, Loader2, Search } from 'lucide-react'
import styles from '@/styles/brandflow'
import { type ReactNode, useState, useEffect } from 'react'
import { useBrandFlow } from '@/hooks/useBrandFlow'
import { SetupWizard } from '@/components/editor/SetupWizard'

const navItems = [
  { href: '/brandflow/overview', icon: Gauge, label: '概览' },
  { href: '/brandflow/tasks', icon: FileText, label: '任务' },
  { href: '/brandflow/knowledge', icon: BookOpen, label: '知识' },
  { href: '/brandflow/brands', icon: Tags, label: '品牌' },
  { href: '/brandflow/channels', icon: LayoutGrid, label: '渠道' },
  { href: '/brandflow/evaluation', icon: FileCheck2, label: '评估' },
  { href: '/brandflow/settings', icon: Settings, label: '设置' },
]

const segmentLabelMap: Record<string, string> = {
  overview: '概览',
  tasks: '任务',
  knowledge: '知识库',
  brands: '品牌',
  channels: '渠道',
  evaluation: '评估',
  settings: '设置',
}

export default function BrandFlowLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const { tasks, loading } = useBrandFlow()
  const [searchValue, setSearchValue] = useState('')
  const [showSetupWizard, setShowSetupWizard] = useState(false)

  useEffect(() => {
    if (!loading && tasks.length === 0) {
      setShowSetupWizard(true)
    }
  }, [loading, tasks.length])

  const pendingCount = tasks.filter((t) => t.status === 'pending_approval' || t.status.startsWith('waiting_for_')).length

  const segments = pathname.replace('/brandflow', '').split('/').filter(Boolean)
  const isTaskId = (s: string) => /^[a-f0-9-]{20,}$/.test(s)
  const breadcrumbs = [
    { label: 'BrandFlow', href: '/brandflow' },
    ...segments.map((seg, i) => {
      let label = segmentLabelMap[seg]
      if (!label) {
        label = isTaskId(seg)
          ? (tasks.find(t => t.task_id === seg)?.title || '任务详情')
          : seg.charAt(0).toUpperCase() + seg.slice(1)
      }
      return { label, href: '/brandflow/' + segments.slice(0, i + 1).join('/') }
    }),
  ]

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (searchValue.trim()) {
      window.location.href = '/brandflow/knowledge?search=' + encodeURIComponent(searchValue.trim())
    }
  }

  if (loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={32} /></div>
        <h1>正在加载工作区</h1>
        <p>读取任务、审批与保存状态。</p>
      </main>
    )
  }

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar} style={{ gridRow: '1 / -1' }}>
        <div className={styles.logo}>
          <b>B</b>
          <span>
            <strong>BrandFlow</strong>
            <small>内容工作区</small>
          </span>
        </div>
        <nav>
          {navItems.map(({ href, icon: Icon, label }) => {
            const isActive = pathname.startsWith(href)
            return (
              <Link key={href} href={href} className={isActive ? styles.active : undefined}>
                <Icon size={18} />
                {label}
              </Link>
            )
          })}
        </nav>
        <div className={styles.system}>
          <CircleDot size={14} />
          状态来自真实服务
        </div>
      </aside>
      <nav className={styles.mobileNav}>
        {navItems.map(({ href, icon: Icon, label }) => {
          const isActive = pathname.startsWith(href)
          return (
            <Link key={href} href={href} className={isActive ? styles.active : undefined}>
              <Icon size={20} />
              <span>{label}</span>
            </Link>
          )
        })}
      </nav>
      <header className={styles.topbar}>
        <div className={styles.breadcrumbs}>
          {breadcrumbs.map((bc, i) => (
            <span key={bc.href}>
              {i > 0 && <span className={styles.separator}>/</span>}
              <Link href={bc.href}>{bc.label}</Link>
            </span>
          ))}
        </div>
        {pendingCount > 0 && (
          <span className={styles.pendingBadge}>{pendingCount} 待审批</span>
        )}
        <form className={styles.searchBox} onSubmit={handleSearch}>
          <Search size={16} />
          <input
            type="text"
            placeholder="搜索任务、知识项或内容..."
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
          />
        </form>
      </header>
      {showSetupWizard && tasks.length === 0 && (pathname === '/brandflow' || pathname === '/brandflow/overview') && (
        <main className={styles.main}>
          <SetupWizard onComplete={() => setShowSetupWizard(false)} />
        </main>
      )}
      {!(showSetupWizard && tasks.length === 0 && (pathname === '/brandflow' || pathname === '/brandflow/overview')) && children}
    </div>
  )
}
