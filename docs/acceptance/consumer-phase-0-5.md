# Consumer Phase 0–5 验收指南

基线永远是运行验收命令时的当前 checkout：先记录 `git rev-parse HEAD`
与 `git status --short`，历史绿灯不能替代本次证据。本文只保留可复跑的
门禁；一次性票据、探针、截图和运行日志不属于验收交付物。

## 常规质量门禁（PowerShell）

```powershell
# 前端：契约、组件、类型、静态检查和生产构建
npm.cmd run test:all
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build

# Agent API：在其自身目录运行，避免 Python path 冲突
Push-Location services\agent-api
.\.venv\Scripts\python.exe -m pytest -q
Pop-Location

# Brand tools MCP：复用 Agent API 的项目解释器
Push-Location services\brand-tools-mcp
..\agent-api\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

## 数据库与真实浏览器门禁

只可针对确认可丢弃的 PostgreSQL 执行以下门禁；不得将测试迁移指向业务
数据库。`scripts/start-brand-mcp.mjs` 和 `scripts/start-real-agent-api.mjs`
使用本地一次性数据库的 `127.0.0.1:54998`，与下方容器端口一致。

```powershell
# disposable PostgreSQL：按序应用 001–008，角色与 schema 初始化见 RUNBOOK
docker run --rm --name brandagent-real-pg -d `
  -e POSTGRES_HOST_AUTH_METHOD=trust `
  -p 127.0.0.1:54998:5432 `
  -v "D:\demo\brandagent\docs\migrations:/migrations:ro" `
  docker.1ms.run/library/postgres:16-alpine

# 真实数据库回归
$env:RUN_AGENT_DB_TESTS = 'true'
$env:AGENT_TEST_DATABASE_URL = 'postgresql://postgres@127.0.0.1:54998/postgres'
Push-Location services\agent-api
.\.venv\Scripts\python.exe -m pytest -q
Pop-Location

# 浏览器验收：先完成生产构建，再分别启动 MCP、Agent API 与 Web
node scripts\start-brand-mcp.mjs
node scripts\start-real-agent-api.mjs
node scripts\start-prod-web.mjs

# 需要本地、未提交的真实 Clerk 登录态；缺失时属于环境 blocker，不能算通过
$env:BRANDFLOW_E2E_STORAGE_STATE = 'tests/e2e/.auth/state.json'
$env:PLAYWRIGHT_SKIP_WEBSERVER = 'true'
npx.cmd playwright test tests/e2e/consumer-real-journey.spec.ts tests/e2e/consumer-signin-entry.spec.ts --project=chromium
```

迁移与 RLS 的完整维护窗口规则见 [RUNBOOK](../deployment/RUNBOOK.md)。

## 验收范围

| 门禁 | 证明内容 |
|---|---|
| Consumer migration gate | 001–008 顺序可应用；004/005 RLS 与 FORCE、006 风格档案隔离、007/008 schema 契约有效。 |
| 登录入口 | 匿名 `/app` 进入 Clerk 登录；登录后能回到工作台且无循环。 |
| 真实创作旅程 | 创建项目、导入/关联素材、编辑核心观点、生成稿件走真实 BFF 与后端，不以 route fulfill 替代。 |
| 账本与模型失败 | 已执行、结果丢失、格式无效和本地后处理失败都不得错误退款或改写稿件。 |

## 工作区卫生

验收前检查 `git status --short`。认证票据、`.next` 备份、构建日志、研究运行
产物和一次性浏览器探针必须保持在仓库外或被忽略；正式回归只使用 `tests/`
中的可重复测试和 `scripts/` 中受维护的启动脚本。
