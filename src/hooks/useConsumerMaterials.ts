'use client'

/**
 * Consumer materials state hook (upgrade plan task 7).
 *
 * Loads the real material list through the BFF; link states always come from
 * API responses, never from optimistic local flags.
 */

import { useCallback, useEffect, useState } from 'react'

import {
  listMaterials,
  getMaterialExcerpts,
  importMaterialText,
  linkMaterialToProject,
  type MaterialListItem,
  type MaterialImportResult,
} from '@/lib/api/consumer'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import type { ConsumerMaterialExcerpt, MaterialLinkState } from '@/types/consumer.types'
import { newIdempotencyKey } from '@/lib/idempotency'

export { type MaterialLinkState as MATERIAL_LINK_STATES }

export interface ConsumerMaterialsState {
  loading: boolean
  error: BrandFlowApiError | null
  materials: MaterialListItem[]
  excerpts: ConsumerMaterialExcerpt[]
  linkStates: Record<string, MaterialLinkState>
  refresh: () => Promise<void>
  importText: (text: string, name: string) => Promise<MaterialImportResult>
  linkToProject: (projectId: string, excerptId: string) => Promise<void>
  /** Merge SERVER-known link states (e.g. from the project view) so the
   * drawer shows real associations, not just this session's actions. */
  seedLinkStates: (states: Record<string, MaterialLinkState>) => void
  loadExcerpts: (documentId: string) => Promise<void>
  loadAllExcerpts: () => Promise<void>
}


export function useConsumerMaterials(): ConsumerMaterialsState {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<BrandFlowApiError | null>(null)
  const [materials, setMaterials] = useState<MaterialListItem[]>([])
  const [excerpts, setExcerpts] = useState<ConsumerMaterialExcerpt[]>([])
  const [linkStates, setLinkStates] = useState<Record<string, MaterialLinkState>>({})

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setError(null)
      const response = await listMaterials()
      setMaterials(response.items)
    } catch (caught) {
      setError(caught as BrandFlowApiError)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const loadExcerpts = useCallback(async (documentId: string) => {
    try {
      setError(null)
      const response = await getMaterialExcerpts(documentId)
      setExcerpts(response.items)
    } catch (caught) {
      setError(caught as BrandFlowApiError)
    }
  }, [])

  const loadAllExcerpts = useCallback(async () => {
    /** Aggregate the workspace's ready excerpts for the write-page drawer
     * (the per-document loader overwrites, so it cannot fill a drawer). */
    try {
      setError(null)
      const documents = await listMaterials()
      const collected: ConsumerMaterialExcerpt[] = []
      for (const document of documents.items) {
        try {
          const response = await getMaterialExcerpts(document.document_id)
          collected.push(...response.items)
        } catch {
          /* a document still processing contributes no excerpts yet */
        }
      }
      setExcerpts(collected)
    } catch (caught) {
      setError(caught as BrandFlowApiError)
    }
  }, [])

  const importText = useCallback(async (text: string, name: string) => {
    const result = await importMaterialText(text, name, newIdempotencyKey())
    await refresh()
    return result
  }, [refresh])

  const linkToProject = useCallback(async (projectId: string, excerptId: string) => {
    setLinkStates(previous => ({ ...previous, [excerptId]: 'linking' }))
    try {
      await linkMaterialToProject(projectId, excerptId, newIdempotencyKey())
      // Status comes from the API response completing, not from optimism.
      setLinkStates(previous => ({ ...previous, [excerptId]: 'linked' }))
    } catch (caught) {
      setLinkStates(previous => ({ ...previous, [excerptId]: 'failed' }))
      throw caught
    }
  }, [])

  const seedLinkStates = useCallback((states: Record<string, MaterialLinkState>) => {
    // server truth only; never downgrade a failed/linking state mid-action
    setLinkStates(previous => ({ ...states, ...previous }))
  }, [])

  return {
    loading,
    error,
    materials,
    excerpts,
    linkStates,
    refresh,
    importText,
    linkToProject,
    seedLinkStates,
    loadExcerpts,
    loadAllExcerpts,
  }
}
