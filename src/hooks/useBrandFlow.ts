'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  BrandFlowApiError,
  BrandFlowTask,
  BrandFlowWorkspace,
  brandFlowRequest,
  streamTaskEvents,
} from '@/lib/api/brandflow'

export function useBrandFlow() {
  const [tasks, setTasks] = useState<BrandFlowTask[]>([])
  const [workspace, setWorkspace] = useState<BrandFlowWorkspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<BrandFlowApiError | null>(null)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [reconnecting, setReconnecting] = useState(false)
  const eventCursor = useRef(0)
  const workspaceRef = useRef(workspace)
  workspaceRef.current = workspace
  const activeTaskId = workspace?.task.task_id

  const refreshTasks = useCallback(async () => {
    try {
      setError(null)
      await brandFlowRequest<{ workspace_id: string; role: string }>(
        '/api/v1/workspaces/bootstrap',
        { method: 'POST' }
      )
      const data = await brandFlowRequest<{ items: BrandFlowTask[] }>('/api/v1/tasks')
      setTasks(data.items)
    } catch (caught) {
      setError(caught as BrandFlowApiError)
    } finally {
      setLoading(false)
    }
  }, [])

  const openTask = useCallback(async (taskId: string) => {
    setLoading(true)
    try {
      setError(null)
      setWorkspace(
        await brandFlowRequest<BrandFlowWorkspace>(`/api/v1/tasks/${taskId}/workspace`)
      )
      eventCursor.current = 0
    } catch (caught) {
      setError(caught as BrandFlowApiError)
    } finally {
      setLoading(false)
    }
  }, [])

  const command = useCallback(
    async <T>(path: string, body: unknown, method: string = 'POST', key = crypto.randomUUID()) => {
      setSaveState('saving')
      try {
        const init: RequestInit = {
          method,
          headers: {} as Record<string, string>,
        }
        if (method !== 'GET') {
          init.body = JSON.stringify(body)
          ;(init.headers as Record<string, string>)['Idempotency-Key'] = key
        }
        const result = await brandFlowRequest<T>(path, init)
        if (workspaceRef.current) await openTask(workspaceRef.current.task.task_id)
        await refreshTasks()
        setSaveState('saved')
        return result
      } catch (caught) {
        setSaveState('error')
        throw caught
      }
    },
    [openTask, refreshTasks]
  )

  useEffect(() => {
    void refreshTasks()
  }, [refreshTasks])

  useEffect(() => {
    if (!activeTaskId) return
    const controller = new AbortController()

    const connect = async (retryDelay = 1000) => {
      try {
        setReconnecting(false)
        await streamTaskEvents(
          activeTaskId,
          eventCursor.current,
          (event) => {
            eventCursor.current = event.id
            void openTask(activeTaskId)
          },
          controller.signal
        )
      } catch (caught) {
        if (controller.signal.aborted) return
        setReconnecting(true)
        setError(caught as BrandFlowApiError)
        const delay = Math.min(retryDelay, 30000)
        await new Promise((r) => setTimeout(r, delay))
        if (!controller.signal.aborted) {
          void connect(delay * 2)
        }
      }
    }

    void connect()
    return () => controller.abort()
  }, [activeTaskId, openTask])

  return {
    isLoaded: true,
    isSignedIn: true,
    hasActiveWorkspace: true,
    organizationRole: 'content_operator' as const,
    tasks,
    workspace,
    loading,
    error,
    saveState,
    reconnecting,
    refreshTasks,
    openTask,
    command,
    closeTask: () => setWorkspace(null),
  }
}
