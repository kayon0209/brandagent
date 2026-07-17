/**
 * SEO 关键词建议 API Route（F06）
 * POST /api/generate/seo
 * Body: { title: string, content: string }
 * Response: { success: true, data: { seoResult: SeoResult } }
 */
import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'
import { glmClient, MODEL_WRITER } from '@/lib/api/anthropic'
import { buildSeoPrompt } from '@/lib/prompts/seo-analysis'
import { checkQuota, recordTokenUsage } from '@/lib/quota'
import type { SeoKeyword, SeoResult } from '@/types'

// Re-export for backwards compatibility
export type { SeoKeyword, SeoResult }

// --- 输入 Schema ---
const RequestSchema = z.object({
  title: z.string().trim().min(1, '请提供文章标题').max(150, '标题不能超过150字'),
  content: z
    .string()
    .trim()
    .min(1, '请提供文章内容')
    .max(10000, '文章内容不能超过10000字'),
})

// --- AI 输出结构校验 Schema ---
const SeoKeywordSchema = z.object({
  word: z.string().min(1),
  currentCount: z.number().int().min(0),
  suggestedCount: z.number().int().min(0),
  importance: z.enum(['high', 'medium', 'low']),
})

const SeoResultSchema = z.object({
  coreKeywords: z.array(SeoKeywordSchema).min(1).max(10),
  missingKeywords: z.array(z.string().min(1)).min(1).max(10),
  suggestions: z.array(z.string().min(1)).min(3).max(5),
})

// SEO 分析预估消耗约 2000 tokens
const ESTIMATED_TOKENS = 2000

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

  const { title, content } = parsed.data

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

  // Step 4：调用 GLM 进行 SEO 分析
  try {
    const prompt = buildSeoPrompt(title, content)
    const message = await glmClient.messages.create({
      model: MODEL_WRITER,
      max_tokens: 2000,
      messages: [{ role: 'user', content: prompt }],
    })

    const inputTokens = message.usage.input_tokens
    const outputTokens = message.usage.output_tokens
    const rawText = message.content[0]?.type === 'text' ? message.content[0].text : ''

    // Step 5：解析并用 Zod 校验 AI 输出的 JSON 结构
    const jsonMatch = rawText.match(/\{[\s\S]*\}/)
    if (!jsonMatch) {
      return NextResponse.json(
        { success: false, error: { code: 'AI_ERROR', message: 'AI 输出格式异常，请重试' } },
        { status: 502 }
      )
    }

    let seoResult: SeoResult
    try {
      const rawParsed = JSON.parse(jsonMatch[0])
      const validated = SeoResultSchema.safeParse(rawParsed)
      if (!validated.success) {
        console.warn('[generate/seo] Output validation failed:', validated.error.message)
        return NextResponse.json(
          { success: false, error: { code: 'AI_ERROR', message: 'AI 输出结构异常，请重试' } },
          { status: 502 }
        )
      }
      seoResult = validated.data
    } catch {
      return NextResponse.json(
        { success: false, error: { code: 'AI_ERROR', message: 'AI 输出解析失败，请重试' } },
        { status: 502 }
      )
    }

    // Step 6：异步记录 token 用量
    recordTokenUsage(userId, 'seo_analysis', inputTokens, outputTokens).catch((err) =>
      console.warn('[generate/seo] Failed to record token usage:', err)
    )

    return NextResponse.json({
      success: true,
      data: { seoResult },
      usage: { inputTokens, outputTokens },
    })
  } catch (error) {
    console.error('[generate/seo] GLM API error:', error)
    return NextResponse.json(
      { success: false, error: { code: 'AI_ERROR', message: 'AI 生成失败，请稍后重试' } },
      { status: 500 }
    )
  }
}
