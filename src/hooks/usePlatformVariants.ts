'use client'

/**
 * Platform variants state hook (task 12 + Phase 5 review fix):
 * network/server failures surface an honest error state — never a fake
 * "no master" empty state — and error codes travel with the state.
 */

import { useCallback, useEffect, useState } from 'react'

import { brandFlowRequest, BrandFlowApiError } from '@/lib/api/brandflow'
import type { ChannelVariantState } from '@/components/consumer/preview/PlatformPreview'

export type VariantsStatus = 'no_master' | 'generating' | 'failed' | 'ready' | 'error'

export interface VariantsState {
  status: VariantsStatus
  channels: Record<string, ChannelVariantState | undefined>
  failedChannels: Record<string, { retryable: boolean } | undefined>
  reviewBubbles: { kind: 'needs_fix' | 'blocking' | 'hint'; text: string }[]
  error?: { code: string; message: string }
}

interface GenerateResult {
  channels: Record<string, { status: 'ready' | 'failed'; retryable?: boolean; error_code?: string; content_version_id?: string }>
}

export function usePlatformVariants(projectId: string) {
  const [state, setState] = useState<VariantsState>({
    status: 'no_master',
    channels: {},
    failedChannels: {},
    reviewBubbles: [],
  })

  const load = useCallback(async () => {
    try {
      const data = await brandFlowRequest<{
        requires_approval: boolean
        master_content_version_id: string | null
        channels: Record<string, ChannelVariantState>
        review?: { bubbles: { kind: 'needs_fix' | 'blocking' | 'hint'; text: string }[] }
      }>(`/api/v1/consumer/projects/${projectId}/variants/preview`)
      setState({
        status: data.master_content_version_id ? 'ready' : 'no_master',
        channels: data.channels ?? {},
        failedChannels: {},
        reviewBubbles: data.review?.bubbles ?? [],
      })
    } catch (error) {
      // honest error state; a transport failure is NOT "no master"
      setState(previous => ({
        status: 'error',
        channels: previous.channels,
        failedChannels: {},
        reviewBubbles: previous.reviewBubbles,
        error: {
          code: error instanceof BrandFlowApiError ? error.code : 'NETWORK_ERROR',
          message: error instanceof Error ? error.message : '网络出了点问题',
        },
      }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        reviewBubbles: previous.reviewBubbles,
      }))
      await load()
    } catch (error) {
      setState(previous => ({
        status: 'failed',
        channels: previous.channels,
        failedChannels: {},
        reviewBubbles: previous.reviewBubbles,
        error: {
          code: error instanceof BrandFlowApiError ? error.code : 'NETWORK_ERROR',
          message: error instanceof Error ? error.message : '生成失败，上一版仍可查看',
        },
      }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      } catch (error) {
        setState(previous => ({
          status: 'failed',
          channels: previous.channels,
          failedChannels: {},
          reviewBubbles: previous.reviewBubbles,
          error: {
            code: error instanceof BrandFlowApiError ? error.code : 'NETWORK_ERROR',
            message: error instanceof Error ? error.message : '重新生成失败，上一版仍可查看',
          },
        }))
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [generate, load, projectId],
  )

  return { state, generate, regenerate, reload: load }
}
