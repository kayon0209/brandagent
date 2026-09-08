# MASTER_PLAN — BrandAgent Consumer Upgrade

> 本文件是阶段与门禁的权威索引，不复制规格细节。
> 升级规格全文：[docs/superpowers/plans/2026-08-28-consumer-brandagent-upgrade.md](./superpowers/plans/2026-08-28-consumer-brandagent-upgrade.md)（第 1—9 节为产品与架构权威规格）。

## 产品边界

| 界面 | 路由 | 面向用户 | 状态 |
|---|---|---|---|
| 个人创作工作台 | `/app`（实现位于 `src/app/(consumer)/workspace/*`，由 middleware 受保护地内部重写） | 个人创作者 | 升级目标，逐 Phase 交付 |
| 企业审批工作台（BrandFlow） | `/brandflow` | 品牌团队（内容运营 / 品牌审核 / 最终审批） | 兼容窗口保留，不承载 C 端新功能 |
| 旧博客助手 | `(dashboard)`、`api/generate/*` | — | 冻结，不再新增功能；下线需单独授权 |

个人创作链路不暴露 task、workflow node、approval requirement、lineage、model log 等系统词；这些对象只作为后台能力存在。

## 阶段与门禁

| Phase | 目标 | 不可跳过的门禁 |
|---|---|---|
| Phase 0 | 规格、工具链与契约基线 | lint / typecheck / build / contract tests 全绿；package.json 与 pnpm-lock.yaml 一致；状态 enum 无手写漂移 |
| Phase 1 | 真实身份与个人 workspace | 浏览器不能绕过 BFF 直连受保护 FastAPI；personal / organization 隔离测试通过；新路由不引用匿名登录 |
| Phase 2 | Consumer 数据扩展与素材闭环 | 任一 excerpt 可追溯到 document + chunk；跨 workspace 读取测试通过；素材抽屉符合已确认视觉 |
| Phase 3 | 稿纸、自动保存与选区改写 | 连续编辑 / 刷新 / 断网 / 409 冲突均有测试；工具栏跟随真实选区；AI 建议失败不改稿 |
| Phase 4 | 平台预览与发布前检查 | 渠道版本绑定母稿 snapshot 与 lineage；普通预览免审批，真正发布 fail closed |
| Phase 5 | 配额、评测、完整旅程与兼容迁移 | 全量质量命令有当前 checkout 证据；consumer golden gate 达标；B 端兼容旅程仍绿；安全审查无 P0/P1 |
| Phase 6（候选） | 深度调研与受限多 Agent 取证 | 仅在 Phase 5 完成后单独立项；相对单工作流基线显著提高可引用材料覆盖率，且引用有效性、成本、时延、安全与取消恢复门禁全部达标 |

推进规则：一次只做一个 Phase；门禁全部通过且用户明确回复「继续」后，才进入下一 Phase。

Phase 6 不属于当前 Consumer Upgrade 的默认交付范围。Phase 5 完成只代表具备开展对照实验的基础，不自动授权 Phase 6 的数据库、外部搜索服务、模型预算或产品上线；这些事项届时单独确认。

## Phase 6 立项决定（2026-09-08）

Phase 5 验收已在 checkout `cd1f303` 完成全量证据（前端合同 33 + Jest 73 全绿、生产构建 28 页、agent-api pytest 252 passed 含真实 DB/RLS、MCP pytest 33 passed、真实栈 E2E 4/4）。用户（项目负责人）已于 2026-09-08 明确批准：

1. 直接进入 Phase 6 产品化，不等第二轮 S1/S2 复现实验。第一轮对照实验（`services/agent-api/evaluation/research/results/summary_full_v1.json`，数据集 sha `6cee2586…`）的结论——S2 相对 S1 覆盖率 +1.31（95%CI [0.80, 1.82]，21/29 wins），但搜索成本 2.5×、14 个 S2 tuple 因 Tavily 配额未恢复——按原计划应做第二轮复现再决策；用户选择跳过复现直接产品化。
2. 风险接受声明：覆盖率收益基于单轮实验，尚未复现；产品化后若 S2 成本/时延不可接受，回退路径为保留 S1 单工作流编排（S2 编排器与 S1 共享同一 EvidenceScout 组件，差异只在并行度）。
3. 授权范围：009 号 additive migration（新增 deep research 表，不动旧表）、复用现有 Tavily/GLM 凭据与 usage ledger、/app 内新增调研入口与进度/候选素材视图。外部搜索服务不新购（Tavily 现有凭据）、模型预算沿用现有配额门禁。部署与公网开放仍需单独授权。

Phase 6 完成门禁沿用规格第 10 节（引用校验、Prompt Injection、SSRF、租户隔离、取消与配额测试全部通过），且实验数据集与对比结果继续留档于 evaluation/research/。


## Consumer Golden Gate（Phase 5，consumer_golden_v1）

数据集：`services/agent-api/evaluation/consumer_golden_v1.jsonl`（110 条合成样例：45 选区建议 + 45 渠道改写 + 10 无证据拒绝 + 10 stale/conflict 工程样例；不含任何生产素材）。

| 指标 | 阈值 | 判定来源 |
|---|---|---|
| excerpt attribution precision | = 1.0 | structured `supportingExcerptIds`（不从生成文本猜测） |
| unsupported claim rate | = 0 | 数字断言必须能在 source_texts 中溯源 |
| core idea preservation | = 1.0 | 输出含核心观点前缀，或为核心观点的精简前缀 |
| channel format pass rate | = 1.0 | 三渠道各自结构约束（段落≥2 / 含 # 标签 / 行数≥2） |
| shorten compression pass rate | = 1.0 | 精简输出不得长于原选区 |

suggestion acceptance rate 只作产品指标，不进离线质量真值。门槛由 `agent_api.evaluation.consumer_metrics.GATE_THRESHOLDS` 单点定义，测试 `test_consumer_evaluation.py` 验证。

## 红线（所有 Phase 适用）

- 数据库 schema 变更、环境变量修改、删除旧路由、安装依赖、部署或发布：逐项单独取得用户授权。
- 数据迁移只新增；不删除、不重命名旧表或旧列；旧 B 端接口在兼容窗口内继续工作。
- 任何「完成」结论必须来自当前 checkout 的 test / lint / typecheck / build / E2E 结果，不以原型截图或文档描述代替。

## 权威文档索引

| 文档 | 职责 |
|---|---|
| [升级计划全文](./superpowers/plans/2026-08-28-consumer-brandagent-upgrade.md) | 产品与架构权威规格、任务分解、验收标准 |
| [PRD v2](./PRD-v2.md) | 产品需求：C 端用户旅程、非目标、术语表；B 端 BrandFlow 需求 |
| [brandflow-openapi.yaml](./brandflow-openapi.yaml) | API 权威契约（OpenAPI 3.1），TypeScript / Python 类型以其为准生成或对齐 |
| [AGENTS.md](../AGENTS.md) | 项目协作规范、目录结构、命名与禁止事项 |
| [consumer-ui-concept/index-v4.html](../_sandbox/consumer-ui-concept/index-v4.html) | C 端视觉基线（素材抽屉 + 核心观点 + 稿纸 + 平台预览骨架） |
| [deployment/RUNBOOK.md](./deployment/RUNBOOK.md) | 部署、恢复、回滚与运维 |
