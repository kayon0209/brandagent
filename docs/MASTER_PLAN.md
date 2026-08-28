# MASTER_PLAN — BrandAgent Consumer Upgrade

> 本文件是阶段与门禁的权威索引，不复制规格细节。
> 升级规格全文：[docs/superpowers/plans/2026-08-28-consumer-brandagent-upgrade.md](./superpowers/plans/2026-08-28-consumer-brandagent-upgrade.md)（第 1—9 节为产品与架构权威规格）。

## 产品边界

| 界面 | 路由 | 面向用户 | 状态 |
|---|---|---|---|
| 个人创作工作台 | `/app`（`src/app/(consumer)/app/*`） | 个人创作者 | 升级目标，逐 Phase 交付 |
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

推进规则：一次只做一个 Phase；门禁全部通过且用户明确回复「继续」后，才进入下一 Phase。

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
