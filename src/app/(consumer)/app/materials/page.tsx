'use client'

// Clerk-protected, data-driven page: prerender has no session, so a
// static export would bake the interception shell (prod 404 root
// cause). Render per-request like the middleware expects.
export const dynamic = 'force-dynamic'


/**
 * Consumer materials page (upgrade plan task 7): /app/materials.
 *
 * Full material management: import (paste text) + read + trace to source.
 * The write page embeds only the drawer; this page owns the import flow
 * (audit finding: import/link existed in the hook but no page called it).
 */

import { useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { useConsumerMaterials } from '@/hooks/useConsumerMaterials'
import { MaterialCard } from '@/components/consumer/materials/MaterialCard'
import { MaterialSourceDetail } from '@/components/consumer/materials/MaterialSourceDetail'
import { buildMaterialsBackLink, MATERIALS_FROM_PARAM } from '@/lib/navigation/materials'
import styles from '@/components/consumer/materials/consumer-materials.module.css'

export default function MaterialsPage() {
  // useSearchParams needs a Suspense boundary in a statically-exported
  // client page (Next 14 build requirement)
  return (
    <Suspense fallback={<div className={styles.page}><p>正在打开素材…</p></div>}>
      <MaterialsPageInner />
    </Suspense>
  )
}

function MaterialsPageInner() {
  const { loading, error, materials, excerpts, refresh, loadExcerpts, importText } = useConsumerMaterials()
  const searchParams = useSearchParams()
  const fromProjectId = searchParams?.get(MATERIALS_FROM_PARAM)
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null)
  const [selectedExcerpt, setSelectedExcerpt] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importTextValue, setImportTextValue] = useState('')
  const [importName, setImportName] = useState('')
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState<string | null>(null)

  async function openDocument(documentId: string) {
    setSelectedDocument(documentId)
    await loadExcerpts(documentId)
  }

  async function submitImport() {
    if (!importTextValue.trim()) return
    setImporting(true)
    setImportMessage(null)
    try {
      const result = await importText(importTextValue, importName.trim() || '未命名素材')
      setImportTextValue('')
      setImportName('')
      setImportOpen(false)
      setImportMessage(
        result.status === 'duplicate'
          ? '这段内容之前导入过，没有重复入库。'
          : result.status === 'distilled'
            ? '素材已导入，可引用片段已就绪。'
            : '素材已导入，正在整理可引用片段。',
      )
    } catch (importError) {
      setImportMessage(importError instanceof Error ? importError.message : '导入失败，请重试。')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className={styles.page}>
      <nav aria-label="返回导航">
        <a href={buildMaterialsBackLink(fromProjectId)} data-testid="materials-back">
          {fromProjectId ? '回到写作' : '回到我的写作'}
        </a>
      </nav>
      <h1>素材</h1>

      {error && (
        <div role="alert">
          <p>处理失败：{error.message}</p>
          <button type="button" onClick={() => void refresh()}>
            重试
          </button>
        </div>
      )}

      {loading && <p>正在处理你的素材…</p>}

      {/* the honest empty state only renders when loading is done AND there
          is no failure — never stack both (audit finding) */}
      {!loading && !error && materials.length === 0 && (
        <p>还没有素材。粘贴一段文字开始第一次导入。</p>
      )}

      <button type="button" className="consumer-primary-button" onClick={() => setImportOpen(previous => !previous)}>
        {importOpen ? '收起导入' : '导入素材'}
      </button>
      {importMessage && <p role="status">{importMessage}</p>}

      {importOpen && (
        <section className={styles.state}>
          <label htmlFor="import-name" className="consumer-field-label">
            素材名称
          </label>
          <input
            id="import-name"
            className="consumer-text-input"
            value={importName}
            onChange={event => setImportName(event.target.value)}
            placeholder="例如：播客第 3 期录音稿"
          />
          <label htmlFor="import-text" className="consumer-field-label">
            素材内容
          </label>
          <textarea
            id="import-text"
            className="consumer-text-input"
            rows={6}
            value={importTextValue}
            onChange={event => setImportTextValue(event.target.value)}
            placeholder="粘贴笔记、文章或对话记录…"
          />
          <button
            type="button"
            className="consumer-primary-button"
            disabled={importing || !importTextValue.trim()}
            onClick={() => void submitImport()}
          >
            {importing ? '正在导入…' : '导入这段内容'}
          </button>
        </section>
      )}

      <ul className={styles.documentList}>
        {materials.map(material => (
          <li key={material.document_id}>
            <button type="button" onClick={() => void openDocument(material.document_id)}>
              {material.document_name}
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
