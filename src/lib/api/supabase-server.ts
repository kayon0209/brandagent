/**
 * 服务端 Supabase 客户端（携带用户 session，受 RLS 保护）
 * 仅在 Server Components、API Routes、Server Actions 中使用
 * src/lib/api/supabase-server.ts
 */
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

export async function createSupabaseServerClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

  if (!url || !anonKey) {
    throw new Error('Missing Supabase server environment variables')
  }

  // Next 15: cookies() is async
  const cookieStore = await cookies()

  return createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll()
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          )
        } catch {
          // Server Component 中无法写 cookie，忽略（读操作不受影响）
        }
      },
    },
  })
}

/**
 * 服务端管理员客户端（绕过 RLS，仅用于服务端可信操作）
 * ⚠️ 永远不要在客户端代码中导入此函数
 */
export function createSupabaseAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY

  if (!url || !serviceKey) {
    throw new Error('Missing Supabase admin environment variables')
  }

  // 使用 createServerClient 而非 createClient，保持连接复用
  return createServerClient(url, serviceKey, {
    cookies: { getAll: () => [], setAll: () => {} },
    auth: { persistSession: false, autoRefreshToken: false },
  })
}
