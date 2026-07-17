/**
 * 大纲生成 API Route
 * POST /api/generate/outline
 * Body: { title: string, length?: 'short' | 'medium' | 'long' }
 * Response: ApiResponse<{ outline: OutlineData }>
 */
import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'
import { glmClient, MODEL_WRITER } from '@/lib/api/anthropic'
import { buildOutlinePrompt } from '@/lib/prompts/outline-generation'
import { checkQuota, recordTokenUsage } from '@/lib/quota'

// --- 输入 Schema ---
const RequestSchema = z.object({
  title: z.string().trim().min(1, '请提供文章标题').max(150, '标题不能超过150字'),
  length: z.enum(['short', 'medium', 'long']).default('medium'),
})

// --- 输出 Schema（对齐 OutlineSection 类型）---
const OutlineSectionSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1).max(100),
  points: z.array(z.string().min(1).max(200)).min(1).max(5),
})

const OutlineResponseSchema = z.object({
  intro: z.string().min(1).max(500),
  sections: z.array(OutlineSectionSchema).min(2).max(7),
  conclusion: z.string().min(1).max(500),
})

export type OutlineData = z.infer<typeof OutlineResponseSchema>

// 大纲生成预估消耗约 800 tokens
const ESTIMATED_TOKENS = 1000

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

  const { title, length } = parsed.data

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

  // Step 4：调用 GLM 生成大纲
  try {
    const prompt = buildOutlinePrompt(title, length)
    const message = await glmClient.messages.create({
      model: MODEL_WRITER,
      max_tokens: 1500,
      messages: [{ role: 'user', content: prompt }],
    })

    const inputTokens = message.usage.input_tokens
    const outputTokens = message.usage.output_tokens
    const rawText = message.content[0]?.type === 'text' ? message.content[0].text : ''

    // Step 5：解析并校验输出
    const jsonMatch = rawText.match(/\{[\s\S]*\}/)
    if (!jsonMatch) {
      return NextResponse.json(
        { success: false, error: { code: 'AI_ERROR', message: 'AI 输出格式异常，请重试' } },
        { status: 502 }
      )
    }

    let outline: OutlineData
    try {
      const rawParsed = JSON.parse(jsonMatch[0])
      const validated = OutlineResponseSchema.safeParse(rawParsed)
      if (!validated.success) {
        console.warn('[generate/outline] Output validation failed:', validated.error.message)
        return NextResponse.json(
          { success: false, error: { code: 'AI_ERROR', message: 'AI 输出结构异常，请重试' } },
          { status: 502 }
        )
      }
      outline = validated.data
    } catch {
      return NextResponse.json(
        { success: false, error: { code: 'AI_ERROR', message: 'AI 输出解析失败，请重试' } },
        { status: 502 }
      )
    }

    // Step 6：异步记录 token 用量
    recordTokenUsage(userId, 'generate_outline', inputTokens, outputTokens).catch((err) =>
      console.warn('[generate/outline] Failed to record token usage:', err)
    )

    return NextResponse.json({
      success: true,
      data: { outline },
      usage: { inputTokens, outputTokens },
    })
  } catch (error) {
    console.error('[generate/outline] GLM API error:', error)
    return NextResponse.json(
      { success: false, error: { code: 'AI_ERROR', message: 'AI 生成失败，请稍后重试' } },
      { status: 500 }
    )
  }
}
