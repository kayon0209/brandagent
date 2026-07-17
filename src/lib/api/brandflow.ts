export type BrandFlowTask = {
  task_id: string
  title: string
  status: string
  selected_channels: string[]
  current_node: string | null
  error: null | {
    code: string
    message: string
    recoverable: boolean
    saved_work_safe: boolean
    requires_human: boolean
  }
}

export type BrandFlowWorkspace = {
  task: BrandFlowTask
  brief: Record<string, unknown> | null
  versions: Array<Record<string, unknown>>
  reviews: Array<Record<string, unknown>>
  issues: Array<Record<string, unknown>>
  approval_requirements: Array<Record<string, unknown>>
  human_decisions: Array<Record<string, unknown>>
  tool_calls: Array<Record<string, unknown>>
  lineage: Array<Record<string, unknown>>
}

type Envelope<T> =
  { success: true; data: T } | { success: false; error: { code: string; message: string } }

const API_URL = '/brandflow-api'

export class BrandFlowApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number
  ) {
    super(message)
  }
}

export async function brandFlowRequest<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  const raw = await response.text()
  let payload: Envelope<T>
  try {
    payload = JSON.parse(raw) as Envelope<T>
  } catch {
    throw new BrandFlowApiError(
      'INVALID_GATEWAY_RESPONSE',
      'BrandFlow 服务返回了无法识别的响应。已保存内容不会丢失。',
      response.status
    )
  }
  if (!response.ok || !payload.success) {
    const error = payload.success
      ? { code: `HTTP_${response.status}`, message: response.statusText }
      : payload.error
    throw new BrandFlowApiError(error.code, error.message, response.status)
  }
  return payload.data
}

export async function streamTaskEvents(
  taskId: string,
  lastEventId: number,
  onEvent: (event: { id: number; type: string; data: Record<string, unknown> }) => void,
  signal: AbortSignal
) {
  const response = await fetch(`${API_URL}/api/v1/tasks/${taskId}/events`, {
    headers: { 'Last-Event-ID': String(lastEventId) },
    signal,
  })
  if (!response.ok || !response.body)
    throw new BrandFlowApiError(
      'EVENT_STREAM_UNAVAILABLE',
      '任务更新流暂时不可用。已保存内容不会丢失。',
      response.status
    )
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (!signal.aborted) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      if (frame.startsWith(':')) continue
      const id = Number(frame.match(/^id: (.+)$/m)?.[1] ?? lastEventId)
      const type = frame.match(/^event: (.+)$/m)?.[1] ?? 'message'
      const raw = frame.match(/^data: (.+)$/m)?.[1]
      if (raw) onEvent({ id, type, data: JSON.parse(raw) as Record<string, unknown> })
    }
  }
}
