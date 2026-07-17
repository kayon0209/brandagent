/**
 * Multi-Agent 扩写 API Route（SSE 流式输出）
 * POST /api/generate/expand
 * Body: { sectionTitle: string, sectionPoints: string[], styleCard?: string, wordCount?: number }
 *
 * 响应：text/event-stream，每条 SSE 事件为 JSON 序列化的 SSEEvent
 * 详见：src/lib/agents/expand-state-machine.ts
 */
import { NextRequest } from 'next/server'
import { z } from 'zod'
import { checkQuota, recordTokenUsage } from '@/lib/quota'
import { runExpandStateMachine } from '@/lib/agents/expand-state-machine'
import type { SSEEvent } from '@/lib/agents/expand-state-machine'

// 扩写预估 token 消耗（Research ~500 + Write ~800 + Review ~600，最多 2 轮）
const ESTIMATED_TOKENS = 4000

const RequestSchema = z.object({
  sectionTitle: z.string().trim().min(1, '章节标题不能为空').max(100),
  sectionPoints: z.array(z.string().min(1).max(200)).min(1, '至少需要一个要点').max(5),
  styleCard: z.string().max(2000).nullable().optional(),
  wordCount: z.number().int().min(200).max(800).default(400),
})

// SSE 工具函数：将事件序列化为标准 SSE 格式
function encodeSSE(event: SSEEvent): string {
  return `data: ${JSON.stringify(event)}\n\n`
}

export async function POST(req: NextRequest) {
  // Step 1：认证（已移除 Clerk，使用匿名用户）
  const userId = 'anonymous'

  // Step 2：入参校验
  const parsed = RequestSchema.safeParse(await req.json().catch(() => ({})))
  if (!parsed.success) {
    return new Response(
      encodeSSE({
        type: 'error',
        code: 'VALIDATION_ERROR',
        message: parsed.error.issues[0]?.message ?? '入参校验失败',
      }),
      { status: 400, headers: { 'Content-Type': 'text/event-stream' } }
    )
  }

  const { sectionTitle, sectionPoints, styleCard, wordCount } = parsed.data

  // Step 3：配额检查
  const quota = await checkQuota(userId, ESTIMATED_TOKENS)
  if (!quota.allowed) {
    return new Response(
      encodeSSE({
        type: 'error',
        code: 'QUOTA_EXCEEDED',
        message: `本月免费额度已用完（已用 ${quota.used}/${quota.quota} tokens），请升级 Pro 套餐`,
      }),
      { status: 429, headers: { 'Content-Type': 'text/event-stream' } }
    )
  }

  // Step 4：建立 SSE 流，运行状态机
  let totalInput = 0
  let totalOutput = 0

  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder()

      const enqueue = (event: SSEEvent) => {
        controller.enqueue(encoder.encode(encodeSSE(event)))
      }

      try {
        const generator = runExpandStateMachine(
          {
            sectionTitle,
            sectionPoints,
            styleCard: styleCard ?? null,
            wordCount,
          },
          (inputTokens, outputTokens) => {
            totalInput += inputTokens
            totalOutput += outputTokens
          }
        )

        for await (const event of generator) {
          enqueue(event)

          // 状态机结束时记录 token 用量
          if (event.type === 'done') {
            recordTokenUsage(userId, 'expand_section', totalInput, totalOutput).catch((err) =>
              console.warn('[generate/expand] Failed to record token usage:', err)
            )
          }

          // 合规或致命错误：终止流
          if (event.type === 'error') break
        }
      } catch (err) {
        console.error('[generate/expand] State machine error:', err)
        enqueue({ type: 'error', code: 'AI_ERROR', message: 'AI 生成过程异常，请重试' })
      } finally {
        controller.close()
      }
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no', // 关闭 Nginx 缓冲，确保实时推送
    },
  })
}

// Vercel Edge 函数最大执行时间（Multi-Agent 链路较长）
export const maxDuration = 120
