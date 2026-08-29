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
  loadExcerpts: (documentId: string) => Promise<void>
}

function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
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

  return {
    loading,
    error,
    materials,
    excerpts,
    linkStates,
    refresh,
    importText,
    linkToProject,
    loadExcerpts,
  }
}
