'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Bell,
  BookOpen,
  Check,
  ChevronDown,
  CircleHelp,
  ClipboardList,
  FileCheck2,
  FileText,
  Gauge,
  History,
  LayoutGrid,
  Menu,
  MessageSquareText,
  PanelRightClose,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Tags,
  X,
} from 'lucide-react'
import styles from './brandflow-task-workspace.module.css'

type WorkspaceView = 'brief' | 'outline'
type ContextTab = 'sources' | 'issues' | 'versions'
type ProductArea =
  | 'Overview'
  | 'Tasks'
  | 'Knowledge'
  | 'Brand'
  | 'Channels'
  | 'Evaluation'
  | 'Settings'

const workflow = [
  'Brief',
  'Research',
  'Outline',
  'Master content',
  'Channel variants',
  'Final approval',
  'Export',
]

const briefSections = [
  ['Basic information', true],
  ['Audience and objective', true],
  ['Product and key messages', true],
  ['Required facts and sources', false],
  ['Brand tone', false],
  ['Forbidden claims', false],
  ['Channel selection', true],
  ['Final review', false],
] as const

const navItems = [
  [Gauge, 'Overview'],
  [ClipboardList, 'Tasks'],
  [BookOpen, 'Knowledge'],
  [Tags, 'Brand'],
  [LayoutGrid, 'Channels'],
  [FileCheck2, 'Evaluation'],
  [Settings, 'Settings'],
] as const

export function BrandFlowTaskWorkspace() {
  const [activeArea, setActiveArea] = useState<ProductArea>('Overview')
  const [taskCenterOpen, setTaskCenterOpen] = useState(true)
  const [view, setView] = useState<WorkspaceView>('brief')
  const [contextTab, setContextTab] = useState<ContextTab>('sources')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(true)
  const [mobileContextOpen, setMobileContextOpen] = useState(false)
  const [savedState, setSavedState] = useState<'saved' | 'saving'>('saved')
  const [taskName, setTaskName] = useState('Nova X3 Q3 产品发布')
  const [audience, setAudience] = useState('企业 IT 决策者与设备管理负责人')
  const [objective, setObjective] = useState('建立可信的产品认知，并引导预约产品演示')
  const [approvalDialog, setApprovalDialog] = useState(false)
  const [approved, setApproved] = useState(false)
  const [validationAttempted, setValidationAttempted] = useState(false)
  const saveTimer = useRef<number | null>(null)

  const currentStep = view === 'brief' ? 1 : 3
  const completion = useMemo(
    () =>
      Math.round(
        (briefSections.filter((section) => section[1]).length / briefSections.length) * 100
      ),
    []
  )

  const requiredFieldsComplete = Boolean(taskName.trim() && audience.trim() && objective.trim())

  useEffect(() => {
    const draft = window.sessionStorage.getItem('brandflow-demo-brief')
    if (!draft) return
    try {
      const parsed = JSON.parse(draft) as {
        taskName?: string
        audience?: string
        objective?: string
      }
      if ('taskName' in parsed) setTaskName(parsed.taskName ?? '')
      if ('audience' in parsed) setAudience(parsed.audience ?? '')
      if ('objective' in parsed) setObjective(parsed.objective ?? '')
    } catch {
      window.sessionStorage.removeItem('brandflow-demo-brief')
    }
  }, [])

  useEffect(() => {
    setSavedState('saving')
    if (saveTimer.current) window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      window.sessionStorage.setItem(
        'brandflow-demo-brief',
        JSON.stringify({ taskName, audience, objective })
      )
      setSavedState('saved')
    }, 650)
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current)
    }
  }, [taskName, audience, objective])

  function updateField(setter: (value: string) => void, value: string) {
    setter(value)
  }

  function submitBrief() {
    setValidationAttempted(true)
    if (requiredFieldsComplete) setView('outline')
  }

  return (
    <div className={styles.app}>
      <button
        className={styles.mobileMenu}
        onClick={() => setSidebarOpen(true)}
        aria-label="打开主导航"
      >
        <Menu size={19} />
      </button>

      <aside className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ''}`}>
        <div className={styles.brandBlock}>
          <div className={styles.brandMark}>B</div>
          <div>
            <strong>BrandFlow</strong>
            <span>Acme 内容工作区</span>
          </div>
          <button
            className={styles.mobileClose}
            onClick={() => setSidebarOpen(false)}
            aria-label="关闭主导航"
          >
            <X size={18} />
          </button>
        </div>

        <nav className={styles.primaryNav} aria-label="主导航">
          {navItems.map(([Icon, label]) => (
            <button
              type="button"
              className={label === activeArea ? styles.activeNav : undefined}
              onClick={() => {
                setActiveArea(label)
                if (label === 'Tasks') setTaskCenterOpen(true)
                setSidebarOpen(false)
              }}
              key={label}
            >
              <Icon size={17} />
              <span>{label}</span>
              {label === 'Tasks' && <em>4</em>}
            </button>
          ))}
        </nav>

        <div className={styles.sidebarFooter}>
          <button className={styles.systemStatus}>
            <span className={styles.unverifiedDot} />
            状态未验证 · 示例
            <ChevronDown size={14} />
          </button>
          <div className={styles.userBlock}>
            <span className={styles.avatar}>陈</span>
            <span>
              <strong>李雯</strong>
              <small>品牌审核人 · 示例</small>
            </span>
          </div>
        </div>
      </aside>

      <div className={styles.workspace} id="task-workspace">
        <div className={styles.demoBanner} role="note">
          <span>前端预览</span>
          示例数据不会写入生产系统；Brief 草稿仅保留在当前标签页。
          <button onClick={() => setView(view === 'brief' ? 'outline' : 'brief')}>
            预览{view === 'brief' ? '大纲审批' : 'Brief 编辑'}
          </button>
        </div>
        <header className={styles.topbar}>
          <div className={styles.breadcrumb}>
            {activeArea === 'Tasks' ? <ArrowLeft size={15} /> : <LayoutGrid size={15} />}
            <span>{activeArea}</span>
            {activeArea === 'Tasks' && <i>/</i>}
            {activeArea === 'Tasks' && <strong>{taskName}</strong>}
          </div>
          <div className={styles.topActions}>
            <span className={styles.saveState} aria-live="polite">
              {savedState === 'saving' ? (
                <span className={styles.savingDot} />
              ) : (
                <Check size={14} />
              )}
              {savedState === 'saving' ? 'Saving…' : 'Saved'}
            </span>
            <button className={styles.iconButton} aria-label="搜索">
              <Search size={18} />
            </button>
            <button className={styles.notificationButton} aria-label="通知与待审批">
              <Bell size={18} />
              <span>2</span>
            </button>
            {activeArea === 'Tasks' && !taskCenterOpen && (
              <button
                className={styles.primaryButton}
                onClick={() => (view === 'brief' ? submitBrief() : setApprovalDialog(true))}
                disabled={view === 'outline' && approved}
              >
                {view === 'brief' ? '提交 Brief' : approved ? '大纲已批准' : '审核并批准'}
              </button>
            )}
          </div>
        </header>

        {activeArea === 'Tasks' && taskCenterOpen ? (
          <TaskCenterPage onOpenTask={() => setTaskCenterOpen(false)} />
        ) : activeArea === 'Tasks' ? (
          <>
            <section className={styles.taskHeader}>
              <div>
                <span className={styles.eyebrow}>CONTENT TASK · BF-2026-034</span>
                <h1>{view === 'brief' ? '完善内容 Brief' : '审核主内容大纲'}</h1>
                <p>
                  {view === 'brief'
                    ? '按引导补充必要信息，系统会在提交前指出事实缺口。'
                    : '检查结构、内容策略以及每一节的来源覆盖。'}
                </p>
              </div>
              <span className={view === 'brief' ? styles.infoBadge : styles.warningBadge}>
                {view === 'brief' ? `${completion}% complete` : '等待品牌审核'}
              </span>
            </section>

            <ol className={styles.workflowStepper} aria-label="任务进度">
              {workflow.map((label, index) => {
                const step = index + 1
                const state =
                  step < currentStep ? 'done' : step === currentStep ? 'current' : 'future'
                return (
                  <li className={styles[state]} key={label}>
                    <span>{state === 'done' ? <Check size={13} /> : step}</span>
                    <b>{label}</b>
                    <small>
                      {state === 'current' ? (view === 'brief' ? 'Editing' : 'Needs action') : ''}
                    </small>
                  </li>
                )
              })}
            </ol>

            <div className={`${styles.contentGrid} ${!contextOpen ? styles.contextCollapsed : ''}`}>
              <main className={styles.mainCanvas}>
                {view === 'brief' ? (
                  <BriefEditor
                    taskName={taskName}
                    audience={audience}
                    objective={objective}
                    updateTaskName={(value) => updateField(setTaskName, value)}
                    updateAudience={(value) => updateField(setAudience, value)}
                    updateObjective={(value) => updateField(setObjective, value)}
                    completion={completion}
                    validationAttempted={validationAttempted}
                    onContinue={submitBrief}
                  />
                ) : (
                  <OutlineEditor
                    onRequestIssue={() => setContextTab('issues')}
                    onApprove={() => setApprovalDialog(true)}
                  />
                )}
              </main>

              {(contextOpen || mobileContextOpen) && (
                <ContextPanel
                  activeTab={contextTab}
                  onTabChange={setContextTab}
                  view={view}
                  mobileOpen={mobileContextOpen}
                />
              )}
              <button
                className={styles.contextToggle}
                onClick={() => {
                  if (window.matchMedia('(max-width: 900px)').matches) {
                    setMobileContextOpen((open) => !open)
                  } else {
                    setContextOpen((open) => !open)
                  }
                }}
                aria-label={contextOpen ? '收起上下文面板' : '展开上下文面板'}
              >
                <PanelRightClose size={17} />
              </button>
            </div>
          </>
        ) : (
          <ProductAreaPage
            area={activeArea}
            onOpenTask={() => {
              setActiveArea('Tasks')
              setTaskCenterOpen(true)
            }}
          />
        )}
      </div>

      {approvalDialog && (
        <div
          className={styles.dialogBackdrop}
          role="presentation"
          onMouseDown={() => setApprovalDialog(false)}
        >
          <section
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="approval-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className={styles.dialogIcon}>
              <ShieldCheck size={22} />
            </div>
            <span className={styles.eyebrow}>DELIBERATE APPROVAL</span>
            <h2 id="approval-title">批准大纲 v3</h2>
            <p>批准后，系统将以此版本生成主内容。当前仍有 1 项非阻塞警告，涉及第二节的品牌措辞。</p>
            <dl className={styles.approvalSummary}>
              <div>
                <dt>当前版本</dt>
                <dd>Outline v3</dd>
              </div>
              <div>
                <dt>来源覆盖</dt>
                <dd>6 / 7 claims</dd>
              </div>
              <div>
                <dt>受影响阶段</dt>
                <dd>Master content</dd>
              </div>
            </dl>
            <div className={styles.dialogActions}>
              <button className={styles.secondaryButton} onClick={() => setApprovalDialog(false)}>
                返回检查
              </button>
              <button
                className={styles.primaryButton}
                onClick={() => {
                  setApproved(true)
                  setApprovalDialog(false)
                }}
              >
                确认界面预览状态
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

function ProductAreaPage({
  area,
  onOpenTask,
}: {
  area: Exclude<ProductArea, 'Tasks'>
  onOpenTask: () => void
}) {
  const pages = {
    Overview: <OverviewPage onOpenTask={onOpenTask} />,
    Knowledge: <KnowledgePage />,
    Brand: <BrandPage />,
    Channels: <ChannelsPage />,
    Evaluation: <EvaluationPage />,
    Settings: <SettingsPage />,
  }
  return pages[area]
}

function PageIntro({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string
  title: string
  description: string
  action?: string
}) {
  return (
    <header className={styles.pageIntro}>
      <div>
        <span className={styles.eyebrow}>{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && (
        <button className={styles.primaryButton} disabled title="等待后端接入">
          {action}
        </button>
      )}
    </header>
  )
}

function OverviewPage({ onOpenTask }: { onOpenTask: () => void }) {
  return (
    <main className={styles.areaPage}>
      <PageIntro
        eyebrow="TUESDAY · 14 JULY"
        title="内容运营概览"
        description="只展示需要采取行动的工作、运行状态和可信系统提醒。"
        action="创建内容任务"
      />
      <section className={styles.actionStrip}>
        <div>
          <span className={styles.warningIcon}>
            <Bell size={18} />
          </span>
          <p>
            <b>3 个任务需要人工操作</b>
            <small>1 个大纲审批、1 个事实澄清、1 个最终审批</small>
          </p>
        </div>
        <button onClick={onOpenTask}>打开任务收件箱</button>
      </section>
      <div className={styles.overviewGrid}>
        <section className={styles.areaCard}>
          <div className={styles.areaCardHeader}>
            <div>
              <span className={styles.panelLabel}>REQUIRES ACTION</span>
              <h2>待你处理</h2>
            </div>
            <button>查看全部</button>
          </div>
          <TaskRow
            status="大纲审批"
            title="Nova X3 Q3 产品发布"
            meta="品牌审核 · 等待 42 分钟"
            tone="warning"
            onClick={onOpenTask}
          />
          <TaskRow
            status="需要澄清"
            title="Aster 企业安全白皮书"
            meta="缺少可公开使用的客户数据"
            tone="error"
          />
          <TaskRow
            status="最终审批"
            title="Orbit 2.0 发布内容包"
            meta="4 个渠道已审核"
            tone="info"
          />
        </section>
        <section className={styles.areaCard}>
          <div className={styles.areaCardHeader}>
            <div>
              <span className={styles.panelLabel}>RUNNING NOW</span>
              <h2>正在运行</h2>
            </div>
          </div>
          <ProgressTask title="Atlas 春季活动" stage="正在核验产品事实" progress={42} />
          <ProgressTask title="Nova 合作伙伴邮件" stage="正在生成渠道版本" progress={76} />
          <div className={styles.systemNotice}>
            <span className={styles.statusDot} />
            <p>
              <b>知识与工具服务可用</b>
              <small>状态为前端示例，不代表实时监控结果</small>
            </p>
          </div>
        </section>
      </div>
      <section className={styles.areaCard}>
        <div className={styles.areaCardHeader}>
          <div>
            <span className={styles.panelLabel}>RECENTLY COMPLETED</span>
            <h2>最近完成</h2>
          </div>
          <button>查看内容库</button>
        </div>
        <div className={styles.compactTable}>
          <div className={styles.tableHead}>
            <span>内容任务</span>
            <span>批准版本</span>
            <span>渠道</span>
            <span>完成时间</span>
          </div>
          <div>
            <b>Nova X2 生命周期更新</b>
            <span>Master v8</span>
            <span>4 / 4</span>
            <span>昨天 16:24</span>
          </div>
          <div>
            <b>Acme 品牌术语更新</b>
            <span>Master v3</span>
            <span>2 / 2</span>
            <span>7 月 11 日</span>
          </div>
        </div>
      </section>
    </main>
  )
}

function TaskCenterPage({ onOpenTask }: { onOpenTask: () => void }) {
  const filters = [
    'All tasks',
    'Draft Briefs',
    'Running',
    'Needs clarification',
    'Needs approval',
    'Failed',
    'Completed',
  ]
  return (
    <main className={styles.areaPage}>
      <PageIntro
        eyebrow="TASK CENTER"
        title="内容任务"
        description="按需要采取的动作组织任务，而不是暴露内部工作流节点。"
        action="创建内容任务"
      />
      <div className={styles.taskFilters}>
        {filters.map((filter, index) => (
          <button className={index === 0 ? styles.activeTaskFilter : undefined} key={filter}>
            {filter}
          </button>
        ))}
      </div>
      <section className={styles.areaCard}>
        <div className={styles.taskTableHeader}>
          <span>任务</span>
          <span>当前阶段</span>
          <span>渠道</span>
          <span>需要操作</span>
          <span>最近更新</span>
        </div>
        <TaskTableRow
          title="Nova X3 Q3 产品发布"
          id="BF-2026-034"
          stage="Outline"
          channels="4 channels"
          action="大纲审批"
          update="42 分钟前"
          tone="warning"
          onClick={onOpenTask}
        />
        <TaskTableRow
          title="Aster 企业安全白皮书"
          id="BF-2026-033"
          stage="Brief"
          channels="2 channels"
          action="补充事实"
          update="1 小时前"
          tone="error"
        />
        <TaskTableRow
          title="Atlas 春季活动"
          id="BF-2026-032"
          stage="Research"
          channels="3 channels"
          action="系统运行中"
          update="2 小时前"
          tone="info"
        />
        <TaskTableRow
          title="Orbit 2.0 发布内容包"
          id="BF-2026-031"
          stage="Final approval"
          channels="4 channels"
          action="最终审批"
          update="昨天"
          tone="warning"
        />
        <TaskTableRow
          title="Nova X2 生命周期更新"
          id="BF-2026-030"
          stage="Completed"
          channels="4 channels"
          action="已完成"
          update="昨天"
          tone="info"
        />
      </section>
    </main>
  )
}

function TaskTableRow({
  title,
  id,
  stage,
  channels,
  action,
  update,
  tone,
  onClick,
}: {
  title: string
  id: string
  stage: string
  channels: string
  action: string
  update: string
  tone: 'warning' | 'error' | 'info'
  onClick?: () => void
}) {
  return (
    <button className={styles.taskTableRow} onClick={onClick}>
      <span>
        <b>{title}</b>
        <small>{id}</small>
      </span>
      <span>{stage}</span>
      <span>{channels}</span>
      <span className={styles[`${tone}Badge`]}>{action}</span>
      <span>{update}</span>
    </button>
  )
}

function TaskRow({
  status,
  title,
  meta,
  tone,
  onClick,
}: {
  status: string
  title: string
  meta: string
  tone: 'warning' | 'error' | 'info'
  onClick?: () => void
}) {
  return (
    <button className={styles.taskRow} onClick={onClick}>
      <span className={styles[`${tone}Badge`]}>{status}</span>
      <span>
        <b>{title}</b>
        <small>{meta}</small>
      </span>
      <ChevronDown size={16} />
    </button>
  )
}

function ProgressTask({
  title,
  stage,
  progress,
}: {
  title: string
  stage: string
  progress: number
}) {
  return (
    <div className={styles.progressTask}>
      <div>
        <b>{title}</b>
        <span>{progress}%</span>
      </div>
      <p>{stage}</p>
      <div>
        <i style={{ width: `${progress}%` }} />
      </div>
    </div>
  )
}

function KnowledgePage() {
  const tabs = [
    'Product facts',
    'Brand guidelines',
    'Channel guidelines',
    'Approved content',
    'Forbidden claims',
  ]
  return (
    <main className={styles.areaPage}>
      <PageIntro
        eyebrow="KNOWLEDGE CENTER"
        title="权威知识与文档"
        description="管理可被内容工作流引用的事实、规范、版本与使用权限。"
        action="上传文档"
      />
      <div className={styles.filterBar}>
        <div className={styles.searchField}>
          <Search size={16} />
          <input aria-label="搜索知识" placeholder="搜索文档、事实或术语" />
        </div>
        <button>
          全部状态 <ChevronDown size={14} />
        </button>
        <button>
          有效日期 <ChevronDown size={14} />
        </button>
      </div>
      <div className={styles.knowledgeLayout}>
        <aside className={styles.knowledgeTabs}>
          {tabs.map((tab, index) => (
            <button className={index === 0 ? styles.activeKnowledgeTab : undefined} key={tab}>
              {tab}
              <span>{[24, 6, 4, 18, 12][index]}</span>
            </button>
          ))}
        </aside>
        <section className={styles.areaCard}>
          <div className={styles.areaCardHeader}>
            <div>
              <span className={styles.panelLabel}>PRODUCT FACTS</span>
              <h2>Nova X3</h2>
            </div>
            <span className={styles.infoBadge}>24 active facts</span>
          </div>
          <KnowledgeItem
            title="最长 18 小时本地视频播放续航"
            source="Nova X3 产品规格书 · v4 · 第 8 页"
            authority="Primary"
            date="生效至 2027-03-31"
          />
          <KnowledgeItem
            title="支持统一设备策略配置与安全更新"
            source="Nova X3 管理指南 · v2 · 第 3 节"
            authority="Primary"
            date="生效中"
          />
          <KnowledgeItem
            title="适用于常见混合办公设备环境"
            source="2026 产品定位说明 · 第 2 节"
            authority="Approved"
            date="需品牌审核"
          />
        </section>
      </div>
    </main>
  )
}

function KnowledgeItem({
  title,
  source,
  authority,
  date,
}: {
  title: string
  source: string
  authority: string
  date: string
}) {
  return (
    <article className={styles.knowledgeItem}>
      <span>
        <FileCheck2 size={17} />
      </span>
      <div>
        <h3>{title}</h3>
        <p>{source}</p>
        <div>
          <em>{authority}</em>
          <small>{date}</small>
          <small>允许公开使用</small>
        </div>
      </div>
      <button aria-label={`查看${title}`}>•••</button>
    </article>
  )
}

function BrandPage() {
  return (
    <main className={styles.areaPage}>
      <PageIntro
        eyebrow="ACTIVE BRAND PROFILE · V6"
        title="Acme Enterprise 品牌规范"
        description="当前工作流使用此版本检查定位、术语、语气和禁用表达。"
        action="创建新版本"
      />
      <div className={styles.brandGrid}>
        <section className={styles.areaCard}>
          <span className={styles.panelLabel}>POSITIONING</span>
          <h2>让复杂的企业技术更容易被理解和采用</h2>
          <p className={styles.readingText}>
            Acme
            以精确、克制、证据优先的方式解释产品价值。内容应帮助决策者理解适用场景和真实边界，而不是制造焦虑。
          </p>
          <div className={styles.termGrid}>
            <div>
              <b>标准公司名</b>
              <span>Acme Enterprise</span>
            </div>
            <div>
              <b>标准产品名</b>
              <span>Nova X3</span>
            </div>
            <div>
              <b>首选术语</b>
              <span>集中管理、可验证、安全更新</span>
            </div>
            <div>
              <b>避免术语</b>
              <span>颠覆、革命性、绝对安全</span>
            </div>
          </div>
        </section>
        <aside className={styles.areaCard}>
          <span className={styles.panelLabel}>TONE PROFILE</span>
          <h2>语气权重</h2>
          <Tone label="可信" value={92} />
          <Tone label="清晰" value={86} />
          <Tone label="克制" value={78} />
          <Tone label="活跃" value={34} />
          <div className={styles.brandWarning}>
            <AlertTriangle size={16} />
            <p>
              <b>禁止绝对化承诺</b>
              <small>包括“零风险”“行业第一”“永久有效”</small>
            </p>
          </div>
        </aside>
      </div>
    </main>
  )
}

function Tone({ label, value }: { label: string; value: number }) {
  return (
    <div className={styles.toneRow}>
      <span>{label}</span>
      <div>
        <i style={{ width: `${value}%` }} />
      </div>
      <b>{value}</b>
    </div>
  )
}

function ChannelsPage() {
  const channels = [
    ['微信 / 官网', 'v3', '已批准', '长文 · 1,680 字'],
    ['小红书', 'v4', '有警告', '短帖 · 682 字'],
    ['60 秒视频', 'v2', '已批准', '约 56 秒'],
    ['营销邮件', 'v3', '待审批', '主题 + 正文'],
  ]
  return (
    <main className={styles.areaPage}>
      <PageIntro
        eyebrow="CHANNEL MATRIX · MASTER V7"
        title="多渠道内容矩阵"
        description="所有渠道版本均从同一个已批准主内容版本派生。"
        action="运行一致性检查"
      />
      <section className={styles.masterSummary}>
        <div>
          <span className={styles.successMark}>
            <Check size={16} />
          </span>
          <p>
            <b>Canonical master content v7</b>
            <small>批准于 7 月 14 日 11:08 · 来源覆盖 100%</small>
          </p>
        </div>
        <button>查看主内容与沿袭关系</button>
      </section>
      <div className={styles.channelGrid}>
        {channels.map(([name, version, status, meta], index) => (
          <article className={styles.channelCard} key={name}>
            <header>
              <span>{['微', 'RED', '▶', '@'][index]}</span>
              <div>
                <h2>{name}</h2>
                <p>源自 Master v7 · {version}</p>
              </div>
              <em
                className={
                  status === '已批准'
                    ? styles.successBadge
                    : status === '有警告'
                      ? styles.warningBadge
                      : styles.infoBadge
                }
              >
                {status}
              </em>
            </header>
            <div className={styles.channelPreview}>
              <b>
                {index === 0
                  ? '让混合办公设备管理更可控'
                  : index === 1
                    ? 'IT 团队的设备管理，终于不用靠“人盯人”'
                    : index === 2
                      ? '0–5 秒｜办公室切换镜头'
                      : 'Subject: 让设备管理少一点不确定性'}
              </b>
              <p>
                {index === 2
                  ? '当团队分散在不同地点，设备策略是否还能保持一致？'
                  : 'Nova X3 以可验证的续航和集中管理能力，支持常见混合办公场景。'}
              </p>
            </div>
            <footer>
              <span>{meta}</span>
              <button>打开渠道版本</button>
            </footer>
          </article>
        ))}
      </div>
      <section className={styles.consistencyBar}>
        <ShieldCheck size={19} />
        <div>
          <b>跨渠道事实一致性：通过</b>
          <small>4 个渠道均引用 Master v7；小红书存在 1 项非阻塞语气警告。</small>
        </div>
        <button>查看分组问题</button>
      </section>
    </main>
  )
}

function EvaluationPage() {
  return (
    <main className={styles.areaPage}>
      <PageIntro
        eyebrow="EVALUATION · NO FABRICATED METRICS"
        title="质量与工作流评估"
        description="此页面仅展示指标定义和待采集状态；没有版本化运行结果前不显示成功率。"
        action="创建评估任务"
      />
      <div className={styles.evalNotice}>
        <CircleHelp size={18} />
        <p>
          <b>尚无可复现评估运行</b>
          <small>连接版本化任务集并执行评估后，系统才会显示真实样本量、质量、成本和延迟。</small>
        </p>
      </div>
      <div className={styles.metricGrid}>
        {[
          ['Master content', '事实支持率、引用准确率、Brief 覆盖率'],
          ['Channel quality', '格式符合率、新增无支持主张、核心信息保留'],
          ['Workflow', '完成率、修订次数、人工介入节点'],
          ['MCP reliability', '工具成功率、超时、降级和恢复'],
          ['Human editing', '字符、句子、事实、结构与语气编辑'],
          ['Cost & latency', '按 provider、model、prompt version 记录'],
        ].map(([title, desc]) => (
          <article className={styles.metricCard} key={title}>
            <span>Not measured</span>
            <h2>{title}</h2>
            <p>{desc}</p>
            <button>查看指标定义</button>
          </article>
        ))}
      </div>
    </main>
  )
}

function SettingsPage() {
  return (
    <main className={styles.areaPage}>
      <PageIntro
        eyebrow="WORKSPACE SETTINGS"
        title="设置与高级配置"
        description="技术配置保持次级；敏感值不会在界面中回显。"
      />
      <div className={styles.settingsLayout}>
        <aside className={styles.knowledgeTabs}>
          {[
            'Workspace',
            'Members & roles',
            'Model providers',
            'MCP servers',
            'Workflow',
            'Data & export',
          ].map((x, i) => (
            <button className={i === 0 ? styles.activeKnowledgeTab : undefined} key={x}>
              {x}
            </button>
          ))}
        </aside>
        <section className={styles.areaCard}>
          <span className={styles.panelLabel}>WORKSPACE</span>
          <h2>基础信息</h2>
          <div className={styles.settingsForm}>
            <label>
              <span>Workspace name</span>
              <input defaultValue="Acme 内容工作区" />
            </label>
            <label>
              <span>Default brand</span>
              <button>
                Acme Enterprise <ChevronDown size={15} />
              </button>
            </label>
            <label>
              <span>Default locale</span>
              <button>
                简体中文 <ChevronDown size={15} />
              </button>
            </label>
          </div>
          <div className={styles.settingsSection}>
            <div>
              <h3>审批职责分离</h3>
              <p>作者不能批准自己最后编辑的版本。</p>
            </div>
            <button className={styles.toggle} aria-label="审批职责分离已启用">
              <span />
            </button>
          </div>
          <div className={styles.settingsSection}>
            <div>
              <h3>高级系统状态</h3>
              <p>模型与 MCP 连接状态需要后端接入后才能验证。</p>
            </div>
            <span className={styles.neutralBadge}>Unverified</span>
          </div>
          <footer className={styles.editorFooter}>
            <button className={styles.primaryButton}>保存工作区设置</button>
          </footer>
        </section>
      </div>
    </main>
  )
}

function BriefEditor(props: {
  taskName: string
  audience: string
  objective: string
  updateTaskName: (value: string) => void
  updateAudience: (value: string) => void
  updateObjective: (value: string) => void
  completion: number
  validationAttempted: boolean
  onContinue: () => void
}) {
  return (
    <div className={styles.briefLayout}>
      <aside className={styles.sectionNav}>
        <div
          className={styles.progressRing}
          style={{ '--progress': `${props.completion * 3.6}deg` } as React.CSSProperties}
        >
          <span>{props.completion}%</span>
        </div>
        <div>
          <strong>Brief progress</strong>
          <small>4 of 8 sections complete</small>
        </div>
        <nav aria-label="Brief sections">
          {briefSections.map(([label, complete], index) => (
            <button className={index === 0 ? styles.currentSection : undefined} key={label}>
              <span>{complete ? <Check size={12} /> : index + 1}</span>
              {label}
            </button>
          ))}
        </nav>
        <div className={styles.continueLater}>
          <History size={16} />
          <span>
            <b>Continue later</b>
            <small>Your draft is saved automatically.</small>
          </span>
        </div>
      </aside>

      <section className={styles.editorCard}>
        <div className={styles.cardHeader}>
          <div>
            <span className={styles.sectionNumber}>01</span>
            <h2>Basic information</h2>
            <p>Give the task a clear internal name and establish its working context.</p>
          </div>
          <CircleHelp size={19} />
        </div>
        <div className={styles.formGrid}>
          <label className={styles.fullField}>
            <span>
              Task name <em>Required</em>
            </span>
            <input
              required
              aria-invalid={props.validationAttempted && !props.taskName.trim()}
              value={props.taskName}
              onChange={(event) => props.updateTaskName(event.target.value)}
            />
            <small>Use a name teammates can recognize in approvals and exports.</small>
          </label>
          <label>
            <span>
              Brand <em>Required</em>
            </span>
            <button className={styles.selectField}>
              Acme Enterprise <ChevronDown size={16} />
            </button>
          </label>
          <label>
            <span>
              Product <em>Required</em>
            </span>
            <button className={styles.selectField}>
              Nova X3 <ChevronDown size={16} />
            </button>
          </label>
          <label className={styles.fullField}>
            <span>
              Primary audience <em>Required</em>
            </span>
            <input
              required
              aria-invalid={props.validationAttempted && !props.audience.trim()}
              value={props.audience}
              onChange={(event) => props.updateAudience(event.target.value)}
            />
          </label>
          <label className={styles.fullField}>
            <span>
              Content objective <em>Required</em>
            </span>
            <textarea
              required
              aria-invalid={props.validationAttempted && !props.objective.trim()}
              rows={3}
              value={props.objective}
              onChange={(event) => props.updateObjective(event.target.value)}
            />
            <small>Describe the desired audience response, not a vague performance target.</small>
          </label>
        </div>
        <div className={styles.linkedFacts}>
          <div>
            <FileText size={18} />
            <span>
              <b>2 authoritative documents linked</b>
              <small>Nova X3 规格书 v4 · 产品定位说明 2026</small>
            </span>
          </div>
          <button>Review sources</button>
        </div>
        <footer className={styles.editorFooter}>
          <button className={styles.secondaryButton}>Save and continue later</button>
          <button className={styles.secondaryButton} onClick={props.onContinue}>
            Preview outline screen
          </button>
        </footer>
      </section>
    </div>
  )
}

function OutlineEditor({
  onRequestIssue,
  onApprove,
}: {
  onRequestIssue: () => void
  onApprove: () => void
}) {
  const outline = [
    [
      '01',
      '混合办公下的设备管理挑战',
      '建立真实的业务背景，避免未经证实的市场规模与绝对化表述。',
      '2 sources',
      'supported',
    ],
    [
      '02',
      'Nova X3 的核心产品价值',
      '围绕续航、集中管理与安全更新解释产品价值。',
      '1 warning',
      'warning',
    ],
    [
      '03',
      '部署、合规与下一步',
      '以可验证的部署信息结束，并引导预约产品演示。',
      '3 sources',
      'supported',
    ],
  ] as const

  return (
    <section className={styles.outlineCard}>
      <header className={styles.outlineHeader}>
        <div>
          <span className={styles.eyebrow}>CONTENT STRATEGY</span>
          <h2>结构与论证路径</h2>
          <p>每个章节都应服务同一内容目标，并能追溯至来源。</p>
        </div>
        <span className={styles.aiLabel}>
          <Sparkles size={14} /> AI-generated · v3
        </span>
      </header>
      <div className={styles.strategyNote}>
        <MessageSquareText size={18} />
        <p>
          <b>Strategy note</b>面向企业 IT
          决策者，使用克制、证据优先的表达。重点说明可验证的设备管理价值，而不是泛化的“智能化升级”。
        </p>
      </div>
      <div className={styles.outlineList}>
        {outline.map(([number, title, description, evidence, state]) => (
          <article key={number}>
            <span className={styles.outlineNumber}>{number}</span>
            <div>
              <h3>{title}</h3>
              <p>{description}</p>
              <button onClick={state === 'warning' ? onRequestIssue : undefined}>
                {state === 'warning' ? <AlertTriangle size={13} /> : <FileCheck2 size={13} />}
                {evidence}
              </button>
            </div>
            <button className={styles.moreButton} aria-label={`编辑${title}`}>
              •••
            </button>
          </article>
        ))}
      </div>
      <footer className={styles.editorFooter}>
        <button className={styles.secondaryButton}>Request revision</button>
        <button className={styles.primaryButton} onClick={onApprove}>
          Review and approve v3
        </button>
      </footer>
    </section>
  )
}

function ContextPanel({
  activeTab,
  onTabChange,
  view,
  mobileOpen,
}: {
  activeTab: ContextTab
  onTabChange: (tab: ContextTab) => void
  view: WorkspaceView
  mobileOpen: boolean
}) {
  return (
    <aside className={`${styles.contextPanel} ${mobileOpen ? styles.contextPanelMobileOpen : ''}`}>
      <div className={styles.contextTabs} role="tablist" aria-label="任务上下文">
        {(['sources', 'issues', 'versions'] as const).map((tab) => (
          <button
            className={activeTab === tab ? styles.activeContextTab : undefined}
            onClick={() => onTabChange(tab)}
            role="tab"
            aria-selected={activeTab === tab}
            key={tab}
          >
            {tab}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {activeTab === 'sources' && <SourcesPanel view={view} />}
        {activeTab === 'issues' && <IssuesPanel />}
        {activeTab === 'versions' && <VersionsPanel />}
      </div>
    </aside>
  )
}

function SourcesPanel({ view }: { view: WorkspaceView }) {
  return (
    <div className={styles.contextContent}>
      <span className={styles.panelLabel}>
        {view === 'brief' ? 'LINKED KNOWLEDGE' : 'SECTION EVIDENCE'}
      </span>
      <h3>{view === 'brief' ? 'Authoritative sources' : 'Evidence coverage'}</h3>
      <p>
        {view === 'brief'
          ? 'These sources will ground research and claim review.'
          : '6 of 7 outline claims have direct support.'}
      </p>
      <div className={styles.sourceItem}>
        <span>PDF</span>
        <div>
          <b>Nova X3 产品规格书</b>
          <small>Version 4 · Active</small>
        </div>
        <em>42 facts</em>
      </div>
      <div className={styles.sourceItem}>
        <span>DOC</span>
        <div>
          <b>2026 产品定位说明</b>
          <small>Approved · 3 days ago</small>
        </div>
        <em>18 facts</em>
      </div>
      <button className={styles.addSourceButton}>+ Link another knowledge item</button>
      <div className={styles.advancedDisclosure}>
        <button>
          Advanced retrieval details <ChevronDown size={14} />
        </button>
      </div>
    </div>
  )
}

function IssuesPanel() {
  return (
    <div className={styles.contextContent}>
      <span className={styles.panelLabel}>REVIEW ISSUES</span>
      <h3>1 issue needs attention</h3>
      <p>Resolve critical issues before approval. Warnings may be acknowledged.</p>
      <div className={styles.issueCard}>
        <span>
          <AlertTriangle size={16} />
        </span>
        <div>
          <b>Unsupported superiority claim</b>
          <p>“行业领先”没有权威比较依据。删除表述或关联可信来源。</p>
          <button>Open in outline</button>
        </div>
      </div>
      <div className={styles.resolvedIssue}>
        <Check size={15} />
        <span>
          <b>Forbidden claim removed</b>
          <small>Resolved in outline v3</small>
        </span>
      </div>
    </div>
  )
}

function VersionsPanel() {
  return (
    <div className={styles.contextContent}>
      <span className={styles.panelLabel}>VERSION LINEAGE</span>
      <h3>Outline history</h3>
      <p>Approval always applies to one immutable version.</p>
      {['v3 · Current review', 'v2 · AI revision', 'v1 · Initial generation'].map(
        (version, index) => (
          <div className={styles.versionItem} key={version}>
            <span>{index === 0 ? 'NOW' : `0${3 - index}`}</span>
            <div>
              <b>{version}</b>
              <small>{index === 0 ? 'Based on operator feedback' : 'Created by BrandFlow'}</small>
            </div>
          </div>
        )
      )}
    </div>
  )
}
