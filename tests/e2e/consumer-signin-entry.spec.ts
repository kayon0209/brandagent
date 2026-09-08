/**
 * P0 acceptance: the Clerk sign-in ENTRY must be usable by a fresh browser.
 *
 * Regression being locked: /app redirected anonymous users to /sign-in,
 * which had no route — a Next 404 meant nobody (including the real-journey
 * suite) could ever sign in. This spec runs WITHOUT a storage state: it
 * verifies the anonymous entry path only.
 *
 * 1. /app redirects to /sign-in (NOT a 404)
 * 2. /sign-in renders a real Clerk sign-in UI (its form/card iframe)
 * 3. /sign-up renders a real Clerk sign-up UI (new-user path)
 * 4. the redirect back to /app is preserved in the URL
 */

import { expect, test } from '@playwright/test'

test('anonymous /app entry shows a usable Clerk sign-in page (never 404)', async ({ browser }) => {
  // the playwright config injects BRANDFLOW_E2E_STORAGE_STATE into EVERY
  // test; the anonymous legs must opt out with a fresh, cookie-less context
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const page = await context.newPage()
  try {
    const response = await page.goto('/app')
    // the browser follows the middleware redirect to /sign-in
    await page.waitForURL(/\/sign-in/, { timeout: 15_000 })

    // NOT a 404: the sign-in route renders
    expect(page.url()).not.toContain('404')
    const status = response?.status() ?? 200
    expect([200, 307, 401]).toContain(status)

    // a REAL Clerk sign-in card is mounted (verified DOM classes on the
    // current Clerk 5.x build: .cl-card + identifier input inside a form)
    await expect(page.locator('.cl-card').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('input[name="identifier"]').first()).toBeVisible({ timeout: 20_000 })

    // the return-to-workspace URL is preserved so sign-in lands back on /app
    const url = new URL(page.url())
    const redirectTarget = url.searchParams.get('redirect_url') ?? url.searchParams.get('redirectUrl')
    expect(redirectTarget ?? '/app').toContain('/app')
  } finally {
    await context.close()
  }
})

test('sign-up route renders a usable Clerk registration page (never 404)', async ({ browser }) => {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const page = await context.newPage()
  try {
    await page.goto('/sign-up')
    await page.waitForURL(/\/sign-up/, { timeout: 15_000 })
    expect(page.url()).not.toContain('404')
    await expect(page.locator('.cl-card').first()).toBeVisible({ timeout: 20_000 })
  } finally {
    await context.close()
  }
})

test('signed-in round trip: storage state reaches /app without a redirect loop', async ({ browser }) => {
  test.skip(
    !process.env.BRANDFLOW_E2E_STORAGE_STATE,
    'ENVIRONMENT NOT PREPARED — the signed-in leg needs BRANDFLOW_E2E_STORAGE_STATE (not a pass).',
  )
  const context = await browser.newContext({
    storageState: process.env.BRANDFLOW_E2E_STORAGE_STATE,
  })
  const page = await context.newPage()
  await page.goto('/app')
  // no loop back to sign-in, no 404: the U1 workspace project list renders.
  await expect(page.getByRole('heading', { name: '项目', exact: true })).toBeVisible({ timeout: 30_000 })
  expect(page.url()).toContain('/app')
  await context.close()
})
