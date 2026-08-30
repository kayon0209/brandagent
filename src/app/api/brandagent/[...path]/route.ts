import { NextResponse, type NextRequest } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { agentApiUrl } from '@/lib/api/server-agent-api'

type RouteContext = { params: { path: string[] } }

const ANONYMOUS_ENVELOPE = {
  success: false as const,
  error: { code: 'AUTH_REQUIRED', message: '登录后才能继续使用工作区。' },
}

// End-to-end request body cap (security review P2): the biggest legitimate
// payload is a material upload (10MB) + JSON envelope headroom.
const MAX_BODY_BYTES = 12 * 1024 * 1024

async function proxy(request: NextRequest, context: RouteContext) {
  const { userId, getToken } = await auth()
  const token = await getToken()
  if (!userId || !token) {
    return NextResponse.json(ANONYMOUS_ENVELOPE, { status: 401 })
  }

  const contentLength = Number(request.headers.get('content-length') ?? '0')
  if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
    return NextResponse.json(
      {
        success: false,
        error: { code: 'PAYLOAD_TOO_LARGE', message: '请求内容过大，请减小后重试。' },
      },
      { status: 413 },
    )
  }

  const requestId = request.headers.get('x-request-id') ?? crypto.randomUUID()
  const headers = new Headers({
    Authorization: `Bearer ${token}`,
    'X-Request-Id': requestId,
  })
  const idempotencyKey = request.headers.get('idempotency-key')
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey)
  const lastEventId = request.headers.get('last-event-id')
  if (lastEventId) headers.set('Last-Event-ID', lastEventId)

  const search = new URL(request.url).search
  const target = `${agentApiUrl()}/${context.params.path.join('/')}${search}`
  const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.arrayBuffer()

  let upstream: Response
  try {
    upstream = await fetch(target, { method: request.method, headers, body })
  } catch {
    return NextResponse.json(
      { success: false, error: { code: 'GATEWAY_UNAVAILABLE', message: '写作服务暂时不可用，请稍后重试。' } },
      { status: 502, headers: { 'X-Request-Id': requestId } }
    )
  }

  const responseHeaders = new Headers()
  const contentType = upstream.headers.get('content-type')
  if (contentType) responseHeaders.set('Content-Type', contentType)
  responseHeaders.set('X-Request-Id', requestId)
  return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders })
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
