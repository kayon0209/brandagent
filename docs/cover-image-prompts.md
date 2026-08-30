# 三个项目封面图生图指南

> 把每个项目的「视觉特征 + 生图 Prompt」直接复制给 ChatGPT/DALL-E 即可。

---

## 1. BrandFlow（品牌内容智能体）

### 真实 UI 视觉特征（从源码提取）

**设计系统：双轨制**

| 层 | 色板 | 字体 | 风格 |
|---|---|---|---|
| 落地页（Editorial） | Ivory `#FAFAF8` 底 + Gold `#B8860B` 点缀 + Ink `#1A1A1A` 字 | Playfair Display（衬线标题）+ Source Sans 3（正文）+ IBM Plex Mono（标签） | 杂志编辑风：大留白、金色细线分隔、小号大写字母标签 |
| 工作台（Dashboard） | 浅灰 `#f6f7f9` 底 + 蓝 `#3b5ccc` 主色 + 白色卡片 + `#e4e7ec` 边框 | Georgia 衬线标题 + Inter 正文 | 现代 SaaS：左侧 240px 导航栏 + 顶部面包屑、卡片圆角 12px、状态点指示器 |

**布局结构**：
- 左侧栏：蓝色 Logo 方块「B」+ 7 个导航项（概览/任务/知识/品牌/渠道/评估/设置），每项带 Lucide 图标
- 顶部栏：面包屑导航 + 待审批黄色 Badge + 搜索框
- 主区域：白色卡片网格，任务列表带状态圆点（蓝=进行中/绿=完成/橙=等待/红=失败）
- 任务详情：7 步 Stepper + 左右分栏（内容画布 + 上下文面板）

### 推荐封面图 Prompt

```
A modern GitHub project banner for "BrandFlow — AI Agent Content Workbench".

Layout: Wide horizontal banner (1280×480), clean minimalist design.

Left side: A sleek dashboard UI preview showing:
- A left sidebar with a blue square logo "B" and 7 navigation items with subtle icons
- A main content area with white cards on a light gray (#f6f7f9) background
- Task list rows with small colored status dots (blue, green, orange)
- A 7-step horizontal progress indicator (stepper) at the top
- Primary accent color: blue (#3b5ccc)
- Clean typography with Georgia serif headings

Right side: Abstract representation of an AI agent workflow:
- A central node labeled "Master Draft" branching out to 4 channel nodes (WeChat, Weibo, RED, SEO)
- Flow arrows showing: Draft → Multi-channel Rewrite → Validation → Approval Gate
- A checkpoint icon (save/resume) and a shield icon (approval gate)
- Gold accent line (#B8860B) connecting the workflow nodes

Background: Ivory (#FAFAF8) with subtle geometric patterns.
Typography: "BrandFlow" in Playfair Display serif, tagline "AI Agent Content Workbench" in IBM Plex Mono uppercase below.

Style: Professional, editorial, premium SaaS product aesthetic. No photorealistic elements. Flat design with subtle shadows.
```

---

## 2. MindGraph（混合检索问答智能体）

### 真实 UI 视觉特征（从源码提取）

**设计系统：温暖大地色**

| 元素 | 色值 | 说明 |
|---|---|---|
| 品牌主色 | Terracotta `#A84528` | 赤陶橙红，温暖辨识度高 |
| 背景 | Cream `#FBF8F2` | 奶油白底 |
| 卡片底 | Warm beige `#F1E9DC` | 暖米色卡片 |
| 成功 | Forest green `#356859` | 深森绿 |
| 信息 | Teal `#315E74` | 鸭青蓝 |
| 警告 | Mustard `#C28A3D` | 芥末黄 |
| 正文 | Dark brown `#28231F` | 深棕字 |
| 边框 | Tan `#D8CCBC` | 棕褐边框 |

**字体**：IBM Plex Mono（代码/标签）+ 系统默认无衬线
**圆角**：8-24px（大圆角，柔和感）
**框架**：Streamlit 单页应用，居中窄栏布局

### 推荐封面图 Prompt

```
A modern GitHub project banner for "MindGraph — Hybrid Retrieval QA Agent".

Layout: Wide horizontal banner (1280×480), warm and approachable design.

Color palette: Terracotta (#A84528) primary, cream (#FBF8F2) background, warm beige (#F1E9DC) cards, forest green (#356859) accents, teal (#315E74) highlights.

Center: A visual flow diagram showing the RAG pipeline:
- Left: A document icon (representing policy text corpus) with "34 QA pairs" label
- Middle: Three parallel retrieval paths converging:
  1. "FAISS (Dense BGE)" path with a vector embedding icon
  2. "BM25 (Sparse)" path with a keyword matching icon
  3. Both feeding into an "RRF Fusion" merge node
- Right: A knowledge graph with 3-4 nodes connected by edges (one-hop expansion)
- Far right: An LLM node generating an answer with citation badges

Below the flow: A small metrics panel showing:
- "R@5 = 0.587" with a green checkmark
- "Latency: 13ms (hybrid) vs 1293ms (rerank)" with a speed icon
- "4-strategy ablation" label

Style: Warm, scholarly, data-driven aesthetic. Rounded corners (12-16px), soft shadows, IBM Plex Mono for labels and metrics. No photorealistic elements. Flat illustration style with subtle depth.
```

---

## 3. HRBPilot（HR 领域智能体）

### 真实架构特征（从源码提取）

**注意**：HRBPilot 是纯 FastAPI 后端，**没有前端 UI**。封面图应以架构图/数据流为主。

**核心架构**：中间件链 + 5 大 HR 场景

```
Request → RequestID → CORS → TenantContext → Auth → RBAC → SecurityHeaders → Response
```

**5 大场景路由**：
1. `/policy_qa` — 政策问答（RAG: dense/sparse/hybrid + rerank）
2. `/interview_digest` — 面试纪要摘要
3. `/voice_insight` — 员工声音洞察
4. `/weekly_report` — 周报生成
5. `/culture_content` — 文化内容生成

**评测真实数据**（250 样本 golden eval）：
- Guardrail overall: 1.0（注入拦截率 100%）
- Token total: 225,133（占 10M 预算 2.25%）
- 5 场景各 50 样本 + 5 条注入拒答用例

### 推荐封面图 Prompt

```
A modern GitHub project banner for "HRBPilot — HR Domain AI Agent with Guardrails".

Layout: Wide horizontal banner (1280×480), professional enterprise design.

Color scheme: Deep navy (#1a2744) background with white text, teal (#315E74) and gold (#C9A227) accents, green (#356859) for success metrics.

Left side: A vertical middleware chain visualization (top to bottom):
- Request → RequestID → CORS → TenantContext → Auth → RBAC → SecurityHeaders
- Each step shown as a pill/badge with an icon
- A shield icon prominently displayed for the "Guardrails" layer

Center: Five HR scenario cards arranged in a fan/grid layout:
1. "Policy QA" with a document+chat icon
2. "Interview Digest" with a microphone icon
3. "Voice Insight" with a waveform icon
4. "Weekly Report" with a chart icon
5. "Culture Content" with a sparkle icon
- All connected to a central "RAG Pipeline" engine node
- The RAG node shows: Dense + Sparse → Hybrid → Rerank

Right side: A metrics dashboard panel showing:
- "Guardrail: 100%" with a green shield
- "Injection Recall: 1.0" with a lock icon
- "Budget: 2.25% used" with a progress bar (10M tokens)
- "250 samples" with a checkmark

Bottom: A token budget governance bar showing thresholds: 75% (warning) → 90% (critical)

Style: Enterprise, trustworthy, secure. Clean geometric shapes, subtle gradients, monospace font for metrics. No photorealistic elements. Dark theme with glowing accents.
```

---

## 使用说明

1. 复制对应项目的 Prompt，粘贴到 ChatGPT（需支持 DALL-E 3 生图的版本）
2. 如果生图效果不理想，可在 Prompt 末尾追加：`Style references: Linear.app banner, Vercel project cards, Notion hero images`
3. 生成后保存为 `assets/hero-banner.png`（或 `assets/cover.png`），放到对应项目根目录
4. 在 README.md 顶部 `# 项目名` 标题下方加一行：
   ```markdown
   ![BrandFlow](assets/hero-banner.png)
   ```
5. 提交推送即可

## 各项目当前已有 vs 还缺

| 项目 | 架构图 SVG | 封面图 | Demo 截图 |
|---|---|---|---|
| BrandFlow | ✅ 已有 | ❌ 需生图 | ❌ 需运行项目截图 |
| MindGraph | ✅ 已有 | ❌ 需生图 | ❌ 需运行 Streamlit 截图 |
| HRBPilot | ✅ 已有 | ❌ 需生图 | N/A（纯 API，用 Swagger 截图即可） |
