/**
 * One-shot: mint a fresh sign-in token, complete the login on 127.0.0.1,
 * and overwrite tests/e2e/.auth/state.json.
 *
 * Clerk dev-instance sessions are short-lived; any key rotation ALSO
 * invalidates prior cookies. Re-run this before each real-journey batch.
 * Requires the web server on :3000 (scripts/start-real-web.mjs).
 */
import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'

const env = {}
for (const line of readFileSync('.env.local', 'utf8').split('\n')) {
  const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/)
  if (m && !line.trim().startsWith('#')) env[m[1]] = m[2].replace(/^["']|["']$/g, '')
}

const USER_ID = process.env.E2E_CLERK_USER_ID || 'user_3IiFkN3lqEqInuu8Jjt6A2yb7gp'
const res = await fetch('https://api.clerk.com/v1/sign_in_tokens', {
  method: 'POST',
  headers: { Authorization: `Bearer ${env.CLERK_SECRET_KEY}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ user_id: USER_ID, expires_in_seconds: 600 }),
})
if (!res.ok) {
  console.error(`token mint failed: HTTP ${res.status}`)
  process.exit(1)
}
const { token } = await res.json()

const browser = await chromium.launch()
const context = await browser.newContext()
const page = await context.newPage()
try {
  await page.goto(`http://127.0.0.1:3000/sign-in?__clerk_ticket=${token}`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  for (let i = 0; i < 15; i++) {
    await page.waitForTimeout(4000)
    if (!page.url().includes('sign-in')) break
  }
  const ok = await page.getByRole('heading', { name: '我的写作' }).isVisible().catch(() => false)
  if (!ok) {
    console.error(`login did not land on /app (url=${page.url()})`)
    process.exit(1)
  }
  await context.storageState({ path: 'tests/e2e/.auth/state.json' })
  console.log('storage state refreshed (127.0.0.1 cookies)')
} finally {
  await browser.close()
}
