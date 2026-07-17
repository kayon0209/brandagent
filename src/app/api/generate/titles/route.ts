/**
 * 标题生成 API Route
 * POST /api/generate/titles
 *
 * 修复记录：
 * - C-2：加入配额检查，Free 用户超额返回 429
 * - H-1：使用 Zod 校验 GLM 输出结构，防止崩溃/注入
 * - H-2：TODO — 速率限制（需 Upstash Redis，待 infrastructure 就绪后接入）
 * - H-3：audience 字段加长度与类型校验
 * - M-1：TitleItem 从 @/types 导入，移除本地重复定义
 */
import { NextRequest, NextResponse } from 'next/server'
import { z } from 'zod'
import { glmClient, MODEL_WRITER } from '@/lib/api/anthropic'
import { buildTitlePrompt } from '@/lib/prompts/title-generation'
import { checkQuota, recordTokenUsage } from '@/lib/quota'
import type { TitleItem } from '@/types'

// --- Zod 校验 Schema（H-1）---
const TitleItemSchema = z.object({
  title: z.string().min(1).max(120),
  reason: z.string().min(1).max(300),
})

const TitlesResponseSchema = z.object({
  titles: z.array(TitleItemSchema).min(1).max(10),
})

// 标题生成预计消耗约 500 tokens（输入 Prompt ~300 + 输出 ~200）
const ESTIMATED_TOKENS = 600

export async function POST(req: NextRequest) {
  // Step 1：认证（已移除 Clerk，使用匿名用户）
  const userId = 'anonymous'

  // Step 2：入参校验（H-3：audience 同步校验）
  const RequestSchema = z.object({
    topic: z.string().trim().min(1, '请输入文章主题').max(200, '主题描述不能超过200字'),
    audience: z.string().trim().max(100, '目标读者描述不能超过100字').optional(),
  })

  const parsed = RequestSchema.safeParse(await req.json().catch(() => ({})))
  if (!parsed.success) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: 'VALIDATION_ERROR',
          message: parsed.error.issues[0]?.message ?? '入参校验失败',
        },
      },
      { status: 400 }
    )
  }

  const { topic, audience } = parsed.data

  // Step 3：配额检查（C-2）
  const quota = await checkQuota(userId, ESTIMATED_TOKENS)
  if (!quota.allowed) {
    return NextResponse.json(
      {
        success: false,
        error: {
          code: 'QUOTA_EXCEEDED',
          message: `本月免费额度已用完（已用 ${quota.used}/${quota.quota} tokens），请升级 Pro 套餐继续使用`,
        },
      },
      { status: 429 }
    )
  }

  // Step 4：调用 GLM API
  try {
    const prompt = buildTitlePrompt(topic, audience)
    const message = await glmClient.messages.create({
      model: MODEL_WRITER,
      max_tokens: 1024,
      messages: [{ role: 'user', content: prompt }],
    })

    const inputTokens = message.usage.input_tokens
    const outputTokens = message.usage.output_tokens

    // Step 5：解析并校验输出（H-1：Zod 校验）
    const rawText = message.content[0]?.type === 'text' ? message.content[0].text : ''
    let titles: TitleItem[] = []

    const jsonMatch = rawText.match(/\{[\s\S]*\}/)
    const jsonStr = jsonMatch ? jsonMatch[0] : rawText

    try {
      const rawParsed = JSON.parse(jsonStr)
      const validated = TitlesResponseSchema.safeParse(rawParsed)
      if (validated.success) {
        titles = validated.data.titles
      } else {
        // 结构校验失败，记录日志但不崩溃，返回空列表并提示重试
        console.warn('[generate/titles] GLM output validation failed:', validated.error.message)
        return NextResponse.json(
          { success: false, error: { code: 'AI_ERROR', message: 'AI 输出格式异常，请重试' } },
          { status: 502 }
        )
      }
    } catch {
      return NextResponse.json(
        { success: false, error: { code: 'AI_ERROR', message: 'AI 输出解析失败，请重试' } },
        { status: 502 }
      )
    }

    // Step 6：异步记录 token 用量（不阻塞响应）
    recordTokenUsage(userId, 'generate_titles', inputTokens, outputTokens).catch((err) =>
      console.warn('[generate/titles] Failed to record token usage:', err)
    )

    return NextResponse.json({
      success: true,
      data: { titles },
      usage: { inputTokens, outputTokens },
    })
  } catch (error) {
    console.error('[generate/titles] GLM API error:', error)
    return NextResponse.json(
      { success: false, error: { code: 'AI_ERROR', message: 'AI 生成失败，请稍后重试' } },
      { status: 500 }
    )
  }
}
