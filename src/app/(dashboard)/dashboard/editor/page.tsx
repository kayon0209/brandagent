// ============================================================
// 编辑器工作台主页面
// src/app/(dashboard)/dashboard/editor/page.tsx
// ============================================================
'use client'

import { useCallback, useEffect, useRef, useState, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { OutlineSection, WorkflowStep } from '@/types'
import { useArticleEditor, type AgentPhase, type SectionAgentStatus } from '@/hooks/useArticleEditor'
import { useModerationCheck } from '@/hooks/useModerationCheck'
import { ExportPanel } from '@/components/editor/ExportPanel'
import { PolishPanel } from '@/components/editor/PolishPanel'
import { SeoPanel } from '@/components/editor/SeoPanel'

// ═══════════════════════════════════════════════════════════════
// 常量
// ═══════════════════════════════════════════════════════════════
const STEPS: { key: WorkflowStep; label: string; num: number }[] = [
  { key: 'topic', label: '主题', num: 1 },
  { key: 'titles', label: '标题', num: 2 },
  { key: 'outline', label: '大纲', num: 3 },
  { key: 'writing', label: '写作', num: 4 },
]

const STEP_ORDER: WorkflowStep[] = ['topic', 'titles', 'outline', 'writing', 'done']

function stepIndex(s: WorkflowStep): number {
  return STEP_ORDER.indexOf(s)
}

// ── Token 配额（从 API 实时加载） ──────────────────────────────
interface QuotaData {
  used: number
  total: number | null  // null 表示 Pro/Team 无限制
  plan: string
}

function useQuota(): QuotaData {
  const [quota, setQuota] = useState<QuotaData>({ used: 0, total: 30000, plan: 'Free' })
  useEffect(() => {
    fetch('/api/quota')
      .then(r => r.json())
      .then(json => {
        if (json.success && json.data) {
          setQuota(json.data)
        }
      })
      .catch(() => { /* 静默降级，保持默认值 */ })
  }, [])
  return quota
}

// ═══════════════════════════════════════════════════════════════
// 子组件：步骤进度条
// ═══════════════════════════════════════════════════════════════
interface StepBarProps {
  current: WorkflowStep
}

function StepBar({ current }: StepBarProps) {
  const currentIdx = stepIndex(current)
  return (
    <div className="flex items-center gap-0 border-b border-[var(--color-ivory-border)] bg-[var(--color-surface)]">
      {STEPS.map((s, i) => {
        const done = stepIndex(s.key) < currentIdx
        const active = s.key === current
        return (
          <div
            key={s.key}
            className={[
              'flex items-center gap-2 px-5 py-3 text-xs font-mono uppercase tracking-widest transition-all duration-200',
              active
                ? 'text-[var(--color-gold)] border-b-2 border-[var(--color-gold)] bg-[var(--color-ivory)]'
                : done
                  ? 'text-[var(--color-ink-muted)]'
                  : 'text-[var(--color-ink-faint)]',
            ].join(' ')}
          >
            <span
              className={[
                'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                active
                  ? 'bg-[var(--color-gold)] text-white'
                  : done
                    ? 'bg-[var(--color-ink-muted)] text-white'
                    : 'bg-[var(--color-ivory-border)] text-[var(--color-ink-faint)]',
              ].join(' ')}
            >
              {done ? '✓' : s.num}
            </span>
            {s.label}
            {i < STEPS.length - 1 && (
              <span className="ml-2 text-[var(--color-ivory-border)]">›</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 子组件：左侧导航面板
// ═══════════════════════════════════════════════════════════════
interface SideNavProps {
  current: WorkflowStep
  outline: { sections: OutlineSection[] } | null
  expandedContent: Record<string, string>
  agentStatus: Record<string, SectionAgentStatus>
  quota: QuotaData
  onSectionClick?: (id: string) => void
}

function agentIcon(phase: AgentPhase): string {
  if (phase === 'running') return '⟳'
  if (phase === 'done') return '✓'
  if (phase === 'failed') return '✕'
  return '○'
}

function agentColor(phase: AgentPhase): string {
  if (phase === 'running') return 'text-[var(--color-gold)]'
  if (phase === 'done') return 'text-green-600'
  if (phase === 'failed') return 'text-red-500'
  return 'text-[var(--color-ink-faint)]'
}

function SideNav({ current, outline, expandedContent, agentStatus, quota, onSectionClick }: SideNavProps) {
  const pct = quota.total !== null ? Math.min(100, Math.round((quota.used / quota.total) * 100)) : 0

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-[var(--color-ivory-border)] bg-[var(--color-surface-warm)]">
      {/* 步骤列表 */}
      <div className="flex-1 overflow-y-auto p-4">
        <p className="section-label-inline mb-4">工作流程</p>
        <nav className="space-y-1">
          {STEPS.map(s => {
            const done = stepIndex(s.key) < stepIndex(current)
            const active = s.key === current
            return (
              <div
                key={s.key}
                className={[
                  'rounded-none border-l-2 px-3 py-2 text-sm transition-all',
                  active
                    ? 'border-[var(--color-gold)] bg-[var(--color-ivory)] font-medium text-[var(--color-ink)]'
                    : done
                      ? 'border-transparent text-[var(--color-ink-muted)]'
                      : 'border-transparent text-[var(--color-ink-faint)]',
                ].join(' ')}
              >
                {s.label}
              </div>
            )
          })}
        </nav>

        {/* writing 阶段显示章节列表 */}
        {current === 'writing' && outline && (
          <div className="mt-6">
            <p className="section-label-inline mb-3">章节进度</p>
            <div className="space-y-2">
              {outline.sections.map(sec => {
                const st = agentStatus[sec.id]
                const isDone = !!expandedContent[sec.id] && expandedContent[sec.id].length > 50
                return (
                  <button
                    key={sec.id}
                    onClick={() => onSectionClick?.(sec.id)}
                    className="w-full rounded-none border border-[var(--color-ivory-border)] bg-[var(--color-ivory)] px-3 py-2 text-left text-xs transition-all hover:border-[var(--color-gold)]"
                  >
                    <div className="truncate font-medium text-[var(--color-ink)]">{sec.title}</div>
                    {st && (
                      <div className="mt-1 flex gap-2">
                        <span className={`${agentColor(st.research)} font-mono`} title="研究">
                          🔍{agentIcon(st.research)}
                        </span>
                        <span className={`${agentColor(st.write)} font-mono`} title="写作">
                          ✍{agentIcon(st.write)}
                        </span>
                        <span className={`${agentColor(st.review)} font-mono`} title="审校">
                          ✅{agentIcon(st.review)}
                        </span>
                      </div>
                    )}
                    {isDone && !st && (
                      <div className="mt-1 text-[var(--color-ink-faint)]">已完成</div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Token 配额（Free 用户） */}
      <div className="border-t border-[var(--color-ivory-border)] p-4">
        <div className="flex items-center justify-between mb-1">
          <span className="section-label-inline">Token 配额</span>
          <span className="text-xs font-mono text-[var(--color-ink-muted)]">{quota.plan}</span>
        </div>
        {quota.total !== null ? (
          <>
            <div className="h-1.5 w-full rounded-none bg-[var(--color-ivory-border)]">
              <div
                className="h-1.5 bg-[var(--color-gold)] transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="mt-1 flex justify-between font-mono text-[10px] text-[var(--color-ink-faint)]">
              <span>{quota.used.toLocaleString()}</span>
              <span>{quota.total.toLocaleString()}</span>
            </div>
          </>
        ) : (
          <p className="mt-1 font-mono text-[10px] text-green-600">无限制</p>
        )}
      </div>
    </aside>
  )
}

// ═══════════════════════════════════════════════════════════════
// 子组件：错误提示条
// ═══════════════════════════════════════════════════════════════
interface ErrorBannerProps {
  message: string
  onClose: () => void
}

function ErrorBanner({ message, onClose }: ErrorBannerProps) {
  return (
    <div className="flex items-start gap-3 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      <span className="mt-0.5 shrink-0">⚠</span>
      <span className="flex-1">{message}</span>
      <button onClick={onClose} className="shrink-0 text-red-400 hover:text-red-600">
        ✕
      </button>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Step 1：主题输入
// ═══════════════════════════════════════════════════════════════
interface TopicStepProps {
  topic: string
  audience: string
  isLoading: boolean
  blockedMessage: string | null
  onTopicChange: (v: string) => void
  onAudienceChange: (v: string) => void
  onClearBlocked: () => void
  onSubmit: () => void
}

function TopicStep({ topic, audience, isLoading, blockedMessage, onTopicChange, onAudienceChange, onClearBlocked, onSubmit }: TopicStepProps) {
  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSubmit()
    }
  }

  return (
    <div className="mx-auto max-w-xl py-12">
      <h2 className="mb-1 font-serif text-2xl font-bold text-[var(--color-ink)]">
        开始你的文章
      </h2>
      <div className="rule-divider-gold mb-6" />
      <div className="space-y-5">
        <div>
          <label className="mb-1.5 block text-xs font-mono uppercase tracking-widest text-[var(--color-ink-muted)]">
            文章主题 <span className="text-red-400">*</span>
          </label>
          <input
            className="input"
            placeholder="例如：AI工具推荐、职场成长技巧..."
            value={topic}
            onChange={e => { onTopicChange(e.target.value); onClearBlocked() }}
            onKeyDown={handleKey}
            disabled={isLoading}
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-mono uppercase tracking-widest text-[var(--color-ink-muted)]">
            目标读者 <span className="text-[var(--color-ink-faint)]">（可选）</span>
          </label>
          <input
            className="input"
            placeholder="例如：职场新人、独立博主..."
            value={audience}
            onChange={e => onAudienceChange(e.target.value)}
            onKeyDown={handleKey}
            disabled={isLoading}
          />
        </div>
        {blockedMessage && (
          <div className="flex items-start gap-2 border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            <span className="shrink-0 mt-0.5">⚠</span>
            <span>{blockedMessage}</span>
          </div>
        )}
        <button
          className="btn-primary w-full justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={onSubmit}
          disabled={isLoading || !topic.trim()}
        >
          {isLoading ? (
            <>
              <span className="animate-spin">⟳</span> 生成中...
            </>
          ) : (
            '生成标题建议 →'
          )}
        </button>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Step 2：标题选择
// ═══════════════════════════════════════════════════════════════
interface TitlesStepProps {
  titles: { title: string; reason: string }[]
  selectedTitle: string
  customTitle: string
  isLoading: boolean
  onSelect: (title: string) => void
  onCustomChange: (v: string) => void
  onRegenerate: () => void
  onConfirm: (title: string) => Promise<void>
}

function TitlesStep({
  titles,
  selectedTitle,
  customTitle,
  isLoading,
  onSelect,
  onCustomChange,
  onRegenerate,
  onConfirm,
}: TitlesStepProps) {
  const effectiveTitle = customTitle.trim() || selectedTitle

  return (
    <div className="py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="font-serif text-2xl font-bold text-[var(--color-ink)]">选择标题</h2>
          <div className="rule-divider-gold mt-1" />
        </div>
        <button className="btn-ghost text-xs" onClick={onRegenerate} disabled={isLoading}>
          重新生成
        </button>
      </div>

      <div className="space-y-2">
        {titles.map((item, i) => {
          const active = selectedTitle === item.title && !customTitle.trim()
          return (
            <button
              key={i}
              onClick={() => onSelect(item.title)}
              className={[
                'w-full rounded-none border p-4 text-left transition-all',
                active
                  ? 'border-[var(--color-gold)] bg-[var(--color-ivory)]'
                  : 'border-[var(--color-ivory-border)] bg-[var(--color-surface)] hover:border-[var(--color-gold)]',
              ].join(' ')}
            >
              <div className="font-medium text-[var(--color-ink)]">{item.title}</div>
              <div className="mt-1 text-xs text-[var(--color-ink-muted)]">{item.reason}</div>
            </button>
          )
        })}
      </div>

      {/* 自定义标题 */}
      <div className="mt-6">
        <label className="mb-1.5 block text-xs font-mono uppercase tracking-widest text-[var(--color-ink-muted)]">
          或自定义标题
        </label>
        <input
          className="input"
          placeholder="输入你自己的标题..."
          value={customTitle}
          onChange={e => onCustomChange(e.target.value)}
        />
      </div>

      <div className="mt-6">
        <button
          className="btn-primary w-full justify-center disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={!effectiveTitle || isLoading}
          onClick={() => onConfirm(effectiveTitle)}
        >
          {isLoading ? (
            <>
              <span className="animate-spin">⟳</span> 生成大纲中...
            </>
          ) : (
            '使用此标题，生成大纲 →'
          )}
        </button>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 可拖拽章节行（@dnd-kit/sortable）
// ═══════════════════════════════════════════════════════════════
interface SortableSectionRowProps {
  section: OutlineSection
  onRemove: (id: string) => void
  onUpdate: (id: string, updates: Partial<OutlineSection>) => void
}

function SortableSectionRow({ section, onRemove, onUpdate }: SortableSectionRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: section.id,
  })

  const [expanded, setExpanded] = useState(false)
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState(section.title)

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const commitTitle = () => {
    if (titleDraft.trim()) {
      onUpdate(section.id, { title: titleDraft.trim() })
    } else {
      setTitleDraft(section.title)
    }
    setEditingTitle(false)
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="border border-[var(--color-ivory-border)] bg-[var(--color-surface)]"
    >
      <div className="flex items-center gap-2 px-3 py-2">
        {/* 拖拽把手 */}
        <button
          {...attributes}
          {...listeners}
          className="cursor-grab touch-none text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)] active:cursor-grabbing"
          aria-label="拖拽排序"
        >
          ⋮⋮
        </button>

        {/* 标题 */}
        {editingTitle ? (
          <input
            className="input flex-1 py-1"
            value={titleDraft}
            onChange={e => setTitleDraft(e.target.value)}
            onBlur={commitTitle}
            onKeyDown={e => {
              if (e.key === 'Enter') commitTitle()
              if (e.key === 'Escape') {
                setTitleDraft(section.title)
                setEditingTitle(false)
              }
            }}
            autoFocus
          />
        ) : (
          <button
            className="flex-1 text-left font-medium text-[var(--color-ink)] hover:text-[var(--color-gold)]"
            onDoubleClick={() => setEditingTitle(true)}
            title="双击编辑标题"
          >
            {section.title}
          </button>
        )}

        {/* 展开/折叠要点 */}
        <button
          onClick={() => setExpanded(v => !v)}
          className="shrink-0 text-xs text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
        >
          {expanded ? '▲' : '▼'}
        </button>

        {/* 删除 */}
        <button
          onClick={() => onRemove(section.id)}
          className="shrink-0 text-xs text-[var(--color-ink-faint)] hover:text-red-500"
          aria-label="删除章节"
        >
          ✕
        </button>
      </div>

      {/* 要点列表 */}
      {expanded && (
        <div className="border-t border-[var(--color-ivory-border)] px-4 py-2">
          <ul className="space-y-1">
            {section.points.map((p, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-[var(--color-ink-muted)]">
                <span className="mt-1 shrink-0 text-[var(--color-gold)]">·</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Step 3：大纲确认
// ═══════════════════════════════════════════════════════════════
interface OutlineStepProps {
  outline: { intro: string; sections: OutlineSection[]; conclusion: string } | null
  outlineLength: 'short' | 'medium' | 'long'
  isLoading: boolean
  selectedTitle: string
  customTitle: string
  onLengthChange: (v: 'short' | 'medium' | 'long') => void
  onRegenerate: () => void
  onAddSection: () => void
  onRemoveSection: (id: string) => void
  onUpdateSection: (id: string, updates: Partial<OutlineSection>) => void
  onReorderSections: (sections: OutlineSection[]) => void
  onConfirm: () => void
}

function OutlineStep({
  outline,
  outlineLength,
  isLoading,
  selectedTitle,
  customTitle,
  onLengthChange,
  onRegenerate,
  onAddSection,
  onRemoveSection,
  onUpdateSection,
  onReorderSections,
  onConfirm,
}: OutlineStepProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event
      if (!over || active.id === over.id || !outline) return
      const oldIdx = outline.sections.findIndex(s => s.id === active.id)
      const newIdx = outline.sections.findIndex(s => s.id === over.id)
      if (oldIdx === -1 || newIdx === -1) return
      onReorderSections(arrayMove(outline.sections, oldIdx, newIdx))
    },
    [outline, onReorderSections]
  )

  const displayTitle = customTitle.trim() || selectedTitle

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-[var(--color-ink-muted)]">
        <span className="animate-spin text-3xl">⟳</span>
        <p className="mt-4 font-mono text-sm uppercase tracking-widest">大纲生成中...</p>
      </div>
    )
  }

  if (!outline) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-[var(--color-ink-faint)]">
        <p>暂无大纲，请先选择标题</p>
      </div>
    )
  }

  return (
    <div className="py-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h2 className="font-serif text-2xl font-bold text-[var(--color-ink)]">确认大纲</h2>
          {displayTitle && (
            <p className="mt-1 text-sm text-[var(--color-ink-muted)]">{displayTitle}</p>
          )}
          <div className="rule-divider-gold mt-2" />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {/* 文章长度 */}
          <select
            className="input w-auto py-1.5 text-xs"
            value={outlineLength}
            onChange={e => onLengthChange(e.target.value as 'short' | 'medium' | 'long')}
          >
            <option value="short">短文（~800字）</option>
            <option value="medium">中文（~1500字）</option>
            <option value="long">长文（~3000字）</option>
          </select>
          <button className="btn-ghost text-xs" onClick={onRegenerate}>
            重新生成
          </button>
        </div>
      </div>

      {/* 引言 */}
      <div className="mb-3 border border-[var(--color-ivory-border)] bg-[var(--color-ivory)] px-4 py-3">
        <p className="section-label-inline mb-1">引言</p>
        <p className="text-sm text-[var(--color-ink-muted)]">{outline.intro}</p>
      </div>

      {/* 可拖拽章节 */}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext
          items={outline.sections.map(s => s.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-2">
            {outline.sections.map(sec => (
              <SortableSectionRow
                key={sec.id}
                section={sec}
                onRemove={onRemoveSection}
                onUpdate={onUpdateSection}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      {/* 添加章节 */}
      <button
        onClick={onAddSection}
        className="mt-2 w-full border border-dashed border-[var(--color-ivory-border)] py-2 text-xs font-mono uppercase tracking-widest text-[var(--color-ink-faint)] transition-all hover:border-[var(--color-gold)] hover:text-[var(--color-gold)]"
      >
        + 添加章节
      </button>

      {/* 结论 */}
      <div className="mt-3 border border-[var(--color-ivory-border)] bg-[var(--color-ivory)] px-4 py-3">
        <p className="section-label-inline mb-1">结论</p>
        <p className="text-sm text-[var(--color-ink-muted)]">{outline.conclusion}</p>
      </div>

      <button
        className="btn-primary mt-6 w-full justify-center"
        onClick={onConfirm}
      >
        确认大纲，开始写作 →
      </button>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// Step 4：写作阶段
// ═══════════════════════════════════════════════════════════════
interface WritingStepProps {
  outline: { intro: string; sections: OutlineSection[]; conclusion: string } | null
  articleTitle: string
  articleId: string | null
  expandedContent: Record<string, string>
  agentStatus: Record<string, SectionAgentStatus>
  expandingSections: Set<string>
  activeSectionRef: React.RefObject<HTMLDivElement>
  onExpandSection: (section: OutlineSection) => void
  onExpandAll: () => void
  onUpdateSectionContent: (id: string, content: string) => void
}

function WritingStep({
  outline,
  articleTitle,
  articleId,
  expandedContent,
  agentStatus,
  expandingSections,
  activeSectionRef,
  onExpandSection,
  onExpandAll,
  onUpdateSectionContent,
}: WritingStepProps) {
  const [copied, setCopied] = useState<'md' | 'rich' | null>(null)
  const [activePanel, setActivePanel] = useState<'export' | 'polish' | 'seo' | null>(null)

  if (!outline) return null

  const allDone = outline.sections.every(s => expandedContent[s.id]?.length > 50)
  const anyRunning = expandingSections.size > 0

  // 拼接全文（Markdown）
  const fullMarkdown = [
    `# ${articleTitle}`,
    '',
    outline.intro,
    '',
    ...outline.sections.flatMap(sec => [
      `## ${sec.title}`,
      '',
      expandedContent[sec.id] ?? '（待生成）',
      '',
    ]),
    `## 结语`,
    '',
    outline.conclusion,
  ].join('\n')

  const copyMd = async () => {
    await navigator.clipboard.writeText(fullMarkdown)
    setCopied('md')
    setTimeout(() => setCopied(null), 2000)
  }

  // 去掉 Markdown 标记（# ## 等），复制纯文本，粘贴到微信/掘金等平台更干净
  const copyRich = async () => {
    const plainText = fullMarkdown
      .replace(/^#{1,6}\s+/gm, '')   // 去掉标题前缀 # ## 等
      .replace(/\*\*(.*?)\*\*/g, '$1') // 去掉加粗 **text**
      .replace(/\*(.*?)\*/g, '$1')     // 去掉斜体 *text*
      .replace(/`(.*?)`/g, '$1')       // 去掉行内代码 `code`
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // 去掉链接，保留文字
      .trim()
    await navigator.clipboard.writeText(plainText)
    setCopied('rich')
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div className="flex h-full flex-col">
      {/* 操作栏 */}
      <div className="flex items-center justify-between border-b border-[var(--color-ivory-border)] bg-[var(--color-surface)] px-6 py-3">
        <h2 className="font-serif text-lg font-bold text-[var(--color-ink)]">全文生成</h2>
        <div className="flex gap-2">
          {!allDone && (
            <button
              className="btn-primary text-xs"
              onClick={onExpandAll}
              disabled={anyRunning}
            >
              {anyRunning ? (
                <>
                  <span className="animate-spin">⟳</span> 生成中...
                </>
              ) : (
                '一键生成全文 →'
              )}
            </button>
          )}
          {allDone && (
            <>
              <button className="btn-ghost text-xs" onClick={copyMd}>
                {copied === 'md' ? '✓ 已复制' : 'Markdown 复制'}
              </button>
              <button className="btn-primary text-xs" onClick={copyRich}>
                {copied === 'rich' ? '✓ 已复制' : '全文复制'}
              </button>
            </>
          )}
        </div>
      </div>

      {/* 主体区：章节状态 + 流式内容 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左：章节列表（可单独扩写） */}
        <div className="w-56 shrink-0 overflow-y-auto border-r border-[var(--color-ivory-border)] p-3">
          <p className="section-label-inline mb-3">章节</p>
          <div className="space-y-2">
            {outline.sections.map(sec => {
              const st = agentStatus[sec.id]
              const isExpanding = expandingSections.has(sec.id)
              const isDone = !!expandedContent[sec.id] && expandedContent[sec.id].length > 50

              return (
                <div
                  key={sec.id}
                  className={[
                    'border p-2 text-xs transition-all',
                    isDone
                      ? 'border-green-200 bg-green-50'
                      : isExpanding
                        ? 'border-[var(--color-gold)] bg-[var(--color-ivory)]'
                        : 'border-[var(--color-ivory-border)] bg-[var(--color-surface)]',
                  ].join(' ')}
                >
                  <div className="mb-1 font-medium text-[var(--color-ink)] leading-snug">
                    {sec.title}
                  </div>
                  {st && (
                    <div className="flex gap-1.5 text-[10px]">
                      <span className={agentColor(st.research)}>🔍{agentIcon(st.research)}</span>
                      <span className={agentColor(st.write)}>✍{agentIcon(st.write)}</span>
                      <span className={agentColor(st.review)}>✅{agentIcon(st.review)}</span>
                    </div>
                  )}
                  {!isDone && !isExpanding && (
                    <button
                      onClick={() => onExpandSection(sec)}
                      className="mt-1 text-[10px] font-mono uppercase tracking-widest text-[var(--color-gold)] hover:underline"
                    >
                      生成
                    </button>
                  )}
                  {isDone && (
                    <span className="mt-1 block text-[10px] text-green-600">已完成</span>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* 右：全文内容展示 */}
        <div
          ref={activeSectionRef}
          className="flex-1 overflow-y-auto bg-[var(--color-ivory)] p-8 font-serif"
        >
          <h1 className="mb-2 font-serif text-3xl font-bold text-[var(--color-ink)]">
            {articleTitle}
          </h1>
          <div className="rule-divider-gold mb-6" />

          {/* 引言 */}
          <p className="mb-8 text-[var(--color-ink-secondary)] leading-relaxed">{outline.intro}</p>

          {/* 各章节 */}
          {outline.sections.map(sec => (
            <div key={sec.id} id={`section-${sec.id}`} className="mb-8">
              <h2 className="mb-4 font-serif text-xl font-semibold text-[var(--color-ink)]">
                {sec.title}
              </h2>
              {expandedContent[sec.id] ? (
                <div className="whitespace-pre-wrap text-[var(--color-ink-secondary)] leading-[1.9]">
                  {expandedContent[sec.id]}
                </div>
              ) : expandingSections.has(sec.id) ? (
                <div className="flex items-center gap-2 text-sm text-[var(--color-ink-faint)]">
                  <span className="animate-pulse">▌</span>
                  <span>正在生成...</span>
                </div>
              ) : (
                <div className="border border-dashed border-[var(--color-ivory-border)] py-6 text-center text-sm text-[var(--color-ink-faint)]">
                  等待生成
                </div>
              )}
            </div>
          ))}

          {/* 结论 */}
          <div className="border-t border-[var(--color-ivory-border)] pt-6">
            <h2 className="mb-4 font-serif text-xl font-semibold text-[var(--color-ink)]">
              结语
            </h2>
            <p className="text-[var(--color-ink-secondary)] leading-[1.9]">{outline.conclusion}</p>
          </div>

          {/* 完成后的功能区 */}
          {allDone && (
            <div className="mt-12 space-y-4">
              {/* 功能选项卡按钮组 */}
              <div className="flex gap-2 border-b border-[var(--color-ivory-border)] pb-4">
                <button
                  className={activePanel === 'export' ? 'btn-primary text-xs' : 'btn-ghost text-xs'}
                  onClick={() => setActivePanel(activePanel === 'export' ? null : 'export')}
                >
                  ↓ 导出文章
                </button>
                <button
                  className={activePanel === 'polish' ? 'btn-primary text-xs' : 'btn-ghost text-xs'}
                  onClick={() => setActivePanel(activePanel === 'polish' ? null : 'polish')}
                >
                  ✦ 润色文章
                </button>
                <button
                  className={activePanel === 'seo' ? 'btn-primary text-xs' : 'btn-ghost text-xs'}
                  onClick={() => setActivePanel(activePanel === 'seo' ? null : 'seo')}
                >
                  ◎ SEO 分析
                </button>
              </div>

              {/* 导出面板 */}
              {activePanel === 'export' && (
                <ExportPanel
                  articleTitle={articleTitle}
                  fullMarkdown={fullMarkdown}
                  wordCount={Math.round(fullMarkdown.length / 2)}
                  articleId={articleId}
                />
              )}

              {/* 润色面板：对全文内容润色 */}
              {activePanel === 'polish' && (
                <PolishPanel
                  content={outline.sections
                    .map(s => `## ${s.title}\n\n${expandedContent[s.id] ?? ''}`)
                    .join('\n\n')}
                  onApply={(polished) => {
                    // 将润色结果写入第一个章节的 expandedContent（简化策略）
                    // 用户也可通过"复制润色结果"按钮直接复制
                    const firstSection = outline.sections[0]
                    if (firstSection) {
                      onUpdateSectionContent(firstSection.id, polished)
                    }
                  }}
                />
              )}

              {/* SEO 分析面板 */}
              {activePanel === 'seo' && (
                <SeoPanel
                  articleTitle={articleTitle}
                  content={outline.sections
                    .map(s => expandedContent[s.id] ?? '')
                    .filter(c => c.length > 0)
                    .join('\n\n')
                    .slice(0, 10000)}
                />
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════════════
function EditorPageInner() {
  const editor = useArticleEditor()
  const activeSectionRef = useRef<HTMLDivElement>(null)
  const searchParams = useSearchParams()
  const moderation = useModerationCheck()
  const quota = useQuota()

  // 读取 URL ?id= 参数，若存在则加载文章（避免重复加载）
  useEffect(() => {
    const id = searchParams.get('id')
    if (id && !editor.articleId) {
      editor.loadArticle(id)
    }
  }, [searchParams, editor.articleId, editor.loadArticle])

  // 当进入 writing 步骤后自动滚动到顶部
  useEffect(() => {
    if (editor.step === 'writing') {
      activeSectionRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [editor.step])

  // 加载中占位
  if (editor.isLoading) {
    return (
      <div
        className="flex flex-col bg-[var(--color-ivory)] overflow-hidden"
        style={{ height: 'calc(100vh - 3.75rem)' }}
      >
        <div className="flex flex-1 items-center justify-center flex-col gap-4 text-[var(--color-ink-muted)]">
          <span className="animate-spin text-4xl">⟳</span>
          <p className="font-mono text-sm uppercase tracking-widest">加载文章中...</p>
        </div>
      </div>
    )
  }

  // ── 中间 AI 操作区内容 ────────────────────────────────────────
  const renderCenter = () => {
    switch (editor.step) {
      case 'topic':
        return (
          <TopicStep
            topic={editor.topic}
            audience={editor.audience}
            isLoading={editor.isGeneratingTitles || moderation.isChecking}
            blockedMessage={moderation.blockedMessage}
            onTopicChange={editor.setTopic}
            onAudienceChange={editor.setAudience}
            onClearBlocked={moderation.clearBlocked}
            onSubmit={async () => {
              if (!editor.topic.trim()) return
              const allowed = await moderation.checkText(editor.topic + ' ' + editor.audience)
              if (!allowed) return
              editor.generateTitles()
            }}
          />
        )

      case 'titles':
        return (
          <TitlesStep
            titles={editor.titles}
            selectedTitle={editor.selectedTitle}
            customTitle={editor.customTitle}
            isLoading={editor.isGeneratingOutline}
            onSelect={t => {
              // 点击标题卡：高亮选中，清空自定义输入
              editor.setSelectedTitle(t)
              editor.setCustomTitle('')
            }}
            onCustomChange={editor.setCustomTitle}
            onRegenerate={editor.generateTitles}
            onConfirm={editor.selectTitle}
          />
        )

      case 'outline':
        return (
          <OutlineStep
            outline={editor.outline}
            outlineLength={editor.outlineLength}
            isLoading={editor.isGeneratingOutline}
            selectedTitle={editor.selectedTitle}
            customTitle={editor.customTitle}
            onLengthChange={editor.setOutlineLength}
            onRegenerate={editor.generateOutline}
            onAddSection={editor.addSection}
            onRemoveSection={editor.removeSection}
            onUpdateSection={editor.updateSection}
            onReorderSections={editor.reorderSections}
            onConfirm={editor.expandAll}
          />
        )

      case 'writing':
      case 'done':
        return (
          <WritingStep
            outline={editor.outline}
            articleTitle={editor.customTitle.trim() || editor.selectedTitle}
            articleId={editor.articleId}
            expandedContent={editor.expandedContent}
            agentStatus={editor.agentStatus}
            expandingSections={editor.expandingSections}
            activeSectionRef={activeSectionRef}
            onExpandSection={editor.expandSection}
            onExpandAll={editor.expandAll}
            onUpdateSectionContent={(id, content) =>
              editor.updateExpandedContent(id, content)
            }
          />
        )
    }
  }

  const isFullscreen = editor.step === 'writing' || editor.step === 'done'

  return (
    <div
      className="flex flex-col bg-[var(--color-ivory)] overflow-hidden"
      style={{ height: 'calc(100vh - 3.75rem)' }}
    >
      {/* 顶部步骤进度条 */}
      <StepBar current={editor.step} />

      {/* 错误提示 */}
      {editor.error && (
        <div className="px-6 pt-3">
          <ErrorBanner message={editor.error} onClose={editor.clearError} />
        </div>
      )}

      {/* 主体：三栏布局 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左侧导航 */}
        <SideNav
          current={editor.step}
          outline={editor.outline}
          expandedContent={editor.expandedContent}
          agentStatus={editor.agentStatus}
          quota={quota}
          onSectionClick={id => {
            // 滚动到对应 section（通过 id 查找 DOM）
            const el = document.getElementById(`section-${id}`)
            el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }}
        />

        {/* 中间 AI 操作 / 写作区 */}
        <main
          className={[
            'flex flex-col overflow-hidden',
            isFullscreen ? 'flex-1' : 'flex-1',
          ].join(' ')}
        >
          {isFullscreen ? (
            // 写作阶段：全屏占满中间+右侧
            renderCenter()
          ) : (
            <div className="flex flex-1 overflow-hidden">
              {/* 中间操作区 */}
              <div className="flex-1 overflow-y-auto px-8">
                {renderCenter()}
              </div>

              {/* 右侧预览区 */}
              <div className="hidden w-72 shrink-0 overflow-y-auto border-l border-[var(--color-ivory-border)] bg-[var(--color-surface-warm)] p-6 xl:block">
                <p className="section-label-inline mb-4">预览</p>
                {editor.selectedTitle || editor.customTitle ? (
                  <div>
                    <h3 className="font-serif text-base font-bold text-[var(--color-ink)]">
                      {editor.customTitle.trim() || editor.selectedTitle}
                    </h3>
                    <div className="rule-divider-gold mt-2 mb-4" />
                  </div>
                ) : (
                  <p className="text-sm text-[var(--color-ink-faint)]">
                    选择标题后在此预览文章结构
                  </p>
                )}
                {editor.outline && (
                  <div className="space-y-2 text-sm">
                    <p className="text-[var(--color-ink-muted)]">{editor.outline.intro}</p>
                    <div className="space-y-1 pt-2">
                      {editor.outline.sections.map((s, i) => (
                        <div key={s.id} className="flex gap-2 text-[var(--color-ink-secondary)]">
                          <span className="shrink-0 font-mono text-[var(--color-gold)]">
                            {i + 1}.
                          </span>
                          <span>{s.title}</span>
                        </div>
                      ))}
                    </div>
                    <p className="pt-2 text-[var(--color-ink-muted)]">{editor.outline.conclusion}</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default function EditorPage() {
  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center text-[var(--color-ink-muted)]">加载中…</div>}>
      <EditorPageInner />
    </Suspense>
  )
}
