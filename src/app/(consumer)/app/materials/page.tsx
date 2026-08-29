'use client'

/**
 * Consumer materials page (upgrade plan task 7): /app/materials.
 *
 * Full material management page. <!-- The write page embeds only the drawer. -->
 */

import { useState } from 'react'

import { useConsumerMaterials } from '@/hooks/useConsumerMaterials'
import { MaterialCard } from '@/components/consumer/materials/MaterialCard'
import { MaterialSourceDetail } from '@/components/consumer/materials/MaterialSourceDetail'
import styles from '@/components/consumer/materials/consumer-materials.module.css'

export default function MaterialsPage() {
  const { loading, error, materials, excerpts, refresh, loadExcerpts } = useConsumerMaterials()
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null)
  const [selectedExcerpt, setSelectedExcerpt] = useState<string | null>(null)

  async function openDocument(documentId: string) {
    setSelectedDocument(documentId)
    await loadExcerpts(documentId)
  }

  return (
    <div className={styles.page}>
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
        <p>还没有素材。从一篇笔记、一段录音稿或一个链接开始。</p>
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
