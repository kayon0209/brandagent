# Consumer Desktop Redesign 验收指南

本指南验证 `/app` 与 `/app/write/[projectId]` 的桌面重构。它不以视觉截图替代真实数据和认证链路证据。

## 前端组件与静态检查

```powershell
pnpm exec jest tests/unit/consumer-project-dashboard.test.tsx tests/unit/consumer-preview.test.tsx tests/unit/consumer-editor.test.tsx --runInBand
pnpm run typecheck
pnpm run lint
```

预期：项目卡只展示项目接口提供的标题、核心观点与写作意图；`平台预览` 能区分已输入正文、空稿纸和请求错误，错误状态出现 `重试预览`。

## 真实浏览器验收

只使用可丢弃数据库与真实 Clerk 测试登录态。缺少 `BRANDFLOW_E2E_STORAGE_STATE` 时，Playwright 的认证套件会跳过，这是环境未准备，不是通过。

```powershell
$env:BRANDFLOW_E2E_STORAGE_STATE = 'tests/e2e/.auth/state.json'
$env:PLAYWRIGHT_SKIP_WEBSERVER = 'true'
pnpm exec playwright test tests/e2e/consumer-editor.spec.ts tests/e2e/consumer-real-journey.spec.ts --project=chromium
```

在 `1440 × 810` 视口人工确认：

1. `/app` 顶部导航、工作台概览、快速开始与最近项目都可见；点击任一 `新建项目` 打开既有创建表单。
2. 创建项目后地址仍为同源 `/app/write/<task_id>`。
3. 在稿纸输入一段正文后，右侧默认公众号卡显示同一段文字；切换小红书与口播仍显示各自的版式。
4. 断开预览请求后，错误提示不遮挡稿纸并可通过 `重试预览` 恢复。
5. 窄屏下预览栏位于稿纸下方，无横向滚动和不可触达的操作按钮。

真实栈服务与可丢弃 PostgreSQL 的启动方式见 [Consumer Phase 0–5 验收指南](./consumer-phase-0-5.md)。
