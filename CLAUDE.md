# CLAUDE.md — BrandAgent 项目规范
> 中间层约束文档（项目级）
> 继承自：~/.claude/rules/common/ 全局规范
> 优先级：项目级规则 > 全局规则（具体覆盖一般）

---

## 1. 项目身份

**产品名**：BrandAgent（仓库前身 ai-blog-assistant，package.json name 仍为 ai-blog-assistant）
**定位**：面向个人创作者的品牌写作工作台（素材 → 核心观点 → 稿纸编辑 → 平台预览）；企业版 BrandFlow 审批工作台（`/brandflow`）在兼容窗口内保留，不承载 C 端新功能
**技术栈**：Next.js 15.5（App Router）+ React 19 + TailwindCSS 4 + Tiptap 3 编辑器 + FastAPI/LangGraph（`services/agent-api`）+ MCP 工具服务（`services/brand-tools-mcp`）+ PostgreSQL 16（RLS 强制行级安全）+ Clerk 认证 + 智谱 GLM 兼容网关（OpenAI-compatible，经 `GLM_BASE_URL` 可切换）
**商业模式**：Freemium，C 端以 token 计量（Free 30000 tokens/月，`src/types/index.ts:48-57`），未接支付（仅有意向收集 `src/app/api/upgrade-intent/route.ts`）

---

## 2. 目录结构（规范，不得随意新增顶层目录）

```
brandagent/
├── CLAUDE.md              # 本文件，项目规范（必读）
├── src/                   # Next.js 业务代码（仅放这里）
│   ├── app/
│   │   ├── (consumer)/    # C 端创作链路（/app 首页、materials 素材库、write/[projectId] 稿纸）
│   │   ├── (dashboard)/   # 旧博客助手（冻结，不新增功能）
│   │   ├── brandflow/     # B 端审批工作台（兼容窗口保留）
│   │   ├── api/           # Route Handlers（含 brandagent/[...path] BFF 代理）
│   │   ├── sign-in|sign-up/  # Clerk 认证页
│   │   └── page.tsx       # 入口分发（NEXT_PUBLIC_DEFAULT_ENTRY 可回滚）
│   ├── components/
│   │   ├── consumer/      # C 端组件（editor/ materials/ preview/）
│   │   ├── editor/        # B 端工作区组件（BrandFlowTaskWorkspace 等）
│   │   └── ui/            # 通用UI组件
│   ├── lib/
│   │   ├── api/           # BFF 客户端（brandflow.ts SSE / consumer.ts / anthropic.ts GLM 客户端）
│   │   └── prompts/       # 旧链路 Prompt 模板（C 端 prompt 在 Python 侧）
│   ├── hooks/             # 自定义 React Hooks（useConsumerDraft 等）
│   └── types/             # 类型定义（index.ts / consumer.types.ts / generated/）
├── services/
│   ├── agent-api/         # FastAPI + LangGraph 服务（Python，业务代码仅放 src/agent_api/）
│   └── brand-tools-mcp/   # MCP server：九项品牌工具与高风险审批门禁（8100 端口）
├── docs/
│   ├── MASTER_PLAN.md     # 阶段与门禁权威索引
│   ├── PRD-v2.md          # 产品需求
│   ├── brandflow-openapi.yaml  # API 权威契约（OpenAPI 3.1）
│   ├── migrations/        # 只增不删的 SQL migration（001–005）
│   └── deployment/        # 运维手册
├── _sandbox/              # 实验区，不进生产
├── scripts/               # 本地启动/验收脚本（node .mjs）
├── tests/
│   ├── unit/              # 契约测试（node --test）+ Jest 单元/组件
│   └── e2e/               # Playwright（mock/real 分层纪律）
├── .env.local             # 本地环境变量（不提交）
├── .env.example           # 环境变量模板（提交）
└── package.json           # pnpm 单包工作区
```

---

## 3. 命名规则

| 类型 | 规则 | 示例 |
|------|------|------|
| 组件文件 | PascalCase | `WorkspaceEditor.tsx` |
| Hook 文件 | camelCase，use 前缀 | `useArticleGenerate.ts` |
| API Route | kebab-case | `generate-title/route.ts` |
| Prompt 文件 | kebab-case | `title-generation.ts` |
| 类型文件 | camelCase | `article.types.ts` |
| 常量 | SCREAMING_SNAKE_CASE | `MAX_FREE_ARTICLES = 5` |
| 数据库表 | snake_case | `user_articles` |

---

## 4. 核心业务类型定义（权威来源：`src/types/index.ts`）

> 以下为旧博客链路类型（`/dashboard`，冻结）。C 端现行 view model 见 `src/types/consumer.types.ts`（明确不泄漏 task/workflow/approval 词汇）；B 端契约类型由 `docs/brandflow-openapi.yaml` 经 openapi-typescript 生成（`src/types/generated/brandflow-api.ts`）。

```typescript
// 文章创作流程状态机
type WorkflowStep = 'topic' | 'titles' | 'outline' | 'writing' | 'done'

// 用户订阅级别
type PlanTier = 'free' | 'pro' | 'team'

// 文章实体
interface Article {
  id: string
  userId: string
  title: string
  outline: OutlineSection[]
  content: string
  status: 'draft' | 'completed'
  createdAt: Date
  updatedAt: Date
}

interface OutlineSection {
  id: string
  title: string
  points: string[]
  content?: string  // 扩写后填充
}
```

---

## 5. API 设计规范

所有 `/api/*` 路由统一返回格式：
```typescript
// 成功
{ success: true, data: T }

// 失败
{ success: false, error: { code: string, message: string } }
```

错误码规范：
- `AUTH_REQUIRED` — 未登录
- `QUOTA_EXCEEDED` — 免费额度耗尽
- `AI_ERROR` — 模型网关调用失败
- `VALIDATION_ERROR` — 入参校验失败

---

## 6. Prompt 工程规范

- Prompt 模板文件统一放 `src/lib/prompts/`，每个功能独立文件。
- Prompt 使用 TypeScript 函数封装，接收变量参数，返回字符串。
- 禁止在 API Route 里直接写 Prompt 字符串（散落各处难以维护）。
- 每次 Prompt 修改必须在 `_sandbox/` 先测试，通过后再合并。

```typescript
// src/lib/prompts/title-generation.ts 示例结构
export function buildTitlePrompt(topic: string, audience: string): string {
  return `...`
}
```

---

## 7. 环境变量规范

必须在 `.env.example` 中声明所有变量（无值），在 `.env.local` 中填值（不提交）。

```
GLM_API_KEY=              # 必填，模型网关 Key（OpenAI-compatible）
GLM_MODEL=                # 模型名（如 glm-4.7，或网关提供的模型）
GLM_BASE_URL=             # 模型网关地址（默认智谱 open.bigmodel.cn）
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=  # 必填，Clerk 公钥
CLERK_SECRET_KEY=         # 必填，Clerk 私钥
CLERK_JWKS_URL= / CLERK_ISSUER=     # 必填，Clerk JWKS 与 Issuer
AGENT_DATABASE_URL=       # 必填，业务库（brandflow_app 角色）
AGENT_CHECKPOINT_DATABASE_URL=      # 必填，LangGraph checkpoint 库（brandflow_checkpoint 角色）
BRAND_MCP_URL= / BRAND_MCP_DATABASE_URL= / BRAND_MCP_SERVICE_TOKEN=  # 必填，MCP 服务
TAVILY_API_KEY=           # 仅 Phase 6 研究实验用（搜索 provider）
NEXT_PUBLIC_SUPABASE_URL= # 可选，旧链路遗留（新链路走 FastAPI + PostgreSQL）
```

---

## 8. 开发工作流（必须遵守顺序）

```
1. 需求变更 → 先更新 PRD / 本 CLAUDE.md
2. 写测试（RED）→ 写实现（GREEN）→ 重构（IMPROVE）
3. 代码变更 → code-reviewer agent 审查
4. 合并前 → security-reviewer agent 过一遍
5. 提交格式：feat/fix/refactor/docs/test/chore: <描述>
```

---

## 9. 禁止事项

- 禁止在 `src/` 外写业务代码。
- 禁止硬编码 API Key、密码等敏感信息。
- 禁止在未更新 CLAUDE.md 的情况下新增顶层目录。
- 禁止跳过测试直接合并到 main。
- 禁止在 API Route 内写超过 50 行的业务逻辑（抽到 `lib/`）。
- 禁止为赶进度绕过文档直接改代码。

---

## 10. 当前阶段

**阶段**：Consumer Upgrade Phase 0–5 已交付（验收基线见 ACCEPTANCE.md）；Phase 6（深度调研与受限多 Agent 取证）为候选，仅在 Phase 5 门禁通过后单独立项
**下一步**：按 `docs/MASTER_PLAN.md` 逐 Phase 推进；每 Phase 门禁全绿且用户明确回复「继续」后才进入下一 Phase
**权威计划**：`docs/MASTER_PLAN.md`；升级规格全文见 `docs/superpowers/plans/2026-08-28-consumer-brandagent-upgrade.md`

---

_最后更新：2026-09-03 | 维护人：李凯盟_
_修改本文件需通知相关开发者，规则变更先改文档再改代码。_
