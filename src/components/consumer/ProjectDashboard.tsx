'use client'

import Link from 'next/link'

import styles from './project-dashboard.module.css'

export interface ProjectDashboardProject {
  task_id: string
  title: string
  core_idea: string
  writing_intent: string
}

interface ProjectDashboardProps {
  projects: ProjectDashboardProject[]
  projectCount: number
  learnedStyleCount: number
  quotaRemaining: number | null
  activeFilter: 'all' | 'recent' | 'mine' | 'favorite'
  onFilterChange(filter: 'all' | 'recent' | 'mine' | 'favorite'): void
  onCreateProject(): void
}

const FILTERS: Array<{ value: 'all' | 'recent' | 'mine' | 'favorite'; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'recent', label: '最近 7 天' },
  { value: 'mine', label: '我创建的' },
  { value: 'favorite', label: '收藏' },
]

export function ProjectDashboard({
  projects,
  projectCount,
  learnedStyleCount,
  quotaRemaining,
  activeFilter,
  onFilterChange,
  onCreateProject,
}: ProjectDashboardProps) {
  const weeklyCount = projects.length > 0 ? 1 : 0
  const hasProjects = projects.length > 0

  return (
    <div className={styles.dashboard}>
      <section className={styles.hero} aria-labelledby="project-dashboard-title">
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>你的创作工作台</p>
          <h1 id="project-dashboard-title">项目</h1>
          <p className={styles.heroDescription}>管理你的内容创作项目，让好的想法持续变成有影响力的内容。</p>
          <button type="button" className={styles.createButton} onClick={onCreateProject}>
            <span aria-hidden>＋</span>
            新建项目
          </button>
        </div>
        <div className={styles.heroDesk} aria-hidden>
          <span className={styles.heroNote}>好内容<br />让品牌被看见。</span>
          <span className={styles.heroPaper} />
          <span className={styles.heroPen} />
          <span className={styles.heroBook} />
        </div>
      </section>

      <section className={styles.metrics} aria-label="工作区概况">
        <div className={styles.metricCard}>
          <span className={styles.metricIcon} aria-hidden>▭</span>
          <div className={styles.metricBody}>
            <strong>{projectCount}</strong>
            <span>进行中的项目</span>
            <small>持续写作，收获更多的内容</small>
          </div>
        </div>
        <div className={styles.metricCard}>
          <span className={styles.metricIcon} aria-hidden>◫</span>
          <div className={styles.metricBody}>
            <strong>0</strong>
            <span>已发布内容</span>
            <small>让你的内容被更多人看到</small>
          </div>
        </div>
        <div className={styles.metricCard}>
          <span className={styles.metricIcon} aria-hidden>⬡</span>
          <div className={styles.metricBody}>
            <strong>{learnedStyleCount}</strong>
            <span>学习到的写作风格</span>
            <small>越用越懂你，创作更轻松</small>
          </div>
        </div>
        <div className={`${styles.metricCard} ${styles.metricWeekly}`}>
          <div className={styles.metricBody}>
            <div className={styles.weeklyTop}>
              <span className={styles.weeklyLabel}>本周创作进度</span>
              <Link href="/app" className={styles.weeklyLink}>查看详情 →</Link>
            </div>
            <div className={styles.weeklyMain}>
              <strong>{weeklyCount}</strong>
              <span className={styles.weeklyUnit}>篇内容</span>
            </div>
            <small className={weeklyCount > 0 ? styles.weeklyUp : undefined}>
              {weeklyCount > 0 ? '较上周 +100%' : '还没有本周数据'}
            </small>
          </div>
          <div className={styles.weeklyChart} aria-hidden>
            {['一','二','三','四','五','六','日'].map((d, i) => (
              <span key={d} className={styles.chartBarWrap}>
                <i className={styles.chartBar} data-active={i === 3} style={{ height: `${[8,6,10,28,10,8,6][i]}px` }} />
                <em>{d}</em>
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.quickStart} aria-labelledby="quick-start-title">
        <div className={styles.sectionHeading}>
          <h2 id="quick-start-title">快速开始</h2>
          <p>从一个灵感开始，创建更多可能。</p>
        </div>
        <div className={styles.quickGrid}>
          <button type="button" className={styles.quickCard} onClick={onCreateProject}>
            <span className={styles.quickIcon} aria-hidden>▤</span>
            <span><strong>新建项目</strong><small>从观点到成稿，AI 全程助力</small></span>
            <span className={styles.arrow} aria-hidden>→</span>
          </button>
          <Link className={styles.quickCard} href="/app/materials">
            <span className={styles.quickIcon} aria-hidden>▧</span>
            <span><strong>从素材开始</strong><small>导入资料，生成机理内容</small></span>
            <span className={styles.arrow} aria-hidden>→</span>
          </Link>
          <Link className={styles.quickCard} href="/app/materials">
            <span className={styles.quickIcon} aria-hidden>✦</span>
            <span><strong>导入灵感</strong><small>把想法变成完整内容</small></span>
            <span className={styles.arrow} aria-hidden>→</span>
          </Link>
          <Link className={styles.quickCard} href="/app/style">
            <span className={styles.quickIcon} aria-hidden>◈</span>
            <span><strong>查看平台表现</strong><small>了解内容效果，优化创作方向</small></span>
            <span className={styles.arrow} aria-hidden>→</span>
          </Link>
        </div>
      </section>

      <section className={styles.projects} aria-labelledby="recent-projects-title">
        <div className={styles.projectsToolbar}>
          <div className={styles.toolbarLeft}>
            <h2 id="recent-projects-title">最近项目</h2>
            <div className={styles.filters} role="tablist" aria-label="项目筛选">
              {FILTERS.map(filter => (
                <button
                  key={filter.value}
                  type="button"
                  role="tab"
                  aria-selected={activeFilter === filter.value}
                  data-active={activeFilter === filter.value}
                  onClick={() => onFilterChange(filter.value)}
                >
                  {filter.label}{filter.value === 'all' && hasProjects ? ` (${projects.length})` : ''}
                </button>
              ))}
            </div>
          </div>
          <div className={styles.projectTools}>
            <div className={styles.searchBox} aria-hidden>
              <span>⌕</span>
              <input placeholder="搜索项目名称、内容或标签..." disabled />
            </div>
            <button type="button" className={styles.sortButton}>最近编辑 ▾</button>
            <div className={styles.viewToggle} aria-hidden>
              <span data-active>▦</span><span>☰</span>
            </div>
          </div>
        </div>

        {projects.length > 0 ? (
          <ul className={styles.projectList}>
            {projects.map(project => (
              <li key={project.task_id}>
                <Link href={`/app/write/${project.task_id}`} className={styles.projectRow} aria-label={`打开项目：${project.title}`}>
                  <span className={styles.projectMark} aria-hidden>▭</span>
                  <span className={styles.projectMain}>
                    <span className={styles.projectTitleRow}>
                      <strong>{project.title}</strong>
                      <span className={styles.favStar} aria-hidden>☆</span>
                    </span>
                    <span className={styles.projectSub}>{project.core_idea ? project.core_idea.slice(0, 32) : '还没有填写核心观点。'}</span>
                    <span className={styles.projectMetaRow}>
                      <span className={styles.tagDraft}>草稿中</span>
                      <span className={styles.tagPlain}>公众号</span>
                      <span className={styles.tagPlain}>小红书</span>
                      <span className={styles.tagPlain}>口播</span>
                      <span className={styles.metaDate}>今天编辑 10:24</span>
                    </span>
                  </span>
                  <span className={styles.projectStages} aria-label="项目流程">
                    <span className={styles.stageDone}>观点</span><i />
                    <span className={styles.stageActive}>草稿</span><i />
                    <span>精修</span><i />
                    <span>发布</span>
                  </span>
                  {project.writing_intent && <span className={styles.intentTag}>{project.writing_intent}</span>}
                  <span className={styles.continueAction}>继续创作 <span aria-hidden>→</span></span>
                  <span className={styles.rowMore} aria-hidden>⋯</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className={styles.emptyProjects}>
            <span className={styles.emptyMark} aria-hidden>＋</span>
            <div><strong>从第一篇内容开始</strong><p>写下一个想法，后续可以关联素材、生成初稿，再按平台预览。</p></div>
            <button type="button" onClick={onCreateProject}>新建项目</button>
          </div>
        )}

        {hasProjects && (
          <div className={styles.moreHint}>
            <div className={styles.moreIcon} aria-hidden>▭<span>＋</span></div>
            <div>
              <strong>还没有更多项目？</strong>
              <p>点击「新建项目」开始你的下一个创作，<br />也可以从素材库中发现更多内容。</p>
              <button type="button" className={styles.moreButton} onClick={onCreateProject}>⊕ 新建项目</button>
            </div>
            <span className={styles.moreScript} aria-hidden>好的想法<br />值得被认真对待。</span>
          </div>
        )}
      </section>
    </div>
  )
}
