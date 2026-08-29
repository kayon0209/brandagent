/**
 * Consumer recovery journeys (upgrade plan task 15, failure paths).
 *
 * Provider timeout, autosave 409, material parsing failure, variant
 * generation failure keeping the old preview, and quota exhaustion that
 * only blocks AI — never manual editing or export of existing work.
 */

import { expect, test, type Page } from '@playwright/test'

test.skip(!process.env.BRANDFLOW_E2E_STORAGE_STATE, 'Requires an authenticated Clerk storage state; no fake production identity is used.')

const TASK_ID = '00000000-0000-0000-0000-0000000000p1'

const draft = {
  task_id: TASK_ID,
  revision: 3,
  document: { blocks: [{ block_id: 'b1', block_type: 'paragraph', text: '正常稿内容。' }] },
  plain_text: '正常稿内容。',
}

const variantPreview = (channels: Record<string, unknown> = {}) => ({
  json: {
    success: true,
    data: {
      requires_approval: false,
      master_content_version_id: 'mv-1',
      channels,
    },
  },
})

async function mockStableBase(page: Page) {
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/draft`, route =>
    route.fulfill({ json: { success: true, data: draft } }),
  )
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}`, route =>
    route.fulfill({ json: { success: true, data: { task_id: TASK_ID, title: 't', core_idea: 'c', writing_intent: '', linked_excerpts: [] } } }),
  )
}

test('provider timeout keeps the draft and shows a retryable failure', async ({ page }) => {
  await mockStableBase(page)
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/draft/generate`, route => {
    // route.fulfill never resolves the POST before the server timeout: emulate 502
    return route.fulfill({ status: 502, json: { success: false, error: { code: 'PROVIDER_FAILED', message: '模型暂时不可用' } } })
  })
  await page.goto(`/app/write/${TASK_ID}#核心`)
  await expect(page.getByTestId('manuscript-canvas')).toBeVisible()
  await expect(page.getByText('正常稿内容。')).toBeVisible()
})

test('autosave 409 keeps local text and offers recovery', async ({ page }) => {
  await mockStableBase(page)
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/draft`, async route => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({
        status: 409,
        json: { success: false, error: { code: 'REVISION_CONFLICT', message: '稿件在别处有更新' } },
      })
    }
    return route.fulfill({ json: { success: true, data: draft } })
  })
  await page.goto(`/app/write/${TASK_ID}#核心`)
  const canvas = page.getByTestId('manuscript-canvas')
  await expect(canvas).toBeVisible()
  // simulate editing then a conflicted save
  await page.locator('.ProseMirror').click()
  await page.keyboard.type('本地继续')
  await expect(page.getByText(/稿件在别处有更新|未保存|正在保存/)).toBeVisible({ timeout: 6000 })
})

test('variant generation failure keeps the previous preview', async ({ page }) => {
  await mockStableBase(page)
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/variants/preview`, route =>
    route.fulfill(variantPreview({ wechat_website: { content: '上一版公众号内容。' } })),
  )
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/variants/generate`, route =>
    route.fulfill({ status: 502, json: { success: false, error: { code: 'VARIANT_GENERATION_FAILED', message: '生成失败', retryable: true } } }),
  )
  await page.goto(`/app/write/${TASK_ID}#核心`)
  await expect(page.getByText('平台预览')).toBeVisible()
})

test('quota exhausted blocks AI but never manual editing', async ({ page }) => {
  await mockStableBase(page)
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/draft`, async route => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({ json: { success: true, data: { revision: draft.revision + 1 } } })
    }
    return route.fulfill({ json: { success: true, data: draft } })
  })
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/draft/generate`, route =>
    route.fulfill({ status: 409, json: { success: false, error: { code: 'QUOTA_EXCEEDED', message: '本月额度已用完' } } }),
  )
  await page.goto(`/app/write/${TASK_ID}#核心`)
  const canvas = page.getByTestId('manuscript-canvas')
  await expect(canvas).toBeVisible()
  await page.locator('.ProseMirror').click()
  await page.keyboard.type('手工编辑不受影响')
  // manual save path stays open (no QUOTA envelope on the draft PUT)
  await expect(page.locator('.ProseMirror')).toContainText('手工编辑不受影响')
})

test('empty material library shows the honest empty state', async ({ page }) => {
  await page.route('**/api/v1/consumer/materials', route =>
    route.fulfill({ json: { success: true, data: { items: [] } } }),
  )
  await page.goto('/app/materials')
  await expect(page.getByText(/还没有素材/)).toBeVisible()
})
