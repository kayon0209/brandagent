'use client'

/**
 * Consumer draft autosave state machine (upgrade plan task 10).
 *
 * states: saved -> dirty -> saving -> saved
 *                    \-> conflict (server revision moved; local text kept)
 *                    \-> error    (network failed; local text kept, sessionStorage backup)
 *
 * Saves are debounced 800ms; "已保存" is only shown after the SERVER
 * confirms the new revision.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type DraftSaveState = 'saved' | 'dirty' | 'saving' | 'conflict' | 'error'

export interface ConsumerDraftApi {
  getDraft(projectId: string): Promise<{
    task_id: string
    revision: number
    document: { blocks: unknown[] }
    plain_text: string
  }>
  saveDraft(
    projectId: string,
    payload: { document: { blocks: unknown[] }; plainText: string; baseRevision: number },
  ): Promise<{ revision: number }>
  proposeSuggestion(...args: unknown[]): Promise<unknown>
  acceptSuggestion(...args: unknown[]): Promise<unknown>
}

const DEBOUNCE_MS = 800
const BACKUP_KEY = 'brandagent:draft-backup:'

export function useConsumerDraft(projectId: string, api: ConsumerDraftApi) {
  const [status, setStatus] = useState<DraftSaveState>('saved')
  const [revision, setRevision] = useState(0)
  const [document, setDocument] = useState<{ blocks: unknown[] } | null>(null)
  const [plainText, setPlainText] = useState('')
  const [localPlainText, setLocalPlainText] = useState('')

  const revisionRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingRef = useRef<{ document: { blocks: unknown[] }; plainText: string } | null>(null)
  const flushingRef = useRef(false)

  const load = useCallback(async () => {
    const draft = await api.getDraft(projectId)
    revisionRef.current = draft.revision
    setRevision(draft.revision)
    setDocument(draft.document)
    setPlainText(draft.plain_text)
    setLocalPlainText(draft.plain_text)
    setStatus('saved')
    try {
      window.sessionStorage.removeItem(BACKUP_KEY + projectId)
    } catch {
      /* storage may be unavailable */
    }
  }, [api, projectId])

  useEffect(() => {
    void load()
  }, [load])

  const flush = useCallback(async () => {
    if (flushingRef.current) return
    const pending = pendingRef.current
    if (!pending) return
    flushingRef.current = true
    setStatus('saving')
    try {
      window.sessionStorage.setItem(BACKUP_KEY + projectId, pending.plainText)
    } catch {
      /* storage may be unavailable */
    }
    try {
      const result = await api.saveDraft(projectId, {
        document: pending.document,
        plainText: pending.plainText,
        baseRevision: revisionRef.current,
      })
      revisionRef.current = result.revision
      setRevision(result.revision)
      setPlainText(pending.plainText)
      setDocument(pending.document)
      pendingRef.current = null
      setStatus('saved')
      try {
        window.sessionStorage.removeItem(BACKUP_KEY + projectId)
      } catch {
        /* storage may be unavailable */
      }
    } catch (error) {
      const code = (error as { code?: string })?.code
      if (code === 'REVISION_CONFLICT') {
        setStatus('conflict')
      } else {
        setStatus('error')
      }
      // local draft is intentionally kept; pendingRef stays armed for retry
    } finally {
      flushingRef.current = false
    }
  }, [api, projectId])

  const markDirty = useCallback(
    (document: { blocks: unknown[] }, text: string) => {
      pendingRef.current = { document, plainText: text }
      setLocalPlainText(text)
      setStatus('dirty')
      if (timerRef.current) clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => {
        void flush()
      }, DEBOUNCE_MS)
    },
    [flush],
  )

  const resolveConflict = useCallback(async () => {
    await load()
  }, [load])

  useEffect(() => {
    // flush before unload: sendBeacon is unreliable, so fire the fetch now
    const handler = () => {
      if (pendingRef.current && !flushingRef.current) {
        void flush()
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => {
      window.removeEventListener('beforeunload', handler)
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [flush])

  return {
    status,
    revision,
    document,
    plainText,
    localPlainText,
    markDirty,
    flush,
    resolveConflict,
    reload: load,
  }
}
