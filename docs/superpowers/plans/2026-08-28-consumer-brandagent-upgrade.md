# BrandAgent Consumer Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把当前以 BrandFlow 企业审批工作台为主的 BrandAgent，升级为面向个人创作者的 C 端品牌写作产品；前端采用已经确认的“素材抽屉 + 核心观点 + 稿纸编辑 + 平台预览”骨架，后端复用现有证据、版本、渠道、审查、幂等与审计能力，并通过个人创作 API 门面隐藏 B 端组织流程。

**Architecture:** Next.js 负责 C 端页面、认证态和同源 BFF；FastAPI 新增 consumer application layer 和 /api/v1/consumer 契约；PostgreSQL 中继续复用 BrandFlow V2 的 content_tasks、content_versions、content_blocks、source_documents、source_chunks、review_results、content_lineage、task_events 与 model_call_logs，新增少量个人创作扩展表。LangGraph 只负责长耗时生成任务，不进入按键级编辑与自动保存链路。

**Tech Stack:** Next.js 14、React 18、TypeScript、CSS Modules/Tailwind、Clerk、Tiptap/ProseMirror、FastAPI、Pydantic、PostgreSQL、LangGraph、SSE、MCP、pytest、Jest/Testing Library、Playwright。

**Spec:** 本文第 1—9 节是产品与架构权威规格；视觉基线为 [_sandbox/consumer-ui-concept/index-v4.html](../../../_sandbox/consumer-ui-concept/index-v4.html)，现有 B 端契约为 [docs/brandflow-openapi.yaml](../../brandflow-openapi.yaml)，现状需求参考 [docs/PRD-v2.md](../../PRD-v2.md)。

## Global Constraints

- 本计划只授权文档设计，不授权数据库迁移、环境变量修改、删除旧路由、安装依赖、部署或发布；进入相应任务前必须按 AGENTS.md 单独取得授权。
- 一次只推进一个 Phase。每个 Phase 的验收门禁通过并由用户明确回复“继续”后，才能进入下一 Phase。
- 所有新增写接口必须有 Clerk 身份、个人 workspace 边界、幂等键或乐观并发控制；不能继续使用 anonymous 或硬编码登录态。
- C 端页面不得暴露 task、workflow node、approval requirement、lineage、model log 等系统词；这些对象只作为后台能力存在。
- 不新增全局深色侧边栏，不回退已确认的界面骨架；红色只用于编辑区底部“采用这版”主操作和需要注意的细节。
- 不复制 HRBPilot 的专有代码。只能复用架构思想。MindGraph 为 MIT，可在保留许可证声明和测试证据的前提下移植小型、稳定、无存储耦合的算法。
- 数据迁移只新增，不删除、不重命名旧表或旧列；旧 B 端接口在兼容窗口内继续工作。
- 任何“完成”结论必须来自当前 checkout 的 test、lint、typecheck、build、API contract 和关键 E2E 结果，不以原型截图或文档描述代替。

---

## 1. 结论先行

升级方向不是“把 BrandFlow 换一套漂亮皮肤”，也不是“另起炉灶重写 C 端”。

正确方向是：

1. 对用户，把产品重构成个人创作工作台：素材、观点、正文、平台效果、发布前检查。
2. 对前端，建立一个无全局侧边栏、以稿纸为中心的 C 端路由组；真实编辑器负责选择范围、光标锚点和浮动工具栏。
3. 对 API，新增个人创作语义门面，把 project、material、draft、suggestion、variant 暴露给前端。
4. 对后端，保留 BrandFlow Core：证据来源、不可变版本、渠道衍生、审查问题、内容血缘、事件流和模型调用账本。
5. 对工作流，把多角色人工审批从默认创作链路移走。个人用户的“采用、重生成、确认风险”记录为可审计的用户动作事件，但不写入企业审批决策，也不触发角色门禁。
6. 对发布，把“平台预览”与“真正发布”拆开。预览是低风险读取/渲染；直接发布仍是高风险能力，MVP 不做自动发布。

若不做这层语义拆分，前端越精致，后台越会显得笨重：用户每改一句话都可能撞上任务状态、审批要求或整页刷新，这会直接破坏 C 端体验。

---

## 2. 当前状况与主要缺口

### 2.1 当前可用资产

| 资产 | 当前实现 | 可复用判断 |
|---|---|---|
| 任务与租户边界 | workspaces、workspace_members、content_tasks | 保留；C 端每个用户自动拥有个人 workspace |
| Brief | content_briefs | 部分复用；topic、audience、tone 可映射，核心观点单独建模 |
| 素材与证据 | source_documents、source_chunks、verified_facts | 保留原始素材与 chunk；“蒸馏素材”新增 excerpt，不冒充 verified fact |
| 内容版本 | content_versions、content_blocks、immutable_hash | 重点复用；作为生成、采用、渠道化和导出的不可变快照 |
| 渠道衍生 | channel service、channel content versions | 重点复用；映射为微信、小红书、60 秒口播预览 |
| 审查 | review_results、review_issues | 重点复用；前端改写成人话气泡 |
| 血缘 | content_lineage | 保留；支持“这句话来自哪条素材、哪个母稿版本” |
| 事件流 | task_events + SSE | 保留；用于素材处理、生成与渠道预览状态 |
| 成本与日志 | model_call_logs、tool_call_logs | 保留；补用户配额账本与聚合接口 |
| 高风险工具门禁 | brand-tools-mcp | 保留在真正导出/发布边界，不用于普通平台预览 |

### 2.2 当前必须先解决的问题

1. 项目身份分裂：README、AGENTS.md、PRD 同时描述旧博客助手与 BrandFlow B 端，AGENTS.md 指向的 docs/MASTER_PLAN.md 实际不存在。
2. 登录是假状态：src/hooks/useBrandFlow.ts 直接返回 isSignedIn: true、hasActiveWorkspace: true；旧生成路由还存在“已移除 Clerk，使用匿名用户”。
3. BFF 不成立：next.config.js 只是把 /brandflow-api 透明 rewrite 到 FastAPI，浏览器没有可靠注入 Clerk token。
4. Clerk 依赖漂移：pnpm-lock.yaml 有 @clerk/nextjs，package.json 没有，安装树与锁文件不一致。
5. 前后端契约漂移：TypeScript 的任务状态比 Python domain enum 更宽，workspace 大量使用 Record<string, unknown>，无法保障 UI 与后端同步。
6. 编辑器不适合 C 端：现有 BlockEditor 以块级“接受/拒绝/重新生成”为中心，只在编辑态使用 contentEditable，不能稳定锚定跨文本选择。
7. 组件过大：BrandFlowLiveWorkspace.tsx 约 753 行、BrandFlowTaskWorkspace.tsx 约 1380 行，不能在其上继续堆 C 端分支。
8. 预览语义错误：现有 preview/export 被视为高风险 B 端动作；C 端右侧平台预览必须是低风险派生视图。
9. 素材只读不闭环：后端有 source repository，但缺少面向个人用户的导入、解析、蒸馏、关联项目和展示来源链路。
10. 工具链基线不干净：2026-08-28 当前 contract tests 为 3/3 通过，agent-api 为 50 passed / 5 skipped，MCP 为 12 passed / 2 skipped；npm run lint 因 node_modules 绑定到旧 pnpm store 而失败，不能把该失败误判成业务代码 lint 失败。

### 2.3 已存在但不应继续扩张的部分

- src/app/(dashboard) 和 src/app/api/generate/* 属于旧博客助手，不再承载新功能。
- src/app/brandflow/* 是企业版工作台，可在兼容期保留，但不作为 C 端组件库。
- Supabase article/quota 路径与 FastAPI BrandFlow V2 数据路径不能长期双写。新 C 端只通过 FastAPI 访问 V2 数据。
- LangGraph interrupt 审批流适合长任务和企业治理，不适合自动保存、选区改写或普通平台预览。

---

## 3. C 端产品边界

### 3.1 MVP 用户目标

用户能在一个页面内完成：

1. 新建写作项目并写下核心观点。
2. 从个人素材库选择可引用的蒸馏素材。
3. 在稿纸中自由编辑，选中一句话后调用“展开说说 / 换个例子 / 短一点”。
4. 看见微信、小红书、60 秒口播的真实语态预览。
5. 看见口语化的发布前提醒，并能追溯提醒所依据的素材或规则。
6. 采用当前版本、重新生成单个平台版本、复制或导出内容。
7. 自动保存，断线后恢复，不因 AI 请求失败丢稿。

### 3.2 明确不进入 MVP

- 多成员组织、角色分离、审批队列和管理员控制台。
- 自动发布到微信公众号、小红书或视频平台。
- 社交媒体排期、评论运营、数据回流和增长分析。
- 全量 GraphRAG、自动关系扩展或复杂知识图谱。
- 多人实时协作和评论线程。
- 为每次按键创建不可变 content_version。
- 把所有素材内容标记成“已验证事实”。

### 3.3 “可引用材料”的权威定义

界面中的“素材”不是原始文件列表，也不是已经被证明正确的事实列表。

它是从用户导入内容中蒸馏出的 material excerpt：

~~~text
原始来源 source_document
  -> 结构化片段 source_chunk
    -> 蒸馏素材 material_excerpt
      -> 项目关联 project_material_link
        -> 稿件块 / 渠道块 content_lineage
~~~

每条蒸馏素材至少包含：

- 一句可读摘要 summary
- 适合引用的原文或事实 excerpt_text
- 类型 quote / claim / example / voice_sample
- 关键词 tags
- 原始 document_id 与 chunk_id
- provenance_hash
- 状态 ready / needs_review / rejected

界面默认只显示摘要与标签；来源、日期、原文位置按需展开。这与已确认的素材抽屉一致，同时保留可信追溯能力。

---

## 4. 前端界面与后端对象的逐项匹配

| 已确认界面 | 前端组件 | API 契约 | 应用服务 | 持久化对象 |
|---|---|---|---|---|
| 顶部品牌名/头像 | ConsumerHeader | GET /consumer/me | ConsumerIdentityService | creator_profiles + workspace_members |
| 默认收起的素材抽屉 | MaterialDrawer | GET /consumer/materials、GET /consumer/projects/{id}/materials | MaterialService | source_documents、source_chunks、material_excerpts、project_material_links |
| 核心观点卡片 | CoreIdeaBlock | PATCH /consumer/projects/{id}/core-idea | ConsumerProjectService | consumer_projects.core_idea |
| 空稿生成首稿 | ManuscriptCanvas empty state | POST /consumer/projects/{id}/draft/generate | ConsumerDraftGenerationService | content_versions candidate + task_events |
| 720px 稿纸 | ManuscriptCanvas | GET/PUT /consumer/projects/{id}/draft | DraftService | consumer_drafts + content_versions 快照 |
| 选区工具栏 | SelectionToolbar | POST /consumer/projects/{id}/suggestions | EditorialAssistService | editor_suggestions + model_call_logs |
| 接受选区建议 | SuggestionPopover | POST /consumer/projects/{id}/suggestions/{sid}/accept | EditorialAssistService | consumer_drafts revision + content_versions + editor_suggestions + task_events |
| 平台预览 tabs | PlatformPreview | POST/GET /consumer/projects/{id}/variants/{channel} | PlatformVariantService | content_versions(channel_*) + content_lineage |
| 重新生成当前平台 | PlatformPreview action | POST /variants/{channel}/regenerate | PlatformVariantService | 新 channel version，不修改母稿 |
| 发布前再看一眼 | PrePublishReview | GET /consumer/projects/{id}/review | ConsumerReviewService | review_results、review_issues |
| 采用这版 | PrimaryActionBar | POST /consumer/projects/{id}/adopt | DraftService | immutable master snapshot + consumer_projects pointer + task_events |
| 准备发布 | Header secondary action | POST /consumer/projects/{id}/prepare-export | ExportPreparationService | export snapshot；不直接发布 |
| 底部保存状态 | SaveStatus | draft PUT response + SSE | DraftService | consumer_drafts.revision、updated_at |
| 75%—150% 缩放 | ZoomControl | 无后端 | local UI state | localStorage，仅影响稿纸 |

约束：一个界面状态只能有一个权威来源。保存状态来自 draft revision；生成进度来自 SSE；平台预览来自 channel content version；检查气泡来自 review issue。禁止在客户端伪造“已保存”“已核对”“已关联”。

---

## 5. 目标架构

~~~mermaid
flowchart LR
    U[个人创作者] --> UI[Next.js Consumer UI]
    UI --> BFF[Next.js authenticated BFF]
    BFF --> API[FastAPI Consumer API]

    API --> ID[Identity and Personal Workspace]
    API --> MAT[Material Service]
    API --> DRAFT[Draft and Suggestion Service]
    API --> VAR[Platform Variant Service]
    API --> REVIEW[Consumer Review Service]

    MAT --> DOC[(source_documents / source_chunks)]
    MAT --> EXT[(material_excerpts)]
    DRAFT --> HEAD[(consumer_drafts)]
    DRAFT --> VER[(content_versions / blocks)]
    VAR --> VER
    REVIEW --> ISS[(review_results / issues)]

    DOC --> LINEAGE[(content_lineage)]
    EXT --> LINEAGE
    VER --> LINEAGE

    MAT --> JOB[Background generation jobs]
    DRAFT --> JOB
    VAR --> JOB
    JOB --> LLM[Provider abstraction]
    JOB --> EVENTS[(task_events + SSE)]
    JOB --> LOGS[(model_call_logs / usage ledger)]

    API --> CORE[Existing BrandFlow Core]
    CORE --> MCP[High-risk MCP tools]
    MCP --> EXPORT[Export or future publish]
~~~

### 5.1 三条运行链路

1. 快速编辑链路：PUT draft，目标 P95 小于 300ms，不调用 LangGraph、不调用 LLM。
2. AI 建议链路：POST suggestion，记录 selection anchor、model call 和 proposal；失败不影响当前稿。
3. 长任务链路：素材解析/蒸馏、首稿生成、渠道生成走任务事件与 SSE；断线重连后可从 event cursor 恢复。

### 5.1.1 上传文件的 MVP 存储边界

- text 与 URL 导入持久化规范化正文、checksum、canonical URL 和 chunks。
- md/txt/pdf/docx 上传在受限临时目录中解析；MVP 持久化文件名、MIME、checksum、页码/标题路径和抽取文本，解析结束后清理临时字节。
- 原始文件长期下载不属于 MVP。若后续要求“打开原文件”，再引入 MaterialBlobStore 与对象存储；这属于新的外部服务与环境配置，必须单独批准。
- storage_reference 为空不影响 excerpt provenance；provenance 由 document checksum + chunk hash + 位置信息保证。

### 5.2 个人 workspace

- Clerk 用户首次访问时，用 user_id 派生稳定 personal workspace_id。
- 没有 Clerk organization 也能登录；有 organization 时仍进入 B 端 BrandFlow 路由。
- 个人 workspace 只创建一个 content_operator 成员，不制造 brand_reviewer 或 final_approver。
- FastAPI 根据 token principal 决定 workspace，绝不信任请求 body 中的 workspace_id。
- Next.js 不再使用透明 rewrite 直接把浏览器请求转发到 FastAPI；改为同源 Route Handler，从服务端读取 Clerk token 后注入 Authorization。

### 5.3 编辑文档模型

MVP 使用稳定、后端可校验的块文档，而不是直接持久化任意 HTML：

~~~typescript
type ConsumerDocument = {
  schemaVersion: '1.0'
  blocks: Array<{
    id: string
    type: 'heading' | 'paragraph' | 'quote' | 'listItem'
    text: string
  }>
}
~~~

Tiptap 只负责前端编辑体验，并把每个顶层节点映射到稳定 block id。后端以 block id + 字符偏移处理建议，避免保存危险 HTML。

### 5.4 乐观并发与选区安全

~~~typescript
type DraftUpdateRequest = {
  baseRevision: number
  document: ConsumerDocument
}

type SelectionAnchor = {
  blockId: string
  start: number
  end: number
  selectedTextHash: string
}

type EditorialAction = 'expand' | 'replace_example' | 'shorten'
~~~

- draft update 只有 baseRevision 等于当前 revision 才成功；否则返回 409 DRAFT_CONFLICT 和服务器当前 revision。
- suggestion accept 再次核对 block、range 和 selectedTextHash；文本变化时返回 409 STALE_SELECTION，不覆盖用户新编辑。
- 每个写命令要求 Idempotency-Key。
- 接受建议后一次事务内更新 consumer_drafts、写 immutable content_version、更新 suggestion 状态并写用户动作 task event；不复用企业审批 human_decisions。

---

## 6. 数据模型演进

数据库变更拟放在 docs/migrations/003_consumer_experience.sql。该文件只能在用户明确授权后创建和执行。

### 6.1 新增表

1. creator_profiles
   - workspace_id、user_id 唯一
   - display_name、brand_name、audience
   - voice_traits JSONB、preferences JSONB
   - created_at、updated_at

2. consumer_projects
   - task_id 主键并外键到 content_tasks
   - workspace_id
   - core_idea、writing_intent
   - active_master_version_id
   - created_at、updated_at

3. consumer_drafts
   - task_id 主键
   - workspace_id
   - revision BIGINT
   - document JSONB
   - plain_text
   - last_snapshot_version_id
   - updated_at、updated_by

4. material_excerpts
   - excerpt_id
   - workspace_id、document_id、chunk_id
   - excerpt_type
   - summary、excerpt_text、tags JSONB
   - provenance_hash
   - status
   - created_by_type、created_at

5. project_material_links
   - workspace_id、task_id、excerpt_id
   - pinned、position、created_at
   - 联合唯一 task_id + excerpt_id

6. editor_suggestions
   - suggestion_id
   - workspace_id、task_id、base_revision
   - block_id、start_offset、end_offset、selected_text_hash
   - action、proposal_text
   - supporting_excerpt_ids
   - status proposed / accepted / rejected / stale
   - model_call_id、created_at、resolved_at

7. usage_ledger
   - workspace_id、user_id、request_id 唯一
   - operation、model、input_tokens、output_tokens、estimated_cost
   - state reserved / settled / refunded
   - created_at、settled_at

### 6.2 继续复用的表

- content_tasks：内部 project aggregate root，不把 task 命名暴露给 C 端。
- content_briefs：保留 topic、audience、tone、channel 选择。
- source_documents/source_chunks：原始素材和结构化切片。
- content_versions/content_blocks：采用版本、渠道版本和快照。
- review_results/review_issues：检查结果。
- content_lineage：素材到母稿、母稿到渠道稿的追踪。
- task_events：长任务状态流。
- model_call_logs：模型调用明细。
- idempotency_records：写命令幂等。

### 6.3 不做的 schema 操作

- 不把 content_tasks 重命名为 projects。
- 不删除 approval 表。
- 不放宽 verified_facts.product_id 的 NOT NULL 来迁就个人素材。
- 不把 material_excerpt 混进 verified_facts。
- 不把向量检索存储立即迁移到 Milvus。
- 不在本阶段把 REAL[] 强行升级为 pgvector；先通过结构化路径和全文检索证明需要，再开独立决策。

---

## 7. Consumer API 契约

所有端点继续使用 { success: true, data } / { success: false, error } envelope；SSE 维持版本化事件 envelope。

### 7.1 身份与项目

| Method | Path | 语义 |
|---|---|---|
| POST | /api/v1/consumer/bootstrap | 创建或读取个人 workspace 与 profile |
| GET | /api/v1/consumer/me | 当前个人 profile、plan、quota |
| GET | /api/v1/consumer/projects | 项目列表 |
| POST | /api/v1/consumer/projects | 新建项目，要求 Idempotency-Key |
| GET | /api/v1/consumer/projects/{id}/workspace | 一次加载编辑页所需的聚合视图 |
| PATCH | /api/v1/consumer/projects/{id}/core-idea | 更新核心观点 |
| POST | /api/v1/consumer/projects/{id}/draft/generate | 从核心观点和已关联素材生成首稿候选 |
| POST | /api/v1/consumer/projects/{id}/draft/candidates/{versionId}/apply | 在 revision 校验通过后应用候选稿 |
| POST | /api/v1/consumer/projects/{id}/adopt | 采用当前 draft revision 为 master snapshot |

### 7.2 素材

| Method | Path | 语义 |
|---|---|---|
| GET | /api/v1/consumer/materials | 按状态、标签、搜索词分页 |
| POST | /api/v1/consumer/materials/text | 导入粘贴文本 |
| POST | /api/v1/consumer/materials/url | 导入 URL；服务端做 SSRF 防护 |
| POST | /api/v1/consumer/materials/upload | 上传 md/txt/pdf/docx；限制 MIME、大小和页数 |
| GET | /api/v1/consumer/materials/{id} | 原始来源、chunks、蒸馏状态 |
| GET | /api/v1/consumer/materials/{id}/excerpts | 蒸馏素材 |
| PUT | /api/v1/consumer/projects/{id}/materials/{excerptId} | 关联或置顶 |
| DELETE | /api/v1/consumer/projects/{id}/materials/{excerptId} | 仅解除项目关联；删除本体另行授权 |

注意：DELETE 端点的实现属于破坏性能力，即使只是解除关联，也必须证明不会删除 source_document；删除素材本体不进入本计划。

### 7.3 稿件与建议

| Method | Path | 语义 |
|---|---|---|
| GET | /api/v1/consumer/projects/{id}/draft | 读取 document + revision |
| PUT | /api/v1/consumer/projects/{id}/draft | 乐观并发自动保存 |
| POST | /api/v1/consumer/projects/{id}/suggestions | 对选区生成建议 |
| POST | /api/v1/consumer/projects/{id}/suggestions/{sid}/accept | 原子接受建议 |
| POST | /api/v1/consumer/projects/{id}/suggestions/{sid}/reject | 记录拒绝，不改稿 |

### 7.4 平台预览与检查

| Method | Path | 语义 |
|---|---|---|
| GET | /api/v1/consumer/projects/{id}/variants | 返回各平台最新 version |
| POST | /api/v1/consumer/projects/{id}/variants/{channel}/generate | 从固定 master snapshot 生成 |
| POST | /api/v1/consumer/projects/{id}/variants/{channel}/regenerate | 只新建当前 channel version |
| GET | /api/v1/consumer/projects/{id}/review | 返回口语化检查 view model |
| POST | /api/v1/consumer/projects/{id}/review/{issueId}/keep | 用户确认保留该表达 |
| POST | /api/v1/consumer/projects/{id}/prepare-export | 冻结导出 snapshot |
| GET | /api/v1/consumer/projects/{id}/events | SSE |

channel 仅允许 wechat_website、xiaohongshu、video_script_60s；marketing_email 暂留企业版，不进入首版 tabs。

### 7.5 C 端 view model

API 返回面向界面的中文语义，不把内部审核对象直接透传：

~~~typescript
type ReviewBubble = {
  id: string
  tone: 'note' | 'attention' | 'blocking'
  message: string
  targetBlockId?: string
  supportingExcerptIds: string[]
  actions: Array<'keep' | 'replace' | 'open_source'>
}
~~~

例如内部 brand issue 可以映射为：

“这句比你的日常表达更用力，确定要保留吗？”

映射文案由 deterministic mapper 控制，不让 LLM直接生成不可预测的系统提示。

---

## 8. 前端信息架构与组件规则

### 8.1 路由

~~~text
src/app/(consumer)/
  app/
    layout.tsx
    page.tsx
    materials/page.tsx
    write/[projectId]/page.tsx
    profile/page.tsx
    settings/page.tsx
~~~

- /app：最近项目、创建入口、素材处理进度。
- /app/write/{projectId}：主创作页，复刻 index-v4 已确认骨架。
- /app/materials：完整素材管理；编辑页只用抽屉。
- /app/profile：个人品牌、受众、语气样本。
- /brandflow：兼容企业版，不与 /app 共用导航。

### 8.2 组件

~~~text
src/components/consumer/
  layout/
    ConsumerHeader.tsx
    ConsumerShell.tsx
  materials/
    MaterialDrawer.tsx
    MaterialCard.tsx
    MaterialSourceDetail.tsx
  editor/
    ConsumerEditor.tsx
    CoreIdeaBlock.tsx
    ManuscriptCanvas.tsx
    SelectionToolbar.tsx
    SuggestionPopover.tsx
    SaveStatus.tsx
    ZoomControl.tsx
  preview/
    PlatformPreview.tsx
    WeChatPreview.tsx
    XiaohongshuPreview.tsx
    VideoScriptPreview.tsx
    PrePublishReview.tsx
    PrimaryActionBar.tsx
~~~

### 8.3 视觉令牌

权威令牌：

- canvas #E9E5DC
- paper #FFFDF8
- paper-warm #F5F1E8
- sand #E9E0CF
- line #DDD6CA
- ink #27241F
- ink-soft #514B43
- muted #8A8278
- brown #6F5D49
- accent #AD5641
- accent-soft #F3E5DF
- success #657764

字号：

- 稿件大标题 28px
- 正文 16px，line-height 2.1
- 核心观点正文 16px
- 核心观点标签 13px
- UI 标签与提示 12—13px

尺寸：

- 稿纸 max-width 720px
- 稿纸 padding 42px 48px 120px
- 核心观点到正文标题 32px
- 右侧预览按稿纸 80%—85% 缩放
- 编辑缩放 75%—150%，仅作用于稿纸容器

交互：

- SelectionToolbar 只有 selection 非折叠、属于稿纸、且编辑器聚焦时出现。
- 位置来自浏览器 selection range 的 bounding rect，经过 viewport collision detection 后置于选区上方或下方。
- 滚动、resize、selectionchange、编辑器 blur 都更新或隐藏工具栏。
- 浮动工具栏不得用 fixed center 或稿纸绝对居中。
- 右上“准备发布”是墨色/棕色次级按钮；编辑区只有“采用这版”使用 accent。
- 发布提示为浅米底 + 左侧细红边，不使用整块红底。

### 8.4 状态管理

- 服务端数据：以 typed fetcher + React hooks 管理；若引入 SWR/TanStack Query，需单独决策，MVP 不因惯例新增状态库。
- draft：本地编辑状态 + debounce save + revision；网络失败保留 dirty buffer。
- zoom、抽屉开关：本地状态，可存 localStorage。
- generation：SSE event cursor；断线指数退避，页面恢复后重新拉 workspace snapshot。
- 禁止整个 workspace 每收到一个 SSE event 就全量刷新；按 event type 精确失效 draft、variant 或 review。
- 首稿生成开始时记录 base revision；生成完成时若用户已经继续编辑，只保存为 candidate version 并提示比较，绝不覆盖较新的 draft。

---

## 9. MindGraph、HRBPilot 与 BrandFlow 的复用边界

| 来源 | 应复用 | 不应复用 | 原因 |
|---|---|---|---|
| BrandFlow 当前代码 | PostgreSQL tenant scope、content versions、lineage、reviews、channel variants、task events、idempotency、model logs、MCP risk gate | B 端侧边栏、八段 Brief、组织角色审批、每阶段 interrupt、全量 workspace 原始对象 | 这是 C 端的后端内核，但不是用户心智模型 |
| MindGraph | 结构化 chunk 思路、稳定 hash/ID、来源位置、版本/状态过滤、引用 trace、冲突先于生成、评测指标 | SQLite/FAISS 全栈、Obsidian frontmatter 注入、默认图扩展、整套本地 Vault 同步 | 素材蒸馏需要来源可信；存储与产品形态不同，不能整包搬运 |
| HRBPilot | scenario 边界思想、tenant middleware 顺序、混合检索与 RRF 思路、幂等 token ledger、结构化 citation metrics、golden evaluation | HR 领域代码、Milvus/MinIO/Celery 全家桶、专有源码直接复制、内存降级进入生产 | 可借鉴治理与评测；MVP 没有足够规模证据支持增加三套基础设施 |

### 9.1 MindGraph 可移植的最小代码

仅在 Phase 2 实测需要后，允许移植并改写：

- StructuredChunker 的稳定 parent/child hash 思路。
- 文档 checksum 与增量去重。
- 引用完整性指标的结构化字段约束。

移植要求：

- 在新文件头保留 MIT 来源说明。
- 不复制 VaultSyncService，因为它会修改源文件 frontmatter，且绑定 SQLite/ProductDatabase。
- 不启用图扩展；只有基础检索在 C 端 golden set 上达标后，才允许单独评估关系扩展。

### 9.2 HRBPilot 只复用原则

- request_id 必须贯穿 BFF、API、provider、event 和 usage ledger。
- usage ledger 对 workspace_id + request_id 唯一，重复 settle 不重复计费。
- 检索或模型基础设施不可用时显式失败，不返回伪造结果。
- citation metrics 读取结构化引用，不从答案文本猜引用。

---

## 10. Phase 与实施任务

## Phase 0 — 规格、工具链与契约基线

目标：先把项目身份、依赖、认证和 API 权威来源对齐。此阶段不做数据库迁移、不做新 UI。

### Task 1: 固化产品边界与主计划

**Files:**

- Modify: AGENTS.md
- Modify: README.md
- Modify: docs/PRD-v2.md
- Create: docs/MASTER_PLAN.md
- Modify: tests/unit/brandflow-contracts.test.mjs

**Step 1: Write the failing contract test**

增加断言：

- docs/MASTER_PLAN.md 存在。
- MASTER_PLAN 明确区分 /app consumer 与 /brandflow enterprise。
- PRD 明确“素材 = 可追溯 excerpt，不等于 verified fact”。
- README 不再把旧博客助手描述为当前主产品。

**Step 2: Run test to verify it fails**

Run: npm.cmd run test:contracts

Expected: FAIL，提示缺失 MASTER_PLAN 或缺少 consumer contract 标识。

**Step 3: Write minimal documentation**

- AGENTS.md 当前阶段改为 Consumer Upgrade Phase 0，并保留 BrandFlow Core 边界。
- docs/MASTER_PLAN.md 只写阶段、门禁、权威文档索引，不复制本文细节。
- PRD 添加 C 端用户旅程、非目标和术语表。

**Step 4: Run test to verify it passes**

Run: npm.cmd run test:contracts

Expected: PASS。

**Step 5: Commit**

~~~bash
git add AGENTS.md README.md docs/PRD-v2.md docs/MASTER_PLAN.md tests/unit/brandflow-contracts.test.mjs
git commit -m "docs: define consumer upgrade boundary"
~~~

### Task 2: 修复包管理与质量基线

**Files:**

- Modify: package.json
- Modify: pnpm-lock.yaml
- Create: jest.config.mjs
- Create: jest.setup.ts
- Modify: tsconfig.json

**Precondition:** node_modules 当前绑定到 D:\.pnpm-store\v11，而当前 pnpm 期望项目内 store。任何删除/重装 node_modules 前必须取得用户授权。

**Step 1: Add scripts and dependency consistency checks**

新增：

- typecheck: tsc --noEmit
- test:unit: jest --runInBand
- test:all: contracts + unit

恢复 package.json 中锁文件已有但声明缺失的 Clerk 依赖；统一 React 与 @types/react 主版本。

**Step 2: Reinstall with one package manager**

Run after approval: corepack pnpm install --frozen-lockfile

Expected: node_modules 与 pnpm-lock.yaml 一致，不自动改写 lock。

**Step 3: Verify baseline**

Run:

- npm.cmd run lint
- npm.cmd run typecheck
- npm.cmd run test:contracts
- npm.cmd run build

Expected: 全部退出 0。若失败，记录为 Phase 0 blocker，不进入功能开发。

**Step 4: Commit**

~~~bash
git add package.json pnpm-lock.yaml jest.config.mjs jest.setup.ts tsconfig.json
git commit -m "chore: restore frontend quality baseline"
~~~

### Task 3: 统一 OpenAPI、Python domain 与 TypeScript 类型

**Files:**

- Modify: docs/brandflow-openapi.yaml
- Modify: package.json
- Modify: pnpm-lock.yaml
- Modify: services/agent-api/src/agent_api/domain/models.py
- Modify: services/agent-api/src/agent_api/api/models.py
- Create: src/types/generated/brandflow-api.ts
- Modify: src/types/brandflow.types.ts
- Modify: src/lib/api/brandflow.ts
- Modify: tests/unit/brandflow-contracts.test.mjs
- Modify: services/agent-api/tests/test_domain_state.py

**Step 1: Write failing drift tests**

- 对比 OpenAPI task status、Python TaskStatus 和 TS generated union。
- 禁止 BrandFlowWorkspace 核心字段使用 Record<string, unknown>。

**Step 2: Run RED**

Run:

- npm.cmd run test:contracts
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_domain_state.py -q

Expected: 当前状态集合漂移导致失败。

**Step 3: Make OpenAPI authoritative**

- 把完整 task lifecycle 放入同一个 schema。
- 以项目 devDependency 安装 openapi-typescript，不做全局安装。
- 用 openapi-typescript 生成 src/types/generated/brandflow-api.ts。
- 手写 brandflow.types.ts 只保留 UI view model，不再复制服务端 enum。

**Step 4: Run GREEN**

Run:

- npm.cmd run test:contracts
- npm.cmd run typecheck
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_domain_state.py -q

**Step 5: Commit**

~~~bash
git add docs/brandflow-openapi.yaml package.json pnpm-lock.yaml services/agent-api/src/agent_api/domain/models.py services/agent-api/src/agent_api/api/models.py src/types src/lib/api/brandflow.ts tests/unit/brandflow-contracts.test.mjs services/agent-api/tests/test_domain_state.py
git commit -m "refactor: make openapi the shared contract"
~~~

### Phase 0 Gate

- MASTER_PLAN 存在且产品术语一致。
- lint、typecheck、build、contract tests 通过。
- package.json 与 pnpm-lock.yaml 一致。
- 状态 enum 无手写漂移。
- 用户明确回复“继续”。

---

## Phase 1 — 真实身份与个人 workspace

目标：让 C 端每个请求都有真实用户与稳定 workspace，不再匿名或伪登录。

### Task 4: 建立 authenticated BFF 与个人 principal

**Files:**

- Create: src/app/api/brandagent/[...path]/route.ts
- Create: src/lib/api/server-agent-api.ts
- Create: src/middleware.ts
- Modify: src/lib/api/brandflow.ts
- Modify: src/hooks/useBrandFlow.ts
- Modify: next.config.js
- Modify: services/agent-api/src/agent_api/api/security.py
- Modify: services/agent-api/src/agent_api/api/bootstrap.py
- Modify: services/agent-api/tests/test_clerk_security.py
- Modify: services/agent-api/tests/test_api.py
- Create: tests/unit/consumer-auth.test.mjs

**Step 1: Write failing tests**

- 无 session 的 /api/brandagent 返回 401。
- BFF 转发 Authorization、Idempotency-Key、Last-Event-ID 和 request id。
- 无 organization 的 Clerk user 派生稳定 personal workspace UUID。
- organization token 仍按现有 B 端 workspace 解析。
- useBrandFlow 不再返回硬编码 true。

**Step 2: Run RED**

Run:

- npm.cmd run test:contracts
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_clerk_security.py services\agent-api\tests\test_api.py -q

**Step 3: Implement minimal auth bridge**

- BFF 从 Clerk server auth 获取 token，后端 URL 只在服务端读取。
- FastAPI Principal 增加 experience: personal / organization。
- personal workspace id 使用 UUID5(namespace, brandagent:personal:{sub})。
- bootstrap 以 workspace_id + user_id 幂等。
- 保留 dev auth，但必须显式 BRANDFLOW_AUTH_MODE=dev；生产默认 fail closed。

**Step 4: Run GREEN**

Run:

- npm.cmd run test:all
- npm.cmd run typecheck
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_clerk_security.py services\agent-api\tests\test_api.py -q

**Step 5: Commit**

~~~bash
git add src/app/api/brandagent src/lib/api src/middleware.ts src/hooks/useBrandFlow.ts next.config.js services/agent-api/src/agent_api/api services/agent-api/tests tests/unit
git commit -m "feat: add authenticated personal workspace gateway"
~~~

### Phase 1 Gate

- 浏览器不能绕过 BFF 直接调用受保护 FastAPI。
- personal 与 organization workspace 均有隔离测试。
- anonymous 旧路由未被新 /app 引用。
- 没有环境变量真实值写入仓库。
- 用户明确回复“继续”。

---

## Phase 2 — Consumer 数据扩展与素材闭环

目标：让“素材抽屉”展示真实蒸馏素材，并能回到原始来源。

### Task 5: 新增 additive consumer migration

**Files:**

- Create after explicit approval: docs/migrations/003_consumer_experience.sql
- Create: tests/unit/consumer-migration-checks.sql
- Create: tests/unit/consumer-migration-docker.test.mjs
- Modify: package.json

**Step 1: Write failing migration contract**

检查：

- 七张新表与所有外键。
- 每张业务表都有 workspace_id。
- editor_suggestions 有 selected_text_hash。
- usage_ledger 对 workspace_id + request_id 唯一。
- migration 不包含 DROP、RENAME、TRUNCATE。
- 旧 001/002 schema 与 B 端 tests 保持通过。

**Step 2: Run RED**

Run: npm.cmd run test:db:consumer

Expected: 003 文件不存在。

**Step 3: Request approval**

数据库 schema 变更属于红线。没有明确批准，不创建 003、不运行 Docker migration。

**Step 4: Write additive SQL and run GREEN**

Run:

- npm.cmd run test:db
- npm.cmd run test:db:consumer

**Step 5: Commit**

~~~bash
git add docs/migrations/003_consumer_experience.sql tests/unit/consumer-migration-checks.sql tests/unit/consumer-migration-docker.test.mjs package.json
git commit -m "feat: add consumer experience schema"
~~~

### Task 6: 实现素材导入、解析、蒸馏与项目关联

**Files:**

- Create: services/agent-api/src/agent_api/domain/consumer.py
- Create: services/agent-api/src/agent_api/application/materials.py
- Create: services/agent-api/src/agent_api/repositories/postgres_materials.py
- Create: services/agent-api/src/agent_api/api/consumer.py
- Modify: services/agent-api/src/agent_api/api/main.py
- Modify: services/agent-api/src/agent_api/runtime.py
- Modify: services/agent-api/pyproject.toml
- Modify: docs/brandflow-openapi.yaml
- Create: services/agent-api/tests/test_consumer_materials.py
- Create: services/agent-api/tests/test_material_security.py
- Modify: tests/unit/brandflow-contracts.test.mjs

**Step 1: Write failing service tests**

覆盖：

- text 导入 checksum 去重。
- 相同文本重复请求幂等。
- chunk id/hash 稳定。
- excerpt 必须引用当前 workspace 可见的 document/chunk。
- 任何跨 workspace document id 返回 404，不泄露存在性。
- URL 导入拒绝 localhost、私网、重定向到私网、非 http/https。
- upload 拒绝伪造 MIME、超限文件、加密 PDF 和宏文档。
- 蒸馏失败保留原始素材并返回可重试状态，不生成伪 excerpt。

**Step 2: Run RED**

Run: services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_consumer_materials.py services\agent-api\tests\test_material_security.py -q

**Step 3: Implement ports and adapters**

- MaterialParser protocol：parse_text、parse_file。
- MaterialDistiller protocol：输入 chunks，输出结构化 excerpts。
- 先支持 text、md、txt；PDF/DOCX 只有添加 pypdf/python-docx 并完成安全测试后启用。
- 不使用 Celery/Milvus；任务量未达到阈值前，沿用现有事件与 worker 运行方式。
- excerpt 生成结果必须计算 provenance_hash。

**Step 4: Add API and events**

事件：

- consumer.material.imported.v1
- consumer.material.parsing.v1
- consumer.material.distilled.v1
- consumer.material.failed.v1

public payload 只含 material id、状态、进度和安全错误码，不含原始全文。

**Step 5: Run GREEN**

Run:

- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests -q
- npm.cmd run test:contracts

**Step 6: Commit**

~~~bash
git add services/agent-api/src services/agent-api/tests services/agent-api/pyproject.toml docs/brandflow-openapi.yaml tests/unit/brandflow-contracts.test.mjs
git commit -m "feat: add traceable consumer materials"
~~~

### Task 7: 建立素材库页面与编辑页抽屉

**Files:**

- Create: src/app/(consumer)/app/materials/page.tsx
- Create: src/components/consumer/materials/MaterialDrawer.tsx
- Create: src/components/consumer/materials/MaterialCard.tsx
- Create: src/components/consumer/materials/MaterialSourceDetail.tsx
- Create: src/lib/api/consumer.ts
- Create: src/hooks/useConsumerMaterials.ts
- Create: src/types/consumer.types.ts
- Create: tests/unit/consumer-materials.test.tsx
- Modify: tests/e2e/brandflow-primary-journeys.spec.ts

**Step 1: Write failing UI tests**

- Drawer 默认收起。
- 卡片只显示摘要与标签，不显示编号、来源日期和系统状态。
- 点击卡片才展开来源详情。
- 处理中、失败、空状态都有可行动文案。
- 关联素材后状态来自 API response。

**Step 2: Run RED**

Run: npm.cmd run test:unit -- consumer-materials

**Step 3: Implement the smallest real UI**

先完成真实数据与交互，不实现编辑页其它区域。

**Step 4: Run GREEN**

Run:

- npm.cmd run test:unit -- consumer-materials
- npm.cmd run typecheck
- npm.cmd run lint

**Step 5: Commit**

~~~bash
git add src/app/(consumer)/app/materials src/components/consumer/materials src/lib/api/consumer.ts src/hooks/useConsumerMaterials.ts src/types/consumer.types.ts tests/unit/consumer-materials.test.tsx tests/e2e/brandflow-primary-journeys.spec.ts
git commit -m "feat: add consumer material drawer"
~~~

### Phase 2 Gate

- 任一 excerpt 可追溯到 document + chunk。
- 没有来源的 AI 摘要不会显示为可引用素材。
- 跨 workspace 读取测试通过。
- 素材抽屉符合已确认视觉与渐进展示。
- 用户明确回复“继续”。

---

## Phase 3 — 稿纸、自动保存与选区改写

目标：把中心稿纸变成真实可编辑、可恢复、可安全调用 AI 的主工作区。

### Task 8: 实现项目、draft revision 与 adopt snapshot

**Files:**

- Create: services/agent-api/src/agent_api/application/consumer_projects.py
- Create: services/agent-api/src/agent_api/application/drafts.py
- Create: services/agent-api/src/agent_api/application/draft_generation.py
- Create: services/agent-api/src/agent_api/repositories/postgres_consumer_projects.py
- Create: services/agent-api/src/agent_api/workflow/consumer_graph.py
- Modify: services/agent-api/src/agent_api/api/consumer.py
- Modify: docs/brandflow-openapi.yaml
- Create: services/agent-api/tests/test_consumer_projects.py
- Create: services/agent-api/tests/test_consumer_drafts.py

**Step 1: Write RED tests**

- 新项目同时创建 content_task、content_brief、consumer_project、consumer_draft。
- project title/core idea 可独立更新。
- baseRevision 不匹配返回 409，不覆盖服务器稿件。
- adopt 创建 immutable master_draft version 与 blocks。
- 重复 adopt 同一 revision 幂等，不能生成重复 version。
- draft autosave 不创建 content_version。
- generate draft 固定 core idea、linked excerpts 和 base revision，并先产出 candidate content_version。
- 生成完成时 revision 未变才允许应用到 draft；revision 已变化只发 candidate_ready event，不覆盖新稿。
- apply candidate 再次做 revision compare-and-swap。
- 跨 workspace project id 返回 404。

**Step 2: Implement transaction boundary**

- create project 一次事务。
- update draft 使用 SELECT FOR UPDATE 或 revision compare-and-swap。
- adopt 一次事务内写 version、blocks、project active pointer 和用户动作 event。
- consumer_graph 只编排 collect linked excerpts -> generate candidate -> deterministic review -> persist candidate，不包含企业审批 interrupt。

**Step 3: Run GREEN**

Run:

- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_consumer_projects.py services\agent-api\tests\test_consumer_drafts.py -q
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests -q

**Step 4: Commit**

~~~bash
git add services/agent-api/src/agent_api/application services/agent-api/src/agent_api/repositories services/agent-api/src/agent_api/api/consumer.py services/agent-api/tests docs/brandflow-openapi.yaml
git commit -m "feat: add revision-safe consumer drafts"
~~~

### Task 9: 实现选区建议与 stale-selection 防护

**Files:**

- Create: services/agent-api/src/agent_api/application/editorial_assist.py
- Create: services/agent-api/src/agent_api/repositories/postgres_suggestions.py
- Modify: services/agent-api/src/agent_api/api/consumer.py
- Modify: services/agent-api/src/agent_api/providers/base.py
- Modify: services/agent-api/src/agent_api/providers/logged.py
- Create: services/agent-api/tests/test_editorial_assist.py
- Modify: docs/brandflow-openapi.yaml

**Step 1: Write RED tests**

- expand、replace_example、shorten 三种 action 有固定结构化 prompt。
- provider 输出不能引入未关联素材中的新事实；若建议包含事实，返回 supportingExcerptIds。
- accept 前校验 revision、block id、offset、hash。
- stale selection 返回 409 且 draft 不变。
- accept 重复请求幂等。
- provider 超时或格式错误不修改 draft。

**Step 2: Implement suggestion proposal**

- 只把选区、必要的上下文句、核心观点、已关联 excerpts 传给模型。
- 不把整个素材库或整个 workspace 发送给模型。
- prompt 放入 services/agent-api 的 provider/application 模块，不放 API route。
- logged provider 写 input/output tokens、latency、prompt version。

**Step 3: Implement atomic accept**

- 服务器按 canonical document 替换字符区间。
- 写新 draft revision。
- 写 content_version snapshot。
- suggestion -> accepted。
- task event 记录用户 action、target hash 和 suggestion id；不伪装成企业审批。

**Step 4: Run GREEN**

Run:

- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_editorial_assist.py -q
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests -q

**Step 5: Commit**

~~~bash
git add services/agent-api/src/agent_api/application/editorial_assist.py services/agent-api/src/agent_api/repositories/postgres_suggestions.py services/agent-api/src/agent_api/api/consumer.py services/agent-api/src/agent_api/providers services/agent-api/tests/test_editorial_assist.py docs/brandflow-openapi.yaml
git commit -m "feat: add anchored editorial suggestions"
~~~

### Task 10: 构建 C 端稿纸与真实 selection toolbar

**Files:**

- Create: src/app/(consumer)/app/layout.tsx
- Create: src/app/(consumer)/app/write/[projectId]/page.tsx
- Create: src/components/consumer/layout/ConsumerHeader.tsx
- Create: src/components/consumer/layout/ConsumerShell.tsx
- Create: src/components/consumer/editor/ConsumerEditor.tsx
- Create: src/components/consumer/editor/CoreIdeaBlock.tsx
- Create: src/components/consumer/editor/ManuscriptCanvas.tsx
- Create: src/components/consumer/editor/SelectionToolbar.tsx
- Create: src/components/consumer/editor/SuggestionPopover.tsx
- Create: src/components/consumer/editor/SaveStatus.tsx
- Create: src/components/consumer/editor/ZoomControl.tsx
- Create: src/components/consumer/editor/consumer-editor.module.css
- Create: src/styles/consumer-tokens.css
- Create: src/hooks/useConsumerDraft.ts
- Create: tests/unit/consumer-editor.test.tsx
- Create: tests/e2e/consumer-editor.spec.ts
- Modify: package.json
- Modify: pnpm-lock.yaml

**Step 1: Write RED component tests**

- 稿纸 max-width 720px。
- 核心观点到正文标题间距 32px。
- 选区为空时 toolbar 不存在。
- 选中段落文本时出现三个白底药丸按钮。
- selection 改变时 toolbar 的 transform 来自 range rect，不是固定中心。
- blur、Escape、collapsed selection 隐藏。
- zoom 只改变稿纸 transform/scale，不改变左右面板。
- 保存 debounce，冲突时保留本地稿并提供恢复入口。

**Step 2: Add editor dependencies after approval**

建议依赖：

- @tiptap/react
- @tiptap/starter-kit
- @tiptap/extension-placeholder

不引入完整 block editor UI 套件。

**Step 3: Implement position algorithm**

1. 从 editor state 取得 from/to。
2. 映射到 DOM Range。
3. 读取 range.getBoundingClientRect。
4. 计算 toolbar 宽度。
5. 优先放选区上方 8px；空间不足放下方。
6. clamp 到 viewport 左右 12px。
7. 相对 viewport 用 fixed 定位；随 scroll、resize、selection update 重算。

**Step 4: Implement autosave**

- 800ms debounce。
- 页面离开前有 dirty draft 时触发 sendBeacon 不可靠，因此先立即 flush fetch；失败写入 sessionStorage 恢复缓存。
- 后端确认 revision 后才显示“已保存”。
- 409 时停止覆盖，显示“稿件在别处有更新”，加载 diff/恢复选择。

**Step 5: Run GREEN**

Run:

- npm.cmd run test:unit -- consumer-editor
- npm.cmd run typecheck
- npm.cmd run lint
- npm.cmd run test:e2e -- tests/e2e/consumer-editor.spec.ts

**Step 6: Commit**

~~~bash
git add src/app/(consumer) src/components/consumer src/styles/consumer-tokens.css src/hooks/useConsumerDraft.ts tests/unit/consumer-editor.test.tsx tests/e2e/consumer-editor.spec.ts package.json pnpm-lock.yaml
git commit -m "feat: build the consumer manuscript editor"
~~~

### Phase 3 Gate

- 连续编辑、刷新、断网恢复、409 冲突都有测试。
- 工具栏确实跟随选区，不在稿纸中间固定。
- AI 建议失败不会改变当前稿。
- 采用版本可追溯到 draft revision。
- 用户明确回复“继续”。

---

## Phase 4 — 平台预览与发布前检查

目标：右侧面板显示真实平台版本和口语化检查，不暴露 B 端审批术语。

### Task 11: 拆分安全预览与高风险发布

**Files:**

- Create: services/agent-api/src/agent_api/application/platform_variants.py
- Create: services/agent-api/src/agent_api/application/consumer_reviews.py
- Modify: services/agent-api/src/agent_api/application/channels.py
- Modify: services/agent-api/src/agent_api/api/consumer.py
- Modify: services/brand-tools-mcp/src/brand_tools_mcp/server.py
- Modify: docs/brandflow-openapi.yaml
- Create: services/agent-api/tests/test_consumer_variants.py
- Create: services/agent-api/tests/test_consumer_reviews.py
- Modify: services/brand-tools-mcp/tests/test_security.py

**Step 1: Write RED tests**

- 普通 preview/render 不要求 approval。
- generate variant 必须绑定明确 master_content_version_id。
- regenerate 只新增同一 channel version，不修改 master。
- 渠道版本不能新增无 lineage 的事实性主张。
- prepare export 固定 snapshot；真正 publish/high-risk MCP 仍要求审批。
- review mapper 输出 ReviewBubble，不透传事实与主张一致等机器文案。

**Step 2: Implement variant service**

- 复用 channel spec、content_versions、content_lineage。
- C 端默认三渠道。
- 生成失败时保留上一个成功版本。
- 同一 master hash + channel + prompt version 可命中幂等结果。

**Step 3: Implement deterministic review mapper**

映射 factual、citation、brand、channel_format、compliance 到少量口语化模板。

blocking 只用于：

- 未支持事实主张。
- 明确合规禁止项。
- 导出 snapshot 与当前采用版不一致。

**Step 4: Run GREEN**

Run:

- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_consumer_variants.py services\agent-api\tests\test_consumer_reviews.py -q
- services\brand-tools-mcp\..\agent-api\.venv\Scripts\python.exe -m pytest services\brand-tools-mcp\tests\test_security.py -q
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests -q

**Step 5: Commit**

~~~bash
git add services/agent-api/src/agent_api/application services/agent-api/src/agent_api/api/consumer.py services/agent-api/tests services/brand-tools-mcp/src services/brand-tools-mcp/tests docs/brandflow-openapi.yaml
git commit -m "feat: separate platform preview from publishing"
~~~

### Task 12: 实现右侧平台预览和检查气泡

**Files:**

- Create: src/components/consumer/preview/PlatformPreview.tsx
- Create: src/components/consumer/preview/WeChatPreview.tsx
- Create: src/components/consumer/preview/XiaohongshuPreview.tsx
- Create: src/components/consumer/preview/VideoScriptPreview.tsx
- Create: src/components/consumer/preview/PrePublishReview.tsx
- Create: src/components/consumer/preview/PrimaryActionBar.tsx
- Create: src/components/consumer/preview/consumer-preview.module.css
- Create: src/hooks/usePlatformVariants.ts
- Create: tests/unit/consumer-preview.test.tsx
- Modify: tests/e2e/consumer-editor.spec.ts

**Step 1: Write RED tests**

- 标题为“平台预览”。
- 公众号为浅底黑字文章，小红书为白底卡片与标签，口播为脚本文本。
- 整个预览视觉比例不超过编辑稿纸的 85%。
- 检查区标题为“发布前再看一眼”。
- 提示是浅米底 + 左侧细红边。
- “采用这版”在左且为唯一红色主按钮；“重新生成”在右且为次按钮。
- “准备发布”是棕/墨色次按钮。

**Step 2: Implement real data states**

- no master snapshot：提示先采用当前稿。
- generating：保留上一版并显示非阻塞进度。
- failed：保留上一版，提供重试。
- review empty：不显示虚假的“全部通过”，显示“暂未发现需要你确认的地方”。

**Step 3: Run GREEN**

Run:

- npm.cmd run test:unit -- consumer-preview
- npm.cmd run typecheck
- npm.cmd run lint
- npm.cmd run test:e2e -- tests/e2e/consumer-editor.spec.ts

**Step 4: Commit**

~~~bash
git add src/components/consumer/preview src/hooks/usePlatformVariants.ts tests/unit/consumer-preview.test.tsx tests/e2e/consumer-editor.spec.ts
git commit -m "feat: add human platform previews"
~~~

### Phase 4 Gate

- 平台预览不是深色渲染器，也不展示技术元标签。
- 每个渠道版本绑定母稿 snapshot 和 lineage。
- 普通预览不需要 B 端审批；真正发布仍 fail closed。
- 三种平台有独立结构，不是同一段文字换壳。
- 用户明确回复“继续”。

---

## Phase 5 — 配额、评测、完整旅程与兼容迁移

目标：证明产品可控、可计费、可回归，再决定旧界面何时下线。

### Task 13: 实现 usage ledger 与 C 端配额

**Files:**

- Create: services/agent-api/src/agent_api/application/usage.py
- Create: services/agent-api/src/agent_api/repositories/postgres_usage.py
- Modify: services/agent-api/src/agent_api/providers/logged.py
- Modify: services/agent-api/src/agent_api/api/consumer.py
- Create: services/agent-api/tests/test_consumer_usage.py
- Modify: src/lib/quota.ts
- Modify: src/app/api/quota/route.ts

**Step 1: Write RED tests**

- request id 重复 settle 不重复计费。
- provider 有实测 token 时记录 measured；无数据时标 estimated。
- 配额不足在调用模型前拒绝，不影响普通 draft 保存。
- 失败调用按策略 settle 或 refund。
- 个人 workspace 不能查询他人用量。

**Step 2: Implement one authority**

FastAPI usage ledger 成为新 C 端唯一权威。旧 Supabase quota endpoint 进入 deprecated 状态，不双写。

**Step 3: Run GREEN**

Run:

- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_consumer_usage.py -q
- npm.cmd run test:all

**Step 4: Commit**

~~~bash
git add services/agent-api/src/agent_api/application/usage.py services/agent-api/src/agent_api/repositories/postgres_usage.py services/agent-api/src/agent_api/providers/logged.py services/agent-api/src/agent_api/api/consumer.py services/agent-api/tests/test_consumer_usage.py src/lib/quota.ts src/app/api/quota/route.ts
git commit -m "feat: add idempotent consumer usage ledger"
~~~

### Task 14: 建立 C 端 golden evaluation

**Files:**

- Create: services/agent-api/evaluation/consumer_golden_v1.jsonl
- Create: services/agent-api/src/agent_api/evaluation/consumer_metrics.py
- Create: services/agent-api/tests/test_consumer_evaluation.py
- Modify: services/agent-api/src/agent_api/evaluation/metrics.py
- Modify: docs/MASTER_PLAN.md

**Dataset minimum:**

- 15 条选区扩写。
- 15 条换例子。
- 15 条精简。
- 15 条小红书改写。
- 15 条微信改写。
- 15 条 60 秒口播。
- 10 条无证据拒绝/降级。
- 10 条 stale selection / conflict 工程样例。

**Metrics:**

- excerpt attribution precision。
- unsupported claim rate。
- core idea preservation。
- channel format pass rate。
- shorten compression ratio。
- suggestion acceptance rate 只做产品指标，不做离线质量真值。
- latency、tokens、estimated cost。

**Step 1: Write schema and failing metric tests**

Golden 每条必须有 dataset_version、case_id、input、expected_constraints、source_excerpt_ids；不能把生产素材写入数据集。

**Step 2: Implement deterministic metrics**

来源指标读取 structured supportingExcerptIds，不从生成文本猜测。

**Step 3: Run GREEN**

Run: services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests\test_consumer_evaluation.py -q

**Step 4: Commit**

~~~bash
git add services/agent-api/evaluation services/agent-api/src/agent_api/evaluation services/agent-api/tests/test_consumer_evaluation.py docs/MASTER_PLAN.md
git commit -m "test: add consumer writing evaluation gate"
~~~

### Task 15: 完成 E2E、可访问性和兼容窗口

**Files:**

- Create: tests/e2e/consumer-primary-journey.spec.ts
- Create: tests/e2e/consumer-recovery.spec.ts
- Modify: tests/e2e/brandflow-primary-journeys.spec.ts
- Modify: src/app/page.tsx
- Modify: src/app/brandflow/page.tsx
- Modify: README.md
- Modify: docs/deployment/runbook.md

**Step 1: Add E2E journeys**

正常：

1. 登录并 bootstrap personal workspace。
2. 导入文本素材并等待 excerpts。
3. 创建项目、编辑核心观点和正文。
4. 选择一句话、生成建议、采用。
5. 采用母稿，生成三个平台预览。
6. 查看检查气泡并准备导出。

异常：

- provider 超时。
- SSE 断线重连。
- autosave 409。
- 素材解析失败。
- 渠道生成失败但保留旧预览。
- quota exhausted 只阻止 AI，不阻止手工编辑与导出已有稿。

边界：

- 空素材库。
- 超长中文段落。
- selection 跨两个 block。
- 75% 与 150% 缩放。
- 窄桌面宽度。
- 键盘操作与 focus order。

**Step 2: Run full gate**

Run:

- npm.cmd run test:contracts
- npm.cmd run test:unit
- npm.cmd run typecheck
- npm.cmd run lint
- npm.cmd run build
- npm.cmd run test:e2e
- services\agent-api\.venv\Scripts\python.exe -m pytest services\agent-api\tests -q
- services\brand-tools-mcp\..\agent-api\.venv\Scripts\python.exe -m pytest services\brand-tools-mcp\tests -q

**Step 3: Independent reviews**

- code-reviewer：状态同步、并发、组件边界、重复逻辑。
- security-reviewer：BFF token、SSRF、上传、tenant filter、日志脱敏、高风险工具边界。
- designer review：与 index-v4 骨架对照，检查 AI 味回流、视觉层级、真实平台预览。

**Step 4: Compatibility decision**

只有以下数据满足后才讨论默认首页从 /brandflow 或旧 dashboard 切换到 /app：

- C 端 E2E 全绿。
- 旧 BrandFlow E2E 仍绿。
- 关键生成成功率、unsupported claim rate、autosave conflict 恢复达标。
- 有回滚开关，可恢复旧入口。

删除旧路由不在本计划授权范围。先标 deprecated，至少保留一个发布周期。

**Step 5: Commit**

~~~bash
git add tests/e2e src/app/page.tsx src/app/brandflow/page.tsx README.md docs/deployment/runbook.md
git commit -m "test: verify consumer primary journeys"
~~~

### Phase 5 Gate

- 全部质量命令有当前 checkout 证据。
- consumer golden gate 达标，阈值写入 MASTER_PLAN。
- B 端兼容旅程仍通过。
- 安全审查没有 P0/P1。
- 用户单独批准入口切换、部署或任何旧路由删除。

---

## 11. 推荐实施顺序与产品切片

| 顺序 | 可演示结果 | 后端完成 | 前端完成 | 不可跳过门禁 |
|---|---|---|---|---|
| 0 | 项目身份与契约一致 | 状态 schema 对齐 | 工具链可构建 | baseline 全绿 |
| 1 | 真实个人登录 | personal workspace | /app 受保护 | tenant 隔离 |
| 2 | 素材抽屉有真实内容 | import/chunk/excerpt | drawer/materials | provenance |
| 3 | 中心稿纸可稳定编辑 | draft revision/adopt | Tiptap/autosave | conflict recovery |
| 4 | 选区工具真正跟随文字 | suggestion/anchor | floating toolbar | stale-selection |
| 5 | 三平台真实预览 | variant/lineage/review | preview/check bubble | preview != publish |
| 6 | 可试用、可计费、可回滚 | ledger/eval/events | 完整旅程 | full gate |

每个切片都同时交付 UI、API、服务和测试，禁止先做完所有页面再补假接口，也禁止先扩建后端半年却没有可验证用户旅程。

---

## 12. 风险与必须提前做的决定

### P0 风险

1. 认证与 workspace 混乱
   - 当前客户端伪登录和透明 rewrite 必须先停用。
   - personal workspace 与 organization workspace 需要同一 Principal 契约。

2. 草稿覆盖
   - 没有 revision compare-and-swap 就上线自动保存，会直接丢用户内容。

3. 选区漂移
   - 只传 selectedText 而不传 block/range/hash，会把建议应用到错误位置。

4. 预览与发布混淆
   - 若沿用 B 端 preview approval，C 端会被审批卡死；若移除所有门禁，未来直接发布会失守。

5. 素材被错误标为事实
   - excerpt 是候选材料，verified_fact 才是治理后的事实，两者必须分表。

### P1 风险

1. 双数据源：旧 Supabase articles/quota 与新 FastAPI consumer 不能双写。
2. OpenAPI 漂移：继续手写 TS/Python 类型会重复当前问题。
3. 组件复用过度：从 1380 行 B 端 workspace 继续加 if consumer 会形成不可维护分支。
4. 基础设施膨胀：没有负载证据前引入 Celery、Milvus、MinIO，会增加部署和故障面。
5. 模型成本：选区操作频繁，必须在调用前查 quota，并只发送最小上下文。

### 需要用户明确批准的节点

- 重装 node_modules 或改变包管理 store。
- 创建或执行 003 migration。
- 修改 .env.example 以外的环境配置。
- 引入对象存储或新的外部服务。
- 默认入口切到 /app。
- 部署到任何环境。
- 删除旧 dashboard、BrandFlow 路由或数据库对象。

---

## 13. Definition of Done

整个升级只有同时满足以下条件才算完成：

### 产品

- 新用户在 5 分钟内能完成“导入素材—写核心观点—编辑—选区改写—平台预览—采用”。
- 界面不出现 task id、workflow node、approval、lineage、native preview、linked sources 等技术语言。
- 三个平台是结构真实的内容预览，不是同一张深色卡片。

### 前端

- 选区工具栏锚定真实 selection，collision 与滚动行为正确。
- 自动保存有 revision、dirty、saving、saved、conflict、error 六种真实状态。
- 稿纸、预览、抽屉的缩放和布局互不污染。
- keyboard、focus、contrast 和 reduced motion 通过检查。

### 后端

- 每个 C 端对象有 workspace filter。
- draft 不可静默覆盖。
- excerpt 可追溯。
- suggestion 可审计且 stale-safe。
- variant 绑定 master snapshot。
- preview 低风险，publish 高风险。
- model usage 可幂等结算。

### 质量

- contract、unit、typecheck、lint、build、E2E、agent-api pytest、MCP pytest 全绿。
- consumer golden dataset 有版本和 hash。
- 独立 code/security/design review 完成，P0/P1 清零。
- runbook 写明启动、恢复、回滚、数据边界与已知限制。

---

## 14. 执行建议

第一步只执行 Phase 0，不碰数据库和新界面。原因不是保守，而是当前 package/lock、认证、OpenAPI 与项目身份都存在真实漂移；在这些基础上直接开发，会把后续每个界面问题放大成联调问题。

Phase 0 完成后，按“身份 → 素材 → 稿纸 → 选区建议 → 平台预览 → 配额评测”的顺序逐阶段推进。不要先做 landing page、价格页或更多视觉方案；当前最稀缺的不是页面数量，而是一个前后端闭环、可恢复、可信且不暴露 B 端复杂性的核心写作旅程。
