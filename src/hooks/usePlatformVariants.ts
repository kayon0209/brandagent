'use client'

/**
 * Platform variants state hook (upgrade plan task 12).
 *
 * Loads the preview (never approval-gated), triggers generation and
 * per-channel regeneration, and keeps the previous version visible while
 * generating or after a failure.
 */

import { useCallback, useEffect, useState } from 'react'

import { brandFlowRequest } from '@/lib/api/brandflow'
import type { ChannelVariantState } from '@/components/consumer/preview/PlatformPreview'

export type VariantsStatus = 'no_master' | 'generating' | 'failed' | 'ready'

export interface VariantsState {
  status: VariantsStatus
  channels: Record<string, ChannelVariantState | undefined>
  failedChannels: Record<string, { retryable: boolean } | undefined>
}

interface GenerateResult {
  channels: Record<string, { status: 'ready' | 'failed'; retryable?: boolean; error_code?: string; content_version_id?: string }>
}

export function usePlatformVariants(projectId: string) {
  const [state, setState] = useState<VariantsState>({
    status: 'no_master',
    channels: {},
    failedChannels: {},
  })

  const load = useCallback(async () => {
    try {
      const data = await brandFlowRequest<{
        requires_approval: boolean
        master_content_version_id: string | null
        channels: Record<string, ChannelVariantState>
      }>(`/api/v1/consumer/projects/${projectId}/variants/preview`)
      setState({
        status: data.master_content_version_id ? 'ready' : 'no_master',
        channels: data.channels ?? {},
        failedChannels: {},
      })
    } catch {
      setState({ status: 'no_master', channels: {}, failedChannels: {} })
    }
  }, [projectId])

  useEffect(() => {
    void load()
  }, [load])

  const generate = useCallback(async () => {
    setState(previous => ({ ...previous, status: 'generating' }))
    try {
      const result = await brandFlowRequest<GenerateResult>(
        `/api/v1/consumer/projects/${projectId}/variants/generate`,
        { method: 'POST' },
      )
      const failedChannels: VariantsState['failedChannels'] = {}
      for (const [channel, outcome] of Object.entries(result.channels ?? {})) {
        if (outcome.status === 'failed') {
          failedChannels[channel] = { retryable: outcome.retryable ?? true }
        }
      }
      setState(previous => ({
        status: 'ready',
        channels: previous.channels, // previous versions stay visible
        failedChannels,
      }))
      await load()
    } catch {
      setState(previous => ({ ...previous, status: 'failed' }))
    }
  }, [load, projectId])

  const regenerate = useCallback(
    async (channel?: string) => {
      if (!channel) {
        await generate()
        return
      }
      setState(previous => ({ ...previous, status: 'generating' }))
      try {
        await brandFlowRequest<Record<string, unknown>>(
          `/api/v1/consumer/projects/${projectId}/variants/${channel}/regenerate`,
          { method: 'POST' },
        )
        await load()
      } catch {
        setState(previous => ({ ...previous, status: 'failed' }))
      }
    },
    [generate, load, projectId],
  )

  return { state, generate, regenerate, reload: load }
}
