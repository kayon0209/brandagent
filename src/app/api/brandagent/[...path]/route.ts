import { NextResponse, type NextRequest } from 'next/server'
import { auth } from '@clerk/nextjs/server'
import { agentApiUrl } from '@/lib/api/server-agent-api'

type RouteContext = { params: Promise<{ path: string[] }> }

const ANONYMOUS_ENVELOPE = {
  success: false as const,
  error: { code: 'AUTH_REQUIRED', message: '登录后才能继续使用工作区。' },
}

// End-to-end request body cap (security review P2): the biggest legitimate
// payload is a material upload (10MB) + JSON envelope headroom.
const MAX_BODY_BYTES = 12 * 1024 * 1024

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params
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
  // the original Content-Type must survive (multipart uploads break
  // without their boundary); other hop-by-hop headers are not forwarded
  const contentType = request.headers.get('content-type')
  if (contentType) headers.set('Content-Type', contentType)
  const idempotencyKey = request.headers.get('idempotency-key')
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey)
  const lastEventId = request.headers.get('last-event-id')
  if (lastEventId) headers.set('Last-Event-ID', lastEventId)

  const search = new URL(request.url).search
  const target = `${agentApiUrl()}/${path.join('/')}${search}`

  let body: ArrayBuffer | undefined
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    body = await request.arrayBuffer()
    // verify the REAL size: chunked requests carry no Content-Length and
    // would otherwise bypass the cap above (security review P1)
    if (body.byteLength > MAX_BODY_BYTES) {
      return NextResponse.json(
        {
          success: false,
          error: { code: 'PAYLOAD_TOO_LARGE', message: '请求内容过大，请减小后重试。' },
        },
        { status: 413, headers: { 'X-Request-Id': requestId } },
      )
    }
  }

  let upstream: Response
  try {
    // no hang: a stuck upstream must surface as GATEWAY_UNAVAILABLE in
    // bounded time, never an infinite "生成中" (runtime audit finding).
    // SSE streams are exempt: the connection is intentionally long-lived
    // and aborts on client disconnect — a 90s cap would silently saw
    // every event stream in half.
    const isEventStream = path[path.length - 1] === 'events'
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      ...(isEventStream ? {} : { signal: AbortSignal.timeout(90_000) }),
    })
  } catch {
    return NextResponse.json(
      { success: false, error: { code: 'GATEWAY_UNAVAILABLE', message: '写作服务暂时不可用，请稍后重试。' } },
      { status: 502, headers: { 'X-Request-Id': requestId } }
    )
  }

  const responseHeaders = new Headers()
  const upstreamContentType = upstream.headers.get('content-type')
  if (upstreamContentType) responseHeaders.set('Content-Type', upstreamContentType)
  responseHeaders.set('X-Request-Id', requestId)
  return new NextResponse(upstream.body, { status: upstream.status, headers: responseHeaders })
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
