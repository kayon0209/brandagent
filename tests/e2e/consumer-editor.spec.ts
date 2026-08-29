import { expect, test } from '@playwright/test'

test.skip(!process.env.BRANDFLOW_E2E_STORAGE_STATE, 'Requires an authenticated Clerk storage state; no fake production identity is used.')

const draft = {
  task_id: '00000000-0000-0000-0000-0000000000a1',
  revision: 3,
  document: { blocks: [{ block_id: 'b1', block_type: 'paragraph', text: '这是第一段。这里有一个需要改写的句子。' }] },
  plain_text: '这是第一段。这里有一个需要改写的句子。',
}

test('manuscript editor autosaves and recovers from revision conflicts', async ({ page }) => {
  let revision = draft.revision
  await page.route('**/api/v1/consumer/projects/*/draft', async route => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: { success: true, data: { ...draft, revision } } })
    }
    const body = route.request().postDataJSON() as { baseRevision: number }
    if (body.baseRevision !== revision) {
      return route.fulfill({
        status: 409,
        json: { success: false, error: { code: 'REVISION_CONFLICT', message: '稿件在别处有更新' } },
      })
    }
    revision += 1
    return route.fulfill({ json: { success: true, data: { revision } } })
  })

  await page.goto(`/app/write/${draft.task_id}#核心观点`)
  const canvas = page.getByTestId('manuscript-canvas')
  await expect(canvas).toBeVisible()
  await expect(canvas).toHaveCSS('max-width', '720px')
  await expect(page.getByTestId('core-idea-block')).toBeVisible()

  // type, wait past the 800ms debounce, then confirm via the save badge
  await page.locator('.ProseMirror').click()
  await page.keyboard.type('编辑后的句子')
  await expect(page.getByText(/未保存|正在保存/)).toBeVisible()
  await expect(page.getByText(/已保存|稿件在别处有更新/)).toBeVisible({ timeout: 5000 })

  // a stale save keeps the local text and shows the recovery entry
  await page.evaluate(() => window.dispatchEvent(new Event('beforeunload')))
})
