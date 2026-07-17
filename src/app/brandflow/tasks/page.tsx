'use client'

import { FormEvent, useEffect, useMemo, useState } from 'react'
import { useBrandFlow } from '@/hooks/useBrandFlow'
import { statusLabel, channelLabel } from '@/lib/brandflow-labels'
import { AlertTriangle, ChevronRight, FileText, Loader2, RefreshCw, Plus } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/styles/brandflow'

export default function BrandFlowTasks() {
  const flow = useBrandFlow()
  const [creating, setCreating] = useState(false)
  const searchParams = useSearchParams()

  useEffect(() => {
    if (searchParams.get('create') === 'true') {
      setCreating(true)
    }
  }, [searchParams])

  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载任务列表</h1>
        <p>从工作区获取最新任务状态。</p>
      </main>
    )
  }

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div>
          <span>BrandFlow / Tasks</span>
          <h1>内容任务</h1>
        </div>
        {!creating && (
          <button className={styles.primary} onClick={() => setCreating(true)}>
            <Plus size={16} /> 创建任务
          </button>
        )}
      </header>
      {flow.error && <RecoveryBanner error={flow.error} onRetry={flow.refreshTasks} />}
      {creating ? (
        <CreateTask
          onCancel={() => setCreating(false)}
          onCreate={async (body) => {
            const task = await flow.command<{ task_id: string }>('/api/v1/tasks', body)
            setCreating(false)
            window.location.href = `/brandflow/tasks/${task.task_id}`
          }}
        />
      ) : flow.tasks.length === 0 ? (
        <section className={styles.empty}>
          <div><FileText size={32} /></div>
          <h2>还没有内容任务</h2>
          <p>创建首个结构化 Brief。系统会明确显示取证、审批、失败与恢复状态。</p>
          <button className={styles.primary} onClick={() => setCreating(true)}>创建首个任务</button>
        </section>
      ) : (
        <section className={styles.taskList} aria-label="任务列表">
          {flow.tasks.map((task) => (
            <Link
              key={task.task_id}
              href={`/brandflow/tasks/${task.task_id}`}
              className={styles.taskRow}
            >
              <span className={styles.statusDot} data-status={task.status} />
              <span>
                <strong>{task.title}</strong>
                <small>
                  {statusLabel[task.status] ?? task.status} · {task.selected_channels.length} 个渠道
                </small>
              </span>
              <ChevronRight size={16} />
            </Link>
          ))}
        </section>
      )}
    </main>
  )
}

function RecoveryBanner({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const accessError = error instanceof BrandFlowApiError && (error.status === 401 || error.status === 403)
  return (
    <div className={styles.recovery} role="alert">
      <AlertTriangle />
      <span>
        <b>{accessError ? '当前登录身份无法访问此工作区' : '服务暂时不可用'}</b>
        <small>{error.message}</small>
      </span>
      <button onClick={onRetry}>{accessError ? '重新验证' : '重试'}</button>
    </div>
  )
}

const REQUIRED_BRIEF_FIELDS = ['title', 'topic', 'brandId', 'productId', 'audience', 'objective', 'action']

const brandOptions = [
  { id: 'default', label: '默认品牌' },
  { id: 'brand_acme', label: 'Acme Corp' },
  { id: 'brand_techflow', label: 'TechFlow' },
]
const productOptions = [
  { id: 'prod_default', label: '默认产品' },
  { id: 'prod_platform', label: 'BrandFlow 平台' },
  { id: 'prod_api', label: 'BrandFlow API' },
]

function getSectionFields(section: number): string[] {
  switch (section) {
    case 0: return ['title', 'topic']
    case 1: return ['audience', 'objective', 'action']
    case 2: return ['brandId', 'productId', 'keyProducts', 'keyFacts']
    case 3: return ['requiredFacts', 'sourceLinks']
    case 4: return ['brandTone', 'styleNotes']
    case 5: return ['forbiddenClaims']
    case 6: return ['channels']
    case 7: return []
    default: return []
  }
}

function CreateTask({
  onCancel,
  onCreate,
}: {
  onCancel: () => void
  onCreate: (body: unknown) => Promise<void>
}) {
  const [saving, setSaving] = useState(false)
  const [section, setSection] = useState(0)
  const [form, setForm] = useState({
    title: '',
    topic: '',
    brandId: '',
    productId: '',
    audience: '',
    objective: '',
    action: '',
    channels: ['wechat_website'],
    keyProducts: '',
    keyFacts: '',
    requiredFacts: '',
    sourceLinks: '',
    brandTone: '',
    styleNotes: '',
    forbiddenClaims: '',
  })
  const sections = [
    '基本信息',
    '受众与目标',
    '产品与关键信息',
    '必需事实与来源',
    '品牌语气',
    '禁止声明',
    '渠道选择',
    '最终复核',
  ]

  const sectionCompleteness = useMemo(() => {
    return sections.map((_, index) => {
      const fields = getSectionFields(index)
      const filled = fields.filter((f) => {
        const val = (form as Record<string, unknown>)[f]
        if (Array.isArray(val)) return val.length > 0
        return val !== null && val !== undefined && String(val).trim() !== ''
      }).length
      if (filled === 0) return 'empty'
      if (filled === fields.length) return 'complete'
      return 'partial'
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form])

  const canSubmit = useMemo(
    () => REQUIRED_BRIEF_FIELDS.every((key) => {
      const val = (form as Record<string, unknown>)[key]
      if (Array.isArray(val)) return val.length > 0
      return val !== null && val !== undefined && String(val).trim() !== ''
    }),
    [form]
  )

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setSaving(true)
    try {
      await onCreate({
        title: form.title,
        selected_channels: form.channels,
        brief: {
          topic: form.topic,
          brand_id: form.brandId,
          product_id: form.productId,
          target_audience: form.audience,
          publishing_objective: form.objective,
          primary_channel: form.channels[0],
          desired_audience_action: form.action,
          key_products: form.keyProducts,
          key_facts: form.keyFacts,
          required_facts: form.requiredFacts,
          source_links: form.sourceLinks.split('\n').filter(Boolean),
          brand_tone: form.brandTone,
          style_notes: form.styleNotes,
          forbidden_claims: form.forbiddenClaims.split('\n').filter(Boolean),
        },
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className={styles.create} onSubmit={submit}>
      <header>
        <div>
          <small>分步填写</small>
          <h2>创建内容任务</h2>
          <p>按八个章节填写结构化 Brief，技术配置不进入内容流程。</p>
        </div>
        <button type="button" className={styles.back} onClick={onCancel}>取消</button>
      </header>
      <div className={styles.sectionNav}>
        {sections.map((label, index) => (
          <button type="button" key={label} data-active={section === index} onClick={() => setSection(index)}>
            <span>{index + 1}</span>
            {label}
            <span className={styles.sectionDot} data-state={sectionCompleteness[index]}>
              {sectionCompleteness[index] === 'complete' ? '\u2713' : sectionCompleteness[index] === 'partial' ? '\u25CF' : '\u25CB'}
            </span>
          </button>
        ))}
      </div>
      <div className={styles.fields}>
        {section === 0 && (
          <>
            <Field label="任务名称" value={form.title} onChange={(title) => setForm({ ...form, title })} />
            <Field label="主题" value={form.topic} onChange={(topic) => setForm({ ...form, topic })} />
          </>
        )}
        {section === 1 && (
          <>
            <Field label="目标受众" value={form.audience} onChange={(audience) => setForm({ ...form, audience })} />
            <Field label="发布目标" value={form.objective} onChange={(objective) => setForm({ ...form, objective })} />
            <Field label="期望受众行动" value={form.action} onChange={(action) => setForm({ ...form, action })} />
          </>
        )}
        {section === 2 && (
          <>
            <Field label="品牌 ID" value={form.brandId} onChange={(brandId) => setForm({ ...form, brandId })} selectOptions={brandOptions} />
            <Field label="产品 ID" value={form.productId} onChange={(productId) => setForm({ ...form, productId })} selectOptions={productOptions} />
            <Field label="关键产品" value={form.keyProducts} onChange={(keyProducts) => setForm({ ...form, keyProducts })} multiline />
            <Field label="关键事实" value={form.keyFacts} onChange={(keyFacts) => setForm({ ...form, keyFacts })} multiline />
          </>
        )}
        {section === 3 && (
          <>
            <Field label="必需事实" value={form.requiredFacts} onChange={(requiredFacts) => setForm({ ...form, requiredFacts })} multiline />
            <Field label="来源链接" value={form.sourceLinks} onChange={(sourceLinks) => setForm({ ...form, sourceLinks })} multiline placeholder="权威来源链接，每行一个" />
          </>
        )}
        {section === 4 && (
          <>
            <label className={styles.field}>
              <span>品牌语气<em>必填</em></span>
              <select value={form.brandTone} onChange={(event) => setForm({ ...form, brandTone: event.target.value })} required>
                <option value="">请选择</option>
                <option value="专业权威">专业权威</option>
                <option value="亲切友好">亲切友好</option>
                <option value="创新科技">创新科技</option>
                <option value="温情关怀">温情关怀</option>
              </select>
            </label>
            <Field label="风格说明" value={form.styleNotes} onChange={(styleNotes) => setForm({ ...form, styleNotes })} multiline />
          </>
        )}
        {section === 5 && (
          <>
            <Field label="禁止声明" value={form.forbiddenClaims} onChange={(forbiddenClaims) => setForm({ ...form, forbiddenClaims })} multiline placeholder="每行一条禁止声明…" />
          </>
        )}
        {section === 6 && (
          <fieldset>
            <legend>输出渠道</legend>
            {['wechat_website', 'xiaohongshu', 'video_script_60s', 'marketing_email'].map((channel) => (
              <label key={channel}>
                <input
                  type="checkbox"
                  checked={form.channels.includes(channel)}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      channels: event.target.checked
                        ? [...form.channels, channel]
                        : form.channels.filter((item) => item !== channel),
                    })
                  }
                />
                {channelLabel(channel)}
              </label>
            ))}
          </fieldset>
        )}
        {section === 7 && (
          <div className={styles.summary}>
            <h3>复核内容</h3>
            <dl>
              <dt>任务名称</dt><dd>{form.title || '—'}</dd>
              <dt>主题</dt><dd>{form.topic || '—'}</dd>
              <dt>目标受众</dt><dd>{form.audience || '—'}</dd>
              <dt>发布目标</dt><dd>{form.objective || '—'}</dd>
              <dt>期望受众行动</dt><dd>{form.action || '—'}</dd>
              <dt>品牌 ID</dt><dd>{form.brandId || '—'}</dd>
              <dt>产品 ID</dt><dd>{form.productId || '—'}</dd>
              <dt>关键产品</dt><dd>{form.keyProducts || '—'}</dd>
              <dt>关键事实</dt><dd>{form.keyFacts || '—'}</dd>
              <dt>必需事实</dt><dd>{form.requiredFacts || '—'}</dd>
              <dt>来源链接</dt><dd>{form.sourceLinks || '—'}</dd>
              <dt>品牌语气</dt><dd>{form.brandTone || '—'}</dd>
              <dt>风格说明</dt><dd>{form.styleNotes || '—'}</dd>
              <dt>禁止声明</dt><dd>{form.forbiddenClaims || '—'}</dd>
              <dt>输出渠道</dt><dd>{form.channels.map(channelLabel).join('、') || '—'}</dd>
            </dl>
            <button className={styles.primary} disabled={!canSubmit || saving}>
              {saving ? '正在创建…' : '提交任务'}
            </button>
          </div>
        )}
      </div>
      <footer>
        <span>{section + 1} / {sections.length} 章节</span>
        {section < 7 ? (
          <button type="button" className={styles.primary} onClick={() => setSection(section + 1)}>继续</button>
        ) : null}
      </footer>
    </form>
  )
}

function Field({
  label,
  value,
  onChange,
  multiline,
  placeholder,
  selectOptions,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  multiline?: boolean
  placeholder?: string
  selectOptions?: { id: string; label: string }[]
}) {
  if (selectOptions) {
    const newItemLabel = label.includes('品牌') ? '新建品牌' : label.includes('产品') ? '新建产品' : `新建${label.replace(/\s*ID\s*/, '')}`
    return (
      <label className={styles.field}>
        <span>{label}<em>必填</em></span>
        <select value={value} onChange={(event) => onChange(event.target.value)} required>
          <option value="">请选择</option>
          {selectOptions.map((opt) => (
            <option key={opt.id} value={opt.id}>{opt.label}</option>
          ))}
          <option value="__new__">{newItemLabel}</option>
        </select>
      </label>
    )
  }
  if (multiline) {
    return (
      <label className={styles.field}>
        <span>{label}<em>必填</em></span>
        <textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          required
        />
      </label>
    )
  }
  return (
    <label className={styles.field}>
      <span>{label}<em>必填</em></span>
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} required />
    </label>
  )
}
