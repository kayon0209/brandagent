'use client'

/**
 * Consumer draft autosave state machine (upgrade plan task 10).
 *
 * states: saved -> dirty -> saving -> saved
 *                    \-> conflict (server revision moved; local text kept)
 *                    \-> error    (network failed; local text kept, sessionStorage backup)
 *
 * Review fixes for the audit findings:
 * - flush() SERIALIZES saves: a call while a save is in flight chains
 *   after it (the previous code silently dropped the caller's payload);
 * - adopt reads the live revision via latestRevision() — the React state
 *   closure inside adoptCurrent always saw a stale revision and 409'd;
 * - the sessionStorage backup is now READ BACK on load when it is newer
 *   than the server draft (it used to be written and deleted, never read);
 * - load() failure surfaces as status 'error' instead of silent 'saved';
 * - beforeunload sends a keepalive fetch (the previous plain async fetch
 *   was cancelled on page exit despite claiming otherwise).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export type DraftSaveState = 'loading' | 'saved' | 'dirty' | 'saving' | 'conflict' | 'error'

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

interface BackupEntry {
  plainText: string
  document: { blocks: unknown[] }
  savedAt: number
}

function readBackup(projectId: string): BackupEntry | null {
  try {
    const raw = window.sessionStorage.getItem(BACKUP_KEY + projectId)
    return raw ? (JSON.parse(raw) as BackupEntry) : null
  } catch {
    return null
  }
}

function writeBackup(projectId: string, payload: { document: { blocks: unknown[] }; plainText: string }) {
  try {
    const entry: BackupEntry = { ...payload, savedAt: Date.now() }
    window.sessionStorage.setItem(BACKUP_KEY + projectId, JSON.stringify(entry))
  } catch {
    /* storage may be unavailable */
  }
}

function clearBackup(projectId: string) {
  try {
    window.sessionStorage.removeItem(BACKUP_KEY + projectId)
  } catch {
    /* storage may be unavailable */
  }
}

export function useConsumerDraft(projectId: string, api: ConsumerDraftApi) {
  const [status, setStatus] = useState<DraftSaveState>('loading')
  const [revision, setRevision] = useState(0)
  const [document, setDocument] = useState<{ blocks: unknown[] } | null>(null)
  const [plainText, setPlainText] = useState('')
  const [localPlainText, setLocalPlainText] = useState('')
  const [seedVersion, setSeedVersion] = useState(0)

  const revisionRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingRef = useRef<{ document: { blocks: unknown[] }; plainText: string } | null>(null)
  const flushChainRef = useRef<Promise<unknown>>(Promise.resolve())

  const load = useCallback(async () => {
    const draft = await api.getDraft(projectId)
    revisionRef.current = draft.revision
    setRevision(draft.revision)
    // a backup newer than the last flush beats the server copy: the user
    // typed past a failed save, and that text must not be silently lost
    const backup = readBackup(projectId)
    if (backup && backup.plainText !== draft.plain_text) {
      pendingRef.current = { document: backup.document, plainText: backup.plainText }
      setDocument(backup.document)
      setPlainText(draft.plain_text)
      setLocalPlainText(backup.plainText)
      setStatus('dirty')
    } else {
      pendingRef.current = null
      setDocument(draft.document)
      setPlainText(draft.plain_text)
      setLocalPlainText(draft.plain_text)
      setStatus('saved')
    }
    setSeedVersion(value => value + 1)
  }, [api, projectId])

  useEffect(() => {
    load().catch(() => {
      setStatus('error')
    })
  }, [load])

  const flush = useCallback(async () => {
    // serialize: a flush during an in-flight save chains after it instead
    // of returning early and dropping the caller's payload (audit P1)
    const run = flushChainRef.current.then(async () => {
      const pending = pendingRef.current
      if (!pending) return
      setStatus('saving')
      writeBackup(projectId, pending)
      try {
        const result = await api.saveDraft(projectId, {
          document: pending.document,
          plainText: pending.plainText,
          baseRevision: revisionRef.current,
        })
        revisionRef.current = result.revision
        setRevision(result.revision)
        // only clear the payload we actually saved; edits that arrived while
        // this request was in flight remain armed (lost-update fix)
        if (pendingRef.current === pending) {
          pendingRef.current = null
          setPlainText(pending.plainText)
          setDocument(pending.document)
          setStatus('saved')
          clearBackup(projectId)
        } else {
          // newer edits exist: keep them dirty and re-arm the debounce
          setStatus('dirty')
          if (timerRef.current) clearTimeout(timerRef.current)
          timerRef.current = setTimeout(() => {
            void flush()
          }, DEBOUNCE_MS)
        }
      } catch (error) {
        const code = (error as { code?: string })?.code
        if (code === 'REVISION_CONFLICT') {
          setStatus('conflict')
        } else {
          setStatus('error')
        }
        // local draft is intentionally kept; pendingRef stays armed for retry
      }
    })
    flushChainRef.current = run.catch(() => {})
    await run
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

  const latestRevision = useCallback(() => revisionRef.current, [])

  const saveKeepalive = useCallback(() => {
    // beforeunload cannot await: fire-and-forget keepalive so the last
    // keystrokes reach the server even as the tab closes
    const pending = pendingRef.current
    if (!pending) return
    try {
      void fetch(`/api/brandagent/api/v1/consumer/projects/${projectId}/draft`, {
        method: 'PUT',
        keepalive: true,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          document: pending.document,
          plainText: pending.plainText,
          baseRevision: revisionRef.current,
        }),
      })
      pendingRef.current = null
    } catch {
      /* keepalive failures surface via the backup on next load */
    }
  }, [projectId])

  useEffect(() => {
    const handler = () => {
      if (pendingRef.current) {
        saveKeepalive()
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => {
      window.removeEventListener('beforeunload', handler)
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [saveKeepalive])

  return {
    status,
    revision,
    document,
    plainText,
    localPlainText,
    seedVersion,
    markDirty,
    flush,
    resolveConflict,
    reload: load,
    latestRevision,
    saveKeepalive,
  }
}
