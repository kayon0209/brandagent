# AGENTS.md — ai-blog-assistant 项目规范
> 中间层约束文档（项目级）
> 继承自：~/.Codex/rules/common/ 全局规范
> 优先级：项目级规则 > 全局规则（具体覆盖一般）

---

## 1. 项目身份

**产品名**：AI写作助手（ai-blog-assistant）
**定位**：帮助博主/营销人员从0快速生成中文博客，克服写作启动难。
**技术栈**：Next.js 14 + TailwindCSS + Shadcn/UI + Anthropic Codex API + Supabase + Clerk + Vercel
**商业模式**：Freemium（Free 5篇/月 | Pro ¥39/月 | Team ¥99/月）

---

## 2. 目录结构（规范，不得随意新增顶层目录）

```
ai-blog-assistant/
├── AGENTS.md              # 本文件，项目规范（必读）
├── src/
│   ├── app/               # Next.js App Router 页面
│   │   ├── (auth)/        # 认证相关路由组
│   │   ├── (dashboard)/   # 登录后主界面路由组
│   │   ├── api/           # API Route Handlers
│   │   └── page.tsx       # Landing Page
│   ├── components/
│   │   ├── editor/        # 编辑器核心组件（WorkspaceEditor, OutlineEditor 等）
│   │   ├── ui/            # 通用UI组件（从 shadcn/ui 扩展）
│   │   └── layout/        # 布局组件（Header, Sidebar, Footer）
│   ├── lib/
│   │   ├── prompts/       # AI Prompt 模板（每个功能一个文件）
│   │   ├── api/           # 外部 API 封装（anthropic.ts, supabase.ts）
│   │   └── utils.ts       # 通用工具函数
│   ├── hooks/             # 自定义 React Hooks
│   ├── types/             # TypeScript 类型定义（全局类型放 index.ts）
│   └── styles/            # 全局 CSS（globals.css）
├── docs/                  # 项目文档（PRD、架构图、会议记录）
│   ├── PRD-ai-blog-assistant.md
│   ├── architecture.md
│   ├── brandflow-openapi.yaml  # BrandFlow V2 API 权威契约
│   └── migrations/        # 按编号递增、只前进的 SQL migration
│   └── deployment/        # 容器启动、数据库角色初始化与运维手册
├── _sandbox/              # 实验区（Prompt 测试、临时脚本）不进生产
├── public/                # 静态资源
├── services/
│   └── agent-api/         # BrandFlow FastAPI + LangGraph 服务（Python）
│   └── brand-tools-mcp/   # 独立 MCP server；九项品牌工具与高风险审批门禁
├── tests/
│   ├── unit/              # 单元测试（Jest + Testing Library）
│   └── e2e/               # 端到端测试（Playwright）
├── .env.local             # 本地环境变量（不提交 Git）
├── .env.example           # 环境变量模板（提交 Git）
└── package.json
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

所有返回 JSON 的 `/api/*` 路由统一返回格式；SSE 端点使用版本化事件 envelope，不套 JSON HTTP envelope：
```typescript
// 成功
{ success: true, data: T }

// 失败
{ success: false, error: { code: string, message: string } }
```

错误码规范：
- `AUTH_REQUIRED` — 未登录
- `QUOTA_EXCEEDED` — 免费额度耗尽
- `AI_ERROR` — Codex API 调用失败
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
ANTHROPIC_API_KEY=         # 必填，Codex API Key
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=  # 必填，Clerk 公钥
CLERK_SECRET_KEY=          # 必填，Clerk 私钥
NEXT_PUBLIC_SUPABASE_URL=  # 必填，Supabase 项目 URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=  # 必填，Supabase 匿名密钥
SUPABASE_SERVICE_ROLE_KEY= # 必填，Supabase 服务密钥（仅服务端）
```

---

## 8. 开发工作流（必须遵守顺序）

```
1. 需求变更 → 先更新 PRD / 本 AGENTS.md
2. 写测试（RED）→ 写实现（GREEN）→ 重构（IMPROVE）
3. 代码变更 → code-reviewer agent 审查
4. 合并前 → security-reviewer agent 过一遍
5. 提交格式：feat/fix/refactor/docs/test/chore: <描述>
```

---

## 9. 禁止事项

- Next.js 业务代码仅放 `src/`；BrandFlow Python 服务业务代码仅放 `services/agent-api/src/`。
- 禁止硬编码 API Key、密码等敏感信息。
- 禁止在未更新 AGENTS.md 的情况下新增顶层目录。
- 禁止跳过测试直接合并到 main。
- 禁止在 API Route 内写超过 50 行的业务逻辑（抽到 `lib/`）。
- 禁止为赶进度绕过文档直接改代码。

---

## 10. 当前阶段

**阶段**：BrandFlow Milestone 5 — Evaluation and completion
**下一步**：全量集成验证、前端旅程、容器化、运行手册与最终审查
**权威计划**：见 `docs/MASTER_PLAN.md`
**迁移规则**：Milestone 1 只新增 V2 表，不执行远端数据库变更，不删除或重命名旧表/列

---

_最后更新：2026-07-14 | 维护人：李凯盟_
_修改本文件需通知相关开发者，规则变更先改文档再改代码。_
