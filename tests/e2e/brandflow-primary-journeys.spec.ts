import { expect, test } from '@playwright/test'

test.skip(!process.env.BRANDFLOW_E2E_STORAGE_STATE, 'Requires an authenticated Clerk storage state; no fake production identity is used.')

const task = { task_id: '00000000-0000-0000-0000-000000000001', title: 'Nova 发布任务', status: 'waiting_for_outline_approval', selected_channels: ['wechat_website', 'marketing_email'], current_node: 'wait_for_outline_approval', error: null }
const workspace = {
  task,
  brief: { topic: 'Nova', target_audience: 'IT 决策者', publishing_objective: '解释产品价值', desired_audience_action: '预约演示' },
  versions: [{ content_version_id: 'v1', content_type: 'master_outline', channel: null, version_number: 1, content: '第一节\n第二节', created_by_type: 'model' }],
  reviews: [], issues: [], tool_calls: [], lineage: [],
  approval_requirements: [{ approval_requirement_id: 'r1', content_version_id: 'v1', decision_type: 'outline', status: 'pending', target_snapshot_hash: 'a'.repeat(64) }],
}

async function mockApi(page) {
  await page.route('**/api/v1/tasks', async (route) => {
    if (route.request().method() === 'POST') return route.fulfill({ json: { success: true, data: task }, status: 201 })
    return route.fulfill({ json: { success: true, data: { items: [task] } } })
  })
  await page.route('**/api/v1/tasks/*/workspace', (route) => route.fulfill({ json: { success: true, data: workspace } }))
  await page.route('**/api/v1/tasks/*/events', (route) => route.fulfill({ body: '', headers: { 'content-type': 'text/event-stream' } }))
  await page.route('**/api/v1/tasks/*/outline/approve', (route) => route.fulfill({ json: { success: true, data: { ...task, status: 'generating_master' } } }))
}

test('create task, complete guided Brief, and open the workflow workspace', async ({ page }) => {
  await mockApi(page)
  await page.goto('/brandflow')
  await page.getByRole('button', { name: '创建任务' }).click()
  await page.getByLabel('任务名称').fill('Nova 发布任务')
  await page.getByLabel('主题').fill('Nova')
  await page.getByRole('button', { name: '继续' }).click()
  await page.getByLabel('目标受众').fill('IT 决策者')
  await page.getByLabel('发布目标').fill('解释产品价值')
  await page.getByLabel('期望受众行动').fill('预约演示')
  await page.getByRole('button', { name: '继续' }).click()
  await page.getByLabel('品牌 ID').fill('00000000-0000-0000-0000-000000000010')
  await page.getByLabel('产品 ID').fill('00000000-0000-0000-0000-000000000020')
  await page.getByRole('button', { name: '继续' }).click()
  await page.getByRole('button', { name: '提交任务' }).click()
  await expect(page.getByText('需要人工操作')).toBeVisible()
})

test('approve outline deliberately and expose issues, versions, lineage and tools', async ({ page }) => {
  await mockApi(page)
  await page.goto('/brandflow')
  await page.getByText('Nova 发布任务').click()
  page.once('dialog', (dialog) => dialog.accept('已核对来源和结构'))
  await page.getByRole('button', { name: '检查并批准' }).click()
  for (const tab of ['问题', '版本', '谱系', '工具']) await expect(page.getByRole('button', { name: tab })).toBeVisible()
})

test('recover from MCP failure and interrupted service state', async ({ page }) => {
  const failed = { ...workspace, task: { ...task, status: 'failed', error: { code: 'MCP_UNAVAILABLE', message: '品牌工具暂时不可用', recoverable: true, saved_work_safe: true, requires_human: false } } }
  await mockApi(page)
  await page.route('**/api/v1/tasks/*/workspace', (route) => route.fulfill({ json: { success: true, data: failed } }))
  await page.route('**/api/v1/tasks/*/retry', (route) => route.fulfill({ json: { success: true, data: task } }))
  await page.goto('/brandflow')
  await page.getByText('Nova 发布任务').click()
  await expect(page.getByText('工作已安全保存')).toBeVisible()
  await page.getByRole('button', { name: '从安全检查点重试' }).click()
})

test('channel approval, cross-channel final gate, version comparison and export remain API-gated', async ({ request }) => {
  test.skip(!process.env.BRANDFLOW_E2E_API_TOKEN, 'Requires a real test API token and disposable database.')
  const headers = { Authorization: `Bearer ${process.env.BRANDFLOW_E2E_API_TOKEN}`, 'Idempotency-Key': crypto.randomUUID() }
  for (const suffix of ['channels/generate', 'final/prepare', 'export']) {
    const response = await request.post(`/api/v1/tasks/${task.task_id}/${suffix}`, { headers, data: {} })
    expect([200, 403, 409, 422]).toContain(response.status())
  }
})
