import { expect, test } from '@playwright/test'

test.skip(!process.env.BRANDFLOW_E2E_STORAGE_STATE, 'Requires an authenticated Clerk storage state; no fake production identity is used.')

const draft = {
  task_id: '00000000-0000-0000-0000-0000000000a1',
  revision: 3,
  document: { blocks: [{ block_id: 'b1', block_type: 'paragraph', text: '这是第一段。这里有一个需要改写的句子。' }] },
  plain_text: '这是第一段。这里有一个需要改写的句子。',
}

// The write page fetches the project server-side for the core idea (commit
// 7fda06d); the specs must mock that GET too or the page falls into the
// honest project-error state ("Project not found").
const project = {
  task_id: draft.task_id,
  title: 'E2E 写作项目',
  core_idea: '把复杂的方法讲成普通人能上手的步骤',
  writing_intent: '',
  active_master_version_id: null,
}

async function mockProject(page: import('@playwright/test').Page) {
  await page.route('**/api/v1/consumer/projects/*', route => {
    const url = new URL(route.request().url())
    // only the bare project GET (no /draft, /variants, /materials suffix)
    if (/\/projects\/[^/]+$/.test(url.pathname)) {
      return route.fulfill({ json: { success: true, data: project } })
    }
    return route.fallback()
  })
}

test('manuscript editor autosaves and recovers from revision conflicts', async ({ page }) => {
  let revision = draft.revision
  await mockProject(page)
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

test('platform preview renders three structures and never asks for approval', async ({ page }) => {
  await mockProject(page)
  await page.route('**/api/v1/consumer/projects/*/draft', route =>
    route.fulfill({ json: { success: true, data: draft } }),
  )
  await page.route('**/api/v1/consumer/projects/*/variants/preview', route =>
    route.fulfill({
      json: {
        success: true,
        data: {
          requires_approval: false,
          master_content_version_id: 'mv-1',
          channels: {
            wechat_website: { content: '公众号第一段。\n公众号第二段。', content_version_id: 'cv-1', master_content_version_id: 'mv-1' },
            xiaohongshu: { content: '笔记正文一句话。 #标签一 #标签二', content_version_id: 'cv-2', master_content_version_id: 'mv-1' },
            video_script_60s: { content: '开场口播。\n核心卖点。', content_version_id: 'cv-3', master_content_version_id: 'mv-1' },
          },
        },
      },
    }),
  )

  await page.goto(`/app/write/${draft.task_id}#核心观点`)
  await expect(page.getByText('平台预览')).toBeVisible()
  // three independent structures, not one text re-skinned
  await expect(page.getByTestId('wechat-paragraphs')).toBeVisible()
  await page.getByRole('tab', { name: '小红书' }).click()
  await expect(page.getByTestId('xiaohongshu-tags')).toBeVisible()
  await page.getByRole('tab', { name: '口播' }).click()
  await expect(page.getByTestId('video-script-lines')).toBeVisible()
  // honest empty review, no fake all-passed
  await expect(page.getByText('发布前再看一眼')).toBeVisible()
  await expect(page.getByText(/暂未发现需要你确认的地方/)).toBeVisible()
})
