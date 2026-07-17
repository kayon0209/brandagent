/**
 * 全文润色 API Route（F05）
 * POST /api/generate/polish
 * Body: { content: string, intensity?: 'light' | 'medium' | 'deep' }
 * Response: { success: true, data: { polishedContent: string } }
 */
import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'
import { glmClient, MODEL_WRITER } from '@/lib/api/anthropic'
import { buildPolishPrompt } from '@/lib/prompts/polish-generation'
import { checkQuota, recordTokenUsage } from '@/lib/quota'

// --- 输入 Schema ---
const RequestSchema = z.object({
  content: z
    .string()
    .trim()
    .min(1, '请提供待润色的文章内容')
    .max(8000, '文章内容不能超过8000字'),
  intensity: z.enum(['light', 'medium', 'deep']).default('medium'),
})

// 润色预估消耗约 6000 tokens（输入输出都较长）
const ESTIMATED_TOKENS = 6000

export async function POST(req: NextRequest) {
  // Step 1：认证（已移除 Clerk，使用匿名用户）
  const userId = 'anonymous'

  // Step 2：入参校验
  const parsed = RequestSchema.safeParse(await req.json().catch(() => ({})))
  if (!parsed.success) {
    return NextResponse.json(
      {
        success: false,
        error: { code: 'VALIDATION_ERROR', message: parsed.error.issues[0]?.message ?? '入参校验失败' },
      },
      { status: 400 }
    )
  }

  const { content, intensity } = parsed.data

  // Step 3：配额检查
  const quota = await checkQuota(userId, ESTIMATED_TOKENS)
  if (!quota.allowed) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: 'QUOTA_EXCEEDED',
          message: `本月免费额度已用完（已用 ${quota.used}/${quota.quota} tokens），请升级 Pro 套餐`,
        },
      },
      { status: 429 }
    )
  }

  // Step 4：调用 GLM 进行全文润色
  try {
    const prompt = buildPolishPrompt(content, intensity)
    const message = await glmClient.messages.create({
      model: MODEL_WRITER,
      max_tokens: 8192,
      messages: [{ role: 'user', content: prompt }],
    })

    const inputTokens = message.usage.input_tokens
    const outputTokens = message.usage.output_tokens
    const rawText = message.content[0]?.type === 'text' ? message.content[0].text : ''

    const polishedContent = rawText.trim()
    if (!polishedContent) {
      return NextResponse.json(
        { success: false, error: { code: 'AI_ERROR', message: 'AI 输出为空，请重试' } },
        { status: 502 }
      )
    }

    // Step 5：异步记录 token 用量
    recordTokenUsage(userId, 'polish_content', inputTokens, outputTokens).catch((err) =>
      console.warn('[generate/polish] Failed to record token usage:', err)
    )

    return NextResponse.json({
      success: true,
      data: { polishedContent },
      usage: { inputTokens, outputTokens },
    })
  } catch (error) {
    console.error('[generate/polish] GLM API error:', error)
    return NextResponse.json(
      { success: false, error: { code: 'AI_ERROR', message: 'AI 生成失败，请稍后重试' } },
      { status: 500 }
    )
  }
}
