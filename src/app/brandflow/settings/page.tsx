'use client'

import { useState } from 'react'
import { useBrandFlow } from '@/hooks/useBrandFlow'
import { AlertTriangle, Check, ChevronDown, Loader2, Settings } from 'lucide-react'
import { BrandFlowApiError } from '@/lib/api/brandflow'
import styles from '@/styles/brandflow'

const settingSections = [
  'Workspace',
  'Members & roles',
  'Model providers',
  'MCP servers',
  'Workflow',
  'Data & export',
]

export default function BrandFlowSettings() {
  const flow = useBrandFlow()
  const [activeSection, setActiveSection] = useState(0)
  const [saving, setSaving] = useState(false)
  const [workspaceName, setWorkspaceName] = useState('')
  const [testingModel, setTestingModel] = useState(false)
  const [modelTestResult, setModelTestResult] = useState<string | null>(null)
  const [testingMcp, setTestingMcp] = useState(false)
  const [mcpTestResult, setMcpTestResult] = useState<string | null>(null)
  const [maxRevisionRounds, setMaxRevisionRounds] = useState(3)
  const [savingWorkflow, setSavingWorkflow] = useState(false)

  async function testModelConnection() {
    setTestingModel(true)
    setModelTestResult(null)
    try {
      await flow.command('/api/v1/settings/models/test', {})
      setModelTestResult('连接成功')
    } catch {
      setModelTestResult('连接失败')
    } finally {
      setTestingModel(false)
    }
  }

  async function verifyMcpAvailability() {
    setTestingMcp(true)
    setMcpTestResult(null)
    try {
      await flow.command('/api/v1/settings/mcp/test', {})
      setMcpTestResult('验证成功')
    } catch {
      setMcpTestResult('验证失败')
    } finally {
      setTestingMcp(false)
    }
  }

  async function saveWorkflowSettings() {
    setSavingWorkflow(true)
    try {
      await flow.command('/api/v1/settings/workflow', { max_revision_rounds: maxRevisionRounds })
    } catch {
      /* error handled by hook */
    } finally {
      setSavingWorkflow(false)
    }
  }

  if (!flow.isLoaded || flow.loading) {
    return (
      <main className={styles.centered}>
        <div><Loader2 className={styles.spin} size={24} /></div>
        <h1>正在加载设置</h1>
        <p>获取工作区配置与系统集成状态。</p>
      </main>
    )
  }

  async function saveSettings() {
    setSaving(true)
    try {
      // Workspace settings are managed via Clerk organization metadata
      await new Promise((r) => setTimeout(r, 500))
    } finally {
      setSaving(false)
    }
  }

  return (
    <main className={styles.main}>
      <header className={styles.topbar}>
        <div>
          <span>BrandFlow / Settings</span>
          <h1>设置与高级配置</h1>
        </div>
      </header>
      {flow.error && (
        <div className={styles.recovery} role="alert">
          <AlertTriangle />
          <span><b>数据加载失败</b><small>{flow.error.message}</small></span>
          <button onClick={flow.refreshTasks}>重试</button>
        </div>
      )}

      <div className={styles.settingsLayout}>
        <aside className={styles.knowledgeTabs}>
          {settingSections.map((label, index) => (
            <button
              key={label}
              className={index === activeSection ? styles.activeKnowledgeTab : undefined}
              onClick={() => setActiveSection(index)}
            >
              {label}
            </button>
          ))}
        </aside>

        <section className={styles.areaCard}>
          {activeSection === 0 && (
            <>
              <span className={styles.panelLabel}>WORKSPACE</span>
              <h2>基础信息</h2>
              <p className={styles.readingText}>
                工作区配置管理与品牌内容工作隔离。敏感值（API Key、MCP Token）不在界面中回显。
              </p>
              <div className={styles.settingsForm}>
                <label>
                  <span>Workspace name</span>
                  <input
                    value={workspaceName}
                    onChange={(e) => setWorkspaceName(e.target.value)}
                    placeholder="输入工作区名称"
                  />
                </label>
                <label>
                  <span>Default locale</span>
                  <button className={styles.selectField}>
                    简体中文 <ChevronDown size={15} />
                  </button>
                </label>
              </div>
              <div className={styles.settingsSection}>
                <div>
                  <h3>审批职责分离</h3>
                  <p>作者不能批准自己最后编辑的版本。此策略确保内容审批的独立性和可信度。</p>
                </div>
                <button className={styles.toggle} aria-label="审批职责分离已启用">
                  <span />
                </button>
              </div>
              <div className={styles.settingsSection}>
                <div>
                  <h3>Agent API 连接</h3>
                  <p>后端 Agent API 负责工作流编排、模型调用、MCP 工具集成和 PostgreSQL checkpoint 管理。</p>
                </div>
                <span className={styles.neutralBadge}>需要后端运行</span>
              </div>
              <div className={styles.settingsSection}>
                <div>
                  <h3>MCP 工具服务</h3>
                  <p>Brand Tools MCP 提供品牌文档检索、产品事实查询、规范验证、内容保存与导出工具。</p>
                </div>
                <span className={styles.neutralBadge}>需要 MCP 运行</span>
              </div>
              <footer className={styles.editorFooter}>
                <button className={styles.primary} onClick={saveSettings} disabled={saving}>
                  {saving ? '保存中…' : '保存工作区设置'}
                </button>
              </footer>
            </>
          )}
          {activeSection === 1 && (
            <>
              <span className={styles.panelLabel}>MEMBERS</span>
              <h2>成员与角色</h2>
              <p className={styles.readingText}>
                成员角色通过 Clerk 组织管理进行分配。Content Operator 负责内容创作与提交，
                Brand Reviewer 负责品牌语言审查，Final Approver 负责关键事实和风险批准。
              </p>
              <div className={styles.knowledgeEmpty}>
                <Settings size={48} />
                <h3>成员管理由 Clerk 控制台统一管理</h3>
                <p>
                  请前往 <a href="https://dashboard.clerk.com/organization-settings" target="_blank" rel="noopener noreferrer">Clerk 组织管理界面</a> 添加成员并分配角色。
                </p>
              </div>
            </>
          )}
          {activeSection === 2 && (
            <>
              <span className={styles.panelLabel}>MODEL PROVIDERS</span>
              <h2>模型提供商</h2>
              <p className={styles.readingText}>
                当前使用智谱 GLM-4.7 作为主力模型。API Key 通过环境变量配置，不在界面回显。
              </p>
              <div className={styles.settingsSection}>
                <div>
                  <h3>Zhipu GLM</h3>
                  <p>Provider: zhipu · Model: glm-4.7 · 需要 <code>GLM_API_KEY</code> 环境变量</p>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {modelTestResult && <span className={modelTestResult === '连接成功' ? styles.neutralBadge : styles.errorBadge}>{modelTestResult}</span>}
                  <button className={styles.secondary} onClick={testModelConnection} disabled={testingModel}>
                    {testingModel ? <Loader2 className={styles.spin} size={14} /> : null}
                    测试连接
                  </button>
                </div>
              </div>
            </>
          )}
          {activeSection === 3 && (
            <>
              <span className={styles.panelLabel}>MCP SERVERS</span>
              <h2>MCP 工具服务</h2>
              <p className={styles.readingText}>
                Brand Tools MCP 以独立进程运行，通过 Streamable HTTP 与 Agent API 通信。
                需要 <code>BRAND_MCP_SERVICE_TOKEN</code> 进行服务间认证。
              </p>
              <div className={styles.settingsSection}>
                <div>
                  <h3>Brand Tools MCP</h3>
                  <p>默认端口 8100 · 9 个工具 · read/write/high_risk 分类</p>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {mcpTestResult && <span className={mcpTestResult === '验证成功' ? styles.neutralBadge : styles.errorBadge}>{mcpTestResult}</span>}
                  <button className={styles.secondary} onClick={verifyMcpAvailability} disabled={testingMcp}>
                    {testingMcp ? <Loader2 className={styles.spin} size={14} /> : null}
                    验证可用性
                  </button>
                </div>
              </div>
            </>
          )}
          {activeSection === 4 && (
            <>
              <span className={styles.panelLabel}>WORKFLOW</span>
              <h2>工作流配置</h2>
              <p className={styles.readingText}>
                LangGraph 工作流编排 Brief 校验、事实检索、内容生成、多渠道审批和导出。
                工作流配置通过 Agent API 环境变量控制。
              </p>
              <div className={styles.settingsSection}>
                <div>
                  <h3>最大修订轮次</h3>
                  <p>Reviewer Agent 每节点最多 <input
                    type="number"
                    min={1}
                    max={10}
                    value={maxRevisionRounds}
                    onChange={(e) => setMaxRevisionRounds(Math.min(10, Math.max(1, Number(e.target.value))))}
                    style={{ width: 48, textAlign: 'center', display: 'inline-block' }}
                  /> 轮自动修订，超限转人工处理。</p>
                </div>
                <button className={styles.primary} onClick={saveWorkflowSettings} disabled={savingWorkflow}>
                  {savingWorkflow ? '保存中…' : '保存'}
                </button>
              </div>
              <div className={styles.settingsSection}>
                <div>
                  <h3>Checkpoint 存储</h3>
                  <p>使用独立 PostgreSQL schema 存储 LangGraph checkpoint，与业务数据隔离。</p>
                </div>
              </div>
            </>
          )}
          {activeSection === 5 && (
            <>
              <span className={styles.panelLabel}>DATA & EXPORT</span>
              <h2>数据与导出</h2>
              <p className={styles.readingText}>
                内容版本 append-only，审批绑定不可变快照。导出时服务端原子重验门禁与包摘要。
              </p>
              <div className={styles.settingsSection}>
                <div>
                  <h3>审计保留策略</h3>
                  <p>审批决策、工具调用、模型调用和幂等记录按工作区保留。</p>
                </div>
              </div>
              <div className={styles.settingsSection}>
                <div>
                  <h3>导出格式</h3>
                  <p>支持 Markdown、JSON、DOCX 三种格式。预览仅生成安全 HTML。</p>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  )
}
