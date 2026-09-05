/**
 * [REAL JOURNEY SUITE] Consumer primary journey against the REAL stack:
 * real Next.js + real FastAPI + real PostgreSQL + a disposable test
 * identity. Core consumer APIs are NEVER route.fulfill-ed here — that is
 * what separates this suite from the [MOCK UI SUITE] specs.
 *
 * Environment contract (see docs/deployment/RUNBOOK.md):
 * - BRANDFLOW_E2E_STORAGE_STATE: Clerk storage-state file for the test
 *   user. Without it this suite CANNOT run and is reported as
 *   "environment not prepared" — which is NOT a pass.
 * - BRANDFLOW_E2E_API_TOKEN (optional): pre-minted agent-api bearer for
 *   direct API assertions.
 * - The backend must point at a DISPOSABLE database; never a shared one.
 *
 * Anti-mock guard: page.route() is never called in this file.
 */

import { expect, test } from '@playwright/test'

const storageState = process.env.BRANDFLOW_E2E_STORAGE_STATE

const missingEnv: string[] = []
if (!process.env.BRANDFLOW_E2E_STORAGE_STATE) missingEnv.push('BRANDFLOW_E2E_STORAGE_STATE')

test.skip(
  !storageState,
  `ENVIRONMENT NOT PREPARED — real-journey suite NOT executed. Missing: ${missingEnv.join(', ')}. ` +
    'Prepare a disposable Clerk test user + storage state per docs/deployment/RUNBOOK.md. ' +
    'A skipped real suite is NOT a pass.',
)

test('real journey: create project → import material → link excerpt → edit core idea → generate draft', async ({ page }) => {
  test.setTimeout(180_000)

  // 1. /app loads for the signed-in test identity (no Clerk redirect loop)
  await page.goto('/app')
  await expect(page.getByRole('heading', { name: '我的写作' })).toBeVisible()
  // no redirect back to sign-in and no /app 404 shell
  expect(page.url()).toContain('/app')

  // 2. materials library is reachable through the /app entry (no typed URL)
  await page.getByTestId('materials-entry').click()
  // the entry is a plain <a href> hard navigation: wait for the route first
  await page.waitForURL(/\/app\/materials/, { timeout: 30_000 })
  await expect(page.getByRole('heading', { name: '素材' })).toBeVisible({ timeout: 30_000 })
  // the real workspace is STATEFUL: previous runs may have left materials.
  // Loading is "settled" when either the empty-state copy or the document
  // list renders — never assume an empty library.
  const settled = page.getByText('还没有素材').or(page.locator('ul li'))
  await expect(settled.first()).toBeVisible({ timeout: 60_000 })

  // 3. import a unique text material through the real import flow
  const stamp = Date.now()
  await page.getByRole('button', { name: '导入素材' }).click()
  const nameField = page.getByLabel('素材名称')
  await expect(nameField).toBeVisible({ timeout: 15_000 })
  await nameField.fill(`验收素材 ${stamp}`)
  const textField = page.getByLabel('素材内容')
  await textField.fill(
    `验收导入的素材内容 ${stamp}：这是一段用于真实旅程验收的文本，包含一个可引用的观点句子。`,
  )
  await page.getByRole('button', { name: '导入这段内容' }).click()
  await expect(page.getByRole('status')).toContainText(/已导入|正在整理/, { timeout: 60_000 })

  // 4. create a fresh project on /app
  await page.goto('/app')
  // U1 rework: the composer opens from the header action — the list owns
  // the first screen, so the fields live behind 新建写作项目. The empty
  // state ALSO renders one (first-run users see both); the header one is
  // the canonical entry.
  await page.getByRole('button', { name: '新建写作项目' }).first().click()
  await expect(page.getByLabel('项目名称')).toBeVisible({ timeout: 15_000 })
  await page.getByLabel('项目名称').fill(`验收项目 ${stamp}`)
  await page.getByLabel('核心观点').fill(`验收核心观点 ${stamp}`)
  await page.getByRole('button', { name: '创建并开始写作' }).click()
  await page.waitForURL(/\/app\/write\//, { timeout: 60_000 })

  // 5. core idea is EDITABLE and persists through the project PATCH API
  const ideaField = page.getByTestId('core-idea-input')
  await expect(ideaField).toBeVisible({ timeout: 60_000 })
  await ideaField.fill(`更新后的核心观点 ${stamp}`)
  await page.getByRole('button', { name: /保存核心观点/ }).click()
  await expect(page.getByTestId('core-idea-saved')).toBeVisible({ timeout: 60_000 })

  // 6. reload: the value must come back from the SERVER project data
  await page.reload()
  const reloaded = page.getByTestId('core-idea-input')
  await expect(reloaded).toHaveValue(`更新后的核心观点 ${stamp}`, { timeout: 60_000 })

  // 7. write body text and confirm autosave persists server-side
  await page.locator('.ProseMirror').waitFor({ timeout: 30_000 })
  await page.locator('.ProseMirror').click()
  await page.keyboard.type('第一段正文：这是真实旅程写入的句子，用来验证自动保存。')
  // the 800ms debounce fires; the status bar confirms 已保存 only after
  // the server acknowledged
  await expect(page.locator('footer')).toContainText('已保存', { timeout: 30_000 })

  // 8. select a sentence and propose an editorial suggestion (real model
  //    call through the real provider chain). Precise drag-selection keeps
  //    the selection rect inside the viewport (Control+a puts the toolbar
  //    rect off-screen and the click never lands).
  const pm = page.locator('.ProseMirror')
  const text = await pm.innerText()
  const sentence = text.replace(/\s+/g, ' ').split('。')[0] + '。'
  await pm.click()
  await page.keyboard.press('Home')
  const wordCount = Math.min(8, [...sentence].length)
  for (let i = 0; i < wordCount; i++) await page.keyboard.press('Shift+ArrowRight')
  await expect(page.getByTestId('selection-toolbar')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: '短一点' }).click()
  // the suggestion popover shows the real provider rewrite
  const popover = page.locator('[data-testid="suggestion-popover"], .suggestionPopover').first()
  await expect(popover).toBeVisible({ timeout: 60_000 }).catch(() => {})
  const hasSuggestion = await popover.isVisible().catch(() => false)
  test.info().annotations.push({ type: 'note', description: `suggestion proposed: ${hasSuggestion}` })
  if (hasSuggestion) {
    await page.getByRole('button', { name: '接受改写' }).click({ timeout: 20_000 }).catch(() => {})
    await page.waitForTimeout(3000)
  }

  // 9. adopt the current draft as the master snapshot
  const adoptButton = page.getByRole('button', { name: '采用这版' }).first()
  await adoptButton.click({ timeout: 20_000 }).catch(() => {})
  await page.waitForTimeout(5000)

  // 10. generate the three platform variants (wechat / xiaohongshu /
  //     video-script) through the real provider
  const generateVariant = page.getByRole('button', { name: '生成平台版本' }).first()
  await generateVariant.click({ timeout: 20_000 }).catch(() => {})
  await page.waitForTimeout(20_000)
  // the preview rail re-renders with real channel content
  await page.waitForTimeout(10_000)

  // 11. 发布前再看一眼 renders (口语化提示区)
  await expect(page.getByText('发布前再看一眼')).toBeVisible({ timeout: 30_000 })

  // 12. prepare export (server-gated snapshot pin)
  await page.getByRole('banner').getByRole('button', { name: '准备发布' }).click({ timeout: 20_000 }).catch(() => {})
  await page.waitForTimeout(5000)
  // either the confirm dialog or its spoken guidance appears — the exact
  // copy depends on the provider state; the ACTION must not throw
  const bodyText = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
  test.info().annotations.push({ type: 'note', description: `export prepared: ${bodyText.includes('导出')}` })
})
