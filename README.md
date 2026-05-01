# AI 写作助手 · AI Blog Assistant

> 从一句话主题，10 分钟生成一篇完整的中文博客——由 Multi-Agent 协作驱动，带内容审核、SEO 分析和全文润色。

[![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-blue?logo=typescript)](https://www.typescriptlang.org)
[![Supabase](https://img.shields.io/badge/Supabase-green?logo=supabase)](https://supabase.com)
[![Clerk](https://img.shields.io/badge/Clerk-Auth-purple?logo=clerk)](https://clerk.com)
## 截图

![界面预览](./public/project-screenshot.png)
---

## ✨ 功能概览

| 步骤 | 功能 | 说明 |
|------|------|------|
| 1 | **标题生成** | 输入主题 → AI 给出 10 个差异化标题（数字型/问题型/对比型） |
| 2 | **大纲生成** | 选定标题 → 生成可编辑的结构化大纲，支持拖拽排序 |
| 3 | **段落扩写** | Multi-Agent 协作：研究员 → 撰稿人 → 主编审校，SSE 流式输出 |
| 4 | **全文润色** | 轻度 / 中度 / 深度三档润色，AI 重写提升可读性 |
| 5 | **SEO 分析** | 关键词分布分析 + 补充建议 + 优化提示 |
| 6 | **导出** | 下载 `.md` 文件 / 复制 Markdown / 复制纯文本（适合微信/掘金） |

**系统特性：**
- 🔐 Clerk 身份认证（支持 Google / 邮箱注册）
- 📊 Token 级配额系统（Free: 30,000 tokens/月，每月自动重置）
- 🛡️ 内容合规护栏（本地敏感词过滤 + 拦截日志）
- 💾 文章自动保存 + 历史记录管理
- 📈 语义相似度数据采集埋点（衡量 AI 有效性）

---

## 🏗️ 技术架构

```
用户浏览器
└── Next.js 14 App Router（Server Components + Client Components）
    ├── /app/(dashboard)/dashboard/editor  ← 编辑器主页面（4步工作流）
    ├── /app/api/generate/*                ← AI 生成接口（SSE 流式输出）
    ├── /app/api/articles/*                ← 文章 CRUD
    ├── /app/api/moderation/check          ← 内容合规检查
    ├── /app/api/generate/polish           ← 全文润色
    ├── /app/api/generate/seo              ← SEO 分析
    └── /app/api/quota                     ← Token 配额查询

后端 / 数据层
├── 智谱 GLM API（glm-4.5-air）← AI 生成，兼容 Anthropic SDK 接口
├── Supabase（PostgreSQL）     ← 文章存储 / Token 用量 / 合规日志
└── Clerk                      ← 身份认证 + 用户管理
```

### Multi-Agent 扩写流程（F04）

```
用户点击"生成" → /api/generate/expand（SSE）
                        │
              ┌─────────▼──────────┐
              │  Research Agent    │  检索相关背景知识
              │  （研究员）         │
              └─────────┬──────────┘
                        │ agent_status: research→done
              ┌─────────▼──────────┐
              │  Writer Agent      │  基于研究结果撰写段落
              │  （撰稿人）         │  text_delta 流式输出
              └─────────┬──────────┘
                        │ agent_status: write→done
              ┌─────────▼──────────┐
              │  Reviewer Agent    │  LLM-as-Judge 质量审校
              │  （主编）           │
              └─────────┬──────────┘
                        │ done
                   写入数据库，自动保存
```

---

## 🚀 本地运行

### 前置要求

- Node.js 18+
- [智谱 GLM API Key](https://open.bigmodel.cn)（免费注册，有免费额度）
- [Clerk](https://clerk.com) 应用（免费套餐够用）
- [Supabase](https://supabase.com) 项目（免费套餐够用）

### 1. 克隆并安装

```bash
git clone https://github.com/kayon09/ai-blog-assistant.git
cd ai-blog-assistant
npm install
```

### 2. 配置环境变量

```bash
cp .env.example .env.local
```

编辑 `.env.local`，填写以下变量：

```env
GLM_API_KEY=your_glm_api_key

NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...

NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
```

### 3. 初始化数据库

在 Supabase SQL Editor 中执行以下建表语句：

<details>
<summary>点击展开 SQL</summary>

```sql
-- 用户表
create table users (
  id uuid primary key default gen_random_uuid(),
  clerk_id text not null unique,
  plan_tier text not null default 'free',
  token_used integer not null default 0,
  token_quota integer not null default 30000,
  quota_reset_at timestamptz not null default (date_trunc('month', now()) + interval '1 month'),
  created_at timestamptz not null default now()
);

-- 文章表
create table articles (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  title text,
  outline jsonb,
  content text,
  status text not null default 'draft',
  word_count integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Token 用量日志
create table usage_logs (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  article_id uuid references articles(id),
  operation text not null,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  model text,
  created_at timestamptz not null default now()
);

-- 内容合规拦截日志
create table moderation_logs (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  input_hash text not null,
  trigger_level text not null,
  rule_id text,
  created_at timestamptz not null default now()
);

-- 文章分析埋点
create table article_analytics (
  article_id uuid primary key references articles(id),
  user_id text not null,
  ai_draft_hash text,
  user_final_text_length integer,
  exported_at timestamptz,
  created_at timestamptz not null default now()
);

-- Token 原子递增 RPC
create or replace function increment_token_used(p_clerk_id text, p_tokens integer)
returns void as $$
  update users set token_used = token_used + p_tokens where clerk_id = p_clerk_id;
$$ language sql;

-- 付费意向收集（正式支付接入前使用）
create table upgrade_intents (
  id             uuid primary key default gen_random_uuid(),
  clerk_user_id  text,                          -- 登录用户的 Clerk ID，未登录为 null
  plan           text not null,                  -- 'pro' | 'team'
  email          text not null,
  wechat         text,
  note           text,
  status         text not null default 'pending', -- 'pending' | 'contacted' | 'converted'
  created_at     timestamptz not null default now()
);
```

</details>

### 4. 启动开发服务器

```bash
npm run dev
```

打开 [http://localhost:3000](http://localhost:3000)

---

## 📁 项目结构

```
src/
├── app/
│   ├── (auth)/              # 登录 / 注册页（Clerk）
│   ├── (dashboard)/         # 工作台（需登录）
│   │   ├── dashboard/
│   │   │   ├── page.tsx     # 工作台首页（最近文章）
│   │   │   ├── articles/    # 文章历史列表
│   │   │   └── editor/      # 编辑器主页面（4步工作流）
│   │   └── layout.tsx       # Dashboard 布局（顶部导航）
│   ├── api/
│   │   ├── generate/        # AI 生成接口
│   │   │   ├── titles/      # 标题生成
│   │   │   ├── outline/     # 大纲生成
│   │   │   ├── expand/      # 段落扩写（Multi-Agent SSE）
│   │   │   ├── polish/      # 全文润色
│   │   │   └── seo/         # SEO 分析
│   │   ├── articles/        # 文章 CRUD
│   │   ├── moderation/      # 内容合规检查
│   │   ├── quota/           # Token 配额查询
│   │   └── analytics/       # 数据埋点
│   └── page.tsx             # Landing Page
├── components/
│   └── editor/              # ExportPanel / PolishPanel / SeoPanel
├── hooks/
│   ├── useArticleEditor.ts  # 编辑器核心状态管理
│   └── useModerationCheck.ts
├── lib/
│   ├── api/                 # GLM / Supabase 客户端封装
│   ├── prompts/             # AI Prompt 模板
│   └── moderation/          # 本地敏感词过滤
└── types/
    └── index.ts             # 全局类型定义
```

---

## 🎯 设计亮点

### 1. Multi-Agent 协作（不是单次 LLM 调用）
每个章节扩写经过三个 Agent 串联处理，前端通过 SSE 实时展示各 Agent 状态（研究中 / 写作中 / 审校中）。

### 2. 自动保存，内容不丢失
大纲生成后自动创建草稿，每个章节扩写完成后自动更新。刷新页面、关闭浏览器，下次通过 URL `?id=` 参数完整恢复。

### 3. Token 级配额系统
按实际消耗 token 数计费（而非篇数），更精准。Free 用户 30,000 tokens/月，每月 1 日自动重置，超额直接拒绝服务防止成本失控。

### 4. 内容合规护栏
405 个敏感词（政治/色情/暴力三类）本地即时过滤，命中后记录日志但不阻断 UX，降级优雅。

---

## 📄 文档

- [PRD — 产品需求文档](./docs/PRD-ai-blog-assistant.md)
- [架构决策记录](./docs/architecture.md)
- [项目开发规范](./CLAUDE.md)

---

## 🛠️ 技术栈

| 分类 | 技术 |
|------|------|
| 前端框架 | Next.js 14 App Router |
| 样式 | TailwindCSS + CSS Variables |
| 拖拽排序 | @dnd-kit/sortable |
| 身份认证 | Clerk v6 |
| 数据库 | Supabase (PostgreSQL) |
| AI 模型 | 智谱 GLM (glm-4.5-air) |
| AI SDK | Anthropic SDK（兼容 GLM 接口） |
| 部署 | Vercel |
| 语言 | TypeScript 5 |

---

## License

MIT
