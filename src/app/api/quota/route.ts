// ============================================================
// Token 配额查询接口（已废弃）
// src/app/api/quota/route.ts
// ============================================================
// 按升级计划 Task 13：C 端配额的唯一权威是 FastAPI usage ledger
// (/api/v1/consumer/projects/{id}/usage)。这个旧 Supabase 端点在兼容
// 窗口内保留，但不再作为真实数据源——返回结构化的 deprecated 信封，
// 绝不在未配置 Supabase 的部署里崩成 500。
import { NextResponse } from 'next/server'

export const dynamic = 'force-dynamic'

export async function GET() {
  return NextResponse.json(
    {
      success: false,
      error: {
        code: 'ENDPOINT_DEPRECATED',
        message: '配额查询已迁移到新的写作服务。请使用 /api/v1/consumer/projects/{id}/usage。',
      },
    },
    { status: 410 },
  )
}
