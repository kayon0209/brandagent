'use client'

// Clerk-protected, data-driven page: prerender has no session, so a
// static export would bake the interception shell (prod 404 root
// cause). Render per-request like the middleware expects.
export const dynamic = 'force-dynamic'


/**
 * Consumer materials page (upgrade plan task 7): /app/materials.
 *
 * round-3g C — 档案感取材库: two-column rich cards (type chip / linked
 * count / import date / citation state / BA-M number), filter chips
 * (全部/文字/文件/链接), local sort (最近导入/名称), and THREE real import
 * entries (粘贴文字 / 上传文件 / 保存一个链接 — the link fetch happens on
 * the server; failures speak honestly). Empty-state hero preserved.
 */

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useMemo, useState } from 'react'

import { useConsumerMaterials } from '@/hooks/useConsumerMaterials'
import { importMaterialFile, importMaterialUrl, type MaterialListItem } from '@/lib/api/consumer'
import type { MaterialImportKind } from '@/types/consumer.types'
import { MaterialCard } from '@/components/consumer/materials/MaterialCard'
import { MaterialSourceDetail } from '@/components/consumer/materials/MaterialSourceDetail'
import { ConsumerNav } from '@/components/consumer/ConsumerNav'
import { buildMaterialsBackLink, MATERIALS_FROM_PARAM } from '@/lib/navigation/materials'
import { newIdempotencyKey } from '@/lib/idempotency'
import styles from '@/components/consumer/materials/consumer-materials.module.css'

const KIND_LABELS: Record<MaterialImportKind, string> = { text: '文字', file: '文件', link: '链接' }
type FilterKind = 'all' | MaterialImportKind
type SortKind = 'recent' | 'recent_used' | 'name'

/** §5 numbering: BA-M-XXXX, display-layer only — a stable hash of the
 * document id; monotonic per workspace is NOT required by the spec, just
 * distinct + 4 digits. */
function materialNumber(documentId: string): string {
  let hash = 0
  for (let i = 0; i < documentId.length; i += 1) {
    hash = (hash * 31 + documentId.charCodeAt(i)) >>> 0
  }
  return `BA-M-${String(hash % 10000).padStart(4, '0')}`
}

function chineseDate(iso?: string): string {
  if (!iso) return '—'
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return iso.slice(0, 10)
  return `${m[1]} 年 ${Number(m[2])} 月 ${Number(m[3])} 日`
}

export default function MaterialsPage() {
  // useSearchParams needs a Suspense boundary in a statically-exported
  // client page (Next build requirement)
  return (
    <Suspense fallback={<div className={styles.page}><p>正在打开素材…</p></div>}>
      <MaterialsPageInner />
    </Suspense>
  )
}

function MaterialsPageInner() {
  const { loading, error, materials, excerpts, refresh, loadExcerpts, loadAllExcerpts, importText } = useConsumerMaterials()
  const searchParams = useSearchParams()
  const fromProjectId = searchParams?.get(MATERIALS_FROM_PARAM)
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null)
  const [selectedExcerpt, setSelectedExcerpt] = useState<string | null>(null)

  // round-3g C2: filter + sort live entirely on the client (the list is
  // small; server ordering stays created_at DESC)
  const [filter, setFilter] = useState<FilterKind>('all')
  const [sort, setSort] = useState<SortKind>('recent')

  // C3: three import modes with independent open state — one visible at a
  // time keeps the panel honest about what the user is doing
  const [importMode, setImportMode] = useState<'none' | 'text' | 'file' | 'link'>('none')
  const [importTextValue, setImportTextValue] = useState('')
  const [importName, setImportName] = useState('')
  const [importUrl, setImportUrl] = useState('')
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState<string | null>(null)

  const visibleMaterials = useMemo(() => {
    const filtered = filter === 'all' ? materials : materials.filter(item => item.document_type === filter)
    const sorted = [...filtered]
    if (sort === 'name') {
      sorted.sort((a, b) => a.document_name.localeCompare(b.document_name, 'zh'))
    } else if (sort === 'recent_used') {
      // round-3g C2: most recently cited first; never-cited materials sink
      // below any cited one (last_used_at is null until a link happens)
      sorted.sort((a, b) => {
        const ta = a.last_used_at ? new Date(a.last_used_at).getTime() : -Infinity
        const tb = b.last_used_at ? new Date(b.last_used_at).getTime() : -Infinity
        return tb - ta
      })
    }
    // 'recent' = server order (created_at DESC) — keep as-is
    return sorted
  }, [materials, filter, sort])

  async function openDocument(documentId: string) {
    setSelectedDocument(documentId)
    await loadExcerpts(documentId)
  }

  async function submitTextImport() {
    if (!importTextValue.trim()) return
    setImporting(true)
    setImportMessage(null)
    try {
      const result = await importText(importTextValue, importName.trim() || '未命名素材')
      await afterImport(result.status, '素材已导入。')
    } catch (importError) {
      setImportMessage(importError instanceof Error ? importError.message : '导入失败，请重试。')
    } finally {
      setImporting(false)
    }
  }

  /** C3 file entry: the browser reads the file (txt/md), the upload
   * endpoint stamps type=file + original filename. PDFs are refused by the
   * server's allowlist with an honest message — surfaced as-is. */
  async function submitFileImport(file: File | null) {
    if (!file) return
    setImporting(true)
    setImportMessage(null)
    try {
      const content = await file.text()
      const { importMaterialFile: upload } = await import('@/lib/api/consumer')
      const result = await upload(file.name, content, newIdempotencyKey())
      await afterImport(result.status, `文件「${file.name}」已收进素材库。`)
    } catch (importError) {
      setImportMessage(importError instanceof Error ? importError.message : '文件导入失败，请重试。')
    } finally {
      setImporting(false)
    }
  }

  /** C3 link entry: server fetches the page; failures speak honestly and
   * nothing fake is imported. */
  async function submitLinkImport() {
    const trimmed = importUrl.trim()
    if (!trimmed) return
    setImporting(true)
    setImportMessage(null)
    try {
      const result = await importMaterialUrl(trimmed, newIdempotencyKey())
      await afterImport(result.status, `链接已保存，来源：${trimmed}`)
    } catch (importError) {
      setImportMessage(importError instanceof Error ? importError.message : '链接保存失败，请重试。')
    } finally {
      setImporting(false)
    }
  }

  async function afterImport(status: string, successCopy: string) {
    setImportTextValue('')
    setImportName('')
    setImportUrl('')
    setImportMode('none')
    if (status === 'duplicate') {
      setImportMessage('这段内容之前收过，没有重复入库。')
    } else if (status === 'distilled') {
      setImportMessage(`${successCopy} 可引用片段已就绪。`)
    } else {
      setImportMessage(`${successCopy} 正在整理可引用片段。`)
    }
    if (status !== 'duplicate') {
      // keep the write-page drawer in sync (N1: it renders from excerpts)
      await loadAllExcerpts()
    }
  }

  return (
    <div className={styles.page}>
      <ConsumerNav active="materials" />
      {fromProjectId && (
        <Link
          href={buildMaterialsBackLink(fromProjectId)}
          data-testid="materials-back"
          className={styles.materialsBackInline}
        >
          ← 回到写作
        </Link>
      )}

      {!loading && !error && materials.length === 0 ? (
        <section className={styles.materialEmpty} data-testid="material-empty-state">
          <h1 className={styles.materialEmptyTitle}>建立你的素材库</h1>
          <p className={styles.materialEmptyBody}>
            收进笔记、采访稿、历史文章或参考链接。生成内容时，你可以选择引用哪些素材——AI 只在这些素材上发挥。
          </p>
          {/* round-3g C3: three import entries available from the empty state */}
          <ImportEntryRow mode={importMode} onModeChange={setImportMode} />
          {importMode === 'text' && (
            <div className={styles.materialImportPanel}>
              <ImportForm
                name={importName}
                value={importTextValue}
                busy={importing}
                onNameChange={setImportName}
                onValueChange={setImportTextValue}
                onSubmit={() => void submitTextImport()}
              />
            </div>
          )}
          {importMode === 'file' && (
            <div className={styles.materialImportPanel}>
              <FileImportPanel busy={importing} onFile={file => void submitFileImport(file)} />
            </div>
          )}
          {importMode === 'link' && (
            <div className={styles.materialImportPanel}>
              <LinkImportPanel
                busy={importing}
                url={importUrl}
                onUrlChange={setImportUrl}
                onSubmit={() => void submitLinkImport()}
              />
            </div>
          )}
          <ul className={styles.materialTrust}>
            <li>导入的原文始终保留，不会自动改写。</li>
            <li>生成内容里可点开每条引用的来源原文。</li>
            <li>素材只在你选择时参与生成。</li>
          </ul>
        </section>
      ) : (
        <h1>素材</h1>
      )}

      {error && (
        <div role="alert">
          <p>处理失败：{error.message}</p>
          <button type="button" onClick={() => void refresh()}>
            重试
          </button>
        </div>
      )}

      {loading && <p>正在处理你的素材…</p>}

      {!loading && !error && materials.length > 0 && (
        <>
          <ImportEntryRow mode={importMode} onModeChange={setImportMode} />
          {importMode === 'text' && (
            <section className={styles.state}>
              <ImportForm
                name={importName}
                value={importTextValue}
                busy={importing}
                onNameChange={setImportName}
                onValueChange={setImportTextValue}
                onSubmit={() => void submitTextImport()}
              />
            </section>
          )}
          {importMode === 'file' && (
            <section className={styles.state}>
              <FileImportPanel busy={importing} onFile={file => void submitFileImport(file)} />
            </section>
          )}
          {importMode === 'link' && (
            <section className={styles.state}>
              <LinkImportPanel
                busy={importing}
                url={importUrl}
                onUrlChange={setImportUrl}
                onSubmit={() => void submitLinkImport()}
              />
            </section>
          )}
        </>
      )}
      {importMessage && <p role="status" data-testid="import-message">{importMessage}</p>}

      {/* C2: filter chips + sort — client-side, honest defaults */}
      {!loading && !error && materials.length > 0 && (
        <div className={styles.materialFilterRow} data-testid="material-filters">
          {(['all', 'text', 'file', 'link'] as FilterKind[]).map(kind => (
            <button
              key={kind}
              type="button"
              className={filter === kind ? styles.styleTabActive : styles.styleTab}
              data-testid={`filter-${kind}`}
              onClick={() => setFilter(kind)}
            >
              {kind === 'all' ? '全部' : KIND_LABELS[kind]}
            </button>
          ))}
          <select
            aria-label="排序方式"
            className="consumer-text-input"
            style={{ width: 130, marginLeft: 'auto' }}
            value={sort}
            onChange={event => setSort(event.target.value as SortKind)}
          >
            <option value="recent">最近导入</option>
            <option value="recent_used">最近引用</option>
            <option value="name">名称</option>
          </select>
        </div>
      )}

      {/* C1: two-column rich cards; whole card opens the excerpt view */}
      <ul className={styles.materialCardGrid} data-testid="material-card-grid">
        {visibleMaterials.map(material => (
          <li key={material.document_id}>
            <button
              type="button"
              className={styles.materialRichCard}
              data-testid="material-rich-card"
              onClick={() => void openDocument(material.document_id)}
            >
              <span className={styles.materialCardNumber}>{materialNumber(material.document_id)}</span>
              <span className={styles.materialKindChip} data-kind={material.document_type}>
                {KIND_LABELS[material.document_type]}
              </span>
              <strong className={styles.materialCardTitle}>{material.document_name}</strong>
              {material.excerpt_preview && (
                <span className={styles.materialCardExcerpt}>{material.excerpt_preview}</span>
              )}
              {material.source_url && (
                <span className={styles.materialCardSource} title={material.source_url}>
                  来源：{material.source_url.slice(0, 42)}{material.source_url.length > 42 ? '…' : ''}
                </span>
              )}
              <span className={styles.materialCardMetaRow}>
                {chineseDate(material.created_at)}
                {material.excerpt_count > 0 ? ` · 已引用 ${material.excerpt_count} 次` : ' · 尚无引用'}
                {(material.linked_projects_count ?? 0) > 0 ? ` · 关联 ${material.linked_projects_count} 个项目` : ''}
              </span>
              <span className={styles.materialCardOpen} aria-hidden>→</span>
            </button>
          </li>
        ))}
      </ul>

      {selectedDocument && (
        <section className="consumer-materials-excerpts">
          <h2>可引用片段</h2>
          {excerpts.map(excerpt => (
            <div key={excerpt.excerpt_id}>
              <MaterialCard excerpt={excerpt} linkState="unlinked" />
              <button type="button" onClick={() => setSelectedExcerpt(excerpt.excerpt_id)}>
                查看完整来源
              </button>
              {selectedExcerpt === excerpt.excerpt_id && <MaterialSourceDetail excerpt={excerpt} />}
            </div>
          ))}
        </section>
      )}
    </div>
  )
}

/** round-3g C3: the three import entries (one visible panel at a time). */
function ImportEntryRow({
  mode,
  onModeChange,
}: {
  mode: 'none' | 'text' | 'file' | 'link'
  onModeChange(mode: 'none' | 'text' | 'file' | 'link'): void
}) {
  return (
    <div className={styles.materialImportRow} data-testid="import-entries" role="group" aria-label="导入方式">
      <button
        type="button"
        className="consumer-primary-button"
        data-testid="import-entry-text"
        style={{ alignSelf: 'flex-start' }}
        onClick={() => onModeChange(mode === 'text' ? 'none' : 'text')}
      >
        {mode === 'text' ? '收起' : '粘贴文字'}
      </button>
      <button
        type="button"
        className={mode === 'file' ? 'consumer-primary-button' : styles.materialImportAlt}
        data-testid="import-entry-file"
        style={{ alignSelf: 'flex-start' }}
        onClick={() => onModeChange(mode === 'file' ? 'none' : 'file')}
      >
        {mode === 'file' ? '收起' : '上传文件'}
      </button>
      <button
        type="button"
        className={mode === 'link' ? 'consumer-primary-button' : styles.materialImportAlt}
        data-testid="import-entry-link"
        style={{ alignSelf: 'flex-start' }}
        onClick={() => onModeChange(mode === 'link' ? 'none' : 'link')}
      >
        {mode === 'link' ? '收起' : '保存一个链接'}
      </button>
    </div>
  )
}

function FileImportPanel({ busy, onFile }: { busy: boolean; onFile(file: File): void }) {
  return (
    <div>
      <label className="consumer-field-label" htmlFor="import-file">
        选择文件（当前支持 txt / md 文本文件）
      </label>
      <input
        id="import-file"
        type="file"
        accept=".txt,.md,text/plain,text/markdown"
        disabled={busy}
        data-testid="import-file-input"
        onChange={event => {
          const file = event.target.files?.[0] ?? null
          if (file) onFile(file)
          event.target.value = ''
        }}
      />
      {busy && <p role="status" className={styles.generateProgress}>正在收进文件…</p>}
    </div>
  )
}

function LinkImportPanel({
  busy,
  url,
  onUrlChange,
  onSubmit,
}: {
  busy: boolean
  url: string
  onUrlChange(url: string): void
  onSubmit(): void
}) {
  return (
    <div>
      <label className="consumer-field-label" htmlFor="import-url">
        链接地址
      </label>
      <input
        id="import-url"
        className="consumer-text-input"
        value={url}
        placeholder="https://example.com/article"
        onChange={event => onUrlChange(event.target.value)}
      />
      <button
        type="button"
        className="consumer-primary-button"
        disabled={busy || !url.trim()}
        onClick={onSubmit}
      >
        {busy ? '正在抓取页面…' : '保存这个链接'}
      </button>
      <p className={styles.generateProgress}>保存后我们去抓取页面正文；抓不到时会如实告诉你，不会收进假正文。</p>
    </div>
  )
}

function ImportForm({
  name,
  value,
  busy,
  onNameChange,
  onValueChange,
  onSubmit,
}: {
  name: string
  value: string
  busy: boolean
  onNameChange(name: string): void
  onValueChange(value: string): void
  onSubmit(): void
}) {
  return (
    <>
      <label htmlFor="import-name" className="consumer-field-label">
        素材名称
      </label>
      <input
        id="import-name"
        className="consumer-text-input"
        value={name}
        onChange={event => onNameChange(event.target.value)}
        placeholder="例如：播客第 3 期录音稿"
      />
      <label htmlFor="import-text" className="consumer-field-label">
        素材内容
      </label>
      <textarea
        id="import-text"
        className="consumer-text-input"
        rows={6}
        value={value}
        onChange={event => onValueChange(event.target.value)}
        placeholder="粘贴笔记、文章或对话记录…"
      />
      <button
        type="button"
        className="consumer-primary-button"
        disabled={busy || !value.trim()}
        onClick={onSubmit}
      >
        {busy ? '正在导入…' : '导入这段内容'}
      </button>
    </>
  )
}
