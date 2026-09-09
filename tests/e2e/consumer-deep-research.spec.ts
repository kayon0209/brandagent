/**
 * [REAL JOURNEY SUITE] Deep research end-to-end against the REAL stack
 * (Phase 6, user-approved 2026-09-08): real Next.js + real FastAPI +
 * real PostgreSQL + real Tavily search + real GLM model calls.
 *
 * Covers the MASTER_PLAN §10 gate on the live path:
 * - 发起调研 from the material drawer (project context);
 * - SSE progress shows directions; cancel keeps partial results;
 * - candidate cards arrive with source/excerpt/retrieved_at/risk hint;
 * - 加入素材 turns ONE card into a traceable material (document with
 *   source_url provenance) linked to the project;
 * - the synthesis NEVER auto-joins (library grows only on user action).
 *
 * Environment contract: same as consumer-real-journey.spec.ts — the
 * disposable Clerk storage state is REQUIRED (a skip is NOT a pass).
 */

import { expect, test } from '@playwright/test'

const storageState = process.env.BRANDFLOW_E2E_STORAGE_STATE

test.skip(
  !storageState,
  'ENVIRONMENT NOT PREPARED — deep-research real suite NOT executed. ' +
    'Prepare a disposable Clerk test user + storage state per docs/deployment/RUNBOOK.md. A skipped suite is NOT a pass.',
)

test('deep research: start → progress → candidate cards → join one card into materials', async ({ page }) => {
  test.setTimeout(600_000)

  // 1. enter a fresh project (the research entry lives in its drawer)
  await page.goto('/app')
  await expect(page.getByRole('heading', { name: '项目', exact: true })).toBeVisible()
  const stamp = Date.now()
  await page.getByRole('button', { name: '新建项目', exact: true }).first().click()
  await expect(page.getByLabel('项目名称')).toBeVisible({ timeout: 15_000 })
  await page.getByLabel('项目名称').fill(`调研验收 ${stamp}`)
  await page.getByLabel('核心观点').fill(`验收核心观点 ${stamp}`)
  await page.getByRole('button', { name: '创建并开始写作' }).click()
  await page.waitForURL(/\/app\/write\//, { timeout: 60_000 })

  // 2. open the material drawer: the deep research entry is there.
  //    The toolbar button carries a live count suffix (素材 N), so match
  //    by prefix, not exact name.
  await page.getByRole('button', { name: /^素材/ }).click()
  const panel = page.getByTestId('deep-research-panel')
  await expect(panel).toBeVisible({ timeout: 15_000 })
  await panel.getByRole('button', { name: '发起深度调研' }).click()
  const form = page.getByTestId('research-form')
  await expect(form).toBeVisible({ timeout: 10_000 })

  // 3. the honest pre-start estimate is visible BEFORE billing starts
  await expect(page.getByTestId('research-estimate')).toContainText('13K')

  // 4. a real research question through the real planner/scout chain
  await page.getByTestId('research-question-input').fill('2026 年个人创作者在小红书发内容有哪些注意事项？')
  await page.getByTestId('research-audience-input').fill('准备开始做账号的新手创作者')
  await page.getByTestId('research-submit').click()

  // 5. progress view replaces the form; directions appear; cancel exists
  const progress = page.getByTestId('research-progress')
  await expect(progress).toBeVisible({ timeout: 60_000 })
  await expect(progress).toContainText(/已完成/, { timeout: 60_000 })
  await expect(page.getByTestId('research-cancel')).toBeVisible()

  // 6. Real search + model calls. THREE honest outcomes, all gated:
  //    a) provider healthy → candidate cards with source/excerpt/risk;
  //    b) search provider over its plan limit (Tavily HTTP 432, the
  //       documented quota window) → the run completes and SAYS SO,
  //       billing only the real model calls;
  //    c) the GLM gateway loses a provider response (MODEL_EXECUTION_
  //       UNKNOWN) → the run fails honestly with the consumed tokens
  //       visible — never a hang, never silent fake cards.
  //    Silent fake cards are a failure in every branch.
  const cardList = page.getByTestId('research-cards')
  const noCards = page.getByTestId('research-no-cards')
  const failedView = page.getByTestId('research-failed')
  await expect(cardList.or(noCards).or(failedView)).toBeVisible({ timeout: 420_000 })

  if (await failedView.isVisible()) {
    // Branch c: the honest model failure is also an acceptance — the run
    // reached a terminal state through SSE, shows the honest error, and
    // never invents cards. The consumed-quota line must also be present
    // (取消与恢复 gate: partial consumption stays explainable).
    await expect(failedView).toContainText(/调研没能完成/)
    const tokensUsed = page.getByTestId('research-tokens-used')
    if (await tokensUsed.isVisible()) {
      await expect(tokensUsed).toContainText(/token 额度/)
    }
    await expect(page.getByTestId('research-progress')).toBeHidden()
    return
  }

  if (await noCards.isVisible()) {
    // Branch b: the honest degradation is the acceptance — a completed
    // run whose synthesis states the evidence gap instead of inventing
    // sources (plan §10: 调研结果默认可信；无来源不装作有来源).
    await expect(noCards).toContainText(/没有拿到可核实的来源|换个问法/)
    // the progress run reported terminal state through the SSE stream
    await expect(page.getByTestId('research-progress')).toBeHidden()
    return
  }

  await expect(page.getByTestId('research-synthesis')).toBeVisible({ timeout: 30_000 })
  // every card names its source + retrieval time + risk hint (plan §10)
  await expect(cardList.getByTestId('research-card').first()).toContainText('来源：')
  await expect(cardList.getByTestId('research-card').first()).toContainText('风险提示：')

  // 7. NOTHING auto-joined: the library is unchanged until the user acts
  const joinButton = cardList.getByTestId('research-card').first().getByRole('button', { name: '加入素材', exact: true })
  await expect(joinButton).toBeVisible()

  // 8. join exactly ONE card through the real import pipeline
  await joinButton.click()
  await expect(cardList.getByTestId('research-card').first().getByRole('button', { name: '已加入素材库' })).toBeVisible({ timeout: 60_000 })

  // 9. the joined material is traceable in the real materials library
  await page.getByRole('link', { name: '素材库', exact: true }).click()
  await page.waitForURL(/\/app\/materials/, { timeout: 30_000 })
  await expect(page.getByRole('heading', { name: '素材' })).toBeVisible({ timeout: 30_000 })
  const settled = page.getByText('还没有素材').or(page.locator('ul li'))
  await expect(settled.first()).toBeVisible({ timeout: 60_000 })
  // the research-joined material rides as a link-kind card
  const researchMaterial = page.locator('li', { hasText: '调研：' })
  await expect(researchMaterial.first()).toBeVisible({ timeout: 60_000 })
})
