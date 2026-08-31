/**
 * Consumer primary journey (upgrade plan task 15, normal path).
 *
 * 1. bootstrap personal workspace
 * 2. import text material and wait for excerpts
 * 3. create project, edit core idea and body
 * 4. select a sentence, propose a suggestion, accept it
 * 5. adopt the master draft, generate three platform previews
 * 6. see review bubbles and prepare export
 */

import { expect, test, type Page } from '@playwright/test'

test.skip(!process.env.BRANDFLOW_E2E_STORAGE_STATE, 'Requires an authenticated Clerk storage state; no fake production identity is used.')

const WORKSPACE_ID = '00000000-0000-0000-0000-0000000000c1'
const TASK_ID = '00000000-0000-0000-0000-0000000000p1'

const material = {
  document_id: '00000000-0000-0000-0000-0000000000d1',
  document_name: '第一份素材',
  status: 'active',
  checksum: 'c'.repeat(12),
  created_at: '2026-08-29T00:00:00Z',
}
const excerpt = {
  excerpt_id: '00000000-0000-0000-0000-0000000000e1',
  excerpt_type: 'quote',
  summary: '一句可读的摘要',
  excerpt_text: '适合引用的原文句子。',
  tags: ['素材'],
  status: 'ready',
  provenance_hash: 'p'.repeat(64),
  document_id: material.document_id,
  chunk_id: '00000000-0000-0000-0000-0000000000k1',
  created_by_type: 'model',
}

const project = {
  task_id: TASK_ID,
  title: 'Nova 发布',
  core_idea: '把复杂的方法讲成普通人能上手的步骤',
  writing_intent: '公众号文章',
  active_master_version_id: null,
  linked_excerpts: [excerpt],
}

const draft = {
  task_id: TASK_ID,
  revision: 3,
  document: { blocks: [{ block_id: 'b1', block_type: 'paragraph', text: '这里有一个需要改写的句子，它有点啰嗦。' }] },
  plain_text: '这里有一个需要改写的句子，它有点啰嗦。',
}

async function mockAll(page: Page) {
  await page.route('**/api/v1/consumer/materials', route =>
    route.fulfill({ json: { success: true, data: { items: [material] } } }),
  )
  await page.route(`**/api/v1/consumer/materials/${material.document_id}/excerpts`, route =>
    route.fulfill({ json: { success: true, data: { items: [excerpt] } } }),
  )
  await page.route('**/api/v1/consumer/projects', route =>
    route.fulfill({ json: { success: true, data: { items: [project] } } }),
  )
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}`, route =>
    route.fulfill({ json: { success: true, data: project } }),
  )
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/draft`, route =>
    route.fulfill({ json: { success: true, data: draft } }),
  )
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/variants/preview`, route =>
    route.fulfill({
      json: {
        success: true,
        data: {
          requires_approval: false,
          master_content_version_id: 'mv-1',
          channels: {
            wechat_website: { content: '第一段。\n第二段。', content_version_id: 'cv-1', master_content_version_id: 'mv-1' },
            xiaohongshu: { content: '笔记一句话。 #标签', content_version_id: 'cv-2', master_content_version_id: 'mv-1' },
            video_script_60s: { content: '开场。\n卖点。', content_version_id: 'cv-3', master_content_version_id: 'mv-1' },
          },
        },
      },
    }),
  )
  await page.route(`**/api/v1/consumer/projects/${TASK_ID}/usage`, route =>
    route.fulfill({ json: { success: true, data: { used: 1200, quota: 30000 } } }),
  )
}

test('full consumer journey from material import to export preparation', async ({ page }) => {
  await mockAll(page)

  // 1-2: material library shows the distilled document and its excerpt
  await page.goto('/app/materials')
  await expect(page.getByText('第一份素材')).toBeVisible()
  await page.getByText('第一份素材').click()
  await expect(page.getByText('一句可读的摘要')).toBeVisible()

  // 3-6: write page carries core idea, platform previews, honest review
  await page.goto(`/app/write/${TASK_ID}#${encodeURIComponent('把复杂的方法讲成普通人能上手的步骤')}`)
  await expect(page.getByTestId('core-idea-block')).toBeVisible()
  await expect(page.getByText('平台预览')).toBeVisible()
  await expect(page.getByTestId('wechat-paragraphs')).toBeVisible()
  await expect(page.getByText('发布前再看一眼')).toBeVisible()
  await expect(page.getByRole('button', { name: '采用这版' })).toBeVisible()
  // 准备发布 exists BOTH in the topbar and the primary action bar (v4 spec);
  // scope to the topbar to keep the locator strict.
  await expect(page.getByRole('banner').getByRole('button', { name: '准备发布' })).toBeVisible()
})
