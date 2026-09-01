'use client'

/**
 * Platform variants state hook (task 12 + Phase 5 review fix):
 * network/server failures surface an honest error state — never a fake
 * "no master" empty state — and error codes travel with the state.
 *
 * P1-2: every model-costing action carries an Idempotency-Key held for the
 * whole action lifetime, so an automatic retry of the SAME action can never
 * double-call the provider or double-book the usage ledger. A NEW user
 * action (clicking generate again) mints a fresh key.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { brandFlowRequest, BrandFlowApiError } from '@/lib/api/brandflow'
import type { ChannelVariantState } from '@/components/consumer/preview/PlatformPreview'
import { newIdempotencyKey } from '@/lib/idempotency'

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
  // one key per in-flight action: retries of the same action reuse it
  const generateKeyRef = useRef<string | null>(null)
  const regenKeysRef = useRef<Record<string, string>>({})

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
    // a fresh user action mints a fresh key; the SAME action's retries reuse it
    if (!generateKeyRef.current) generateKeyRef.current = newIdempotencyKey()
    const key = generateKeyRef.current
    try {
      const result = await brandFlowRequest<GenerateResult>(
        `/api/v1/consumer/projects/${projectId}/variants/generate`,
        { method: 'POST', headers: { 'Idempotency-Key': key } },
      )
      const failedChannels: VariantsState['failedChannels'] = {}
      for (const [channel, outcome] of Object.entries(result.channels ?? {})) {
        if (outcome.status === 'failed') {
          failedChannels[channel] = { retryable: outcome.retryable ?? true }
        }
      }
      generateKeyRef.current = null // action completed — next click is a new action
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
      if (!regenKeysRef.current[channel]) regenKeysRef.current[channel] = newIdempotencyKey()
      const key = regenKeysRef.current[channel]
      try {
        await brandFlowRequest<Record<string, unknown>>(
          `/api/v1/consumer/projects/${projectId}/variants/${channel}/regenerate`,
          { method: 'POST', headers: { 'Idempotency-Key': key } },
        )
        delete regenKeysRef.current[channel] // completed — next regenerate is new
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
